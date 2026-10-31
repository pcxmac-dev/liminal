"""Bitstamp (bitstamp.net): crypto minute bars from 2011, no key; an exchange of its own."""
from __future__ import annotations

import json
from dataclasses import dataclass

from ...config import PUBLIC_FEEDS
from ..public import BITSTAMP_PAIRS, BitstampSource
from ..registry import Provider, public_client
from ..stream import Live, Reconnect, trade

TIER, PER_RUN, PER_DAY = PUBLIC_FEEDS["bitstamp"]

@dataclass
class BitstampStream:
    """Bitstamp's public v2 feed: a live_trades channel per pair."""
    source: str = "bitstamp"
    url: str = "wss://ws.bitstamp.net"
    keepalive: str | None = json.dumps({"event": "bts:heartbeat"})
    dynamic: bool = False  # as CoinbaseStream
    asset: str = "crypto"
    authed: bool = True
    confirmed: frozenset = frozenset()

    def subscribe(self, coins) -> list[str]:
        self.confirmed = frozenset()
        return [json.dumps({"event": "bts:subscribe", "data": {"channel": f"live_trades_{c.lower()}usd"}})
                for c in coins]

    def change(self, add, drop) -> list[str]:
        return [json.dumps({"event": f"bts:{kind}", "data": {"channel": f"live_trades_{t.lower()}"}})
                for kind, pairs in (("unsubscribe", drop), ("subscribe", add)) for t in sorted(pairs)]

    def parse(self, msg: dict) -> list[tuple[str, dict]]:
        event = msg.get("event")
        if event == "bts:request_reconnect":
            raise Reconnect("bitstamp asked for a new connection")
        if event == "bts:error":
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            raise ConnectionError(f"bitstamp: {data.get('message') or msg}")
        if event in ("bts:subscription_succeeded", "bts:unsubscription_succeeded"):
            pair = str(msg.get("channel") or "").removeprefix("live_trades_").upper()
            self.confirmed = (self.confirmed | {pair}) if event == "bts:subscription_succeeded" else (self.confirmed - {pair})
            return []
        if event != "trade":
            return []
        d = msg["data"]
        ticker = msg["channel"].removeprefix("live_trades_").upper()
        tid = int(d["id"])
        return [(ticker, trade(int(d["microtimestamp"]) * 1000, tid, d.get("price_str", d["price"]),
                                d.get("amount_str", d["amount"]), tid))]


PLUGIN = Provider(
    version="1.1.0", api="1.5",  # its own release (its stream in it), and the contract it needs (Provider.live)
    name="bitstamp", title="Bitstamp",
    build=lambda settings, budget: BitstampSource(
        public_client("bitstamp", "https://www.bitstamp.net/api/v2", settings, budget)),
    assets=frozenset({"crypto"}), order=20, about="crypto minute bars from 2011 (no key)",
    tier=TIER, per_run=PER_RUN, per_day=PER_DAY, limits="8,000 requests per 10 minutes", kind="exchange",
    per_request={"day": BitstampSource.PAGE, "minute": BitstampSource.PAGE},
    streams={"crypto": "real time, public trades (no key), coins open on a chart"},
    live=(Live("bitstamp", "crypto", stream=BitstampStream),),
    carries=lambda spec: spec.ticker.upper() in BITSTAMP_PAIRS,
)
