"""
bulletin_board.py - the rooftop's bulletin board, where notes for Ember and Vega get pinned. Built entirely from code.

In Blender: Scripting tab -> Open -> this file -> Run Script. It clears the scene and builds the board.
From a terminal it can also render previews and export the model for Ember's roof:
  blender -b -P bulletin_board.py -- --render --export
That saves bulletin_board.blend and two preview pictures next to this file, and ../site/models/bulletin_board.glb.
"""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

SCRIPT = Path(globals().get("__file__", ""))
HERE = SCRIPT.resolve().parent if SCRIPT.is_file() else Path.cwd()
BOARD_Z, BOARD_W, BOARD_H = 1.55, 3.0, 1.5  # the cork: its middle, width and height
FRONT = -0.09  # the cork's face; the board faces -Y, which Ember's builder turns towards the viewer
rng = np.random.default_rng(3)
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


def cork(w=256, h=128):
    base = np.array((0.42, 0.27, 0.15)) * (0.8 + 0.4 * rng.random((h, w, 1)))
    for _ in range(300):  # darker flecks
        y, x = rng.integers(0, h), rng.integers(0, w)
        base[y:y + 2, x:x + 2] *= 0.6
    return base


def paper(colour, w=96, h=96, lines=5):
    img = np.empty((h, w, 3))
    img[:] = colour
    for i in range(lines):  # scribbled lines of writing
        y = 18 + i * 13
        img[y:y + 3, 10:10 + rng.integers(30, 76)] = np.array(colour) * 0.35
    return img * (1 - 0.05 * rng.random((h, w, 1)))


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


NOTE_COLOURS = [(1.0, 0.93, 0.55), (0.62, 0.95, 1.0), (1.0, 0.7, 0.85), (0.75, 1.0, 0.7), (1.0, 0.85, 0.6)]


def make_materials():
    M["cork"] = material("Cork", image=make_image("Cork", cork()), roughness=0.9)
    M["wood"] = material("Frame", (0.16, 0.1, 0.06), roughness=0.6)
    M["metal"] = material("Dark metal", (0.035, 0.038, 0.05), metallic=0.6, roughness=0.45)
    M["steel"] = material("Steel", (0.3, 0.32, 0.36), metallic=0.8, roughness=0.35)
    M["slab"] = material("Slab", (0.12, 0.12, 0.13), roughness=0.85)
    for i, colour in enumerate(NOTE_COLOURS):
        M[f"note{i}"] = material(f"Note {i + 1}", image=make_image(f"Note {i + 1}", paper(colour)), roughness=0.8)
    M["cyan"] = material("Neon cyan", (0.05, 0.45, 0.5), emission=(0.1, 0.9, 1), strength=3.0)
    M["warm"] = material("Warm light", (1, 0.72, 0.4), emission=(1, 0.72, 0.4), strength=3.0)
    M["red"] = material("Pin red", (0.8, 0.05, 0.08), roughness=0.3)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def collection(name):
    found = bpy.data.collections.get(name)
    if not found:
        found = bpy.data.collections.new(name)
        scene.collection.children.link(found)
    return found


def add(name, mesh, mat, location, rotation=(0, 0, 0), group="Board"):
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


def sphere(name, radius, location, mat):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=6, radius=radius)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add(name, mesh, mat, location)


def picture(name, width, height, location, mat, tilt=0.0):
    """A flat picture facing -Y, turned a little about Y so pinned notes sit crooked."""
    mesh = bpy.data.meshes.new(name)
    w, h = width / 2, height / 2
    mesh.from_pydata([(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = uv
    return add(name, mesh, mat, location, (0, tilt, 0))


def text(name, body, size, location, mat):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.align_x, curve.align_y, curve.extrude = body, size, "CENTER", "CENTER", 0.015
    font = Path(r"C:\Windows\Fonts\bahnschrift.ttf")
    if font.exists():
        curve.font = bpy.data.fonts.load(str(font), check_existing=True)
    obj = bpy.data.objects.new(name, curve)
    collection("Board").objects.link(obj)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)
    return add(name, mesh, mat, location, (math.pi / 2, 0, 0))


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

def build():
    box("Slab", (4.2, 1.8, 0.1), (0, -0.3, 0.05), M["slab"])
    for x in (-1.65, 1.65):
        box("Post", (0.12, 0.12, 2.75), (x, 0, 0.1 + 1.375), M["steel"])
    box("Frame", (BOARD_W + 0.16, 0.12, BOARD_H + 0.16), (0, 0, BOARD_Z), M["wood"])
    picture("Cork", BOARD_W, BOARD_H, (0, FRONT + 0.03, BOARD_Z), M["cork"])

    # An awning with a strip light underneath, and NOTICES in neon on top
    box("Awning", (3.7, 0.7, 0.06), (0, -0.25, 2.62), M["metal"], rotation=(math.radians(-12), 0, 0))
    box("Awning light", (3.0, 0.04, 0.03), (0, -0.48, 2.55), M["warm"])
    box("Sign backing", (2.1, 0.08, 0.42), (0, 0.02, 3.0), M["metal"])
    text("NOTICES", "NOTICES", 0.3, (0, -0.04, 3.0), M["cyan"])

    # Notes pinned up all over it, at odd angles
    spots = [(-1.1, 1.9), (-0.45, 2.0), (0.3, 1.95), (1.05, 1.85), (-0.85, 1.25), (-0.1, 1.2), (0.75, 1.3), (1.2, 1.05)]
    for i, (x, z) in enumerate(spots):
        size = 0.42 + 0.1 * rng.random()
        picture(f"Pinned note {i + 1}", size, size, (x, FRONT + 0.02 - 0.002 * i, z), M[f"note{i % len(NOTE_COLOURS)}"],
                tilt=rng.uniform(-0.18, 0.18))
        sphere("Pin", 0.025, (x, FRONT - 0.005, z + size / 2 - 0.05), M["red"] if i % 3 else M["cyan"])


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
    light("Under the awning", (0, -0.6, 2.4), (0, 0, 0), (1, 0.75, 0.45), 40, 2.5)
    light("Key", (-3, -4, 4), (math.radians(50), 0, math.radians(-35)), (0.6, 0.7, 1), 150, 3)
    light("Rim", (3, 2, 4), (math.radians(-45), 0, math.radians(130)), (1, 0.3, 0.7), 120, 3)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.type, camera.data.ortho_scale = "ORTHO", 5.2
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
    target, distance = (0, 0, 1.6), 30
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
    for obj in collection("Board").objects:
        groups.setdefault(obj.active_material.name, []).append(obj)
    for objs in groups.values():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs,
                                           selected_editable_objects=objs):
                bpy.ops.object.join()
    for obj in scene.objects:
        obj.select_set(obj.users_collection[0].name == "Board")
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
    parser.add_argument("--export", action="store_true", help="save ../site/models/bulletin_board.glb for Ember")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    clear()
    make_materials()
    build()
    stage()
    if args.render or args.export:
        bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "bulletin_board.blend"))
    if args.render:
        print("Rendering on", use_gpu())
        for view in VIEWS:
            aim(scene.camera, view)
            scene.render.filepath = str(HERE / f"bulletin_board_{view}.png")
            bpy.ops.render.render(write_still=True)
    if args.export:
        export(HERE.parent / "site" / "models" / "bulletin_board.glb")


main()
