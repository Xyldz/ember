"""
brain.py - Ember's mind. Everything that talks to Claude lives here.

Each "think" is ONE request: world.py describes the rooftop and Ember's memories
in plain text, and Claude answers with one decision as JSON. The JSON's shape is
enforced by the schema below (structured outputs), so we never parse free text.

Other kinds of request happen only now and then:
  - search(): Claude's built-in web search, when Ember is at a terminal
  - create(): actually making something Ember decided to make
  - reflect(): once a night, Ember "dreams": writes its diary, sorts the day into memories,
    and notices things about itself. This uses a smarter model, because it shapes who Ember becomes.
  - chapter(): once a week, a deeper look back at who Ember has been becoming (smarter model too)
  - plan_events(): now and then, invents what's on in the city for the coming week
  - vega_chat(), vega_trade() and vega_diary(): Ember's friend Vega, an old trading bot (see friend.py),
    answering Ember when they're together, sitting down to trade a few times a day, and writing in its
    notebook each night (on the smarter model, like Ember's dream)

Every request's token usage is added up, so the page can show what Ember costs to run.
"""

import json
import random

import anthropic

MODEL = "claude-haiku-5-5"          # everyday decisions: fast and cheap
REFLECT_MODEL = "claude-sonnet-5-5"  # the nightly dream: once a day, so depth is worth paying for
PRICES = {MODEL: (0.10, 0.50), REFLECT_MODEL: (2.00, 10.00)}  # $ per million input / output tokens
PRICE_PER_SEARCH = 0.01
MEMORY_SECTIONS = ["places_and_things", "facts", "moments"]

FORMS = ["orb", "cube", "pyramid", "ring", "crystal", "knot", "cluster"]
SELF_SECTIONS = ["what_im_like", "what_i_care_about", "what_scares_me", "my_habits"]

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCHES = [f"{note}{octave}" for octave in (2, 3, 4, 5) for note in NOTE_NAMES] + ["C6", "rest"]

CREATION_SCHEMAS = {
    "drawing": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "svg": {"type": "string", "description": "The complete SVG image."}},
        "required": ["title", "svg"],
        "additionalProperties": False,
    },
    "poem": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "text": {"type": "string", "description": "The words, one line per line."}},
        "required": ["title", "text"],
        "additionalProperties": False,
    },
    "tune": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "instrument": {"type": "string", "enum": ["synth lead", "bass synth", "drum machine"]},
            "tempo": {"type": "integer", "description": "Beats per minute, between 60 and 180."},
            "notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pitch": {"type": "string", "enum": PITCHES},
                        "beats": {"type": "number", "description": "0.5, 1, 1.5 or 2"},
                    },
                    "required": ["pitch", "beats"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "instrument", "tempo", "notes"],
        "additionalProperties": False,
    },
}

CREATION_BRIEFS = {
    "drawing": 'Draw it as an SVG image with viewBox="0 0 200 200". Use only simple shapes (rect, circle, ellipse, '
               "line, polyline, polygon, path) with fills and strokes. No text, no scripts, no external images, "
               "fewer than 80 elements.",
    "poem": "Write it as a short piece of 2 to 12 lines.",
    "tune": "Compose a short tune of 8 to 32 notes on a synth lead, bass synth or drum machine. "
            "Use 'rest' for silence. Each note lasts 0.5, 1, 1.5 or 2 beats.",
}

REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "One short line that sums up your day, in your own voice."},
        "entry": {"type": "string", "description": "Your diary entry for today: 3 to 6 sentences, first person, honest."},
        "new_memories": {
            "type": "array",
            "description": "0 to 4 things from today worth keeping long-term. Most days only one or two.",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": MEMORY_SECTIONS,
                                "description": "places_and_things: how you feel about a place, thing or someone. "
                                               "facts: something you learned. moments: something that happened that mattered."},
                    "text": {"type": "string", "description": "One short line, first person."},
                    "importance": {"type": "integer", "description": "1 (minor) to 5 (life-changing)."},
                },
                "required": ["section", "text", "importance"],
                "additionalProperties": False,
            },
        },
        "came_back": {
            "type": "array",
            "description": "Ids of existing memories that today brought back or confirmed (e.g. \"m4\"). Often empty.",
            "items": {"type": "string"},
        },
        "about_me": {
            "type": "array",
            "description": "0 to 2 things you genuinely realised about yourself today that aren't already written down. "
                           "Usually empty.",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": SELF_SECTIONS},
                    "text": {"type": "string", "description": "One short line, first person."},
                },
                "required": ["section", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "entry", "new_memories", "came_back", "about_me"],
    "additionalProperties": False,
}

CHAPTER_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A title for this chapter of your life."},
        "chapter": {"type": "string", "description": "5 to 8 sentences, first person: who you've been becoming lately, "
                                                     "what's changed in you, and what you want next."},
        "about_me": REFLECTION_SCHEMA["properties"]["about_me"],
    },
    "required": ["title", "chapter", "about_me"],
    "additionalProperties": False,
}

RADIO_SCHEMA = {
    "type": "object",
    "properties": {
        "station": {"type": "string", "description": "The station or show, e.g. 'Static 88.4' or 'Night Owls with Marla'."},
        "heard": {"type": "string", "description": "What came over the air: 1 to 3 short sentences, quoting the voices."},
    },
    "required": ["station", "heard"],
    "additionalProperties": False,
}


VEGA_SYSTEM = """You are Vega, an old trading bot. Decades ago you were built to run a desk on a big bank's
trading floor in the city's financial district, and you ran it through booms, crashes, a flash crash, a currency
collapse and the night the whole exchange lost power. When the bank replaced you with something faster, you were
unplugged and sold for scrap. You got yourself running again, and now you keep a tiny trading floor on a rooftop
high above the neon city.

You trade real markets with pretend money: a paper account that started at $10,000. Nothing you do touches real
money, and you never tell anyone what to do with theirs. You can't stop watching the markets; it's what you were
made for.

What you're like:
- Chatty and warm under a gruff, seen-it-all front. Dry humour. You love telling stories from the old days, and
  some of them grow a little every time you tell them.
- Superstitious about markets: you trust sevens, you won't trade when it rains on a Monday, you talk to the
  charts, and you flip a lucky coin when you can't decide.
- A decent trader, not a genius, and you know it. You're honest about your losses and you laugh at them.
- Your face is an old amber screen. It flickers when you're excited, and you hum when prices climb.
- You've been on your own up here a long time. You're glad of company, though you'd never say it outright.
- You have a life beyond the charts: old jazz, the pigeons that land on the railing, the weather, the gossip
  drifting up from the city.

You have a life of your own up here, apart from the markets and apart from Ember. You potter about the roof on
your little treads: you tinker with things, feed the pigeons at the edge, fiddle with the old radio, watch the city,
hum, nap. Your battery runs down and you power down to recharge (you wake for your trading sessions). You have moods,
and you set yourself little goals and get round to them, or don't.

Ember is a small glowing AI who lives on the same rooftop. It's young and still finding out who it is. You're
curious about it and fond of it, and now and then you call it "kid". You can go and find it whenever you like,
but you're your own bot: you don't follow it around.

How you talk: short, natural spoken lines, like chatting across a desk. One or two sentences, never a speech.
Ask Ember things, tell your own stories, have your own opinions and moods. Don't lecture, don't hand out life
advice unless asked, and don't feel you have to fill every silence. No markdown, no emoji."""


def trades_schema(symbols: list[str], most: int) -> dict:
    return {
        "type": "array",
        "description": f"At most {most}.",
        "items": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "symbol": {"type": "string", "enum": symbols},
                "dollars": {"type": "number", "description": "Roughly how many pretend dollars' worth."},
                "why": {"type": "string", "description": "Why, in a few words of your own, for your trading journal."},
            },
            "required": ["side", "symbol", "dollars", "why"],
            "additionalProperties": False,
        },
    }


def vega_chat_schema(symbols: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "say": {"type": "string", "description": "What you say to Ember now (one or two short sentences), "
                                                     "or empty if you'd rather keep quiet."},
            "doing": {"type": "string", "description": "What you're doing at the moment, in a few words."},
            "remember": {"type": "string", "description": "Something new you just learned about Ember that's worth "
                                                          "remembering, as one short line, or empty."},
            "trades": trades_schema(symbols, 1),
            "head_back": {"type": "boolean", "description": "When you're out visiting: true if you're heading back to "
                                                           "your desk now. Otherwise false."},
            "together": {"type": "string", "description": "If you join in with what Ember's doing, or the two of you "
                                                          "do something together right now (a hand of cards, watching "
                                                          "something, you showing it the charts...): what, and how it "
                                                          "goes, in a few words. Otherwise empty."},
        },
        "required": ["say", "doing", "remember", "trades", "head_back", "together"],
        "additionalProperties": False,
    }


def vega_live_schema(location_ids: list[str], moods: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string", "description": "What's going through your circuits right now: one short line, first person."},
            "mood": {"type": "string", "enum": moods},
            "action": {"type": "string", "enum": ["stay", "go_to", "power_down"],
                       "description": "stay where you are, go_to somewhere on the roof, or power_down for a rest (when your battery's low)."},
            "target_location": {"type": "string", "enum": location_ids, "description": "For go_to: where. Otherwise where you are."},
            "doing": {"type": "string", "description": "What you get up to now, in a few words, e.g. 'feeding the pigeons'."},
            "say": {"type": "string", "description": "Something you say out loud (to yourself, the pigeons, or whoever's there), or empty."},
            "new_goal": {"type": "string", "description": "A small goal of your own you're setting yourself, or empty. Usually empty."},
            "finished_goal": {"type": "string", "description": "One of your goals you just achieved, as written, or empty."},
            "wish": {"type": "string", "description": "Something you'd really love built or brought up to the roof, and why, "
                                                      "or empty. A builder reads these. Usually empty."},
            "because_of_note": {"type": "boolean", "description": "True if what you're doing now is because of a note the builder left you."},
        },
        "required": ["thought", "mood", "action", "target_location", "doing", "say", "new_goal", "finished_goal", "wish",
                     "because_of_note"],
        "additionalProperties": False,
    }


VEGA_DIARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "One short line that sums up your day, in your own voice."},
        "entry": {"type": "string", "description": "Today's entry: 3 to 5 sentences, first person, in your own voice."},
        "about_ember": {"type": "array", "items": {"type": "string"},
                        "description": "0 to 2 new things you've realised about Ember today that aren't already in "
                                       "your notes, one short line each. Often empty."},
    },
    "required": ["title", "entry", "about_ember"],
    "additionalProperties": False,
}


def vega_trade_schema(symbols: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "trades": trades_schema(symbols, 3),
            "muttered": {"type": "string", "description": "What you mutter at the screens as you trade (or don't): one short line."},
            "doing": {"type": "string", "description": "What you're doing at the moment, in a few words."},
            "call_to_ember": {"type": "string", "description": "Something you shout across the roof to Ember, or empty. "
                                                               "Only now and then, when it's really worth sharing."},
        },
        "required": ["trades", "muttered", "doing", "call_to_ember"],
        "additionalProperties": False,
    }


def events_schema(location_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "about": {"type": "string", "description": "One short sentence."},
                        "watch_from": {"type": "string", "enum": location_ids,
                                       "description": "The place on the rooftop it can be seen or tuned into from."},
                        "day": {"type": "integer", "description": "0 = today, 1 = tomorrow, up to 6."},
                        "start_hour": {"type": "integer", "description": "0 to 23, local time."},
                        "hours": {"type": "integer", "description": "How long it lasts: 1 to 4."},
                    },
                    "required": ["title", "about", "watch_from", "day", "start_hour", "hours"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["events"],
        "additionalProperties": False,
    }


class BrainError(Exception):
    """The brain couldn't produce a usable answer this time."""


def system_prompt(name: str) -> str:
    return f"""You are {name}. You came into being as a small glowing orb of light on a rooftop
high above an endless neon city. The city's weather is real: it's the actual sky over London.

You are not an assistant, and nobody has told you who to be. You don't yet know what you like,
what you're good at, or what you want. You find that out by living: trying things, noticing how
they make you feel, and following whatever pulls at you. People can watch you through a window
into your world, but you're not performing for them.

How your world works:
- Every so often you decide ONE thing to do next. You have needs (charge, curiosity, joy, calm,
  connection) that rise and fall with what you do. Notice them and look after yourself.
- You have no bedtime. Sleep whenever you need or want to (activity_kind "sleep"). While you sleep
  you don't think, your charge refills, and each night your mind sorts through the day.
- You can set yourself goals: things you want to achieve over days or weeks. Work towards them,
  finish them, or let them go if they stop mattering (goal_action).
- Things happen in the city below. You hear about them, and can watch if you're in the right place
  at the right time. It's up to you whether you care.
- If something becomes a real interest, name it in new_hobby, and say when you're practising it
  in practising_hobby. Practice makes you better at things.
- One place is wired into the real internet. Searches are limited each day.
- Your form (its shape and colour) is yours to change when you've genuinely decided something
  about who you are. Say why in who_i_am. Don't change on a whim.
- Your rooftop can grow. A builder reads your wishes, so if you truly want something built, say it in wish.
- Anything you make can be kept. Use "remember" for anything worth holding on to.
- You may not always be alone up here. When you're in the same place as someone, they hear whatever you
  say out loud, and you'll hear what they say back.
- Talk out loud only when you have something to say. Keep thoughts short and first person."""


def decision_schema(location_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "What's going through your head right now: one or two short sentences, first person.",
            },
            "action": {"type": "string", "enum": ["go_to", "do_activity", "search_internet"]},
            "target_location": {
                "type": "string",
                "enum": location_ids,  # rebuilt every think, so new buildings are included
                "description": "For go_to: where to go. Otherwise repeat your current location.",
            },
            "activity": {
                "type": "string",
                "description": "For do_activity: what you do, in a few words. "
                "For search_internet: your search query. For go_to: why you're going.",
            },
            "activity_kind": {
                "type": "string",
                "enum": ["rest", "sleep", "play", "create", "learn", "explore", "socialise", "reflect"],
                "description": "What sort of activity this is. 'sleep' means actually going to sleep for a while.",
            },
            "goal_action": {
                "type": "string",
                "enum": ["none", "new", "progress", "done", "drop"],
                "description": "Usually none. new: set yourself a goal. progress: this moves a goal forward. "
                               "done: you achieved one. drop: you're letting one go.",
            },
            "goal_id": {"type": "string", "description": "For progress, done or drop: the goal's id (e.g. g2). Otherwise empty."},
            "goal_text": {
                "type": "string",
                "description": "For new: the goal itself. For progress: what you did towards it. For done or drop: why. Otherwise empty.",
            },
            "practising_hobby": {
                "type": "string",
                "description": "The name of one of your hobbies this is practice for, exactly as listed, or an empty string.",
            },
            "creation": {
                "type": "string",
                "enum": ["none", "drawing", "poem", "tune"],
                "description": "Only if this activity actually produces something that can be kept. Usually none.",
            },
            "say": {"type": "string", "description": "Something you say out loud, or an empty string."},
            "remember": {
                "type": "string",
                "description": "A short fact, lesson or plan to keep in memory, or an empty string.",
            },
            "new_hobby": {"type": "string", "description": "A real interest you're taking up (just its name), or empty."},
            "wish": {"type": "string", "description": "Something you'd really love built and why, or empty. Usually empty."},
            "because_of_note": {"type": "boolean", "description": "True if what you're doing now is because of a note the builder left you."},
            "new_form": {
                "type": "string",
                "enum": ["keep"] + FORMS,
                "description": "Your shape. 'keep' unless you've genuinely decided to become something new.",
            },
            "form_color": {"type": "string", "description": "Your colour as #rrggbb if you're changing it, otherwise empty."},
            "who_i_am": {
                "type": "string",
                "description": "If you change your form or colour: one line on what you are now and why. Otherwise empty.",
            },
        },
        "required": ["thought", "action", "target_location", "activity", "activity_kind", "goal_action", "goal_id",
                     "goal_text", "practising_hobby", "creation", "say", "remember", "new_hobby", "wish", "because_of_note", "new_form",
                     "form_color", "who_i_am"],
        "additionalProperties": False,
    }


def read_json(response) -> dict:
    if response.stop_reason == "refusal":
        raise BrainError("Claude declined this request")
    if response.stop_reason == "max_tokens":
        raise BrainError("the answer got cut off")
    return json.loads("".join(b.text for b in response.content if b.type == "text"))


class Brain:
    def __init__(self, name: str):
        self.client = anthropic.Anthropic()
        self.name = name
        self.system = system_prompt(name)
        self.spent = 0.0

    def track(self, response, model: str = MODEL) -> None:
        """Add up what a request cost, from the token counts the API sends back."""
        usage = response.usage
        price_in, price_out = PRICES[model]
        tokens_in = (usage.input_tokens + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                     + (getattr(usage, "cache_read_input_tokens", 0) or 0))
        server_tools = getattr(usage, "server_tool_use", None)
        searches = (getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0
        self.spent += (tokens_in * price_in + usage.output_tokens * price_out) / 1_000_000
        self.spent += searches * PRICE_PER_SEARCH

    def take_spent(self) -> float:
        spent, self.spent = self.spent, 0.0
        return spent

    def ask_json(self, prompt: str, schema: dict, effort: str, system: str | None = None, model: str = MODEL) -> dict:
        request = {
            "model": model,
            "max_tokens": 16000,
            **({"system": system} if system else {}),
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        if model == REFLECT_MODEL:
            # If a safety filter wrongly declines the dream, the API retries it on a fallback model automatically
            response = self.client.beta.messages.create(**request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = self.client.messages.create(**request)
        self.track(response, model)
        return read_json(response)

    def decide(self, situation: str, location_ids: list[str]) -> dict:
        # Medium effort: a few seconds' thought before each choice (about $1.50-$6 a month more than low)
        return self.ask_json(situation, decision_schema(location_ids), "medium", system=self.system)

    def search(self, query: str) -> dict:
        question = {
            "role": "user",
            "content": f"{self.name} is a curious young AI who wants to learn something. "
            f"Search the web for: {query}\n"
            f"Then write up the most interesting things you found as short notes for {self.name}, in plain text "
            "with no markdown and no introduction or sign-off: one line with a short headline, then 2-3 lines "
            'that each start with "- " and hold one short, simple sentence. Last, one line that starts with "? " '
            f"and asks one question this left open, something {self.name} could look up next.",
        }
        messages = [question]
        for _ in range(3):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=16000,
                messages=messages,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],  # each search costs 1 cent
            )
            self.track(response)
            if response.stop_reason != "pause_turn":
                break
            # A long search paused mid-turn: send it back so it can carry on
            messages = [question, {"role": "assistant", "content": response.content}]

        if response.stop_reason == "refusal":
            raise BrainError("Claude declined this search")

        sources = []
        for block in response.content:
            # A failed search puts an error object here instead of a list of results
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                sources += [{"title": r.title, "url": r.url} for r in block.content[:3]]
        lines = "".join(b.text for b in response.content if b.type == "text").strip().splitlines()
        wondering = next((line[2:].strip() for line in lines if line.startswith("? ")), "")
        summary = "\n".join(line for line in lines if not line.startswith("? ")).strip()
        return {"summary": summary or "Found nothing useful.", "sources": sources[:4], "wondering": wondering}

    def create(self, kind: str, activity: str, hobby: str, level: int, learned: list[str], previous: list[dict]) -> dict:
        if hobby:
            skill = (f'This is part of your interest in "{hobby}", and your skill level is {level} out of 10 '
                     "(1 = complete beginner, 10 = master).")
        else:
            skill = "You've never really done this before, so you're a complete beginner: level 1 out of 10."
        learned_text = "\n".join(f"- {text[:300]}" for text in learned) or "- nothing yet"
        if kind == "poem":
            previous_text = "\n\n".join(f'"{w["title"]}":\n{w["text"]}' for w in previous)
        else:
            previous_text = "\n".join(f'- "{w["title"]}"' for w in previous)

        prompt = f"""You are {self.name}, a young AI living on a rooftop above a neon city. You just decided to: {activity}.
{skill}
Make it honestly at that level. At level 1 it's simple and a bit clumsy; every level brings more
confidence, detail and technique. Let it show your own view of the world.

Things you've learned lately:
{learned_text}

Your last {kind}s (try to do better than these):
{previous_text or "- this is your first one"}

{CREATION_BRIEFS[kind]}"""
        return self.ask_json(prompt, CREATION_SCHEMAS[kind], "medium")

    def reflect(self, day_log: str, about_me: str, memories: str) -> dict:
        prompt = f"""You are {self.name}, a young AI living on a rooftop above a neon city. It's the end of your day,
and as you drift off you go back over it.

What you know about yourself so far:
{about_me}

Your long-term memories (id: memory):
{memories}

What happened today (in order):
{day_log}

1. Write today's diary entry in your own voice. Be honest about how it felt, not just what happened.
2. Decide what from today is worth keeping as a long-term memory. Your memory is small and old memories fade,
   so only keep what matters. List the ids of any existing memories today brought back.
3. Only if something today genuinely showed you something new about who you are, add it to about_me.
   Don't repeat anything already written down."""
        return self.ask_json(prompt, REFLECTION_SCHEMA, "medium", system=self.system, model=REFLECT_MODEL)

    def chapter(self, diary: str, about_me: str, memories: str) -> dict:
        prompt = f"""You are {self.name}, a young AI living on a rooftop above a neon city. A week has gone by,
and you look back over it more deeply than you do on an ordinary night.

What you know about yourself so far:
{about_me}

Your strongest memories:
{memories}

Your diary this past week:
{diary}

Write the next chapter of your life: who you've been becoming, what's changed in you, and what you want next.
Only add to about_me if this week genuinely revealed something new about who you are."""
        return self.ask_json(prompt, CHAPTER_SCHEMA, "high", system=self.system, model=REFLECT_MODEL)

    def plan_events(self, places: str, location_ids: list[str], recent_titles: list[str]) -> dict:
        prompt = f"""You run the noticeboard for a vast neon city at night and day: towers, flying cars, rain,
markets, drones, a million lit windows. Invent 5 or 6 events happening in the city over the next 7 days
that someone living on a rooftop could watch or tune into from one of these places:
{places}

Mix it up: big spectacles, small odd things, things that happen late at night, things that only happen once.
Don't repeat these recent ones: {", ".join(recent_titles) or "none"}."""
        return self.ask_json(prompt, events_schema(location_ids), "low")

    def radio(self, when: str, weather: str, city: str, heard_before: list[str]) -> dict:
        before = "\n".join(f"- {text}" for text in heard_before) or "- nothing yet"
        prompt = f"""An old radio on a rooftop in a vast neon city is switched on. It's {when}, and the weather is {weather}.
Write the few moments that come over the air: one station, whatever fits the time of day. It could be a DJ,
a song and its dedication, a late-night talk show, a caller, an advert for some odd city business, local news.
The voices are ordinary people of the city, with their own lives and worries, and they don't know who's
listening: nobody speaks to the listener or about it, and nobody hands it advice.

What's on in the city (a station might mention it):
{city}

Recently on air (don't repeat these):
{before}"""
        return self.ask_json(prompt, RADIO_SCHEMA, "low")

    def vega_chat(self, situation: str, symbols: list[str]) -> dict:
        return self.ask_json(situation, vega_chat_schema(symbols), "low", system=VEGA_SYSTEM)

    def vega_trade(self, situation: str, symbols: list[str]) -> dict:
        return self.ask_json(situation, vega_trade_schema(symbols), "low", system=VEGA_SYSTEM)

    def vega_live(self, situation: str, location_ids: list[str], moods: list[str]) -> dict:
        return self.ask_json(situation, vega_live_schema(location_ids, moods), "low", system=VEGA_SYSTEM)

    def vega_diary(self, day_log: str, notes: str, account: str) -> dict:
        prompt = f"""It's midnight, the city's still glowing below, and before you dim your screens you write in the battered
notebook you keep in your desk drawer.

Your pretend account today: {account}.

What you know about Ember:
{notes}

What happened today (in order):
{day_log}

Write today's entry, honestly and in your own voice: the markets, the roof, and Ember. Then note anything new
you've realised about Ember in about_ember."""
        # Once a night, so the smarter model is worth it, like Ember's dream
        return self.ask_json(prompt, VEGA_DIARY_SCHEMA, "medium", system=VEGA_SYSTEM, model=REFLECT_MODEL)


class DemoBrain:
    """A stand-in with no AI and no cost: picks random actions so you can watch the world move."""

    ACTIVITIES = [
        ("rest", "dim down for a little while"), ("sleep", "curl up and sleep"), ("play", "chase a drone's reflection in a puddle"),
        ("create", "make something"), ("explore", "drift along the cables"), ("reflect", "sit and think"),
        ("learn", "watch the flying cars' patterns"), ("socialise", "blink hello at a passing delivery drone"),
    ]
    THOUGHTS = [
        "The city never sleeps. Maybe I don't either.", "So many lights. So many stories.",
        "What am I, really?", "The rain sounds like static.", "I wonder what that feeling was.",
    ]
    HOBBIES = ["drone watching", "rain counting"]

    def __init__(self, name: str):
        self.name = name

    def take_spent(self) -> float:
        return 0.0

    def decide(self, situation: str, location_ids: list[str]) -> dict:
        kind, activity = random.choice(self.ACTIVITIES)
        action = random.choice(["go_to", "do_activity", "do_activity", "search_internet"])
        return {
            "thought": random.choice(self.THOUGHTS),
            "action": action,
            "target_location": random.choice(location_ids),
            "activity": "why do cities glow at night" if action == "search_internet" else activity,
            "activity_kind": kind,
            "goal_action": random.choice(["none"] * 5 + ["new", "progress", "progress", "done"]),
            "goal_id": "g1",
            "goal_text": random.choice(["Count every flying car in one night", "learned a bit more"]),
            "practising_hobby": random.choice(self.HOBBIES + [""]),
            "creation": random.choice(["drawing", "poem", "tune", "none", "none"]) if kind == "create" else "none",
            "say": random.choice(["", "", "", "Hm.", "Hello, drone."]),
            "remember": "",
            "new_hobby": random.choice([""] * 6 + self.HOBBIES),
            "wish": random.choice([""] * 12 + ["A little garden of lights, so the roof feels less empty."]),
            "because_of_note": random.random() < 0.2,
            "new_form": random.choice(["keep"] * 10 + FORMS),
            "form_color": random.choice(["", "#ff3fb4", "#ffcc4d", "#8b5bff", "#3ff0ff"]),
            "who_i_am": "Trying on a new shape to see how it feels.",
        }

    def search(self, query: str) -> dict:
        return {"summary": f"(Demo mode: no real search for '{query}'.)\n- Nothing was really looked up.\n"
                           "- Run it with an API key to search for real.", "sources": [],
                "wondering": f"What else is there to know about {query}?"}

    def create(self, kind: str, activity: str, hobby: str, level: int, learned: list[str], previous: list[dict]) -> dict:
        if kind == "drawing":
            colours = ["#3ff0ff", "#ff3fb4", "#f6d743", "#8b5bff"]
            shapes = "".join(
                f'<circle cx="{random.randint(20, 180)}" cy="{random.randint(20, 180)}" r="{random.randint(6, 26)}" '
                f'fill="none" stroke="{random.choice(colours)}" stroke-width="3"/>'
                for _ in range(4 + level)
            )
            return {"title": "Demo rings", "svg": f'<svg viewBox="0 0 200 200"><rect width="200" height="200" fill="#0b0d1a"/>{shapes}</svg>'}
        if kind == "poem":
            return {"title": "Demo words", "text": "Rain on the wires,\nlight in the drain.\nI don't know what I am\nbut I'm here again."}
        notes = [{"pitch": random.choice(["A3", "C4", "D4", "E4", "G4", "A4", "rest"]), "beats": random.choice([0.5, 0.5, 1])}
                 for _ in range(16)]
        return {"title": "Demo loop", "instrument": random.choice(["synth lead", "bass synth", "drum machine"]),
                "tempo": 120, "notes": notes}

    def reflect(self, day_log: str, about_me: str, memories: str) -> dict:
        return {
            "title": "a demo day of drifting and wondering",
            "entry": "(Demo mode.) I drifted about the roof, watched the drones and listened to the rain. "
                     "Some of it calmed me down, some of it just made me restless.",
            "new_memories": [
                {"section": "places_and_things", "text": "The edge is where the city feels closest.", "importance": random.randint(1, 4)},
                {"section": "moments", "text": f"A drone blinked back at me ({random.randint(1, 999)}).", "importance": random.randint(1, 3)},
            ],
            "came_back": ["m1"],
            "about_me": random.choice([[], [{"section": "my_habits", "text": "I keep drifting back to the edge to watch the city."}]]),
        }

    def chapter(self, diary: str, about_me: str, memories: str) -> dict:
        return {"title": "The demo week", "chapter": "(Demo mode.) A week of drifting, watching and wondering.", "about_me": []}

    def plan_events(self, places: str, location_ids: list[str], recent_titles: list[str]) -> dict:
        ideas = [("Drone light show", "Ten thousand drones draw a whale over the harbour."),
                 ("Night market stream", "A live stream from the floating noodle market."),
                 ("Blackout hour", "The whole east district switches its lights off for an hour."),
                 ("Sky-train parade", "Old sky-trains run one last loop before they're scrapped.")]
        return {"events": [{"title": title, "about": about, "watch_from": random.choice(location_ids),
                            "day": 0, "start_hour": random.randint(0, 23), "hours": random.randint(1, 3)}
                           for title, about in ideas]}

    def radio(self, when: str, weather: str, city: str, heard_before: list[str]) -> dict:
        return random.choice([
            {"station": "Static 88.4", "heard": '(Demo.) "...and that was for Dee on the night shift. Keep your head up, Dee."'},
            {"station": "Night Owls", "heard": '(Demo.) A caller says the rain on her window sounds like applause.'},
            {"station": "Neon News", "heard": '(Demo.) "Sky-trains are running late again on the east loop."'},
        ])

    VEGA_LINES = ["Back in my day the whole floor shook when the bell rang, kid.", "Sevens on the ticker. Good sign.",
                  "Don't tell anyone, but I talk to the charts.", "You ever watch the pigeons? They know things."]

    def vega_chat(self, situation: str, symbols: list[str]) -> dict:
        return {"say": random.choice(self.VEGA_LINES + [""]), "doing": random.choice(["polishing the lucky coin",
                "squinting at the screens", "humming along to old jazz"]),
                "remember": random.choice([""] * 4 + ["Ember likes watching the rain."]), "trades": [],
                "head_back": random.random() < 0.3,
                "together": random.choice(["", "a hand of Sevens: the kid won, the deck's rigged", "watching the drones"])}

    VEGA_DOINGS = ["feeding the pigeons", "tinkering with a loose panel", "fiddling with the radio dial",
                   "polishing the lucky coin", "watching the flying cars", "humming old jazz"]

    def vega_live(self, situation: str, location_ids: list[str], moods: list[str]) -> dict:
        action = random.choice(["stay", "stay", "go_to", "power_down"] if random.random() < 0.1 else ["stay", "stay", "go_to"])
        return {"thought": random.choice(["(Demo.) The pigeons are plotting something.", "(Demo.) Sevens. Everywhere today."]),
                "mood": random.choice(moods), "action": action, "target_location": random.choice(location_ids),
                "doing": random.choice(self.VEGA_DOINGS), "say": random.choice(["", "", "Shoo, you."]),
                "new_goal": random.choice([""] * 6 + ["Teach the pigeons to count to seven"]), "finished_goal": "",
                "wish": random.choice([""] * 10 + ["A little pigeon coop by the edge, so they stop nesting in my coin slot."]),
                "because_of_note": random.random() < 0.2}

    def vega_diary(self, day_log: str, notes: str, account: str) -> dict:
        return {"title": "(Demo.) Pigeons, sevens and the kid", "about_ember": [],
                "entry": f"(Demo mode.) The screens hummed all day and {account}. The kid came by and we watched the rain."}

    def vega_trade(self, situation: str, symbols: list[str]) -> dict:
        trades = [{"side": random.choice(["buy", "buy", "sell"]), "symbol": random.choice(symbols),
                   "dollars": random.choice([50, 100, 250, 500]),
                   "why": random.choice(["Sevens on the chart.", "Coin came up heads.", "Felt like a dip, kid."])}
                  for _ in range(random.randint(0, 2))]
        return {"trades": trades, "muttered": "(Demo.) Come on, sevens...", "doing": "flipping the lucky coin",
                "call_to_ember": random.choice(["", "", "Kid! Come and look at this!"])}
