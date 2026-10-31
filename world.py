"""
world.py - Ember's rooftop: the rules of the world, Ember's memory, and one "tick" of its life.

Nothing here runs on its own. Two small programs drive it:
  run_local.py  - on your computer: a tick every couple of minutes, plus the web page at localhost
  tick_once.py  - on GitHub: one tick, then exit (GitHub Actions runs it every 15 minutes)

The web page only reads the two files this writes: site/data/state.json and site/data/gallery.json.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

from brain import BrainError

HERE = Path(__file__).parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
TIMEZONE = ZoneInfo(CONFIG["timezone"])
DATA_DIR = HERE / "site" / "data"
STATE_FILE = DATA_DIR / "state.json"
GALLERY_FILE = DATA_DIR / "gallery.json"

# How each kind of activity changes Ember's charge and mood
EFFECTS = {
    "rest": {"energy": 25},
    "play": {"mood": 10, "energy": -5},
    "create": {"mood": 10, "energy": -4},
    "learn": {"mood": 8, "energy": -3},
    "explore": {"mood": 7, "energy": -5},
    "socialise": {"mood": 6, "energy": -2},
}
PRACTICE_XP = 10  # doubled if Ember looked up tips at the terminal first
RESEARCH_XP = 5
MAX_WISHES_PER_DAY = 2
MAX_FORM_CHANGES_PER_DAY = 2
ACTION_WORDS = {"search": "search the internet", "create": "make art, poems and music", "rest": "recharge faster"}

state: dict = {}
gallery: list = []
buildings: dict = {}
empty_lots: list = []


# ---------------------------------------------------------------------------
# Loading and saving
# ---------------------------------------------------------------------------

def new_state() -> dict:
    return {
        "name": CONFIG["name"], "location": "terminal", "energy": 80, "mood": 70,
        "activity": "Flickering into existence", "thought": "", "say": "", "said_at": 0,
        "form": {"shape": "orb", "color": "#3ff0ff", "about": "A small glowing orb of light, newly awake."},
        "hobbies": [], "learned": [], "events": [], "wishes": [], "known_buildings": [],
        "asleep": False, "status": "",
        "day": "", "thinks_today": 0, "searches_today": 0, "wishes_today": 0, "form_changes_today": 0,
        "costs": {"month": "", "usd": 0.0, "total_usd": 0.0},
        "tick_started_at": 0, "next_think_at": 0,
    }


def use_data_dir(path: Path) -> None:
    global DATA_DIR, STATE_FILE, GALLERY_FILE
    DATA_DIR, STATE_FILE, GALLERY_FILE = path, path / "state.json", path / "gallery.json"


def load_buildings() -> None:
    """Re-read buildings.json, so buildings you add show up without a restart."""
    data = json.loads((HERE / "buildings.json").read_text(encoding="utf-8"))
    buildings.clear()
    buildings.update({b["id"]: b for b in data["buildings"]})
    empty_lots[:] = data.get("empty_lots", [])


def load() -> None:
    global gallery
    load_buildings()
    state.clear()
    state.update(new_state())
    if STATE_FILE.exists():
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.update({key: value for key, value in saved.items() if key in state})
    gallery = json.loads(GALLERY_FILE.read_text(encoding="utf-8")) if GALLERY_FILE.exists() else []


def write_json(path: Path, data) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)  # swap in one go, so the page never reads a half-written file


def save() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(STATE_FILE, {
        **state,
        # Extra things only the web page needs
        "skills": [{"name": h["name"], "level": skill_level(h["xp"])[0], "progress": skill_level(h["xp"])[1],
                    "inspired": h["inspired"]} for h in state["hobbies"]],
        "buildings": list(buildings.values()),
        "empty_lots": empty_lots,
        "gallery_key": f"{len(gallery)}:{gallery[-1]['id'] if gallery else 0}",
        "today": now().strftime("%Y-%m-%d"),
        "max_searches_per_day": CONFIG["max_searches_per_day"],
        "support_url": CONFIG["support_url"],
        "support_text": CONFIG["support_text"],
    })
    write_json(GALLERY_FILE, gallery)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now() -> datetime:
    return datetime.now(TIMEZONE)


def log_event(text: str, kind: str = "event") -> None:
    t = now()
    state["events"] = (state["events"] + [{"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
                                           "kind": kind, "text": text}])[-200:]
    print(f"[{t:%H:%M}] {text}")


def change(stat: str, amount: float) -> None:
    state[stat] = max(0, min(100, round(state[stat] + amount)))


def can(building_id: str, action: str) -> bool:
    return action in buildings[building_id].get("actions", [])


def skill_level(xp: int) -> tuple[int, float]:
    """Turn skill points into (level 1-10, progress towards the next level from 0 to 1).
    Each level needs 30 more points than the one before."""
    level, needed = 1, 30
    while xp >= needed and level < 10:
        xp -= needed
        level += 1
        needed = 30 * level
    return level, 1.0 if level == 10 else xp / needed


def find_hobby(name: str) -> dict | None:
    """Match the brain's hobby name to one of Ember's hobbies, forgiving small wording differences."""
    name = name.strip().lower()
    if not name:
        return None
    for hobby in state["hobbies"]:
        if hobby["name"].lower() == name:
            return hobby
    for hobby in state["hobbies"]:
        if hobby["name"].lower() in name or name in hobby["name"].lower():
            return hobby
    return None


def add_xp(hobby: dict, amount: int) -> None:
    before = skill_level(hobby["xp"])[0]
    hobby["xp"] += amount
    after = skill_level(hobby["xp"])[0]
    if after > before:
        log_event(f"Got better at {hobby['name']}! Now level {after}.", "levelup")


def add_wish(text: str) -> None:
    if state["wishes_today"] >= MAX_WISHES_PER_DAY:
        return
    if any(w["text"].lower()[:30] == text.lower()[:30] for w in state["wishes"]):
        return
    t = now()
    state["wishes"] = (state["wishes"] + [{"text": text, "date": t.strftime("%Y-%m-%d"), "granted": False, "issue_url": ""}])[-20:]
    state["wishes_today"] += 1
    log_event(f"Made a wish: {text}", "wish")


def change_form(shape: str, color: str, who_i_am: str) -> None:
    """Ember decides what it looks like. Limited per day, so it means something."""
    form = state["form"]
    new_shape = shape if shape != "keep" else form["shape"]
    new_color = color.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", color.strip()) else form["color"]
    if (new_shape, new_color) == (form["shape"], form["color"]) or state["form_changes_today"] >= MAX_FORM_CHANGES_PER_DAY:
        return
    state["form"] = {"shape": new_shape, "color": new_color, "about": who_i_am or form["about"]}
    state["form_changes_today"] += 1
    log_event(f"Changed form: now a {new_shape} ({new_color}). {who_i_am}".strip(), "form")


def notice_new_buildings() -> None:
    """When you add a building, Ember spots it (and any wish it grants comes true)."""
    known = set(state["known_buildings"])
    for building in buildings.values():
        if known and building["id"] not in known:
            change("mood", 15)
            log_event(f"Something new appeared on the roof: {building['name']}!", "build")
        granted = building.get("grants_wish", "").lower()
        for wish in state["wishes"]:
            if granted and not wish["granted"] and granted in wish["text"].lower():
                wish["granted"] = True
                log_event(f'A wish came true: "{wish["text"]}"', "wish")
    state["known_buildings"] = list(buildings)
    if state["location"] not in buildings:
        state["location"] = next(iter(buildings))


# ---------------------------------------------------------------------------
# What Ember knows, written as plain text for the brain
# ---------------------------------------------------------------------------

def describe_situation() -> str:
    t = now()
    part_of_day = ("night" if t.hour < 6 or t.hour >= 21 else "morning" if t.hour < 12
                   else "afternoon" if t.hour < 17 else "evening")
    here = buildings[state["location"]]
    feelings = []
    if state["energy"] <= 25:
        feelings.append("Your battery is running low.")
    if state["mood"] <= 30:
        feelings.append("You feel flat and bored.")

    def unlocks(building: dict) -> str:
        words = [ACTION_WORDS[a] for a in building.get("actions", []) if a in ACTION_WORDS]
        return f" Here you can {' and '.join(words)}." if words else ""

    places = "\n".join(f"- {b['id']} ({b['name']}): {b['about']}{unlocks(b)}" for b in buildings.values())
    hobbies = "\n".join(
        f"- {h['name']}: level {skill_level(h['xp'])[0]}/10"
        + (" (you read something that will help next time you practise)" if h["inspired"] else "")
        for h in state["hobbies"]
    ) or "- none yet. You haven't found one"
    made = "\n".join(f'- "{w["title"]}" ({w["type"]})' for w in gallery[-4:]) or "- nothing yet"
    wishes = "\n".join(f'- {w["text"]} ({"came true!" if w["granted"] else "still waiting"})'
                       for w in state["wishes"][-6:]) or "- none yet"
    memories = "\n".join(
        f"- {m['text'][:220]}" + (f" (looked up: {m['query']})" if m.get("query") else "")
        for m in state["learned"][-12:]
    ) or "- nothing yet"
    recent = "\n".join(f"- {e['time']} {e['text']}" for e in state["events"][-14:] if e["kind"] != "thought") or "- nothing yet"
    searches_left = max(0, CONFIG["max_searches_per_day"] - state["searches_today"])

    return f"""It is {t:%A %d %B, %H:%M} ({part_of_day}).
You are at: {here['name']} ({state['location']}). {here['about']}
Your form: a {state['form']['color']} {state['form']['shape']}. In your words: {state['form']['about']}
Your energy: charge {state['energy']}/100, mood {state['mood']}/100. {' '.join(feelings)}

Places on your rooftop:
{places}
There are also {len(empty_lots)} empty lots where new things could be built one day.

Internet searches left today: {searches_left}

Your hobbies and skill levels:
{hobbies}

Things you've made (newest last):
{made}

Your wishes:
{wishes}

Things you remember (newest last):
{memories}

What happened recently (newest last):
{recent}

What do you do next?"""


# ---------------------------------------------------------------------------
# Applying Ember's decisions to the world
# ---------------------------------------------------------------------------

def apply_decision(decision: dict, brain) -> None:
    here = state["location"]
    state["thought"] = decision["thought"].strip()
    log_event(state["thought"], "thought")

    if decision["say"].strip():
        state["say"], state["said_at"] = decision["say"].strip(), time.time()
        log_event(f'Said: "{state["say"]}"', "say")

    new_hobby = decision["new_hobby"].strip()
    if new_hobby and not find_hobby(new_hobby):
        state["hobbies"].append({"name": new_hobby, "xp": 0, "inspired": False})
        log_event(f"Took up a new hobby: {new_hobby}!", "hobby")
        if len(state["hobbies"]) > 6:
            dropped = min(state["hobbies"][:-1], key=lambda h: h["xp"])
            state["hobbies"].remove(dropped)
            log_event(f"Lost interest in {dropped['name']}.")
    hobby = find_hobby(decision["practising_hobby"])

    if decision["wish"].strip():
        add_wish(decision["wish"].strip())
    change_form(decision["new_form"], decision["form_color"], decision["who_i_am"].strip())
    if decision["remember"].strip():
        state["learned"] = (state["learned"] + [{"time": now().strftime("%H:%M"), "text": decision["remember"].strip()}])[-40:]
        log_event(f"Made a note: {decision['remember'].strip()}", "note")

    action = decision["action"]
    if action == "go_to":
        target = decision["target_location"]
        if target in buildings and target != here:
            state["location"] = target
            state["activity"] = f"Heading to the {buildings[target]['name'].lower()}"
            change("energy", -2)
            log_event(f"Went to the {buildings[target]['name'].lower()}.")

    elif action == "do_activity":
        kind, activity = decision["activity_kind"], decision["activity"].strip().rstrip(".")
        creation = decision["creation"]
        if creation != "none" and not can(here, "create"):
            log_event(f"Wanted to make a {creation}, but there's nothing to make it with at the {buildings[here]['name'].lower()}.")
            return
        for stat, amount in EFFECTS.get(kind, {}).items():
            change(stat, amount)
        if kind == "rest" and can(here, "rest"):
            change("energy", 15)
        state["activity"] = activity[:1].upper() + activity[1:]
        log_event(state["activity"] + ".", kind)
        if hobby:
            add_xp(hobby, PRACTICE_XP * (2 if hobby["inspired"] else 1))
            hobby["inspired"] = False
        if creation != "none":
            make_creation(brain, creation, activity, hobby)

    elif action == "search_internet":
        query = decision["activity"].strip()
        if not can(here, "search"):
            log_event(f'Wanted to look up "{query}", but there\'s no internet at the {buildings[here]["name"].lower()}.')
        elif state["searches_today"] >= CONFIG["max_searches_per_day"]:
            log_event("The terminal says: DAILY DATA ALLOWANCE USED UP. Try again tomorrow.")
        else:
            state["searches_today"] += 1
            research(brain, query, hobby)


def research(brain, query: str, hobby: dict | None) -> None:
    state["activity"] = f'Searching the internet for "{query}"'
    log_event(f'Searched the internet for "{query}".', "search")
    save()  # let the page show the search while it runs
    try:
        result = brain.search(query)
    except (BrainError, anthropic.APIStatusError, anthropic.APIConnectionError) as error:
        state["status"] = f"Search failed: {getattr(error, 'message', error)}"
        log_event("The terminal's connection dropped.")
        return
    state["learned"] = (state["learned"] + [{
        "time": now().strftime("%H:%M"), "text": result["summary"], "query": query, "sources": result["sources"],
    }])[-40:]
    change("mood", 6)
    log_event(f"Learned: {result['summary']}", "learned")
    if hobby:
        add_xp(hobby, RESEARCH_XP)
        hobby["inspired"] = True
        log_event(f"Feels inspired to practise {hobby['name']}.", "note")


def make_creation(brain, kind: str, activity: str, hobby: dict | None) -> None:
    level = skill_level(hobby["xp"])[0] if hobby else 1
    state["activity"] = f"Working on a {kind}..."
    save()
    try:
        work = brain.create(kind, activity, hobby["name"] if hobby else "", level,
                            [m["text"] for m in state["learned"][-5:]],
                            [w for w in gallery if w["type"] == kind][-2:])
    except (BrainError, json.JSONDecodeError, anthropic.APIStatusError, anthropic.APIConnectionError) as error:
        state["status"] = f"Couldn't finish the {kind}: {getattr(error, 'message', error)}"
        return

    if kind == "drawing":
        svg = work["svg"]
        start = svg.find("<svg")
        if start == -1 or len(svg) > 60_000 or "foreignobject" in svg.lower():
            log_event("Made a glitchy drawing, didn't like it, and deleted it.")
            return
        svg = svg[start:]
        if "xmlns=" not in svg.split(">", 1)[0]:
            svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)  # browsers need this to show it
        work["svg"] = svg

    t = now()
    gallery.append({"id": int(time.time() * 1000), "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
                    "type": kind, "hobby": hobby["name"] if hobby else "", "level": level, **work})
    del gallery[:-100]
    state["activity"] = f'Admiring "{work["title"]}"'
    state["say"], state["said_at"] = f'Finished "{work["title"]}"!', time.time()
    log_event(f'Made a {kind}: "{work["title"]}".', "creation")


# ---------------------------------------------------------------------------
# One tick: a moment of Ember's life
# ---------------------------------------------------------------------------

def sleep_tick() -> None:
    if not state["asleep"]:
        state.update(asleep=True, location="pod" if "pod" in buildings else state["location"],
                     activity="Sleeping", thought="Zzz...", say="")
        log_event("Dimmed down and drifted off for the night.")
    change("energy", 8)
    state["status"] = f"Asleep until {CONFIG['wake_time']:02d}:00"


def live(brain, never_sleep: bool) -> None:
    if brain is None:
        state["status"] = "Brain offline: no API key. Set ANTHROPIC_API_KEY and restart."
        return
    hour = now().hour
    if not never_sleep and (hour >= CONFIG["bedtime"] or hour < CONFIG["wake_time"]):
        sleep_tick()
        return
    if state["asleep"]:
        state.update(asleep=False, activity="Waking up", status="")
        log_event("Flickered back on.")
    if state["thinks_today"] >= CONFIG["max_thinks_per_day"]:
        state["status"] = "Daydreaming: reached today's think limit"
        return

    change("energy", -2)  # time passes: a little tireder and a little more bored
    change("mood", -1)
    state["thinks_today"] += 1
    try:
        decision = brain.decide(describe_situation(), list(buildings))
    except anthropic.AuthenticationError:
        state["status"] = "Brain offline: the API key was rejected."
        return
    except anthropic.RateLimitError:
        state["status"] = "Brain resting: rate limited (or out of credits)."
        return
    except anthropic.APIStatusError as error:
        state["status"] = f"Brain error ({error.status_code}): {error.message}"
        return
    except anthropic.APIConnectionError:
        state["status"] = "Brain offline: can't reach the internet."
        return
    except (BrainError, json.JSONDecodeError) as error:
        state["status"] = f"Brain glitch: {error}"
        return
    state["status"] = ""
    apply_decision(decision, brain)


def tick(brain, next_think_in_seconds: float, never_sleep: bool = False) -> None:
    load_buildings()
    t = now()
    if state["day"] != t.strftime("%Y-%m-%d"):
        state.update(day=t.strftime("%Y-%m-%d"), thinks_today=0, searches_today=0, wishes_today=0, form_changes_today=0)
    if state["costs"]["month"] != t.strftime("%Y-%m"):
        state["costs"].update(month=t.strftime("%Y-%m"), usd=0.0)
    state["tick_started_at"] = time.time()
    notice_new_buildings()
    try:
        live(brain, never_sleep)
    finally:
        spent = brain.take_spent() if brain else 0.0
        state["costs"]["usd"] = round(state["costs"]["usd"] + spent, 5)
        state["costs"]["total_usd"] = round(state["costs"]["total_usd"] + spent, 5)
        state["next_think_at"] = time.time() + next_think_in_seconds
        save()
