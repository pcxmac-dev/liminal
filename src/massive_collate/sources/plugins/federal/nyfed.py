"""The New York Fed: the federal funds target range, the effective federal funds rate and SOFR,
from its Markets Data API (documented for programs, no key). It publishes each business day:
SOFR at about 8:00 a.m. ET and the effective rate at about 9:00 a.m., read just after those, and
every four hours besides."""
from __future__ import annotations

from datetime import date, datetime, time

from ....sessions import ET
from ...publisher import Feed, Policy, Publisher, Read
from .release import API, VERSION


def moments(day: date) -> tuple[datetime, ...]:
    if day.weekday() >= 5:
        return ()
    return tuple(datetime.combine(day, t, tzinfo=ET) for t in (time(8, 5), time(9, 5)))


def parse_nyfed(data: dict) -> dict | None:
    """The New York Fed's newest reference rate: {series, day, value, lo, hi} (lo/hi: the
    federal funds target range, on EFFR only)."""
    rows = data.get("refRates") or []
    if not rows:
        return None
    r = rows[0]
    return {"series": r.get("type"), "day": r.get("effectiveDate"), "value": r.get("percentRate"),
            "lo": r.get("targetRateFrom"), "hi": r.get("targetRateTo")}


def parse(answer, feed) -> Read:
    """Its Markets Data API's answer: the newest rate (none without its day)."""
    rate = parse_nyfed(answer.json())
    return Read(rates=[rate] if rate and rate["day"] else [])


PUBLISHER = Publisher(
    version=VERSION, api=API, part_of="federal",  # the Federal plugin's release and contract (federal/__init__.py)
    name="nyfed", title="New York Fed", order=210,
    about="the federal funds target range, the effective federal funds rate and SOFR",
    feeds=(
        Feed("nyfed-effr", "New York Fed", "Effective federal funds rate and target range",
             "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json", "nyfed", every_minutes=240,
             parse=parse),
        Feed("nyfed-sofr", "New York Fed", "SOFR",
             "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json", "nyfed", every_minutes=240,
             parse=parse),
    ),
    policy=Policy(hosts=("markets.newyorkfed.org",), min_minutes=30, per_day=40,
                  terms="the Markets Data API, documented for programs; no key",
                  terms_url="https://markets.newyorkfed.org/static/docs/markets-api.html"),
    moments=moments,
)
