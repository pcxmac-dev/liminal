"""Public historical sources as closed feeds: request shapes, split adjustment, empty history heads,
and closing (filled once, then never asked again)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from liminal.collector import ET, sync
from liminal.config import ALPACA_TIERS, TIERS
from liminal.coverage import FeedProfile, ms, plan
from liminal.errors import NotEntitled
from liminal.sources import provider, supports
from liminal.sources.http import PublicClient
from liminal.sources.plugins.tiingo.client import TiingoSource, split_adjust
from liminal.symbols import resolve

from .conftest import FakeResponse, FakeSession, FakeSource

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=ET)


def _log(_):
    pass


def _client(responses):
    session = FakeSession(responses)
    return PublicClient("https://x.test/api", session=session, sleep=lambda s: None), session


def test_tiingo_is_split_adjusted_only_and_needs_a_key():
    rows = [{"date": "2020-08-27T00:00:00.000Z", "open": 500.0, "high": 510.0, "low": 490.0, "close": 500.0,
             "volume": 100, "splitFactor": 1.0, "divCash": 0.8},
            {"date": "2020-08-31T00:00:00.000Z", "open": 127.0, "high": 131.0, "low": 126.0, "close": 129.0,
             "volume": 400, "splitFactor": 4.0, "divCash": 0.0}]
    out = split_adjust(rows)
    assert out[0]["c"] == 125.0 and out[0]["v"] == 400.0  # before the 4:1 split: /4 prices, x4 volume
    assert out[1]["c"] == 129.0 and out[1]["v"] == 400.0  # the split day is already in new shares
    assert out[0]["t"] == ms(datetime(2020, 8, 27, tzinfo=ET))
    client, session = _client([FakeResponse(200, rows)])
    keyed = TiingoSource(PublicClient("https://api.tiingo.com", headers={"Authorization": "Token K"},
                                      session=session, sleep=lambda s: None), has_key=True)
    bars = next(keyed.bar_pages("BRK.B", date(2020, 1, 1), date(2020, 12, 31), "day"))
    assert len(bars) == 2 and session.calls[0][0].endswith("/tiingo/daily/BRK-B/prices")
    assert session.calls[0][2]["Authorization"] == "Token K"
    keyless = TiingoSource(_client([])[0], has_key=False)
    assert not keyless.serves("stock") and keyless.resolutions("stock") == ()
    with pytest.raises(NotEntitled):
        next(keyless.bar_pages("AAPL", date(2020, 1, 1), date(2020, 1, 2), "day"))


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
    from liminal import cli
    from liminal.storage import Store

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


def test_the_exchanges_send_five_minute_and_hourly_candles():
    from liminal.sources.plugins.bitfinex import BitfinexSource
    from liminal.sources.plugins.coinbase import CoinbaseSource

    t0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    lo, hi = datetime.fromtimestamp(t0, timezone.utc), datetime.fromtimestamp(t0 + 3600, timezone.utc)
    client, session = _client([FakeResponse(200, [])] * 2)
    list(CoinbaseSource(client).bar_pages("X:BTCUSD", lo, hi, "hour", 1))
    assert session.calls[0][1]["granularity"] == 3600
    client, session = _client([FakeResponse(200, [])])
    list(BitfinexSource(client).bar_pages("X:BTCUSD", lo, hi, "minute", 5))
    assert "/candles/trade:5m:tBTCUSD/hist" in session.calls[0][0]
    with pytest.raises(ValueError):
        list(CoinbaseSource(client).bar_pages("X:BTCUSD", lo, hi, "minute", 3))  # not a Coinbase granularity
