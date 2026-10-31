"""
run_local.py - run Ember on your own computer.

  python run_local.py              real AI brain (needs ANTHROPIC_API_KEY)
  python run_local.py --demo       no AI and no cost: random actions every few seconds
  python run_local.py --no-sleep   real brain, but stays awake through the night

Then open http://localhost:8000 to watch. Ctrl+C to stop.
Memories are saved in site/data/, so Ember picks up where it left off.
(Demo mode keeps its own memories in site/demo-data/, so it never mixes with the real Ember.)
"""

import functools
import os
import sys
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import world
from brain import Brain, DemoBrain

PORT = 8000
DEMO = "--demo" in sys.argv
NEVER_SLEEP = DEMO or "--no-sleep" in sys.argv


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if DEMO and path.startswith("/data/"):
            path = "/demo-data/" + path[len("/data/"):]
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # keep the terminal for Ember's diary, not web requests


def life_loop(brain, every_seconds: float) -> None:
    while True:
        try:
            world.tick(brain, every_seconds, NEVER_SLEEP)
        except Exception:
            traceback.print_exc()
        time.sleep(every_seconds)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    name = world.CONFIG["name"]
    if DEMO:
        world.use_data_dir(world.HERE / "site" / "demo-data")
        brain, every = DemoBrain(name), 8
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        brain, every = Brain(name), world.CONFIG["think_every_minutes_local"] * 60
    else:
        brain, every = None, 60
        print("No API key found, so the brain is offline. Set ANTHROPIC_API_KEY, or try --demo.")

    world.load()
    threading.Thread(target=life_loop, args=(brain, every), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Handler, directory=str(world.HERE / "site")))
    print(f"{name}'s rooftop is live at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Bye!")


if __name__ == "__main__":
    main()
