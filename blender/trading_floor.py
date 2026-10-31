"""
trading_floor.py - a cyberpunk trading floor for Ember's rooftop, built entirely from code.

In Blender: Scripting tab -> Open -> this file -> Run Script. It clears the scene, builds the trading floor and
switches the 3D view to the rendered camera view with the neon glowing (Z -> Solid to go back, Numpad 0 for the
camera). Everything it makes is an ordinary Blender object (grouped into collections), so you can move, recolour
and delete things by hand. Blender always opens saved files in Solid view: press Z -> Rendered to light it up.

From a terminal it can also render previews and export the model for Ember's builder mode:
  blender -b -P trading_floor.py -- --render --export
That saves trading_floor.blend and two preview pictures next to this file, and ../site/models/trading_floor.glb.
"""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

SCRIPT = Path(globals().get("__file__", ""))
HERE = SCRIPT.resolve().parent if SCRIPT.is_file() else Path.cwd()  # where the .blend and previews go
W, D, H = 6.0, 4.5, 4.4  # the main block: width (x), depth (y), height (z)
SLAB = 0.12              # the pavement it stands on
FRONT = -D / 2           # the front faces -Y, which Ember's builder turns towards the viewer
G = 2.1                  # the trading floor at street level
UP = SLAB + G            # where the upper floor starts
TOP = SLAB + H           # the roof
GLASS = FRONT + 0.6      # the street-level glass sits back under the upper floor
NEON = 3.0               # how bright the neon is (Ember's 3D view uses this as its glow)
NEON_COLOURS = {"pink": (1, 0.1, 0.55), "cyan": (0.1, 0.9, 1), "green": (0.15, 1, 0.35),
                "amber": (1, 0.6, 0.08), "red": (1, 0.08, 0.12), "blue": (0.2, 0.35, 1)}
RISING, FALLING = (0.1, 1, 0.45), (1, 0.15, 0.3)  # chart colours
rng = np.random.default_rng(7)  # the same "random" panels and charts every time
scene = bpy.context.scene
M = {}  # materials by short name


# ---------------------------------------------------------------------------
# Pictures, painted with numpy (so they travel inside the .blend and the .glb)
# ---------------------------------------------------------------------------

def make_image(name, rgb):
    """A picture from a (height, width, 3) array of 0-1 colours, top row first."""
    h, w, _ = rgb.shape
    rgba = np.concatenate([np.clip(rgb, 0, 1), np.ones((h, w, 1))], axis=2)
    image = bpy.data.images.new(name, w, h)
    image.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
    image.pack()
    return image


def disc(img, cx, cy, r, colour):
    y, x = np.ogrid[:img.shape[0], :img.shape[1]]
    img[(x - cx) ** 2 + (y - cy) ** 2 <= r * r] = colour


def panels(size=256, grey=0.15):
    """Dark cladding panels, twice as wide as they're tall."""
    img = np.full((size, size, 3), grey * 0.45)
    for r in range(size // 64):
        for c in range(size // 128):
            tone = grey * rng.uniform(0.85, 1.15) * np.array((0.95, 1, 1.1))
            img[r * 64 + 2:(r + 1) * 64 - 2, c * 128 + 2:(c + 1) * 128 - 2] = tone
    return img * (1 + rng.normal(0, 0.03, (size, size, 1)))


def tiles(size=256, cell=64, grey=0.2):
    img = np.full((size, size, 3), grey * 0.45)
    for r in range(size // cell):
        for c in range(size // cell):
            img[r * cell + 2:(r + 1) * cell - 2, c * cell + 2:(c + 1) * cell - 2] = grey * rng.uniform(0.85, 1.15)
    return img * (1 + rng.normal(0, 0.04, (size, size, 1)))


def concrete(size=256, grey=0.16):
    img = np.full((size, size, 3), grey) * (1 + rng.normal(0, 0.06, (size, size, 1)))
    for _ in range(6):  # puddle stains
        disc(img, *rng.uniform(0, size, 2), rng.uniform(10, 40), grey * 0.7)
    return img


def walk(r, n, drift=0.25):
    """A made-up price that wanders about, mostly upwards."""
    return np.cumsum(r.normal(drift, 1.0, n))


def screen(h, w):
    img = np.empty((h, w, 3))
    img[:] = (0.01, 0.015, 0.03)
    return img


def candles(seed, w=512, h=224, n=40):
    """A candlestick chart: green candles closed higher than they opened, red ones lower."""
    r = np.random.default_rng(seed)
    img = screen(h, w)
    img[20::28, :] = (0.04, 0.07, 0.11)  # grid
    img[:, ::32] = (0.04, 0.07, 0.11)
    img[:16] = (0.03, 0.06, 0.12)  # title bar
    for i in range(w // 84):
        img[6:10, 10 + i * 84:10 + i * 84 + r.integers(24, 60)] = (0.6, 0.8, 1)  # its "writing"
    price = walk(r, n + 1)
    opens, closes = price[:-1], price[1:]
    highs = np.maximum(opens, closes) + r.uniform(0.1, 0.9, n)
    lows = np.minimum(opens, closes) - r.uniform(0.1, 0.9, n)
    lo, hi = lows.min(), highs.max()
    row = lambda v: int(h - 8 - (v - lo) / (hi - lo) * (h - 32))
    step = (w - 20) / n
    body = max(int(step * 0.6), 2)
    for i in range(n):
        x = int(10 + i * step)
        colour = RISING if closes[i] >= opens[i] else FALLING
        img[row(highs[i]):row(lows[i]) + 1, x + body // 2 - 1:x + body // 2 + 1] = colour  # the wick
        top, bottom = sorted((row(opens[i]), row(closes[i])))
        img[top:max(bottom, top + 2), x:x + body] = colour
    average = np.convolve(np.pad(price, (4, 0), mode="edge"), np.ones(5) / 5, mode="valid")
    for x in range(10, w - 10):  # a moving average line through it
        y = row(np.interp((x - 10) / step, np.arange(n + 1), average))
        img[y - 1:y + 1, x] = (0.2, 0.85, 1)
    return img


def line_chart(seed, w=128, h=80):
    """A small price line with the area under it shaded."""
    r = np.random.default_rng(seed)
    img = screen(h, w)
    img[::16, :] = (0.04, 0.07, 0.11)
    price = walk(r, w, 0.1)
    rows = (h - 6 - (price - price.min()) / (price.max() - price.min()) * (h - 18)).astype(int)
    colour = np.array(RISING if price[-1] >= price[0] else FALLING)
    for x, y in enumerate(rows):
        img[y + 1:h - 4, x] = colour * 0.18
        img[y - 1:y + 1, x] = colour
    img[3:7, 4:4 + r.integers(20, 50)] = (0.6, 0.8, 1)
    return img


def order_book(seed, w=128, h=80):
    """Rows of offers to sell (red, above) and to buy (green, below)."""
    r = np.random.default_rng(seed)
    img = screen(h, w)
    for i in range(12):
        y = 4 + i * 6 + (4 if i >= 6 else 0)
        colour = np.array(FALLING if i < 6 else RISING)
        depth = int(r.uniform(0.15, 0.95) * (w - 40))
        img[y:y + 4, w - depth:w] = colour * 0.35
        img[y + 1:y + 3, 6:6 + r.integers(14, 30)] = colour
    return img


def market_map(seed, w=128, h=80, rows=5, cols=8):
    """The whole market at a glance: one square per company, greener the more it's up, redder the more it's down."""
    r = np.random.default_rng(seed)
    img = np.full((h, w, 3), 0.01)
    ch, cw = h // rows, w // cols
    for i in range(rows):
        for j in range(cols):
            move = r.normal(0.2, 1)
            colour = np.array(RISING if move >= 0 else FALLING) * min(0.25 + abs(move) * 0.45, 1)
            img[i * ch + 1:(i + 1) * ch - 1, j * cw + 1:(j + 1) * cw - 1] = colour
            img[i * ch + ch // 2 - 1:i * ch + ch // 2 + 1, j * cw + cw // 4:j * cw + 3 * cw // 4] = 0.9  # its name
    return img


def offices(w=256, h=64):
    """Office windows at night: most lit cool or warm, some with the blinds down, the odd one dark."""
    img = np.zeros((h, w, 3))
    shade = np.linspace(1, 0.6, h)[:, None, None]
    for x0 in range(0, w, 32):
        colour = np.array((0.35, 0.5, 0.75) if rng.random() < 0.7 else (0.8, 0.55, 0.3))
        if rng.random() < 0.15:
            colour *= 0.08  # nobody in
        img[:, x0:x0 + 32] = colour * shade
        if rng.random() < 0.5:
            down = int(h * rng.uniform(0.2, 0.9))
            img[:down, x0:x0 + 32] *= 0.3
            img[2:down:4, x0:x0 + 32] *= 0.5  # the slats
        img[h - 14:h - 6, x0 + 6:x0 + 6 + rng.integers(8, 20)] = 0.03  # the back of someone's screen
    img[:, ::32] = 0.02  # window frames
    img[:2] = img[-2:] = 0.02
    return img


# ---------------------------------------------------------------------------
# Materials (plain Principled BSDF, so they export to glTF as they look here)
# ---------------------------------------------------------------------------

def material(name, colour=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.6, emission=None, strength=0.0,
             image=None, glowing_image=False):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if image:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.location = (-400, 200)
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        if glowing_image:
            links.new(texture.outputs["Color"], bsdf.inputs["Emission Color"])
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    mat.diffuse_color = (*(emission or colour), 1)  # its colour in the solid viewport
    return mat


def glass():
    mat = material("Glass", (0.05, 0.09, 0.12), roughness=0.02)
    next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Alpha"].default_value = 0.15
    mat.surface_render_method = "BLENDED"  # see-through in Eevee and in Ember's 3D view too
    return mat


def glowing(name, picture, strength=1.2):
    return material(name, image=make_image(name, picture), glowing_image=True, strength=strength)


def make_materials():
    M["cladding"] = material("Cladding", image=make_image("Panels", panels()), metallic=0.3, roughness=0.45)
    M["pavement"] = material("Pavement", image=make_image("Tiles", tiles()), roughness=0.75)
    M["roof"] = material("Roof", image=make_image("Concrete", concrete()), roughness=0.9)
    M["big screen"] = glowing("Big screen", candles(3), 1.5)
    M["chart wall"] = glowing("Chart wall", candles(5, 768, 192, 60))
    M["market map"] = glowing("Market map", market_map(11, 192, 288, 9, 5))
    for i, picture in enumerate((line_chart(1), order_book(2), market_map(4), line_chart(6))):
        M[f"screen{i}"] = glowing(f"Monitor {i + 1}", picture)
    M["offices"] = glowing("Office windows", offices(), 0.6)
    M["glass"] = glass()
    M["floor"] = material("Polished floor", (0.02, 0.025, 0.035), roughness=0.12)
    M["desk"] = material("Desk", (0.1, 0.11, 0.13), roughness=0.35)
    M["chair"] = material("Chairs", (0.03, 0.03, 0.035), roughness=0.6)
    M["concrete"] = material("Concrete", (0.32, 0.31, 0.3), roughness=0.85)
    M["dark"] = material("Dark metal", (0.035, 0.038, 0.05), metallic=0.6, roughness=0.45)
    M["steel"] = material("Steel", (0.3, 0.32, 0.36), metallic=0.8, roughness=0.35)
    M["panel"] = material("Sign backing", (0.02, 0.02, 0.03), roughness=0.4)
    M["live ticker"] = material("Live ticker", (0.02, 0.02, 0.03), roughness=0.4)  # Ember's site paints the prices on
    M["white"] = material("White metal", (0.75, 0.77, 0.8), metallic=0.3, roughness=0.35)
    M["solar"] = material("Solar panels", (0.02, 0.04, 0.14), metallic=0.4, roughness=0.15)
    M["leaves"] = material("Leaves", (0.05, 0.35, 0.08), roughness=0.7)
    for name, colour in NEON_COLOURS.items():
        M[name] = material(f"Neon {name}", tuple(c * 0.5 for c in colour), emission=colour, strength=NEON)
    M["warm"] = material("Warm light", (1, 0.72, 0.4), emission=(1, 0.72, 0.4), strength=NEON)
    M["strip"] = material("Light strip", (0.8, 0.9, 1), emission=(0.8, 0.9, 1), strength=NEON * 0.7)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def collection(name):
    found = bpy.data.collections.get(name)
    if not found:
        found = bpy.data.collections.new(name)
        scene.collection.children.link(found)
    return found


def add(name, mesh, mat, location, rotation=(0, 0, 0), group="Building"):
    if mat:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler = location, rotation
    collection(group).objects.link(obj)
    return obj


def box(name, size, location, mat, rotation=(0, 0, 0), uv=(1, 1), group="Building"):
    """A box, with UVs laid out by position so panels and tiles line up from one box to the next."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]
    bm.normal_update()
    layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        axis = max(range(3), key=lambda i: abs(face.normal[i]))
        a, b = [(1, 2), (0, 2), (0, 1)][axis]
        for loop in face.loops:
            p = [loop.vert.co[i] + location[i] for i in range(3)]
            loop[layer].uv = (p[a] / uv[0], p[b] / uv[1])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add(name, mesh, mat, location, rotation, group)


def cylinder(name, radius, depth, location, mat, rotation=(0, 0, 0), top=None, segments=16, group="Building"):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius if top is None else top, depth=depth)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for face in mesh.polygons:
        face.use_smooth = abs(face.normal.z) < 0.5  # round sides, flat caps
    return add(name, mesh, mat, location, rotation, group)


def sphere(name, radius, location, mat, scale=(1, 1, 1), group="Props"):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=radius)
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * scale[0], v.co.y * scale[1], v.co.z * scale[2]
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for face in mesh.polygons:
        face.use_smooth = True
    return add(name, mesh, mat, location, group=group)


def picture(name, width, height, location, mat, rotation=(0, 0, 0), group="Front"):
    """A flat picture facing -Y (turn it with rotation)."""
    mesh = bpy.data.meshes.new(name)
    w, h = width / 2, height / 2
    mesh.from_pydata([(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = uv
    return add(name, mesh, mat, location, rotation, group)


def as_mesh(obj, mat):
    """Turn a text or curve object into an ordinary mesh (which is what exports to Ember)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    mesh.materials.clear()
    mesh.materials.append(mat)
    name, location, rotation, groups, data = obj.name, obj.location.copy(), obj.rotation_euler.copy(), obj.users_collection, obj.data
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(data)
    new = bpy.data.objects.new(name, mesh)
    new.location, new.rotation_euler = location, rotation
    for group in groups:
        group.objects.link(new)
    return new


def text(name, body, size, location, mat, font=None, rotation=(math.pi / 2, 0, 0), line=1.0, group="Signs"):
    """Neon letters. Standing up and facing -Y by default."""
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.space_line = body, size, line
    curve.align_x, curve.align_y = "CENTER", "CENTER"
    curve.extrude, curve.bevel_depth, curve.resolution_u = 0.012, 0.004, 3
    if font:
        curve.font = font
    obj = bpy.data.objects.new(name, curve)
    obj.location, obj.rotation_euler = location, rotation
    collection(group).objects.link(obj)
    return as_mesh(obj, mat)


def tube(name, points, radius, mat, cyclic=False, group="Signs"):
    """A neon tube or a cable through a list of points."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions, curve.bevel_depth, curve.bevel_resolution, curve.use_fill_caps = "3D", radius, 2, True
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (*co, 1)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    collection(group).objects.link(obj)
    return as_mesh(obj, mat)


def frame(name, x0, x1, z0, z1, y, mat):
    """A neon tube around a sign."""
    return tube(name, [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], 0.014, mat, cyclic=True)


def cable(name, a, b, sag, mat=None):
    points = []
    for t in np.linspace(0, 1, 12):
        p = [a[i] + (b[i] - a[i]) * t for i in range(3)]
        p[2] -= sag * 4 * t * (1 - t)
        points.append(p)
    return tube(name, points, 0.008, mat or M["dark"], group="Props")


def font(path):
    try:
        return bpy.data.fonts.load(path, check_existing=True)
    except (RuntimeError, OSError):
        return None


# ---------------------------------------------------------------------------
# The trading floor
# ---------------------------------------------------------------------------

def desk(x, y, k):
    """A trader's desk: three screens angled in around one chair."""
    box("Desk", (1.3, 0.62, 0.05), (x, y, SLAB + 0.74), M["desk"], group="Inside")
    for dx in (-0.6, 0.6):
        box("Desk side", (0.05, 0.56, 0.72), (x + dx, y, SLAB + 0.36), M["dark"], group="Inside")
    for i, (dx, turn) in enumerate(((-0.43, 0.35), (0, 0), (0.43, -0.35))):
        cx, cy = x + dx, y + 0.17 - (0.06 if turn else 0)
        box("Screen stand", (0.04, 0.04, 0.2), (cx, cy + 0.03, SLAB + 0.86), M["dark"], group="Inside")
        box("Monitor", (0.42, 0.03, 0.27), (cx, cy, SLAB + 1.08), M["dark"], rotation=(0, 0, turn), group="Inside")
        picture("Screen", 0.39, 0.24, (cx + 0.017 * math.sin(turn), cy - 0.017 * math.cos(turn), SLAB + 1.08),
                M[f"screen{(k + i) % 4}"], rotation=(0, 0, turn), group="Inside")
    cylinder("Chair seat", 0.2, 0.06, (x, y - 0.6, SLAB + 0.48), M["chair"], group="Inside")
    cylinder("Chair post", 0.03, 0.42, (x, y - 0.6, SLAB + 0.24), M["dark"], segments=8, group="Inside")
    box("Chair back", (0.36, 0.05, 0.42), (x, y - 0.78, SLAB + 0.78), M["chair"], rotation=(-0.12, 0, 0), group="Inside")


def dish(name, x, y, radius, aim, floor):
    """A satellite dish on a post, with the arm that holds its receiver."""
    cylinder(f"{name} post", 0.04, 0.5, (x, y, floor + 0.25), M["dark"], segments=8, group="Roof")
    centre = Vector((x, y, floor + 0.55))
    cylinder(name, 0.05, radius * 0.3, centre, M["white"], rotation=aim, top=radius, segments=24, group="Roof")
    axis = Euler(aim).to_matrix() @ Vector((0, 0, 1))
    cylinder(f"{name} arm", 0.012, radius * 0.9, centre + axis * radius * 0.45, M["steel"], rotation=aim, segments=6, group="Roof")
    sphere(f"{name} receiver", 0.05, centre + axis * radius * 0.9, M["dark"], group="Roof")


def build():
    latin = font(r"C:\Windows\Fonts\bahnschrift.ttf")
    cjk = font(r"C:\Windows\Fonts\YuGothB.ttc") or font(r"C:\Windows\Fonts\msgothic.ttc")

    # The block: offices and a big screen upstairs, standing over a glass-fronted trading floor
    box("Pavement", (7.8, 5.9, SLAB), (0.45, -0.25, SLAB / 2), M["pavement"], uv=(1.2, 1.2))
    box("Upper floor", (W, D, H - G), (0, 0, UP + (H - G) / 2), M["cladding"], uv=(1.5, 1.5))
    box("Cornice", (W + 0.12, D + 0.12, 0.14), (0, 0, TOP - 0.07), M["concrete"])
    inside = D / 2 - GLASS  # how deep the trading floor is
    box("Back wall", (W, 0.2, G), (0, D / 2 - 0.1, SLAB + G / 2), M["cladding"], uv=(1.5, 1.5))
    for side, x in (("left", -W / 2 + 0.1), ("right", W / 2 - 0.1)):
        box(f"Side wall {side}", (0.2, inside, G), (x, GLASS + inside / 2, SLAB + G / 2), M["cladding"], uv=(1.5, 1.5))
        box(f"Column {side}", (0.3, 0.3, G), (math.copysign(W / 2 - 0.15, x), FRONT + 0.15, SLAB + G / 2), M["concrete"])

    # Street level: a glass front with a pair of doors, lit from the overhang above
    box("Glass", (W - 0.4, 0.02, G), (0, GLASS, SLAB + G / 2), M["glass"], group="Front")
    for x in np.linspace(-W / 2 + 0.2, W / 2 - 0.2, 7):
        box("Mullion", (0.06, 0.08, G), (x, GLASS, SLAB + G / 2), M["steel"], group="Front")
    for z in (SLAB + 0.03, UP - 0.04):
        box("Glass frame", (W - 0.4, 0.08, 0.06), (0, GLASS, z), M["steel"], group="Front")
    box("Door top", (1.86, 0.08, 0.05), (0, GLASS, SLAB + 1.85), M["steel"], group="Front")
    for x in (-0.09, 0.09):
        box("Door handle", (0.03, 0.04, 0.5), (x, GLASS - 0.06, SLAB + 1.0), M["steel"], group="Front")
    box("Doormat", (1.2, 0.5, 0.01), (0, GLASS - 0.3, SLAB + 0.005), M["dark"], group="Front")
    box("Overhang light", (W - 0.7, 0.05, 0.03), (0, FRONT + 0.12, UP - 0.015), M["warm"], group="Front")
    for x in (-2.0, -0.7, 0.7, 2.0):
        cylinder("Downlight", 0.07, 0.02, (x, GLASS - 0.3, UP - 0.01), M["warm"], segments=12, group="Front")
    box("Paper sign", (1.25, 0.04, 0.17), (0, GLASS - 0.12, UP - 0.2), M["panel"], group="Signs")
    text("Paper trades only", "PAPER TRADES ONLY", 0.085, (0, GLASS - 0.145, UP - 0.2), M["amber"], latin)
    for x in (-0.5, 0.5):
        box("Sign hanger", (0.015, 0.015, 0.11), (x, GLASS - 0.12, UP - 0.055), M["steel"], group="Signs")

    # Inside: rows of desks covered in screens, and a wall of charts at the back
    box("Trading floor", (W - 0.4, inside - 0.2, 0.02), (0, GLASS + inside / 2 - 0.1, SLAB + 0.01), M["floor"], group="Inside")
    picture("Chart wall", W - 0.8, 1.2, (0, D / 2 - 0.21, SLAB + 1.3), M["chart wall"], group="Inside")
    for x in (-1.75, 0, 1.75):
        box("Ceiling light", (0.08, inside - 0.6, 0.03), (x, GLASS + inside / 2, UP - 0.02), M["strip"], group="Inside")
    for row, y in enumerate((-0.75, 0.6)):
        for col, x in enumerate((-1.75, 0.0, 1.75)):
            desk(x, y, row * 3 + col)

    # Upstairs: a stock ticker running round the building, a big screen of candlesticks and lit offices
    band = UP + 0.2
    box("Ticker band", (W + 0.04, 0.1, 0.34), (0, FRONT - 0.05, band), M["panel"], group="Signs")
    box("Ticker band", (0.1, D + 0.04, 0.34), (W / 2 + 0.05, 0, band), M["panel"], group="Signs")
    quotes = [("EMBR", "+4.20"), ("NEON", "-1.37"), ("RAIN", "+0.88"), ("VOLT", "+2.05"),
              ("SYNTH", "-0.42"), ("ORBX", "+7.31"), ("GRID", "-2.16")]
    spots = [(x, FRONT - 0.105, 0) for x in (-2.0, -0.6, 0.8, 2.2)] + \
            [(W / 2 + 0.105, y, math.pi / 2) for y in (-1.5, 0, 1.5)]
    for (name, change), (x, y, turn) in zip(quotes, spots):
        along = Vector((math.cos(turn), math.sin(turn), 0))  # the way the ticker reads
        colour = M["green"] if change.startswith("+") else M["red"]
        text(f"Ticker {name}", name, 0.17, Vector((x, y, band)) - along * 0.3, M["amber"], latin, rotation=(math.pi / 2, 0, turn))
        text(f"Ticker {name} change", change, 0.17, Vector((x, y, band)) + along * 0.32, colour, latin, rotation=(math.pi / 2, 0, turn))
    # The live ticker: on Ember's roof these strips show real prices and Vega's account scrolling past (the site
    # finds them by their name, "LiveTicker"). One unit of U is 64 times a strip's height, so the letters keep their
    # shape on any length of strip. Renders here don't show them, so the made-up quotes stay in the pictures.
    for width, location, rotation in ((W, (0, FRONT - 0.13, band), (0, 0, 0)),
                                      (D - 0.4, (W / 2 + 0.13, -0.15, band), (0, 0, math.pi / 2))):
        strip = picture("LiveTicker", width, 0.3, location, M["live ticker"], rotation=rotation, group="Signs")
        for loop in strip.data.uv_layers[0].data:
            loop.uv.x *= width / 0.3 / 64
        strip.hide_render = True

    bx, bz, bw, bh = 0.75, UP + 1.25, 3.5, 1.45
    box("Big screen frame", (bw + 0.16, 0.12, bh + 0.16), (bx, FRONT - 0.06, bz), M["dark"], group="Signs")
    picture("Big screen", bw, bh, (bx, FRONT - 0.125, bz), M["big screen"], group="Signs")
    frame("Big screen tube", bx - bw / 2 - 0.1, bx + bw / 2 + 0.1, bz - bh / 2 - 0.1, bz + bh / 2 + 0.1, FRONT - 0.13, M["cyan"])
    for z in (UP + 0.75, UP + 1.3, UP + 1.85):
        box("Office window frame", (1.62, 0.05, 0.42), (-2.05, FRONT - 0.02, z), M["dark"], group="Front")
        picture("Office window", 1.5, 0.34, (-2.05, FRONT - 0.05, z), M["offices"])

    # A blade sign sticking out from the corner: 取引所, "the exchange"
    vx, vy, vz = -W / 2 + 0.3, FRONT - 0.5, UP + 1.1
    box("Blade sign", (0.1, 0.6, 1.75), (vx, vy, vz), M["panel"], group="Signs")
    for dz in (-0.6, 0.6):
        box("Blade sign bracket", (0.05, 0.22, 0.05), (vx, FRONT - 0.1, vz + dz), M["dark"], group="Signs")
    for side, turn in (("right", math.pi / 2), ("left", -math.pi / 2)):
        dx = math.copysign(0.055, turn)
        text(f"Blade letters {side}", "取\n引\n所" if cjk else "T\nR\nA\nD\nE", 0.4 if cjk else 0.28,
             (vx + dx, vy, vz), M["pink"], cjk or latin, rotation=(math.pi / 2, 0, turn), line=0.95)
        tube(f"Blade tube {side}", [(vx + dx * 1.1, vy + a, vz + b) for a, b in ((-0.25, -0.8), (0.25, -0.8), (0.25, 0.8), (-0.25, 0.8))],
             0.014, M["pink"], cyclic=True)

    # Up top: TRADING FLOOR in big letters on a frame along the front of the roof
    floor, lz = TOP + 0.04, TOP + 0.72
    text("TRADING FLOOR", "TRADING FLOOR", 0.5, (0.35, FRONT + 0.25, lz), M["cyan"], latin)
    tube("Letters underline", [(-1.5, FRONT + 0.25, lz - 0.33), (2.2, FRONT + 0.25, lz - 0.33)], 0.012, M["pink"])
    brace = math.asin(0.67 / math.hypot(0.67, 0.9))
    for x in (-1.45, -0.25, 0.95, 2.15):
        box("Letter frame post", (0.05, 0.05, 1.0), (x, FRONT + 0.33, floor + 0.5), M["dark"], group="Roof")
        box("Letter frame brace", (0.04, 0.04, math.hypot(0.67, 0.9)), (x, FRONT + 0.665, floor + 0.45), M["dark"],
            rotation=(brace, 0, 0), group="Roof")
    for z in (lz - 0.28, lz + 0.22):
        box("Letter frame bar", (3.8, 0.04, 0.04), (0.35, FRONT + 0.33, z), M["dark"], group="Roof")

    # The roof: parapet, a stair hut, a chiller for the computers, dishes, solar panels and a mast
    box("Roof", (W - 0.24, D - 0.24, 0.04), (0, 0, TOP + 0.02), M["roof"], uv=(2, 2), group="Roof")
    t, ph = 0.15, 0.3
    for name, size, (x, y) in (("front", (W, t, ph), (0, FRONT + t / 2)), ("back", (W, t, ph), (0, D / 2 - t / 2)),
                               ("left", (t, D - 2 * t, ph), (-W / 2 + t / 2, 0)), ("right", (t, D - 2 * t, ph), (W / 2 - t / 2, 0))):
        box(f"Parapet {name}", size, (x, y, TOP + ph / 2), M["cladding"], uv=(1.5, 1.5), group="Roof")
        box(f"Coping {name}", (size[0] + 0.04, size[1] + 0.04, 0.05), (x, y, TOP + ph + 0.025), M["concrete"], group="Roof")

    hx, hy = -1.9, 1.3
    box("Stair hut", (1.3, 1.2, 1.5), (hx, hy, floor + 0.75), M["cladding"], uv=(1.5, 1.5), group="Roof")
    box("Stair hut roof", (1.42, 1.32, 0.07), (hx, hy, floor + 1.535), M["concrete"], group="Roof")
    box("Stair hut door", (0.62, 0.05, 1.15), (hx + 0.2, hy - 0.61, floor + 0.575), M["steel"], group="Roof")
    box("Stair hut light", (0.5, 0.06, 0.03), (hx + 0.2, hy - 0.63, floor + 1.25), M["strip"], group="Roof")
    box("Keypad", (0.08, 0.03, 0.12), (hx - 0.25, hy - 0.615, floor + 0.95), M["green"], group="Roof")

    cx, cy = 1.15, 1.35
    box("Chiller", (1.6, 0.9, 0.55), (cx, cy, floor + 0.275), M["white"], group="Roof")
    for dx in (-0.4, 0.4):
        cylinder("Chiller fan", 0.3, 0.04, (cx + dx, cy, floor + 0.57), M["dark"], segments=20, group="Roof")
        for a in range(3):
            box("Fan blade", (0.5, 0.06, 0.01), (cx + dx, cy, floor + 0.6), M["steel"], rotation=(0, 0, a * math.pi / 3), group="Roof")

    dish("Big dish", 0.2, 0.3, 0.5, (-0.6, 0, 0.5), floor)
    dish("Small dish", 0.95, -0.6, 0.3, (-0.5, 0, -0.4), floor)
    for x in (-2.1, -0.95):
        box("Solar panel", (1.0, 0.65, 0.03), (x, -0.55, floor + 0.35), M["solar"], rotation=(0.44, 0, 0), group="Roof")
        for dx in (-0.4, 0.4):
            box("Solar leg", (0.04, 0.04, 0.42), (x + dx, -0.3, floor + 0.21), M["dark"], group="Roof")

    mx, my = 2.4, 0.15
    cylinder("Mast", 0.035, 2.6, (mx, my, floor + 1.3), M["steel"], segments=8, group="Roof")
    for z in (0.9, 1.5, 2.1):
        box("Mast bar", (0.45, 0.03, 0.03), (mx, my, floor + z), M["steel"], group="Roof")
    for a in (0, 2 * math.pi / 3, 4 * math.pi / 3):
        box("Mast antenna", (0.12, 0.04, 0.4), (mx + 0.1 * math.cos(a), my + 0.1 * math.sin(a), floor + 1.75), M["white"],
            rotation=(0, 0, a + math.pi / 2), group="Roof")
    sphere("Mast light", 0.06, (mx, my, floor + 2.62), M["red"], group="Roof")
    for end in ((2.75, my - 0.9), (2.75, my + 0.9), (1.6, my)):
        cable("Guy wire", (mx, my, floor + 2.0), (*end, floor + 0.02), 0)

    # Right side: a neon chart line climbing the wall, a screen of the whole market, and a side door
    rx, turn = W / 2, (0, 0, math.pi / 2)  # turn faces +X
    line = [(-1.95, 2.95), (-1.5, 3.35), (-1.15, 3.1), (-0.65, 3.75), (-0.3, 3.5), (0.25, 4.15)]
    tube("Chart line", [(rx + 0.05, y, z) for y, z in line], 0.025, M["green"], group="Side")
    tip = Vector(line[-1])
    back = (Vector(line[-2]) - tip).normalized() * 0.32
    for a in (0.55, -0.55):
        head = tip + Matrix.Rotation(a, 2) @ back
        tube("Chart arrow", [(rx + 0.05, *head), (rx + 0.05, *tip)], 0.025, M["green"], group="Side")
    box("Market map frame", (0.1, 1.25, 1.7), (rx + 0.05, 1.35, UP + 1.27), M["dark"], group="Side")
    picture("Market map", 1.05, 1.55, (rx + 0.105, 1.35, UP + 1.27), M["market map"], rotation=turn, group="Side")
    box("Side door", (0.05, 0.85, 1.7), (rx + 0.02, 0.9, SLAB + 0.85), M["steel"], group="Side")
    box("Side door light", (0.06, 0.65, 0.04), (rx + 0.05, 0.9, SLAB + 1.82), M["blue"], group="Side")
    box("Side keypad", (0.03, 0.08, 0.12), (rx + 0.03, 0.35, SLAB + 1.05), M["green"], group="Side")
    for i, y in enumerate((-1.2, -0.45)):
        box(f"Server cooler {i + 1}", (0.55, 0.65, 0.95), (rx + 0.3, y, SLAB + 0.475), M["white"], group="Side")
        for z in (0.3, 0.68):
            cylinder("Cooler fan", 0.16, 0.03, (rx + 0.585, y, SLAB + z), M["dark"], rotation=(0, math.pi / 2, 0), group="Side")
        box("Cooler light", (0.02, 0.4, 0.03), (rx + 0.58, y, SLAB + 0.88), M["cyan"], group="Side")
    box("Cable tray", (0.12, 0.2, H + 0.4), (rx + 0.16, 2.1, SLAB + (H + 0.4) / 2), M["steel"], group="Side")

    # Left side: a drainpipe and more office windows
    lx = -W / 2
    cylinder("Drainpipe", 0.05, H + 0.25, (lx - 0.07, 1.9, SLAB + (H + 0.25) / 2), M["dark"], segments=10, group="Side")
    for z in (UP + 0.8, UP + 1.5):
        picture("Office window", 2.6, 0.34, (lx - 0.005, 0.2, z), M["offices"], rotation=(0, 0, -math.pi / 2), group="Side")

    # Out front: lit bollards, a quote terminal, a bench and a planter under the overhang
    for x in (-1.3, 1.3, 2.6):
        cylinder("Bollard", 0.08, 0.6, (x, FRONT - 0.75, SLAB + 0.3), M["dark"], segments=12, group="Props")
        cylinder("Bollard light", 0.085, 0.05, (x, FRONT - 0.75, SLAB + 0.5), M["cyan"], segments=12, group="Props")
    kx = -2.4
    box("Quote terminal", (0.42, 0.3, 1.35), (kx, FRONT - 0.6, SLAB + 0.675), M["dark"], group="Props")
    picture("Quote screen", 0.32, 0.5, (kx, FRONT - 0.755, SLAB + 0.95), M["screen0"], group="Props")
    box("Quote terminal light", (0.42, 0.31, 0.04), (kx, FRONT - 0.6, SLAB + 1.33), M["cyan"], group="Props")
    box("Bench", (1.0, 0.36, 0.06), (1.85, FRONT + 0.3, SLAB + 0.45), M["desk"], group="Props")
    for dx in (-0.4, 0.4):
        box("Bench leg", (0.06, 0.32, 0.42), (1.85 + dx, FRONT + 0.3, SLAB + 0.21), M["dark"], group="Props")
    box("Planter", (0.7, 0.4, 0.45), (-1.85, FRONT + 0.3, SLAB + 0.225), M["concrete"], group="Props")
    for dx, dz, r in ((-0.15, 0.55, 0.17), (0.12, 0.6, 0.15), (0, 0.75, 0.13), (0.2, 0.5, 0.1), (-0.25, 0.48, 0.1)):
        sphere("Leaves", r, (-1.85 + dx, FRONT + 0.3, SLAB + dz), M["leaves"])


# ---------------------------------------------------------------------------
# A stage to photograph it on (not exported): wet ground, a night sky, coloured light
# ---------------------------------------------------------------------------

def light(name, kind, location, rotation, colour, energy, size=1.0, reflected=True):
    data = bpy.data.lights.new(name, kind)
    data.color, data.energy = colour, energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = location, rotation
    obj.visible_glossy = reflected  # off for low lights that would show up as bright squares in the wet ground
    collection("Stage").objects.link(obj)


def stage():
    ground = material("Wet ground", (0.01, 0.012, 0.018), roughness=0.12)
    mesh = bpy.data.meshes.new("Ground")
    mesh.from_pydata([(-40, -40, 0), (40, -40, 0), (40, 40, 0), (-40, 40, 0)], [], [(0, 1, 2, 3)])
    add("Ground", mesh, ground, (0, 0, -0.001), group="Stage")

    world = bpy.data.worlds.new("Night")
    if world.node_tree is None:
        world.use_nodes = True
    background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    background.inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
    scene.world = world

    # Area lights shine down their -Z: these turn them to shine at the front wall (+Y) or the right wall (-X)
    down, at_front, at_right = (0, 0, 0), (math.pi / 2, 0, 0), (math.pi / 2, 0, math.pi / 2)
    light("Moon", "SUN", (0, 0, 10), (math.radians(55), 0, math.radians(-35)), (0.55, 0.65, 1), 0.5)
    light("Trading floor light", "AREA", (0, 0.3, UP - 0.08), down, (0.75, 0.85, 1), 40, 3.2)
    light("Overhang light", "AREA", (0, FRONT + 0.3, UP - 0.1), down, (1, 0.72, 0.4), 20, 1.5, reflected=False)
    light("Big screen glow", "AREA", (0.75, FRONT - 0.35, UP + 1.25), (-math.pi / 4, 0, 0), (0.3, 1, 0.55), 40, 2, reflected=False)
    light("Letters glow", "AREA", (0.35, FRONT - 0.4, TOP + 0.75), at_front, NEON_COLOURS["cyan"], 25, 2.5, reflected=False)
    light("Blade sign glow", "AREA", (-W / 2 + 0.8, FRONT - 0.9, UP + 1.1), at_front, NEON_COLOURS["pink"], 15, 1, reflected=False)
    light("Chart line glow", "AREA", (W / 2 + 1.0, -0.85, 3.5), at_right, NEON_COLOURS["green"], 35, 1.8, reflected=False)
    light("Market map glow", "AREA", (W / 2 + 0.9, 1.35, 3.45), at_right, (1, 0.45, 0.4), 12, 1.2, reflected=False)
    light("Side door glow", "AREA", (W / 2 + 0.8, 0.9, 1.9), at_right, NEON_COLOURS["blue"], 20, 1, reflected=False)
    light("Roof glow", "AREA", (0, 0, TOP + 3.5), down, (0.5, 0.75, 1), 60, 4)
    light("City glow", "AREA", (W / 2 + 4, D / 2 + 3, 5), (math.radians(60), 0, math.radians(130)), (1, 0.25, 0.6), 150, 4)
    light("Rim", "AREA", (-3, 4, 7), (math.radians(-140), 0, math.radians(-30)), (0.5, 0.4, 1), 120, 4)

    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.type = "ORTHO"
    collection("Stage").objects.link(camera)
    scene.camera = camera
    aim(camera, "iso")

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.cycles.preview_samples = 32  # the rendered 3D view: quick, and denoised
    scene.cycles.use_preview_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 1024
    for look in ("AgX - Punchy", "Punchy"):
        try:
            scene.view_settings.view_transform, scene.view_settings.look = "AgX", look
            break
        except TypeError:
            continue
    glow()
    for screen in bpy.data.screens:  # look through the camera, rendered and glowing
        for area in screen.areas:
            if area.type == "VIEW_3D":
                view = area.spaces.active
                view.shading.type, view.shading.use_compositor = "RENDERED", "ALWAYS"
                view.region_3d.view_perspective = "CAMERA"


def glow():
    """A soft bloom around the neon, like a camera would see it, in renders and in the rendered 3D view."""
    tree = bpy.data.node_groups.new("Glow", "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    layers, out, bloom = (tree.nodes.new(t) for t in ("CompositorNodeRLayers", "NodeGroupOutput", "CompositorNodeGlare"))
    bloom.inputs["Type"].default_value = "Bloom"
    bloom.inputs["Quality"].default_value = "High"
    bloom.inputs["Threshold"].default_value = 0.5
    bloom.inputs["Strength"].default_value = 1.0
    bloom.inputs["Size"].default_value = 0.75
    tree.links.new(layers.outputs["Image"], bloom.inputs["Image"])
    tree.links.new(bloom.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = tree


VIEWS = {  # what the camera looks at, from how far round and how far down (degrees), and how much it takes in
    "iso": ((0.6, -0.3, 3.2), 40, 32, 11.5),
    "front": ((0.35, -0.2, 3.3), 0, 2, 10.0),
}


def aim(camera, view):
    target, around, down, size = VIEWS[view]
    a, e = math.radians(around), math.radians(down)
    looking = Vector((-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), -math.sin(e)))
    camera.location = Vector(target) - looking * 40
    camera.rotation_euler = (math.pi / 2 - e, 0, a)
    camera.data.ortho_scale = size


# ---------------------------------------------------------------------------
# Command-line extras: previews and the .glb for Ember
# ---------------------------------------------------------------------------

def use_gpu():
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            preferences.compute_device_type = kind
        except TypeError:
            continue
        preferences.get_devices()
        devices = [d for d in preferences.devices if d.type == kind]
        if devices:
            for d in devices:
                d.use = True
            scene.cycles.device = "GPU"
            return kind
    return "CPU"


def brighten_lights(factor):
    """Turn every glowing material up (for photos) or back down (for Ember, whose 3D view adds its own glow)."""
    for mat in bpy.data.materials:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.node_tree else None
        if bsdf and bsdf.inputs["Emission Strength"].default_value > 0:
            bsdf.inputs["Emission Strength"].default_value *= factor


def render(view, path):
    aim(scene.camera, view)
    scene.render.filepath = str(path)
    brighten_lights(2.5)
    bpy.ops.render.render(write_still=True)
    brighten_lights(1 / 2.5)


def export(path):
    """One mesh per material (far fewer draw calls for Ember's 3D view), then a .glb with no lights or camera."""
    bpy.context.view_layer.update()
    building = [o for o in scene.objects if o.type == "MESH" and o.users_collection[0].name != "Stage"]
    by_material = {}
    for obj in building:
        by_material.setdefault(obj.active_material.name, []).append(obj)
    keep = []
    for objs in by_material.values():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs,
                                           selected_editable_objects=objs):
                bpy.ops.object.join()
        keep.append(objs[0])
    for obj in scene.objects:
        obj.select_set(obj in keep)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
                              export_lights=False, export_cameras=False, export_yup=True,
                              export_draco_mesh_compression_enable=True)  # Ember's 3D view can unpack it


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for group in list(bpy.data.collections):
        bpy.data.collections.remove(group)
    for blocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.images, bpy.data.lights,
                   bpy.data.cameras, bpy.data.worlds):
        for block in list(blocks):
            if block.users == 0:
                blocks.remove(block)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="save iso and front previews")
    parser.add_argument("--export", action="store_true", help="save ../site/models/trading_floor.glb for Ember")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    clear()
    make_materials()
    build()
    stage()
    if args.render or args.export:
        bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "trading_floor.blend"))
    if args.render:
        print("Rendering on", use_gpu())
        render("iso", HERE / "trading_floor_iso.png")
        render("front", HERE / "trading_floor_front.png")
    if args.export:
        export(HERE.parent / "site" / "models" / "trading_floor.glb")


main()
