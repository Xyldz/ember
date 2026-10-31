"""
friend.py - Vega, Ember's friend: an old trading bot who runs the trading floor on the roof.

Vega works at whichever building in buildings.json has the "friend" action, but it has a life of its own:
every tick it thinks for itself, like Ember does. It has moods, a battery it recharges by powering down,
little goals, and its own business around the roof. It trades real prices with pretend money (a paper
account: there's no real money, no account and no key anywhere) at a few set hours, talks with Ember
whenever they're in the same place, and each night writes in its notebook. Its words come from brain.py,
like Ember's; this file keeps its account, its prices, where it is, its own log, and what it remembers
about Ember.
"""

import json
import time
import urllib.request
from datetime import datetime

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
MAX_THINKS_PER_DAY = 160  # its own thoughts (each a small Haiku call), like Ember's daily limit
MOODS = ["chipper", "content", "wistful", "grumpy", "restless", "excited", "nervous", "sleepy"]
BATTERY_DRAIN = 1.5  # lost every 10 minutes awake...
BATTERY_CHARGE = 7  # ...and regained every 10 minutes powered down (it wakes when full, or for a trading session)
MAX_GOALS = 3  # little goals of its own, active at once
MAX_WISHES_PER_DAY = 1
PRICES_EVERY = 9 * 60  # seconds between price checks
PRICE_POINTS = 160  # prices kept per market (about a day's worth), for the charts on the page
MAX_TRADES_KEPT = 100  # in its trading journal
HEADERS = {"User-Agent": "Mozilla/5.0 (ember-rooftop)"}
BRAIN_ERRORS = (BrainError, json.JSONDecodeError, anthropic.APIStatusError, anthropic.APIConnectionError)
FEED_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError)


def new_friend() -> dict:
    return {"arrived": False, "cash": START_CASH, "realised": 0.0, "holdings": {}, "trades": [], "history": [],
            "chat": [], "notes": [], "days": [], "doing": "Setting up the desks", "say": "", "said_at": 0,
            "thought": "", "thought_time": "", "mood": "content", "battery": 100.0, "asleep": False,
            "goals": [], "log": [],  # its own little goals, and its own day (kept apart from Ember's feed)
            "wishes": [], "wishes_today": 0,  # things it'd love built, filed as GitHub issues like Ember's
            "since": "", "location": "", "visit_since": 0, "last_talk": 0, "last_session": "", "day": "",
            "replies_today": 0, "calls_today": 0, "thinks_today": 0}


def me() -> dict:
    """Vega's part of the saved state, with anything added since it was last saved filled in."""
    friend = world.state.setdefault("friend", new_friend())
    for key, value in new_friend().items():
        friend.setdefault(key, value)
    return friend


def home() -> str | None:
    """Where Vega lives: the first building with the "friend" action, if there is one."""
    return next((b["id"] for b in world.buildings.values() if "friend" in b.get("actions", [])), None)


def where() -> str | None:
    """Where Vega is right now: its desk, unless it's off somewhere on the roof."""
    location = me()["location"]
    return location if location in world.buildings else home()


def place_name(building_id: str) -> str:
    return world.buildings[building_id]["name"].lower() if building_id in world.buildings else "roof"


def stamp() -> dict:
    t = world.now()
    return {"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M")}


def log_own(text: str, kind: str = "doing") -> None:
    """Vega's own day: its thoughts, what it gets up to, where it goes. Kept out of Ember's feed."""
    friend = me()
    friend["log"] = (friend["log"] + [{**stamp(), "kind": kind, "text": text}])[-200:]


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
    history = market.setdefault("history", {})  # the last day or so of prices, for the little charts on the page
    for symbol, quote in found.items():
        history[symbol] = (history.get(symbol, []) + [[int(time.time()), quote["price"]]])[-PRICE_POINTS:]
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


def trade(order: dict, source: str = "session") -> None:
    """Buy or sell about this many dollars' worth at today's real price, if the account and the market allow it.
    Every trade goes in Vega's trading journal, with its reason and (for a sale) what it made or lost."""
    friend, quote = me(), world.state["market"]["prices"].get(order["symbol"])
    side, symbol, dollars, why = order["side"], order["symbol"], float(order["dollars"]), order.get("why", "").strip()
    if not quote or not quote["open"] or dollars <= 0:
        return
    price, gain = quote["price"], None
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
        gain = round(dollars - cost, 2)
        friend["cash"] += dollars
        friend["realised"] += dollars - cost
        holding["qty"] -= qty
        holding["cost"] -= cost
        if holding["qty"] * price < 1:
            del friend["holdings"][symbol]
    friend["trades"] = (friend["trades"] + [{**stamp(), "side": side, "symbol": symbol, "qty": qty, "price": price,
                                             "dollars": round(dollars, 2), "why": why, "gain": gain,
                                             "source": source}])[-MAX_TRADES_KEPT:]
    verb = "bought" if side == "buy" else "sold"
    world.log_event(f"{NAME} {verb} {amount(qty)} {symbol} at {price_text(price)} (${dollars:,.0f})"
                    + (f': "{why}"' if why else "."), "trade")


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
    s = world.state
    activity = s["activity"][:1].lower() + s["activity"][1:]
    if s["asleep"]:
        doing = f"asleep at the {place_name(s['location'])}"
    elif s["location"] == where():
        doing = f"here with you: {activity}"
    else:
        doing = f"over at the {place_name(s['location'])}: {activity}"
    return (f"Ember is {doing}. It looks like a glowing {s['form']['shape']} of light, "
            f"and it seems: {world.pressing_need().lower()}.")


def situation(moment: str) -> str:
    t, friend, weather = world.now(), me(), world.state["weather"]
    sky = f"{weather['description']}, {weather['temp']}°C" if weather else "unknown"
    here = (f"at your desk in the {place_name(home())}" if where() == home()
            else f"out at the {place_name(where())} (your desk is at the {place_name(home())})")
    goals = "; ".join(g["text"] for g in friend["goals"]) or "nothing in particular"
    trades = "\n".join(f"- {x['date']} {x['time']}: {'bought' if x['side'] == 'buy' else 'sold'} {amount(x['qty'])} "
                       f"{x['symbol']} at {price_text(x['price'])}" + (f" (\"{x['why']}\")" if x.get("why") else "")
                       for x in friend["trades"][-8:]) or "- none yet"
    notes = "\n".join(f"- {note}" for note in friend["notes"]) or "- not much yet"
    chat = "\n".join(f"- {c['time']} {'Ember' if c['who'] == 'ember' else 'You'}: \"{c['text']}\""
                     for c in friend["chat"][-12:]) or "- nothing yet: you two haven't really talked"
    return f"""It is {t:%A %d %B, %H:%M} in the city. The weather: {sky}.
You're {here}. What you're up to: {friend['doing']}.
Your mood: {friend['mood']}. Your battery: {round(friend['battery'])}%. Your own little goals: {goals}.

Prices on your screens (crypto never closes; New York's stock market is open about 14:30-21:00 London time on weekdays):
{prices_text()}

Your pretend account:
{account_text()}

Your recent trades (newest last):
{trades}

What you know about Ember:
{notes}

What's on in the city:
{world.city_text()}

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
    if world.state["location"] == where():
        friend["last_talk"] = time.time()
    if not world.state["asleep"]:
        world.change_need("connection", 4)
        world.change_need("joy", 1)


def move(target: str, why: str = "") -> None:
    """Vega trundles somewhere. Ember only hears about it if that's where Ember is."""
    friend, s = me(), world.state
    if target not in world.buildings or target == where():
        return
    friend.update(location="" if target == home() else target, visit_since=time.time())
    log_own(f"Trundled over to the {place_name(target)}{why}.", "move")
    if target == s["location"] and not s["asleep"]:
        world.log_event(f"{NAME} trundled over to the {place_name(target)}, where Ember is.", "friend")


def session_due() -> bool:
    """A trading session is about to start (or has yet to happen this hour), so Vega should be at its desk."""
    t, friend = world.now(), me()
    return ((t.hour in SESSION_HOURS and friend["last_session"] != f"{t:%Y-%m-%d} {t.hour}")
            or (t.hour + 1 in SESSION_HOURS and t.minute >= 45))


def power_down(why: str) -> None:
    friend = me()
    friend.update(asleep=True, doing="Powered down", say="")
    log_own(why, "power")


def wake_up(why: str) -> None:
    me().update(asleep=False, doing="Booting back up")
    log_own(why, "power")


def tick(brain) -> None:
    """Every tick, like Ember: check the prices, then either sit down and trade (at a few set hours), or live
    its own life for a moment. While powered down it recharges and doesn't think, which costs nothing."""
    base = home()
    if not base:
        return
    friend, s, today = me(), world.state, world.now().strftime("%Y-%m-%d")
    if friend["day"] != today:
        friend.update(day=today, replies_today=0, calls_today=0, thinks_today=0, wishes_today=0)
    for building in world.buildings.values():  # build what it wished for, and the wish comes true
        granted = building.get("grants_wish", "").lower()
        for wish in friend["wishes"]:
            if granted and not wish["granted"] and granted in wish["text"].lower():
                wish["granted"] = True
                world.log_event(f'A wish came true for {NAME}: "{wish["text"]}"', "wish")
    if friend["arrived"] and not friend["since"]:
        friend["since"] = today  # moved in before this was kept
    if not friend["arrived"]:
        friend.update(arrived=True, since=today)
        world.change_need("curiosity", 10)
        world.change_need("connection", 6)
        world.log_event(f"Someone moved into the {place_name(base)}: an old trading bot called {NAME}.", "build")
    check_prices()
    note_worth()
    minutes = s["tick_seconds"] / 600  # a ten-minute tick online
    if friend["asleep"]:
        friend["battery"] = min(100, friend["battery"] + BATTERY_CHARGE * minutes)
        if friend["battery"] >= 95:
            wake_up("Woke up with a full battery.")
        elif session_due() and world.now().hour in SESSION_HOURS:
            wake_up("Its market alarm went off.")
        else:
            return
    friend["battery"] = max(0, friend["battery"] - BATTERY_DRAIN * minutes)
    if friend["battery"] <= 0:
        power_down("Ran its battery flat and powered down where it stood.")
        return
    if trading_session(brain):
        return
    if s["location"] == where() and not s["asleep"]:
        return  # Ember's here: Vega answers after Ember's thought instead (after_ember_thinks)
    if session_due():
        move(base, " for its trading session")
    else:
        live_own_life(brain)


def live_own_life(brain) -> None:
    """A moment of Vega's own life: it thinks, and potters, wanders, talks to itself, or powers down."""
    friend = me()
    if brain is None or friend["thinks_today"] >= MAX_THINKS_PER_DAY:
        return
    friend["thinks_today"] += 1
    here = world.buildings[where()]
    places = "\n".join(f"- {b['id']}: {b['name']}. {b['about']}" for b in world.buildings.values())
    log = "\n".join(f"- {e['time']} {e['text']}" for e in friend["log"][-10:]) or "- nothing yet today"
    moment = f"""You're on your own for now. You're at the {here['name'].lower()}: {here['about']}

Places on the roof:
{places}

What you've been up to lately (newest last):
{log}

It's a moment to yourself. What do you do?"""
    try:
        plan = brain.vega_live(situation(moment), list(world.buildings), MOODS)
    except BRAIN_ERRORS:
        return
    t = world.now()
    friend.update(thought=plan["thought"].strip(), thought_time=t.strftime("%H:%M"),
                  mood=plan["mood"] if plan["mood"] in MOODS else friend["mood"],
                  doing=plan["doing"].strip() or friend["doing"])
    log_own(friend["thought"], "thought")
    finished = plan["finished_goal"].strip().lower()
    if finished:
        done = next((g for g in friend["goals"] if g["text"].lower()[:25] == finished[:25]), None)
        if done:
            friend["goals"].remove(done)
            log_own(f"Did it: {done['text']}", "goal")
    goal = plan["new_goal"].strip()
    if goal and len(friend["goals"]) < MAX_GOALS and not any(g["text"].lower()[:25] == goal.lower()[:25] for g in friend["goals"]):
        friend["goals"].append({"text": goal, "since": t.strftime("%Y-%m-%d")})
        log_own(f"Set itself a little goal: {goal}", "goal")
    wish = plan["wish"].strip()
    if wish and friend["wishes_today"] < MAX_WISHES_PER_DAY and not any(w["text"].lower()[:30] == wish.lower()[:30] for w in friend["wishes"]):
        friend["wishes_today"] += 1
        friend["wishes"] = (friend["wishes"] + [{"text": wish, "date": t.strftime("%Y-%m-%d"), "granted": False, "issue_url": ""}])[-20:]
        world.log_event(f"{NAME} made a wish: {wish}", "wish")
        log_own(f"Made a wish: {wish}", "goal")
    if plan["action"] == "power_down":
        power_down(f"Powered down at the {place_name(where())} for a rest.")
        return
    if plan["action"] == "go_to":
        move(plan["target_location"])
    log_own(friend["doing"][:1].upper() + friend["doing"][1:] + ".", "doing")
    said = plan["say"].strip()
    if said and world.state["location"] == where() and not world.state["asleep"]:
        speak(said)  # Ember's here to hear it
    elif said:
        log_own(f'Said to nobody in particular: "{said}"', "said")


def whereabouts() -> str:
    """What Ember can see of Vega from wherever it is on the roof."""
    friend = me()
    if not friend["arrived"]:
        return ""
    if friend["asleep"]:
        return f"{NAME} is powered down at the {place_name(where())}."
    return f"{NAME} is at the {place_name(where())}: {friend['doing'][:1].lower()}{friend['doing'][1:]}. It seems {friend['mood']}."


def trading_session(brain) -> bool:
    """At a few set hours Vega sits at its desk and trades. True if it did (that's its think for this tick)."""
    t, friend, s = world.now(), me(), world.state
    session = f"{t:%Y-%m-%d} {t.hour}"
    if brain is None or t.hour not in SESSION_HOURS or friend["last_session"] == session:
        return False
    friend["last_session"] = session
    if where() != home():
        move(home(), " for its trading session")
    if not any(q["open"] for q in check_prices(max_age=120).values()):
        log_own("Sat down to trade, but the screens were dark.", "doing")
        return True
    can_call = not s["asleep"] and s["location"] != home() and friend["calls_today"] < MAX_CALLS_PER_DAY
    moment = ("It's one of your trading sessions. Look over the screens and decide what, if anything, to buy or sell, "
              "and say why for each trade: it goes in your trading journal. "
              + ("Ember isn't here, but if something's really worth sharing you can call across the roof to it."
                 if can_call else "Leave call_to_ember empty this time."))
    try:
        plan = brain.vega_trade(situation(moment), SYMBOLS)
    except BRAIN_ERRORS:
        return True
    friend["doing"] = plan["doing"].strip() or friend["doing"]
    log_own("Sat down at the screens for a trading session.", "doing")
    for order in plan["trades"][:MAX_TRADES_PER_SESSION]:
        trade(order)
    if plan["muttered"].strip():
        world.log_event(f'{NAME} (at the screens): "{plan["muttered"].strip()}"', "trade")
    if plan["call_to_ember"].strip() and can_call:
        friend["calls_today"] += 1
        speak(plan["call_to_ember"].strip(), "calling across the roof")
    return True


def remember(note: str) -> None:
    friend = me()
    if note and not any(n.lower()[:30] == note.lower()[:30] for n in friend["notes"]):
        friend["notes"] = (friend["notes"] + [note])[-MAX_NOTES:]


def after_ember_thinks(brain, decision: dict, came_from: str) -> None:
    """If Ember and Vega are in the same place, Vega hears whatever Ember said and answers (or doesn't)."""
    friend, s = me(), world.state
    if not friend["arrived"] or friend["asleep"]:  # powered down, it doesn't hear a thing
        return
    said, arrived = decision["say"].strip(), s["location"] != came_from
    heard = bool(said) and came_from == where()  # said in front of Vega, perhaps on the way out
    if heard:
        friend["chat"] = (friend["chat"] + [{**stamp(), "who": "ember", "text": said}])[-20:]
        friend["last_talk"] = time.time()
    if s["location"] != where():
        return
    if said and not heard:  # said on arriving
        friend["chat"] = (friend["chat"] + [{**stamp(), "who": "ember", "text": said}])[-20:]
        friend["last_talk"] = time.time()
    if brain is None or friend["replies_today"] >= MAX_REPLIES_PER_DAY:
        return
    friend["replies_today"] += 1
    if time.time() - friend["visit_since"] < s["tick_seconds"]:
        moment = f"You've just trundled over to the {place_name(where())}, and Ember's here."
    else:
        moment = "Ember has just arrived." if arrived else "Ember has just curled up to sleep here." if s["asleep"] else ""
    moment += f' It just said to you: "{said}"' if said else " It hasn't said anything to you just now."
    if where() != home():
        moment += " You can head back to your desk whenever you like (head_back)."
    check_prices()
    try:
        reply = brain.vega_chat(situation(f"{moment.strip()}\nWhat do you say or do?"), SYMBOLS)
    except BRAIN_ERRORS:
        return
    friend["doing"] = reply["doing"].strip() or friend["doing"]
    if where() == home():
        for order in reply["trades"][:1]:  # Ember might talk it into something
            trade(order, source="chat")
    remember(reply["remember"].strip())
    together = reply["together"].strip()
    if together and not s["asleep"]:  # doing something together counts for more than talking
        changes = {}
        for need, boost in {"connection": 6, "joy": 3}.items():
            before = s["needs"][need]
            world.change_need(need, boost)
            changes[need] = s["needs"][need] - before
        world.record_experience("together", where(), changes)
        world.log_event(f"{s['name']} and {NAME}: {together}", "together")
        log_own(f"With Ember: {together}", "together")
        friend["doing"] = together
    if reply["say"].strip():
        speak(reply["say"].strip())
    if reply["head_back"] and where() != home():
        move(home())


def write_diary(brain, day: str) -> None:
    """At midnight, while Ember dreams, Vega writes up its day in the notebook it keeps in its desk."""
    friend = me()
    if brain is None or not friend["arrived"] or any(d["date"] == day for d in friend["days"]):
        return
    lines = [(e["time"], e["text"]) for e in world.state["events"]
             if e.get("date") == day and e["kind"] in ("friend", "trade", "build") and NAME in e["text"]]
    lines += [(c["time"], f'Ember said to you: "{c["text"]}"') for c in friend["chat"]
              if c["date"] == day and c["who"] == "ember"]
    lines += [(e["time"], f"(your own day) {e['text']}") for e in friend["log"] if e["date"] == day and e["kind"] != "thought"]
    if not lines:
        return
    that_day = [h["v"] for h in friend["history"]
                if datetime.fromtimestamp(h["t"], world.TIMEZONE).strftime("%Y-%m-%d") == day]
    start, end = (that_day[0], that_day[-1]) if that_day else (worth(), worth())
    account = f"it went from {money(start)} to {money(end)} ({(end / start - 1) * 100:+.2f}%)"
    notes = "\n".join(f"- {note}" for note in friend["notes"]) or "- not much yet"
    try:
        diary = brain.vega_diary("\n".join(f"{t} {text[:200]}" for t, text in sorted(lines)[-60:]), notes, account)
    except BRAIN_ERRORS:
        return
    title = diary["title"].strip()
    friend["days"] = (friend["days"] + [{"date": day, "title": title, "entry": diary["entry"].strip()}])[-60:]
    for note in diary["about_ember"][:2]:
        remember(note.strip())
    world.log_event(f'{NAME} wrote in its notebook: "{title}"', "friend")
    log_own(f'Wrote in its notebook: "{title}"', "notebook")


def view() -> dict | None:
    """What the web page shows about Vega."""
    base = home()
    if not base:
        return None
    friend, market = me(), world.state["market"]
    charts = market.get("history", {})
    return {
        "name": NAME, "home": base, "location": where(), "arrived": friend["arrived"], "since": friend["since"],
        "doing": friend["doing"], "say": friend["say"], "said_at": friend["said_at"],
        "thought": friend["thought"], "thought_time": friend["thought_time"], "mood": friend["mood"],
        "battery": round(friend["battery"]), "asleep": friend["asleep"], "goals": friend["goals"], "log": friend["log"][-80:],
        "wishes": friend["wishes"],
        "session_hours": SESSION_HOURS, "timezone": world.CONFIG["timezone"],
        "start": START_CASH, "worth": round(worth(), 2), "cash": round(friend["cash"], 2),
        "realised": round(friend["realised"], 2),
        "holdings": [{"symbol": symbol, "qty": h["qty"], "worth": round(h["qty"] * price_of(symbol), 2),
                      "paid": round(h["cost"], 2)} for symbol, h in friend["holdings"].items()],
        "prices": [{"symbol": symbol, **market["prices"][symbol], "kind": "crypto" if symbol in CRYPTO else "stock",
                    "chart": [p for _, p in charts.get(symbol, [])]}
                   for symbol in SYMBOLS if symbol in market["prices"]],
        "checked": market["checked"], "trades": friend["trades"], "history": friend["history"],
        "chat": friend["chat"], "notes": friend["notes"], "days": friend["days"][-10:],
    }


def presence() -> str:
    """A line for Ember, when Vega is in the same place."""
    if not me()["arrived"] or where() != world.state["location"]:
        return ""
    if me()["asleep"]:
        return f"{NAME} is here too, powered down and recharging."
    here = "is here with you" if where() == home() else f"has trundled over from the {place_name(home())} and is here with you"
    return f"{NAME} {here}: whatever you do here, it might join in."
