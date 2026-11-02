"""The chart app quiet (gui/server.py: using, release, watch_quiet): with no page in touch for a
while every store is closed, the recorder and MongoDB's keeper let go and the sampler ended; the
next request opens the stores again. Nothing runs for nobody: the start's extras wait for the first
page, and a hidden tab asks for nothing (activity.js). The user, 2026-11-01: no open databases or
processes when the app is not in use."""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from liminal import mongo
from liminal.config import load_settings
from liminal.gui import server
from liminal.gui.server import ChartApp
from liminal.storage import Store

from .test_frontend_guards import _function, _js


def until(cond, within=5.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture
def app(tmp_path, monkeypatch):
    settings = replace(load_settings(env={}, env_file=None), db_path=tmp_path / "liminal.db")
    monkeypatch.setattr(mongo, "detach", lambda: None)
    store = Store(settings.db_path, check_same_thread=False)
    a = ChartApp(store, settings=settings)
    yield a
    a.close()


def _closed(store) -> bool:
    try:
        store.conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_released_the_app_closes_every_store_and_a_request_opens_them_again(app, monkeypatch):
    let_go: list[str] = []
    monkeypatch.setattr(mongo, "detach", lambda: let_go.append("mongo"))

    class Live:
        def alive(self):
            return True

        def detach(self):
            let_go.append("live")
    app._live = Live()
    monitor = app.monitor  # made: it samples until the app is released
    stores = [app.store, app.engine.store, app._panel_store, app._status_store, app._deps_store,
              app._datasets_store, app._symbols_store, app._profiles_store]
    assert app.release() is True and app.quiet
    assert all(_closed(s) for s in stores)
    assert let_go == ["live", "mongo"] and app._live is None and monitor._stop.is_set() and app._monitor is None
    assert app.release() is False  # once
    with app.using():  # a page back: the stores open again, new ones
        assert not app.quiet
        assert app.store is not stores[0] and not _closed(app.store) and not _closed(app.engine.store)
        assert app.activity({})["feeds"] is not None  # a request works
    assert not app.quiet and app.release() is True  # and quiet again when let go
    app.close()  # already quiet: nothing more


def test_the_app_is_not_released_while_a_request_is_under_way(app):
    inside, go = threading.Event(), threading.Event()

    def request():
        with app.using():
            inside.set()
            go.wait(5)
    t = threading.Thread(target=request, daemon=True)
    t.start()
    assert inside.wait(5) and app.release() is False  # a request under way: not now
    go.set()
    t.join(5)
    assert app.release() is True


def test_the_watcher_releases_the_app_once_no_page_has_been_in_touch(app, monkeypatch):
    monkeypatch.setattr(ChartApp, "QUIET_CHECK_SECONDS", 0.05)
    monkeypatch.setenv("LIMINAL_QUIET_SECONDS", "0.3")
    assert app.quiet_seconds() == 0.3
    stop = threading.Event()
    threading.Thread(target=app.watch_quiet, args=(stop,), daemon=True).start()
    time.sleep(0.5)
    assert not app.quiet  # no page ever came: nothing to release (the stores wait for the first)
    with app.using():
        pass
    assert until(lambda: app.quiet, within=3)  # the page gone for the quiet time
    with app.using():  # back
        assert not app.quiet
        time.sleep(0.5)
        assert not app.quiet  # in touch all along: a request under way
    assert until(lambda: app.quiet, within=3)
    stop.set()


def test_the_starts_extras_run_at_the_first_page_not_at_the_start(app):
    ran: list[str] = []
    app.on_wake(lambda: ran.append("rescan"))
    app.on_wake(lambda: ran.append("warm"))
    assert ran == [] and app._monitor is None  # nothing for nobody
    with app.using():
        pass
    assert ran == ["rescan", "warm"] and app._monitor is not None and app._monitor._thread is not None
    with app.using():
        pass
    assert ran == ["rescan", "warm"]  # once
    src = Path(server.__file__).read_text(encoding="utf-8")
    serve = src.split("\ndef serve(", 1)[1].split("\ndef ", 1)[0]
    assert "app.on_wake(lambda: threading.Timer(RESCAN_AFTER_START_S, rescan_now).start())" in serve
    assert "app.on_wake(lambda: threading.Thread(target=world.warm, daemon=True).start())" in serve
    assert "app.monitor.start()" not in serve and "threading.Thread(target=app.watch_quiet" in serve
    assert "app.close()" in serve  # the app ending: its stores closed, its hosts let go


def test_every_request_runs_under_using():
    src = Path(server.__file__).read_text(encoding="utf-8")
    handler = src.split("def make_handler(", 1)[1]
    for method in ("do_POST", "do_PUT", "do_DELETE", "do_GET"):
        body = handler.split(f"def {method}(self) -> None:", 1)[1].split("\n        def ", 1)[0]
        assert "with app.using():" in body, method


def test_a_hidden_tab_asks_for_nothing_and_asks_at_once_when_back():
    act = _js("activity.js")
    poll = _function(act, "pollOnce") if "function pollOnce(" in act else act.split("async function pollOnce(", 1)[1].split("\n  }\n", 1)[0]
    assert "if (document.hidden) {" in poll and poll.index("document.hidden") < poll.index("fetch(`/api/activity")
    assert "document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });" in act
