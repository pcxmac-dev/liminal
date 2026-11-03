"""The project is liminal (renamed from massive on 2026-11-01); the Massive data provider keeps its
name. The app's own names carry no trace of the old one, and the app's settings a user may still
have under their old names are read."""
from __future__ import annotations

import re
from pathlib import Path

from liminal_lib import config, layout, live

SRC = Path(__file__).resolve().parents[1] / "src" / "liminal_app"
OLD = re.compile(r"massive_collate|massive-collate|MassiveCollate|Massive Charts|X-Massive-|MassiveIcons"
                 r"|MassiveData|MASSIVE_(DB|OFFLINE|READONLY|REFRESH_HOURS|LIVE_LOCK|MONGO_PORT|DATA_REPOS)\b"
                 r"|massive-live\.lock|\.massive-collate")
# The browser's storage prefix: in the chart app's static files only (elsewhere `massive:` is the
# provider's: its ledgers' names, its feed's derivation keys).
OLD_PREFIX = re.compile(r"['\"`]massive:")


def test_the_app_carries_none_of_its_old_names():
    """Allowed: config.RENAMED (the old names of the settings, read for the new) and app.js moving
    the settings saved in the browser under the old storage prefix to the new."""
    found = []
    for path in SRC.rglob("*"):
        if path.is_dir() or "vendor" in path.parts or path.suffix in (".pyc", ".png", ".bin", ".ico"):
            continue
        patterns = [OLD] + ([OLD_PREFIX] if "static" in path.parts else [])
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if any(p.search(line) for p in patterns) and "RENAMED" not in line and "OLD_PREFIX" not in line:
                found.append(f"{path.relative_to(SRC)}:{n}: {line.strip()[:80]}")
    assert found == []
    assert "OLD_PREFIX = 'massive:'" in (SRC / "gui" / "static" / "app.js").read_text(encoding="utf-8")


def test_the_apps_settings_are_read_under_their_old_names_too(tmp_path, monkeypatch):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    s = config.load_settings(env={"MASSIVE_DB": str(old), "MASSIVE_OFFLINE": "1"}, env_file=None)
    assert s.db_path == old and s.offline
    s = config.load_settings(env={"MASSIVE_DB": str(old), "LIMINAL_DB": str(new)}, env_file=None)
    assert s.db_path == new and not s.offline  # the new name wins
    monkeypatch.delenv("LIMINAL_LIVE_LOCK", raising=False)
    monkeypatch.setenv("MASSIVE_LIVE_LOCK", str(tmp_path / "live.lock"))
    assert live.machine_lock() == tmp_path / "live.lock"
    assert set(config.RENAMED) == {f"LIMINAL_{n}" for n in (
        "DB", "OFFLINE", "READONLY", "REFRESH_HOURS", "LIVE_LOCK", "MONGO_PORT", "DATA_REPOS")}


def test_the_data_folder_and_the_main_file_are_liminals():
    assert layout.MAIN == "liminal.db"
    assert config.DEFAULT_DB_PATH == layout.data_dir() / "liminal.db"  # store/data in the workspace, else ~/LiminalData
    assert layout.data_dir().name in ("data", "LiminalData")
    assert live.lock_path(Path("x/liminal.db")) == Path("x/liminal-live.lock")
