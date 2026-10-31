"""
run_local.py - run Ember on your own computer.

  python run_local.py              real AI brain (needs ANTHROPIC_API_KEY)
  python run_local.py --demo       no AI and no cost: random actions every few seconds
  python run_local.py --build      builder mode: opens the rooftop editor in your browser (demo brain, no cost)

Then open http://localhost:8000 to watch (or http://localhost:8000/?build to edit). Ctrl+C to stop.
Memories are saved in site/data/, so Ember picks up where it left off.
(Demo and builder mode keep their own memories in site/demo-data/, so they never mix with the real Ember.)

Builder mode can only be used from this computer. It saves to buildings.json, puts your 3D models in
site/models/, and its Publish button pushes them to GitHub so the live Ember gets them.
"""

import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import world
from brain import Brain, DemoBrain

PORT = 8000
BUILD = "--build" in sys.argv
DEMO = "--demo" in sys.argv or BUILD
MODELS_DIR = world.HERE / "site" / "models"
MODEL_EXTENSIONS = {".glb", ".gltf", ".bin", ".obj", ".mtl", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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

    def reply(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def from_builder(self) -> bool:
        """Only the builder page on this computer may change files. Other websites can't send this header
        to localhost without the browser asking us first (and we never say yes), so they can't fake it."""
        origin = self.headers.get("Origin", "")
        local = not origin or re.fullmatch(r"http://(localhost|127\.0\.0\.1):\d+", origin)
        return self.headers.get("X-Ember-Builder") == "1" and bool(local)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/buildings":
            self.reply(200, json.loads((world.HERE / "buildings.json").read_text(encoding="utf-8")))
        else:
            super().do_GET()

    def do_POST(self):
        url = urlsplit(self.path)
        if not self.from_builder():
            return self.reply(403, {"error": "Only the builder page on this computer can do that."})
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD_BYTES:
            return self.reply(413, {"error": "That file is over 50 MB."})
        body = self.rfile.read(length)
        try:
            if url.path == "/api/buildings":
                self.reply(200, save_buildings(json.loads(body)))
            elif url.path == "/api/upload":
                self.reply(200, save_model(parse_qs(url.query).get("name", [""])[0], body))
            elif url.path == "/api/publish":
                self.reply(200, publish())
            else:
                self.reply(404, {"error": "Unknown request."})
        except ValueError as error:
            self.reply(400, {"error": str(error)})


def save_buildings(data: dict) -> dict:
    buildings, lots = data.get("buildings"), data.get("empty_lots", [])
    if not isinstance(buildings, list) or not buildings:
        raise ValueError("There has to be at least one building.")
    ids = set()
    for building in buildings:
        if not re.fullmatch(r"[a-z0-9_]{1,30}", str(building.get("id", ""))):
            raise ValueError(f"Building id {building.get('id')!r} must be lowercase letters, numbers or _.")
        if building["id"] in ids:
            raise ValueError(f"Two buildings are both called {building['id']!r}.")
        ids.add(building["id"])
        x, z = building.get("pos", [None, None])
        if not all(isinstance(v, (int, float)) and -11.5 <= v <= 11.5 for v in (x, z)):
            raise ValueError(f"{building['id']} is off the edge of the roof.")
    path = world.HERE / "buildings.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update(buildings=buildings, empty_lots=lots)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"saved": len(buildings)}


def save_model(name: str, body: bytes) -> dict:
    name = os.path.basename(name).replace(" ", "_")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name) or os.path.splitext(name)[1].lower() not in MODEL_EXTENSIONS:
        raise ValueError(f"{name!r} isn't a model file I can use (.glb, .gltf, .obj, .mtl, or a texture).")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / name).write_bytes(body)
    return {"path": f"models/{name}"}


def publish() -> dict:
    """Send buildings.json and your models to GitHub, so the live Ember gets them on its next thought."""
    def git(*args):
        result = subprocess.run(["git", *args], cwd=world.HERE, capture_output=True, text=True)
        return result.returncode, (result.stdout + result.stderr).strip()

    log = []
    for step in (["pull", "--rebase", "--autostash", "origin", "main"], ["add", "buildings.json"]):
        code, output = git(*step)
        log.append(output)
        if code:
            return {"ok": False, "log": "\n".join(log)}
    if MODELS_DIR.exists():
        git("add", "site/models")
    if git("diff", "--cached", "--quiet")[0] == 0:
        return {"ok": True, "log": "Nothing new to publish."}
    for step in (["commit", "-m", "Update Ember's rooftop (from builder mode)"], ["push", "origin", "main"]):
        code, output = git(*step)
        log.append(output)
        if code:
            return {"ok": False, "log": "\n".join(log)}
    return {"ok": True, "log": "Published! The live site updates in a minute or two."}


def life_loop(brain, every_seconds: float) -> None:
    while True:
        try:
            world.tick(brain, every_seconds)
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
    if BUILD:
        print(f"Builder mode: http://localhost:{PORT}/?build")
        webbrowser.open(f"http://localhost:{PORT}/?build")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Bye!")


if __name__ == "__main__":
    main()
