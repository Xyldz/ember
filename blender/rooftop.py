"""
rooftop.py - everything on Ember's roof that used to be plain boxes, remade properly. Built entirely from code.

The four places Ember uses (the data terminal, charging pod, lookout railing and old radio) are built to the same
measurements as the boxes they replace, so Ember still stands, sleeps and looks in the same spots. The rest is roof
clutter (air conditioners, a water tank, a dish, vents, crates, pipes, a stairwell), placed as props in
../site/scenery.json, where builder mode can move them.

From a terminal:
  blender -b -P rooftop.py -- --render --export
That exports every piece to ../site/models/, renders a preview of each into rooftop/ (not kept in git) and one of the
whole roof (rooftop.png), and saves rooftop.blend: the whole roof laid out as it is on the site (the Blender-made
buildings included), so you can open it and look around.
  blender -b -P rooftop.py -- --only radio --render    just one piece
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

SCRIPT = Path(globals().get("__file__", ""))
HERE = SCRIPT.resolve().parent if SCRIPT.is_file() else Path.cwd()
SITE = HERE.parent / "site"
rng = np.random.default_rng(11)
scene = bpy.context.scene
M = {}
piece = "Stage"  # the collection new objects go into


# ---------------------------------------------------------------------------
# Pictures and materials
# ---------------------------------------------------------------------------

def make_image(name, rgb):
    h, w, _ = rgb.shape
    image = bpy.data.images.new(name, w, h)
    image.pixels.foreach_set(np.flipud(np.concatenate([np.clip(rgb, 0, 1), np.ones((h, w, 1))], axis=2)).astype(np.float32).ravel())
    image.pack()
    return image


def code_lines(w=192, h=128, colour=(0.25, 1, 0.55)):
    img = np.zeros((h, w, 3))
    img[:] = (0.01, 0.03, 0.03)
    for y in range(6, h - 6, 7):
        x = 6 + 6 * rng.integers(0, 4)
        img[y:y + 3, x:x + rng.integers(20, w - x - 6)] = np.array(colour) * rng.uniform(0.5, 1)
    return img


def graph(w=192, h=128, colour=(1, 0.3, 0.75)):
    img = np.zeros((h, w, 3))
    img[:] = (0.02, 0.01, 0.04)
    img[::16] = img[:, ::16] = (0.08, 0.06, 0.14)  # grid
    ys = (h / 2 + np.cumsum(rng.normal(0, 4, w))).clip(8, h - 8).astype(int)
    for x, y in enumerate(ys):
        img[y - 1:y + 2, x] = colour
        img[y + 2:, x] = np.array(colour) * 0.12
    return img


def planks(w=128, h=128, base=(0.32, 0.21, 0.12)):
    img = np.array(base) * (0.8 + 0.35 * rng.random((h, w, 1)))
    img[::21] *= 0.35  # gaps between the slats
    return img


def louvres(w=64, h=64):
    img = np.full((h, w, 3), 0.42)
    img[::5] = 0.1
    img[1::5] = 0.6
    return img


def hazard(w=128, h=32):
    x = np.arange(w)[None, :] + np.arange(h)[:, None]
    img = np.where(((x // 12) % 2)[..., None] == 0, np.array((1, 0.75, 0.05)), np.array((0.05, 0.05, 0.05)))
    return img.astype(float)


def material(name, colour=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.6, emission=None, strength=0.0, image=None,
             glow_image=False, alpha=1.0):
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
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        if glow_image:  # a screen: the picture itself glows
            links.new(texture.outputs["Color"], bsdf.inputs["Emission Color"])
            strength = strength or 1.6
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        bsdf.inputs["Alpha"].default_value = alpha
        for attr, value in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            if hasattr(mat, attr):
                setattr(mat, attr, value)
    mat.diffuse_color = (*(emission or colour), 1)
    return mat


NEON = {"cyan": (0.1, 0.9, 1), "pink": (1, 0.25, 0.7), "amber": (1, 0.75, 0.3), "violet": (0.55, 0.36, 1),
        "red": (1, 0.1, 0.12), "green": (0.2, 1, 0.45)}


def make_materials():
    M["dark"] = material("Dark metal", (0.035, 0.038, 0.05), metallic=0.6, roughness=0.45)
    M["panel"] = material("Panel", (0.09, 0.1, 0.14), metallic=0.4, roughness=0.5)
    M["steel"] = material("Steel", (0.3, 0.32, 0.36), metallic=0.85, roughness=0.32)
    M["chrome"] = material("Chrome", (0.8, 0.82, 0.86), metallic=1, roughness=0.12)
    M["white"] = material("White paint", (0.55, 0.57, 0.62), roughness=0.55)
    M["rubber"] = material("Rubber", (0.02, 0.02, 0.025), roughness=0.85)
    M["concrete"] = material("Concrete", (0.16, 0.16, 0.17), roughness=0.9)
    M["paint"] = material("Painted metal", (0.2, 0.24, 0.3), metallic=0.3, roughness=0.55)
    M["rust"] = material("Rusty metal", (0.28, 0.14, 0.08), metallic=0.5, roughness=0.75)
    M["wood"] = material("Crate wood", image=make_image("Planks", planks()), roughness=0.8)
    M["louvres"] = material("Louvres", image=make_image("Louvres", louvres()), metallic=0.4, roughness=0.5)
    M["hazard"] = material("Hazard stripes", image=make_image("Hazard", hazard()), roughness=0.6)
    M["glass"] = material("Glass", (0.6, 0.95, 1), roughness=0.05, alpha=0.16)
    M["cushion"] = material("Cushion", (0.22, 0.1, 0.32), roughness=0.95)
    M["code"] = material("Code screen", (0.02, 0.05, 0.05), emission=(0.1, 0.6, 0.5), strength=0.6)
    M["graph"] = material("Graph screen", image=make_image("Graph", graph()), glow_image=True)
    M["lines"] = material("Side screen", image=make_image("Lines", code_lines()), glow_image=True)
    for name, colour in NEON.items():
        M[name] = material(f"Neon {name}", colour, emission=colour, strength=4.0)


# ---------------------------------------------------------------------------
# Building blocks: every new object lands in the current piece's collection
# ---------------------------------------------------------------------------

def collection(name):
    found = bpy.data.collections.get(name)
    if not found:
        found = bpy.data.collections.new(name)
        scene.collection.children.link(found)
    return found


def add(name, mesh, mat, location, rotation=(0, 0, 0)):
    if mat:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler = location, rotation
    collection(piece).objects.link(obj)
    return obj


def from_bmesh(name, bm, mat, location, rotation=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add(name, mesh, mat, location, rotation)


def box(name, size, location, mat, rotation=(0, 0, 0), bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]
    if bevel:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, segments=2, affect="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if mat and mat.node_tree and any(n.type == "TEX_IMAGE" for n in mat.node_tree.nodes):
        uv = bm.loops.layers.uv.new("UVMap")  # simple box mapping, so textures show
        for face in bm.faces:
            axis = max(range(3), key=lambda i: abs(face.normal[i]))
            a, b = [i for i in range(3) if i != axis]
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co[a] / max(size[a], 1e-3) + 0.5, loop.vert.co[b] / max(size[b], 1e-3) + 0.5)
    return from_bmesh(name, bm, mat, location, rotation)


def cylinder(name, radius, length, middle, direction, mat, segments=16, tip=None):
    """A cylinder (or a cone, with tip=its far radius) along direction, centred on middle."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius if tip is None else tip, depth=length, calc_uvs=True)
    return from_bmesh(name, bm, mat, Vector(middle), Vector(direction).to_track_quat("Z", "Y").to_euler())


def rod(name, radius, start, end, mat, segments=8):
    start, end = Vector(start), Vector(end)
    return cylinder(name, radius, (end - start).length, (start + end) / 2, end - start, mat, segments)


def torus(name, major, minor, location, mat, rotation=(0, 0, 0), segments=40, sides=8, arc=2 * math.pi):
    bm = bmesh.new()
    rings = []
    closed = arc >= 2 * math.pi - 1e-6
    for i in range(segments + (0 if closed else 1)):
        a = arc * i / segments
        centre = Vector((math.cos(a) * major, math.sin(a) * major, 0))
        out = Vector((math.cos(a), math.sin(a), 0))
        rings.append([bm.verts.new(centre + out * math.cos(b) * minor + Vector((0, 0, math.sin(b) * minor)))
                      for b in (2 * math.pi * j / sides for j in range(sides))])
    for i in range(len(rings) - (0 if closed else 1)):
        r0, r1 = rings[i], rings[(i + 1) % len(rings)]
        for j in range(sides):
            bm.faces.new((r0[j], r1[j], r1[(j + 1) % sides], r0[(j + 1) % sides]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return from_bmesh(name, bm, mat, location, rotation)


def sphere(name, radius, location, mat, segments=16, rings=10, top_half=False, bowl=False, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    if top_half or bowl:
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if (v.co.z > 1e-4 if bowl else v.co.z < -1e-4)], context="VERTS")
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * scale[0], v.co.y * scale[1], v.co.z * scale[2]
    return from_bmesh(name, bm, mat, location)


def picture(name, width, height, location, mat, tilt=0.0, turn=0.0):
    """A flat picture facing -Y (towards Ember), leaning back by tilt, turned about Z by turn."""
    mesh = bpy.data.meshes.new(name)
    w, h = width / 2, height / 2
    mesh.from_pydata([(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = uv
    return add(name, mesh, mat, location, (-tilt, 0, turn))


def text(name, body, size, location, mat, rotation=(math.pi / 2, 0, 0)):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.align_x, curve.align_y, curve.extrude = body, size, "CENTER", "CENTER", 0.012
    font = Path(r"C:\Windows\Fonts\bahnschrift.ttf")
    if font.exists():
        curve.font = bpy.data.fonts.load(str(font), check_existing=True)
    obj = bpy.data.objects.new(name, curve)
    collection(piece).objects.link(obj)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)
    return add(name, mesh, mat, location, rotation)


def cable(name, points, radius, mat):
    """A cable through these points, as a chain of rods."""
    for i, (a, b) in enumerate(zip(points, points[1:])):
        rod(f"{name} {i + 1}", radius, a, b, mat, segments=6)


# ---------------------------------------------------------------------------
# The places Ember uses. Ember stands at the origin; each faces it from +Y (the page's -Z)
# ---------------------------------------------------------------------------

def terminal():
    """A console desk with a big screen of scrolling code (the page draws it live onto CodeScreen), side monitors,
    two server racks and cables running off to the roof's edge. Same footprint as the old box version."""
    box("Desk", (2.3, 0.95, 0.78), (0, 1.35, 0.39), M["panel"], bevel=0.03)
    box("Desk top", (2.4, 0.7, 0.08), (0, 1.2, 0.85), M["dark"], rotation=(math.radians(-14), 0, 0), bevel=0.02)
    box("Front glow", (2.1, 0.03, 0.03), (0, 0.85, 0.8), M["cyan"])
    box("Keyboard", (1.1, 0.3, 0.03), (0, 1.12, 0.91), M["rubber"], rotation=(math.radians(-14), 0, 0))
    for i in range(14):  # a row of lit keys
        box("Key", (0.06, 0.05, 0.02), (-0.5 + i * 0.077, 1.06, 0.93), M["cyan"] if i % 5 == 0 else M["steel"],
            rotation=(math.radians(-14), 0, 0))
    for x, colour in ((-0.85, "pink"), (-0.72, "amber"), (0.75, "green"), (0.88, "cyan")):
        cylinder("Knob", 0.035, 0.04, (x, 1.18, 0.92), (0, -0.25, 1), M[colour], segments=10)
    # The main screen on two posts, leaning back a little
    for x in (-0.7, 0.7):
        rod("Screen post", 0.04, (x, 1.75, 0.8), (x, 1.75, 1.35), M["steel"])
    tilt = math.radians(7)
    box("Screen bezel", (2.4, 0.12, 1.5), (0, 1.8, 2.0), M["dark"], rotation=(-tilt, 0, 0), bevel=0.03)
    screen = picture("CodeScreen", 2.2, 1.3, (0, 1.735, 2.0), M["code"], tilt=tilt)
    screen.name = "CodeScreen"
    box("Screen light", (2.2, 0.04, 0.03), (0, 1.74, 2.77), M["cyan"], rotation=(-tilt, 0, 0))
    # Side monitors, turned towards Ember
    for side, mat in ((-1, M["graph"]), (1, M["lines"])):
        turn = -side * math.radians(28)
        x = side * 1.62
        box("Monitor", (0.82, 0.08, 0.6), (x, 1.45, 1.55), M["dark"], rotation=(0, 0, turn), bevel=0.02)
        picture("Monitor screen", 0.72, 0.5, (x - side * 0.02, 1.405, 1.55), mat, turn=turn)
        rod("Monitor arm", 0.03, (x, 1.5, 0.8), (x, 1.5, 1.27), M["steel"])
    # Server racks with blinking lights, behind and to the sides
    for side in (-1, 1):
        x = side * 1.75
        box("Rack", (0.62, 0.8, 2.3), (x, 2.55, 1.15), M["dark"], bevel=0.02)
        box("Rack front", (0.52, 0.02, 2.1), (x, 2.14, 1.15), M["panel"])
        for row in range(12):
            z = 0.25 + row * 0.16
            box("Rack slot", (0.46, 0.02, 0.1), (x, 2.13, z), M["rubber"])
            for k in range(3):
                colour = ("cyan", "green", "pink", "amber")[(row + k * 3 + side) % 4]
                box("LED", (0.025, 0.02, 0.025), (x - 0.18 + k * 0.05, 2.12, z), M[colour])
        box("Rack top light", (0.5, 0.6, 0.02), (x, 2.55, 2.31), M["violet"])
    # Cables off to the edge of the roof, sagging a little
    for x, colour in ((-0.6, "pink"), (0.5, "cyan")):
        cable("Cable", [(x, 1.8, 0.02), (x * 1.1, 4, 0.03), (x * 0.9, 7, 0.02), (x, 10.8, 0.03)], 0.035, M[colour])
    cable("Power cable", [(-1.7, 2.9, 0.4), (-1.9, 3.3, 0.04), (-1.4, 6, 0.04), (-1.6, 10.8, 0.04)], 0.06, M["rubber"])
    cable("Power cable", [(1.7, 2.9, 0.4), (1.95, 3.4, 0.04), (2.3, 6.5, 0.04), (2.1, 10.8, 0.04)], 0.06, M["rubber"])


def pod():
    """A charging capsule: a plinth with a neon ring, a padded bed (Ember sleeps on it, 0.35 up), a framed glass dome,
    charging coils and a battery unit wired in behind. Centred 1.5 behind Ember, like the old one."""
    c = Vector((0, 1.5, 0))
    cylinder("Step", 1.58, 0.08, c + Vector((0, 0, 0.04)), (0, 0, 1), M["dark"], segments=8)
    cylinder("Plinth", 1.42, 0.25, c + Vector((0, 0, 0.205)), (0, 0, 1), M["panel"], segments=8)
    torus("Neon ring", 1.32, 0.04, c + Vector((0, 0, 0.33)), M["pink"], segments=48)
    cylinder("Bed", 1.0, 0.05, c + Vector((0, 0, 0.35)), (0, 0, 1), M["cushion"], segments=32)
    for r in (0.45, 0.75):
        torus("Bed stitching", r, 0.012, c + Vector((0, 0, 0.376)), M["violet"], segments=40, sides=6)
    sphere("Dome", 1.25, c + Vector((0, 0, 0.33)), M["glass"], segments=32, rings=16, top_half=True)
    for i in range(3):  # ribs over the dome, each one right over the top
        torus("Rib", 1.26, 0.022, c + Vector((0, 0, 0.33)), M["steel"], rotation=(math.pi / 2, 0, i * math.pi / 3),
              segments=24, sides=6, arc=math.pi)
    for z, r in ((0.75, 1.19), (1.15, 0.99)):
        torus("Charging coil", r, 0.018, c + Vector((0, 0, z)), M["cyan"], segments=48, sides=6)
    cylinder("Cap", 0.18, 0.1, c + Vector((0, 0, 1.6)), (0, 0, 1), M["dark"], segments=16)
    sphere("Cap light", 0.08, c + Vector((0, 0, 1.68)), M["pink"])
    # The battery unit and its cable
    b = Vector((1.55, 2.75, 0))
    box("Battery", (0.62, 0.42, 1.05), b + Vector((0, 0, 0.525)), M["paint"], bevel=0.03)
    box("Battery window", (0.42, 0.02, 0.62), b + Vector((0, -0.215, 0.6)), M["rubber"])
    for k in range(5):
        box("Charge bar", (0.34, 0.02, 0.08), b + Vector((0, -0.225, 0.37 + k * 0.115)), M["green"] if k < 4 else M["rubber"])
    box("Battery stripe", (0.62, 0.43, 0.08), b + Vector((0, 0, 0.98)), M["hazard"])
    cable("Battery cable", [b + Vector((-0.2, -0.1, 0.15)), (1.2, 2.3, 0.05), (0.9, 2.15, 0.05), (0.7, 2.0, 0.2)], 0.05, M["rubber"])


def railing():
    """The lookout at the roof's edge: a kerb, glass panels between steel posts, a neon handrail, and a coin-op viewer.
    1.6 behind Ember, 6.2 wide, like the old rail."""
    y = 1.6
    box("Kerb", (6.5, 0.36, 0.22), (0, y + 0.08, 0.11), M["concrete"], bevel=0.02)
    for i in range(7):
        x = -3.15 + i * 1.05
        box("Post", (0.07, 0.07, 1.1), (x, y, 0.55 + 0.22), M["steel"])
        if i < 6:
            box("Glass", (0.96, 0.02, 0.78), (x + 0.525, y, 0.66), M["glass"])
    box("Handrail", (6.4, 0.1, 0.06), (0, y, 1.35), M["steel"], bevel=0.015)
    box("Handrail glow", (6.3, 0.03, 0.02), (0, y - 0.05, 1.31), M["cyan"])
    box("Lower rail", (6.3, 0.04, 0.04), (0, y, 0.28), M["steel"])
    # A coin-op viewer on a post
    v = Vector((-2.2, 1.0, 0))
    cylinder("Viewer base", 0.22, 0.06, v + Vector((0, 0, 0.03)), (0, 0, 1), M["dark"], segments=16)
    rod("Viewer post", 0.06, v + Vector((0, 0, 0.05)), v + Vector((0, 0, 1.05)), M["paint"])
    box("Viewer head", (0.42, 0.3, 0.26), v + Vector((0, 0.04, 1.2)), M["paint"], bevel=0.05)
    for dx in (-0.1, 0.1):
        cylinder("Viewer lens", 0.07, 0.18, v + Vector((dx, 0.24, 1.22)), (0, 1, 0), M["dark"], segments=12)
        cylinder("Viewer eyepiece", 0.055, 0.1, v + Vector((dx, -0.15, 1.24)), (0, 1, 0), M["rubber"], segments=12)
    box("Coin slot", (0.12, 0.02, 0.05), v + Vector((0.13, -0.11, 1.12)), M["amber"])
    # Two little floor lights
    for x in (1.4, 2.9):
        cylinder("Bollard", 0.07, 0.4, (x, 1.15, 0.2), (0, 0, 1), M["dark"], segments=10)
        cylinder("Bollard light", 0.072, 0.06, (x, 1.15, 0.36), (0, 0, 1), M["cyan"], segments=10)


def radio():
    """A chunky old boombox on a crate, with a telescopic antenna. The page lights the antenna's tip (3.9 up, 0.6 to
    the right, 1.6 back) and sends signal rings off it, so the antenna stops just below there."""
    c = Vector((0, 1.5, 0))
    box("Crate", (1.7, 1.0, 0.7), c + Vector((0, 0, 0.35)), M["wood"], bevel=0.02)
    for x in (-0.82, 0.82):
        box("Crate post", (0.06, 1.02, 0.72), c + Vector((x, 0, 0.36)), M["rust"])
    box("Small crate", (0.7, 0.7, 0.62), (-1.35, 1.35, 0.31), M["wood"], rotation=(0, 0, 0.35), bevel=0.02)
    # The boombox
    body = c + Vector((0, 0, 1.1))
    box("Boombox", (1.5, 0.6, 0.8), body, M["paint"], bevel=0.07)
    box("Front panel", (1.42, 0.02, 0.7), body + Vector((0, -0.305, -0.02)), M["dark"])
    for side in (-0.44, 0.44):
        cylinder("Speaker", 0.25, 0.03, body + Vector((side, -0.315, -0.04)), (0, -1, 0), M["rubber"], segments=32)
        cylinder("Speaker cone", 0.16, 0.1, body + Vector((side, -0.265, -0.04)), (0, 1, 0), M["dark"], segments=24, tip=0.05)
        torus("Speaker ring", 0.255, 0.018, body + Vector((side, -0.33, -0.04)), M["pink"], rotation=(math.pi / 2, 0, 0))
        sphere("Speaker cap", 0.05, body + Vector((side, -0.3, -0.04)), M["steel"], scale=(1, 0.5, 1))
    box("Cassette deck", (0.42, 0.02, 0.26), body + Vector((0, -0.32, -0.1)), M["rubber"])
    box("Cassette window", (0.3, 0.02, 0.1), body + Vector((0, -0.33, -0.08)), M["violet"])
    box("Tuning dial", (0.62, 0.02, 0.1), body + Vector((0, -0.33, 0.22)), M["amber"])
    box("Dial needle", (0.015, 0.025, 0.12), body + Vector((0.08, -0.34, 0.22)), M["red"])
    for k in range(5):
        box("Button", (0.1, 0.12, 0.05), body + Vector((-0.3 + k * 0.15, 0, 0.42)), M["steel"] if k != 2 else M["pink"])
    for x in (-0.48, 0.48):
        rod("Handle post", 0.035, body + Vector((x, 0, 0.4)), body + Vector((x, 0, 0.62)), M["chrome"])
    rod("Handle", 0.04, body + Vector((-0.5, 0, 0.62)), body + Vector((0.5, 0, 0.62)), M["chrome"])
    # The antenna, in telescopic sections
    base = Vector((0.6, 1.6, 1.5))
    for k, (length, radius) in enumerate(((0.85, 0.028), (0.8, 0.021), (0.75, 0.015))):
        top = base + Vector((0, 0, length))
        rod(f"Antenna {k + 1}", radius, base, top, M["chrome"])
        base = top - Vector((0, 0, 0.05))
    cylinder("Antenna hinge", 0.05, 0.08, (0.6, 1.6, 1.52), (1, 0, 0), M["dark"], segments=12)
    # Cassettes on the crate, and a cable down to the roof
    for k in range(3):
        box("Cassette", (0.26, 0.17, 0.03), (-0.45 + k * 0.05, 1.18, 0.715 + k * 0.032), M["dark"], rotation=(0, 0, 0.3 * k - 0.3))
        box("Cassette label", (0.2, 0.11, 0.005), (-0.45 + k * 0.05, 1.18, 0.732 + k * 0.032),
            M[("pink", "cyan", "amber")[k]], rotation=(0, 0, 0.3 * k - 0.3))
    cable("Radio cable", [(0.75, 1.8, 0.9), (0.9, 1.75, 0.75), (0.93, 1.3, 0.4), (1.1, 0.95, 0.03), (1.6, 0.8, 0.03)], 0.025, M["rubber"])
    sphere("Lamp", 0.12, (-1.35, 1.35, 0.78), M["amber"])
    cylinder("Lamp base", 0.09, 0.06, (-1.35, 1.35, 0.65), (0, 0, 1), M["dark"], segments=12)


# ---------------------------------------------------------------------------
# Roof clutter (props). Each sits on the roof around its own origin
# ---------------------------------------------------------------------------

def roof_ac():
    box("AC body", (1.7, 0.95, 1.0), (0, 0, 0.55), M["paint"], bevel=0.04)
    for x in (-0.86, 0.86):
        box("Louvres", (0.02, 0.8, 0.75), (x, 0, 0.55), M["louvres"])
    box("Front louvres", (1.4, 0.02, 0.75), (0, -0.48, 0.55), M["louvres"])
    cylinder("Fan well", 0.4, 0.02, (0.3, 0, 1.055), (0, 0, 1), M["rubber"], segments=32)
    for k in range(3):
        box("Fan blade", (0.34, 0.09, 0.012), (0.3, 0, 1.075), M["dark"], rotation=(0.3, 0, k * 2 * math.pi / 3))
    torus("Fan guard", 0.39, 0.025, (0.3, 0, 1.095), M["steel"])
    for k in range(4):
        torus("Guard ring", 0.09 * (k + 1), 0.008, (0.3, 0, 1.1), M["steel"], segments=24, sides=4)
    for x in (-0.6, 0.6):
        box("Foot", (0.12, 0.9, 0.06), (x, 0, 0.03), M["dark"])
    box("Status", (0.06, 0.02, 0.04), (-0.6, -0.49, 0.95), M["green"])
    cable("Coolant pipe", [(-0.86, 0.25, 0.5), (-1.05, 0.25, 0.5), (-1.05, 0.25, 0.08), (-1.4, 0.25, 0.08)], 0.04, M["steel"])


def roof_tank():
    for x in (-0.6, 0.6):
        for y in (-0.6, 0.6):
            rod("Tank leg", 0.06, (x, y, 0), (x * 0.9, y * 0.9, 1.6), M["rust"])
    for z in (0.5, 1.1):
        for (a, b) in (((-0.6, -0.6), (0.6, -0.6)), ((0.6, -0.6), (0.6, 0.6)), ((0.6, 0.6), (-0.6, 0.6)), ((-0.6, 0.6), (-0.6, -0.6))):
            rod("Brace", 0.03, (*a, z), (*b, z), M["rust"])
    box("Tank deck", (1.5, 1.5, 0.08), (0, 0, 1.64), M["dark"])
    cylinder("Tank", 0.9, 1.6, (0, 0, 2.48), (0, 0, 1), M["wood"], segments=24)
    for z in (1.85, 2.48, 3.1):
        torus("Hoop", 0.915, 0.025, (0, 0, z), M["rust"], segments=32, sides=6)
    cylinder("Tank roof", 0.98, 0.5, (0, 0, 3.53), (0, 0, 1), M["dark"], segments=24, tip=0.08)
    sphere("Warning light", 0.09, (0, 0, 3.86), M["red"])
    for k in range(10):  # a ladder up the front
        rod("Rung", 0.015, (-0.2, -0.95, 0.3 + k * 0.32), (0.2, -0.95, 0.3 + k * 0.32), M["steel"])
    for x in (-0.2, 0.2):
        rod("Ladder rail", 0.02, (x, -0.95, 0.1), (x, -0.95, 3.3), M["steel"])
    cable("Outflow", [(0.5, 0.5, 1.7), (0.7, 0.7, 1.2), (0.75, 0.75, 0.15), (0.75, 1.3, 0.15)], 0.06, M["steel"])


def roof_dish():
    box("Dish base", (0.8, 0.8, 0.35), (0, 0, 0.175), M["concrete"], bevel=0.03)
    rod("Dish mast", 0.07, (0, 0, 0.35), (0, 0, 1.1), M["steel"])
    dish = sphere("Dish", 1.0, (0, 0, 0), M["white"], segments=24, rings=12, bowl=True, scale=(0.75, 0.75, 0.22))
    dish.location, dish.rotation_euler = (0, 0.15, 1.5), (math.radians(60), 0, 0)
    rod("Feed arm", 0.025, (0, 0.05, 1.3), (0, -0.55, 1.75), M["steel"])
    cylinder("Feed horn", 0.06, 0.16, (0, -0.58, 1.78), (0, -0.6, 0.35), M["dark"], segments=12)
    sphere("Beacon", 0.05, (0, -0.65, 1.83), M["red"])
    cable("Dish cable", [(0, 0, 0.4), (0.3, 0.3, 0.05), (0.9, 0.5, 0.04)], 0.025, M["rubber"])


def roof_vents():
    for k, (x, y, h, r) in enumerate(((0, 0, 1.4, 0.18), (0.55, 0.25, 1.0, 0.14), (-0.45, 0.35, 0.75, 0.12))):
        cylinder("Vent pipe", r, h, (x, y, h / 2), (0, 0, 1), M["steel"], segments=16)
        cylinder("Vent cap", r * 2.1, 0.12, (x, y, h + 0.12), (0, 0, 1), M["dark"], segments=16, tip=r * 0.6)
        torus("Vent collar", r + 0.015, 0.02, (x, y, 0.1), M["rust"], segments=20, sides=6)
    box("Box vent", (0.8, 0.6, 0.5), (0.15, -0.55, 0.25), M["paint"], bevel=0.03)
    box("Box vent grille", (0.6, 0.02, 0.3), (0.15, -0.86, 0.27), M["louvres"])
    box("Vent glow", (0.6, 0.02, 0.03), (0.15, -0.87, 0.47), M["violet"])


def roof_crates():
    box("Crate", (1.0, 1.0, 0.8), (0, 0, 0.4), M["wood"], bevel=0.02)
    box("Crate", (0.9, 0.9, 0.7), (0.15, 0.05, 1.15), M["wood"], rotation=(0, 0, 0.3), bevel=0.02)
    box("Crate", (0.6, 0.6, 0.5), (-0.9, -0.3, 0.25), M["wood"], rotation=(0, 0, -0.4), bevel=0.02)
    for k, (x, y) in enumerate(((0.95, -0.55), (1.35, 0.2))):
        cylinder("Barrel", 0.3, 0.9, (x, y, 0.45), (0, 0, 1), M["rust"] if k else M["paint"], segments=20)
        for z in (0.2, 0.7):
            torus("Barrel hoop", 0.305, 0.015, (x, y, z), M["dark"], segments=24, sides=6)
        torus("Barrel stripe", 0.305, 0.03, (x, y, 0.45), M["pink"] if k == 0 else M["amber"], segments=24, sides=6)
    cylinder("Spool", 0.45, 0.5, (-0.6, 0.9, 0.45), (1, 0, 0), M["wood"], segments=20)
    torus("Spool cable", 0.3, 0.13, (-0.6, 0.9, 0.45), M["rubber"], rotation=(0, math.pi / 2, 0), segments=24, sides=8)
    box("Tarp", (0.95, 0.95, 0.04), (0.15, 0.05, 1.52), M["cushion"], rotation=(0.05, -0.04, 0.3))


def roof_pipes():
    length = 11.0
    for k, (x, z, r) in enumerate(((0, 0.42, 0.13), (0.32, 0.3, 0.08))):
        rod("Pipe", r, (x, -length / 2, z), (x, length / 2, z), M["paint"] if k == 0 else M["rust"], segments=14)
        for end in (-1, 1):
            rod("Pipe drop", r, (x, end * length / 2, z), (x, end * length / 2, 0), M["paint"] if k == 0 else M["rust"], segments=14)
            torus("Elbow", r + 0.02, 0.025, (x, end * length / 2, z), M["dark"], rotation=(math.pi / 2, 0, 0), segments=20, sides=6)
    for y in np.arange(-length / 2 + 1, length / 2, 2):
        box("Bracket", (0.6, 0.1, 0.05), (0.15, y, 0.25), M["dark"])
        for x in (-0.12, 0.42):
            box("Bracket leg", (0.05, 0.08, 0.25), (x, y, 0.125), M["dark"])
    torus("Valve wheel", 0.16, 0.025, (-0.22, 0.3, 0.42), M["red"], rotation=(0, math.pi / 2, 0), segments=24, sides=6)
    rod("Valve stem", 0.03, (-0.13, 0.3, 0.42), (-0.22, 0.3, 0.42), M["steel"])
    box("Pipe band", (0.3, 0.12, 0.3), (0, -2.5, 0.42), M["hazard"])


def roof_stairs():
    box("Stair hut", (2.2, 1.8, 2.5), (0, 0, 1.25), M["concrete"], bevel=0.02)
    box("Roof slab", (2.45, 2.05, 0.12), (0, 0, 2.56), M["dark"])
    box("Door frame", (1.0, 0.06, 2.0), (0, -0.91, 1.0), M["dark"])
    box("Door", (0.86, 0.04, 1.9), (0, -0.93, 0.97), M["paint"])
    box("Door window", (0.4, 0.02, 0.5), (0, -0.955, 1.45), M["amber"])
    box("Door handle", (0.12, 0.05, 0.03), (0.3, -0.97, 0.95), M["chrome"])
    box("Exit sign", (0.5, 0.06, 0.2), (0, -0.93, 2.2), M["dark"])
    text("EXIT", "EXIT", 0.13, (0, -0.965, 2.2), M["green"])
    box("Step", (1.2, 0.4, 0.12), (0, -1.1, 0.06), M["concrete"])
    cylinder("Wall lamp", 0.07, 0.14, (0.75, -0.95, 2.05), (0, -1, 0), M["dark"], segments=12)
    sphere("Wall lamp bulb", 0.06, (0.75, -1.02, 2.05), M["amber"])
    cylinder("Roof vent", 0.16, 0.5, (0.6, 0.4, 2.87), (0, 0, 1), M["steel"], segments=14)
    cylinder("Roof vent cap", 0.3, 0.1, (0.6, 0.4, 3.15), (0, 0, 1), M["dark"], segments=14, tip=0.1)
    box("Neon tag", (0.9, 0.02, 0.05), (-0.55, -0.91, 1.7), M["pink"], rotation=(0, 0.25, 0))
    box("Neon tag", (0.5, 0.02, 0.05), (-0.6, -0.91, 1.55), M["cyan"], rotation=(0, -0.2, 0))


BUILDINGS = {"terminal": terminal, "pod": pod, "railing": railing, "radio": radio}
PROPS = {"roof_ac": roof_ac, "roof_tank": roof_tank, "roof_dish": roof_dish, "roof_vents": roof_vents,
         "roof_crates": roof_crates, "roof_pipes": roof_pipes, "roof_stairs": roof_stairs}
PIECES = {**BUILDINGS, **PROPS}


# ---------------------------------------------------------------------------
# A stage to photograph things on (not exported), and the command-line extras
# ---------------------------------------------------------------------------

def light(name, location, rotation, colour, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.color, data.energy, data.size = colour, energy, size
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = location, rotation
    collection("Stage").objects.link(obj)


def stage():
    global piece
    piece = "Stage"
    world = bpy.data.worlds.new("Night")
    if world.node_tree is None:
        world.use_nodes = True
    next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.004, 0.005, 0.012, 1)
    scene.world = world
    light("Key", (-6, -8, 9), (math.radians(45), 0, math.radians(-35)), (0.6, 0.7, 1), 900, 6)
    light("Rim", (7, 6, 7), (math.radians(-45), 0, math.radians(130)), (1, 0.3, 0.7), 700, 6)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    collection("Stage").objects.link(camera)
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 48, True
    scene.cycles.preview_samples, scene.cycles.use_preview_denoising = 32, True
    scene.render.resolution_x = scene.render.resolution_y = 1024
    for look in ("AgX - Punchy", "Punchy"):
        try:
            scene.view_settings.view_transform, scene.view_settings.look = "AgX", look
            break
        except TypeError:
            continue
    tree = bpy.data.node_groups.new("Glow", "CompositorNodeTree")  # a soft bloom round the neon
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    layers, out, bloom = (tree.nodes.new(t) for t in ("CompositorNodeRLayers", "NodeGroupOutput", "CompositorNodeGlare"))
    bloom.inputs["Type"].default_value, bloom.inputs["Threshold"].default_value = "Bloom", 0.5
    tree.links.new(layers.outputs["Image"], bloom.inputs["Image"])
    tree.links.new(bloom.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = tree


def roof_slab(size):
    """The roof itself, for the layout and the hero shot: a dark slab, a cyan grid and neon edges, like the page's."""
    global piece
    piece = "Roof"
    box("Roof", (size, size, 0.2), (0, 0, -0.1), material("Roof", (0.06, 0.065, 0.1), roughness=0.35))
    grid = material("Grid", (0.1, 0.9, 1), emission=(0.1, 0.9, 1), strength=0.35)
    for k in range(-int(size // 2) + 1, int(size // 2), 2):
        box("Grid line", (size, 0.015, 0.002), (0, k, 0.001), grid)
        box("Grid line", (0.015, size, 0.002), (k, 0, 0.001), grid)
    for i, colour in enumerate(("pink", "cyan", "cyan", "pink")):
        a = i * math.pi / 2
        box("Edge", (size, 0.08, 0.08), (math.sin(a) * size / 2, -math.cos(a) * size / 2, 0.04), M[colour], rotation=(0, 0, a))


def frame(camera, objects, around=35, down=24, margin=1.25):
    """Point an orthographic camera at these objects from the front-right and above, filling the picture."""
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    high = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    centre, size = (low + high) / 2, (high - low).length
    a, d = math.radians(around), math.radians(down)
    camera.data.type, camera.data.ortho_scale = "ORTHO", size * margin
    camera.location = centre + Vector((math.sin(a) * math.cos(d), -math.cos(a) * math.cos(d), math.sin(d))) * 40
    camera.rotation_euler = (math.pi / 2 - d, 0, a)


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


def join_by_material(name):
    """One mesh per material (fewer draw calls on the page). CodeScreen keeps its name: the page looks for it."""
    groups = {}
    for obj in collection(name).objects:
        if obj.type == "MESH" and obj.name != "CodeScreen":
            groups.setdefault(obj.active_material.name, []).append(obj)
    for objs in groups.values():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs,
                                           selected_editable_objects=objs):
                bpy.ops.object.join()


def export(name, path):
    for obj in scene.objects:
        obj.select_set(obj.users_collection[0].name == name)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
                              export_lights=False, export_cameras=False, export_yup=True,
                              export_draco_mesh_compression_enable=True)


def show_only(names):
    for c in bpy.data.collections:
        c.hide_render = c.name not in names and c.name != "Stage"


def place(name, x, z, rotation_deg=0.0):
    """Move a finished piece to where it is on the page's roof (the page's x, z become Blender's x, -y)."""
    holder = bpy.data.objects.new(f"{name} (on the roof)", None)
    collection(name).objects.link(holder)
    for obj in collection(name).objects:
        if obj is not holder:
            obj.parent = holder
    holder.location, holder.rotation_euler = (x, -z, 0), (0, 0, math.radians(rotation_deg))


def import_model(path, x, z):
    """Bring in one of the other Blender-made buildings, sized and placed the way the page does it."""
    global piece
    piece = path.stem
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
    except RuntimeError as error:
        print("Couldn't import", path.name, error)
        return
    new = [o for o in bpy.data.objects if o not in before]
    for obj in new:
        for c in obj.users_collection:
            c.objects.unlink(obj)
        collection(piece).objects.link(obj)
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    if not corners:
        return
    width = max(max(c.x for c in corners) - min(c.x for c in corners), max(c.y for c in corners) - min(c.y for c in corners))
    holder = bpy.data.objects.new(f"{piece} (on the roof)", None)
    collection(piece).objects.link(holder)
    for obj in new:
        if obj.parent is None:
            obj.parent = holder
    holder.scale = (3.2 / max(width, 1e-3),) * 3
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    cx = (max(c.x for c in corners) + min(c.x for c in corners)) / 2
    cy = (max(c.y for c in corners) + min(c.y for c in corners)) / 2
    holder.location = (x - cx, -(z - 1.8) - cy, -min(c.z for c in corners))


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
    global piece
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="save a preview of each piece in rooftop/")
    parser.add_argument("--export", action="store_true", help="save each piece to ../site/models/")
    parser.add_argument("--only", choices=list(PIECES), help="build just this one")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    clear()
    make_materials()
    stage()
    if args.render:
        print("Rendering on", use_gpu())
    names = [args.only] if args.only else list(PIECES)
    for name in names:
        piece = name
        PIECES[name]()
        join_by_material(name)
        if args.export:
            export(name, SITE / "models" / f"{name}.glb")
        if args.render:
            show_only({name})
            bpy.context.view_layer.update()
            frame(scene.camera, [o for o in collection(name).objects if o.type == "MESH"])
            scene.render.filepath = str(HERE / "rooftop" / f"{name}.png")
            bpy.ops.render.render(write_still=True)
    if args.only:
        return
    # The whole roof, laid out as on the page
    layout = json.loads((HERE.parent / "buildings.json").read_text(encoding="utf-8"))
    scenery = json.loads((SITE / "scenery.json").read_text(encoding="utf-8"))
    roof_slab(scenery.get("roof", {}).get("size", 24))
    placed = set()
    for b in layout["buildings"]:
        x, z = b["pos"]
        if b.get("model") in BUILDINGS and b["model"] not in placed:
            place(b["model"], x, z, b.get("rotation", 0))
            placed.add(b["model"])
        elif str(b.get("model", "")).endswith(".glb"):
            import_model(SITE / b["model"], x, z)
    for p in scenery.get("props", []):
        name = Path(p.get("model", "")).stem
        if name not in PROPS:
            continue
        if name in placed:  # used twice (the air conditioners): place a copy
            piece = f"{name} {p['id']}"
            for obj in bpy.data.collections[name].objects:
                if obj.type == "MESH":
                    twin = obj.copy()
                    twin.parent = None
                    collection(piece).objects.link(twin)
            name = piece
        place(name, p["pos"][0], p["pos"][2], p.get("rotation", 0))
        placed.add(name)
    show_only({c.name for c in bpy.data.collections})
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "rooftop.blend"))
    if args.render:
        camera = scene.camera
        camera.data.type, camera.data.lens = "PERSP", 26
        camera.location, camera.rotation_euler = (15, -19, 13), (math.radians(60), 0, math.radians(38))
        scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
        scene.render.filepath = str(HERE / "rooftop.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":  # city.py borrows the building blocks above
    main()
