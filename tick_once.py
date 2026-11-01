"""
tick_once.py - live one moment of Ember's life, then exit.

GitHub Actions runs this every 10 minutes (see .github/workflows/ember.yml).
  python tick_once.py --wake       wake Ember up if it's asleep (the "wake Ember up" checkbox on GitHub)
  python tick_once.py --dream      dream over today now: diary, memories, self (tonight's dream redoes it)
  python tick_once.py --reset      start Ember's life over from scratch first (the "start over" checkbox)
New wishes (Ember's and Vega's) are also filed as GitHub issues, so you get a notification when either wants something built.
Notes you leave them (issues titled "Note for Ember..." or "Note for Vega...") wait for them to get round to them;
once one's been read, its answer is posted on the issue and the issue is closed.
"""

import json
import os
import sys
import time
import urllib.request

import friend
import world
from brain import Brain

TICK_MINUTES = 10


def desks() -> dict:
    """The notes waiting for each of them on the bulletin board."""
    return {world.CONFIG["name"]: world.state["desk"], friend.NAME: friend.me()["desk"]}


def github(path: str, data: dict | None = None, method: str = "GET"):
    """One call to GitHub's API for this repository. None when there's no token (e.g. on your computer)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return None
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}", data=json.dumps(data).encode("utf-8") if data else None,
        method=method, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def file_wish_issues() -> None:
    wishers = [(world.CONFIG["name"], world.state["wishes"]), (friend.NAME, friend.me()["wishes"])]
    for who, wish in ((who, wish) for who, wishes in wishers for wish in wishes):
        if wish["issue_url"] or wish["granted"]:
            continue
        issue = {
            "title": f"{who} wishes for: {wish['text'][:80]}",
            "body": f"> {wish['text']}\n\nTo grant it, add a building to `buildings.json` with "
                    '`"grants_wish": "<a few words from this wish>"`. '
                    f"{who} will notice it on its next thought.",
        }
        try:
            filed = github("issues", issue, "POST")
        except OSError as error:
            print(f"Couldn't file the wish as an issue: {error}")
            return
        if not filed:
            return
        wish["issue_url"] = filed["html_url"]


def fetch_notes() -> None:
    """Your notes for Ember or Vega. Only issues you opened count: anyone can open one on a public repo."""
    owner = os.environ.get("GITHUB_REPOSITORY", "/").split("/")[0]
    try:
        issues = github(f"issues?state=open&creator={owner}&per_page=30") or []
    except OSError as error:
        print(f"Couldn't check for notes: {error}")
        return
    known = {note["number"] for desk in desks().values() for note in desk}
    for issue in issues:
        title = issue["title"].strip()
        if "pull_request" in issue or issue["user"]["login"].lower() != owner.lower() or issue["number"] in known:
            continue
        for name, desk in desks().items():
            prefix = f"note for {name.lower()}"
            if title.lower().startswith(prefix):
                text = f"{title[len(prefix):].strip(' :-')}\n{issue['body'] or ''}".strip()[:1000]
                desk.append({"number": issue["number"], "text": text or "(a blank note)", "read": False, "reply": "",
                             "answered": False, "pinned": int(time.time())})


def answer_notes() -> None:
    """Once a note's been read, post what they made of it on the issue and close it."""
    for name, desk in desks().items():
        for note in desk:
            if not note["read"] or note["answered"]:
                continue
            reply = f'**{name}:** "{note["reply"]}"' if note["reply"] else f"{name} read your note."
            try:
                github(f"issues/{note['number']}/comments", {"body": reply}, "POST")
                github(f"issues/{note['number']}", {"state": "closed"}, "PATCH")
            except OSError as error:
                print(f"Couldn't answer the note: {error}")
                return
            note["answered"] = True
        desk[:] = [n for n in desk if not n["answered"]] + [n for n in desk if n["answered"]][-10:]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--reset" in sys.argv:
        world.reset()
    world.load()
    brain = Brain(world.CONFIG["name"]) if os.environ.get("ANTHROPIC_API_KEY") else None
    fetch_notes()
    world.tick(brain, TICK_MINUTES * 60, wake_now="--wake" in sys.argv, dream_now="--dream" in sys.argv)
    file_wish_issues()
    answer_notes()
    world.save()


if __name__ == "__main__":
    main()
