"""The fetcher's own page and the data API, served in the fetcher's process (gui/server.py
serve_fetcher): the chart app's page without the chart, the tools and what is the user's (the
user, 2026-11-01), with the request stack; the fetcher itself (liminal-integrator) stands in."""
from __future__ import annotations

import http.client
import json
import threading
from dataclasses import replace

from liminal.config import load_settings
from liminal.gui import server


class FakeFetcher:
    """What serve_fetcher needs of the fetcher: its work, its handle, its status, a wake."""

    def __init__(self):
        self.page_url, self.host, self.woken, self.passes = None, None, 0, 0

    def run(self, stop):
        stop.wait()

    def handle(self, msg):
        return {"ok": True}

    def status(self):
        return {"pid": 4242, "busy": False, "clients": self.host.clients() if self.host else [], "feeds": []}

    def wake_up(self):
        self.woken += 1

    def ask_pass(self):
        self.passes += 1


class FakeHost:
    """serve records the work; the test looks at the page meanwhile."""
    name = "fetcher"

    def __init__(self):
        self.stop, self.touched, self.work, self.secure, self.handle = threading.Event(), 0, None, None, None

    def touch(self):
        self.touched += 1

    def clients(self):
        return [4242]

    def serve(self, work, secure=None, handle=None):
        self.work, self.secure, self.handle = work, secure, handle
        return "recorded"


def test_serve_fetcher_serves_the_fetchers_page_and_the_data_api_in_its_process(tmp_path):
    settings = replace(load_settings(env={}, env_file=None), db_path=tmp_path / "liminal.db")
    h, f = FakeHost(), FakeFetcher()
    assert server.serve_fetcher(settings, f, h, port=0, rescan=False) == "recorded"
    assert f.page_url and f.host is h and h.handle == f.handle and h.work == f.run
    port = int(f.page_url.rsplit(":", 1)[1].rstrip("/"))
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        page = conn.getresponse().read()
        assert b'<body data-mode="fetcher">' in page and b"<title>Liminal Fetcher</title>" in page
        assert b'id="viewFetcher"' in page and b'id="rqForm"' in page
        conn.request("GET", "/api/requests")
        out = json.loads(conn.getresponse().read())
        assert out["rows"] == [] and out["status"]["pid"] == 4242 and out["status"]["clients"] == [4242]
        assert out["kinds"] == ["bars", "live"]
        conn.request("POST", "/api/requests", body=json.dumps({"symbol": "aapl", "kinds": ["bars", "live", "nope"]}),
                     headers={"Content-Type": "application/json", "X-Liminal-Charts": "1"})
        r = conn.getresponse()
        row = json.loads(r.read())
        assert r.status == 202 and row["symbol"] == "AAPL" and row["kinds"] == ["bars", "live"] and row["by"] == "page"
        assert f.woken == 1  # the fetcher woken: it takes the request at once
        conn.request("DELETE", f"/api/requests/{row['id']}", headers={"X-Liminal-Charts": "1"})
        assert json.loads(conn.getresponse().read())["cancelled"] is True and f.woken == 2
        conn.request("POST", "/api/fetching", body=json.dumps({"paused": False}),
                     headers={"Content-Type": "application/json", "X-Liminal-Charts": "1"})
        assert json.loads(conn.getresponse().read())["started"] is True and f.passes == 1  # resuming asks for a pass
        assert h.touched >= 5  # every request touched the host: a page in touch keeps the fetcher up
    finally:
        h.secure()


def test_the_fetchers_page_is_the_chart_page_without_the_chart_and_what_is_the_users():
    page = server.fetcher_page().decode("utf-8")
    assert page.count('data-mode="fetcher"') == 1 and "<title>Liminal Fetcher</title>" in page
    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    hidden = css.split('body[data-mode="fetcher"] #topbar', 1)[1].split("{ display: none !important; }", 1)[0]
    for part in ("#tools", "#sidePanel", "#viewChart", "#symbolDialog", "#railProfile", 'button[data-pane="stock"]',
                 'button[data-pane="analysis"]', 'button[data-pane="trading"]', 'button[data-pane="watchlist"]',
                 'button[data-pane="prefs"]', "hr:first-of-type", "hr:last-of-type"):
        assert part in hidden, part
    for kept in ('data-pane="exchanges"', 'data-pane="markets"', 'data-pane="news"', 'data-pane="gov"',
                 'data-pane="datasets"', 'data-pane="fetcher"', 'data-pane="live"', 'data-pane="plugins"',
                 'data-pane="resources"'):
        assert kept not in hidden and kept in page, kept
    app_js = (server.STATIC / "app.js").read_text(encoding="utf-8")
    assert "const FETCHER_MODE = document.body.dataset.mode === 'fetcher';" in app_js
    start = app_js.split("(async function start() {", 1)[1]
    assert start.lstrip().startswith("if (FETCHER_MODE) {")  # no chart, no layout, no symbol on the fetcher's page
    panels = (server.STATIC / "panels.js").read_text(encoding="utf-8")
    assert "window.FETCHER_MODE && VIEWS[name] === 'chart'" in panels
