"""The fetch queue (storage/queue.py), each plugin's own fetching (plugin API 1.9: sources/fetching.py,
runner.py), the Fetcher as the queue and each plugin's fetching on its page (gui/queue.py). The user,
2026-10-31: "each plugin will manage it's own fetching", "the fetcher will then just show the queue of
all resources being downloaded like symbols", "the plugin status will be available in the plugins::
plugin page"."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from liminal import cli, collector, config, killswitch, publications, runner
from liminal.collector import StopRun, sync
from liminal.config import load_settings
from liminal_plugin_massive import TIERS
from liminal.gov import GovDB
from liminal.sources import registry
from liminal.sources.fetching import Fetched, Fetcher, Job
from liminal.sources.publisher import Policy, Publisher
from liminal.storage import Store

from .conftest import FakeSource
from .test_collector import NOW as SYNC_NOW
from .test_publications import Site, pub, reader

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _store():
    return Store(":memory:")


# -- the queue --------------------------------------------------------------------------------------
def test_the_queue_hands_out_each_plugins_resources_in_their_order_and_keeps_what_they_got():
    with _store() as s:
        s.queue_put("acme", "acme", "bars", [{"key": "SPY", "priority": 1}, {"key": "AAPL", "priority": 0},
                                             {"key": "LATER", "not_before": NOW + timedelta(hours=1)}], now=NOW)
        s.queue_put("other", "other", "news", [{"key": "x"}], now=NOW)
        first = s.queue_claim("acme", now=NOW)
        assert first["key"] == "AAPL" and first["state"] == "running" and first["attempts"] == 1  # its own, by priority
        s.queue_end("acme", "acme", "bars", "AAPL", rows=120, requests=3, detail="minute: 120 rows", now=NOW)
        assert s.queue_claim("acme", now=NOW)["key"] == "SPY"
        assert s.queue_claim("acme", now=NOW) is None  # LATER's time has not come; other's is not acme's
        assert s.queue_claim("acme", now=NOW + timedelta(hours=2))["key"] == "LATER"
        rows = {r["key"]: r for r in s.queue_rows()}
        assert (rows["AAPL"]["state"], rows["AAPL"]["rows"], rows["AAPL"]["requests"]) == ("done", 120, 3)
        assert [r["state"] for r in s.queue_rows()][:3] == ["running", "running", "waiting"]  # running first
        assert s.queue_counts()["plugins"] == {"acme": {"done": 1, "running": 2}, "other": {"waiting": 1}}
        assert s.queue_counts()["kinds"] == {"bars": {"done": 1, "running": 2}, "news": {"waiting": 1}}


def test_a_resource_asked_again_waits_again_but_one_being_fetched_stays_running():
    with _store() as s:
        s.queue_start("acme", "acme", "bars", "SPY", now=NOW)
        s.queue_put("acme", "acme", "bars", [{"key": "SPY", "detail": "new data"}, {"key": "QQQ"}], now=NOW)
        assert {r["key"]: r["state"] for r in s.queue_rows()} == {"SPY": "running", "QQQ": "waiting"}
        s.queue_end("acme", "acme", "bars", "SPY", now=NOW)
        s.queue_put("acme", "acme", "bars", [{"key": "SPY"}], now=NOW)
        assert {r["key"]: r["state"] for r in s.queue_rows()}["SPY"] == "waiting"
        s.queue_end("acme", "acme", "bars", "SPY", detail="kept", now=NOW)
        s.queue_put("acme", "acme", "bars", [{"key": "SPY", "detail": "new"}], now=NOW, replace=False)
        assert {r["key"]: r["detail"] for r in s.queue_rows()}["SPY"] == "kept"  # on the queue already: as it was


def test_a_run_settles_its_part_and_one_that_died_leaves_its_rows_waiting():
    with _store() as s:
        s.queue_put("acme", "acme", "bars", [{"key": k} for k in ("A", "B", "C")], now=NOW)
        s.queue_put("acme", "boats", "bars", [{"key": "A"}], now=NOW)
        assert s.queue_settle("acme", "acme", "bars", ["B"], now=NOW) == 2  # A and C: nothing left to fetch
        states = {(r["part"], r["key"]): (r["state"], r["detail"]) for r in s.queue_rows()}
        assert states[("acme", "A")] == ("done", "up to date") and states[("acme", "B")][0] == "waiting"
        assert states[("boats", "A")][0] == "waiting"  # another part's untouched
        s.queue_start("acme", "acme", "bars", "B", now=NOW)
        assert s.queue_reset("acme", "acme", "bars") == 1
        assert {r["key"]: r["state"] for r in s.queue_rows() if r["part"] == "acme"}["B"] == "waiting"


def test_an_end_state_is_one_of_the_queues():
    with _store() as s, pytest.raises(ValueError):
        s.queue_end("acme", "acme", "bars", "SPY", "running")


# -- a plugin's own fetching (API 1.9) --------------------------------------------------------------
def _plugin(name: str, plan, fetch, kinds=("document",)) -> Publisher:
    return Publisher(name, name.title(), "", (), Policy(), fetcher=Fetcher(plan, fetch, kinds), api="1.9")


@pytest.fixture
def installed(monkeypatch):
    def install(*plugins):
        eps = [SimpleNamespace(name=p.name, value=f"pkg:{p.name}", load=lambda p=p: p) for p in plugins]
        monkeypatch.setattr(registry, "_entry_points", lambda: eps)
        return registry.reload()

    yield install
    registry._providers = None


def test_a_plugins_worker_puts_its_plan_on_the_queue_and_fetches_its_own_jobs(installed):
    asked = []

    def plan(ctx):
        return [Job("document", "a.pdf", "A", priority=1), Job("document", "b.pdf", "B", priority=0),
                Job("document", "c.pdf", "C", priority=2), Job("document", "soon.pdf", "Soon", not_before=NOW + timedelta(days=1))]

    def fetch(ctx, job):
        asked.append(job.key)
        ctx.count(1)
        if job.key == "c.pdf":
            raise OSError("connection reset")
        if job.key == "a.pdf":
            return Fetched(bytes=2048, detail="kept", again=NOW + timedelta(days=7))  # its next version
        return Fetched(rows=1, bytes=1024)

    installed(_plugin("acme", plan, fetch))
    assert registry.plugin_fetchers() == {"acme": [("acme", registry.publishers()["acme"].fetcher)]}
    with _store() as s:
        out = runner.run_plugin("acme", registry.plugin_fetchers()["acme"], s, None, log=lambda *_: None, clock=lambda: NOW)
        assert asked == ["b.pdf", "a.pdf", "c.pdf"]  # its order; "soon" not before its time
        assert out == {"done": 1, "failed": 1, "held": 1, "stopped": None}
        rows = {r["key"]: r for r in s.queue_rows()}
        assert (rows["b.pdf"]["state"], rows["b.pdf"]["bytes"], rows["b.pdf"]["requests"]) == ("done", 1024, 1)
        assert rows["a.pdf"]["state"] == "held" and rows["a.pdf"]["not_before"].startswith("2026-11-07")
        assert rows["c.pdf"]["state"] == "failed" and "connection reset" in rows["c.pdf"]["error"]
        assert rows["soon.pdf"]["state"] == "waiting"
        assert s.requests_today("acme", now=NOW) == 3  # each request counted on its ledger


def test_a_worker_stops_for_the_pause_its_kill_and_a_stop_run(installed):
    installed(_plugin("acme", lambda ctx: [Job("document", k) for k in "abc"],
                      lambda ctx, job: (_ for _ in ()).throw(StopRun("rate limited")) if job.key == "b" else Fetched()))
    parts = registry.plugin_fetchers()["acme"]
    with _store() as s:
        collector.set_pause(s, True, now=NOW)
        out = runner.run_plugin("acme", parts, s, None, log=lambda *_: None, clock=lambda: NOW)
        assert out["stopped"] == "fetching paused" and s.queue_rows() == []  # nothing planned or sent
        collector.set_pause(s, False)
        killswitch.strike(s, "acme", "fetch", "paused by you", now=NOW, minutes=60, shared=False)
        assert runner.run_plugin("acme", parts, s, None, log=lambda *_: None, clock=lambda: NOW)["stopped"].startswith("acme")
        killswitch.release(s, "acme", ("fetch",))
        out = runner.run_plugin("acme", parts, s, None, log=lambda *_: None, clock=lambda: NOW)
        assert out["done"] == 1 and out["stopped"] == "rate limited"
        assert {r["key"]: r["state"] for r in s.queue_rows()} == {"a": "done", "b": "waiting", "c": "waiting"}


def test_one_plugins_failure_is_its_own(installed, tmp_path):
    def bad_plan(ctx):
        raise RuntimeError("plugin bug")

    installed(_plugin("bad", bad_plan, lambda ctx, job: Fetched()),
              _plugin("good", lambda ctx: [Job("document", "x")], lambda ctx, job: Fetched(rows=1)))
    path = tmp_path / "m.db"
    Store(path).close()
    log = []
    out = runner.run_all(lambda: Store(path), None, log.append)
    assert out["bad"] == {"done": 0, "failed": 0, "held": 0, "stopped": None} and out["good"]["done"] == 1
    assert any("bad: bad's plan failed: RuntimeError: plugin bug" in m for m in log)


def test_the_fetcher_command_runs_only_plugins_that_fetch_on_their_own(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "read_env_file", lambda path: {})
    monkeypatch.setenv("LIMINAL_DB", str(tmp_path / "m.db"))
    assert cli.main(["fetcher"]) == 0
    assert "no plugin fetches on its own yet" in capsys.readouterr().out  # none built in does yet (step 1)
    assert registry.plugin_fetchers() == {}


# -- the app's paths not yet in plugins keep the same queue ------------------------------------------
def test_a_bars_sync_puts_its_symbols_on_the_queue_and_ends_each(store):
    bar = {"t": 1_760_000_000_000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
    src = FakeSource(entitled=("minute",), bars={"minute": [bar]})
    store.watch("fake", ["SPCX", "QQQ"])
    seen = []
    sync(src, store, TIERS["free"], SYNC_NOW, log=lambda m: None, on_item=lambda t: seen.append(
        {r["key"]: r["state"] for r in store.queue_rows()}))
    assert seen and all(any(v == "running" for v in s.values()) for s in seen)  # each running while fetched
    rows = {r["key"]: r for r in store.queue_rows(plugin="fake")}
    assert set(rows) == {"SPCX", "QQQ"} and all(r["state"] == "done" and r["kind"] == "bars" for r in rows.values())
    assert rows["SPCX"]["rows"] >= 1 and rows["SPCX"]["detail"].startswith("minute:")
    sync(src, store, TIERS["free"], SYNC_NOW, log=lambda m: None)  # nothing new: no row waits
    assert all(r["state"] == "done" for r in store.queue_rows(plugin="fake"))


def test_a_news_read_is_on_the_queue_under_its_plugin_with_its_next_read(store):
    site = Site()
    r = reader(site, store=store)
    p = pub()
    r.step(NOW, publishers={"t": p})
    row = store.queue_rows(plugin="t")[0]
    assert (row["part"], row["kind"], row["key"], row["title"]) == ("t", "news", "t-press", "T: Press")
    assert row["state"] == "done" and row["not_before"] > NOW.isoformat()  # read, and when next
    r2 = reader(site, store=store)
    r2.step(NOW + timedelta(minutes=1), publishers={"t": p})  # not due: kept as it was
    assert store.queue_rows(plugin="t")[0]["state"] == "done"


def test_a_failed_news_read_is_failed_on_the_queue(store):
    from .test_publications import Resp

    site = Site({"https://news.example.gov/feed.xml": Resp(500)})
    reader(site, store=store).step(NOW, publishers={"t": pub()})
    row = store.queue_rows(plugin="t")[0]
    assert row["state"] == "failed" and row["error"]


# -- the views --------------------------------------------------------------------------------------
def test_the_fetcher_and_a_plugins_page_read_the_queue(tmp_path):
    from liminal.gui.server import ChartApp

    path = tmp_path / "m.db"
    with Store(path, check_same_thread=False) as store:
        store.queue_put("massive", "massive", "bars", [{"key": "SPY", "detail": "stock: new data"}])
        store.queue_put("federal", "bls", "news", [{"key": "bls-cpi", "title": "BLS: Consumer Price Index"}])
        store.queue_start("alpaca", "boats", "bars", "QQQ")
        with store.conn:  # a row left running by a process that is gone
            store.conn.execute("UPDATE fetch_queue SET pid=999999 WHERE key='QQQ'")
        app = ChartApp(store, settings=load_settings(env={"LIMINAL_DB": str(path)}, env_file=None))
        q = app.queue({})
        rows = {r["key"]: r for r in q["rows"]}
        assert rows["QQQ"]["state"] == "stopped" and rows["QQQ"]["partLabel"] == "alpaca (blue ocean)"
        assert rows["SPY"]["ticker"] == "SPY" and rows["SPY"]["asset"] == "stock"
        assert rows["bls-cpi"]["partLabel"] == "Bureau of Labor Statistics"
        assert {p["name"]: p["title"] for p in q["plugins"]}["federal"] == "Federal"
        assert q["totals"] == {"waiting": 2, "stopped": 1} and set(q["kinds"]) == {"bars", "news"}  # its process gone
        assert [r["key"] for r in app.queue({"plugin": "federal"})["rows"]] == ["bls-cpi"]
        assert [r["key"] for r in app.queue({"state": "stopped"})["rows"]] == ["QQQ"]
        status = app.plugin_fetching("massive")
        assert status["state"] == "waiting" and status["counts"] == {"waiting": 1}
        assert [f["name"] for f in status["feeds"]] == ["massive"] and status["feeds"][0]["perDay"]
        collector.set_pause(store, True)
        assert app.plugin_fetching("federal")["state"] == "paused"
        collector.set_pause(store, False)
        publications.pause(store, "federal", True)
        assert app.plugin_fetching("federal")["state"] == "killed"
        with pytest.raises(LookupError):
            app.plugin_fetching("nope")


def test_the_reader_keeps_no_queue_without_the_main_store():
    reader(Site()).step(NOW, publishers={"t": pub()})  # no store: nothing to keep, nothing raised
    assert GovDB(None) is not None


def test_a_datasets_files_are_on_the_queue_under_the_plugin_declaring_it(tmp_path):
    from liminal import datasets

    from .test_dataset_plugins import TODAY, _cot, _Resp, _Session, _zip

    session = _Session(lambda u: _Resp(200, _zip("annual.txt", _cot("2026-03-03"))))
    with Store(tmp_path / "m.db") as store:
        datasets.fetch(store, ["cftc-cot-legacy"], today=TODAY, session=session, log=lambda *_: None)
        rows = store.queue_rows(plugin="federal")
        assert rows and all((r["part"], r["kind"]) == ("cftc", "dataset file") for r in rows)  # the CFTC's: Federal's
        assert {r["state"] for r in rows} == {"done"} and all(r["title"].startswith("cftc-cot-legacy: ") for r in rows)
        assert sum(r["bytes"] for r in rows) > 0


def test_each_plugins_page_shows_its_fetching_first():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src" / "liminal" / "gui" / "static" / "plugins.js").read_text(encoding="utf-8")
    assert "function fetchingHtml(name) {" in js and "api(`/api/plugin-fetching?name=${encodeURIComponent(name)}`)" in js
    assert "${setupHtml(p.name, p.keys)}${fetchingHtml(p.name)}${feedsHtml(p)}" in js  # a feed plugin's, after its setup
    assert "${pubSetupHtml(p)}${fetchingHtml(p.name)}${readsHtml(p)}" in js  # a publisher's
    assert "else { clearTimeout(timer); clearTimeout(fetchState.timer); }" in js  # nothing asked once the view is left
    assert "fetchState.timer = setTimeout(loadFetching, FETCHING_EVERY_MS);" in js
