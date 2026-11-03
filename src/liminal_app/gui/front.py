"""The chart app's front: the chart page, and every request of its pages funnelled to the fetcher.

The user, 2026-11-01: "the concept is to be able to use the app, which connects to the fetcher for
database access"; "so the app needs to funnel requests through the fetcher to the databases"; "i can
look at the fetcher to see what the data looks like, i can use the 'app' to see what i want to do".

`liminal gui` runs this: a local server (127.0.0.1) serving the chart page and its scripts, with
every /api/ request of its pages passed on to the fetcher's data API (fetcher.py: the host
`fetcher`, attached here and started if none answers, its port learnt from it). No database is
opened here. A page in touch keeps the fetcher held; with none in touch for LIMINAL_QUIET_SECONDS
the front lets it go (the fetcher ends once nobody holds it, unless a service does: service.py)
and attaches again at the next request.

In mode "fetcher" the page is the fetcher's own (web.fetcher_page) and this is the integrator's
front (`liminal-integrator serve`, and its service): the page kept at the fetcher's port, 8785,
like the chart's at 8765 (the user, 2026-11-02: "i need a way to run it from the browser like the
other liminals"), while the fetcher itself comes and goes the same way, unless the service's
`--daemon` holds it for good. The fetcher's own page then takes a free port, learnt from it like
the app does.
"""
from __future__ import annotations

import http.client
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from liminal_lib import config, host
from liminal_lib.logs import log_to
from . import web
from .web import MAX_BODY, PROFILE_HEADER, WRITE_HEADER

QUIET_SECONDS = 120.0  # no page in touch for this long: the fetcher let go (LIMINAL_QUIET_SECONDS)
QUIET_CHECK_SECONDS = 15.0
# The request headers passed on to the fetcher: who the page is (its profile cookie, the page's
# profile), that it is this app's page (WRITE_HEADER), what it accepts. Not where it comes from
# (Origin, Sec-Fetch-Site: this front checked them; the fetcher takes a request saying neither)
FORWARDED = ("Cookie", "Content-Type", "Accept", "Last-Event-ID", WRITE_HEADER, PROFILE_HEADER)
PASSED_BACK = ("Content-Type", "Cache-Control", "X-Content-Type-Options")
MODES = ("chart", "fetcher")


class Front:
    """The front's hold on the fetcher: attached while its pages are in touch. `name`: whose
    front this is, in its log lines (the app's, the integrator's page)."""

    def __init__(self, db_path: Path, log=print, name: str = "the app"):
        self.db_path = Path(db_path)
        self.log = log
        self.name = name
        self._lock = threading.Lock()
        self._att = None
        self._port: int | None = None
        self._last_contact = time.monotonic()
        self._woken = False

    def quiet_seconds(self) -> float:
        try:
            return float(config.setting("LIMINAL_QUIET_SECONDS") or QUIET_SECONDS)
        except ValueError:
            return QUIET_SECONDS

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._att is not None and self._port is not None

    def fetcher_port(self) -> int | None:
        """The fetcher's data port, attached to it (started if none answers; the port asked of it).
        None: no fetcher answers, or it has no page."""
        with self._lock:
            self._last_contact = time.monotonic()
            self._woken = True
            if self._att is not None and self._port is not None and self._att.alive():
                return self._port
            self._port = None
            self._att = host.attach_fetcher(self.db_path, log=self.log)
            if self._att is None:
                return None
            try:
                answer = self._att.ask(status=True)
            except (OSError, EOFError, ValueError):
                answer = None
            page = (answer or {}).get("page") if isinstance(answer, dict) else None
            port = urlsplit(page).port if page else None
            if not port:
                self.log(f"the fetcher has no page (LIMINAL_FETCHER_PORT=none): {self.name} cannot reach its data")
                return None
            self._port = port
            self.log(f"{self.name} is connected to the fetcher at {page}")
            return port

    def let_go(self) -> bool:
        """The fetcher let go (it ends once nobody holds it). Whether it was held."""
        with self._lock:
            att, self._att, self._port = self._att, None, None
        if att is None:
            return False
        att.detach()
        return True

    def watch_quiet(self, stop: threading.Event | None = None) -> None:
        """Lets the fetcher go once no page has been in touch for quiet_seconds (a thread)."""
        stop = stop or threading.Event()
        while not stop.wait(QUIET_CHECK_SECONDS):
            with self._lock:
                due = self._att is not None and self._woken and time.monotonic() - self._last_contact >= self.quiet_seconds()
            if due and self.let_go():
                self.log(f"quiet: no page in touch for {self.quiet_seconds():g} s; the fetcher is let go")


def make_front_handler(front: Front, mode: str = "chart"):
    """The front's requests: the page's files from here, /api/ passed on to the fetcher. The page
    is the chart's (a profile's: the login page first without one) or, in mode "fetcher", the
    fetcher's own (nobody's)."""
    if mode not in MODES:
        raise ValueError(f"front: no mode {mode!r} (one of {', '.join(MODES)})")

    class Handler(BaseHTTPRequestHandler):
        server_version = "liminal-front"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # what the fetcher's server checks and sends the same way is shared (web.py)
        def _send(self, status: int, body: bytes, ctype: str, headers: list[tuple[str, str]] | None = None) -> None:
            web.send(self, status, body, ctype, headers)

        def _json(self, data, status: int = 200) -> None:
            web.send_json(self, data, status)

        def _local(self) -> bool:
            return web.local_only(self)

        def _from_this_app(self) -> bool:
            return web.from_this_app(self)  # another site's page never reaches the fetcher through here

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
            """The request passed on to the fetcher's data API, its answer passed back (an event
            stream as it comes)."""
            raw_length = self.headers.get("Content-Length") or "0"
            length = int(raw_length) if raw_length.isdecimal() else -1
            if length < 0:
                return self._json({"error": "bad Content-Length"}, HTTPStatus.BAD_REQUEST)
            if length > MAX_BODY:
                return self._json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            body = self.rfile.read(length) if length else None
            port = front.fetcher_port()
            if port is None:
                return self._json({"error": f"the fetcher is not running (none answered, none could be started): "
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
                front.let_go()  # gone: attached (and started) again at the next request
                return self._json({"error": "the fetcher does not answer; ask again shortly"}, HTTPStatus.SERVICE_UNAVAILABLE)
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
            if rel == "index.html" and mode == "fetcher":  # the fetcher's own page: nobody's, no profile
                return self._send(HTTPStatus.OK, web.fetcher_page(), "text/html; charset=utf-8")
            # a browser signed in as no profile (its cookie; whether it still exists is the fetcher's
            # to check) picks or makes one first
            if rel == "index.html" and web.profile_cookie(self) is None:
                rel = "login.html"
            web.static_file(self, rel)

    return Handler


def serve_front(db_path: Path, port: int = 8765, open_browser: bool = True, log=None, mode: str = "chart",
                stop: threading.Event | None = None) -> None:
    """The chart app: its page here, its data through the fetcher (attached at the first page).
    In mode "fetcher" the fetcher's own page instead, at the fetcher's port (`liminal-integrator
    serve`; its service, which passes `stop`). On `port`, or a free one when it is taken; until
    Ctrl+C or `stop` is set, then the fetcher is let go."""
    log = log or log_to(db_path)
    fetchers = mode == "fetcher"
    front = Front(db_path, log, name="the integrator's page" if fetchers else "the app")
    stop = stop or threading.Event()
    threading.Thread(target=front.watch_quiet, args=(stop,), name="front-quiet", daemon=True).start()
    if port and web.listening(port):  # a bind alone cannot tell on Windows (web.listening)
        log(f"front: port {port} is taken (another server answers there): a free one instead")
        port = 0
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_front_handler(front, mode))
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_front_handler(front, mode))  # port taken: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    log(f"front: {'the fetcher' if fetchers else 'the chart'}'s page at {url}, its data through the fetcher")
    print(f"the fetcher's page at {url}; the fetcher runs while a page is in touch  (Ctrl+C to stop)" if fetchers else
          f"chart app running at {url}, its data through the fetcher  (Ctrl+C to stop)", flush=True)
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
        front.let_go()
