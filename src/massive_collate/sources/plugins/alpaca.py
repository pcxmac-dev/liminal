"""Alpaca (alpaca.markets): US stocks with keys (SIP from 2016, IEX live), crypto without; and
Blue Ocean's overnight session through the same keys, a feed of its own (BOATS).

Its scan finds the plan: Algo Trader Plus serves the consolidated tape's latest 15 minutes, Basic
refuses them; it sets ALPACA_PLAN where you have not.

Blue Ocean ATS (blueocean-tech.io) through Alpaca (the user, 2026-10-29: "the Blue Ocean plugin is
part of alpaca"): US stocks overnight, 20:00-04:00 ET, Sunday to Thursday nights; the fourth session
(sessions.py). Its own market, the only venue trading then, so its own feed (`boats`: its database,
ledgers and watchlist rows), listed and rescanned inside this plugin (Provider.part_of). It uses
Alpaca's keys and shares Alpaca's limits (the same account): one rate window and one daily cap for
both feeds, so together they stay within the free Basic plan. (Tiingo has it too, as a paid add-on:
tiingo.py's scan reports it.)"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from ...config import ALPACA_TIERS, ConfigError
from ..alpaca import PAGE_LIMIT, TRADING_URLS, AlpacaClient, AlpacaSource, BoatsSource, normalize_trade
from ..registry import KeyVar, Provider, Scanned, limiter, machine_caps
from ..stream import PING, Live, Notice, Refused

IEX_FEED = "iex"  # its live stream's feed: IEX's trades, one venue's share (alpaca (iex))


def build(settings, request_budget):
    """Builds without keys too: crypto needs none, and stock requests are refused before sending."""
    a = settings.alpaca
    if a is None:
        raise ConfigError("Alpaca settings missing")
    client = AlpacaClient(a.key_id, a.secret_key, trading_url=TRADING_URLS[a.paper],
                          rate_limiter=limiter("alpaca", settings, a.key_id), request_budget=request_budget)
    return AlpacaSource(machine_caps(client, "alpaca", settings, a.key_id), feed=a.feed, crypto_loc=a.crypto_loc,
                        realtime=a.tier.name == "alpaca-plus")


def view(base):
    a = base.alpaca
    if a is None:
        return base
    return replace(base, tier=a.tier, max_requests_per_run=a.max_requests_per_run,
                   max_requests_per_day=a.max_requests_per_day, origin=base)


def markets(settings):
    a = settings.alpaca
    loc = a.crypto_loc if a else "us-1"
    return {"stock": a.feed if a else "sip", "crypto": "alpaca" if loc == "us" else "kraken"}


def scan(source) -> list[tuple[str, bool, str]] | Scanned:
    """What the plan gives (one request each): the consolidated tape's minute bars, crypto's, and
    with keys its latest 15 minutes, which tell the plans apart."""
    stocks = source.is_entitled("minute", "AAPL", "stock")
    crypto = source.is_entitled("minute", "BTCUSD", "crypto")
    rows = [("stock minute bars, every exchange (SIP), from 2016", stocks,
             "" if stocks else "refused (keys or plan)"),
            ("crypto minute bars, no key", crypto, "")]
    if not stocks:
        return rows  # no keys, or refused: nothing tells the plan
    recent = source.recent_allowed("AAPL")
    plan = "algo_trader_plus" if recent else "basic"
    rows.append(("stock bars of the latest 15 minutes (Algo Trader Plus)", recent,
                 f"plan: {'Algo Trader Plus' if recent else 'Basic (free)'}"))
    return Scanned(tuple(rows), {"ALPACA_PLAN": plan})


# Alpaca stream errors that end the session, and the seconds to wait before connecting again:
# 401 not authenticated, 402 auth failed, 404 auth timeout, 406 connection limit exceeded (another
# connection on the account), 407 slow client, 409 insufficient subscription, 500 internal error.
ALPACA_REFUSALS = {401: 60, 402: 600, 404: 60, 406: 120, 407: 60, 409: 3600, 500: 60}


@dataclass
class AlpacaIexStream:
    """Alpaca's free real-time stock stream (v2/iex): every trade on IEX, with cancels and
    corrections (the trades they withdraw are marked `withdrawn`). The keys go in the auth
    message only, never in a log. Its symbols change while it is connected (`change`), once the
    server has accepted the keys; `confirmed` holds those the server says it streams."""
    key_id: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    source: str = IEX_FEED
    url: str = "wss://stream.data.alpaca.markets/v2/iex"
    keepalive: str | None = PING
    dynamic: bool = True  # symbols from the charts (and watchlists: wanted_stocks), not LIVE_COINS
    asset: str = "stock"
    tape_rules: bool = True  # bars by the consolidated tape's rules per trade condition (ticks.py)
    method: str = ("IEX's trades from Alpaca's real-time stream: one exchange, a few per cent of US volume; "
                   "bars rebuilt as trades arrive (a forming bar changes until it closes), by the consolidated "
                   "tape's rules per trade condition; a feed of the whole market (SIP) ranks above them")
    authed: bool = False
    confirmed: frozenset = frozenset()

    def subscribe(self, symbols) -> list[str]:
        """The first messages on a new connection: the keys (symbols follow once accepted)."""
        self.authed, self.confirmed = False, frozenset()
        return [json.dumps({"action": "auth", "key": self.key_id, "secret": self.secret_key})]

    def change(self, add, drop) -> list[str]:
        out = []
        if drop:
            out.append(json.dumps({"action": "unsubscribe", "trades": sorted(drop)}))
        if add:
            out.append(json.dumps({"action": "subscribe", "trades": sorted(add)}))
        return out

    def parse(self, msg) -> list[tuple[str, dict]]:
        out = []
        for m in msg if isinstance(msg, list) else [msg]:
            kind = m.get("T")
            if kind == "t":
                t = normalize_trade(m)
                if t:
                    out.append((m["S"], t))
            elif kind == "x":  # a trade withdrawn: canceled, or an error
                out.append((m["S"], {**normalize_trade(m), "withdrawn": True}))
            elif kind == "c":  # a correction: the original trade withdrawn, the corrected one in its place
                base = {"x": m["x"], "t": m["t"], "z": m.get("z")}
                was = normalize_trade({**base, "i": m["oi"], "p": m["op"], "s": m["os"], "c": m.get("oc")})
                out.append((m["S"], {**was, "withdrawn": True}))
                out.append((m["S"], normalize_trade({**base, "i": m["ci"], "p": m["cp"], "s": m["cs"], "c": m.get("cc")})))
            elif kind == "subscription":
                self.confirmed = frozenset(m.get("trades") or [])
            elif kind == "success" and m.get("msg") == "authenticated":
                self.authed = True
            elif kind == "error":
                code = int(m.get("code") or 0)
                text = f"alpaca {code}: {m.get('msg')}"
                if code in ALPACA_REFUSALS:
                    raise Refused(text, ALPACA_REFUSALS[code])
                raise Notice(text)
        return out


def stream_keys(settings) -> tuple[str, str] | None:
    """Alpaca's keys for the IEX stream: None without keys, with LIVE_STOCKS=off, or offline."""
    a = settings.alpaca
    if settings.offline or not settings.live_stocks or not (a and a.has_keys):
        return None
    return a.key_id, a.secret_key


ALPACA = Provider(
    version="1.2.0", api="1.5",  # its own release (its stream in it), and the contract it needs (Provider.live)
    name="alpaca", title="Alpaca", build=build, assets=frozenset({"stock", "crypto"}), order=10,
    about="US stocks (SIP from 2016, the session up to 15 min ago, IEX live; overnight on Blue Ocean) with keys; "
          "crypto without",
    keys=(KeyVar("ALPACA_API_KEY_ID", "key ID", ("APCA_API_KEY_ID",)),
          KeyVar("ALPACA_API_SECRET_KEY", "secret key", ("APCA_API_SECRET_KEY",))),
    keyless=frozenset({"crypto"}), signup="alpaca.markets: a paper account's API keys",
    plan_vars=("ALPACA_PLAN",), limits="Basic (free): 200 requests per minute; Algo Trader Plus: 10,000",
    plan_choices={"ALPACA_PLAN": tuple(ALPACA_TIERS)},
    kind="exchange", kind_by_asset={"stock": "consolidated"},  # its stocks are the consolidated tape (SIP)
    venue_notes={"crypto": "one exchange's book (Kraken)"}, bulk_resolution="minute",
    provides={"stock": ("day", "minute"), "crypto": ("day", "minute")},  # no 1-second bars
    per_request={"day": 10_000, "minute": 10_000},  # PAGE_LIMIT
    streams={"stock": "real time, IEX's trades only (a few per cent of US volume), symbols open on a chart"},
    live=(Live(IEX_FEED, "stock", stream=AlpacaIexStream, credentials=stream_keys, label="alpaca (iex)",
               partial=True),),
    missing_keys_note="keys not set: US stocks (SIP from 2016, IEX live), options and news wait for "
                      "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY; crypto needs no key and is collected",
    missing_keys_chip="stocks need keys",
    view=view, has_keys=lambda s: bool(s.alpaca and s.alpaca.has_keys), markets=markets, scan=scan,
)


def build_boats(settings, request_budget):
    a = settings.alpaca
    if a is None:
        raise ConfigError("Alpaca settings missing")
    # Alpaca's window and day cap, held for the machine under Alpaca's name: one account's limits
    client = AlpacaClient(a.key_id, a.secret_key, trading_url=TRADING_URLS[a.paper],
                          rate_limiter=limiter("alpaca", settings, a.key_id), request_budget=request_budget)
    return BoatsSource(machine_caps(client, "alpaca", settings, a.key_id), realtime=a.tier.name == "alpaca-plus")


def boats_scan(source) -> list[tuple[str, bool, str]]:
    """What the plan gives Blue Ocean (one request): last week's overnight minute bars of a busy stock."""
    ok = source.is_entitled("minute", "AAPL", "stock")
    return [("stock minute bars overnight (feed=boats)", ok,
             "Alpaca Basic: history up to 15 minutes ago" if ok else "refused by the plan")]


BOATS = Provider(
    version="1.2.0", api="1.5",  # this plugin's release, and the contract it needs (part_of; partial)
    name="boats", title="Blue Ocean", build=build_boats, assets=frozenset({"stock"}), order=15, account="alpaca",
    part_of="alpaca", partial=True,  # one venue's nights: never the whole market's
    about="US stocks overnight, 20:00-04:00 ET, Blue Ocean ATS through Alpaca (your Alpaca keys and limits)",
    keys=ALPACA.keys, signup=ALPACA.signup, kind="exchange",
    provides={"stock": ("minute",)}, per_request={"minute": PAGE_LIMIT},
    limits="shares Alpaca's: 200 requests per minute (Basic) for both feeds",
    missing_keys_note="keys not set: Blue Ocean's overnight bars come through Alpaca, with ALPACA_API_KEY_ID "
                      "and ALPACA_API_SECRET_KEY",
    view=view, rate=lambda settings: ALPACA.rate_window(settings),
    has_keys=lambda s: bool(s.alpaca and s.alpaca.has_keys),
    markets=lambda settings: {"stock": "boats"},
    scan=boats_scan,
)

PLUGINS = (ALPACA, BOATS)  # one plugin, two feeds: the day sessions (and crypto), and Blue Ocean's nights
