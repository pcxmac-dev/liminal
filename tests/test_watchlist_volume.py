"""The Watchlist's Vol column reads the last session's volume (the user, 2026-10-31: "lets add volume to
the watchlist")."""
from massive_collate.gui.server import _market


def test_the_snapshot_carries_the_last_sessions_volume(store):
    day = 86_400_000
    store.upsert_bars("massive", "MCD", "day", 1, [
        {"t": 20 * day, "o": 1, "h": 1, "l": 1, "c": 100.0, "v": 1000, "vw": 100.0},
        {"t": 21 * day, "o": 1, "h": 1, "l": 1, "c": 110.0, "v": 2500, "vw": 110.0}])
    snap = store.daily_snapshot()
    assert snap["MCD"]["volume"] == 2500 and snap["MCD"]["dollarVolume"] == (100_000 + 275_000) / 2
    assert _market(snap, "MCD", {"asset": "stock"})["volume"] == 2500
