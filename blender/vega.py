"""
vega.py - Vega, Ember's friend: a little old trading bot on treads, built entirely from code.

In Blender: Scripting tab -> Open -> this file -> Run Script. It clears the scene and builds Vega.
From a terminal it can also render previews and export the model the site uses:
  blender -b -P vega.py -- --render --export
That saves vega.blend and two preview pictures next to this file, and ../site/models/vega.glb.

The site moves Vega about and animates it, so a few parts keep their names in the .glb:
Head (turns to look at Ember), ArmL and ArmR (wave when it talks), Face (the live amber screen)
and Tip (the antenna light, which blinks). Vega faces -Y, which the site turns towards the viewer.
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
NECK = 0.72  # where the head turns
SHOULDER = 0.56
scene = bpy.context.scene
M = {}


# ---------------------------------------------------------------------------
# Materials (plain Principled BSDF, so they export to glTF as they look here)
# ---------------------------------------------------------------------------

def face_picture(w=256, h=192):
    """Its resting face, for pictures made here. On the site a live face is drawn over it."""
    img = np.zeros((h, w, 3))
    img[:] = (0.1, 0.05, 0.0)
    amber = (1.0, 0.69, 0.18)
    y, x = np.ogrid[:h, :w]
    for cx in (80, 176):
        img[(abs(x - cx) < 15) & (abs(y - 78) < 22)] = amber  # eyes
    smile = (abs(np.hypot(x - 128, y - 90) - 52) < 5) & (y > 118) & (abs(x - 128) < 40)
    img[smile] = amber
    img[::4] *= 0.6  # scan lines
    rgba = np.concatenate([img, np.ones((h, w, 1))], axis=2)
    image = bpy.data.images.new("Vega face", w, h)
    image.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
    image.pack()
    return image


def material(name, colour=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.5, emission=None, strength=0.0, image=None):
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
        links.new(texture.outputs["Color"], bsdf.inputs["Emission Color"])
    elif emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    mat.diffuse_color = (*(emission or colour), 1)
    return mat


def make_materials():
    M["casing"] = material("Vega casing", (0.72, 0.65, 0.5), roughness=0.45)  # old cream plastic, yellowed
    M["metal"] = material("Vega metal", (0.12, 0.13, 0.16), metallic=0.7, roughness=0.35)
    M["rubber"] = material("Vega rubber", (0.03, 0.03, 0.035), roughness=0.85)
    M["steel"] = material("Vega steel", (0.55, 0.57, 0.6), metallic=0.9, roughness=0.3)
    M["bezel"] = material("Vega bezel", (0.035, 0.035, 0.045), roughness=0.3)
    M["face"] = material("Vega face", image=face_picture(), strength=2.0)
    M["amber"] = material("Vega amber", (1, 0.6, 0.15), emission=(1, 0.62, 0.15), strength=3.0)
    M["red"] = material("Vega red", (1, 0.1, 0.1), emission=(1, 0.08, 0.1), strength=4.0)
    M["gold"] = material("Vega gold", (1, 0.74, 0.3), metallic=1.0, roughness=0.25)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def collection(name):
    found = bpy.data.collections.get(name)
    if not found:
        found = bpy.data.collections.new(name)
        scene.collection.children.link(found)
    return found


def add(name, mesh, mat, location, rotation=(0, 0, 0), parent=None, group="Vega"):
    if mat:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler = location, rotation
    obj.parent = parent
    collection(group).objects.link(obj)
    return obj


def empty(name, location, parent=None):
    """A pivot the site turns: the head, or an arm at its shoulder."""
    obj = bpy.data.objects.new(name, None)
    obj.location, obj.empty_display_size = location, 0.1
    obj.parent = parent
    collection("Vega").objects.link(obj)
    return obj


def box(name, size, location, mat, round_by=0.0, rotation=(0, 0, 0), parent=None):
    """A box, with its edges rounded off a little so Vega looks soft and old."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x, v.co.y, v.co.z = v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]
    if round_by:
        bmesh.ops.bevel(bm, geom=bm.verts[:] + bm.edges[:], offset=round_by, segments=3, profile=0.5, affect="EDGES",
                        clamp_overlap=True)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if round_by:
        for face in mesh.polygons:
            face.use_smooth = True
    return add(name, mesh, mat, location, rotation, parent)


def cylinder(name, radius, depth, location, mat, rotation=(0, 0, 0), top=None, segments=20, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius if top is None else top, depth=depth)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for face in mesh.polygons:
        face.use_smooth = abs(face.normal.z) < 0.5
    return add(name, mesh, mat, location, rotation, parent)


def sphere(name, radius, location, mat, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=radius)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for face in mesh.polygons:
        face.use_smooth = True
    return add(name, mesh, mat, location, parent=parent)


def picture(name, width, height, location, mat, parent=None):
    """A flat picture facing -Y."""
    mesh = bpy.data.meshes.new(name)
    w, h = width / 2, height / 2
    mesh.from_pydata([(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = uv
    return add(name, mesh, mat, location, parent=parent)


def label(name, body, size, location, mat, parent=None):
    """Raised letters facing -Y, turned into an ordinary mesh."""
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.align_x, curve.align_y = body, size, "CENTER", "CENTER"
    curve.extrude = 0.004
    font = Path(r"C:\Windows\Fonts\bahnschrift.ttf")
    if font.exists():
        curve.font = bpy.data.fonts.load(str(font), check_existing=True)
    obj = bpy.data.objects.new(name, curve)
    collection("Vega").objects.link(obj)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)
    return add(name, mesh, mat, location, (math.pi / 2, 0, 0), parent)


# ---------------------------------------------------------------------------
# Vega
# ---------------------------------------------------------------------------

def build():
    # Treads: two rubber tracks with steel wheels peeping out of the sides
    for side in (-1, 1):
        x = side * 0.23
        box("Tread", (0.13, 0.52, 0.15), (x, 0, 0.085), M["rubber"], round_by=0.045)
        for y in (-0.17, 0, 0.17):
            cylinder("Wheel", 0.055, 0.02, (x + side * 0.07, y, 0.085), M["steel"], rotation=(0, math.pi / 2, 0), segments=16)
    box("Axle plate", (0.36, 0.36, 0.05), (0, 0, 0.18), M["metal"])

    # Body: a gunmetal box with a cream lid, a row of amber lights, its badge and a coin slot
    box("Body", (0.5, 0.36, 0.38), (0, 0, 0.39), M["metal"], round_by=0.05)
    box("Body lid", (0.52, 0.38, 0.05), (0, 0, 0.585), M["casing"], round_by=0.02)
    for i, x in enumerate((-0.12, -0.04, 0.04, 0.12)):
        box("Chest light", (0.05, 0.02, 0.025), (x, -0.183, 0.49), M["amber"] if i != 2 else M["red"])
    label("Badge", "VEGA-7", 0.06, (0, -0.184, 0.4), M["amber"])
    box("Coin slot", (0.09, 0.01, 0.012), (0, -0.183, 0.31), M["bezel"])
    cylinder("Neck", 0.05, 0.1, (0, 0, NECK - 0.06), M["steel"], segments=12)

    # Head: an old CRT monitor, cream plastic around a dark bezel, the face on its screen
    head = empty("Head", (0, 0, NECK))
    box("Monitor", (0.66, 0.4, 0.5), (0, 0, 0.27), M["casing"], round_by=0.07, parent=head)
    box("Monitor back", (0.46, 0.22, 0.36), (0, 0.24, 0.27), M["casing"], round_by=0.06, parent=head)
    box("Bezel", (0.56, 0.02, 0.4), (0, -0.2, 0.27), M["bezel"], round_by=0.01, parent=head)
    picture("Face", 0.5, 0.34, (0, -0.212, 0.27), M["face"], parent=head)
    for i, z in enumerate((0.12, 0.2)):
        cylinder("Knob", 0.022, 0.03, (0.3, -0.12, z), M["metal"], rotation=(math.pi / 2, 0, 0), segments=12, parent=head)
    for x in (-0.12, -0.04, 0.04, 0.12):
        box("Vent", (0.05, 0.16, 0.012), (x, 0.06, 0.52), M["metal"], parent=head)
    cylinder("Antenna", 0.008, 0.3, (0.2, 0.06, 0.66), M["steel"], segments=6, parent=head)
    sphere("Tip", 0.03, (0.2, 0.06, 0.82), M["red"], parent=head)

    # Arms, pivoting at the shoulders, with little claws; the right one holds its lucky coin
    for side, name in ((-1, "ArmL"), (1, "ArmR")):
        arm = empty(name, (side * 0.27, 0, SHOULDER))
        cylinder("Shoulder", 0.045, 0.05, (side * 0.02, 0, 0), M["steel"], rotation=(0, math.pi / 2, 0), segments=12, parent=arm)
        cylinder("Arm", 0.028, 0.24, (side * 0.045, -0.02, -0.12), M["metal"], rotation=(0.2, -side * 0.15, 0), segments=10, parent=arm)
        for dx in (-0.025, 0.025):
            box("Claw", (0.015, 0.05, 0.03), (side * 0.065 + dx, -0.06, -0.25), M["steel"], parent=arm)
        if side == 1:
            cylinder("Lucky coin", 0.035, 0.008, (side * 0.065, -0.09, -0.25), M["gold"], rotation=(math.pi / 2, 0, 0), segments=20,
                     parent=arm)


# ---------------------------------------------------------------------------
# A stage to photograph it on (not exported)
# ---------------------------------------------------------------------------

def light(name, kind, location, rotation, colour, energy, size=1.0):
    data = bpy.data.lights.new(name, kind)
    data.color, data.energy = colour, energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = location, rotation
    collection("Stage").objects.link(obj)


def stage():
    ground = material("Wet roof", (0.012, 0.014, 0.02), roughness=0.15)
    mesh = bpy.data.meshes.new("Ground")
    mesh.from_pydata([(-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0)], [], [(0, 1, 2, 3)])
    add("Ground", mesh, ground, (0, 0, -0.001), group="Stage")
    world = bpy.data.worlds.new("Night")
    if world.node_tree is None:
        world.use_nodes = True
    next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
    scene.world = world
    light("Key", "AREA", (-1.2, -1.6, 1.8), (math.radians(55), 0, math.radians(-35)), (0.75, 0.8, 1), 60, 1.2)
    light("Rim", "AREA", (1.0, 1.2, 1.6), (math.radians(-50), 0, math.radians(140)), (1, 0.3, 0.7), 80, 1.0)
    light("Glow", "AREA", (0.3, -0.9, 0.9), (math.radians(80), 0, 0), (1, 0.62, 0.2), 8, 0.5)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.lens = 70
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
    glow()


def glow():
    """A soft bloom around the lights, in renders and the rendered 3D view."""
    tree = bpy.data.node_groups.new("Glow", "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    layers, out, bloom = (tree.nodes.new(t) for t in ("CompositorNodeRLayers", "NodeGroupOutput", "CompositorNodeGlare"))
    bloom.inputs["Type"].default_value = "Bloom"
    bloom.inputs["Quality"].default_value = "High"
    bloom.inputs["Threshold"].default_value = 0.6
    bloom.inputs["Size"].default_value = 0.6
    tree.links.new(layers.outputs["Image"], bloom.inputs["Image"])
    tree.links.new(bloom.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = tree


VIEWS = {"iso": (35, 14, 4.2), "front": (0, 6, 4.0)}  # how far round and down (degrees), and how far away


def aim(camera, view):
    around, down, distance = VIEWS[view]
    a, e = math.radians(around), math.radians(down)
    target = (0, 0, 0.62)
    camera.location = (target[0] + math.sin(a) * math.cos(e) * distance, target[1] - math.cos(a) * math.cos(e) * distance,
                       target[2] + math.sin(e) * distance)
    camera.rotation_euler = (math.pi / 2 - e, 0, a)


# ---------------------------------------------------------------------------
# Command-line extras: previews and the .glb for the site
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


def render(view, path):
    aim(scene.camera, view)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def export(path):
    """Joins the little pieces of each part by material (fewer draw calls), keeping the named parts the site
    animates (Head, ArmL, ArmR, Face, Tip) as they are, then writes a .glb with no lights or camera."""
    keep_apart = {"Face", "Tip"}
    groups = {}
    for obj in collection("Vega").objects:
        if obj.type == "MESH" and obj.name not in keep_apart:
            groups.setdefault((obj.parent.name if obj.parent else "", obj.active_material.name), []).append(obj)
    for objs in groups.values():
        if len(objs) > 1:
            with bpy.context.temp_override(active_object=objs[0], object=objs[0], selected_objects=objs,
                                           selected_editable_objects=objs):
                bpy.ops.object.join()
    for obj in scene.objects:
        obj.select_set(obj.users_collection[0].name == "Vega")
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
    parser.add_argument("--export", action="store_true", help="save ../site/models/vega.glb for the site")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    clear()
    make_materials()
    build()
    stage()
    for screen in bpy.data.screens:  # look through the camera, rendered
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type, area.spaces.active.shading.use_compositor = "RENDERED", "ALWAYS"
                area.spaces.active.region_3d.view_perspective = "CAMERA"
    if args.render or args.export:
        bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "vega.blend"))
    if args.render:
        print("Rendering on", use_gpu())
        render("iso", HERE / "vega_iso.png")
        render("front", HERE / "vega_front.png")
    if args.export:
        export(HERE.parent / "site" / "models" / "vega.glb")


main()
