"""What the app gives the plugin packages through the contract, and says of them: a poller's
session (sources/stream.py: session_at, plugin API 1.10), a crypto venue's view of the settings
(sources/archive.py: venue_view, the plugin's own plan and caps), and the daily audit's line on the
closed archives (the archives of stocks alone)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from liminal_app import cli
from liminal_lib.config import load_settings
from liminal_lib.sessions import ET
from liminal_lib.sources import is_archive, providers
from liminal_lib.sources.archive import venue_view
from liminal_lib.sources.registry import get
from liminal_lib.sources.stream import session_at


def test_session_at_finds_blue_oceans_night_on_both_sides_of_midnight():
    """Blue Ocean's night before Friday 2026-10-23: 20:00 Thursday to 04:00 Friday, ET."""
    evening = session_at("overnight", datetime(2026, 10, 22, 22, 0, tzinfo=ET))
    assert evening is not None
    assert (evening.open, evening.close) == (datetime(2026, 10, 22, 20, 0, tzinfo=ET), datetime(2026, 10, 23, 4, 0, tzinfo=ET))
    small_hours = session_at("overnight", datetime(2026, 10, 23, 2, 0, tzinfo=ET))
    assert (small_hours.open, small_hours.close) == (evening.open, evening.close)  # the same night, past midnight
    in_utc = session_at("overnight", datetime(2026, 10, 23, 2, 0, tzinfo=ET).astimezone(timezone.utc))
    assert (in_utc.open, in_utc.close) == (evening.open, evening.close)  # any zone
    assert session_at("overnight", datetime(2026, 10, 23, 4, 0, tzinfo=ET)) is None  # the close is exclusive
    assert session_at("overnight", datetime(2026, 10, 23, 12, 0, tzinfo=ET)) is None  # midday: pre-market and the day's
    assert session_at("overnight", datetime(2026, 10, 24, 22, 0, tzinfo=ET)) is None  # Saturday night: no session


def test_a_venues_view_carries_its_plugins_plan_and_caps():
    p = get("coinbase")
    if p is None:
        pytest.skip("liminal-plugin-coinbase is not installed")
    base = load_settings(env={}, env_file=None)
    v = venue_view("coinbase")(base)
    assert v.tier == p.tier and (v.max_requests_per_run, v.max_requests_per_day) == (p.per_run, p.per_day)
    assert v.origin is base and base.for_source("coinbase").tier == p.tier
    limited = venue_view("coinbase")(replace(base, crypto_venue_days=30))
    assert limited.tier.history_days == 30 and limited.tier.name == p.tier.name  # the plan, this far back only


def test_the_daily_audit_names_the_archives_of_stocks_alone():
    text = cli.daily_audit_text({"stocks": 3, "complete": 1, "head": [("AAA", "1990-01-01", "2003-09-10")],
                                 "none": [], "unchecked": []})
    line = next(l for l in text.splitlines() if "oldest years" in l)
    archives = [n for n in providers() if is_archive(n)]
    for n in archives:  # Tiingo's stocks: named; Cboe's indices and the crypto venues: not
        assert (f" {n}" in line or f"{n} (" in line) == ("stock" in providers()[n].assets), n
    if not any("stock" in providers()[n].assets for n in archives):
        assert "none installed" in line
