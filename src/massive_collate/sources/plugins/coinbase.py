"""Coinbase Exchange (coinbase.com): crypto minute and day bars from 2015, no key; the reference
exchange for crypto (composite.py)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from ...config import PUBLIC_FEEDS
from ...models import Instrument
from ..archive import CRYPTO_PAIRS, EXCHANGE_FRAMES, Archive as _Archive, bounds as _bounds, crypto_pair as _pair
from ..archive import venue_view
from ..base import Page
from ..registry import Provider, public_client
from ..stream import Live, ns, trade


class CoinbaseSource(_Archive):
    """Coinbase Exchange public candles: 300 per request, newest first (time, low, high, open, close,
    volume). Minutes without trades have no candle."""

    name = "coinbase"
    assets = ("crypto",)
    archival = False
    PAGE = 300
    EMPTY_RUN = 200  # empty windows in a row (1-minute candles: about six weeks) before the listing
    STEPS = {("minute", 1): 60, ("minute", 5): 300, ("minute", 15): 900, ("hour", 1): 3600, ("hour", 6): 21600,
             ("day", 1): 86400}

    def resolutions(self, asset: str) -> tuple[str, ...]:
        return ("minute",) if asset == "crypto" else ()

    def native_frames(self, asset: str) -> tuple[tuple[str, int], ...]:
        return EXCHANGE_FRAMES if asset == "crypto" else ()

    def covers(self, ticker: str) -> bool:
        return ticker.upper().removeprefix("X:") in CRYPTO_PAIRS

    def bar_pages(self, ticker, start, end, timespan, multiplier=1, descending=False, asset="crypto",
                  limit: int | None = None) -> Iterator[list[dict]]:
        if (timespan, multiplier) not in self.STEPS:
            raise ValueError(f"Coinbase granularities: {tuple(self.STEPS)}")
        base, quote = _pair(ticker)
        step = self.STEPS[(timespan, multiplier)]
        a, b = _bounds(start, end)
        a_s, b_s = -(-a // 1000) // step * step, b // 1000
        windows = []
        t = a_s
        while t < b_s:
            windows.append((t, min(b_s, t + self.PAGE * step)))
            t += self.PAGE * step
        empty = 0
        for lo, hi in (reversed(windows) if descending else windows):
            if descending and empty >= self.EMPTY_RUN:
                return  # this long with nothing, going back: before the pair was listed (the sync records the rest as empty)
            iso = lambda s: datetime.fromtimestamp(s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
            rows = self.client.get(f"/products/{base}-{quote}/candles",
                                   {"granularity": step, "start": iso(lo), "end": iso(hi - step)})
            empty = 0 if rows else empty + 1
            bars = [{"t": int(r[0]) * 1000, "o": float(r[3]), "h": float(r[2]), "l": float(r[1]), "c": float(r[4]),
                     "v": float(r[5]), "vw": None, "n": None} for r in rows or [] if lo <= int(r[0]) < hi]
            bars.sort(key=lambda x: -x["t"] if descending else x["t"])
            yield Page(bars[:limit] if limit else bars, window=(lo * 1000, hi * 1000))
            if limit:
                return

    def instrument(self, ticker: str, resolve_exchange: bool = True) -> Instrument:
        base, quote = _pair(ticker)
        return Instrument(ticker=base + quote, name=f"{base}/{quote} on Coinbase", details={"venue": "Coinbase"})


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
    version="1.2.0", api="1.6",  # its own release (its stream and client in it), and the contract it needs
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
