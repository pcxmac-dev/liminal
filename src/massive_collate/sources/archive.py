"""What the public feeds' sources share (plugin API 1.6): a closed archive's or a keyless exchange's
DataSource (Archive), time spans in ms, the well-known crypto pairs the exchanges list and a crypto
exchange's settings (venue_view)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import PUBLIC_FEEDS
from ..errors import NotEntitled
from ..models import Instrument
from .base import DataSource
from .http import PublicClient

ET = ZoneInfo("America/New_York")
EXCHANGE_FRAMES = (("minute", 5), ("hour", 1))  # the crypto exchanges' own candles above a minute


def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def bounds(start, end, tz=timezone.utc) -> tuple[int, int]:
    """[start, end) in ms from dates (whole days, end inclusive) or datetimes."""
    lo = start if isinstance(start, datetime) else datetime.combine(start, datetime.min.time(), tz)
    hi = end if isinstance(end, datetime) else datetime.combine(end + timedelta(days=1), datetime.min.time(), tz)
    return ms(lo), ms(hi)


class Archive(DataSource):
    """A public feed's source (plugin API 1.6: the exchanges' and archives'): no ticks, no venues,
    reference from the other feeds."""

    archival = True  # a closed feed: fills history once per symbol, then is not asked again
    assets: tuple[str, ...] = ()

    def __init__(self, client: PublicClient):
        self.client = client

    @property
    def requests_made(self) -> int:
        return self.client.requests_made

    def covers(self, ticker: str) -> bool:
        return True

    def serves(self, asset: str) -> bool:
        return asset in self.assets

    def is_entitled(self, resolution: str, ticker: str, asset: str = "stock") -> bool:
        return asset in self.assets and resolution in self.resolutions(asset)  # public: no plan to probe

    def trade_pages(self, ticker, gte_ns=None, lt_ns=None, descending=False):
        raise NotEntitled(0, f"{self.name} has no ticks")

    def exchanges(self):
        return []

    def instrument(self, ticker: str, resolve_exchange: bool = True) -> Instrument:
        raise NotImplementedError(f"{self.name} has no reference data")


CRYPTO_PAIRS = {"BTCUSD", "ETHUSD", "LTCUSD", "BCHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "ADAUSD", "AVAXUSD",
                "LINKUSD", "DOTUSD", "XLMUSD", "UNIUSD", "BTCEUR", "ETHEUR", "ETHBTC"}


def crypto_pair(ticker: str) -> tuple[str, str]:
    t = ticker.upper().removeprefix("X:")
    for quote in ("USD", "EUR", "BTC"):
        if t.endswith(quote) and len(t) > len(quote):
            return t[:-len(quote)], quote
    return t, ""


def venue_view(name: str):
    """A crypto exchange feed's settings: all the history it holds, unless CRYPTO_VENUE_DAYS limits it."""
    tier, per_run, per_day = PUBLIC_FEEDS[name]

    def view(base):
        t = replace(tier, history_days=base.crypto_venue_days) if base.crypto_venue_days else tier
        return replace(base, tier=t, max_requests_per_run=per_run, max_requests_per_day=per_day, origin=base)

    return view
