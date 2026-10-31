"""Every live stream is its plugin's (the user, 2026-10-31: "every external data provider must be in a
plugin structure"): each declares its live feeds (Provider.live, plugin API 1.5): Coinbase's and
Bitstamp's trade streams, Alpaca's IEX stream, Tiingo's Blue Ocean nights (a poller); the recorder
(live.py) runs what the plugins declare and names no provider itself."""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from massive_collate import live
from massive_collate.config import load_settings
from massive_collate.sources import providers, registry
from massive_collate.sources.plugins.tiingo import BoatsPoller
from massive_collate.sources.stream import Live

ALPACA_KEYS = {"ALPACA_API_KEY_ID": "PKTESTKEY", "ALPACA_API_SECRET_KEY": "test-secret"}


def test_each_live_feed_is_declared_by_its_plugin():
    by = {n: (p.name, x.asset, x.partial) for n, (p, x) in registry.live_feeds().items()}
    assert by == {"bitstamp": ("bitstamp", "crypto", False), "coinbase": ("coinbase", "crypto", False),
                  "iex": ("alpaca", "stock", True), "tiingoboats": ("tiingo", "stock", True)}
    # named by the plugin whose keys they stream on, and one venue's share (with Alpaca's Blue Ocean)
    assert dict(live.LIVE_LABELS) == {"iex": "alpaca (iex)", "tiingoboats": "tiingo (blue ocean)"}
    assert set(live.PARTIAL_FEEDS) == {"iex", "boats", "tiingoboats"} and "boats" in live.PARTIAL_FEEDS
    assert providers()["boats"].partial and not providers()["alpaca"].partial


def test_the_recorder_runs_the_streams_the_plugins_declare(tmp_path):
    rec = live.Recorder(tmp_path / "m.db", coins=("BTC",), stock_keys=("PKTESTKEY", "test-secret"),
                        log=lambda *_: None, connect=lambda url: None)
    assert [s.source for s in rec.streams] == ["bitstamp", "coinbase", "iex"]
    assert [s.url for s in rec.streams] == ["wss://ws.bitstamp.net", "wss://ws-feed.exchange.coinbase.com",
                                            "wss://stream.data.alpaca.markets/v2/iex"]
    assert "test-secret" not in repr(rec)
    # the stock stream signs in with what its plugin says (Alpaca's keys), only where it is set up
    assert live.stock_keys(load_settings(env=ALPACA_KEYS, env_file=None)) == ("PKTESTKEY", "test-secret")
    assert live.stock_keys(load_settings(env={**ALPACA_KEYS, "LIVE_STOCKS": "off"}, env_file=None)) is None
    assert live.stock_keys(load_settings(env={}, env_file=None)) is None


def test_the_night_is_polled_by_its_plugin_only_where_set_up():
    assert live.night_poller(load_settings(env={"TIINGO_API_KEY": "k"}, env_file=None)) is None  # Starter
    poller = live.night_poller(load_settings(env={"TIINGO_API_KEY": "k", "TIINGO_PLAN": "power"}, env_file=None))
    assert isinstance(poller, BoatsPoller) and poller.source == "tiingoboats" and poller.account == "tiingo"
    assert poller.url("BRK.B") == "https://api.tiingo.com/boats/brk-b/prices"  # its provenance: the plugin's
    assert live.night_poller(load_settings(env={"TIINGO_API_KEY": "k", "TIINGO_PLAN": "power",
                                                "MASSIVE_OFFLINE": "1"}, env_file=None)) is None


@dataclass
class AcmeStream:
    source: str = "acmecoin"
    url: str = "wss://stream.acme.example"
    keepalive: str | None = None
    dynamic: bool = False
    asset: str = "crypto"
    authed: bool = True
    confirmed: frozenset = frozenset()

    def subscribe(self, coins):
        return []

    def change(self, add, drop):
        return []

    def parse(self, msg):
        return []


@pytest.fixture
def installed(monkeypatch):
    def install(*plugins):
        eps = [SimpleNamespace(name=p.name, value=f"pkg:{p.name}", load=lambda p=p: p) for p in plugins]
        monkeypatch.setattr(registry, "_entry_points", lambda: eps)
        return registry.reload()

    yield install
    registry._providers = None


def test_an_installed_plugins_stream_is_recorded_like_the_built_ins(tmp_path, installed):
    acme = replace(providers()["bitfinex"], name="acme", title="Acme", order=90, api="1.5",
                   live=(Live("acmecoin", "crypto", stream=AcmeStream),))
    installed(acme)
    assert "acmecoin" in live.crypto_streams()
    rec = live.Recorder(tmp_path / "m.db", coins=("BTC",), log=lambda *_: None, connect=lambda url: None)
    assert [s.source for s in rec.streams] == ["bitstamp", "coinbase", "acmecoin"]


def test_a_live_feed_is_never_another_plugins(installed):
    base = providers()["bitfinex"]
    thief = replace(base, name="thief", title="Thief", api="1.5", live=(Live("coinbase", "crypto", stream=AcmeStream),))
    squatter = replace(base, name="squatter", title="Squatter", api="1.5", live=(Live("massive", "crypto", stream=AcmeStream),))
    installed(thief, squatter)
    assert "thief" not in providers() and "squatter" not in providers()
    why = " ".join(w for _, w in registry.errors())
    assert "live feed 'coinbase'" in why and "live feed 'massive'" in why
    assert registry.live_feeds()["coinbase"][0].name == "coinbase"
