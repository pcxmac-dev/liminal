"""A retired symbol (no longer listed): its stored data is there to look at, nothing new is asked
for, and a source that still has its history completes it once (the user, 2026-11-02: "lets not
request retired stocks data then", "but i should be able to look at the stock data if i want",
"if however, the retired stock data is still available on any of the sources, complete the
retired symbol")."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from liminal_lib import collector
from liminal_lib.config import load_settings
from liminal_app.gui.server import ChartApp
from liminal_lib.storage import Store

RETIRED_ON = date(2026, 10, 27)


def _app(store, settings=None):
    return ChartApp(store, settings=settings, fetcher=SimpleNamespace(wake_up=lambda: None, ask_pass=lambda: None, status=lambda: {}))


def test_opening_a_retired_symbol_asks_for_nothing_once_its_history_is_complete(tmp_path, monkeypatch):
    store = Store(tmp_path / "m.db", check_same_thread=False)
    store.watch("massive", ["ELME"], "minute", exchange="XNYS")
    store.set_retired("ELME", RETIRED_ON)
    floor = collector.history_floor(load_settings(env={"MASSIVE_API_KEY": "k"}, env_file=None).for_source("massive").tier,
                                    date(2026, 11, 2), "stock")
    store.set_backfilled("massive", "ELME", floor)  # its history complete to the plan's floor ...
    store.set_synced("massive", "ELME", datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc))  # ... and synced after its last day
    app = _app(store, load_settings(env={"MASSIVE_API_KEY": "k"}, env_file=None))
    out = app.priority("ELME")
    assert out["state"] == "retired" and out["retiredOn"] == "2026-10-27" and out["feeds"] == ["massive"]
    assert store.request_rows() == [] and collector.priority_requests(store) == {}  # nothing asked of the fetcher
    # its data is still served: the chart opens it as any symbol (the API answers; the page keeps the pick)
    assert app.symbols()[0]["ticker"] == "ELME" and app.symbols()[0]["data"]["state"] == "retired"
    store.close()


def test_a_retired_symbol_a_source_still_has_history_for_is_completed_once(tmp_path, monkeypatch):
    store = Store(tmp_path / "m.db", check_same_thread=False)
    for feed in ("massive", "alpaca"):
        store.watch(feed, ["ELME"], "minute", exchange="XNYS")
    store.set_retired("ELME", RETIRED_ON)
    store.set_synced("massive", "ELME", datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc))
    # Alpaca never synced it: its history of the symbol (up to its last listed day) is still to come
    app = _app(store, load_settings(env={"MASSIVE_API_KEY": "k", "ALPACA_API_KEY_ID": "a", "ALPACA_API_SECRET_KEY": "s"},
                                    env_file=None))
    out = app.priority("ELME")
    assert out["state"] == "started" and "alpaca" in out["need"]
    (req,) = store.request_rows()
    assert req["symbol"] == "ELME" and req["by"] == "chart"  # the fetcher completes it on the feeds that still have it
    store.close()
