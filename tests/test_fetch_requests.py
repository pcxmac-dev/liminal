"""The fetcher's requests (storage/requests.py): a stack of asks in front of a queue of standing
work (the user, 2026-11-01: "the fetcher can take a queue/stack of requests")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from liminal_lib.storage import Store
from liminal_lib.storage.requests import STANDING

T0 = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_asks_are_a_stack_in_front_of_the_standing_queue(store):
    store.request_put("aapl", by="chart", now=at(0))
    store.request_put("MSFT", by=STANDING, now=at(1))
    store.request_put("NVDA", by=STANDING, now=at(2))
    store.request_put("tsla", by="page", now=at(3))
    taken = []
    while (r := store.request_next(now=at(10))) is not None:
        taken.append((r["symbol"], r["state"], r["pid"] is not None))
    # the newest ask first, then the older ask, then the standing work in its order
    assert taken == [("TSLA", "assessing", True), ("AAPL", "assessing", True), ("MSFT", "assessing", True),
                     ("NVDA", "assessing", True)]
    assert store.request_counts() == {"assessing": 4}


def test_a_symbol_asked_again_is_one_request_asked_anew(store):
    first = store.request_put("AAPL", kinds=("bars",), by="chart", now=at(0))
    store.request_put("NVDA", by="chart", now=at(1))
    again = store.request_put("aapl", kinds=("live",), by="page", now=at(2))
    assert again["id"] == first["id"] and again["kinds"] == ("bars", "live") and again["by"] == "page"
    assert again["asked_at"] > first["asked_at"]
    assert [r["symbol"] for r in store.requests_open()] == ["AAPL", "NVDA"]  # asked anew: in front again
    # a request being collected goes on; the next ask for the symbol is a new request once it ended
    store.request_next(now=at(3))
    store.request_update(first["id"], state="collecting", plan={"feeds": ["massive"]}, detail="massive")
    assert store.request_put("AAPL", by="chart", now=at(4))["id"] == first["id"]
    assert store.request_get(first["id"])["state"] == "collecting"
    store.request_update(first["id"], state="done", detail="served by massive", now=at(5))
    assert store.request_put("AAPL", by="chart", now=at(6))["id"] != first["id"]


def test_a_request_moves_on_and_keeps_its_plan(store):
    r = store.request_put("AAPL", by="cli", now=at(0))
    assert r["state"] == "waiting" and r["kinds"] == ("bars",) and r["plan"] is None
    taken = store.request_next(now=at(1))
    assert taken["id"] == r["id"] and taken["started_at"] is not None
    plan = {"asset": "stock", "jobs": [{"plugin": "massive", "resolution": "day"}], "feeds": ["massive"]}
    r = store.request_update(r["id"], state="collecting", plan=plan, detail="massive: run attached")
    assert r["state"] == "collecting" and r["plan"] == plan and r["finished_at"] is None
    r = store.request_update(r["id"], state="done", detail="served by massive", now=at(9))
    assert r["state"] == "done" and r["finished_at"] == at(9).isoformat(timespec="seconds") and r["pid"] is None
    with pytest.raises(ValueError, match="not a request state"):
        store.request_update(r["id"], state="running")
    with pytest.raises(ValueError, match="not a symbol"):
        store.request_put("", by="cli")


def test_an_open_request_can_be_cancelled_and_a_dead_fetchers_are_reset(store):
    a = store.request_put("AAPL", by="chart", now=at(0))
    b = store.request_put("MSFT", by="chart", now=at(1))
    assert store.request_cancel(a["id"], now=at(2)) and store.request_get(a["id"])["state"] == "cancelled"
    assert not store.request_cancel(a["id"])  # not open any more
    store.request_next(now=at(3))  # MSFT assessing, by a fetcher that then dies
    assert store.request_reset() == 1
    r = store.request_get(b["id"])
    assert r["state"] == "waiting" and r["pid"] is None and r["started_at"] is None and "ended before" in r["detail"]


def test_the_rows_show_the_collecting_first_then_the_waiting_in_order_then_the_newest_ended(store):
    store.request_put("OLD", by="chart", now=at(0))
    store.request_update(store.request_next(now=at(0))["id"], state="failed", detail="no feed", now=at(1))
    store.request_put("DONE", by="chart", now=at(2))
    store.request_update(store.request_next(now=at(2))["id"], state="done", now=at(3))
    store.request_put("GOING", by="chart", now=at(4))
    store.request_update(store.request_next(now=at(4))["id"], state="collecting")
    store.request_put("QUEUED", by=STANDING, now=at(5))
    store.request_put("ASKED", by="page", now=at(6))
    assert [r["symbol"] for r in store.request_rows()] == ["GOING", "ASKED", "QUEUED", "DONE", "OLD"]
    assert [r["symbol"] for r in store.request_rows(state="done")] == ["DONE"]
    assert store.request_counts() == {"collecting": 1, "waiting": 2, "done": 1, "failed": 1}
    assert store.requests_prune(keep=1) == 1  # the oldest ended forgotten
    assert [r["symbol"] for r in store.request_rows()] == ["GOING", "ASKED", "QUEUED", "DONE"]
