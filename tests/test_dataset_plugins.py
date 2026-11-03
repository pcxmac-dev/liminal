"""Every dataset is a plugin's (the user, 2026-10-31: "lets add all the different data sources to
plugins, respective of their source"; "every external data provider must be in a plugin structure"):
declared by the publisher plugin that puts it out (Publisher.datasets holding its Dataset, plugin API
1.4), read only from that plugin's hosts, and stopped by its pause."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from liminal_lib import datasets, killswitch, publications
from liminal_lib.sources import publishers, registry
from liminal_lib.sources.dataset import Dataset, Parsed
from liminal_lib.sources.publisher import Policy, Publisher
from liminal_lib.storage import Store

from .test_datasets import TODAY, _cot, _Resp, _Session, _zip


@pytest.fixture(autouse=True)
def no_submodules(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets, "REPOS", tmp_path / "no-repos")


def test_each_dataset_is_declared_by_the_plugin_of_its_source():
    by = {n: (d.publisher, d.provider) for n, d in datasets.DATASETS.items()}
    assert by == {
        # the CFTC's own report, in the Federal plugin
        "cftc-cot-legacy": ("cftc", "cftc"),
        # Ken French's library at Tuck (Dartmouth)
        "french-3-factors-daily": ("french", "french"), "french-3-factors-monthly": ("french", "french"),
        "french-5-factors-daily": ("french", "french"), "french-49-industries-daily": ("french", "french"),
        # Datahub's core datasets on GitHub; each keeps the file it always had (no stored data moves)
        "sp500-constituents": ("datahub", "sp500"), "shiller-us-market-monthly": ("datahub", "shiller"),
        "imf-commodities-monthly": ("datahub", "imf"),
    }
    assert registry.publisher_of("cftc") == "federal"
    pubs = publishers()
    assert pubs["french"].kind == "research" and pubs["datahub"].kind == "mirror" and not pubs["french"].feeds
    assert datasets.DATASETS["sp500-constituents"].index == "S&P 500"


def test_every_datasets_files_are_on_its_plugins_hosts():
    pubs = publishers()
    for ds in datasets.DATASETS.values():
        pub = pubs[ds.publisher]
        for url, _ in ds.files(TODAY):
            assert publications.url_refusal(pub, url) is None, (ds.name, url)
        if ds.git:
            assert datasets.GIT_HOST in pub.policy.hosts, ds.name


def _library(monkeypatch, pub: Publisher):
    """An installed plugin beside the real packages (the dataset libraries are packages now); the
    registry looks again (the built-ins, the packages installed, and this one)."""
    from importlib.metadata import entry_points

    real = list(entry_points(group=registry.ENTRY_POINTS))
    ep = SimpleNamespace(name=pub.name, value=f"pkg:{pub.name}", load=lambda: pub)
    monkeypatch.setattr(registry, "_entry_points", lambda: [*real, ep])
    registry.reload()


@pytest.fixture
def restore_registry():
    yield
    registry._providers = None


def test_a_file_off_its_plugins_hosts_is_never_requested(tmp_path, monkeypatch, restore_registry):
    stray = Dataset("stray-set", "Stray", "", lambda t: [("https://elsewhere.example/x.csv", False),
                                                          ("http://stray.example/y.csv", False),
                                                          ("https://www.finra.org/z.csv", False)],
                    lambda u, b: Parsed(values=[("X", 0, 1.0)]), 7, "stray", "research")
    _library(monkeypatch, Publisher("stray", "Stray", "", (), Policy(hosts=("stray.example", "www.finra.org")),
                                    api="1.4", datasets=(stray,)))
    session, log = _Session(lambda u: _Resp(200, b"x")), []
    with Store(tmp_path / "m.db") as store:
        assert datasets.fetch(store, ["stray-set"], today=TODAY, session=session, log=log.append) == {"stray-set": 0}
    assert session.calls == []  # another host, plain HTTP, a blocked site: none asked
    assert any("not one of its hosts" in m for m in log) and any("not HTTPS" in m for m in log)
    assert any("terms bar programs" in m for m in log)


def test_pausing_a_plugin_stops_its_datasets(tmp_path):
    session = _Session(lambda u: _Resp(200, _zip("annual.txt", _cot("2026-03-03"))))
    log = []
    with Store(tmp_path / "m.db") as store:
        publications.pause(store, "federal", True)  # the CFTC is Federal's: pausing Federal stops it
        datasets.fetch(store, ["cftc-cot-legacy"], today=TODAY, session=session, log=log.append)
        assert session.calls == [] and any("federal is paused" in m for m in log)
        publications.pause(store, "federal", False)
        publications.pause(store, "cftc", True)  # or the agency alone
        datasets.fetch(store, ["cftc-cot-legacy"], today=TODAY, session=session, log=log.append)
        assert session.calls == []
        publications.pause(store, "cftc", False)
        assert killswitch.killed(store, "cftc", "fetch") is None
        datasets.fetch(store, ["cftc-cot-legacy"], today=TODAY, session=session, log=log.append)
        assert session.calls  # resumed: fetched


def test_a_second_plugin_never_takes_a_datasets_name_or_file(monkeypatch, restore_registry):
    cot = datasets.DATASETS["cftc-cot-legacy"]
    same_name = replace(cot, provider="mine", publisher="")
    same_file = Dataset("my-own", "Mine", "", lambda t: [], lambda u, b: Parsed(), 7, "french", "research")
    for ds in (same_name, same_file):
        _library(monkeypatch, Publisher("copycat", "Copycat", "", (), Policy(hosts=("copy.example",)), api="1.4",
                                        datasets=(ds,), order=999))  # after the libraries (packages too): the first keeps the name
        assert "copycat" not in publishers()
        assert any("copycat" in why for _, why in registry.errors())
        assert datasets.DATASETS["cftc-cot-legacy"].publisher == "cftc"


def test_the_datasets_list_names_each_ones_plugin(tmp_path):
    with Store(tmp_path / "m.db") as store:
        rows = {r["name"]: r for r in datasets.status(store, date(2026, 10, 23))}
    cot = rows["cftc-cot-legacy"]  # in the Federal plugin, the CFTC's part of it
    assert (cot["plugin"], cot["pluginTitle"], cot["part"]) == ("federal", "Federal", "CFTC")
    assert rows["french-3-factors-daily"]["part"] is None
    assert rows["french-3-factors-daily"]["pluginTitle"] == "Ken French Data Library"
    assert rows["shiller-us-market-monthly"]["pluginTitle"] == "Datahub"


def test_the_plugins_view_lists_the_dataset_libraries_apart():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src" / "liminal_app" / "gui" / "static" / "plugins.js").read_text(encoding="utf-8")
    assert "const setsOnly = (p) => !p.feeds.length && !p.parts.length && p.datasets.length > 0;" in js
    assert "`<h4 class=\"ex-group\">Datasets</h4>${sets}`" in js  # a group of their own, after the news
    assert "${tile('Datasets', num(p.datasets.length), 'fetched with datasets fetch')}" in js
    assert "their files only from ${p.policy.hosts" in js
