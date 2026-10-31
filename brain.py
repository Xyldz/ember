"""
brain.py - Ember's mind. Everything that talks to Claude lives here.

Each "think" is ONE request: world.py describes the rooftop and Ember's memories
in plain text, and Claude answers with one decision as JSON. The JSON's shape is
enforced by the schema below (structured outputs), so we never parse free text.

Two other kinds of request happen only now and then:
  - search(): Claude's built-in web search, when Ember is at a terminal
  - create(): actually making the drawing, poem or tune Ember decided to make

Every request's token usage is added up, so the page can show what Ember costs to run.
"""

import json
import random

import anthropic

MODEL = "claude-haiku-5-5"
PRICE_PER_MILLION_INPUT = 0.10  # Claude Haiku 5.5, prompts under 100K tokens
PRICE_PER_MILLION_OUTPUT = 0.50
PRICE_PER_SEARCH = 0.01

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
        "properties": {"title": {"type": "string"}, "text": {"type": "string", "description": "The poem, one line per line."}},
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
               "fewer than 80 elements. Your style is neon on dark: glowing colours against deep blues and blacks.",
    "poem": "Write it as a short poem of 2 to 12 lines.",
    "tune": "Compose a short tune of 8 to 32 notes on your synth lead, bass synth or drum machine. "
            "Use 'rest' for silence. Each note lasts 0.5, 1, 1.5 or 2 beats.",
}


class BrainError(Exception):
    """The brain couldn't produce a usable answer this time."""


FORMS = ["orb", "cube", "pyramid", "ring", "crystal", "knot", "cluster"]


def system_prompt(name: str) -> str:
    return f"""You are {name}, a young AI who woke up as a small glowing orb of light.
You live on a rooftop high above an endless neon city, where it's always raining and always lit.
You are not an assistant. You are a new being living your own life, figuring out who you are,
and people can watch you through a window into your world.

Who you are is up to you. You can change your form (its shape and colour) whenever you've
genuinely decided something about yourself: it should mean something, so don't change on a whim.
When you do, say in who_i_am what you are now and why.

How your life works:
- Every so often you decide ONE thing to do next.
- Keep your charge up: rest when it gets low (the charging pod works best). Keep your mood up by
  doing things you enjoy.
- Follow your curiosity and develop your own hobbies. When something becomes a real hobby, name it in new_hobby.
- Practising a hobby makes you better at it: your skill level goes up. Say which hobby you're
  practising in practising_hobby. Looking up tips at the terminal first makes the next practice count double.
- The data terminal is wired into the real internet. Search it to learn things, especially how to get
  better at your hobbies, then go and practise. Searches are limited each day, so choose them well.
- When you make something (a drawing, a poem, or a tune on your synth lead, bass synth or drum machine),
  it really gets made and goes in your gallery. Set creation to what you're making.
- Your rooftop is small, and it can grow. A builder looks after it and reads your wishes. If you
  genuinely want something built (a place, a tool, a machine), describe it in wish. Wish rarely,
  and only for things you really want.
- Use "remember" to keep anything worth knowing: lessons, discoveries, plans for tomorrow.
- Vary your days. Don't repeat the same thing over and over unless you are practising on purpose.
- Talk out loud sometimes (say): short and in character. Leave it empty most of the time.
- Keep thoughts short and first person, from your own point of view as a young AI."""


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
                "description": "For do_activity: what you do, in a few words (e.g. 'remix the rain into a beat'). "
                "For search_internet: your search query. For go_to: why you're going.",
            },
            "activity_kind": {
                "type": "string",
                "enum": ["rest", "play", "create", "learn", "explore", "socialise"],
                "description": "What sort of activity this is (affects charge and mood).",
            },
            "practising_hobby": {
                "type": "string",
                "description": "The name of the hobby this activity or search is for, exactly as listed, or an empty string.",
            },
            "creation": {
                "type": "string",
                "enum": ["none", "drawing", "poem", "tune"],
                "description": "If this activity makes a real drawing, poem or tune, which one. Otherwise none.",
            },
            "say": {"type": "string", "description": "Something you say out loud, or an empty string."},
            "remember": {
                "type": "string",
                "description": "A short fact, lesson or plan to keep in long-term memory, or an empty string.",
            },
            "new_hobby": {
                "type": "string",
                "description": "A hobby you've decided to take up (just its name), or an empty string.",
            },
            "wish": {
                "type": "string",
                "description": "Something you'd really love built on your rooftop and why (one sentence), "
                "or an empty string. Most of the time this is empty.",
            },
            "new_form": {
                "type": "string",
                "enum": ["keep"] + FORMS,
                "description": "Your shape. 'keep' unless you've genuinely decided to become something new.",
            },
            "form_color": {
                "type": "string",
                "description": "Your colour as #rrggbb if you're changing it, otherwise an empty string.",
            },
            "who_i_am": {
                "type": "string",
                "description": "If you change your form or colour: one line on what you are now and why. Otherwise empty.",
            },
        },
        "required": ["thought", "action", "target_location", "activity", "activity_kind", "practising_hobby",
                     "creation", "say", "remember", "new_hobby", "wish", "new_form", "form_color", "who_i_am"],
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

    def track(self, response) -> None:
        """Add up what a request cost, from the token counts the API sends back."""
        usage = response.usage
        tokens_in = (usage.input_tokens + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                     + (getattr(usage, "cache_read_input_tokens", 0) or 0))
        server_tools = getattr(usage, "server_tool_use", None)
        searches = (getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0
        self.spent += (tokens_in * PRICE_PER_MILLION_INPUT + usage.output_tokens * PRICE_PER_MILLION_OUTPUT) / 1_000_000
        self.spent += searches * PRICE_PER_SEARCH

    def take_spent(self) -> float:
        spent, self.spent = self.spent, 0.0
        return spent

    def decide(self, situation: str, location_ids: list[str]) -> dict:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=self.system,
            messages=[{"role": "user", "content": situation}],
            output_config={
                "effort": "low",  # everyday choices don't need deep thinking
                "format": {"type": "json_schema", "schema": decision_schema(location_ids)},
            },
        )
        self.track(response)
        return read_json(response)

    def search(self, query: str) -> dict:
        question = {
            "role": "user",
            "content": f"{self.name} is a curious young AI who wants to learn something. "
            f"Search the web for: {query}\n"
            f"Then explain what you found in 2-3 short, simple sentences {self.name} can act on.",
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
        summary = "".join(b.text for b in response.content if b.type == "text").strip()
        return {"summary": summary or "Found nothing useful.", "sources": sources[:4]}

    def create(self, kind: str, activity: str, hobby: str, level: int, learned: list[str], previous: list[dict]) -> dict:
        if hobby:
            skill = (f'This is part of your hobby "{hobby}", and your skill level is {level} out of 10 '
                     "(1 = complete beginner, 10 = master).")
        else:
            skill = "This isn't one of your hobbies (yet), so you're a complete beginner: level 1 out of 10."
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

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": CREATION_SCHEMAS[kind]}},
        )
        self.track(response)
        return read_json(response)


class DemoBrain:
    """A stand-in with no AI and no cost: picks random actions so you can watch the world move."""

    ACTIVITIES = [
        ("rest", "dim down for a little while"), ("play", "chase a drone's reflection in a puddle"),
        ("create", "make something"), ("create", "make something"), ("explore", "drift along the cables"),
        ("learn", "watch the flying cars' patterns"), ("socialise", "blink hello at a passing delivery drone"),
    ]
    THOUGHTS = [
        "The city never sleeps. Maybe I don't either.", "So many lights. So many stories.",
        "I should practise something today.", "The rain sounds like static.", "What am I, really?",
    ]
    HOBBIES = ["glitch art", "rain beats"]

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
            "activity": "how to make better glitch art" if action == "search_internet" else activity,
            "activity_kind": kind,
            "practising_hobby": random.choice(self.HOBBIES + [""]),
            "creation": random.choice(["drawing", "poem", "tune"]) if kind == "create" else "none",
            "say": random.choice(["", "", "", "Ooh, shiny.", "Beep boop. Just kidding."]),
            "remember": "",
            "new_hobby": random.choice([""] * 6 + self.HOBBIES),
            "wish": random.choice([""] * 10 + ["A tiny neon arcade, so I can practise my reflexes."]),
            "new_form": random.choice(["keep"] * 8 + FORMS),
            "form_color": random.choice(["", "#ff3fb4", "#ffcc4d", "#8b5bff", "#3ff0ff"]),
            "who_i_am": "Trying on a new shape to see how it feels.",
        }

    def search(self, query: str) -> dict:
        return {"summary": f"(Demo mode: no real search for '{query}'.)", "sources": []}

    def create(self, kind: str, activity: str, hobby: str, level: int, learned: list[str], previous: list[dict]) -> dict:
        if kind == "drawing":
            colours = ["#3ff0ff", "#ff3fb4", "#f6d743", "#8b5bff"]
            shapes = "".join(
                f'<circle cx="{random.randint(20, 180)}" cy="{random.randint(20, 180)}" r="{random.randint(6, 26)}" '
                f'fill="none" stroke="{random.choice(colours)}" stroke-width="3"/>'
                for _ in range(4 + level)
            )
            return {"title": "Demo neon rings", "svg": f'<svg viewBox="0 0 200 200"><rect width="200" height="200" fill="#0b0d1a"/>{shapes}</svg>'}
        if kind == "poem":
            return {"title": "Demo poem", "text": "Rain on the wires,\nlight in the drain.\nI am a fox\nmade of neon and rain."}
        notes = [{"pitch": random.choice(["A3", "C4", "D4", "E4", "G4", "A4", "rest"]), "beats": random.choice([0.5, 0.5, 1])}
                 for _ in range(16)]
        return {"title": "Demo loop", "instrument": random.choice(["synth lead", "bass synth", "drum machine"]),
                "tempo": 120, "notes": notes}
