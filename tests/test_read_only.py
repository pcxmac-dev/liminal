"""Read-only (MASSIVE_READONLY): a copy of the app on the real data folder reads it and writes nothing,
fetches nothing and starts nothing. The user, 2026-10-31: "lets not have testing data, lets just safely
query the plugins"."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from massive_collate import gov, mongo
from massive_collate.config import load_settings
from massive_collate.storage import Store, set_read_only


def test_the_setting_reads_only_and_is_offline(tmp_path):
    s = load_settings(env={"MASSIVE_DB": str(tmp_path / "m.db"), "MASSIVE_READONLY": "1"}, env_file=None)
    assert s.read_only and s.offline
    s = load_settings(env={"MASSIVE_DB": str(tmp_path / "m.db"), "MASSIVE_OFFLINE": "1"}, env_file=None)
    assert s.offline and not s.read_only


def test_every_connection_reads_and_refuses_writes(tmp_path):
    main = tmp_path / "massive.db"
    with Store(main) as s:  # the data, made by a process that writes
        s.upsert_bars("alpaca", "AAPL", "minute", 1, [{"t": 60_000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}])
        s.kv_set("k", "v")
        s.save_news("massive", [{"id": "1", "published_ms": 5, "title": "t"}])
    set_read_only(True)
    with Store(main) as s:
        assert s.kv_get("k") == "v" and len(s.bar_rows("alpaca", "AAPL", "minute", 0, 10**9)) == 1
        assert [n["id"] for n in s.news()] == ["1"]
        for write in (lambda: s.kv_set("k", "w"),
                      lambda: s.upsert_bars("alpaca", "AAPL", "minute", 1, [{"t": 120_000, "o": 1, "c": 1}]),
                      lambda: s.save_news("massive", [{"id": "2", "published_ms": 6, "title": "u"}])):
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                write()
        assert s.kv_get("k") == "v"
    g = gov.open_db(main)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        g.save_items("fed-press", [{"id": "a", "agency": "Fed", "title": "x"}], datetime.now(timezone.utc))
    g.close()


def test_mongodb_is_not_started_from_a_reading_copy(tmp_path, monkeypatch):
    set_read_only(True)
    monkeypatch.setattr(mongo, "binary", lambda: tmp_path / "mongod.exe")
    with pytest.raises(RuntimeError, match="read-only"):
        mongo.start(tmp_path)


def test_no_history_run(tmp_path, monkeypatch, capsys):
    from massive_collate import cli

    monkeypatch.setenv("MASSIVE_DB", str(tmp_path / "massive.db"))
    monkeypatch.setenv("MASSIVE_READONLY", "1")
    assert cli.main(["history", "run"]) == 0
    assert "read-only (MASSIVE_READONLY): nothing is copied" in capsys.readouterr().out
