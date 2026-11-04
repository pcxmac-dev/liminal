"""The chart app's front: the chart page, and every request of its pages funnelled to the integrator.

The user, 2026-11-01: "the concept is to be able to use the app, which connects to the fetcher for
database access"; "so the app needs to funnel requests through the fetcher to the databases"; "i can
look at the fetcher to see what the data looks like, i can use the 'app' to see what i want to do".
2026-11-03: "for the webserver / ports, i just integrator, and charts": two listeners on this
machine, the integrator's page and data API (liminal-integrator, LIMINAL_FETCHER_PORT: 8785) and this
front (8765); the fetcher host itself has no HTTP of its own.

`liminal-charts gui` runs this: a local server (127.0.0.1) serving the chart page and its scripts, with
every /api/ request of its pages passed on to the integrator's data API at its port. No database is
opened here, and no pipe: the integrator holds the fetcher while a page is in touch. When nothing
answers at the integrator's port, the front starts the integrator's server for itself
(`liminal-integrator serve --no-browser --until-quiet`: no window, outliving this process; it ends
again once no page has been in touch for LIMINAL_QUIET_SECONDS), unless the integrator's service
keeps it there from the user's logon (service.py).
"""
from __future__ import annotations

import http.client
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from liminal_libs import config
from liminal_libs.logs import log_to
from . import web
from .web import MAX_BODY, PROFILE_HEADER, WRITE_HEADER

INTEGRATOR_PORT = 8785  # the integrator's page and data API (LIMINAL_FETCHER_PORT; none: no page)
START_SECONDS = 30.0  # how long the front waits for an integrator it started to answer
# The request headers passed on to the integrator: who the page is (its profile cookie, the page's
# profile), that it is this app's page (WRITE_HEADER), what it accepts. Not where it comes from
# (Origin, Sec-Fetch-Site: this front checked them; the integrator takes a request saying neither)
FORWARDED = ("Cookie", "Content-Type", "Accept", "Last-Event-ID", WRITE_HEADER, PROFILE_HEADER)
PASSED_BACK = ("Content-Type", "Cache-Control", "X-Content-Type-Options")


def integrator_port() -> int | None:
    """The port of the integrator's page and data API (LIMINAL_FETCHER_PORT, 8785). None: no page at
    all (none, off), or a free one (0) this front cannot know."""
    raw = (config.setting("LIMINAL_FETCHER_PORT") or "").strip().lower()
    if raw in ("none", "off"):
        return None
    try:
        port = int(raw) if raw else INTEGRATOR_PORT
    except ValueError:
        return INTEGRATOR_PORT
    return port or None


def start_integrator(db_path: Path, port: int, log=print) -> bool:
    """Start the integrator's server for this front (`liminal-integrator serve --no-browser --port
    PORT --until-quiet`): no window, outliving this process, on this database (LIMINAL_DB in its
    environment); it ends again once no page has been in touch for a while. False: the integrator is
    not installed (liminal-integrator: the app's `integrator` extra)."""
    try:
        import liminal_integrator  # noqa: F401 - whether it is there
    except ImportError:
        log("the integrator is not installed (liminal-integrator, the app's `integrator` extra): the app has no data to show")
        return False
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe") if os.name == "nt" and exe.with_name("pythonw.exe").exists() else exe
    flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0  # DETACHED | NEW_GROUP | NO_WINDOW
    env = {**os.environ, "LIMINAL_DB": str(db_path)}
    subprocess.Popen([str(pythonw), "-m", "liminal_integrator", "serve", "--no-browser", "--port", str(port), "--until-quiet"],
                     creationflags=flags, close_fds=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    log(f"the integrator's server started for the app at port {port}")
    return True


class Front:
    """The front's way to the integrator's data API: at the integrator's port, the integrator
    started for it when nothing answers there."""

    def __init__(self, db_path: Path, log=print, name: str = "the app"):
        self.db_path = Path(db_path)
        self.log = log
        self.name = name
        self._lock = threading.Lock()
        self._port: int | None = None  # the port answered at last

    @property
    def connected(self) -> bool:
        return self._port is not None and web.listening(self._port)

    def integrator_port(self) -> int | None:
        """The integrator's port, answering: the one set, or the integrator started for it and
        waited for (START_SECONDS). None: no page (LIMINAL_FETCHER_PORT), or none could be started."""
        port = integrator_port()
        if port is None:
            self.log(f"the integrator has no page (LIMINAL_FETCHER_PORT): {self.name} cannot reach its data")
            return None
        if web.listening(port):
            if self._port != port:
                self._port = port
                self.log(f"{self.name} is connected to the integrator at http://127.0.0.1:{port}/")
            return port
        with self._lock:
            if web.listening(port):
                return port
            self._port = None
            if not start_integrator(self.db_path, port, self.log):
                return None
            end = time.monotonic() + START_SECONDS
            while time.monotonic() < end:
                time.sleep(0.25)
                if web.listening(port):
                    self._port = port
                    self.log(f"{self.name} is connected to the integrator at http://127.0.0.1:{port}/")
                    return port
        self.log(f"the integrator started for {self.name} never answered at port {port}; see logs/liminal.log")
        return None


def make_front_handler(front: Front):
    """The front's requests: the page's files from here, /api/ passed on to the integrator. The page
    is the chart's (a profile's: the login page first without one)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "liminal-front"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # what the integrator's server checks and sends the same way is shared (web.py)
        def _send(self, status: int, body: bytes, ctype: str, headers: list[tuple[str, str]] | None = None) -> None:
            web.send(self, status, body, ctype, headers)

        def _json(self, data, status: int = 200) -> None:
            web.send_json(self, data, status)

        def _local(self) -> bool:
            return web.local_only(self)

        def _from_this_app(self) -> bool:
            return web.from_this_app(self)  # another site's page never reaches the integrator through here

        def do_GET(self) -> None:
            if not self._local():
                return
            if self.path.startswith("/api/"):
                if self._from_this_app():
                    self._proxy("GET")
                return
            self._static(urlsplit(self.path).path)

        def _write(self, method: str) -> None:
            if not self._local() or not self._from_this_app():
                return
            if self.headers.get(WRITE_HEADER) != "1":
                return self._send(HTTPStatus.FORBIDDEN, b"missing request header", "text/plain")
            self._proxy(method)

        def do_POST(self) -> None:
            self._write("POST")

        def do_PUT(self) -> None:
            self._write("PUT")

        def do_DELETE(self) -> None:
            self._write("DELETE")

        def _proxy(self, method: str) -> None:
            """The request passed on to the integrator's data API, its answer passed back (an event
            stream as it comes)."""
            raw_length = self.headers.get("Content-Length") or "0"
            length = int(raw_length) if raw_length.isdecimal() else -1
            if length < 0:
                return self._json({"error": "bad Content-Length"}, HTTPStatus.BAD_REQUEST)
            if length > MAX_BODY:
                return self._json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            body = self.rfile.read(length) if length else None
            port = front.integrator_port()
            if port is None:
                return self._json({"error": f"the integrator is not running (none answers, none could be started): "
                                            f"{front.name} has no data to show; see logs/liminal.log"},
                                  HTTPStatus.SERVICE_UNAVAILABLE)
            headers = {name: value for name in FORWARDED if (value := self.headers.get(name)) is not None}
            headers["Host"] = f"127.0.0.1:{port}"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=None)
            try:
                conn.request(method, self.path, body=body, headers=headers)
                resp = conn.getresponse()
            except OSError:
                conn.close()
                return self._json({"error": "the integrator does not answer; ask again shortly"}, HTTPStatus.SERVICE_UNAVAILABLE)
            try:
                ctype = resp.getheader("Content-Type") or "application/octet-stream"
                passed = [(name, value) for name in PASSED_BACK if (value := resp.getheader(name)) is not None]
                passed += [("Set-Cookie", c) for c in resp.msg.get_all("Set-Cookie") or []]
                if ctype.startswith("text/event-stream"):
                    self.send_response(resp.status)
                    for name, value in passed:
                        self.send_header(name, value)
                    self.end_headers()
                    try:
                        while chunk := resp.read1(65536):
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass  # the page went away
                    return
                data = resp.read()
                self._send(resp.status, data, ctype, passed)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the page went away
            finally:
                conn.close()

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            # a browser signed in as no profile (its cookie; whether it still exists is the integrator's
            # to check) picks or makes one first
            if rel == "index.html" and web.profile_cookie(self) is None:
                rel = "login.html"
            web.static_file(self, rel)

    return Handler


def serve_front(db_path: Path, port: int = 8765, open_browser: bool = True, log=None,
                stop: threading.Event | None = None) -> None:
    """The chart app: its page here, its data through the integrator (started for it when nothing
    answers at its port). On `port`, or a free one when it is taken; until Ctrl+C or `stop` is set."""
    log = log or log_to(db_path)
    front = Front(db_path, log)
    stop = stop or threading.Event()
    if port and web.listening(port):  # a bind alone cannot tell on Windows (web.listening)
        log(f"front: port {port} is taken (another server answers there): a free one instead")
        port = 0
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_front_handler(front))
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_front_handler(front))  # port taken: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    log(f"front: the chart's page at {url}, its data through the integrator")
    print(f"chart app running at {url}, its data through the integrator  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    def stopping() -> None:
        stop.wait()
        httpd.shutdown()

    threading.Thread(target=stopping, name="front-stop", daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
