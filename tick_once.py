"""
tick_once.py - live one moment of Ember's life, then exit.

GitHub Actions runs this every 10 minutes (see .github/workflows/ember.yml).
  python tick_once.py --wake       wake Ember up if it's asleep (the "wake Ember up" checkbox on GitHub)
  python tick_once.py --dream      dream over today now: diary, memories, self (tonight's dream redoes it)
  python tick_once.py --reset      start Ember's life over from scratch first (the "start over" checkbox)
New wishes are also filed as GitHub issues, so you get a notification when Ember wants something built.
"""

import json
import os
import sys
import urllib.request

import world
from brain import Brain

TICK_MINUTES = 10


def file_wish_issues() -> None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return
    for wish in world.state["wishes"]:
        if wish["issue_url"] or wish["granted"]:
            continue
        issue = {
            "title": f"{world.CONFIG['name']} wishes for: {wish['text'][:80]}",
            "body": f"> {wish['text']}\n\nTo grant it, add a building to `buildings.json` with "
                    '`"grants_wish": "<a few words from this wish>"`. '
                    f"{world.CONFIG['name']} will notice it on its next thought.",
        }
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues", data=json.dumps(issue).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                wish["issue_url"] = json.load(response)["html_url"]
        except OSError as error:
            print(f"Couldn't file the wish as an issue: {error}")
            return


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--reset" in sys.argv:
        world.reset()
    world.load()
    brain = Brain(world.CONFIG["name"]) if os.environ.get("ANTHROPIC_API_KEY") else None
    world.tick(brain, TICK_MINUTES * 60, wake_now="--wake" in sys.argv, dream_now="--dream" in sys.argv)
    file_wish_issues()
    world.save()


if __name__ == "__main__":
    main()
