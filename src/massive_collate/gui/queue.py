"""The Fetcher view (the queue) and each plugin's fetching status (its page in the Plugins view).

The user, 2026-10-31: "the fetcher will then just show the queue of all resources being downloaded
like symbols", "the plugin status will be available in the plugins:: plugin page". The Fetcher lists
the fetch queue (storage/queue.py) across plugins: every resource waiting, being fetched, held,
failed or done, by plugin, kind and state; a row left running by a process that is gone says so.
A plugin's page shows its own: whether it is fetching (and what), waiting, paused or stopped, its
queue, its feeds' requests against their caps, their limits and runs, and its lines of the log.
Read from the queue, the ledgers, the kills, the run locks and the log: no requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import collector, killswitch
from ..proc import pid_alive
from ..sources import providers, publishers
from ..sources.registry import label, plugin_feeds, plugin_of, publisher_of, publisher_parts
from ..symbols import ASSETS, resolve
from .activity import fetching_feeds, limits, log_path, log_tail


def _plugins() -> dict[str, str]:
    """Every plugin by name with its title (a part's rows are its plugin's)."""
    out = {n: p.title for n, p in providers().items() if plugin_of(n) == n}
    out.update({n: p.title for n, p in publishers().items() if publisher_of(n) == n})
    return out


def _part_label(plugin: str, part: str) -> str:
    if part == plugin:
        return ""
    if part in providers():
        return label(part)
    pub = publishers().get(part)
    return pub.title if pub else part


def _row(r: dict, alive: dict[int, bool]) -> dict:
    out = {**r, "partLabel": _part_label(r["plugin"], r["part"])}
    if r["state"] == "running" and r["pid"] and not alive.setdefault(r["pid"], pid_alive(r["pid"])):
        out["state"], out["detail"] = "stopped", "its process ended before it"
    if r["kind"] == "bars":
        out["ticker"] = r["key"]
        head = (r["detail"] or "").split(":", 1)[0]  # as planned ("stock: new data"; a future's ends so too)
        out["asset"] = head if head in ASSETS else _asset(r["key"])
    return out


def _asset(ticker: str) -> str | None:
    try:
        return resolve(ticker).asset
    except (ValueError, KeyError):
        return None


def view(store, plugin: str | None = None, kind: str | None = None, state: str | None = None,
         limit: int = 300) -> dict:
    """The Fetcher: the queue's rows (running, waiting, held, failed, the newest done), counted by
    plugin, kind and state, with each plugin's title."""
    alive: dict[int, bool] = {}
    rows = [_row(r, alive) for r in store.queue_rows(plugin, kind, None if state == "stopped" else state, limit)]
    if state == "stopped":
        rows = [r for r in rows if r["state"] == "stopped"]
    counts = _counts(store, alive)
    titles = _plugins()
    totals: dict[str, int] = {}
    for by in counts["plugins"].values():
        for s, n in by.items():
            totals[s] = totals.get(s, 0) + n
    return {"rows": rows, "counts": counts, "totals": totals, "limit": limit,
            "plugins": [{"name": n, "title": titles.get(n, n)} for n in counts["plugins"]],
            "kinds": sorted(counts["kinds"])}


def _counts(store, alive: dict[int, bool]) -> dict:
    """The queue's counts by plugin and kind, a row running by a process that is gone counted stopped."""
    counts = store.queue_counts()
    for r in store.queue_rows(state="running", limit=1000):
        if r["pid"] and not alive.setdefault(r["pid"], pid_alive(r["pid"])):
            for by in (counts["plugins"].setdefault(r["plugin"], {}), counts["kinds"].setdefault(r["kind"], {})):
                by["running"] = by.get("running", 1) - 1
                by["stopped"] = by.get("stopped", 0) + 1
                if not by["running"]:
                    del by["running"]
    return counts


def _parts(name: str) -> tuple[list[str], list[str]]:
    """A plugin's feeds (a feed plugin's, its own first) and its publishers (its parts)."""
    if name in providers():
        return plugin_feeds(name), publisher_parts(name)
    return [], [n for n in (name, *publisher_parts(name)) if n in publishers()]


def _mentions(line: str, words: list[str]) -> bool:
    low = line.lower()
    return any(f"{w.lower()}:" in low or f"{w.lower()} " in low for w in words)


def plugin_status(store, settings, db_path: Path, name: str, now: datetime | None = None, log_lines: int = 40) -> dict:
    """A plugin's fetching on its page (see the module's docstring)."""
    if name not in providers() and name not in publishers():
        raise LookupError(f"no plugin named {name}")
    now = now or datetime.now(timezone.utc)
    feeds, pubs = _parts(name)
    alive: dict[int, bool] = {}
    rows = [_row(r, alive) for r in store.queue_rows(plugin=name, limit=60)]
    counts = _counts(store, alive)["plugins"].get(name, {})
    held = fetching_feeds(db_path)
    runs_going = sorted(f for f in feeds if f in held) + ([name] if name in held and name not in feeds else [])
    pause = collector.pause_state(store, now)
    kill = next((k for k in (killswitch.killed(store, n, "fetch", now) for n in (name, *feeds)) if k), None)
    running = [r for r in rows if r["state"] == "running"]
    if kill:
        state, why = "killed", kill.get("why") or ""
    elif pause:
        state, why = ("halted", "every fetch halted until you resume") if pause.get("halt") else \
            ("paused", f"background fetching paused until {pause['until'][:16].replace('T', ' ')} UTC")
    elif running or runs_going:
        state, why = "fetching", ", ".join(r["title"] for r in running[:3]) or f"{', '.join(map(label, runs_going))} running"
    elif counts.get("waiting"):
        state, why = "waiting", f"{counts['waiting']:,} waiting for its next run"
    else:
        state, why = "idle", "nothing waiting"
    feed_rows = []
    for f in feeds:
        s = settings.for_source(f)
        feed_rows.append({"name": f, "label": label(f), "tier": s.tier.name, "rpm": s.tier.requests_per_minute,
                          "today": store.requests_today(f), "perDay": s.max_requests_per_day,
                          "perRun": s.max_requests_per_run, "running": f in held})
    limit_rows = [r for r in limits(store, settings, now) if r["source"] in feeds] if feeds else []
    runs = [r for r in store.runs(60) if r["source"] in (*feeds, name)][:10]
    for r in runs:
        try:
            a = datetime.fromisoformat(r["started_at"])
            b = datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else now
            r["seconds"] = round((b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            r["seconds"] = None
    words = [*feeds, *pubs, name, *(publishers()[p].title for p in pubs)]
    log = [line for line in log_tail(log_path(db_path), 1500) if _mentions(line, words)][-log_lines:]
    return {"name": name, "state": state, "why": why, "running": running, "counts": counts, "rows": rows,
            "feeds": feed_rows, "limits": limit_rows, "runs": runs, "log": log, "parts": pubs,
            "paused": pause, "kill": kill}
