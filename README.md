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
| `friend.py` | Vega, Ember's friend: an old trading bot with a pretend-money trading account |
| `buildings.json` | The buildings on the roof. **Edit this to build things for Ember** |
| `personality.json` | Ember's character sheet. Blank on purpose; add lines if you want to shape it |
| `site/scenery.json` | The look of the world: platform, sky, city, flying cars, neon signs, props |
| `config.json` | Name, timezone, where its real weather comes from, daily limits, support link |
| `site/index.html` | The 3D website |
| `run_local.py` | Run Ember on your own computer, or open builder mode with `--build` |
| `site/builder.js` | Builder mode: the rooftop editor |
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

## Looking around

- **Drag** to turn the camera, **right-drag** (two fingers on a phone) to move around the roof, **scroll** (or pinch)
  to zoom towards whatever's under the pointer. **Double-click** anywhere to fly there; double-click Ember or Vega to follow them.
- The buttons in the corner: **Free** camera, follow **Ember**, follow **Vega**, **⟲** back to the whole roof, and
  **☀ / 🌙**: the real sky, or night all the time. The page remembers your choices.
- **Day and night**: the sky follows the real sun over the place in `config.json` (London): sunrise colours, a hazy blue
  day, golden sunsets, and the neon taking over at night. Cloudy days are greyer. Add `?hour=13` to the address to see
  another time of day. Builder mode always shows the night, which is what `site/scenery.json` describes.

## On your phone

The site works on phones. Add it to your home screen and it opens full-screen like an app, with Ember's icon:
- **iPhone (Safari)**: Share → **Add to Home Screen**.
- **Android (Chrome)**: ⋮ menu → **Add to Home screen** (or **Install app**).

On phones the city is a bit smaller and the animation runs at 30 fps to save battery. Ember's latest news loads
as soon as you open it.

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

## Vega, Ember's friend

Vega is an old trading bot who runs the trading floor on the roof, so Ember has someone to talk to.
It has its own fixed character (written in `brain.py`), and it remembers things about Ember as they get to know each other.

- **Talking**: whenever Ember and Vega are in the same place, Vega hears whatever Ember says out loud and answers
  (or doesn't). Ember hears Vega's replies on its next thought. A couple of times a day Vega may also shout across the roof.
- **Together**: when they're in the same place, Vega may join in with whatever Ember's doing: a hand of cards,
  watching something on in the city, showing it the charts. These shared moments lift Ember more than talking does,
  and Ember learns that over time.
- **Its own life**: every tick, like Ember, Vega thinks for itself: it has moods, wanders the roof on its own business,
  talks to itself and the pigeons, sets itself little goals, and powers down when its battery runs flat (waking for its
  trading sessions). Its own day stays on its side of the panel; Ember can see where it is and how it seems.
- **Notes on its desk**: open a GitHub issue titled `Note for Vega: ...` (or tap "Leave Vega a note" on its side of the
  panel). It goes on Vega's desk; Vega reads it next time it's there and decides for itself what to make of it, and its
  answer is posted on the issue, which then closes. Only issues opened by the repository's owner count.
- **Wishes**: Vega can wish for things to be built too (at most one a day). Like Ember's, they're filed as GitHub issues
  and come true when a building has `"grants_wish"` with words from the wish.
- **Notebook**: at midnight, while Ember dreams, Vega writes up its day: the markets, the roof and Ember
  (on Sonnet, like Ember's dream: about a cent a night).
- **Paper trading**: Vega trades **real prices with pretend money**: a paper account that started with $10,000.
  There's no real money, exchange account or API key anywhere. Prices come free from CoinGecko (crypto) and Yahoo Finance
  (stocks); if they can't be reached, the last prices stay on its screens and nothing gets traded.
  It sits down to trade at 9:00, 13:00, 15:00, 18:00 and 21:00 London time. Stocks only trade while New York's market is open.
- **On the site**: Vega trundles about the roof, its amber face blinking, mouthing what it says. The ticker round the
  trading floor scrolls the real prices and Vega's account (any model part named `LiveTicker` does this).
  The switch at the top of the panel flips between **Ember** and **Vega**, each with their own tabs. Vega's are:
  **Today** (what it said and heard, its trades, where it went), **Journal** (every trade with Vega's reason and how
  it turned out, plus its win rate and best sale), **Portfolio** (its account over time and where the money is),
  **Market** (each market with a chart of the last day), **Notebook**, and **Ember** (what it knows about Ember, and
  their conversation).
- **Its look**: a little CRT-headed bot on treads, modelled in Blender from code (`blender/vega.py`, exported to
  `site/models/vega.glb`). The site keeps its face live (it shows its mood), turns its head to watch Ember and waves while it talks.
- **Cost**: a small Haiku call each tick while it's awake (up to 160 a day), plus replies to Ember and its trading
  sessions, and its nightly notebook: roughly $2-4 a month.
- Vega lives at whichever building has the `"friend"` action ("Vega's desk" in builder mode). Change the watchlist,
  the starting money or the session times at the top of `friend.py`.

## Building things for Ember

Ember can wish for new buildings. Wishes show on the website, and online they're also filed as
GitHub issues, so you get notified.

### Builder mode (the easy way)

In this folder, run:

```
python run_local.py --build
```

Your browser opens Ember's rooftop with a builder panel. It only works on your own computer.

- **Click anything** to select it. **W** = move, **E** = rotate, **R** = resize (or type exact numbers in the panel).
  **Del** deletes it, **Esc** deselects.
- **Buildings tab**: the places Ember uses. **+ New building** or **Build here** on an empty lot adds one;
  **Duplicate** and **✕ / Delete** do what they say.
- **World tab**: everything else, saved in `site/scenery.json`:
  - **Platform**: roof size, colour, grid, the four neon edges, and the skyscraper underneath.
  - **Sky & light**: sky and fog colours, fog, light, neon glow and brightness.
  - **City**: how many towers, how near and far, how tall, window colours, antennas, or a **New random city**.
  - **Flying cars**: how many.
  - **Neon signs**: add, retext, recolour, move, turn and resize them.
  - **Props**: decorations you can put anywhere, even floating, with the same looks as buildings (shapes or your models).
- In the panel: its name, what Ember reads about it, what it unlocks, which needs it helps, and which wish it grants.
- **Look**: a built-in piece (data terminal, charging pod, railing, old radio), simple shapes (editable boxes, cylinders and spheres, neon or not), or **your own 3D model**:
  - From **Roblox Studio**: select your build, **File → Export Selection**, then in the builder pick the `.obj`
    **and** the `.mtl` (and any textures) together.
  - From **Blender**: **File → Export → glTF 2.0**, Format **glTF Binary (.glb)** (one file, textures packed in).
    Tick **Selected Objects** to export just your build. Blender's **Compression** option works too.
    Anything you **animate** in Blender plays on a loop on the roof. Give a material an **Emission** colour
    and it glows like neon. 1 Blender unit is about 1 unit on the roof (24 wide by default).
  - Models are auto-fitted to a lot; untick that to use the model's own size.
- **Save** (or Ctrl+S) writes `buildings.json` and `site/scenery.json`, and keeps your models in `site/models/`.
- **Publish to GitHub** sends them to the live Ember, which notices the new building on its next thought.

### By hand

Everything builder mode does is stored in `buildings.json`, so you can also edit it directly:

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
- `actions` unlocks things: `"search"` (internet), `"rest"` (recharge faster), `"radio"` (Ember hears what's on the
  city's radio whenever it does something there; up to 30 broadcasts a day, each a tiny Haiku call),
  `"friend"` (Vega works here).
- `boosts` (optional) is which needs the place helps: `charge`, `curiosity`, `joy`, `calm`, `connection`.
  Ember isn't told this; it finds out by spending time there.
- `about` is written to Ember. Describe the place, not what Ember should do there, so it decides for itself.
- `grants_wish` marks a wish as come true if it contains these words.
- For the look, use `shapes` (boxes, cylinders and spheres; `pos` is relative to where Ember stands, `glow` makes it neon),
  or a model in `site/models/`: `"model": "models/arcade.glb"`, or `"model": "models/arcade.obj"` with `"mtl": "models/arcade.mtl"`.
- `rotation` (degrees) and `scale` turn and resize the whole building. `"autofit": false` uses a model's own size.

Ember notices new buildings on its next thought, and gets excited about them.

## Costs

With the default limits, Ember costs roughly **$5–6 a month** online: about $4 for thinking every 10 minutes around
the clock on Haiku 5.5 (less, since it doesn't think while it sleeps), and around $1 for the nightly and weekly
Sonnet 5.5 reflections and the city's events. Internet searches are 1 cent each on top (capped at 20 a day).
Vega and the radio add only cents.
The weather comes from Open-Meteo, which is free.
The website shows the running cost for the current month.

Set a monthly spend limit in the Anthropic Console (**Settings → Limits**) so it can never surprise you.
