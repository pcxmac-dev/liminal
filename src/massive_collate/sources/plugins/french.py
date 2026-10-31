"""Kenneth R. French Data Library (Tuck School of Business, Dartmouth): the Fama/French factors and
the 49 industry portfolios, daily and monthly from 1926 (1963 for the 5 factors), returns in percent.
Datasets only (Publisher.datasets): each a zipped CSV from the library's own server, fetched with
`datasets fetch` and again every 30 days. The library updates its files about two months after a
month ends, so a first import's values are dated the 15th of the second month after theirs."""
from __future__ import annotations

from datetime import date

from ..dataset import Dataset, Parsed, months_after, ms, num, text
from ..publisher import Policy, Publisher

FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
LICENCE = "Kenneth R. French Data Library"


def parse_french(url: str, blob: bytes, section: str | None = None, unit: str = "%") -> Parsed:
    """A French data library CSV: the first table (or the one after a heading containing
    `section`): a header row then rows of YYYYMMDD / YYYYMM and values in percent."""
    lines = text(blob, url).splitlines()
    out = Parsed()
    start = 0
    if section:
        start = next((i for i, l in enumerate(lines) if section.lower() in l.lower()), 0)
    header, freq = None, None
    for line in lines[start:]:
        cells = [c.strip() for c in line.split(",")]
        if header is None:
            if len(cells) > 1 and cells[0] == "" and any(cells[1:]):
                header = cells
            continue
        if not cells[0].isdigit():
            if out.values:
                break  # the end of the first table
            continue
        key = cells[0]
        if len(key) == 8:
            d, freq = date(int(key[:4]), int(key[4:6]), int(key[6:])), "day"
        elif len(key) == 6:
            d, freq = date(int(key[:4]), int(key[4:]), 1), "month"
        else:
            break  # the annual table that follows the monthly one
        for name, cell in zip(header[1:], cells[1:]):
            v = num(cell)
            if v is None or v in (-99.99, -999):
                continue  # the library's missing-value markers
            out.values.append((name, ms(d), v))
    for name in (header or [])[1:]:
        out.series[name] = (name, unit, freq or "")
    return out


def _library(name: str, title: str, file: str, parse=parse_french) -> Dataset:
    return Dataset(name, title, LICENCE, lambda today: [(FRENCH + file, False)], parse, 30, "french", "research",
                   published=months_after(2, 15))


DATASETS = (
    _library("french-3-factors-daily", "Fama/French 3 factors, daily (from 1926)",
             "F-F_Research_Data_Factors_daily_CSV.zip"),
    _library("french-3-factors-monthly", "Fama/French 3 factors, monthly (from 1926)", "F-F_Research_Data_Factors_CSV.zip"),
    _library("french-5-factors-daily", "Fama/French 5 factors (2x3), daily (from 1963)",
             "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"),
    _library("french-49-industries-daily", "49 industry portfolios, value-weighted daily returns (from 1926)",
             "49_Industry_Portfolios_daily_CSV.zip",
             lambda url, blob: parse_french(url, blob, section="Average Value Weighted Returns")),
)

PUBLISHER = Publisher(
    version="1.0.0", api="1.4",  # its own release, and the contract it needs (datasets declared by it)
    name="french", title="Ken French Data Library", order=400, kind="research",
    about="Fama/French 3 and 5 factors and 49 industry portfolios, daily and monthly from 1926 (datasets)",
    feeds=(), datasets=DATASETS,
    policy=Policy(hosts=("mba.tuck.dartmouth.edu",), min_minutes=60, per_day=20,
                  terms="the library's files are free to download for research; cite the library",
                  terms_url="https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"),
)
