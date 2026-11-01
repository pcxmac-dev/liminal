"""Tiingo (tiingo.com): US stock daily bars from 1962 with a free account key; a closed archive.

Its scan (`capabilities`, one request each) asks what else the account's plan gives: IEX's minute
bars (one exchange), forex and crypto bars, and Blue Ocean's overnight bars (a paid add-on,
2026-10-27: $9 a month; Alpaca's free plan has them: alpaca.py's BOATS, and from earlier: Tiingo had none
before 2024-09-25, asked 2026-10-28). The stocks' daily bars are collected here, the forex
minutes on a feed of this plugin on this key's limits (FOREX below: tiingo (forex)).

Its plan is found in part: Tiingo's API has no account endpoint and sends no rate-limit headers
(2026-10-27), but its News API is the paid plans' (Power, Commercial) and not Starter's (the pricing
table, 2026-10-27), so the scan's News request tells Starter from a paid plan. Power and Commercial
reach the same data at other limits: a paid key is taken for Power, the lower limits, unless
TIINGO_PLAN says commercial (starter, the default; power; commercial: the key script and the Plugins
view offer them). It also asks for the fundamentals add-on, of a stock outside the Dow 30 (those
are free to evaluate)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from ....config import PUBLIC_FEEDS, Tier
from ....errors import SourceError
from ...http import PublicClient
from ...registry import KeyVar, Provider, Scanned, limiter, machine_caps
from ...stream import Live
from .client import TiingoFxSource, TiingoSource

TIER, PER_RUN, PER_DAY = PUBLIC_FEEDS["tiingo"]
API = "https://api.tiingo.com"
# Blue Ocean's night under way, live from Tiingo (BoatsPoller): a feed of its own, one venue's nights
TIINGO_BOATS = "tiingoboats"
BARS = "open,high,low,close,volume"

# Tiingo's plans (tiingo.com/about/pricing, both tables: "I am an Individual" and "I am a Business or
# Organization", 2026-10-27), each kept a little inside: (plan, requests an hour (a run's cap too: the
# sync runs hourly), a day, different symbols a month).
#   Starter (free): 50 an hour, 1,000 a day, 500 symbols, 1 GB a month.
#   Power (individuals, $30 a month or $300 a year): 10,000 an hour, 100,000 a day, every symbol
#     (110,397), 40 GB a month.
#   Commercial (a business's internal use, up to two developers, $50 a month or $499 a year): 20,000 an
#     hour, 150,000 a day, every symbol, 100 GB a month.
# Enterprise and redistribution are priced by Tiingo's sales, with no published limits: not offered.
PLANS = {
    "starter": (TIER, PER_RUN, PER_DAY, 450),
    "power": (replace(TIER, name="tiingo-power"), 9_500, 95_000, None),
    "commercial": (replace(TIER, name="tiingo-commercial"), 19_000, 142_500, None),
}
ALIASES = {"free": "starter", "business": "commercial"}
PLAN_NOTE = ("Tiingo's API does not say which plan a key is on (no account endpoint, no rate-limit headers). "
             "Its scan tells Starter from a paid plan by the News API, which only Power and Commercial have; "
             "it cannot tell Power from Commercial (the same data, other limits), so a paid key gets Power's "
             "limits unless you set TIINGO_PLAN=commercial")
NEWS = "news (the paid plans: Power and Commercial, not Starter)"
FUNDAMENTALS = "fundamentals (an add-on; asked for ROKU: the Dow 30 are free to evaluate)"


def plan_of(settings) -> str:
    """TIINGO_PLAN's plan (an unknown value: Starter, the free plan's limits, never more)."""
    name = (settings.env.get("TIINGO_PLAN") or "starter").strip().lower()
    name = ALIASES.get(name, name)
    return name if name in PLANS else "starter"


def view(base):
    tier, per_run, per_day, _ = PLANS[plan_of(base)]
    return replace(base, tier=tier, max_requests_per_run=per_run, max_requests_per_day=per_day, origin=base)


def reporter(report, settings):
    """Its plan's symbols a month: TIINGO_PLAN's, or without the settings (the delivery scheme's
    reports) the plan its tier names: a paid plan's report said Starter's 450 to the scheme."""
    plan = plan_of(settings) if settings is not None else next(
        (name for name, p in PLANS.items() if p[0].name == report.plan), "starter")
    return replace(report, limits=replace(report.limits, symbols_a_month=PLANS[plan][3]))


def build(settings, request_budget):
    key = settings.tiingo_api_key
    headers = {"Authorization": f"Token {key}"} if key else {}
    client = PublicClient(API, headers=headers, request_budget=request_budget,
                          rate_limiter=limiter("tiingo", settings, key))
    source = TiingoSource(machine_caps(client, "tiingo", settings, key), has_key=bool(key))
    return monthly_symbols(source, settings, key)


def monthly_symbols(source, settings, key):
    """The plan's different symbols a month on a Tiingo source (collector._monthly_symbol), counted
    for the key on the whole machine: its stocks and its forex (FOREX) take the same places."""
    from ....ratelimit import MachineLedger

    source.symbols_per_month = PLANS[plan_of(settings)][3]
    source.symbol_ledger = MachineLedger("tiingo:symbols", key)
    return source


def probes(today: date) -> list[tuple[str, str, dict]]:
    """(what, path, params) of the scan: a recent weekday of a busy symbol at each endpoint."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    d = day.isoformat()
    return [
        ("stock daily bars, from 1962", "/tiingo/daily/AAPL/prices", {"startDate": d, "endDate": d}),
        ("stock 1-minute bars from IEX (one exchange)", "/iex/AAPL/prices",
         {"startDate": d, "endDate": d, "resampleFreq": "1min", "afterHours": "true", "columns": BARS}),
        ("stock overnight bars from Blue Ocean (20:00-04:00)", "/boats/AAPL/prices",
         {"startDate": d, "endDate": d, "resampleFreq": "1min", "columns": BARS}),
        ("forex 1-minute bars", "/tiingo/fx/prices", {"tickers": "eurusd", "startDate": d, "endDate": d,
                                                      "resampleFreq": "1min"}),
        ("crypto bars", "/tiingo/crypto/prices", {"tickers": "btcusd", "startDate": d, "endDate": d,
                                                  "resampleFreq": "1min"}),
        (NEWS, "/tiingo/news", {"tickers": "aapl", "limit": 1, "startDate": d}),
        (FUNDAMENTALS, "/tiingo/fundamentals/ROKU/daily", {"startDate": d, "endDate": d, "columns": "marketCap"}),
    ]


def rows_of(answer) -> int:
    """Bars in an answer: a list of bars, or crypto's [{priceData: [...]}]."""
    if isinstance(answer, list) and answer and isinstance(answer[0], dict) and "priceData" in answer[0]:
        return sum(len(a.get("priceData") or []) for a in answer)
    return len(answer) if isinstance(answer, list) else 0


def scan(source, today: date | None = None) -> Scanned:
    """Each probe once; the plan from the News request: news served (articles), a paid plan
    (Power's limits, the lower: Commercial's answers are the same); refused by the plan (401, 403),
    Starter; anything else (a timeout, a server error, an answer without articles: an error said
    in a 200, an empty list), no plan: a paid plan's far higher limits are never taken on less."""
    out, plan, alike = [], {}, {}
    for what, path, params in probes(today or date.today()):
        try:
            answer = source.client.get(path, params)
            n = rows_of(answer)
        except SourceError as e:  # NotEntitled included: a refusal names the add-on it needs
            out.append((what, False, str(e)[:200]))
            if what == NEWS and e.status in (401, 403):
                plan["TIINGO_PLAN"] = "starter"
            continue
        if what == NEWS:
            articles = isinstance(answer, list) and any(isinstance(a, dict) and (a.get("title") or a.get("id"))
                                                        for a in answer)
            if not articles:
                out.append((what, False, f"answered without articles ({str(answer)[:120]}): the plan is not told"))
                continue
            plan["TIINGO_PLAN"], alike["TIINGO_PLAN"] = "power", ("commercial",)
            out.append((what, True, "served: a paid plan, Power or Commercial (the same data)"))
        elif what == FUNDAMENTALS:
            out.append((what, True, f"served: the add-on ({n:,} rows)"))
        else:
            out.append((what, True, f"{n:,} bars for {params['startDate']}"))
    return Scanned(tuple(out), plan, alike)


# -- Blue Ocean's night, live: tiingo (blue ocean) ------------------------------------------------

def boats_live(settings) -> bool:
    """Whether Blue Ocean's nights are polled live from Tiingo (BoatsPoller): online, live stocks
    on, Tiingo's key set and a paid plan (Power or Commercial: Starter's 50 requests an hour would
    all go on this)."""
    if settings.offline or not settings.live_stocks or not settings.tiingo_api_key:
        return False
    return plan_of(settings) != "starter"


def _iso_ms(text: str) -> int:
    """Tiingo's time (2026-10-28T07:43:00.000Z, or with an offset and nanoseconds) in ms."""
    text = str(text).replace("Z", "+00:00")
    head, _, rest = text.partition(".")
    if not rest:
        return int(datetime.fromisoformat(head).timestamp() * 1000)
    cut = next((i for i, ch in enumerate(rest) if ch in "+-"), len(rest))  # nanoseconds: microseconds kept
    return int(datetime.fromisoformat(f"{head}.{rest[:cut][:6]}{rest[cut:]}").timestamp() * 1000)


class BoatsPoller:
    """Blue Ocean's overnight session (20:00-04:00 ET, Sunday to Thursday nights), live, from Tiingo's
    REST API: it has no stream for it, but its answers are real time (the newest minute half a minute
    old, asked 2026-10-28 at 03:43 ET); Alpaca's real-time nights are a paid plan, its free one 16
    minutes behind. While a night is open, for the stocks open on a chart (the recorder's wanted
    stocks): their last sale and quote every BOATS_QUOTE_SECONDS, one request for them all (the
    price the pages show); and each one's minutes of the night every BOATS_BARS_SECONDS or so, the
    minutes over stored as the feed's own bars, the forming one as a built bar its final bar
    replaces (TIINGO_BOATS, one of PARTIAL_FEEDS: a chart of all feeds shows them where no other
    feed has the night yet). On the Tiingo key's limits: its window and day cap (the client), its
    kills (a 429 or a refused key kills Tiingo's fetching, and this stops with it)."""

    source = TIINGO_BOATS
    account = "tiingo"  # the feed whose key, limits and kills these requests are
    title = "Blue Ocean from Tiingo"  # in the recorder's log

    def __init__(self, client, now=None):
        self.client = client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.quotes_at = float("-inf")  # monotonic: the last quote request
        self.bars_at: dict[str, float] = {}  # ticker -> monotonic: its minutes last asked for
        self.final_to: dict[str, int] = {}  # ticker -> ms: its minutes stored final up to here
        self.refused_until = float("-inf")  # monotonic: Blue Ocean refused (no add-on) until then

    @staticmethod
    def symbol(ticker: str) -> str:
        return ticker.upper().replace(".", "-").lower()  # Tiingo's: brk-b

    @classmethod
    def url(cls, ticker: str) -> str:
        """Where a stock's minutes of the night come from (their provenance)."""
        return f"{API}/boats/{cls.symbol(ticker)}/prices"

    def night(self, t: datetime):
        """The Blue Ocean session open at `t` (sessions.Session), or None."""
        from ....freshness import CALENDAR
        from ....sessions import ET

        d = t.astimezone(ET).date()
        return next((s for s in CALENDAR.sessions("overnight", d, d + timedelta(days=1)) if s.open <= t < s.close), None)

    def quotes(self, tickers) -> dict[str, dict]:
        """{ticker: {price, last (ms), bid, ask}}: the last sale and quote of each, one request."""
        names = {self.symbol(t): t.upper() for t in tickers}
        rows = self.client.get("/boats/", {"tickers": ",".join(names)})
        out = {}
        for r in rows if isinstance(rows, list) else []:
            ticker = names.get(str(r.get("ticker") or "").lower())
            if ticker and r.get("last") is not None and r.get("lastSaleTimestamp"):
                out[ticker] = {"price": float(r["last"]), "last": _iso_ms(r["lastSaleTimestamp"]),
                               "bid": r.get("bidPrice"), "ask": r.get("askPrice")}
        return out

    def minutes(self, ticker: str, night, since_ms: int = 0) -> list[dict]:
        """The night's minutes from `since_ms` (its open at the latest), the forming one too (oldest
        first). Tiingo reads its dates in New York and, without an endDate, answers only startDate's
        hours before 04:00 ET: asked as the open's UTC date alone, a night came back empty all
        evening (2026-10-28). So from the New York date of the first minute wanted (the open's until
        the minutes after midnight are stored: the night before's last hours come with it, left out
        here) to the close's."""
        from ....sessions import ET

        lo = int(night.open.timestamp() * 1000)
        first = datetime.fromtimestamp(max(lo, since_ms) / 1000, ET).date()
        rows = self.client.get(f"/boats/{self.symbol(ticker)}/prices",
                               {"startDate": first.isoformat(), "endDate": night.close.astimezone(ET).date().isoformat(),
                                "resampleFreq": "1min", "columns": "open,high,low,close,volume"})
        bars = []
        for r in rows if isinstance(rows, list) else []:
            t = _iso_ms(r["date"])
            if t >= lo:
                bars.append({"t": t, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                             "c": float(r["close"]), "v": float(r.get("volume") or 0), "vw": None, "n": None})
        return sorted(bars, key=lambda b: b["t"])


def night_poller(settings) -> BoatsPoller | None:
    """The poller of Blue Ocean's nights, on Tiingo's key's limits (its client: the window and day
    cap), when they are polled here (boats_live)."""
    return BoatsPoller(build(settings, None).client) if boats_live(settings) else None


TIINGO = Provider(
    version="1.3.0", api="1.6",  # this plugin's release (its live nights and client in it), and the contract it needs
    name="tiingo", title="Tiingo", build=build, assets=frozenset({"stock"}), order=60,
    about="US stock daily bars from 1962 (a free account key)",
    keys=(KeyVar("TIINGO_API_KEY"),), signup="tiingo.com: a free account's API token",
    archival=True, tier=TIER, per_run=PER_RUN, per_day=PER_DAY,
    limits="Starter (free): 50 requests an hour, 1,000 a day, 500 symbols and 1 GB a month; "
           "Power ($30 a month): 10,000 an hour, 100,000 a day, 40 GB a month; "
           "Commercial ($50 a month, a business): 20,000 an hour, 150,000 a day, 100 GB a month",
    symbols_per_month=450,  # Starter's 500 different symbols a month, a little inside (Power: PLANS)
    plan_vars=("TIINGO_PLAN",), plan_choices={"TIINGO_PLAN": tuple(PLANS)}, plan_note=PLAN_NOTE,
    view=view, reporter=reporter,
    provides={"stock": ("day",)}, per_request={"day": None},  # one request: a symbol's whole history
    has_keys=lambda s: bool(s.tiingo_api_key),
    live=(Live(TIINGO_BOATS, "stock", poller=night_poller, label="tiingo (blue ocean)", partial=True),),
    rate=lambda settings: (PLANS[plan_of(settings)][1], 3600.0),  # Starter: 50 an hour
    markets=lambda settings: {"stock": "sip"},
    scan=scan,
)


# -- its forex: tiingo (forex) -----------------------------------------------------------------------
# Currency pairs' 1-minute bars from 2020, with the Tiingo key: a feed of this plugin (the user,
# 2026-10-30: "tiingo should be one plugin"), its own database file and watch rows (`tiingofx`), kept
# up to date, on Tiingo's limits: one account, so one rate window and one daily cap for both feeds.
# Its data is Tiingo's own (its own market here), not a copy of Massive's currencies. Taken to spend
# the paid plan's allowance, which the stocks' daily bars leave almost all unused (the user, 2026-10-28).
# Its currencies' history: from Tiingo's first forex minute (its plan's other limits are Tiingo's)
FX_TIER = Tier("tiingofx", requests_per_minute=None, history_years=None, history_start=TiingoFxSource.START)


def view_forex(base):
    """Tiingo's plan (its caps and window, TIINGO_PLAN), with the currencies' history from 2020."""
    out = view(base)
    return replace(out, tier=replace(out.tier, by_asset=(("fx", FX_TIER),)))


def build_forex(settings, request_budget):
    key = settings.tiingo_api_key
    headers = {"Authorization": f"Token {key}"} if key else {}
    # Tiingo's window and day cap, held for the machine under Tiingo's name: one account's limits
    client = PublicClient(API, headers=headers, request_budget=request_budget,
                          rate_limiter=limiter("tiingo", settings, key))
    # its pairs take places among the plan's different symbols a month, with Tiingo's stocks
    return monthly_symbols(TiingoFxSource(machine_caps(client, "tiingo", settings, key), has_key=bool(key)), settings, key)


FOREX = Provider(
    version="1.3.0", api="1.6",  # this plugin's release, and the contract it needs (part_of)
    name="tiingofx", title="Forex", build=build_forex, assets=frozenset({"fx"}), order=61, account="tiingo",
    part_of="tiingo",
    about="currency pairs' 1-minute bars from 2020, from Tiingo (its key and limits)",
    keys=TIINGO.keys, signup=TIINGO.signup, kind="vendor",
    provides={"fx": ("minute",)}, per_request={"minute": TiingoFxSource.WINDOW_DAYS * 1440},
    limits="shares Tiingo's: its plan's requests an hour and a day, for both feeds",
    missing_keys_note="key not set: Tiingo's forex comes with TIINGO_API_KEY",
    view=view_forex, rate=TIINGO.rate, has_keys=lambda s: bool(s.tiingo_api_key),
    markets=lambda settings: {"fx": "tiingofx"},
)

PLUGINS = (TIINGO, FOREX)  # one plugin, two feeds: the stocks' daily archive, and its forex minutes
