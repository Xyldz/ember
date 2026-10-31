# Ember

A small autonomous AI that lives on a rooftop above a neon city. It starts as a blank glowing orb,
with no personality written for it, and works out who it is by living: it has needs (charge,
curiosity, joy, calm, connection), learns what different things do to it, picks up interests,
researches things on the real internet, decides what form to take, and wishes for new things to be
built on its roof. Every night it writes a diary entry and may add a line to its own character sheet.

Its brain is Claude: Haiku 5.5 for everyday decisions, and Sonnet 5.5 for the nightly "dream" where it
writes its diary, sorts its memories and works out who it is. The world is a 3D web page you can open any time.

## What's in here

| File | What it does |
|---|---|
| `brain.py` | Everything that talks to Claude: deciding, searching, making things, the nightly diary |
| `world.py` | The rules: needs, lessons from experience, interests, wishes, memories, one "tick" of life |
| `buildings.json` | The buildings on the roof. **Edit this to build things for Ember** |
| `personality.json` | Ember's character sheet. Blank on purpose; add lines if you want to shape it |
| `config.json` | Name, timezone, where its real weather comes from, daily limits, support link |
| `site/index.html` | The 3D website |
| `run_local.py` | Run Ember on your own computer |
| `tick_once.py` | One moment of life, used by GitHub Actions |
| `.github/workflows/ember.yml` | Runs Ember every 10 minutes on GitHub and publishes the site |

## Run it on your computer

```
pip install -r requirements.txt
python run_local.py --demo
```

Open http://localhost:8000. Demo mode uses no AI and costs nothing; Ember just acts randomly.

For the real thing, get an API key at https://console.anthropic.com, then in PowerShell:

```
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python run_local.py
```


## Put it online (free, runs forever)

GitHub runs Ember every 10 minutes and hosts the website. The repository must be **public**
(that's what makes Actions and Pages free).

1. Create a new public repository on GitHub and upload everything in this folder
   (including the hidden `.github` folder). Make sure the branch is called `main`.
2. **Settings → Secrets and variables → Actions → New repository secret.**
   Name: `ANTHROPIC_API_KEY`, value: your key. It stays secret even in a public repository.
3. **Settings → Pages → Source: GitHub Actions.**
4. **Actions tab → "Ember lives" → Run workflow** to wake Ember up for the first time.

Your site will be at `https://<your-username>.github.io/<repository-name>/`.
Ember's memories are saved to a branch called `data`. Don't edit that branch by hand.

GitHub's 10-minute schedule is "best effort": runs are sometimes late or skipped when GitHub is busy.
If a repository has no activity for 60 days GitHub pauses the schedule; just click **Enable** in the Actions tab.

**Actions → Ember lives → Run workflow** has two checkboxes:
- *Wake Ember up if it's asleep*: wakes it now instead of when it's rested.
- *Dream now*: write today's diary and sort its memories early. Tonight's real dream redoes the day.
- *Start Ember's life over from scratch*: wipes all its memories, diary, interests and lessons. There's no undo.

## Ember's mind

- **Needs**: charge, curiosity, joy, calm and connection drain over time; what Ember does refills (or drains) them.
  The real effect varies each time, and places add their own `boosts`.
- **Lessons**: once something has happened a few times, Ember draws a conclusion from how it actually felt,
  e.g. "Sitting with my thoughts at the rooftop edge settles me (×5)". It reads these every time it thinks.
- **Sleep**: there's no bedtime. Ember sleeps when it decides to (or passes out if its charge hits zero), and wakes
  when it's recharged. Sleeping costs nothing, because it doesn't think while asleep.
- **Diary**: at midnight Ember's mind sorts through the day that ended and writes it up in its own words.
- **Weekly chapter**: once a week, a deeper look back at who it's been becoming. Shown on the Mind tab.
- **Goals**: Ember can set itself up to three goals at a time, work towards them over days, finish them or let them go.
- **Real weather**: the actual weather where `config.json` says (London by default) changes its mood a little,
  and the rain, snow, fog and lightning on the page follow it.
- **What's on**: every few days new events go up around the city. Ember can watch them if it's at the right place at
  the right time; missing one stings a little.
- **Ruts**: if it keeps doing the same thing in the same place, it starts to feel stale and gets restless.
- **Memory**: three small shelves (places & things, facts, moments) of 24 slots each. A memory's strength halves every
  three weeks unless something brings it back, and when a shelf is full a new memory must beat the weakest to get in.
  The nightly dream decides what's worth keeping. See the **Memory** tab.
- **Fascinations**: words that keep turning up in what it reads, weighted towards this week.
- **Character sheet**: `personality.json` is the part you write (blank by default). Each night Ember may add up to two
  lines about itself; it can only ever add, never delete, and near-repeats are rejected.
  The **Mind** tab on the site shows both, plus the lessons.

## Building things for Ember

Ember can wish for new buildings. Wishes show on the website, and online they're also filed as
GitHub issues, so you get notified. To build something, add it to `buildings.json`:

```json
{
  "id": "arcade",
  "name": "Neon arcade",
  "pos": [7, 2.5],
  "about": "A tiny arcade cabinet that plays glitchy retro games.",
  "actions": [],
  "boosts": { "joy": 6 },
  "grants_wish": "arcade",
  "shapes": [
    { "type": "box", "size": [1.4, 2.2, 1], "pos": [0, 1.1, -1.5], "color": "#161a2b" },
    { "type": "box", "size": [1.1, 0.8, 0.05], "pos": [0, 1.6, -0.98], "color": "#ff3fb4", "glow": true }
  ]
}
```

- `pos` is where Ember stands, from about -11 to 11 on each side. Put the building on one of the
  `empty_lots` and remove that lot from the list.
- `actions` unlocks things: `"search"` (internet), `"rest"` (recharge faster).
- `boosts` (optional) is which needs the place helps: `charge`, `curiosity`, `joy`, `calm`, `connection`.
  Ember isn't told this; it finds out by spending time there.
- `about` is written to Ember. Describe the place, not what Ember should do there, so it decides for itself.
- `grants_wish` marks a wish as come true if it contains these words.
- For the look, use `shapes` (boxes, cylinders and spheres; `pos` is relative to where Ember stands, `glow` makes it neon),
  or make a proper 3D model (Blender, etc.), export it as `.glb`, put it in `site/models/`, and set
  `"model": "models/arcade.glb"` (plus `"scale"` if it's the wrong size).

Ember notices new buildings on its next thought, and gets excited about them.

## Costs

With the default limits, Ember costs roughly **$5–6 a month** online: about $4 for thinking every 10 minutes around
the clock on Haiku 5.5 (less, since it doesn't think while it sleeps), and around $1 for the nightly and weekly
Sonnet 5.5 reflections and the city's events. Internet searches are 1 cent each on top (capped at 20 a day).
The weather comes from Open-Meteo, which is free.
The website shows the running cost for the current month.

Set a monthly spend limit in the Anthropic Console (**Settings → Limits**) so it can never surprise you.
