"""The live recorder as a resident host (host.py, `liminal host live`): started by the chart app
when a chart has a symbol open, let go once nothing has been open for a while, and never started
by the hourly sync any more (the user, 2026-11-01: no processes or open databases when the app is
not in use). Nothing here starts a process: the host and the recorder are stand-ins."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from liminal import cli, host as hosting, live
from liminal.config import load_settings
from liminal.gui.server import ChartApp
from liminal.storage import Store


def until(cond, within=5.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class FakeAttachment:
    def __init__(self):
        self.detached = False

    def alive(self):
        return not self.detached

    def detach(self):
        self.detached = True


def _settings(tmp_path):
    return replace(load_settings(env={"LIVE_CRYPTO": "BTC"}, env_file=None), db_path=tmp_path / "liminal.db")


def test_the_host_command_runs_the_recorder_until_its_clients_are_gone_and_frees_its_locks(tmp_path, monkeypatch):
    """`liminal host live`: the recorder under a Host, stopping on the host's stop event; the locks
    released after the recorder's own final flush (its run returns once stopped)."""
    settings = _settings(tmp_path)
    events: list[str] = []

    class FakeRecorder:
        def __init__(self, stop):
            self.stop = stop

        def run(self):
            self.stop.wait(5)
            events.append("run ended: flushed")
    made: dict = {}

    def make_recorder(s, locks, stop=None):
        made["locks"], made["stop"] = locks, stop
        return FakeRecorder(stop)
    monkeypatch.setattr(cli, "make_recorder", make_recorder)
    monkeypatch.setattr(live, "take_locks", lambda db: ["lock-a", "lock-b"])
    monkeypatch.setattr(live, "release_locks", lambda locks: events.append(f"released {locks}"))
    monkeypatch.setattr(cli, "Logger", lambda path: (lambda m: events.append(m)))

    class FakeHost:
        def __init__(self, name, db_path, log=print):
            made["host"] = (name, db_path)
            self.stop = threading.Event()

        def serve(self, work, secure=None, handle=None):
            self.stop.set()  # the clients went
            work(self.stop)
            secure()
            return "no client attached"
    monkeypatch.setattr(hosting, "Host", FakeHost)
    assert cli.cmd_host(SimpleNamespace(name="live"), settings) == 0
    assert made["host"] == ("live", settings.db_path) and made["locks"] == ["lock-a", "lock-b"]
    assert made["stop"] is not None  # the host's stop event is the recorder's
    assert events == ["run ended: flushed", "released ['lock-a', 'lock-b']"]  # secured, then the locks


def test_the_host_command_runs_nothing_with_live_recording_off_or_another_recorder_up(tmp_path, monkeypatch):
    logged: list[str] = []
    monkeypatch.setattr(cli, "Logger", lambda path: logged.append)
    off = replace(load_settings(env={"LIVE_CRYPTO": "off"}, env_file=None), db_path=tmp_path / "liminal.db")
    assert cli.cmd_host(SimpleNamespace(name="live"), off) == 0 and "live recording is off" in logged[-1]
    monkeypatch.setattr(live, "take_locks", lambda db: None)
    assert cli.cmd_host(SimpleNamespace(name="live"), _settings(tmp_path)) == 0
    assert "already running" in logged[-1]
    assert cli.cmd_host(SimpleNamespace(name="nothing"), _settings(tmp_path)) == 2


def test_the_sync_no_longer_starts_the_recorder_and_live_start_says_so(capsys):
    src = Path(cli.__file__).read_text(encoding="utf-8")
    sync = src.split("def _sync(", 1)[1].split("\ndef ", 1)[0]
    assert "start_detached(" not in sync and "live.attach(" not in sync  # the chart app attaches it, nobody else
    assert not hasattr(live, "start_detached")
    assert cli.cmd_live(SimpleNamespace(action="start"), _settings(Path("."))) == 0
    assert "while a chart has a symbol open" in capsys.readouterr().out


def test_the_chart_app_attaches_the_recorder_while_a_symbol_is_open_and_lets_it_go_after(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    attachments: list[FakeAttachment] = []

    def attach(db_path, log=print):
        attachments.append(FakeAttachment())
        return attachments[-1]
    monkeypatch.setattr(live, "attach", attach)
    with Store(settings.db_path) as store:
        app = ChartApp(store, settings=settings)
        assert app.live_wanted()
        now = 1_700_000_000_000
        app.note_open("AAPL", now)
        assert until(lambda: app._live is not None) and len(attachments) == 1
        assert app.attach_live() and len(attachments) == 1  # attached already: kept
        assert not app.settle_live(now + 1000) and not attachments[0].detached  # AAPL is open
        assert app.settle_live(now + live.OPEN_FRESH_MS + 1) and attachments[0].detached  # nothing open for a while
        assert app._live is None and not app.settle_live(now + live.OPEN_FRESH_MS + 2)  # once
        app.note_open("MSFT", now + live.OPEN_FRESH_MS + 60_000)  # opened again: attached again (a new host if need be)
        assert until(lambda: len(attachments) == 2) and app._live is attachments[1]
        attachments[1].detached = True  # the host went away by itself (say it was ended)
        assert app.attach_live() and len(attachments) == 3  # not alive: attached anew
        app.settle_live(now + 10 * live.OPEN_FRESH_MS)


def test_the_chart_app_leaves_the_recorder_alone_when_live_recording_is_off_or_it_reads_only(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(live, "attach", lambda db_path, log=print: calls.append(db_path))
    off = replace(load_settings(env={"LIVE_CRYPTO": "off"}, env_file=None), db_path=tmp_path / "liminal.db")
    with Store(off.db_path) as store:
        app = ChartApp(store, settings=off)
        assert not app.live_wanted()
        app.note_open("AAPL", 1_700_000_000_000)
        time.sleep(0.2)
        assert calls == [] and app._live is None
    ro = replace(_settings(tmp_path), read_only=True)
    with Store(ro.db_path) as store:
        app = ChartApp(store, settings=ro)
        assert not app.live_wanted()
