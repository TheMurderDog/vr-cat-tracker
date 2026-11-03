# Builds a low-poly stick-figure placeholder cat with a simple rig and four actions (Normal, Resting, Moving, Alert) for the
# VRChat cat tracker avatar system, renders previews, and saves the .blend.
# Usage: blender --background --factory-startup --python build_cat_placeholder.py -- <out_blend or ""> <render_dir or ""> [out_fbx]
# Blender forward = -Y (becomes +Z in Unity with the usual FBX export), Z up, metres. The rig root sits on the floor under
# the middle of the body: that point is what the tracker's position puts on the cat.
import bpy, bmesh, math, sys, os
from mathutils import Vector, Matrix, Euler

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT_BLEND = args[0] if len(args) > 0 else ""
RENDER_DIR = args[1] if len(args) > 1 else ""
OUT_FBX = args[2] if len(args) > 2 else ""

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
scn.render.fps = 24

# ---------------- rig ----------------
H = 0.22          # spine height
BONES = {  # name: (head, tail, parent)
    "Root":   ((0, 0, 0), (0, 0, 0.1), None),
    "Hips":   ((0, 0.17, H), (0, 0, H), "Root"),
    "Chest":  ((0, 0, H), (0, -0.17, H), "Hips"),
    "Neck":   ((0, -0.17, H), (0, -0.23, H + 0.09), "Chest"),
    "Head":   ((0, -0.23, H + 0.09), (0, -0.31, H + 0.10), "Neck"),
    "Tail1":  ((0, 0.17, H), (0, 0.25, H + 0.07), "Hips"),
    "Tail2":  ((0, 0.25, H + 0.07), (0, 0.29, H + 0.17), "Tail1"),
    "Tail3":  ((0, 0.29, H + 0.17), (0, 0.28, H + 0.27), "Tail2"),
}
for side, x in (("L", 0.045), ("R", -0.045)):
    for end, y, par in (("Front", -0.15, "Chest"), ("Back", 0.15, "Hips")):
        BONES[f"{end}Leg{side}"] = ((x, y, H - 0.02), (x, y, 0.10), par)
        BONES[f"{end}Paw{side}"] = ((x, y, 0.10), (x, y - 0.005, 0.0), f"{end}Leg{side}")

arm_data = bpy.data.armatures.new("Cat Placeholder Rig")
rig = bpy.data.objects.new("Cat Placeholder Rig", arm_data)
scn.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
for name, (h, t, p) in BONES.items():
    b = arm_data.edit_bones.new(name); b.head = h; b.tail = t; b.roll = 0
for name, (h, t, p) in BONES.items():
    if p: arm_data.edit_bones[name].parent = arm_data.edit_bones[p]; arm_data.edit_bones[name].use_connect = False
bpy.ops.object.mode_set(mode='OBJECT')

# ---------------- mesh (stick figure: tubes + joints + head) ----------------
mat_body = bpy.data.materials.new("Cat Placeholder Body"); mat_body.diffuse_color = (0.95, 0.55, 0.18, 1)
mat_dark = bpy.data.materials.new("Cat Placeholder Eyes"); mat_dark.diffuse_color = (0.05, 0.05, 0.06, 1)
for m in (mat_body, mat_dark):
    m.use_nodes = True; bsdf = m.node_tree.nodes.get("Principled BSDF"); bsdf.inputs["Base Color"].default_value = m.diffuse_color; bsdf.inputs["Roughness"].default_value = 0.7

bm = bmesh.new()
groups = []   # per vertex: bone name
mats = []     # per face: material index

def add_geom(verts_faces, bone, mat=0):
    vs, fs = verts_faces
    base = len(bm.verts); new = [bm.verts.new(v) for v in vs]
    groups.extend([bone] * len(vs)); bm.verts.ensure_lookup_table()
    for f in fs:
        face = bm.faces.new([new[i] for i in f]); face.material_index = mat

def tube(a, b, r, seg=6):
    a, b = Vector(a), Vector(b); d = (b - a); n = d.normalized()
    up = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
    u = n.cross(up).normalized(); w = n.cross(u).normalized()
    vs = []
    for end in (a, b):
        for i in range(seg):
            ang = 2 * math.pi * i / seg; vs.append(end + (u * math.cos(ang) + w * math.sin(ang)) * r)
    vs += [a, b]
    fs = [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)]
    fs += [(2 * seg, (i + 1) % seg, i) for i in range(seg)] + [(2 * seg + 1, seg + i, seg + (i + 1) % seg) for i in range(seg)]
    return vs, fs

def ball(c, r, sub=1):
    tmp = bmesh.new(); bmesh.ops.create_icosphere(tmp, subdivisions=sub, radius=r)
    vs = [Vector(c) + v.co for v in tmp.verts]; tmp.verts.index_update(); fs = [tuple(v.index for v in f.verts) for f in tmp.faces]; tmp.free()
    return vs, fs

def cone(base, tip, r, seg=4):
    base, tip = Vector(base), Vector(tip); n = (tip - base).normalized(); u = n.cross(Vector((0, 1, 0))).normalized()
    if u.length < 1e-6: u = Vector((1, 0, 0))
    w = n.cross(u).normalized()
    vs = [base + (u * math.cos(2 * math.pi * i / seg) + w * math.sin(2 * math.pi * i / seg)) * r for i in range(seg)] + [tip]
    fs = [(i, (i + 1) % seg, seg) for i in range(seg)] + [tuple(reversed(range(seg)))]
    return vs, fs

def bone_pts(n): h, t, _ = BONES[n]; return Vector(h), Vector(t)

# body: rear half on Hips, front half on Chest, a bit thicker than the limbs
add_geom(tube(*bone_pts("Hips"), 0.05, 8), "Hips"); add_geom(tube(*bone_pts("Chest"), 0.05, 8), "Chest")
add_geom(ball(bone_pts("Hips")[0], 0.052), "Hips"); add_geom(ball(bone_pts("Chest")[0], 0.052), "Chest"); add_geom(ball(bone_pts("Chest")[1], 0.052), "Chest")
add_geom(tube(*bone_pts("Neck"), 0.025), "Neck")
hc = bone_pts("Head")[0] + Vector((0, -0.035, 0.01))
add_geom(ball(hc, 0.065, 2), "Head")
for s in (1, -1):
    add_geom(cone(hc + Vector((0.035 * s, 0.01, 0.045)), hc + Vector((0.05 * s, 0.015, 0.105)), 0.022), "Head")       # ears
    add_geom(ball(hc + Vector((0.026 * s, -0.056, 0.015)), 0.011, 1), "Head", 1)                                       # eyes
add_geom(ball(hc + Vector((0, -0.066, -0.008)), 0.009, 1), "Head", 1)                                                    # nose
for t in ("Tail1", "Tail2", "Tail3"):
    add_geom(tube(*bone_pts(t), 0.016), t); add_geom(ball(bone_pts(t)[1], 0.018), t)
for name in [n for n in BONES if "Leg" in n or "Paw" in n]:
    a, b = bone_pts(name); add_geom(tube(a, b, 0.018), name)
    add_geom(ball(b, 0.022 if "Paw" in name else 0.02), name)

me = bpy.data.meshes.new("Cat Placeholder"); bm.to_mesh(me); bm.free()
me.materials.append(mat_body); me.materials.append(mat_dark)
for p in me.polygons: p.use_smooth = False
body = bpy.data.objects.new("Cat Placeholder", me); scn.collection.objects.link(body)
for name in BONES: body.vertex_groups.new(name=name)
for i, g in enumerate(groups): body.vertex_groups[g].add([i], 1.0, 'REPLACE')
body.parent = rig; mod = body.modifiers.new("Armature", 'ARMATURE'); mod.object = rig

# ---------------- poses ----------------
for pb in rig.pose.bones: pb.rotation_mode = 'XYZ'
def clear():
    for pb in rig.pose.bones: pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0); pb.scale = (1, 1, 1)
def key(frame):
    for pb in rig.pose.bones:
        pb.keyframe_insert("location", frame=frame); pb.keyframe_insert("rotation_euler", frame=frame); pb.keyframe_insert("scale", frame=frame)
# Pose helpers work in world axes (in the parent's posed frame), converted to each bone's own frame, so the poses read the
# same whatever way a bone points. +X pitch swings a bone's far end backward / nose down; +Z turns it to the cat's right.
def R(name, x=0, y=0, z=0):
    pb = rig.pose.bones[name]; rest = pb.bone.matrix_local.to_3x3()
    w = Matrix.Rotation(math.radians(z), 3, 'Z') @ Matrix.Rotation(math.radians(y), 3, 'Y') @ Matrix.Rotation(math.radians(x), 3, 'X')
    pb.rotation_euler = (rest.inverted() @ w @ rest).to_euler('XYZ')
def L(name, x=0, y=0, z=0):
    pb = rig.pose.bones[name]; pb.location = pb.bone.matrix_local.to_3x3().inverted() @ Vector((x, y, z))
rig.animation_data_create()

def new_action(name):
    act = bpy.data.actions.new(name); act.use_fake_user = True; rig.animation_data.action = act; return act

def pose_normal():
    clear(); R("Neck", -10); R("Head", 10); R("Tail2", -25); R("Tail3", -35)
def pose_resting():
    # loaf / sphinx: body on the floor, front paws forward, back legs folded at the sides, head low and turned, tail round the side
    clear(); L("Root", 0, 0, -0.155)
    for s, x in (("L", 1), ("R", -1)):
        R(f"FrontLeg{s}", -88)
        R(f"BackLeg{s}", -85, 0, 12 * x); R(f"BackPaw{s}", 165)
    R("Neck", 30, 0, 20); R("Head", -15, 0, 15)
    R("Tail1", -40, 0, 95); R("Tail2", -60, 0, 75); R("Tail3", -20, 0, 65)
def pose_alert():
    # sitting up, looking at you: rear on the floor, spine tilted up, front legs straight down, back legs folded
    clear(); L("Root", 0, 0, -0.16); R("Hips", -35)
    for s in "LR":
        R(f"FrontLeg{s}", 35); R(f"BackLeg{s}", -55); R(f"BackPaw{s}", 160)
    R("Neck", 25); R("Head", 10); R("Tail1", 20, 0, 50); R("Tail2", -50, 0, 50); R("Tail3", -20, 0, 40)

act = new_action("Normal"); pose_normal(); key(1); key(24)
act = new_action("Resting"); pose_resting(); key(1); key(24)
act = new_action("Alert"); pose_alert(); key(1); key(24)
act = new_action("Moving")
N = 24
for f in range(N + 1):
    ph = 2 * math.pi * f / N; clear(); R("Neck", -10); R("Head", 10)
    swing = 25 * math.sin(ph); lift = max(0, math.sin(ph)); lift2 = max(0, -math.sin(ph))
    R("FrontLegL", swing); R("BackLegR", swing); R("FrontLegR", -swing); R("BackLegL", -swing)
    R("FrontPawL", -35 * lift); R("BackPawR", 35 * lift); R("FrontPawR", -35 * lift2); R("BackPawL", 35 * lift2)
    L("Root", 0, 0, 0.008 * abs(math.cos(ph)))
    R("Tail1", 0, 0, 12 * math.sin(ph)); R("Tail2", -25, 0, 10 * math.sin(ph - 0.6)); R("Tail3", -35, 0, 8 * math.sin(ph - 1.2))
    key(f + 1)
for a in bpy.data.actions:
    for fc in a.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = 'LINEAR'
rig.animation_data.action = bpy.data.actions["Normal"]

# ---------------- previews ----------------
if RENDER_DIR:
    os.makedirs(RENDER_DIR, exist_ok=True)
    scn.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE'
    scn.render.resolution_x, scn.render.resolution_y = 900, 700; scn.render.image_settings.file_format = 'PNG'
    world = bpy.data.worlds.new("Preview World"); world.use_nodes = True; world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.34, 0.38, 1); scn.world = world
    pm = bpy.data.meshes.new("Floor"); bmf = bmesh.new(); bmesh.ops.create_grid(bmf, x_segments=1, y_segments=1, size=1.5); bmf.to_mesh(pm); bmf.free()
    floor = bpy.data.objects.new("Preview Floor", pm); scn.collection.objects.link(floor)
    fm = bpy.data.materials.new("Preview Floor"); fm.use_nodes = True; fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.55, 0.58, 1); pm.materials.append(fm)
    rm = bpy.data.meshes.new("Ring"); bmr = bmesh.new(); bmesh.ops.create_circle(bmr, cap_ends=False, radius=0.3, segments=48); bmr.to_mesh(rm); bmr.free()
    ring = bpy.data.objects.new("Preview Ring (tracked spot)", rm); ring.location.z = 0.002; scn.collection.objects.link(ring)
    rmod = ring.modifiers.new("w", 'WIREFRAME'); rmod.thickness = 0.02
    rmat = bpy.data.materials.new("Ring"); rmat.use_nodes = True; rmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.95, 0.6, 0.1, 1); rm.materials.append(rmat)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN')); sun.data.energy = 3.5; sun.rotation_euler = Euler((math.radians(50), 0, math.radians(30))); scn.collection.objects.link(sun)
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera")); scn.collection.objects.link(cam); scn.camera = cam
    cam.data.lens = 50
    def shoot(name, action, frame, angle_deg=-40, dist=1.6, h=0.75):
        rig.animation_data.action = bpy.data.actions[action]; scn.frame_set(frame)
        a = math.radians(angle_deg); cam.location = Vector((dist * math.sin(a), -dist * math.cos(a), h))
        d = Vector((0, 0, 0.18)) - cam.location; cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        scn.render.filepath = os.path.join(RENDER_DIR, name + ".png"); bpy.ops.render.render(write_still=True); print("WROTE", scn.render.filepath)
    shoot("Pose - Normal (standing)", "Normal", 1)
    shoot("Pose - Resting (curled up)", "Resting", 1)
    shoot("Pose - Alert (sitting up)", "Alert", 1)
    for i, f in enumerate((1, 7, 13, 19)): shoot(f"Pose - Moving (walk frame {i + 1})", "Moving", f)
    shoot("Pose - Normal side", "Normal", 1, angle_deg=-90, h=0.35)
    for o in (floor, ring, sun, cam): bpy.data.objects.remove(o, do_unlink=True)
    for d in (pm, rm, fm, rmat): pass

rig.animation_data.action = bpy.data.actions["Normal"]; scn.frame_set(1)
if OUT_BLEND:
    # Data-only write: no window manager / UI blocks, so no remembered file-browser folders end up in the file.
    scn.render.filepath = "//"
    bpy.data.libraries.write(OUT_BLEND, {scn, rig, body, arm_data, me, mat_body, mat_dark, *bpy.data.actions},
                             path_remap='RELATIVE_ALL', fake_user=True, compress=False)
    print("SAVED", OUT_BLEND)
if OUT_FBX:
    bpy.ops.object.select_all(action='DESELECT'); rig.select_set(True); body.select_set(True)
    rig.animation_data.action = None; clear(); scn.frame_set(1)   # rest pose as the FBX's default (Unity shows it in the prefab)
    bpy.ops.export_scene.fbx(filepath=OUT_FBX, use_selection=True, object_types={'ARMATURE', 'MESH'}, axis_forward='-Z', axis_up='Y',
                             primary_bone_axis='Y', secondary_bone_axis='X', add_leaf_bones=False, path_mode='STRIP', embed_textures=False,
                             bake_anim=True, bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True,
                             bake_anim_simplify_factor=0.0, apply_scale_options='FBX_SCALE_ALL')
    print("EXPORTED", OUT_FBX)
print("BONES", len(BONES), "VERTS", len(me.vertices), "TRIS", sum(len(p.vertices) - 2 for p in me.polygons))
