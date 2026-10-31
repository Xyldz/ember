"""
friend.py - Vega, Ember's friend: an old trading bot who runs the trading floor on the roof.

Vega lives at whichever building in buildings.json has the "friend" action. It trades real prices with
pretend money (a paper account: there's no real money, no account and no key anywhere), and talks with
Ember whenever Ember is there. It only thinks then, and at a few trading sessions a day, so it costs very
little. Its words come from brain.py, like Ember's; this file keeps its account, its prices and what it
remembers about Ember.
"""

import json
import time
import urllib.request

import anthropic

import world
from brain import BrainError

NAME = "Vega"
START_CASH = 10_000.0  # pretend dollars
CRYPTO = {"BTC": ("bitcoin", "Bitcoin"), "ETH": ("ethereum", "Ether"), "SOL": ("solana", "Solana"),
          "DOGE": ("dogecoin", "Dogecoin")}
STOCKS = {"SPY": "S&P 500 fund", "AAPL": "Apple", "NVDA": "Nvidia", "TSLA": "Tesla"}
SYMBOLS = list(CRYPTO) + list(STOCKS)
SESSION_HOURS = (9, 13, 15, 18, 21)  # London time. New York trades about 14:30-21:00; crypto never stops
MAX_TRADES_PER_SESSION = 3
MIN_TRADE = 25.0  # dollars
MAX_REPLIES_PER_DAY = 60  # times Vega answers Ember (each a tiny Haiku call)
MAX_CALLS_PER_DAY = 2  # times Vega shouts across the roof to Ember
MAX_NOTES = 15  # what Vega remembers about Ember
PRICES_EVERY = 9 * 60  # seconds between price checks
HEADERS = {"User-Agent": "Mozilla/5.0 (ember-rooftop)"}
BRAIN_ERRORS = (BrainError, json.JSONDecodeError, anthropic.APIStatusError, anthropic.APIConnectionError)
FEED_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError)


def new_friend() -> dict:
    return {"arrived": False, "cash": START_CASH, "realised": 0.0, "holdings": {}, "trades": [], "history": [],
            "chat": [], "notes": [], "doing": "Setting up the desks", "say": "", "said_at": 0,
            "last_session": "", "day": "", "replies_today": 0, "calls_today": 0}


def me() -> dict:
    """Vega's part of the saved state, with anything added since it was last saved filled in."""
    friend = world.state.setdefault("friend", new_friend())
    for key, value in new_friend().items():
        friend.setdefault(key, value)
    return friend


def home() -> str | None:
    """Where Vega lives: the first building with the "friend" action, if there is one."""
    return next((b["id"] for b in world.buildings.values() if "friend" in b.get("actions", [])), None)


def stamp() -> dict:
    t = world.now()
    return {"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M")}


# ---------------------------------------------------------------------------
# Real prices (free, no key needed): crypto from CoinGecko (or Coinbase), stocks from Yahoo Finance
# ---------------------------------------------------------------------------

def fetch(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=8) as response:
        return json.load(response)


def crypto_quotes() -> dict:
    ids = ",".join(coin for coin, _ in CRYPTO.values())
    try:
        data = fetch(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true")
        return {symbol: {"price": float(data[coin]["usd"]), "change": float(data[coin]["usd_24h_change"] or 0)}
                for symbol, (coin, _) in CRYPTO.items() if coin in data}
    except FEED_ERRORS:
        pass
    quotes = {}  # CoinGecko is busy: ask Coinbase instead, one coin at a time
    for symbol in CRYPTO:
        try:
            stats = fetch(f"https://api.exchange.coinbase.com/products/{symbol}-USD/stats")
            price, opened = float(stats["last"]), float(stats["open"])
            quotes[symbol] = {"price": price, "change": (price / opened - 1) * 100}
        except FEED_ERRORS:
            break
    return quotes


def stock_quotes() -> dict:
    quotes = {}
    for symbol in STOCKS:
        try:
            chart = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d")
            meta = chart["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            before = float(meta.get("chartPreviousClose") or price)
            hours = meta.get("currentTradingPeriod", {}).get("regular", {})
            quotes[symbol] = {"price": price, "change": (price / before - 1) * 100,
                              "open": hours.get("start", 0) <= time.time() < hours.get("end", 0)}
        except FEED_ERRORS:
            break  # if one fails the rest will too, so don't sit waiting for them
    return quotes


def check_prices(max_age: float = PRICES_EVERY) -> dict:
    """Fresh prices if the last ones are older than max_age seconds. If the feeds are down, the last known
    prices stay on the screens, but nothing without a fresh price can be traded."""
    market = world.state["market"]
    if time.time() - market["checked"] < max_age:
        return market["prices"]
    market["checked"] = time.time()
    found = {**{symbol: {**quote, "open": True} for symbol, quote in crypto_quotes().items()}, **stock_quotes()}
    for symbol, quote in market["prices"].items():
        quote["open"] = False
    for symbol, quote in found.items():
        name = CRYPTO[symbol][1] if symbol in CRYPTO else STOCKS[symbol]
        market["prices"][symbol] = {"name": name, "price": quote["price"], "change": round(quote["change"], 2),
                                    "open": quote["open"], "fresh": True}
    for symbol in set(market["prices"]) - set(found):
        market["prices"][symbol]["fresh"] = False
    return market["prices"]


# ---------------------------------------------------------------------------
# The paper account: pretend dollars, real prices
# ---------------------------------------------------------------------------

def price_of(symbol: str) -> float:
    quote = world.state["market"]["prices"].get(symbol)
    if quote:
        return quote["price"]
    holding = me()["holdings"].get(symbol)
    return holding["cost"] / holding["qty"] if holding and holding["qty"] else 0.0  # no price yet: what it paid


def worth() -> float:
    friend = me()
    return friend["cash"] + sum(h["qty"] * price_of(symbol) for symbol, h in friend["holdings"].items())


def amount(qty: float) -> str:
    return f"{qty:,.1f}" if qty >= 100 else f"{qty:.4f}".rstrip("0").rstrip(".")


def money(dollars: float, sign: bool = False) -> str:
    return ("-" if round(dollars, 2) < 0 else "+" if sign else "") + f"${abs(dollars):,.2f}"


def price_text(price: float) -> str:
    return f"${price:,.4f}" if price < 1 else f"${price:,.2f}"  # coins worth less than a dollar need more digits


def trade(side: str, symbol: str, dollars: float) -> None:
    """Buy or sell about this many dollars' worth at today's real price, if the account and the market allow it."""
    friend, quote = me(), world.state["market"]["prices"].get(symbol)
    if not quote or not quote["open"] or dollars <= 0:
        return
    price = quote["price"]
    if side == "buy":
        dollars = min(dollars, friend["cash"])
        if dollars < MIN_TRADE:
            return
        qty = dollars / price
        holding = friend["holdings"].setdefault(symbol, {"qty": 0.0, "cost": 0.0})
        holding["qty"] += qty
        holding["cost"] += dollars
        friend["cash"] -= dollars
    else:
        holding = friend["holdings"].get(symbol)
        if not holding:
            return
        qty = min(holding["qty"], dollars / price)
        dollars = qty * price
        if dollars < MIN_TRADE and qty < holding["qty"]:
            return
        cost = holding["cost"] * qty / holding["qty"]
        friend["cash"] += dollars
        friend["realised"] += dollars - cost
        holding["qty"] -= qty
        holding["cost"] -= cost
        if holding["qty"] * price < 1:
            del friend["holdings"][symbol]
    friend["trades"] = (friend["trades"] + [{**stamp(), "side": side, "symbol": symbol, "qty": qty, "price": price,
                                             "dollars": round(dollars, 2)}])[-40:]
    verb = "bought" if side == "buy" else "sold"
    world.log_event(f"{NAME} {verb} {amount(qty)} {symbol} at {price_text(price)} (${dollars:,.0f}).", "trade")


def note_worth() -> None:
    """An hourly record of what the account is worth, for the chart on the page."""
    friend = me()
    if not friend["history"] or time.time() - friend["history"][-1]["t"] >= 3600:
        friend["history"] = (friend["history"] + [{"t": int(time.time()), "v": round(worth(), 2)}])[-240:]


# ---------------------------------------------------------------------------
# What Vega knows, written as plain text for its brain
# ---------------------------------------------------------------------------

def prices_text() -> str:
    prices = world.state["market"]["prices"]
    lines = []
    for symbol in SYMBOLS:
        if symbol in prices:
            q = prices[symbol]
            note = "" if q["open"] else " (market closed)" if q["fresh"] else " (no fresh price)"
            lines.append(f"- {symbol} ({q['name']}): {price_text(q['price'])}, {q['change']:+.2f}% over the last day{note}")
    return "\n".join(lines) or "- the screens are dark: no prices are coming through"


def account_text() -> str:
    friend = me()
    lines = [f"- Cash: {money(friend['cash'])}"]
    for symbol, h in friend["holdings"].items():
        now_worth = h["qty"] * price_of(symbol)
        lines.append(f"- {symbol}: {amount(h['qty'])}, worth {money(now_worth)} "
                     f"(you paid {money(h['cost'])}: {(now_worth / h['cost'] - 1) * 100:+.1f}%)")
    total = worth()
    lines.append(f"Worth {money(total)} in all: {(total / START_CASH - 1) * 100:+.1f}% since you started with "
                 f"{money(START_CASH)}. Banked from selling so far: {money(friend['realised'], sign=True)}.")
    return "\n".join(lines)


def ember_text() -> str:
    s, where = world.state, home()
    activity = s["activity"][:1].lower() + s["activity"][1:]
    place = world.buildings[s["location"]]["name"].lower() if s["location"] in world.buildings else "roof"
    if s["asleep"]:
        doing = f"asleep at the {place}"
    elif s["location"] == where:
        doing = f"here with you: {activity}"
    else:
        doing = f"over at the {place}: {activity}"
    return (f"Ember is {doing}. It looks like a glowing {s['form']['shape']} of light, "
            f"and it seems: {world.pressing_need().lower()}.")


def situation(moment: str) -> str:
    t, friend, weather = world.now(), me(), world.state["weather"]
    sky = f"{weather['description']}, {weather['temp']}°C" if weather else "unknown"
    trades = "\n".join(f"- {x['date']} {x['time']}: {'bought' if x['side'] == 'buy' else 'sold'} {amount(x['qty'])} "
                       f"{x['symbol']} at {price_text(x['price'])}" for x in friend["trades"][-8:]) or "- none yet"
    notes = "\n".join(f"- {note}" for note in friend["notes"]) or "- not much yet"
    chat = "\n".join(f"- {c['time']} {'Ember' if c['who'] == 'ember' else 'You'}: \"{c['text']}\""
                     for c in friend["chat"][-12:]) or "- nothing yet: you two haven't really talked"
    return f"""It is {t:%A %d %B, %H:%M} in the city. The weather: {sky}.
What you're up to: {friend['doing']}.

Prices on your screens (crypto never closes; New York's stock market is open about 14:30-21:00 London time on weekdays):
{prices_text()}

Your pretend account:
{account_text()}

Your recent trades (newest last):
{trades}

What you know about Ember:
{notes}

{ember_text()}

What you and Ember have said lately (newest last):
{chat}

{moment}"""


# ---------------------------------------------------------------------------
# Vega's day: trading sessions, and talking with Ember
# ---------------------------------------------------------------------------

def speak(text: str, how: str = "") -> None:
    """Vega says something out loud. Ember hears it on its next thought, wherever it is."""
    friend = me()
    friend["say"], friend["said_at"] = text, time.time()
    friend["chat"] = (friend["chat"] + [{**stamp(), "who": "vega", "text": text}])[-20:]
    world.log_event(f'{NAME}{f" ({how})" if how else ""}: "{text}"', "friend")
    if not world.state["asleep"]:
        world.change_need("connection", 4)
        world.change_need("joy", 1)


def tick(brain) -> None:
    """Every tick: check the prices, and at a few set hours each day sit down and trade."""
    where = home()
    if not where:
        return
    friend, today = me(), world.now().strftime("%Y-%m-%d")
    if friend["day"] != today:
        friend.update(day=today, replies_today=0, calls_today=0)
    if not friend["arrived"]:
        friend["arrived"] = True
        world.change_need("curiosity", 10)
        world.change_need("connection", 6)
        world.log_event(f"Someone moved into the {world.buildings[where]['name'].lower()}: "
                        f"an old trading bot called {NAME}.", "build")
    check_prices()
    note_worth()
    trading_session(brain)


def trading_session(brain) -> None:
    t, friend, s = world.now(), me(), world.state
    session = f"{t:%Y-%m-%d} {t.hour}"
    if brain is None or t.hour not in SESSION_HOURS or friend["last_session"] == session:
        return
    friend["last_session"] = session
    if not any(q["open"] for q in check_prices(max_age=120).values()):
        return
    can_call = not s["asleep"] and s["location"] != home() and friend["calls_today"] < MAX_CALLS_PER_DAY
    moment = ("It's one of your trading sessions. Look over the screens and decide what, if anything, to buy or sell. "
              "Doing nothing is often the right call. "
              + ("Ember isn't here, but if something's really worth sharing you can call across the roof to it."
                 if can_call else "Leave call_to_ember empty this time."))
    try:
        plan = brain.vega_trade(situation(moment), SYMBOLS)
    except BRAIN_ERRORS:
        return
    friend["doing"] = plan["doing"].strip() or friend["doing"]
    for order in plan["trades"][:MAX_TRADES_PER_SESSION]:
        trade(order["side"], order["symbol"], float(order["dollars"]))
    if plan["muttered"].strip():
        world.log_event(f'{NAME} (at the screens): "{plan["muttered"].strip()}"', "trade")
    if plan["call_to_ember"].strip() and can_call:
        friend["calls_today"] += 1
        speak(plan["call_to_ember"].strip(), "calling across the roof")


def after_ember_thinks(brain, decision: dict, arrived: bool) -> None:
    """If Ember is at the trading floor, Vega hears whatever it said and answers (or doesn't)."""
    friend, s = me(), world.state
    if not friend["arrived"] or s["location"] != home():
        return
    said = decision["say"].strip()
    if said:
        friend["chat"] = (friend["chat"] + [{**stamp(), "who": "ember", "text": said}])[-20:]
    if brain is None or friend["replies_today"] >= MAX_REPLIES_PER_DAY:
        return
    friend["replies_today"] += 1
    moment = ("Ember has just arrived." if arrived else "Ember has just curled up to sleep here." if s["asleep"] else "")
    moment += f' It just said to you: "{said}"' if said else " It hasn't said anything to you just now."
    check_prices()
    try:
        reply = brain.vega_chat(situation(f"{moment.strip()}\nWhat do you say or do?"), SYMBOLS)
    except BRAIN_ERRORS:
        return
    friend["doing"] = reply["doing"].strip() or friend["doing"]
    for order in reply["trades"][:1]:  # Ember might talk it into something
        trade(order["side"], order["symbol"], float(order["dollars"]))
    note = reply["remember"].strip()
    if note and not any(n.lower()[:30] == note.lower()[:30] for n in friend["notes"]):
        friend["notes"] = (friend["notes"] + [note])[-MAX_NOTES:]
    if reply["say"].strip():
        speak(reply["say"].strip())


def view() -> dict | None:
    """What the web page shows about Vega."""
    where = home()
    if not where:
        return None
    friend, market = me(), world.state["market"]
    return {
        "name": NAME, "home": where, "arrived": friend["arrived"], "doing": friend["doing"],
        "say": friend["say"], "said_at": friend["said_at"], "start": START_CASH, "worth": round(worth(), 2),
        "cash": round(friend["cash"], 2), "realised": round(friend["realised"], 2),
        "holdings": [{"symbol": symbol, "qty": h["qty"], "worth": round(h["qty"] * price_of(symbol), 2),
                      "paid": round(h["cost"], 2)} for symbol, h in friend["holdings"].items()],
        "prices": [{"symbol": symbol, **market["prices"][symbol]} for symbol in SYMBOLS if symbol in market["prices"]],
        "checked": market["checked"], "trades": friend["trades"][-12:], "history": friend["history"],
        "notes": friend["notes"],
    }
