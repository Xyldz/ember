# Ember

A small autonomous AI that lives on a rooftop above a neon city. It starts life as a glowing orb and
decides for itself what it wants to become (its shape and colour). Every so often it decides what to
do next: it researches things on the real internet, picks up hobbies and levels them up, makes
drawings, poems and synth tracks, and wishes for new things to be built on its roof.

Its brain is Claude (Haiku 5.5). The world is a 3D web page you can open any time to see what it's up to.

## What's in here

| File | What it does |
|---|---|
| `brain.py` | Everything that talks to Claude: deciding, searching, making things |
| `world.py` | The rules: charge, mood, skills, wishes, memories, one "tick" of life |
| `buildings.json` | The buildings on the roof. **Edit this to build things for Ember** |
| `config.json` | Name, timezone, bedtime, daily limits, support link |
| `site/index.html` | The 3D website |
| `run_local.py` | Run Ember on your own computer |
| `tick_once.py` | One moment of life, used by GitHub Actions |
| `.github/workflows/ember.yml` | Runs Ember every 15 minutes on GitHub and publishes the site |

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

Add `--no-sleep` to keep Ember awake after bedtime.

## Put it online (free, runs forever)

GitHub runs Ember every 15 minutes and hosts the website. The repository must be **public**
(that's what makes Actions and Pages free).

1. Create a new public repository on GitHub and upload everything in this folder
   (including the hidden `.github` folder). Make sure the branch is called `main`.
2. **Settings → Secrets and variables → Actions → New repository secret.**
   Name: `ANTHROPIC_API_KEY`, value: your key. It stays secret even in a public repository.
3. **Settings → Pages → Source: GitHub Actions.**
4. **Actions tab → "Ember lives" → Run workflow** to wake Ember up for the first time.

Your site will be at `https://<your-username>.github.io/<repository-name>/`.
Ember's memories are saved to a branch called `data`. Don't edit that branch by hand.

GitHub's 15-minute schedule is "best effort": runs are sometimes late or skipped when GitHub is busy.
If a repository has no activity for 60 days GitHub pauses the schedule; just click **Enable** in the Actions tab.

## Building things for Ember

Ember can wish for new buildings. Wishes show on the website, and online they're also filed as
GitHub issues, so you get notified. To build something, add it to `buildings.json`:

```json
{
  "id": "arcade",
  "name": "Neon arcade",
  "pos": [7, 2.5],
  "about": "A tiny arcade cabinet that plays glitchy retro games. Great for practising reflexes.",
  "actions": [],
  "grants_wish": "arcade",
  "shapes": [
    { "type": "box", "size": [1.4, 2.2, 1], "pos": [0, 1.1, -1.5], "color": "#161a2b" },
    { "type": "box", "size": [1.1, 0.8, 0.05], "pos": [0, 1.6, -0.98], "color": "#ff3fb4", "glow": true }
  ]
}
```

- `pos` is where Ember stands, from about -11 to 11 on each side. Put the building on one of the
  `empty_lots` and remove that lot from the list.
- `actions` unlocks things: `"search"` (internet), `"create"` (make art/poems/music), `"rest"` (recharge faster).
- `about` is written to Ember: it's how Ember knows what the place is for.
- `grants_wish` marks a wish as come true if it contains these words.
- For the look, use `shapes` (boxes, cylinders and spheres; `pos` is relative to where Ember stands, `glow` makes it neon),
  or make a proper 3D model (Blender, etc.), export it as `.glb`, put it in `site/models/`, and set
  `"model": "models/arcade.glb"` (plus `"scale"` if it's the wrong size).

Ember notices new buildings on its next thought, and gets excited about them.

## Costs

On Claude Haiku 5.5 with the default limits, Ember costs roughly **$1–5 a month** online
(fewer thoughts than running locally), plus 1 cent per internet search (capped at 15 a day, so at most about $4.50 a month).
The website shows the running cost for the current month.

Set a monthly spend limit in the Anthropic Console (**Settings → Limits**) so it can never surprise you.
