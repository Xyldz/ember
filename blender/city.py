"""
city.py - the city around Ember's roof: a kit of skyscrapers and a hover car, built entirely from code.

The page builds the city from this kit (site/models/city.glb): for each tower it picks a design that suits the height,
scales it, turns it and tints it in one of the city's colours (site/scenery.json, builder mode's World tab). It looks
for these names, so keep them:
  Tower_*   one design each, with its full height in a "height" custom property
  Windows   walls covered in lit windows (the page swaps in its own window texture, in the tower's colour)
  Trim      neon trim (the page makes it glow in the tower's colour)
  Beacon    red lights that blink (the "antennas" setting decides how many towers keep theirs)
  Car       a flying car, its nose pointing along +X

From a terminal:
  blender -b -P city.py -- --render --export
That saves city.blend and city.png (the designs in a row) next to this file, and ../site/models/city.glb.
"""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rooftop as kit  # noqa: E402  the same building blocks as the roof
from rooftop import M, box, cylinder, rod, sphere, text, picture, material, make_image  # noqa: E402

HERE = kit.HERE
rng = np.random.default_rng(23)
DESIGNS = {}  # name -> (builder, full height)


def design(height):
    def register(fn):
        DESIGNS[fn.__name__] = (fn, height)
        return fn
    return register


# ---------------------------------------------------------------------------
# Walls with windows: texture coordinates in metres (2 m across, 6 m up per repeat, like the page's old towers)
# ---------------------------------------------------------------------------

def rect(w, d):
    return [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]


def poly(r, sides, phase=0.0):
    return [(math.cos(phase + 2 * math.pi * i / sides) * r, math.sin(phase + 2 * math.pi * i / sides) * r) for i in range(sides)]


def walls(name, outline, z0, z1, mat, offset=(0, 0)):
    """Upright walls round an anticlockwise outline, facing out, no roof."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    run = 0.0
    for i, (x0, y0) in enumerate(outline):
        x1, y1 = outline[(i + 1) % len(outline)]
        length = math.hypot(x1 - x0, y1 - y0)
        face = bm.faces.new([bm.verts.new((x + offset[0], y + offset[1], z)) for x, y, z in
                             ((x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1))])
        for loop, (u, v) in zip(face.loops, ((run, z0), (run + length, z0), (run + length, z1), (run, z1))):
            loop[uv].uv = (u / 2, v / 6)
        run += length
    return kit.from_bmesh(name, bm, mat, (0, 0, 0))


def cap(name, outline, z, mat, offset=(0, 0)):
    bm = bmesh.new()
    bm.faces.new([bm.verts.new((x + offset[0], y + offset[1], z)) for x, y in outline])
    return kit.from_bmesh(name, bm, mat, (0, 0, 0))


def block(outline, z0, z1, offset=(0, 0), band=True):
    """A section of tower: windows all round, a dark roof, and a neon band at the top."""
    walls("Windows", outline, z0, z1, M["windows"], offset)
    cap("Roof", outline, z1, M["tower"], offset)
    if band:
        grown = [(x * 1.012 + math.copysign(0.06, x), y * 1.012 + math.copysign(0.06, y)) for x, y in outline]
        walls("Trim", grown, z1 - 0.6, z1 - 0.1, M["trim"], offset)


def mast(x, y, z0, z1):
    rod("Mast", 0.25, (x, y, z0), (x, y, z1), M["tower"])
    sphere("Beacon", 0.7, (x, y, z1 + 0.5), M["beacon"])


def roof_boxes(w, d, z, count=3):
    for _ in range(count):
        bw, bd = rng.uniform(1.5, 3.5), rng.uniform(1.5, 3)
        box("Roof box", (bw, bd, rng.uniform(1, 2.5)), (rng.uniform(-w / 2 + bw, w / 2 - bw), rng.uniform(-d / 2 + bd, d / 2 - bd), z + 0.8),
            M["tower"])


# ---------------------------------------------------------------------------
# The designs. Each stands on its origin, its full height given to @design
# ---------------------------------------------------------------------------

@design(112)
def slab():
    block(rect(14, 10), 0, 100)
    roof_boxes(14, 10, 100)
    mast(3, 1, 100, 111)


@design(110)
def setback():
    block(rect(16, 16), 0, 50)
    block(rect(12, 12), 50, 80)
    block(rect(8, 8), 80, 96)
    cylinder("Spire", 1.6, 13, (0, 0, 102.5), (0, 0, 1), M["tower"], segments=8, tip=0.15)
    sphere("Beacon", 0.6, (0, 0, 109.3), M["beacon"])


@design(97)
def round_tower():
    outline = poly(6, 24)
    block(outline, 0, 95, band=False)
    for z in (20, 40, 60, 80, 94.4):
        walls("Trim", poly(6.12, 24), z, z + 0.45, M["trim"])
    cylinder("Helipad", 5.2, 0.4, (0, 0, 95.4), (0, 0, 1), M["tower"], segments=24)
    for k in range(12):
        a = k * math.pi / 6
        box("Trim", (0.4, 0.4, 0.1), (math.cos(a) * 4.8, math.sin(a) * 4.8, 95.65), M["trim"])
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        sphere("Beacon", 0.4, (math.cos(a) * 5.6, math.sin(a) * 5.6, 96.1), M["beacon"])


@design(104)
def twin():
    block(rect(7, 7), 0, 100, offset=(-6, 0))
    block(rect(7, 7), 0, 82, offset=(6, 0))
    box("Skybridge", (6, 3.2, 3.5), (0, 0, 60), M["glass"])
    box("Trim", (6, 3.3, 0.25), (0, 0, 58.2), M["trim"])
    box("Trim", (6, 3.3, 0.25), (0, 0, 61.8), M["trim"])
    mast(-6, 0, 100, 103)


@design(100)
def wedge():
    block(rect(12, 12), 0, 86)
    bm = bmesh.new()  # a sloping glass top, high at the back
    low, high = 86, 100
    v = [bm.verts.new(p) for p in ((-6, -6, low), (6, -6, low), (6, 6, low), (-6, 6, low), (-6, 6, high), (6, 6, high))]
    for f in ((0, 3, 2, 1), (0, 1, 5, 4), (1, 2, 5), (0, 4, 3), (3, 4, 5, 2)):
        bm.faces.new([v[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    kit.from_bmesh("Wedge top", bm, M["glass"], (0, 0, 0))
    for x in (-6.05, 6.05):
        rod("Trim", 0.18, (x, -6.05, low), (x, 6.05, high), M["trim"])
    rod("Trim", 0.18, (-6.05, 6.05, high), (6.05, 6.05, high), M["trim"])
    billboard((0, -6.12, 60), 9, 5, M["ad1"])


@design(106)
def crown():
    block(rect(12, 12), 0, 82)
    cylinder("Crown", 8.4, 15, (0, 0, 89.5), (0, 0, 1), M["glass"], segments=4, tip=0.4).rotation_euler.z = math.pi / 4
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        rod("Trim", 0.15, (math.cos(a) * 8.45, math.sin(a) * 8.45, 82), (0, 0, 97), M["trim"])
    mast(0, 0, 97, 105)


@design(101)
def hex_tower():
    outline = poly(7, 6, math.pi / 6)
    block(outline, 0, 100, band=False)
    for x, y in outline:
        box("Trim", (0.35, 0.35, 100), (x * 1.01, y * 1.01, 50), M["trim"])
    roof_boxes(8, 8, 100, 2)
    sphere("Beacon", 0.6, (0, 0, 100.6), M["beacon"])


@design(66)
def billboard_block():
    block(rect(22, 12), 0, 60)
    billboard((0, -6.12, 38), 16, 9, M["ad2"])
    billboard((-11.12, 0, 30), 8, 14, M["ad3"], turn=-math.pi / 2)
    box("Sign frame", (12, 0.6, 0.6), (0, 0, 61.2), M["tower"])
    for x in (-5.5, 5.5):
        rod("Sign post", 0.25, (x, 0, 60), (x, 0, 61), M["tower"])
    text("Trim", "NOVA", 4.2, (0, -0.35, 63.4), M["trim"])
    text("Trim", "NOVA", 4.2, (0, 0.35, 63.4), M["trim"], rotation=(math.pi / 2, 0, math.pi))  # reads right from behind too
    for x in (-10.5, 10.5):
        sphere("Beacon", 0.5, (x, 5.5, 60.6), M["beacon"])


def billboard(at, w, h, ad, turn=0.0):
    """A glowing advert in a dark frame, facing out from a wall (the -Y wall unless turned)."""
    x, y, z = at
    frame = box("Billboard frame", (w + 0.6, 0.3, h + 0.6), (x, y, z), M["tower"])
    frame.rotation_euler.z = turn
    out = (-math.sin(turn) * -0.17, math.cos(turn) * -0.17)  # just in front of the frame
    picture("Billboard", w, h, (x + out[0], y + out[1], z), ad, turn=turn)


# ---------------------------------------------------------------------------
# Adverts (made up, no real brands), the window pattern, and the hover car
# ---------------------------------------------------------------------------

def ad_sunset(w=256, h=144):
    yy, xx = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    img = np.stack([0.15 + 0.7 * yy, 0.02 + 0.15 * yy, 0.35 - 0.2 * yy], -1)
    sun = ((xx - 0.5) * 1.8) ** 2 + ((yy - 0.62) * 1.1) ** 2 < 0.12
    stripes = (yy > 0.62) & ((yy * 40).astype(int) % 3 == 0)
    img[sun & ~stripes] = np.stack([np.ones_like(yy), 0.35 + 0.5 * (1 - yy), 0.3 + 0 * yy], -1)[sun & ~stripes]
    img[yy > 0.85] = (0.05, 0.9, 1) * np.array(1.0)  # a cyan horizon
    return img


def ad_glyphs(w=128, h=224, colour=(0.1, 0.95, 1)):
    img = np.zeros((h, w, 3))
    img[:] = (0.02, 0.02, 0.06)
    for gy in range(12, h - 20, 26):  # blocky made-up glyphs in a column
        for gx in (18, 66):
            cells = rng.random((4, 4)) < 0.5
            for (cy, cx) in zip(*np.nonzero(cells)):
                img[gy + cy * 5:gy + cy * 5 + 4, gx + cx * 11:gx + cx * 11 + 9] = colour
    img[:, :4] = img[:, -4:] = colour
    return img


def ad_bars(w=256, h=144):
    img = np.zeros((h, w, 3))
    img[:] = (0.05, 0.0, 0.08)
    for i, x in enumerate(range(10, w - 10, 16)):
        top = int(h * (0.2 + 0.6 * rng.random()))
        img[top:h - 12, x:x + 10] = (1, 0.25, 0.7) if i % 2 else (0.55, 0.36, 1)
    img[h - 8:h - 4, 10:w - 10] = (1, 0.8, 0.3)
    return img


def windows_pattern(w=64, h=128):
    """The same pattern as the page's window texture, so the previews look like the site."""
    img = np.zeros((h, w, 3))
    for y in range(4, h, 8):
        for x in range(4, w, 10):
            if rng.random() < 0.38:
                img[y:y + 4, x:x + 6] = (0.55, 0.36, 1) * np.array(rng.uniform(0.45, 1))
    return img


def car():
    box("Car body", (1.6, 0.72, 0.28), (0, 0, 0), M["tower"], bevel=0.08)
    box("Car nose", (0.5, 0.6, 0.16), (0.9, 0, -0.04), M["tower"], rotation=(0, math.radians(10), 0), bevel=0.05)
    sphere("Canopy", 0.5, (-0.05, 0, 0.12), M["glass"], scale=(1.1, 0.62, 0.42), top_half=True)
    for y in (-0.3, 0.3):
        box("Headlight", (0.04, 0.16, 0.06), (1.13, y, -0.02), M["head"])
        box("Tail light", (0.04, 0.22, 0.06), (-0.81, y, 0.02), M["beacon"])
        cylinder("Thruster", 0.11, 0.3, (-0.55, y * 1.45, -0.08), (1, 0, 0), M["tower"], segments=12)
        cylinder("Trim", 0.08, 0.02, (-0.71, y * 1.45, -0.08), (1, 0, 0), M["trim"], segments=12)
    box("Trim", (1.5, 0.74, 0.03), (0, 0, -0.15), M["trim"])  # underglow


# ---------------------------------------------------------------------------

def make_materials():
    kit.make_materials()
    M["windows"] = material("Windows", (0.03, 0.03, 0.05), image=make_image("Windows", windows_pattern()), glow_image=True,
                            roughness=0.8)
    M["tower"] = material("Tower", (0.03, 0.035, 0.05), metallic=0.5, roughness=0.6)
    M["glass"] = material("Tower glass", (0.04, 0.07, 0.12), metallic=0.8, roughness=0.12, emission=(0.1, 0.25, 0.45), strength=0.4)
    M["trim"] = material("Trim", (0.1, 0.9, 1), emission=(0.1, 0.9, 1), strength=4)
    M["beacon"] = material("Beacon", (1, 0.1, 0.15), emission=(1, 0.1, 0.15), strength=5)
    M["head"] = material("Headlight", (1, 1, 1), emission=(0.9, 0.95, 1), strength=6)
    M["ad1"] = material("Advert sunset", image=make_image("Sunset", ad_sunset()), glow_image=True)
    M["ad2"] = material("Advert bars", image=make_image("Bars", ad_bars()), glow_image=True)
    M["ad3"] = material("Advert glyphs", image=make_image("Glyphs", ad_glyphs()), glow_image=True)


def finish(name, height=None):
    """Join each design's pieces by material, name them for the page, and hang them off one root."""
    group = kit.collection(name)
    groups = {}
    for obj in group.objects:
        if obj.type == "MESH":
            groups.setdefault(obj.active_material.name, []).append(obj)
    for mat_name, objs in groups.items():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs, selected_editable_objects=objs):
                bpy.ops.object.join()
        objs[0].name = {"Windows": "Windows", "Trim": "Trim", "Beacon": "Beacon"}.get(mat_name, mat_name)
    root = bpy.data.objects.new(name, None)
    group.objects.link(root)
    for obj in group.objects:
        if obj is not root:
            obj.parent = root
    if height:
        root["height"] = height
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="save city.png: the designs in a row")
    parser.add_argument("--export", action="store_true", help="save ../site/models/city.glb for the page")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    kit.clear()
    make_materials()
    kit.stage()
    roots = []
    for name, (build, height) in DESIGNS.items():
        kit.piece = f"Tower_{name}"
        build()
        roots.append(finish(kit.piece, height))
    kit.piece = "Car"
    car()
    roots.append(finish("Car"))
    if args.export:
        for obj in kit.scene.objects:
            obj.select_set(obj.users_collection[0].name != "Stage")
        path = kit.SITE / "models" / "city.glb"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
                                  export_lights=False, export_cameras=False, export_yup=True, export_extras=True,
                                  export_draco_mesh_compression_enable=True)
    for i, root in enumerate(roots[:-1]):  # in a row for looking at (the export above had them all on the origin)
        root.location.x = (i - (len(roots) - 2) / 2) * 34
    roots[-1].location, roots[-1].scale = (0, -40, 30), (8, 8, 8)  # the car, much enlarged, out in front
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "city.blend"))
    if args.render:
        print("Rendering on", kit.use_gpu())
        camera = kit.scene.camera
        camera.data.type, camera.data.lens = "PERSP", 30
        camera.location, camera.rotation_euler = (0, -260, 70), (math.radians(84), 0, 0)
        kit.scene.render.resolution_x, kit.scene.render.resolution_y = 1800, 900
        kit.scene.render.filepath = str(HERE / "city.png")
        bpy.ops.render.render(write_still=True)


main()
