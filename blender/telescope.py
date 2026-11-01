"""
telescope.py - a telescope on a little round deck in the corner of Ember's roof. Built entirely from code.

In Blender: Scripting tab -> Open -> this file -> Run Script. It clears the scene and builds the telescope.
From a terminal it can also render previews and export the model for Ember's roof:
  blender -b -P telescope.py -- --render --export
That saves telescope.blend and two preview pictures next to this file, and ../site/models/telescope.glb.
"""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

SCRIPT = Path(globals().get("__file__", ""))
HERE = SCRIPT.resolve().parent if SCRIPT.is_file() else Path.cwd()
DECK_R, DECK_H = 1.5, 0.12  # the round deck: its radius and height
PIVOT = Vector((0, 0.05, 1.2))  # where the tube turns on its mount
UP, ROUND = math.radians(38), math.radians(115)  # the tube: how far it leans off straight up, and which way round
rng = np.random.default_rng(5)
scene = bpy.context.scene
M = {}


# ---------------------------------------------------------------------------
# Pictures and materials
# ---------------------------------------------------------------------------

def make_image(name, rgb):
    h, w, _ = rgb.shape
    image = bpy.data.images.new(name, w, h)
    image.pixels.foreach_set(np.flipud(np.concatenate([np.clip(rgb, 0, 1), np.ones((h, w, 1))], axis=2)).astype(np.float32).ravel())
    image.pack()
    return image


def star_chart(w=192, h=144):
    """Navy paper with stars dotted on it, a few joined up into constellations."""
    img = np.empty((h, w, 3))
    img[:] = (0.04, 0.07, 0.2)
    img[[8, -9], 8:-8] = img[8:-8, [8, -9]] = (0.5, 0.6, 0.8)  # a thin border
    stars = rng.integers((14, 14), (h - 14, w - 14), size=(60, 2))
    for figure in (stars[:5], stars[5:9], stars[9:13]):
        for (y0, x0), (y1, x1) in zip(figure, figure[1:]):
            for t in np.linspace(0, 1, 60):
                img[int(y0 + (y1 - y0) * t), int(x0 + (x1 - x0) * t)] = (0.35, 0.55, 0.85)
    for i, (y, x) in enumerate(stars):
        size = 2 if i < 13 or i % 4 == 0 else 1
        img[y - size // 2:y + size - size // 2 + 1, x - size // 2:x + size - size // 2 + 1] = (1, 0.97, 0.85)
    return img


def planks(w=128, h=128):
    base = np.array((0.2, 0.13, 0.08)) * (0.85 + 0.3 * rng.random((h, w, 1)))
    base[::16] *= 0.45  # gaps between the boards
    return base


def material(name, colour=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.6, emission=None, strength=0.0, image=None):
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
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    mat.diffuse_color = (*(emission or colour), 1)
    return mat


def make_materials():
    M["deck"] = material("Deck", image=make_image("Planks", planks()), roughness=0.75)
    M["tube"] = material("Tube", (0.85, 0.86, 0.88), metallic=0.3, roughness=0.25)
    M["black"] = material("Black", (0.02, 0.02, 0.025), metallic=0.4, roughness=0.4)
    M["brass"] = material("Brass", (0.75, 0.55, 0.22), metallic=1.0, roughness=0.3)
    M["steel"] = material("Steel", (0.3, 0.32, 0.36), metallic=0.8, roughness=0.35)
    M["crate"] = material("Crate", (0.3, 0.2, 0.11), roughness=0.8)
    M["canvas"] = material("Canvas", (0.12, 0.2, 0.32), roughness=0.9)
    M["chart"] = material("Star chart", image=make_image("Star chart", star_chart()), roughness=0.8)
    M["lens"] = material("Lens", (0.1, 0.25, 0.6), emission=(0.3, 0.55, 1), strength=1.5)
    M["cyan"] = material("Neon cyan", (0.05, 0.45, 0.5), emission=(0.1, 0.9, 1), strength=3.0)
    M["red"] = material("Red lamp", (1, 0.1, 0.08), emission=(1, 0.12, 0.08), strength=4.0)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def collection(name):
    found = bpy.data.collections.get(name)
    if not found:
        found = bpy.data.collections.new(name)
        scene.collection.children.link(found)
    return found


def add(name, mesh, mat, location, rotation=(0, 0, 0), group="Telescope"):
    if mat:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler = location, rotation
    collection(group).objects.link(obj)
    return obj


def box(name, size, location, mat, rotation=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add(name, mesh, mat, location, rotation)


def cylinder(name, radius, length, middle, direction, mat, segments=16, tip=None):
    """A cylinder (or a cone, with tip=its far radius) along direction, centred on middle."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius if tip is None else tip, depth=length, calc_uvs=True)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add(name, mesh, mat, Vector(middle), Vector(direction).to_track_quat("Z", "Y").to_euler())


def rod(name, radius, start, end, mat, segments=8):
    start, end = Vector(start), Vector(end)
    return cylinder(name, radius, (end - start).length, (start + end) / 2, end - start, mat, segments)


def picture(name, width, height, location, mat, lean=0.0):
    """A flat picture facing -Y, leaning back by lean."""
    mesh = bpy.data.meshes.new(name)
    w, h = width / 2, height / 2
    mesh.from_pydata([(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = uv
    return add(name, mesh, mat, location, (-lean, 0, 0))


def text(name, body, size, location, mat):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.align_x, curve.align_y, curve.extrude = body, size, "CENTER", "CENTER", 0.015
    font = Path(r"C:\Windows\Fonts\bahnschrift.ttf")
    if font.exists():
        curve.font = bpy.data.fonts.load(str(font), check_existing=True)
    obj = bpy.data.objects.new(name, curve)
    collection("Telescope").objects.link(obj)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)
    return add(name, mesh, mat, location, (math.pi / 2, 0, 0))


# ---------------------------------------------------------------------------
# The telescope
# ---------------------------------------------------------------------------

def build():
    # A round deck with a neon strip round its edge
    cylinder("Deck", DECK_R, DECK_H, (0, 0, DECK_H / 2), (0, 0, 1), M["deck"], segments=8)
    corners = [Vector((math.cos(a), math.sin(a), 0)) * (DECK_R - 0.03) + Vector((0, 0, DECK_H + 0.01))
               for a in np.linspace(0, 2 * math.pi, 9) + math.pi / 8]
    for i, (a, b) in enumerate(zip(corners, corners[1:])):
        rod(f"Deck neon {i + 1}", 0.018, a, b, M["cyan"], segments=6)

    # A tripod with a tray between its legs
    hub = PIVOT - Vector((0, 0, 0.18))
    feet = [Vector((math.cos(a) * 0.62, math.sin(a) * 0.62 + 0.05, DECK_H)) for a in (math.pi / 2, math.pi * 7 / 6, -math.pi / 6)]
    for i, foot in enumerate(feet):
        rod(f"Leg {i + 1}", 0.028, hub, foot, M["steel"])
        rod(f"Brace {i + 1}", 0.012, hub.lerp(foot, 0.55), hub.lerp(feet[i - 1], 0.55), M["steel"], segments=6)
    cylinder("Hub", 0.09, 0.12, hub, (0, 0, 1), M["black"])
    box("Mount", (0.16, 0.2, 0.22), PIVOT - Vector((0, 0, 0.06)), M["black"])

    # The tube, leaning up and away, with a dew shield, a brass band, a finder, and an eyepiece at the low end
    along = Vector((math.sin(UP) * math.sin(ROUND), -math.sin(UP) * math.cos(ROUND), math.cos(UP)))
    over = Vector((-math.cos(UP) * math.sin(ROUND), math.cos(UP) * math.cos(ROUND), math.sin(UP)))  # the tube's "up" side
    middle = PIVOT + over * 0.17
    cylinder("Tube", 0.13, 1.5, middle + along * 0.1, along, M["tube"], segments=20)
    cylinder("Dew shield", 0.155, 0.42, middle + along * 0.95, along, M["black"], segments=20)
    cylinder("Lens", 0.135, 0.01, middle + along * 1.15, along, M["lens"], segments=20)
    cylinder("Band", 0.142, 0.08, middle + along * 0.35, along, M["brass"], segments=20)
    cylinder("Band", 0.142, 0.05, middle - along * 0.5, along, M["brass"], segments=20)
    cylinder("Back", 0.1, 0.2, middle - along * 0.73, along, M["black"])
    for t in (-0.15, 0.2):
        rod("Finder foot", 0.015, middle + along * t + over * 0.12, middle + along * t + over * 0.21, M["black"], segments=6)
    cylinder("Finder", 0.035, 0.42, middle + along * 0.03 + over * 0.23, along, M["tube"], segments=10)
    back = middle - along * 0.82
    rod("Diagonal", 0.035, back, back + Vector((0, 0, 0.14)), M["black"])
    cylinder("Eyepiece", 0.03, 0.08, back + Vector((0, 0, 0.18)), (0, 0, 1), M["brass"], segments=10)
    rod("Counterweight shaft", 0.018, PIVOT, PIVOT - over * 0.55, M["steel"])
    cylinder("Counterweight", 0.09, 0.08, PIVOT - over * 0.5, over, M["black"])

    # A camp stool by the eyepiece
    seat = Vector((back.x - 0.05, back.y - 0.45, 0.6))
    cylinder("Stool seat", 0.17, 0.05, seat, (0, 0, 1), M["canvas"])
    for i, a in enumerate((0.3, 2.4, 4.5)):
        rod(f"Stool leg {i + 1}", 0.015, seat, seat + Vector((math.cos(a) * 0.18, math.sin(a) * 0.18, DECK_H - seat.z)), M["steel"])

    # A crate with a red lamp (it keeps eyes used to the dark), a flask, and a star chart leaning on it
    crate = Vector((-1.05, 0.25, DECK_H + 0.22))
    box("Crate", (0.5, 0.42, 0.44), crate, M["crate"], rotation=(0, 0, 0.2))
    box("Lamp", (0.12, 0.1, 0.1), crate + Vector((-0.1, 0, 0.27)), M["black"], rotation=(0, 0, 0.2))
    box("Lamp glass", (0.1, 0.02, 0.07), crate + Vector((-0.11, -0.055, 0.27)), M["red"], rotation=(0, 0, 0.2))
    cylinder("Flask", 0.045, 0.24, crate + Vector((0.13, 0.05, 0.34)), (0, 0, 1), M["steel"], segments=12)
    picture("Chart", 0.46, 0.34, crate + Vector((0.02, -0.28, -0.03)), M["chart"], lean=0.3)

    # LOOK UP in neon on a post at the back
    post = Vector((-0.75, 0.95, 0))
    rod("Sign post", 0.035, post + Vector((0, 0, DECK_H)), post + Vector((0, 0, 1.75)), M["steel"])
    box("Sign backing", (1.05, 0.06, 0.32), post + Vector((0, 0, 1.85)), M["black"])
    text("LOOK UP", "LOOK UP", 0.22, post + Vector((0, -0.04, 1.85)), M["cyan"])


# ---------------------------------------------------------------------------
# A stage to photograph it on (not exported), and the command-line extras
# ---------------------------------------------------------------------------

def light(name, location, rotation, colour, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.color, data.energy, data.size = colour, energy, size
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = location, rotation
    collection("Stage").objects.link(obj)


def stage():
    ground = material("Wet roof", (0.012, 0.014, 0.02), roughness=0.15)
    mesh = bpy.data.meshes.new("Ground")
    mesh.from_pydata([(-20, -20, 0), (20, -20, 0), (20, 20, 0), (-20, 20, 0)], [], [(0, 1, 2, 3)])
    add("Ground", mesh, ground, (0, 0, -0.001), group="Stage")
    world = bpy.data.worlds.new("Night")
    if world.node_tree is None:
        world.use_nodes = True
    next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
    scene.world = world
    light("Key", (-3, -4, 4), (math.radians(50), 0, math.radians(-35)), (0.6, 0.7, 1), 150, 3)
    light("Rim", (3, 2, 4), (math.radians(-45), 0, math.radians(130)), (1, 0.3, 0.7), 120, 3)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.type, camera.data.ortho_scale = "ORTHO", 4.4
    collection("Stage").objects.link(camera)
    scene.camera = camera
    aim(camera, "iso")
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 64, True
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


VIEWS = {"iso": (35, 20), "front": (0, 4)}  # how far round and down (degrees)


def aim(camera, view):
    around, down = (math.radians(a) for a in VIEWS[view])
    target, distance = (0, 0, 1.0), 30
    camera.location = (math.sin(around) * math.cos(down) * distance, -math.cos(around) * math.cos(down) * distance,
                       target[2] + math.sin(down) * distance)
    camera.rotation_euler = (math.pi / 2 - down, 0, around)


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


def export(path):
    """One mesh per material (fewer draw calls for Ember's 3D view), then a .glb with no lights or camera."""
    groups = {}
    for obj in collection("Telescope").objects:
        groups.setdefault(obj.active_material.name, []).append(obj)
    for objs in groups.values():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs,
                                           selected_editable_objects=objs):
                bpy.ops.object.join()
    for obj in scene.objects:
        obj.select_set(obj.users_collection[0].name == "Telescope")
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
                              export_lights=False, export_cameras=False, export_yup=True,
                              export_draco_mesh_compression_enable=True)


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
    parser.add_argument("--export", action="store_true", help="save ../site/models/telescope.glb for Ember")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    clear()
    make_materials()
    build()
    stage()
    if args.render or args.export:
        bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "telescope.blend"))
    if args.render:
        print("Rendering on", use_gpu())
        for view in VIEWS:
            aim(scene.camera, view)
            scene.render.filepath = str(HERE / f"telescope_{view}.png")
            bpy.ops.render.render(write_still=True)
    if args.export:
        export(HERE.parent / "site" / "models" / "telescope.glb")


main()
