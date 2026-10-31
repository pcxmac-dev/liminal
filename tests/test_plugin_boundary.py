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
                 "api.tiingo.com",
                 "api.massive.com", "data.alpaca.markets", "api.alpaca.markets"):  # the vendors' clients (1.6)
        assert host not in found, host


def _imports(path: Path) -> set[str]:
    """The modules a file imports, relative imports resolved (massive_collate.sources.http ...)."""
    import ast

    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    package = parts[:-1] if parts[-1] != "__init__" else parts[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = package[:len(package) - (node.level - 1)] if node.level else []
            mod = [*base, *(node.module.split(".") if node.module else [])]
            out |= {".".join(mod)} | {".".join([*mod, a.name]) for a in node.names}
    return out


def _plugin_of(module: str) -> str | None:
    bits = module.split(".")
    return bits[3] if bits[:3] == ["massive_collate", "sources", "plugins"] and len(bits) > 3 else None


def test_plugins_are_self_contained():
    """Each plugin keeps to itself (memory: plugins move to their own repositories): it imports no
    other plugin, and the app imports none by name (it reads them from the registry)."""
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        mine = _plugin_of("massive_collate." + rel[:-3].replace("/", "."))
        if rel.startswith("sources/plugins/") and rel != "sources/plugins/__init__.py":
            others = {_plugin_of(m) for m in _imports(path)} - {None, mine}
            assert not others, f"{rel} imports another plugin: {others}"
        elif not rel.startswith("sources/plugins/"):
            named = {m for m in _imports(path) if _plugin_of(m)}
            assert not named, f"{rel} imports a plugin by name: {named}"
