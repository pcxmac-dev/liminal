"""Closed history in DuckDB (storage/history.py): a feed's closed months copied into a file a month,
checked, entered in its manifest, read from there while current; a write in SQLite makes it stale."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from liminal_lib.storage import Store
from liminal_lib.storage import history

pytest.importorskip("duckdb")

DAY = 86_400_000


def ms(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def bar(t, c, v=100.0, n=5):
    return {"t": t, "o": c - 1, "h": c + 1, "l": c - 2, "c": c, "v": v, "vw": c, "n": n}


@pytest.fixture
def disk(tmp_path):
    s = Store(tmp_path / "liminal.db")
    jan = [bar(ms(2026, 1, 5, 15, i), 100 + i) for i in range(30)]
    feb = [bar(ms(2026, 2, 3, 15, i), 200 + i) for i in range(30)]
    s.upsert_bars("alpaca", "AAPL", "minute", 1, jan + feb)
    s.upsert_bars("alpaca", "MSFT", "minute", 1, [bar(ms(2026, 1, 6, 15, i), 50 + i, v=None, n=None) for i in range(10)])
    s.upsert_bars("alpaca", "AAPL", "day", 1, [bar(ms(2026, 1, 5), 101), bar(ms(2026, 2, 3), 201)])
    s.upsert_built_bars("alpaca", "AAPL", "hour", 1, [bar(ms(2026, 1, 5, 15), 110)], derivation=7)
    yield s
    s.close()


NOW = int(datetime.now(timezone.utc).timestamp() * 1000)
LATER = NOW + 30 * DAY  # both months closed and the bars written now quiet by then


def conn(s):
    return s._bars("alpaca")


def test_month_bounds():
    assert history.bounds("2026-12") == (ms(2026, 12, 1), ms(2027, 1, 1))
    assert history.month_of(ms(2026, 2, 28, 23, 59)) == "2026-02"
    assert history._months(ms(2025, 11, 30), ms(2026, 2, 1)) == ["2025-11", "2025-12", "2026-01", "2026-02"]


def quiet(c):
    """A change log reaching back a year, with nothing in it (the bars written long ago)."""
    history.ensure(c)
    c.execute("DELETE FROM changes")
    c.execute("UPDATE changes_since SET ms=?", (ms(2025, 1, 1),))
    c.commit()


def test_due_newest_first_closed_and_quiet(disk):
    c = conn(disk)
    quiet(c)
    spans = history.series_spans(c)
    assert history.due(c, LATER, spans) == ["2026-02", "2026-01"]  # months some series has bars in
    # January ends 2026-02-01: closed a week after
    assert history.due(c, ms(2026, 2, 5), spans) == []
    assert history.due(c, ms(2026, 2, 9), spans) == ["2026-01"]
    # a change log that does not reach QUIET_DAYS back: nothing is known quiet
    c.execute("UPDATE changes_since SET ms=?", (LATER - DAY,))
    c.commit()
    assert history.due(c, LATER, spans) == []


def test_due_skips_a_month_written_lately(disk):
    c = conn(disk)
    history.ensure(c)
    c.execute("UPDATE changes_since SET ms=?", (ms(2025, 1, 1),))
    c.commit()
    assert history.due(c, NOW + DAY, history.series_spans(c)) == []  # January and February were written now


def test_archive_reads_from_duckdb_the_same(disk, monkeypatch):
    lo, hi = ms(2026, 1, 1), ms(2026, 3, 1)
    before = disk.bars_window(["alpaca"], "AAPL", "minute", lo, hi)
    rows_before = disk.bar_rows("alpaca", "MSFT", "minute", lo, hi)
    loaded_before = disk.load_bars(["AAPL", "MSFT"], "minute", source="alpaca")
    built_before = disk.bars_window(["alpaca"], "AAPL", "hour", lo, hi)
    monkeypatch.setattr(history, "CHUNK_ROWS", 7)  # a series read and written a few rows at a time
    got = history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER)
    assert got.kept and got.bars == 30 + 10 + 1 and got.built == 1
    assert (disk.history_dir / "alpaca" / got.file).exists()
    assert not list((disk.history_dir / "alpaca").glob("*.part"))
    [m] = disk.history_months("alpaca")
    assert (m["month"], m["stale"], m["bars"], m["built"]) == ("2026-01", 0, 41, 1)

    calls = []
    real = history.Reader.frame

    def counted(self, feed, file, sql, params):
        calls.append(file)
        return real(self, feed, file, sql, params)

    monkeypatch.setattr(history.Reader, "frame", counted)
    after = disk.bars_window(["alpaca"], "AAPL", "minute", lo, hi)
    assert calls == [got.file, got.file]  # the feed's own and the built bars of January
    pd.testing.assert_frame_equal(after, before, check_dtype=False)
    assert disk.bar_rows("alpaca", "MSFT", "minute", lo, hi) == rows_before  # a missing volume stays None
    pd.testing.assert_frame_equal(disk.load_bars(["AAPL", "MSFT"], "minute", source="alpaca"), loaded_before,
                                  check_dtype=False)
    built_after = disk.bars_window(["alpaca"], "AAPL", "hour", lo, hi)
    pd.testing.assert_frame_equal(built_after, built_before, check_dtype=False)
    assert built_after["derived"].tolist() == [1]
    # a window outside the archived month never opens it
    calls.clear()
    disk.bars_window(["alpaca"], "AAPL", "minute", ms(2026, 2, 1), ms(2026, 3, 1))
    assert calls == []


def test_sqlite_picked_reads_sqlite_only(disk, monkeypatch):
    history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER)
    disk.kv_set("store:feed:alpaca:bars", "sqlite")
    monkeypatch.setattr(history.Reader, "frame", lambda *a: pytest.fail("read DuckDB"))
    disk._cache.pop(("history_on", "alpaca"), None)
    assert len(disk.bars_window(["alpaca"], "AAPL", "minute", ms(2026, 1, 1), ms(2026, 2, 1))) == 30


def test_a_write_in_sqlite_makes_the_month_stale(disk):
    history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER)
    history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-02", now_ms=LATER)
    disk.upsert_bars("alpaca", "AAPL", "minute", 1, [bar(ms(2026, 1, 5, 15, 3), 999)])  # a correction
    states = {m["month"]: m["stale"] for m in disk.history_months("alpaca")}
    assert states == {"2026-01": 1, "2026-02": 0}
    w = disk.bars_window(["alpaca"], "AAPL", "minute", ms(2026, 1, 1), ms(2026, 2, 1))
    assert 999 in w["close"].tolist()  # read from SQLite again
    # the same values again leave the bar (and the manifest) as they were
    disk.upsert_bars("alpaca", "AAPL", "minute", 1, [bar(ms(2026, 2, 3, 15, 0), 200)])
    assert {m["month"]: m["stale"] for m in disk.history_months("alpaca")}["2026-02"] == 0
    # copied again: a new file; the old one removed by the next tidy
    again = history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER + DAY)
    assert again.kept and again.file == "2026-01.2.duckdb"
    disk._history.forget(disk.history_dir / "alpaca" / "2026-01.1.duckdb")
    assert history.tidy(conn(disk), disk.history_dir, "alpaca") == 1
    assert sorted(p.name for p in (disk.history_dir / "alpaca").iterdir()) == ["2026-01.2.duckdb", "2026-02.1.duckdb"]


def test_a_write_during_the_copy_keeps_nothing(disk):
    # the copy "began" before the bars were written: the change log has them since
    got = history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=ms(2026, 1, 1))
    assert not got.kept
    assert disk.history_months("alpaca") == []
    assert not any((disk.history_dir / "alpaca").iterdir())


def test_stop_ends_without_a_file(disk):
    assert history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER,
                                 stop=lambda: True) is None
    assert not any((disk.history_dir / "alpaca").iterdir())


def test_run_newest_first_within_the_feed_cap(disk):
    c = conn(disk)
    quiet(c)
    lines = []
    done = history.run({"alpaca": c}, disk.history_dir, lines.append, months_per_feed=1, now_ms=LATER)
    assert [g.month for _, g in done] == ["2026-02"]
    assert lines == ["history: alpaca 2026-02 copied to DuckDB: 31 bars, 0 built, "
                     f"{done[0][1].bytes / 1e6:,.1f} MB in {done[0][1].seconds:,.0f} s"]
    assert [g.month for _, g in history.run({"alpaca": c}, disk.history_dir, lines.append, now_ms=LATER)] == ["2026-01"]


def test_in_memory_store_has_no_history(store):
    store.upsert_bars("alpaca", "AAPL", "minute", 1, [bar(ms(2026, 1, 5, 15), 1)])
    assert store.history_dir is None and not store.history_on("alpaca")
    assert len(store.bars_window(["alpaca"], "AAPL", "minute", ms(2026, 1, 1), ms(2026, 2, 1))) == 1


def test_day_bounds_reads_archived_days(disk):
    history.archive_month(conn(disk), disk.history_dir, "alpaca", "2026-01", now_ms=LATER)
    got = disk.load_bars(["AAPL"], "day", start=date(2026, 1, 1), end=date(2026, 2, 28), source="alpaca")
    assert got["close"].tolist() == [101, 201]


def test_the_calendar_frames_stay_in_sqlite(disk, monkeypatch):
    """derive.py rebuilds a symbol's weeks, months and years whole from its days (a 2003 year bar
    written again every hour): never archived, never a change that keeps a month open or stales it."""
    c = conn(disk)
    disk.upsert_built_bars("alpaca", "AAPL", "year", 1, [bar(ms(2026, 1, 1), 150)], derivation=8)
    disk.upsert_built_bars("alpaca", "AAPL", "week", 1, [bar(ms(2026, 1, 5), 101)], derivation=8)
    assert not [s for s in history.series_spans(c) if s[2] in history.CALENDAR]
    got = history.archive_month(c, disk.history_dir, "alpaca", "2026-01", now_ms=LATER)
    assert got.kept and got.built == 1  # the hour built in January; not the week, nor the year
    # a year bar written again (derive's hourly rebuild): the month is not stale for it
    disk.upsert_built_bars("alpaca", "AAPL", "year", 1, [bar(ms(2026, 1, 1), 151)], derivation=9)
    assert [m["stale"] for m in disk.history_months("alpaca")] == [0]
    quiet(c)
    disk.upsert_built_bars("alpaca", "AAPL", "month", 1, [bar(ms(2026, 2, 1), 201)], derivation=9)
    assert "2026-02" in history.due(c, LATER, history.series_spans(c))  # a month bar's write keeps no month open
    # the weeks, months and years are read from SQLite, the archived month notwithstanding
    monkeypatch.setattr(history.Reader, "frame", lambda *a: pytest.fail("read DuckDB for a calendar frame"))
    assert disk.bars_window(["alpaca"], "AAPL", "year", ms(2026, 1, 1), ms(2027, 1, 1))["close"].tolist() == [151]
    assert disk.bars_window(["alpaca"], "AAPL", "week", ms(2026, 1, 1), ms(2026, 2, 1))["close"].tolist() == [101]


def test_triggers_from_before_are_made_again(disk):
    c = conn(disk)
    history.ensure(c)
    with c:  # a trigger as an older version wrote it: without the calendar frames' exception
        c.execute("DROP TRIGGER history_stale_bars_insert")
        c.execute("CREATE TRIGGER history_stale_bars_insert AFTER INSERT ON bars WHEN new.ts < 0 BEGIN "
                  "UPDATE history SET stale=1 WHERE 0; END")
    history.ensure(c)
    found = dict(c.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'history_stale_%'"))
    assert len(found) == 6 and all(history.TRIGGER_MARK in sql for sql in found.values())
