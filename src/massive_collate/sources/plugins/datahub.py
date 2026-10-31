"""Datahub's core datasets (datahub.io; github.com/datasets): free reference data kept as CSV files in
public GitHub repositories (ODC PDDL), each a git submodule of this repository (data/github/datasets/,
pinned commits) whose whole commit history is imported, each commit a published version; downloaded
from raw.githubusercontent.com where the submodule is not checked out. Datasets only
(Publisher.datasets); each is a mirror of someone else's data:
- the S&P 500's members with their GICS sector and sub-industry (s-and-p-500-companies): the market
  map's sectors for S&P 500 members;
- Robert J. Shiller's US stock market data (s-and-p-500): the S&P composite, dividends, earnings,
  CPI, rates and CAPE, monthly from 1871;
- the IMF's primary commodity prices (commodity-prices): 53 commodities and 10 indexes (2005 = 100),
  monthly 1980-2017, a mirror frozen since 2017, so an archive (closed once imported). IMF terms:
  personal, non-commercial use."""
from __future__ import annotations

import csv
import io
from datetime import date

from ..dataset import Dataset, Parsed, months_after, ms, num, text
from ..publisher import Policy, Publisher

RAW = "https://raw.githubusercontent.com/datasets/"


def shiller_date(raw: str) -> date:
    """A Shiller date: ISO (2026-09-01), year.month as in Shiller's own sheet (1871.01, 1871.1 for
    October) or a decimal year at mid-month as in the mirror's first versions (1871.04166 = January)."""
    raw = raw.strip()
    if "-" in raw:
        return date.fromisoformat(raw[:10])
    year, _, frac = raw.partition(".")
    if len(frac) == 2:
        month = int(frac)
    elif len(frac) == 1:
        month = int(frac) * 10
    else:
        month = min(12, int(float("0." + (frac or "0")) * 12) + 1)
    return date(int(year), month, 1)


def parse_shiller(url: str, blob: bytes) -> Parsed:
    """The mirror writes 0 where Shiller has no value yet (recent dividends, earnings, CPI; CAPE's
    first ten years): none of these series is ever really 0, so a 0 is left out as missing."""
    out = Parsed()
    rows = csv.DictReader(io.StringIO(text(blob, url)))
    for r in rows:
        d = shiller_date(r.pop("Date"))
        for k, v in r.items():
            if (x := num(v)) is not None and x != 0:
                out.values.append((k, ms(d), x))
    units = {"SP500": "index", "Dividend": "USD", "Earnings": "USD", "Consumer Price Index": "index",
             "Long Interest Rate": "%", "Real Price": "USD", "Real Dividend": "USD", "Real Earnings": "USD",
             "PE10": "ratio"}
    for k in {s for s, _, _ in out.values}:
        out.series[k] = (k, units.get(k, ""), "month")
    return out


def parse_commodities(url: str, blob: bytes) -> Parsed:
    out = Parsed()
    for r in csv.DictReader(io.StringIO(text(blob, url))):
        raw = r.pop("Date", None) or r.pop("date", None)
        if not raw:
            continue
        d = date.fromisoformat(raw[:10]) if "-" in raw else date(int(raw[:4]), int(raw[5:7] or 1), 1)
        for k, v in r.items():
            if (x := num(v)) is not None:
                out.values.append((k, ms(d), x))
    for k in {s for s, _, _ in out.values}:
        out.series[k] = (k, "index (2005 = 100)" if "Index" in k else "USD (nominal)", "month")
    return out


GICS_TO_MAP = {"Information Technology": "Technology", "Consumer Discretionary": "Consumer Cyclical",
               "Consumer Staples": "Consumer Defensive", "Financials": "Financial", "Health Care": "Healthcare",
               "Materials": "Basic Materials"}


def parse_constituents(url: str, blob: bytes) -> Parsed:
    out = Parsed()
    for r in csv.DictReader(io.StringIO(text(blob, url))):
        t = (r.get("Symbol") or "").strip().upper()
        if not t:
            continue
        sector = (r.get("GICS Sector") or r.get("Sector") or "").strip()  # older versions: Name, Sector
        out.constituents.append({"index": "S&P 500", "ticker": t, "name": (r.get("Security") or r.get("Name") or "").strip(),
                                 "sector": GICS_TO_MAP.get(sector, sector),
                                 "industry": (r.get("GICS Sub-Industry") or "").strip(),
                                 "added": (r.get("Date added") or "").strip() or None,
                                 "cik": (r.get("CIK") or "").strip() or None})
    return out


def _repo_file(repo: str, path: str, final: bool = False):
    """A file of a core dataset's repository: its raw download (when the submodule is not here)."""
    return lambda today: [(f"{RAW}{repo}/main/{path}", final)]


DATASETS = (
    Dataset("sp500-constituents", "S&P 500 members with GICS sector and sub-industry",
            "ODC PDDL (datasets/s-and-p-500-companies)", _repo_file("s-and-p-500-companies", "data/constituents.csv"),
            parse_constituents, 7, "sp500", "mirror",
            git=("datasets/s-and-p-500-companies", "data/constituents.csv"), index="S&P 500"),
    Dataset("shiller-us-market-monthly", "Shiller: S&P composite, dividends, earnings, CPI, rates, CAPE (from 1871)",
            "Robert J. Shiller (shillerdata.com) via datasets/s-and-p-500, ODC PDDL",
            _repo_file("s-and-p-500", "data/data.csv"), parse_shiller, 30, "shiller", "mirror",
            published=months_after(1, 2), git=("datasets/s-and-p-500", "data/data.csv")),
    Dataset("imf-commodities-monthly", "IMF primary commodity prices and indexes, monthly 1980-2017 (frozen mirror)",
            "IMF terms (personal, non-commercial use) via datasets/commodity-prices",
            _repo_file("commodity-prices", "data/commodity-prices.csv", final=True), parse_commodities, 30, "imf",
            "mirror", published=months_after(1, 5), git=("datasets/commodity-prices", "data/commodity-prices.csv")),
)

PUBLISHER = Publisher(
    version="1.0.0", api="1.4",  # its own release, and the contract it needs (datasets declared by it)
    name="datahub", title="Datahub", order=410, kind="mirror",
    about="core datasets on GitHub: S&P 500 members and sectors, Shiller's market data from 1871, "
          "IMF commodity prices (datasets)",
    feeds=(), datasets=DATASETS,
    policy=Policy(hosts=("github.com", "raw.githubusercontent.com"), min_minutes=60, per_day=40,
                  terms="ODC Public Domain Dedication and License (PDDL); each dataset's own source's "
                        "terms besides (the IMF's: personal, non-commercial use)",
                  terms_url="https://datahub.io/docs/core-data"),
)
