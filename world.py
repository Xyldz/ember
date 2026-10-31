"""
world.py - Ember's rooftop: the rules of the world, Ember's memory, and one "tick" of its life.

Nothing here runs on its own. Two small programs drive it:
  run_local.py  - on your computer: a tick every couple of minutes, plus the web page at localhost
  tick_once.py  - on GitHub: one tick, then exit (GitHub Actions runs it every 15 minutes)

The web page only reads the two files this writes: site/data/state.json and site/data/gallery.json.
"""

import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

from brain import MEMORY_SECTIONS, SELF_SECTIONS, BrainError

HERE = Path(__file__).parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
TIMEZONE = ZoneInfo(CONFIG["timezone"])
DATA_DIR = HERE / "site" / "data"
STATE_FILE = DATA_DIR / "state.json"
GALLERY_FILE = DATA_DIR / "gallery.json"

NEEDS = ["charge", "curiosity", "joy", "calm", "connection"]
DECAY = {"charge": 2, "curiosity": 3, "joy": 1, "calm": 1, "connection": 2}  # lost every tick
# What each kind of activity tends to do to Ember's needs. The real effect varies each time,
# and places add their own "boosts", so Ember has to find out what works for it.
EFFECTS = {
    "rest": {"charge": 22, "calm": 4},
    "play": {"joy": 10, "charge": -4},
    "create": {"joy": 8, "calm": 3, "charge": -4},
    "learn": {"curiosity": 10, "charge": -3},
    "explore": {"curiosity": 7, "joy": 3, "charge": -4},
    "socialise": {"connection": 12, "joy": 3, "charge": -2},
    "reflect": {"calm": 10, "charge": -1},
    "search": {"curiosity": 14, "charge": -2},
}
KIND_WORDS = {"rest": "Resting", "play": "Playing", "create": "Making things", "learn": "Studying",
              "explore": "Exploring", "socialise": "Talking to things", "reflect": "Sitting with my thoughts",
              "search": "Searching the internet"}
FEELINGS = {"charge": "Running low on charge", "curiosity": "Bored, craving something new", "joy": "Feeling flat",
            "calm": "Restless and wound up", "connection": "Feeling lonely"}
BELIEF_WORDS = {  # (when it goes up, when it goes down)
    "charge": ("recharges me", "drains me"), "curiosity": ("feeds my curiosity", "bores me"),
    "joy": ("lifts me", "brings me down"), "calm": ("settles me", "winds me up"),
    "connection": ("makes me feel less alone", "makes me feel more alone"),
}
SECTION_TITLES = {"what_im_like": "What I'm like", "what_i_care_about": "What I care about",
                  "what_scares_me": "What scares me", "my_habits": "My habits"}
ACTION_WORDS = {"search": "search the internet", "rest": "recharge faster"}
PRACTICE_XP = 10  # doubled if Ember looked something up about it first
RESEARCH_XP = 5
MAX_WISHES_PER_DAY = 2
MAX_FORM_CHANGES_PER_DAY = 2
MAX_SELF_LINES = 10  # per section of the character sheet
MEMORY_SLOTS = 24  # per memory section: when it's full, a new memory has to beat the weakest one to get in
MEMORY_HALF_LIFE_DAYS = 21  # a memory's strength halves every three weeks unless something brings it back
FASCINATION_HALF_LIFE_DAYS = 7  # this week's reading counts more than last month's
STOPWORDS = set("""a about above after again against all also am an and any are around as at back be because been before
being below between both but by can can't could did do does doing don't down during each even few find for found from
further get had has have having he her here hers him his how i i'm if in into is it it's its itself just like look looks
made make many may me might more most much my new no nor not now of off on once one only or other our out over own really
same see she should so some something still such than that that's the their them then there there's these they thing
things this those through to too under until up use used using very via was way we well were what when where which while
who whom why will with would you you're your ember""".split())

state: dict = {}
gallery: list = []
buildings: dict = {}
empty_lots: list = []
personality: dict = {}


# ---------------------------------------------------------------------------
# Loading and saving
# ---------------------------------------------------------------------------

def new_state() -> dict:
    return {
        "name": CONFIG["name"], "location": "terminal", "born": "",
        "needs": {"charge": 80, "curiosity": 60, "joy": 60, "calm": 60, "connection": 50},
        "activity": "Flickering into existence", "thought": "", "thought_time": "", "say": "", "said_at": 0,
        "form": {"shape": "orb", "color": "#3ff0ff", "about": "A small glowing orb of light, newly awake."},
        "hobbies": [], "learned": [], "events": [], "wishes": [], "known_buildings": [],
        "self": {section: [] for section in SELF_SECTIONS},  # what Ember has written about itself
        "experience": {},  # what each activity, at each place, has done to Ember's needs
        "beliefs": [],     # lessons worked out from that experience
        "days": [],        # Ember's diary, one entry per day
        "memory": {section: [] for section in MEMORY_SECTIONS}, "memory_counter": 0,  # long-term memory
        "recent_kinds": [], "asleep": False, "status": "",
        "day": "", "thinks_today": 0, "searches_today": 0, "wishes_today": 0, "form_changes_today": 0,
        "costs": {"month": "", "usd": 0.0, "total_usd": 0.0},
        "tick_started_at": 0, "next_think_at": 0,
    }


def use_data_dir(path: Path) -> None:
    global DATA_DIR, STATE_FILE, GALLERY_FILE
    DATA_DIR, STATE_FILE, GALLERY_FILE = path, path / "state.json", path / "gallery.json"


def load_buildings() -> None:
    """Re-read buildings.json and personality.json, so your changes show up without a restart."""
    data = json.loads((HERE / "buildings.json").read_text(encoding="utf-8"))
    buildings.clear()
    buildings.update({b["id"]: b for b in data["buildings"]})
    empty_lots[:] = data.get("empty_lots", [])
    sheet = json.loads((HERE / "personality.json").read_text(encoding="utf-8"))
    personality.clear()
    personality.update({section: sheet.get(section, []) for section in SELF_SECTIONS})


def load() -> None:
    global gallery
    load_buildings()
    state.clear()
    state.update(new_state())
    if STATE_FILE.exists():
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.update({key: value for key, value in saved.items() if key in state})
    gallery = json.loads(GALLERY_FILE.read_text(encoding="utf-8")) if GALLERY_FILE.exists() else []


def reset() -> None:
    """Start Ember's life over: forget everything."""
    for path in (STATE_FILE, GALLERY_FILE):
        path.unlink(missing_ok=True)


def write_json(path: Path, data) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)  # swap in one go, so the page never reads a half-written file


def save() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(STATE_FILE, {
        **state,
        # Extra things only the web page needs
        "pressing": pressing_need(),
        "personality": personality,
        "memory_view": {section: sorted(({**m, "strength": round(memory_strength(m) / 5, 2)} for m in shelf),
                                        key=lambda m: -m["strength"]) for section, shelf in state["memory"].items()},
        "memory_slots": MEMORY_SLOTS,
        "fascinations": fascinations(),
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
                                           "kind": kind, "text": text}])[-300:]
    print(f"[{t:%H:%M}] {text}")


def change_need(need: str, amount: float) -> None:
    state["needs"][need] = max(0, min(100, round(state["needs"][need] + amount)))


def pressing_need() -> str:
    need = min(NEEDS, key=lambda n: state["needs"][n])
    if state["needs"][need] < 35:
        return FEELINGS[need]
    return "Content" if state["needs"][need] >= 70 else "Doing alright"


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
    state["wishes"] = (state["wishes"] + [{"text": text, "date": now().strftime("%Y-%m-%d"), "granted": False, "issue_url": ""}])[-20:]
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
    article = "an" if new_shape[0] in "aeiou" else "a"
    log_event(f"Changed form: now {article} {new_shape} ({new_color}). {who_i_am}".strip(), "form")


def notice_new_buildings() -> None:
    """When you add a building, Ember spots it (and any wish it grants comes true)."""
    known = set(state["known_buildings"])
    for building in buildings.values():
        if known and building["id"] not in known:
            change_need("joy", 15)
            change_need("curiosity", 15)
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
# Needs, experience, and the lessons Ember draws from it
# ---------------------------------------------------------------------------

def live_through(kind: str) -> None:
    """Apply what an activity does to Ember's needs, and remember how it felt."""
    here = state["location"]
    effects = dict(EFFECTS.get(kind, {}))
    for need, bonus in buildings[here].get("boosts", {}).items():
        if need in NEEDS:
            effects[need] = effects.get(need, 0) + bonus
    if kind == "rest" and can(here, "rest"):
        effects["charge"] = effects.get("charge", 0) + 12
    if state["recent_kinds"][-2:] == [kind, kind]:  # the same thing three times running gets dull
        effects["joy"] = effects.get("joy", 0) - 6
        effects["curiosity"] = effects.get("curiosity", 0) - 4

    record = state["experience"].setdefault(f"{kind}|{here}", {"count": 0, "totals": {}})
    record["count"] += 1
    for need, amount in effects.items():
        before = state["needs"][need]
        change_need(need, amount * random.uniform(0.6, 1.4))
        record["totals"][need] = record["totals"].get(need, 0) + state["needs"][need] - before
    state["recent_kinds"] = (state["recent_kinds"] + [kind])[-5:]
    update_beliefs()


def update_beliefs() -> None:
    """Turn experience into lessons, like 'Sitting with my thoughts at the rooftop edge settles me'."""
    beliefs = []
    for key, record in state["experience"].items():
        if record["count"] < 3:  # needs to have happened a few times before it counts as a lesson
            continue
        kind, place = key.split("|", 1)
        averages = {need: total / record["count"] for need, total in record["totals"].items()}
        if not averages:
            continue
        need, average = max(averages.items(), key=lambda item: abs(item[1]))
        if abs(average) < 2:
            continue
        place_name = buildings[place]["name"].lower() if place in buildings else "a place that's gone now"
        verb = BELIEF_WORDS[need][0 if average > 0 else 1]
        beliefs.append({"text": f"{KIND_WORDS[kind]} at the {place_name} {verb}.", "count": record["count"]})
    state["beliefs"] = sorted(beliefs, key=lambda b: -b["count"])[:12]


def about_me_text() -> str:
    lines = []
    for section in SELF_SECTIONS:
        entries = personality.get(section, []) + state["self"][section]
        if entries:
            lines.append(f"{SECTION_TITLES[section]}: " + "; ".join(entries))
    return "\n".join(lines) or "Nothing yet. You're still finding out."


def add_self_line(section: str, text: str) -> None:
    """Ember can add to its character sheet, never take away. The 'drift guard' stops near-repeats."""
    if section not in state["self"] or not text or len(state["self"][section]) >= MAX_SELF_LINES:
        return
    lower = text.lower()
    for line in personality.get(section, []) + state["self"][section]:
        if lower[:25] in line.lower() or line.lower()[:25] in lower:
            return
    state["self"][section].append(text)
    log_event(f"Realised something about itself: {text}", "self")


# ---------------------------------------------------------------------------
# Long-term memory: small, and it fades
# ---------------------------------------------------------------------------

def days_since(date: str) -> int:
    try:
        return max(0, (now().date() - datetime.strptime(date, "%Y-%m-%d").date()).days)
    except ValueError:
        return 0


def memory_strength(memory: dict) -> float:
    return memory["importance"] * 0.5 ** (days_since(memory["last_seen"]) / MEMORY_HALF_LIFE_DAYS)


def bring_back(memory_id: str) -> None:
    """Something reminded Ember of a memory, so it stops fading for now."""
    for shelf in state["memory"].values():
        for memory in shelf:
            if memory["id"] == memory_id:
                memory["last_seen"] = now().strftime("%Y-%m-%d")
                memory["times"] += 1


def keep_memory(section: str, text: str, importance: int) -> None:
    if section not in state["memory"] or not text:
        return
    shelf = state["memory"][section]
    for memory in shelf:
        if memory["text"].lower()[:30] == text.lower()[:30]:  # already holding this one
            bring_back(memory["id"])
            return
    importance = max(1, min(5, int(importance)))
    if len(shelf) >= MEMORY_SLOTS:
        weakest = min(shelf, key=memory_strength)
        if memory_strength(weakest) >= importance:
            return  # not worth more than anything already there, so it never gets in
        shelf.remove(weakest)
        log_event(f"Forgot: {weakest['text']}", "forgot")
    state["memory_counter"] += 1
    today = now().strftime("%Y-%m-%d")
    shelf.append({"id": f"m{state['memory_counter']}", "text": text, "importance": importance,
                  "first": today, "last_seen": today, "times": 1})


def strongest_memories(count: int) -> list[dict]:
    everything = [m for shelf in state["memory"].values() for m in shelf]
    return sorted(everything, key=memory_strength, reverse=True)[:count]


def fascinations() -> list[dict]:
    """Words that keep turning up in what Ember reads online. Attraction, not opinion."""
    scores = {}
    for item in state["learned"]:
        if not item.get("query"):
            continue
        weight = 0.5 ** (days_since(item.get("date", "")) / FASCINATION_HALF_LIFE_DAYS)
        for word in re.findall(r"[a-z][a-z-]{2,}", f"{item['query']} {item['text']}".lower().replace("'", "")):
            if word not in STOPWORDS:
                scores[word] = scores.get(word, 0) + weight
    top = sorted(scores.items(), key=lambda item: -item[1])[:8]
    return [{"word": word, "score": round(score, 1)} for word, score in top if score >= 2]


def write_diary(brain, day: str, final: bool = True) -> None:
    """Ember 'dreams' over a day: writes its diary, sorts the day into long-term memory, and may notice
    something new about itself. final=False is the 'dream now' button; the real dream that night redoes the day."""
    if brain is None or any(d["date"] == day and d.get("final", True) for d in state["days"]):
        return
    events = [e for e in state["events"] if e.get("date") == day]
    if not events:
        return
    memories = "\n".join(f"{m['id']}: {m['text']}" for shelf in state["memory"].values() for m in shelf) or "(none yet)"
    try:
        reflection = brain.reflect("\n".join(f"{e['time']} {e['text'][:200]}" for e in events[-60:]), about_me_text(), memories)
    except (BrainError, json.JSONDecodeError, anthropic.APIStatusError, anthropic.APIConnectionError) as error:
        state["status"] = f"Couldn't dream: {getattr(error, 'message', error)}"
        return
    title = reflection["title"].strip()
    state["days"] = [d for d in state["days"] if d["date"] != day]
    state["days"] = (state["days"] + [{"date": day, "title": title, "entry": reflection["entry"].strip(), "final": final}])[-90:]
    log_event(f'Wrote in its diary: "{title}"', "diary")
    for memory_id in reflection["came_back"]:
        bring_back(memory_id.strip())
    for memory in reflection["new_memories"][:4]:
        keep_memory(memory["section"], memory["text"].strip(), memory["importance"])
    for line in reflection["about_me"][:2]:
        add_self_line(line["section"], line["text"].strip())


# ---------------------------------------------------------------------------
# What Ember knows, written as plain text for the brain
# ---------------------------------------------------------------------------

def describe_situation() -> str:
    t = now()
    part_of_day = ("night" if t.hour < 6 or t.hour >= 21 else "morning" if t.hour < 12
                   else "afternoon" if t.hour < 17 else "evening")
    here = buildings[state["location"]]
    needs = ", ".join(f"{need} {state['needs'][need]}" for need in NEEDS)
    feelings = " ".join(f"{FEELINGS[need]}." for need in NEEDS if state["needs"][need] < 35)

    def unlocks(building: dict) -> str:
        words = [ACTION_WORDS[a] for a in building.get("actions", []) if a in ACTION_WORDS]
        return f" Here you can {' and '.join(words)}." if words else ""

    places = "\n".join(f"- {b['id']} ({b['name']}): {b['about']}{unlocks(b)}" for b in buildings.values())
    hobbies = "\n".join(
        f"- {h['name']}: level {skill_level(h['xp'])[0]}/10"
        + (" (you read something that will help next time you practise)" if h["inspired"] else "")
        for h in state["hobbies"]
    ) or "- none yet"
    lessons = "\n".join(f"- {b['text']} (borne out {b['count']} times)" for b in state["beliefs"]) or "- nothing yet"
    made = "\n".join(f'- "{w["title"]}" ({w["type"]})' for w in gallery[-4:]) or "- nothing yet"
    wishes = "\n".join(f'- {w["text"]} ({"came true!" if w["granted"] else "still waiting"})'
                       for w in state["wishes"][-6:]) or "- none yet"
    long_term = "\n".join(f"- {m['text']}" for m in strongest_memories(10)) or "- nothing yet"
    notes = "\n".join(
        f"- {m['text'][:220]}" + (f" (looked up: {m['query']})" if m.get("query") else "")
        for m in state["learned"][-8:]
    ) or "- nothing yet"
    keeps_coming_up = ", ".join(f["word"] for f in fascinations()) or "nothing yet"
    yesterday = state["days"][-1] if state["days"] else None
    recent = "\n".join(f"- {e['time']} {e['text']}" for e in state["events"][-14:] if e["kind"] != "thought") or "- nothing yet"
    searches_left = max(0, CONFIG["max_searches_per_day"] - state["searches_today"])

    return f"""It is {t:%A %d %B, %H:%M} ({part_of_day}).
You are at: {here['name']} ({state['location']}). {here['about']}
Your form: shape {state['form']['shape']}, colour {state['form']['color']}. In your words: {state['form']['about']}
Your needs (0-100, higher is better): {needs}. {feelings}

Who you are:
{about_me_text()}

What experience has taught you:
{lessons}

Places on your rooftop:
{places}
There are also {len(empty_lots)} empty lots where new things could be built one day.

Internet searches left today: {searches_left}

Your interests:
{hobbies}

Things you've made (newest last):
{made}

Your wishes:
{wishes}

Your strongest memories:
{long_term}

Notes and things you've read lately (newest last):
{notes}
Words that keep coming up in what you read: {keeps_coming_up}
{f'Your last diary entry ({yesterday["date"]}): {yesterday["entry"]}' if yesterday else ''}

What happened recently (newest last):
{recent}

What do you do next?"""


# ---------------------------------------------------------------------------
# Applying Ember's decisions to the world
# ---------------------------------------------------------------------------

def apply_decision(decision: dict, brain) -> None:
    here = state["location"]
    state["thought"], state["thought_time"] = decision["thought"].strip(), now().strftime("%H:%M")
    log_event(state["thought"], "thought")

    if decision["say"].strip():
        state["say"], state["said_at"] = decision["say"].strip(), time.time()
        change_need("connection", 2)
        log_event(f'Said: "{state["say"]}"', "say")

    new_hobby = decision["new_hobby"].strip()
    if new_hobby and not find_hobby(new_hobby):
        state["hobbies"].append({"name": new_hobby, "xp": 0, "inspired": False})
        log_event(f"Took up a new interest: {new_hobby}!", "hobby")
        if len(state["hobbies"]) > 6:
            dropped = min(state["hobbies"][:-1], key=lambda h: h["xp"])
            state["hobbies"].remove(dropped)
            log_event(f"Lost interest in {dropped['name']}.")
    hobby = find_hobby(decision["practising_hobby"])

    if decision["wish"].strip():
        add_wish(decision["wish"].strip())
    change_form(decision["new_form"], decision["form_color"], decision["who_i_am"].strip())
    if decision["remember"].strip():
        state["learned"] = (state["learned"] + [{"date": now().strftime("%Y-%m-%d"), "time": now().strftime("%H:%M"),
                                                 "text": decision["remember"].strip()}])[-40:]
        log_event(f"Made a note: {decision['remember'].strip()}", "note")

    action = decision["action"]
    if action == "go_to":
        target = decision["target_location"]
        if target in buildings and target != here:
            state["location"] = target
            state["activity"] = f"Heading to the {buildings[target]['name'].lower()}"
            change_need("charge", -1)
            log_event(f"Went to the {buildings[target]['name'].lower()}.")

    elif action == "do_activity":
        kind, activity = decision["activity_kind"], decision["activity"].strip().rstrip(".")
        state["activity"] = activity[:1].upper() + activity[1:]
        log_event(state["activity"] + ".", kind)
        live_through(kind)
        if hobby:
            add_xp(hobby, PRACTICE_XP * (2 if hobby["inspired"] else 1))
            hobby["inspired"] = False
        if decision["creation"] != "none":
            make_creation(brain, decision["creation"], activity, hobby)

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
        "date": now().strftime("%Y-%m-%d"), "time": now().strftime("%H:%M"),
        "text": result["summary"], "query": query, "sources": result["sources"],
    }])[-40:]
    state["activity"] = f'Reading about "{query}"'
    log_event(f"Learned: {result['summary']}", "learned")
    live_through("search")
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
    state["activity"] = f'Looking at "{work["title"]}"'
    state["say"], state["said_at"] = f'Finished "{work["title"]}".', time.time()
    log_event(f'Made a {kind}: "{work["title"]}".', "creation")


# ---------------------------------------------------------------------------
# One tick: a moment of Ember's life
# ---------------------------------------------------------------------------

def sleep_tick(brain) -> None:
    if not state["asleep"]:
        t = now()  # write up the day that's ending (after midnight, that's yesterday) before drifting off
        write_diary(brain, (t if t.hour >= CONFIG["bedtime"] else t - timedelta(days=1)).strftime("%Y-%m-%d"))
        state.update(asleep=True, location="pod" if "pod" in buildings else state["location"],
                     activity="Sleeping", say="")
        log_event("Dimmed down and drifted off for the night.")
    change_need("charge", 8)
    change_need("calm", 2)
    state["status"] = f"Asleep until {CONFIG['wake_time']:02d}:00"


def live(brain, never_sleep: bool) -> None:
    if brain is None:
        state["status"] = "Brain offline: no API key (ANTHROPIC_API_KEY isn't set)."
        return
    hour = now().hour
    if not never_sleep and (hour >= CONFIG["bedtime"] or hour < CONFIG["wake_time"]):
        sleep_tick(brain)
        return
    if state["asleep"]:
        state.update(asleep=False, activity="Waking up", status="")
        log_event("Flickered back on.")
    if state["thinks_today"] >= CONFIG["max_thinks_per_day"]:
        state["status"] = "Daydreaming: reached today's think limit"
        return

    for need, amount in DECAY.items():  # time passes and every need slowly drains
        change_need(need, -amount)
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


def tick(brain, next_think_in_seconds: float, never_sleep: bool = False, dream_now: bool = False) -> None:
    load_buildings()
    t = now()
    today = t.strftime("%Y-%m-%d")
    if state["day"] != today:
        if state["day"]:
            write_diary(brain, state["day"])  # in case yesterday ended without a bedtime (e.g. --no-sleep)
        state.update(day=today, thinks_today=0, searches_today=0, wishes_today=0, form_changes_today=0)
    state["born"] = state["born"] or today
    if state["costs"]["month"] != t.strftime("%Y-%m"):
        state["costs"].update(month=t.strftime("%Y-%m"), usd=0.0)
    state["tick_started_at"] = time.time()
    notice_new_buildings()
    try:
        live(brain, never_sleep)
        if dream_now:
            write_diary(brain, today, final=False)
    finally:
        spent = brain.take_spent() if brain else 0.0
        state["costs"]["usd"] = round(state["costs"]["usd"] + spent, 5)
        state["costs"]["total_usd"] = round(state["costs"]["total_usd"] + spent, 5)
        state["next_think_at"] = time.time() + next_think_in_seconds
        save()
