"""Setting plugins up in the Plugins view (the user, 2026-10-31: "i need a way to setup plugins inside
the plugin interface in the main window, for all plugins, including keys, user details etc"): every
variable a plugin reads is declared by it (KeyVar on a Provider or a Publisher: plugin API 1.3), typed
in its Setup and saved as a user environment variable, never sent back. And Massive's headlines are
part of the Massive plugin ("massive headlines needs to be rolled in to Massive")."""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from massive_collate import config, publications
from massive_collate.gov import GovDB
from massive_collate.sources import keys, publishers, registry

from .test_plugin_plans import _choosing_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "massive_collate" / "gui" / "static"


def test_every_variable_a_plugin_reads_is_declared_by_it():
    assert [k.name for k in registry.plugin_keys("massive")] == ["MASSIVE_API_KEY"]
    # a plugin's feeds read its keys: each listed once (Alpaca's Blue Ocean on Alpaca's)
    assert [k.name for k in registry.plugin_keys("alpaca")] == ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]
    assert registry.plugin_keys("bitstamp") == [] and registry.plugin_keys("cftc") == []
    # a detail of yours, declared by the agency that asks for it: typed in the open, never shown back
    contact = registry.plugin_keys("sec")[0]
    assert (contact.name, contact.secret) == ("GOV_CONTACT", False) and contact.hint
    assert registry.plugin_keys("federal") == [contact]  # the plugin's Setup holds its parts' too
    # read from the saved user variables because a plugin declares it (no list of names elsewhere)
    assert "GOV_CONTACT" in config.saved_names() and not hasattr(config, "SAVED_NAMES")
    assert "GOV_CONTACT" in registry.variables()


def test_a_typed_value_is_one_line_of_sane_length():
    assert keys.clean("  abc  ") == "abc"
    for bad in ("", "   ", "a\nb", "a\tb", "x" * (keys.MAX_LENGTH + 1)):
        with pytest.raises(ValueError):
            keys.clean(bad)


def test_massive_headlines_are_part_of_the_massive_plugin():
    pubs = publishers()
    assert pubs["massive-news"].part_of == "massive" and pubs["massive-news"].account == "massive"
    assert registry.publisher_of("massive-news") == "massive" and registry.publisher_parts("massive") == ["massive-news"]
    rows = {r["name"]: r for r in registry.menu()}
    assert [p["name"] for p in rows["massive"]["publishers"]] == ["massive-news"]
    assert all(r["publishers"] == [] for n, r in rows.items() if n != "massive")
    assert "massive-news" not in [r["name"] for r in registry.publisher_menu()]  # no longer a plugin of its own
    view = {p["name"]: p for p in publications.view(GovDB(None), publishers=pubs)}
    assert view["massive-news"]["partOf"] == "massive" and view["fed"]["partOf"] == "federal"


def test_setup_saves_a_key_and_never_sends_it_back(tmp_path, monkeypatch):
    store, app, wrote = _choosing_app(tmp_path, monkeypatch)
    try:
        out = app.set_key("tiingo", "TIINGO_API_KEY", "  fresh-key  ")
        assert out == {"plugin": "tiingo", "variable": "TIINGO_API_KEY", "set": True}
        assert wrote == [("TIINGO_API_KEY", "fresh-key")]  # trimmed, saved where the key script saves it
        assert app.settings.env.get("TIINGO_API_KEY") == "fresh-key"  # the app uses it at once
        view = app.plugins()
        assert "fresh-key" not in json.dumps(view)
        tiingo = next(p for p in view["plugins"] if p["name"] == "tiingo")
        assert [(k["name"], k["set"]) for k in tiingo["keys"]] == [("TIINGO_API_KEY", True)]
        # a detail of yours: on the agency, or on its plugin as a whole
        app.set_key("federal", "GOV_CONTACT", "Pat Roe pat@test.invalid")
        app.set_key("sec", "GOV_CONTACT", "Pat Roe pat@test.invalid")
        assert wrote[-1] == ("GOV_CONTACT", "Pat Roe pat@test.invalid")
        by = {p["name"]: p for p in app.publishers()}
        assert by["federal"]["keys"][0]["set"] and by["sec"]["keys"][0]["set"]
        assert "pat@test.invalid" not in json.dumps(by)
        assert app.set_key("tiingo", "TIINGO_API_KEY", None)["set"] is False  # removed
        assert wrote[-1] == ("TIINGO_API_KEY", None)
        n = len(wrote)
        for plugin, variable in (("tiingo", "MASSIVE_API_KEY"), ("bitstamp", "X"), ("nowhere", "TIINGO_API_KEY"),
                                 ("tiingo", "TIINGO_PLAN"), ("fed", "GOV_CONTACT")):
            with pytest.raises(LookupError):
                app.set_key(plugin, variable, "x")  # only what that plugin declares (a plan is chosen, not typed)
        for bad in ("", "a\nb", "x" * 600):
            with pytest.raises(ValueError):
                app.set_key("tiingo", "TIINGO_API_KEY", bad)
        assert len(wrote) == n
    finally:
        store.close()


def test_an_offline_copy_saves_no_key(tmp_path, monkeypatch):
    store, app, wrote = _choosing_app(tmp_path, monkeypatch, offline=True)
    try:
        with pytest.raises(RuntimeError, match="saves no settings"):
            app.set_key("tiingo", "TIINGO_API_KEY", "k")  # it shares your real user variables
        assert wrote == []
    finally:
        store.close()


def test_the_key_route_takes_only_this_apps_pages_and_answers_no_value(tmp_path, monkeypatch):
    from massive_collate.gui.server import make_handler

    store, app, wrote = _choosing_app(tmp_path, monkeypatch)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, [0]))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def post(body, header=True):
        c = HTTPConnection("127.0.0.1", port)
        headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **({"X-Massive-Charts": "1"} if header else {})}
        c.request("POST", "/api/plugins/key", body=json.dumps(body), headers=headers)
        r = c.getresponse()
        raw = r.read()
        return r.status, raw

    try:
        assert post({"plugin": "tiingo", "variable": "TIINGO_API_KEY", "value": "route-key"}, header=False)[0] == 403
        assert wrote == []
        status, raw = post({"plugin": "tiingo", "variable": "TIINGO_API_KEY", "value": "route-key"})
        assert status == 200 and b"route-key" not in raw and json.loads(raw)["set"] is True
        assert wrote == [("TIINGO_API_KEY", "route-key")]
        status, raw = post({"plugin": "tiingo", "variable": "TIINGO_API_KEY", "value": "a\nroute-key"})
        assert status == 400 and b"route-key" not in raw  # refused without echoing it
        assert post({"plugin": "tiingo", "variable": "MASSIVE_API_KEY", "value": "k"})[0] == 404
        assert json.loads(post({"plugin": "tiingo", "variable": "TIINGO_API_KEY", "value": None})[1])["set"] is False
    finally:
        httpd.shutdown()
        store.close()


def test_the_page_sets_each_plugin_up_and_shows_headlines_in_massives_page():
    js = (STATIC / "plugins.js").read_text(encoding="utf-8")
    assert "function setupHtml(owner, keys, account)" in js and "'/api/plugins/key'" in js
    assert "${setupHtml(p.name, p.keys)}" in js and "return `${err}<h4>Feeds</h4>" in js
    assert "type=\"${k.secret ? 'password' : 'text'}\"" in js and 'autocomplete="off"' in js
    assert "input.value = '';  // sent once; never kept in the page" in js
    assert "window.confirm(`Remove ${t.dataset.removeKey}" in js
    assert "const typed = [...box.querySelectorAll('input.pl-key')]" in js  # typing survives the refreshes
    assert "${pubs.map((q) => partHtml(q, pubs.length === 1)).join('')}" in js  # a section, open when alone
    assert "function publishersHtml(p)" in js and "function parentOf(p)" in js and "${pubSetupHtml(p)}${fetchingHtml(p.name)}${readsHtml(p)}" in js
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".pl-setup input.pl-key {" in css


def test_no_plugin_sets_a_system_variable_or_another_plugins(tmp_path, monkeypatch):
    from massive_collate.sources.publisher import Policy, Publisher

    for name in ("PATH", "PYTHONPATH", "TEMP", "MASSIVE_DB", "MASSIVE_OFFLINE", "lower", "A-B", ""):
        assert keys.refusal(name), name
    assert keys.refusal("GOV_CONTACT") is None and keys.refusal("TIINGO_API_KEY") is None
    rogue = Publisher("rogue", "Rogue", "", (), Policy(), api="1.3",
                      keys=(keys.KeyVar("PATH"), keys.KeyVar("MASSIVE_API_KEY")))
    monkeypatch.setattr(registry, "_entry_points", lambda: [type("EP", (), {"name": "rogue", "value": "pkg:rogue",
                                                                              "load": lambda self: rogue})()])
    try:
        registry.reload()
        store, app, wrote = _choosing_app(tmp_path, monkeypatch)
        try:
            for variable in ("PATH", "MASSIVE_API_KEY"):
                with pytest.raises(LookupError):
                    app.set_key("rogue", variable, "x")  # declared, but never its to write
            with pytest.raises(LookupError, match="declared by massive, rogue"):
                app.set_key("massive", "MASSIVE_API_KEY", "x")  # nor Massive's own while another claims it
            assert wrote == []
        finally:
            store.close()
    finally:
        registry._providers = None
