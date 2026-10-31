"""The Federal Register: rules, proposed rules and notices of the SEC (with FINRA's and the
exchanges' rule filings, tagged), the CFTC, the Fed and the Treasury, from its documented JSON API
(no key). It publishes each business day at 6:00 a.m. ET, read just after, and every three hours
besides. FINRA's own site is never read (its terms bar programs): its rule filings arrive here."""
from __future__ import annotations

from datetime import date, datetime, time

from ....sessions import ET
from ...publisher import Feed, Policy, Publisher, Read
from .release import API, VERSION

FEDREG_AGENCIES = {  # the Federal Register's agency slugs -> the name shown
    "securities-and-exchange-commission": "SEC", "commodity-futures-trading-commission": "CFTC",
    "federal-reserve-system": "Fed", "treasury-department": "Treasury",
}
FINRA_TITLE = "Financial Industry Regulatory Authority"
FEDREG_URL = ("https://www.federalregister.gov/api/v1/documents.json?per_page=100&order=newest"
              + "".join(f"&conditions[agencies][]={a}" for a in FEDREG_AGENCIES)
              + "".join(f"&fields[]={f}" for f in ("title", "type", "publication_date", "html_url", "agencies",
                                                    "document_number")))


def parse_fedreg(data: dict) -> list[dict]:
    """The Federal Register's documents: the agency shown (SEC, CFTC, Fed, Treasury), the
    document type, and FINRA's and the exchanges' rule filings tagged."""
    out = []
    for d in data.get("results") or []:
        slugs = [a.get("slug") for a in d.get("agencies") or [] if a.get("slug")]
        agency = next((FEDREG_AGENCIES[s] for s in slugs if s in FEDREG_AGENCIES), "Federal Register")
        title = " ".join((d.get("title") or "").split())
        tags = []
        if FINRA_TITLE in title:
            tags.append("FINRA")
        elif title.startswith("Self-Regulatory Organizations"):
            tags.append("SRO")
        day = d.get("publication_date")
        out.append({"id": d.get("document_number") or d.get("html_url") or title, "agency": agency, "title": title,
                    "url": d.get("html_url"), "published": f"{day}T00:00:00+00:00" if day else None,
                    "kind": (d.get("type") or "document").lower(), "tags": tags})
    return out


def parse(answer, feed) -> Read:
    """Its JSON API's answer: the documents, as items."""
    return Read(items=parse_fedreg(answer.json()))


def moments(day: date) -> tuple[datetime, ...]:
    return () if day.weekday() >= 5 else (datetime.combine(day, time(6, 5), tzinfo=ET),)


PUBLISHER = Publisher(
    version=VERSION, api=API, part_of="federal",  # the Federal plugin's release and contract (federal/__init__.py)
    name="fedreg", title="Federal Register", order=240,
    about="rules and notices of the SEC (FINRA's and the exchanges' filings), the CFTC, the Fed and the Treasury",
    feeds=(Feed("fedreg", "Federal Register", "Rules and notices: SEC (FINRA, exchanges), CFTC, Fed, Treasury",
                FEDREG_URL, "fedreg", every_minutes=180, parse=parse),),
    policy=Policy(hosts=("www.federalregister.gov",), min_minutes=30, per_day=30,
                  terms="the Federal Register API, documented for programs; no key",
                  terms_url="https://www.federalregister.gov/developers/documentation/api/v1"),
    moments=moments,
)
