"""The CFTC: its Commitments of Traders, futures positioning each week (open interest; commercial,
non-commercial and small traders' positions), a dataset it declares (Publisher.datasets:
cftc-cot-legacy, the legacy futures-only report from 1986, fetched with `datasets fetch` and refreshed
weekly). Its rules and notices arrive through the Federal Register; its own news feeds are off (the
CFTC disabled them all in October 2026), so it has no feed to read here yet."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from ...dataset import Dataset, Parsed, at, day_of, ms, num, text
from ...publisher import Policy, Publisher
from .release import API, VERSION

CFTC = "https://www.cftc.gov/files/dea/history/"
COT_FIELDS = {
    "Open Interest (All)": "open_interest",
    "Noncommercial Positions-Long (All)": "noncommercial_long",
    "Noncommercial Positions-Short (All)": "noncommercial_short",
    "Noncommercial Positions-Spreading (All)": "noncommercial_spreading",
    "Commercial Positions-Long (All)": "commercial_long",
    "Commercial Positions-Short (All)": "commercial_short",
    "Nonreportable Positions-Long (All)": "small_long",
    "Nonreportable Positions-Short (All)": "small_short",
}
# A year's COT file is final only from this day of the next January: its last Tuesday's report
# comes out the Friday after (in January when the year ends late in the week, later still after a
# holiday), and a file closed before it is in would never have it.
COT_FINAL_FROM = (1, 15)


def parse_cot(url: str, blob: bytes) -> Parsed:
    """CFTC legacy futures-only report: one series per market code and field ('067651:open_interest')."""
    out = Parsed()
    for r in csv.DictReader(io.StringIO(text(blob, url))):
        code = (r.get("CFTC Contract Market Code") or "").strip()
        raw = (r.get("As of Date in Form YYYY-MM-DD") or "").strip()
        if not code or not raw:
            continue
        d = date.fromisoformat(raw)
        name = (r.get("Market and Exchange Names") or code).strip()
        for col, key in COT_FIELDS.items():
            v = num((r.get(col) or "").strip())
            if v is not None:
                series = f"{code}:{key}"
                out.values.append((series, ms(d), v))
                out.series.setdefault(series, (f"{name}: {key.replace('_', ' ')}", "contracts", "week"))
    return out


def cot_files(today: date) -> list[tuple[str, bool]]:
    # 1986-2016 in one archive, then a file a year; a past year's file is final once its last report is out
    return [(CFTC + "deacot1986_2016.zip", True)] + [
        (f"{CFTC}deacot{y}.zip", today >= date(y + 1, *COT_FINAL_FROM)) for y in range(2017, today.year + 1)]


def cot_published(ts: int) -> int:
    """The COT report as of a Tuesday is released that Friday at 15:30 ET (a holiday week a day or
    two later)."""
    d = day_of(ts)
    return at(d + timedelta(days=(4 - d.weekday()) % 7), 15, 30)


COT = Dataset("cftc-cot-legacy", "CFTC Commitments of Traders, legacy futures-only, weekly (from 1986)",
              "CFTC (public domain)", cot_files, parse_cot, 7, "cftc", "official", published=cot_published)

PUBLISHER = Publisher(
    version=VERSION, api=API, part_of="federal",  # the Federal plugin's release and contract (federal/__init__.py)
    name="cftc", title="CFTC", order=250,
    about="Commitments of Traders: futures positioning, weekly from 1986 (a dataset); its rules come "
          "through the Federal Register",
    feeds=(), datasets=(COT,),
    policy=Policy(hosts=("www.cftc.gov",), min_minutes=60, per_day=30,
                  terms="its reports are public domain (a U.S. government work); its news feeds are off "
                        "(October 2026)",
                  terms_url="https://www.cftc.gov/webpolicy/index.htm"),
)
