from __future__ import annotations

import pytest
import requests

from liminal_charts import cli
from liminal_libs.storage import Store


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.setenv("LIMINAL_DB", str(tmp_path / "data" / "m.db"))
    monkeypatch.setenv("MASSIVE_API_KEY", "FAKE")
    for name in ("MASSIVE_TIER", "MASSIVE_RPM", "MASSIVE_MAX_REQUESTS_PER_RUN", "MASSIVE_MAX_REQUESTS_PER_DAY"):
        monkeypatch.delenv(name, raising=False)

    def no_network(*a, **kw):
        raise AssertionError("no request should be sent")

    monkeypatch.setattr(requests.Session, "get", no_network)
    return tmp_path


def test_watch_and_status_are_offline(env, capsys):
    assert cli.main(["watch", "add", "spcx"]) == 0
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "SPCX" in out and "massive: plan free" in out and "alpaca: plan alpaca-basic" in out


def test_watch_accepts_exchange_and_shows_listing(env, capsys):
    from datetime import date

    cli.main(["watch", "add", "SPCX::NASDAQ", "--resolution", "minute"])
    with Store(env / "data" / "m.db") as s:
        s.set_listing("massive", "SPCX", date(2026, 6, 12), "FIGI", date(2026, 10, 22))
    capsys.readouterr()
    cli.main(["watch", "list"])
    out = capsys.readouterr().out
    assert "SPCX::XNAS" in out and "listed: 2026-06-12" in out


def test_daily_cap_reached_sends_nothing(env, monkeypatch, capsys):
    monkeypatch.setenv("MASSIVE_MAX_REQUESTS_PER_DAY", "0")
    cli.main(["watch", "add", "SPCX"])
    assert cli.main(["--source", "massive", "sync", "--only"]) == 0  # the feed's own run, as the hourly sync starts it
    assert "daily request cap" in capsys.readouterr().out


def test_overlapping_runs_are_refused(env):
    import os

    db = env / "data" / "m.db"
    lock = db.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getppid()))  # another live process holds it
    with pytest.raises(SystemExit):
        with cli.run_lock(db):
            pass
    lock.unlink()
    with cli.run_lock(db):
        with cli.run_lock(db):  # this process again (a whole sync holds it across its feeds)
            assert lock.exists()
        assert lock.exists()  # the inner one leaves it to the outer
    assert not lock.exists()  # released afterwards


def test_lock_left_by_a_dead_process_is_taken_over(env):
    import os

    db = env / "data" / "m.db"
    lock = db.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999")  # no such process
    with cli.run_lock(db):
        assert lock.read_text().split()[0] == str(os.getpid())  # its id and its start
    assert not lock.exists()


def test_lock_of_a_live_process_is_respected(env):
    import os

    db = env / "data" / "m.db"
    lock = db.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()))  # this test process is alive
    with pytest.raises(SystemExit):
        with cli.run_lock(db):
            pass
    lock.unlink()


def test_pid_alive():
    import os

    assert cli.pid_alive(os.getpid()) and not cli.pid_alive(999999) and not cli.pid_alive(0)


class HeldFetcher:
    """The fetcher as `sync` by hand holds it (cli.attach_fetcher): what it was asked, idle at once."""

    def __init__(self):
        self.asked, self.detached, self.host_pid = [], False, 4242

    def alive(self):
        return not self.detached

    def detach(self):
        self.detached = True

    def ask(self, **what):
        self.asked.append(what)
        return {"busy": False} if what.get("status") else {"ok": True}


def test_missing_key_skips_that_feed_and_says_so(env, monkeypatch, capsys):
    monkeypatch.delenv("MASSIVE_API_KEY")
    cli.main(["watch", "add", "SPCX"])
    held = HeldFetcher()
    monkeypatch.setattr(cli, "attach_fetcher", lambda db, log: held)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    assert cli.main(["sync"]) == 0  # the fetcher's pass: the feeds set up here (Alpaca: crypto needs no key), Massive not
    assert held.asked[0] == {"pass": True} and held.detached
    assert "a pass asked of the fetcher" in capsys.readouterr().out
    assert cli.main(["--source", "massive", "sync", "--only"]) == 2  # only an unconfigured feed: an error


def test_export_writes_csv(env, monkeypatch, capsys):
    with Store(env / "data" / "m.db") as s:
        s.upsert_trades("massive", "SPCX", [{"sip_timestamp": 1, "sequence_number": 1, "price": 1.0, "size": 1}])
    out = env / "out.csv"
    assert cli.main(["export", "SPCX", "--out", str(out)]) == 2  # bars-only (the default) reads no ticks
    assert "bars-only mode" in capsys.readouterr().err and not out.exists()
    monkeypatch.setenv("BARS_ONLY", "off")
    assert cli.main(["export", "SPCX", "--out", str(out)]) == 0
    assert out.read_text().count("\n") == 2


def test_tick_backups_and_tick_charts_wait_for_bars_only_to_be_off(env, capsys):
    dest = env / "b.db"
    assert cli.main(["admin", "backup", "--dest", str(dest), "--ticks"]) == 2
    assert cli.main(["chart", "SPCX", "--ticks"]) == 2
    err = capsys.readouterr().err
    assert "backup --ticks: bars-only mode" in err and "chart --ticks: bars-only mode" in err
    assert not dest.exists()


def test_offline_copies_of_the_app_fetch_nothing(env, monkeypatch, capsys):
    monkeypatch.setenv("LIMINAL_OFFLINE", "1")
    cli.main(["watch", "add", "SPCX"])
    assert cli.main(["sync"]) == 0  # requests.Session.get would fail the test if anything were sent
    assert "offline (LIMINAL_OFFLINE)" in capsys.readouterr().out
    assert cli.main(["live", "start"]) == 0
    assert "live recording is off" in capsys.readouterr().out


def test_each_feed_has_its_own_run_lock_and_a_move_of_the_data_waits_for_them_all(env):
    import os

    from liminal_libs import proc

    db = env / "data" / "m.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    with cli.run_lock(db, "massive"):
        with cli.run_lock(db, "alpaca"):  # another feed fetches beside it
            assert proc.run_holders(db) == {"massive": os.getpid(), "alpaca": os.getpid()}
    assert proc.run_holders(db) == {}  # given back
    other = proc.run_lock_path(db, "massive")
    other.write_text(str(os.getppid()))  # Massive's run, in another live process
    with pytest.raises(cli.Busy):
        with cli.run_lock(db, "massive"):  # one run a feed
            pass
    with pytest.raises(cli.Busy):
        with cli.run_lock(db):  # no move of the data while a feed fetches
            pass
    other.unlink()
    proc.run_lock_path(db).write_text(str(os.getppid()))  # a move of the data, or a run from before the feeds ran apart
    with pytest.raises(cli.Busy):
        with cli.run_lock(db, "alpaca"):
            pass
    assert not proc.run_lock_path(db, "alpaca").exists()  # taken, then given back at once


def test_sync_by_hand_asks_the_fetcher_for_a_pass_and_builds_the_derived_frames_after(env, monkeypatch, capsys):
    # the feeds' runs are the fetcher's to hold (each in a process of its own, side by side); `sync`
    # waits for its pass, then builds the composites and derived frames from what arrived
    cli.main(["watch", "add", "SPCX"])
    held, built = HeldFetcher(), []
    monkeypatch.setattr(cli, "attach_fetcher", lambda db, log: held)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli, "after_sync", lambda args, s: built.append(1))
    assert cli.main(["sync"]) == 0
    assert held.asked[0] == {"pass": True} and any(a.get("status") for a in held.asked) and held.detached
    assert built == [1]  # the derived frames from what arrived, once the pass is over
    monkeypatch.setattr(cli, "attach_fetcher", lambda db, log: None)
    assert cli.main(["sync"]) == 0 and "no fetcher answered" in capsys.readouterr().out
    assert built == [1]  # nothing arrived: nothing built


def test_sync_of_an_opened_symbol_puts_it_on_the_fetchers_stack_and_waits_for_it(env, monkeypatch, capsys):
    cli.main(["watch", "add", "SPCX"])
    held = HeldFetcher()
    monkeypatch.setattr(cli, "attach_fetcher", lambda db, log: held)
    db = env / "data" / "m.db"

    def served(s):  # the fetcher's runs serve it meanwhile
        with Store(db) as store:
            for r in store.requests_open():
                store.request_update(r["id"], state="done", detail="served by alpaca, massive")
    monkeypatch.setattr(cli.time, "sleep", served)
    assert cli.main(["sync", "--tickers", "SPCX"]) == 0
    with Store(db) as store:
        (row,) = store.request_rows()
    assert row["symbol"] == "SPCX" and row["by"] == "cli" and row["state"] == "done"
    assert held.asked == [{"wake": True}] and held.detached
    assert "sync: SPCX: done (served by alpaca, massive)" in capsys.readouterr().out
