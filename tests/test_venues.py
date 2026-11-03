"""The Exchanges view (venues.py): every tracked venue with its products and its insight."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from liminal_lib.config import load_settings
from liminal_app.gui import venues
from liminal_lib.sessions import ET, MarketCalendar
from liminal_lib.sources import feed_profiles
from liminal_lib.storage import Store
from liminal_lib.symbols import resolve

KEYS = {"MASSIVE_API_KEY": "k", "ALPACA_API_KEY_ID": "i", "ALPACA_API_SECRET_KEY": "s"}
NOW = datetime(2026, 10, 27, 11, 0, tzinfo=ET)  # a Tuesday, the regular session


def _store(tmp_path) -> Store:
    s = Store(tmp_path / "m.db")
    s.update_directory("massive", "stock", [
        {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "XNAS", "type": "CS", "kind": "stock"},
        {"ticker": "KO", "name": "Coca-Cola", "exchange": "XNYS", "type": "CS", "kind": "stock"},
        {"ticker": "CL", "name": "Colgate-Palmolive", "exchange": "XNYS", "type": "CS", "kind": "stock"}], date(2026, 10, 27))
    s.update_directory("massive", "future", [
        {"ticker": "ES", "name": "E-mini S&P 500", "exchange": "XCME", "type": "us_index", "kind": "future"},
        {"ticker": "CL", "name": "Crude oil", "exchange": "XNYM", "type": "crude_oil", "kind": "future"}], date(2026, 10, 27))
    for feed in ("massive", "alpaca"):
        s.watch_spec(feed, resolve("AAPL::XNAS"))
        s.watch_spec(feed, resolve("KO::XNYS"))
    s.watch_spec("boats", resolve("AAPL::XNAS"))
    s.watch_spec("massive", resolve("ES1!"))
    s.watch_spec("massive", resolve("CL1!"))
    s.watch_spec("coinbase", resolve("BTCUSD"))
    s.watch_spec("massive", resolve("IXIC"))
    s.set_synced("massive", "AAPL", NOW - timedelta(hours=3))
    s.set_backfilled("massive", "AAPL", date(2003, 9, 10))
    s.set_synced("massive", "ES1!", NOW - timedelta(days=5))
    for day, close in ((date(2026, 10, 23), 100.0), (date(2026, 10, 26), 103.0)):
        s.save_market_snapshot("massive", day, [{"T": "AAPL", "c": close, "v": 1e6, "vw": close},
                                                {"T": "KO", "c": 70.0 if day.day == 23 else 69.3, "v": 1e6, "vw": 70.0}])
    return s


def test_every_tracked_venue_with_its_state_products_and_insight(tmp_path):
    feeds = feed_profiles(load_settings(env=KEYS, env_file=None))
    with _store(tmp_path) as s:
        out = venues.summary(s, MarketCalendar(), feeds, now=NOW)
    by = {v["id"]: v for v in out["venues"]}
    assert [v["id"] for v in out["venues"]] == ["XNYS", "XNAS", "BOATS", "XCME", "XNYM", "INDEX", "CRYPTO:coinbase"]
    assert by["XNAS"]["group"] == "Stock exchanges" and by["XNAS"]["state"] == "open" and by["XNAS"]["products"] == 1
    assert sorted(by["XNAS"]["feeds"]) == [("alpaca", 1), ("massive", 1)] and by["BOATS"]["feeds"] == [("boats", 1)]
    assert by["BOATS"]["state"] == "closed" and by["BOATS"]["next"]["at"].startswith("2026-10-27T20:00")
    assert by["XNAS"]["collected"]["filled"] == 1 and by["XNAS"]["collected"]["fresh"] == 1
    assert by["XNYS"]["collected"] == {"filled": 0, "synced": 0, "fresh": 0, "never": 1, "newest": None}
    # futures by their product's exchange (CL is crude oil on NYMEX here, not Colgate-Palmolive)
    assert by["XCME"]["group"] == "CME Group" and by["XNYM"]["sectors"] == [("crude_oil", 1)]
    assert by["XCME"]["collected"]["fresh"] == 0  # synced five days ago
    assert by["CRYPTO:coinbase"]["name"] == "Coinbase" and by["CRYPTO:coinbase"]["state"] == "open"
    assert by["XNAS"]["movers"] == {"up": [{"ticker": "AAPL", "pct": 3.0}], "down": []}
    assert by["XNYS"]["movers"]["down"] == [{"ticker": "KO", "pct": -1.0}]


def test_vix_futures_are_the_cboe_futures_exchanges_venue(tmp_path):
    feeds = feed_profiles(load_settings(env=KEYS, env_file=None))
    with _store(tmp_path) as s:
        s.update_directory("cboefutures", "future", [{"ticker": "VX", "name": "Cboe Volatility Index (VIX) futures",
                                                      "exchange": "XCBF", "type": "volatility", "kind": "future"}], date(2026, 10, 27))
        s.watch_spec("cboefutures", resolve("VX1!"), "day")
        out = venues.summary(s, MarketCalendar(), feeds, now=NOW)
    by = {v["id"]: v for v in out["venues"]}
    assert by["XCBF"]["name"] == "Cboe Futures Exchange" and by["XCBF"]["group"] == "Cboe Futures" and by["XCBF"]["asset"] == "future"
    assert by["XCBF"]["products"] == 1 and by["XCBF"]["feeds"] == [("cboefutures", 1)] and by["XCBF"]["state"] == "open"
    assert "FUT-OTHER" not in by and out["groups"].index("Cboe Futures") == out["groups"].index("CME Group") + 1
    assert [v["id"] for v in out["venues"] if v["group"] in ("CME Group", "Cboe Futures")] == ["XCME", "XNYM", "XCBF"]


def test_a_stock_exchange_abroad_is_a_venue_of_its_own(tmp_path):
    feeds = feed_profiles(load_settings(env=KEYS, env_file=None))
    with _store(tmp_path) as s:
        s.update_directory("twse", "stock", [{"ticker": "2330.TW", "name": "TSMC", "exchange": "XTAI", "type": "CS",
                                              "kind": "stock"}], date(2026, 10, 27))
        s.watch_spec("twse", resolve("2330.TW"))
        s.watch_spec("tiingo", resolve("600519.SS"))
        out = venues.summary(s, MarketCalendar(), feeds, now=NOW)
        taiwan = venues.products(s, feeds, "XTAI")
    by = {v["id"]: v for v in out["venues"]}
    assert by["XTAI"]["name"] == "Taiwan Stock Exchange" and by["XTAI"]["group"] == "Stock exchanges"
    assert by["XTAI"]["timezone"] == "Asia/Taipei" and by["XTAI"]["products"] == 1 and by["XTAI"]["feeds"] == [("twse", 1)]
    assert by["XTAI"]["state"] == "open" and by["XTAI"]["until"].startswith("2026-10-27T12:00")  # 23:00 in Taipei
    assert by["XSHG"]["name"] == "Shanghai Stock Exchange" and by["XSHG"]["delivery"] == []
    assert [v["id"] for v in out["venues"]][:3] == ["XNYS", "XNAS", "BOATS"]  # the US venues keep their places
    assert "US-OTHER" not in by
    (p,) = taiwan["products"]
    assert p["ticker"] == "2330.TW" and p["name"] == "TSMC" and taiwan["group"] == "Stock exchanges"


def test_the_delivery_scheme_behind_each_venue(tmp_path):
    from liminal_lib import sourcing

    feeds = feed_profiles(load_settings(env=KEYS, env_file=None))
    with _store(tmp_path) as s:
        out = venues.summary(s, MarketCalendar(), feeds, sourcing.standing(s, feeds, NOW), now=NOW)
    by = {v["id"]: v for v in out["venues"]}
    assert {e["job"] for e in by["XNAS"]["delivery"]} == {"day", "minute"}  # the free plan: no seconds
    assert by["BOATS"]["delivery"] == [{"job": "minute", "start": "2016-01-01", "end": None, "sources": ["boats"],
                                       "unique": True}]


def test_a_venues_products_for_the_middle_column(tmp_path):
    feeds = feed_profiles(load_settings(env=KEYS, env_file=None))
    with _store(tmp_path) as s:
        out = venues.products(s, feeds, "XNAS")
        none = venues.products(s, feeds, "NOWHERE")
    (p,) = out["products"]
    assert p["ticker"] == "AAPL" and p["name"] == "Apple Inc." and sorted(p["feeds"]) == ["alpaca", "massive"]
    assert p["filled"] and p["change"] == 3.0 and out["group"] == "Stock exchanges"
    assert none["products"] == []


def test_the_chart_app_answers_for_the_exchanges_view(tmp_path):
    from liminal_app.gui.server import ChartApp

    with _store(tmp_path) as s:
        app = ChartApp(s, settings=load_settings(env=KEYS, env_file=None))
        first = app.venues()
        assert app.venues() is first  # kept VENUES_TTL_S
        assert {v["id"] for v in first["venues"]} >= {"XNAS", "XCME"}
        assert app.venue("XCME")["products"][0]["ticker"] == "ES1!"


def test_the_page_has_its_rail_icon_and_view():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src" / "liminal_app" / "gui" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'id="railExchanges"' in html and 'id="viewExchanges"' in html and 'src="venues.js"' in html
    assert "scales:" in (static / "icons.js").read_text(encoding="utf-8")
    assert "exchanges: 'exchanges'" in (static / "panels.js").read_text(encoding="utf-8")
