"""Tiingo's sources (tiingo.com): the stocks' daily bars from 1962, adjusted here for splits only (from
Tiingo's split factors, so they continue the other feeds' split-adjusted bars without a dividend seam),
and the currencies' 1-minute bars from 2020; on the app's keyless client with Tiingo's token."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterator

from ....errors import NotEntitled, SourceError
from ....models import Instrument
from ...archive import ET, Archive as _Archive, bounds as _bounds, ms as _ms
from ...base import Page
from ...http import PublicClient


def split_adjust(rows: list[dict]) -> list[dict]:
    """Tiingo's raw daily rows (oldest first, with splitFactor on split days) as split-adjusted bars:
    prices divided, volume multiplied, by the product of every later split. Dividends are not
    adjusted (the other feeds' bars are split-adjusted only)."""
    out = []
    factor = 1.0
    for r in reversed(rows):
        d = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).date()
        p = lambda k: (float(r[k]) / factor) if r.get(k) is not None else None  # noqa: E731
        out.append({"t": _ms(datetime(d.year, d.month, d.day, tzinfo=ET)), "o": p("open"), "h": p("high"),
                    "l": p("low"), "c": p("close"), "v": float(r["volume"]) * factor if r.get("volume") is not None else None,
                    "vw": None, "n": None})
        split = float(r.get("splitFactor") or 1.0)
        if split and split != 1.0:
            factor *= split  # this day's split applies to every earlier day
    return out[::-1]


class TiingoSource(_Archive):
    """US stock daily history with a free Tiingo key. One request returns a symbol's whole history
    (needed anyway: a split today changes the adjustment of every earlier day)."""

    name = "tiingo"
    assets = ("stock",)

    def __init__(self, client: PublicClient, has_key: bool):
        super().__init__(client)
        self.has_key = has_key
        self._history: dict[str, list[dict]] = {}

    def serves(self, asset: str) -> bool:
        return asset == "stock" and self.has_key

    def resolutions(self, asset: str) -> tuple[str, ...]:
        return ("day",) if asset == "stock" and self.has_key else ()

    def _all(self, ticker: str) -> list[dict]:
        sym = ticker.upper().replace(".", "-")
        if sym not in self._history:
            rows = self.client.get(f"/tiingo/daily/{sym}/prices", {"startDate": "1950-01-01", "format": "json",
                                                                   "resampleFreq": "daily"})
            if not isinstance(rows, list):
                raise SourceError(0, f"unexpected Tiingo answer for {sym}")
            self._history[sym] = split_adjust(rows)
        return self._history[sym]

    def bar_pages(self, ticker, start, end, timespan, multiplier=1, descending=False, asset="stock",
                  limit: int | None = None) -> Iterator[list[dict]]:
        if not self.has_key:
            raise NotEntitled(401, "TIINGO_API_KEY not set; nothing sent")
        if timespan != "day":
            raise NotEntitled(0, "Tiingo serves daily bars here")
        a, b = _bounds(start, end, ET)
        bars = [x for x in self._all(ticker) if a <= x["t"] < b]
        bars.sort(key=lambda x: -x["t"] if descending else x["t"])
        yield bars[:limit] if limit else bars


def tiingo_fx_pair(ticker: str) -> str:
    """Tiingo's name for a currency pair (eurusd): the watch row keeps Massive's (C:EURUSD)."""
    return ticker.upper().removeprefix("C:").lower()


class TiingoFxSource(_Archive):
    """Tiingo's forex: currency pairs' 1-minute bars (open, high, low, close; no volume) from
    2020-01-01, the earliest it serves ("End date must be >= 2020-01-01", asked 2026-10-28). One
    request gives at most about four days of minutes (5,772 bars for a whole year asked, 2026-10-28),
    so it is asked WINDOW_DAYS whole UTC days at a time, which always fit. A feed of its own
    (plugins/tiingo.py, FOREX) on the Tiingo key's limits; still trading, so kept up to date."""

    name = "tiingofx"
    assets = ("fx",)
    archival = False
    WINDOW_DAYS = 3  # 4,320 minutes: inside the ~5,772 one request gives
    START = date(2020, 1, 1)

    def __init__(self, client: PublicClient, has_key: bool):
        super().__init__(client)
        self.has_key = has_key

    def serves(self, asset: str) -> bool:
        return asset == "fx" and self.has_key

    def resolutions(self, asset: str) -> tuple[str, ...]:
        return ("minute",) if self.serves(asset) else ()

    def native_frames(self, asset: str) -> tuple[tuple[str, int], ...]:
        return ()  # its hours and days are built here from its minutes

    def bar_pages(self, ticker, start, end, timespan, multiplier=1, descending=False, asset="fx",
                  limit: int | None = None) -> Iterator[list[dict]]:
        if not self.has_key:
            raise NotEntitled(401, "TIINGO_API_KEY not set; nothing sent")
        if (timespan, multiplier) != ("minute", 1):
            raise NotEntitled(0, "Tiingo's forex is collected as 1-minute bars here")
        pair = tiingo_fx_pair(ticker)
        a, b = _bounds(start, end)
        a = max(a, _ms(datetime.combine(self.START, datetime.min.time(), timezone.utc)))
        day, step = 86_400_000, self.WINDOW_DAYS * 86_400_000
        windows, t = [], a // day * day  # whole UTC days: Tiingo is asked by date
        while t < b:
            windows.append((t, min(b, t + step)))
            t += step
        for lo, hi in (reversed(windows) if descending else windows):
            first = datetime.fromtimestamp(lo / 1000, timezone.utc).date()
            last = datetime.fromtimestamp((hi - 1) / 1000, timezone.utc).date()  # Tiingo's end date is inclusive
            rows = self.client.get("/tiingo/fx/prices", {"tickers": pair, "startDate": first.isoformat(),
                                                         "endDate": last.isoformat(), "resampleFreq": "1min"})
            if not isinstance(rows, list):
                raise SourceError(0, f"unexpected Tiingo answer for {pair}")
            bars = []
            for r in rows:
                ms = _ms(datetime.fromisoformat(r["date"]))
                if max(lo, a) <= ms < hi:
                    bars.append({"t": ms, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                                 "c": float(r["close"]), "v": None, "vw": None, "n": None})
            bars.sort(key=lambda x: -x["t"] if descending else x["t"])
            yield Page(bars[:limit] if limit else bars, window=(max(lo, a), hi))
            if limit:
                return

    def instrument(self, ticker: str, resolve_exchange: bool = True) -> Instrument:
        pair = tiingo_fx_pair(ticker).upper()
        return Instrument(ticker=pair, name=f"{pair[:3]}/{pair[3:]} on Tiingo", details={"venue": "Tiingo"})
