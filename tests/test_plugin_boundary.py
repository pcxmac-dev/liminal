"""Every external data provider is in a plugin structure (the user, 2026-10-31): the app's own code
names no provider's host. What it sends anywhere goes through a plugin (sources/plugins/), which
declares its hosts, keys and limits; the app keeps only links people follow (never fetched)."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "massive_collate"
URL = re.compile(r"\b(?:https?|wss?)://([A-Za-z0-9.-]+)")

# links shown to people in the Federal view, never fetched (gov.LINKS, gov.RULES, the FOMC calendar)
FOR_PEOPLE = {
    ("gov.py", "www.finra.org"), ("gov.py", "www.sec.gov"), ("gov.py", "www.federalreserve.gov"),
    ("gov.py", "www.bls.gov"), ("gov.py", "www.ecfr.gov"),
    ("gui/server.py", "127.0.0.1"),  # this app's own address
}
# still to move into their plugins (emptied piece by piece)
STILL_TO_MOVE = {
    ("config.py", "api.massive.com"),
    ("sources/massive.py", "api.massive.com"),
    ("sources/alpaca.py", "data.alpaca.markets"), ("sources/alpaca.py", "api.alpaca.markets"),
    ("sources/alpaca.py", "paper-api.alpaca.markets"),
    ("gov.py", "www.federalregister.gov"),
}


def hosts_named() -> set[tuple[str, str]]:
    out = set()
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("sources/plugins/"):
            continue
        out |= {(rel, h.lower().rstrip(".")) for h in URL.findall(path.read_text(encoding="utf-8"))}
    return out


def test_no_providers_host_is_named_outside_the_plugins():
    found = hosts_named()
    assert found - FOR_PEOPLE - STILL_TO_MOVE == set(), "a provider's host outside sources/plugins/: move it into its plugin"
    assert STILL_TO_MOVE <= found  # moved: take it off the list


def test_the_datasets_and_the_live_streams_hosts_are_their_plugins():
    found = {h for _, h in hosts_named()}
    for host in ("mba.tuck.dartmouth.edu", "www.cftc.gov", "raw.githubusercontent.com",  # datasets (API 1.4)
                 "ws-feed.exchange.coinbase.com", "ws.bitstamp.net", "stream.data.alpaca.markets",  # streams (1.5)
                 "api.tiingo.com"):
        assert host not in found, host
