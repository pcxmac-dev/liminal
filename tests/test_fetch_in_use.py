"""Fetching only while the app, or a command, is in use (the user, 2026-11-01): a feed's run is the
host feed-NAME and the closed months' copy the host history (cli.cmd_host), stopped at the next
request once let go; `sync` by hand holds them and waits; the chart app holds them while awake
(gui/server.py sync_pass) and lets them go when it goes quiet; nothing is scheduled any more."""
from __future__ import annotations

import threading
import time
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from liminal import cli, host as hosting
from liminal.config import load_settings
from liminal.gui.server import ChartApp
from liminal.storage import Store


class FakeAttachment:
    def __init__(self, name, lives=1):
        self.name, self.lives, self.detached = name, lives, False

    def alive(self):
        if self.detached:
            return False
        self.lives -= 1
        return self.lives >= 0

    def detach(self):
        self.detached = True


class FakeHost:
    made: list = []

    def __init__(self, name, db_path, log=print):
        self.name = name
        self.stop = threading.Event()
        FakeHost.made.append(self)

    def serve(self, work, secure=None, handle=None):
        work(self.stop)
        return "its work ended"


def _settings(tmp_path):
    return replace(load_settings(env={}, env_file=None), db_path=tmp_path / "liminal.db")


def test_a_feed_host_runs_its_pass_and_stops_at_its_next_request_once_let_go(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(hosting, "Host", FakeHost)
    monkeypatch.setattr(cli, "Logger", lambda path: (lambda m: None))
    FakeHost.made.clear()
    runs: list[Namespace] = []
    monkeypatch.setattr(cli, "_sync", lambda args, s: runs.append(args) or (0, 1))
    assert cli.cmd_host(Namespace(name="feed-alpaca"), settings) == 0
    (run,), (h,) = runs, FakeHost.made
    assert h.name == "feed-alpaca" and run.source == "alpaca" and run.fetch_only and not run.all_sources
    assert run._stop is h.stop  # the host's stop event reaches the run's requests
    assert cli.cmd_host(Namespace(name="feed-nothing"), settings) == 2
    # the run's should_stop: once the host's clients are gone, this run stops at its next request
    with Store(settings.db_path) as store:
        stop = threading.Event()
        check = cli._pause_check(store, stop=stop)
        assert check() is None
        stop.set()
        assert check() == cli.HOST_STOPPED


def test_the_history_host_ends_after_the_month_in_hand_once_let_go(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(hosting, "Host", FakeHost)
    monkeypatch.setattr(cli, "Logger", lambda path: (lambda m: None))
    FakeHost.made.clear()
    runs: list[Namespace] = []
    real_cmd_history = cli.cmd_history
    monkeypatch.setattr(cli, "cmd_history", lambda args, s: runs.append(args) or 0)
    assert cli.cmd_host(Namespace(name="history"), settings) == 0
    (run,), (h,) = runs, FakeHost.made
    assert h.name == "history" and run.action == "run" and run.budget == cli.HISTORY_BUDGET_S and run._stop is h.stop
    # cmd_history's own stop check: the host's event, as well as a halt
    from liminal import proc
    from liminal.storage import history

    seen: list = []

    def run_months(conns, history_dir, log, budget_s, code, stop):
        seen.append(stop())
        run._stop.set()
        seen.append(stop())
        return True
    monkeypatch.setattr(history, "run", run_months)
    monkeypatch.setattr(history, "available", lambda: True)
    monkeypatch.setattr(proc, "acquire", lambda path: True)
    monkeypatch.setattr(proc, "release", lambda path: None)
    monkeypatch.setattr(cli, "_background_priority", lambda: None)
    assert real_cmd_history(run, settings) == 0 and seen == [False, True]


def test_sync_by_hand_holds_the_feeds_runs_and_waits_for_them(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lines: list[str] = []
    runs = {"alpaca": FakeAttachment("alpaca", lives=2), "coinbase": FakeAttachment("coinbase", lives=1)}
    monkeypatch.setattr(cli, "start_feed", lambda name, db_path: runs.get(name))
    monkeypatch.setattr(cli, "_fetch_gov", lambda s, log, force=False: lines.append("gov"))
    monkeypatch.setattr(cli, "_stores_pass", lambda s, log, history=True: lines.append("stores") or FakeAttachment("history", 1))
    monkeypatch.setattr(cli.time, "sleep", lambda s: lines.append("waited"))
    profiles = {n: Namespace(assets=("crypto",)) for n in ("alpaca", "coinbase")}
    monkeypatch.setattr(cli, "feed_profiles", lambda s: profiles)
    monkeypatch.setattr(cli, "providers", lambda: ["alpaca", "coinbase", "massive"])
    assert cli.dispatch(settings, lines.append) == 2
    assert lines.count("waited") >= 1 and lines.index("gov") < lines.index("stores") < lines.index("waited")
    assert any("waiting for 3 run(s)" in line for line in lines) and not any(a.detached for a in runs.values())
    # Ctrl+C while waiting: every run let go, each stops at its next request
    held = [FakeAttachment("a", lives=99), FakeAttachment("b", lives=99)]

    def interrupted(s):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli.wait_for_hosts(held, lines.append)
    assert all(a.detached for a in held) and lines[-1].startswith("sync: let go")
    cli.wait_for_hosts([None, 1], lines.append)  # nothing to hold: nothing waited for


def test_the_chart_app_fetches_while_in_use_and_lets_the_runs_go_when_quiet(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    attached: list[tuple[str, Path]] = []
    spawned: list[list[str]] = []

    def attach_or_start(name, db_path, log=print):
        attached.append((name, Path(db_path)))
        return FakeAttachment(name, lives=99)
    monkeypatch.setattr(hosting, "attach_or_start", attach_or_start)
    profiles = {n: Namespace(assets=("crypto",)) for n in ("alpaca", "coinbase")}
    monkeypatch.setattr("liminal.sources.feed_profiles", lambda s: profiles)
    monkeypatch.setattr(cli, "history_due", lambda s: True)
    with Store(settings.db_path, check_same_thread=False) as store:
        app = ChartApp(store, settings=settings)
        monkeypatch.setattr(app, "_spawn", lambda args: spawned.append(args) or Namespace(pid=1, poll=lambda: 0))
        assert app.sync_due()
        out = app.sync_pass()
        assert set(out["started"]) == {"alpaca", "coinbase"} and set(app._feed_hosts) == {"alpaca", "coinbase"}
        assert [n for n, _ in attached] == ["feed-alpaca", "feed-coinbase", "history"]
        assert all(p == settings.db_path for _, p in attached) and app._history_host is not None
        assert spawned[-1][1:] == ["-m", "liminal", "sync", "--extras-only"] and not app.sync_due()
        assert app.sync_pass()["started"] == [] and len(attached) == 3  # held already: nothing more attached
        held = list(app._feed_hosts.values()) + [app._history_host]
        assert app.release() and all(a.detached for a in held) and app._feed_hosts == {} and app._history_host is None
        # a page back: the loop takes up again, and a resume asks for a pass at once
        with app.using():
            assert app._sync_stop is not None and not app._sync_stop.is_set()
            app._last_pass = None
            out = app.set_fetching({"paused": False})
            assert out["started"] is True
            end = time.monotonic() + 5
            while len(attached) < 6 and time.monotonic() < end:
                time.sleep(0.02)
            assert [n for n, _ in attached[3:]] == ["feed-alpaca", "feed-coinbase", "history"]
        app.close()
        assert app._sync_stop.is_set()


def test_nothing_is_scheduled_and_the_extras_run_alone(tmp_path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    assert cli.cmd_schedule(Namespace(action="install", every_hours=1), settings) == 2
    assert "nothing is scheduled" in capsys.readouterr().out
    done: list[str] = []
    monkeypatch.setattr(cli, "_fetch_gov", lambda s, log, force=False: done.append("gov"))
    monkeypatch.setattr(cli, "_stores_pass", lambda s, log, history=True: done.append(f"stores history={history}"))
    monkeypatch.setattr(cli, "after_sync", lambda args, s: done.append("after"))
    monkeypatch.setattr(cli, "_sync", lambda args, s: done.append("feeds") or (0, 0))
    assert cli.cmd_sync(Namespace(extras_only=True, all_sources=True, tickers=None, fetch_only=False), settings) == 0
    assert done == ["gov", "stores history=False", "after"]  # the feeds are the app's to hold, not this process's
