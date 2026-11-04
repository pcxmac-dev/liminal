"""Public historical sources as closed feeds: request shapes, split adjustment, empty history heads,
and closing (filled once, then never asked again)."""
from datetime import date, datetime, timedelta, timezone


from liminal_libs.collector import ET, sync
from plugin_integrator_alpaca import ALPACA_TIERS  # the plugin's plans
from liminal_libs.coverage import FeedProfile, ms, plan
from liminal_libs.sources import provider, supports
from liminal_libs.symbols import resolve

from .conftest import FakeSource

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=ET)


def _log(_):
    pass


def test_supports():
    assert supports("bitstamp", resolve("BTCUSD")) and not supports("bitstamp", resolve("AAPL"))
    assert supports("tiingo", resolve("AAPL")) and not supports("tiingo", resolve("EURUSD"))


class Archive(FakeSource):
    name = "bitstamp"
    archival = True

    def covers(self, ticker):
        return True

    def resolutions(self, asset):
        return ("minute",)


def _minutes(day, n=3, price=100.0):
    t0 = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    return [{"t": ms(t0 + timedelta(minutes=i)), "o": price, "h": price, "l": price, "c": price, "v": 1} for i in range(n)]


def _feeds():
    return {"alpaca": FeedProfile("alpaca", ALPACA_TIERS["basic"], frozenset({"crypto"}), 1),
            "bitstamp": FeedProfile("bitstamp", provider("bitstamp").tier, frozenset({"crypto"}), 2)}


def test_a_feeds_empty_history_head_is_left_to_others_and_the_archive_closes(store):
    for feed in ("alpaca", "bitstamp"):
        store.watch_spec(feed, resolve("BTCUSD"), "minute")
    # Alpaca was asked from 2016 but its history starts in 2021: that head is 'none' for it
    store.upsert_bars("alpaca", "BTCUSD", "minute", 1, _minutes(date(2021, 1, 1)))
    store.add_coverage("alpaca", "BTCUSD", "minute", ms(datetime(2016, 1, 1, tzinfo=ET)), ms(NOW))
    assert store.mark_empty_heads() == 1
    assert store.coverage("BTCUSD", "minute")["alpaca"][0][0] == _minutes(date(2021, 1, 1))[0]["t"]
    gaps = plan(store, _feeds()["bitstamp"], _feeds(), "BTCUSD", "crypto", "minute", date(2011, 8, 1), NOW)
    assert gaps and gaps[-1][1] == _minutes(date(2021, 1, 1))[0]["t"]  # up to where Alpaca's data begins
    archive = Archive(entitled=("minute",), bars={"minute": _minutes(date(2014, 6, 1)), "day": []})
    sync(archive, store, provider("bitstamp").tier, NOW, log=_log, feeds=_feeds())
    assert archive.bar_calls and all(e <= datetime(2021, 1, 1, 12, tzinfo=timezone.utc) for _, s, e, ts, _ in archive.bar_calls)
    row = next(w for w in store.watchlist("bitstamp") if w["ticker"] == "BTCUSD")
    assert row["closed_at"] is not None  # archive complete
    # closed: later runs send nothing at all, whatever the date
    again = Archive(entitled=("minute",), bars={"minute": _minutes(date(2014, 6, 2))})
    sync(again, store, provider("bitstamp").tier, NOW + timedelta(days=30), log=_log, feeds=_feeds())
    assert again.requests_made == 0 and not getattr(again, "bar_calls", [])


def test_closed_feeds_are_not_started_and_can_be_reopened(tmp_path, monkeypatch, capsys):
    from liminal_charts import cli
    from liminal_libs.storage import Store

    db = tmp_path / "m.db"
    monkeypatch.setenv("LIMINAL_DB", str(db))
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    settings = cli.load_settings(env_file=None)
    with Store(db):
        pass
    assert cli._feed_closed(settings, "tiingo")  # nothing watched: closed too
    with Store(db) as s:
        s.watch_spec("tiingo", resolve("AAPL"))
        s.set_closed("tiingo", "AAPL", NOW)
    assert cli._feed_closed(settings, "tiingo")
    assert not cli._feed_closed(settings, "bitstamp")  # an exchange: live
    assert not cli._feed_closed(settings, "massive")
    assert cli.main(["feeds"]) == 0
    out = capsys.readouterr().out
    assert "tiingo    closed feed (public archive)" in out and "closed: archive complete" in out
    assert cli.main(["feeds", "reopen", "tiingo", "AAPL"]) == 0
    assert not cli._feed_closed(settings, "tiingo")
