"""The chart app's front (gui/front.py): the chart page here, every request of its pages funnelled
to the fetcher's data API (the user, 2026-11-01: "the app needs to funnel requests through the
fetcher to the databases"). The fetcher stands in as a small server here; no process starts."""
from __future__ import annotations

import json
import re
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from liminal_lib import host as hosting
from liminal_app.gui import front as front_mod, web
from liminal_app.gui.front import Front, make_front_handler


class FakeAttachment:
    def __init__(self, page):
        self.page, self.detached, self.host_pid = page, False, 4242

    def alive(self):
        return not self.detached

    def detach(self):
        self.detached = True

    def ask(self, **what):
        return {"page": self.page, "busy": False}


class Upstream(BaseHTTPRequestHandler):
    """The fetcher's data API, as far as the front needs one: it echoes what it got."""

    def log_message(self, *a):
        pass

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "mc_profile=7; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(2):
                self.wfile.write(f"data: {i}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
            return
        self._json(200, {"path": self.path, "origin": self.headers.get("Origin"), "site": self.headers.get("Sec-Fetch-Site"),
                         "cookie": self.headers.get("Cookie"), "host": self.headers.get("Host"),
                         "profile": self.headers.get("X-Liminal-Profile")})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        self._json(202, {"got": json.loads(data or b"{}"), "write": self.headers.get("X-Liminal-Charts")})


@pytest.fixture
def upstream():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    yield up
    up.shutdown()
    up.server_close()


def _get(port, path, headers=None):
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", path, headers=headers or {})
    r = conn.getresponse()
    return r.status, r.read(), r


def test_the_front_funnels_its_pages_requests_to_the_fetcher(tmp_path, monkeypatch, upstream):
    page = f"http://127.0.0.1:{upstream.server_address[1]}/"
    att = FakeAttachment(page)
    monkeypatch.setattr(hosting, "attach_or_start", lambda name, db, log=print: att)
    lines: list[str] = []
    front = Front(tmp_path / "liminal.db", log=lines.append)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_front_handler(front))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert not front.connected
        status, body, r = _get(port, "/api/echo?x=1", {"Cookie": "mc_profile=3", "Origin": f"http://127.0.0.1:{port}",
                                                         "Sec-Fetch-Site": "same-origin", "X-Liminal-Profile": "3"})
        j = json.loads(body)
        assert status == 200 and j["path"] == "/api/echo?x=1" and j["cookie"] == "mc_profile=3" and j["profile"] == "3"
        assert j["origin"] is None and j["site"] is None  # where it came from was checked here, not passed on
        assert j["host"] == f"127.0.0.1:{upstream.server_address[1]}"
        assert r.getheader("Set-Cookie") == "mc_profile=7; Path=/"  # the fetcher's cookie passed back
        assert front.connected and any("connected to the fetcher" in m for m in lines)
        # another site's page is refused here, before the fetcher sees it
        assert _get(port, "/api/echo", {"Origin": "http://evil.example"})[0] == 403
        assert _get(port, "/api/echo", {"Host": "evil.example"})[0] == 403
        # a write needs the app's own header, and goes through with its body
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("POST", "/api/requests", body=json.dumps({"symbol": "AAPL"}),
                     headers={"Content-Type": "application/json", "X-Liminal-Charts": "1"})
        r = conn.getresponse()
        assert r.status == 202 and json.loads(r.read()) == {"got": {"symbol": "AAPL"}, "write": "1"}
        conn.request("POST", "/api/requests", body=b"{}", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 403
        # the event stream comes through as it is sent
        status, body, r = _get(port, "/api/stream?since=1")
        assert status == 200 and body == b"data: 0\n\ndata: 1\n\n" and r.getheader("Content-Type").startswith("text/event-stream")
        # the pages: the login page without a profile, the chart page with one (not the fetcher's), nothing outside
        status, body, _ = _get(port, "/")
        assert status == 200 and b"<title>Liminal Charts" in body and b'id="rail"' not in body
        status, body, _ = _get(port, "/", {"Cookie": "mc_profile=1"})
        assert status == 200 and b'id="rail"' in body and b'data-mode="fetcher"' not in body
        assert _get(port, "/style.css")[0] == 200 and _get(port, "/../pyproject.toml")[0] == 404
        # quiet: no page in touch for a while, the fetcher let go; the next request attaches again
        monkeypatch.setattr(front, "quiet_seconds", lambda: 0.2)
        monkeypatch.setattr(front_mod, "QUIET_CHECK_SECONDS", 0.05)
        stop = threading.Event()
        threading.Thread(target=front.watch_quiet, args=(stop,), daemon=True).start()
        end = time.monotonic() + 5
        while front.connected and time.monotonic() < end:
            time.sleep(0.02)
        stop.set()
        assert not front.connected and att.detached and lines[-1].startswith("quiet: no page in touch")
        again = FakeAttachment(page)
        monkeypatch.setattr(hosting, "attach_or_start", lambda name, db, log=print: again)
        assert _get(port, "/api/echo")[0] == 200 and front.connected and not again.detached
        # no fetcher answers at all: the page is told, nothing else
        front.let_go()
        monkeypatch.setattr(hosting, "attach_or_start", lambda name, db, log=print: None)
        status, body, _ = _get(port, "/api/echo")
        assert status == 503 and b"the fetcher is not running" in body
    finally:
        srv.shutdown()
        srv.server_close()
        front.let_go()


def test_the_front_in_fetcher_mode_is_the_integrators_page(tmp_path, monkeypatch, upstream):
    """`liminal-integrator serve` and its service (the user, 2026-11-02: "i need a way to run it from
    the browser like the other liminals"): the fetcher's own page at its port, nobody's (no login),
    its data through the fetcher like the chart's; serve_front ends when told to stop."""
    page = f"http://127.0.0.1:{upstream.server_address[1]}/"
    att = FakeAttachment(page)
    monkeypatch.setattr(hosting, "attach_or_start", lambda name, db, log=print: att)
    lines: list[str] = []
    front = Front(tmp_path / "liminal.db", log=lines.append, name="the integrator's page")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_front_handler(front, mode="fetcher"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for headers in ({}, {"Cookie": "mc_profile=1"}):  # the same page whoever the browser signed in as
            status, body, _ = _get(port, "/", headers)
            assert status == 200 and b'data-mode="fetcher"' in body and b"<title>Liminal Fetcher" in body
        assert _get(port, "/app.js")[0] == 200
        assert json.loads(_get(port, "/api/queue")[1])["path"] == "/api/queue" and front.connected
        assert any(m.startswith("the integrator's page is connected to the fetcher") for m in lines)
    finally:
        srv.shutdown()
        srv.server_close()
        front.let_go()
    assert att.detached
    with pytest.raises(ValueError):
        make_front_handler(front, mode="plots")
    # serve_front itself, as the service runs it: on the port asked, or a free one when something
    # answers there already (on Windows a second server binds a port in use), until told to stop
    taken = upstream.server_address[1]
    assert web.listening(taken)
    stop = threading.Event()
    done = threading.Event()

    def run():
        front_mod.serve_front(tmp_path / "liminal.db", port=taken, open_browser=False, log=lines.append, mode="fetcher", stop=stop)
        done.set()
    threading.Thread(target=run, daemon=True).start()
    end = time.monotonic() + 5
    while not (urls := [m for m in lines if m.startswith("front: the fetcher's page at")]) and time.monotonic() < end:
        time.sleep(0.02)
    served = int(re.search(r"http://127\.0\.0\.1:(\d+)/", urls[0]).group(1))
    assert served != taken and any(f"port {taken} is taken" in m for m in lines)
    assert b'data-mode="fetcher"' in _get(served, "/")[1]
    stop.set()
    assert done.wait(5)
    assert not web.listening(served)


def test_the_gui_command_runs_the_front_unless_alone(tmp_path, monkeypatch):
    from liminal_app import cli
    from liminal_app.gui import front, server

    ran: list = []
    monkeypatch.setattr(front, "serve_front", lambda db_path, port=8765, open_browser=True, log=None: ran.append(("front", port, open_browser)))
    monkeypatch.setattr(server, "serve", lambda *a, **kw: ran.append(("alone", kw.get("port"))))
    settings = cli.load_settings(env={}, env_file=None)
    monkeypatch.delenv("LIMINAL_NO_RESCAN", raising=False)
    args = cli.build_parser().parse_args(["gui", "--no-browser", "--port", "8770", "--no-rescan"])
    assert cli.cmd_gui(args, settings) == 0 and ran == [("front", 8770, False)]
    assert front_mod.config.setting("LIMINAL_NO_RESCAN") or __import__("os").environ.get("LIMINAL_NO_RESCAN") == "1"
    args = cli.build_parser().parse_args(["gui", "--alone", "--no-browser"])
    assert cli.cmd_gui(args, settings) == 0 and ran[-1] == ("alone", 8765)
