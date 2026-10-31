"""Coinbase Exchange (coinbase.com): crypto minute and day bars from 2015, no key; the reference
exchange for crypto (composite.py)."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from ...config import PUBLIC_FEEDS
from ..public import CRYPTO_PAIRS, CoinbaseSource
from ..registry import Provider, public_client
from ..stream import Live, ns, trade


def venue_view(name: str):
    """A crypto exchange feed's settings: all the history it holds, unless CRYPTO_VENUE_DAYS limits it."""
    tier, per_run, per_day = PUBLIC_FEEDS[name]

    def view(base):
        t = replace(tier, history_days=base.crypto_venue_days) if base.crypto_venue_days else tier
        return replace(base, tier=t, max_requests_per_run=per_run, max_requests_per_day=per_day, origin=base)

    return view


@dataclass
class CoinbaseStream:
    """Coinbase Exchange's public feed: the matches channel (every trade) and a heartbeat a second.
    `dynamic`: its coins are those open on a chart (`change` while connected), not all LIVE_COINS."""
    source: str = "coinbase"
    url: str = "wss://ws-feed.exchange.coinbase.com"
    keepalive: str | None = None
    dynamic: bool = False
    asset: str = "crypto"
    authed: bool = True  # nothing to authenticate: symbols can change as soon as it is connected
    confirmed: frozenset = frozenset()  # the pairs the server says it streams (dynamic)

    def subscribe(self, coins) -> list[str]:
        self.confirmed = frozenset()
        return [json.dumps({"type": "subscribe", "product_ids": [f"{c}-USD" for c in coins],
                            "channels": ["matches", "heartbeat"]})] if coins else []

    def change(self, add, drop) -> list[str]:
        """Messages taking pairs (BTCUSD) off and onto the connection."""
        return [json.dumps({"type": kind, "product_ids": [f"{t[:-3]}-USD" for t in sorted(pairs)],
                            "channels": ["matches", "heartbeat"]})
                for kind, pairs in (("unsubscribe", drop), ("subscribe", add)) if pairs]

    def parse(self, msg: dict) -> list[tuple[str, dict]]:
        kind = msg.get("type")
        if kind == "error":  # e.g. "Failed to subscribe" "subscription limit reached": a refusal
            raise ConnectionError(f"coinbase: {msg.get('message')} {msg.get('reason') or ''}".strip())
        if kind == "subscriptions":  # the whole list after each change
            self.confirmed = frozenset(p.replace("-", "") for ch in msg.get("channels") or []
                                       if isinstance(ch, dict) and ch.get("name") == "matches"
                                       for p in ch.get("product_ids") or [])
            return []
        if kind not in ("match", "last_match"):
            return []
        ticker = msg["product_id"].replace("-", "")
        tid = int(msg["trade_id"])
        return [(ticker, trade(ns(msg["time"]), tid, msg["price"], msg["size"], tid))]


PLUGIN = Provider(
    version="1.1.0", api="1.5",  # its own release (its stream in it), and the contract it needs (Provider.live)
    name="coinbase", title="Coinbase",
    build=lambda settings, budget: CoinbaseSource(
        public_client("coinbase", "https://api.exchange.coinbase.com", settings, budget)),
    assets=frozenset({"crypto"}), order=30, about="crypto minute and day bars from 2015 (no key); live trades",
    tier=PUBLIC_FEEDS["coinbase"][0], limits="10 requests per second per IP (public endpoints)",
    kind="exchange", reference_for=frozenset({"crypto"}),
    per_request={"day": CoinbaseSource.PAGE, "minute": CoinbaseSource.PAGE},
    streams={"crypto": "real time, public trades (no key), coins open on a chart"},
    live=(Live("coinbase", "crypto", stream=CoinbaseStream),),
    view=venue_view("coinbase"),
    rate=lambda settings: (8, 1.0),  # 10 a second per address: a minute's window let 300 go in a burst
    carries=lambda spec: spec.ticker.upper() in CRYPTO_PAIRS,
)
