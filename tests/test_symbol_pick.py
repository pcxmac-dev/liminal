"""A symbol you pick stays (the user, 2026-11-02: "when i select 'ELME' it goes back to SPCX"): the
start's layout opened its own symbol after the pick, on a database whose symbol list takes seconds.
There is no JavaScript runtime in the suite: these read the page's script."""
from __future__ import annotations

from pathlib import Path

from liminal_app.gui import server

APP_JS = (Path(server.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    return APP_JS.split(f"function {name}(", 1)[1].split("\n}\n", 1)[0]


def test_the_starts_layout_never_opens_its_symbol_over_one_you_picked():
    assert "state.userPick = state.picked;" in _function("openSymbol")
    assert "if (sym && !state.userPick) await selectSymbol(sym.ticker, sym.source);" in _function("applyLayout")
    assert "state.userPick = null;" in _function("loadLayout")  # a layout you open yourself opens its symbol
    assert "userPick: null," in APP_JS.split("const state = {", 1)[1].split("\n};", 1)[0]


def test_the_symbol_list_is_asked_for_once_while_on_its_way():
    load = _function("loadSymbols")
    assert "if (!symbolsLoading)" in load and "return symbolsLoading;" in load
    assert ".finally(() => { symbolsLoading = null; })" in load


def test_the_fetchers_page_says_what_it_is_in_the_status_bar():
    start = APP_JS.split("(async function start() {", 1)[1].split("\n  }\n", 1)[0]
    assert "$('statusText').textContent = 'The fetcher:" in start
