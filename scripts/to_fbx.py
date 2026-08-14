"""
to_fbx.py — BVH -> FBX listo para el rig Humanoid de Unity. Se corre con Blender:

  blender --background --python to_fbx.py -- \
      --input ../kimodo_animations --out ../fbx --scale 0.01

Que hace y por que:
  * importa el BVH con rotate_mode NATIVE (respeta el orden de canales del archivo)
  * escala cm -> m (los BVH de Kimodo estan en centimetros; Unity espera metros;
    si importas sin escalar, el personaje mide 170 unidades y el root motion vuela)
  * fuerza los ejes de FBX que Unity espera (-Z forward, Y up) y
    apply_scale_options='FBX_SCALE_ALL' para que la escala quede horneada en 1.0
  * add_leaf_bones=False: los leaf bones rompen el automapeo de Humanoid
  * escribe humanoid_map.json con el mapeo de huesos detectado, para que en Unity
    configures el Avatar una sola vez y lo reuses en todos los clips (Copy From Other Avatar)

Nota: esto NO es retargeting. Exporta el esqueleto de Kimodo con su animacion y
deja que Unity haga el mapeo Humanoid. Si necesitas el mismo esqueleto que tu
personaje, el retarget se hace en Unity (Humanoid) o con Rokoko/Auto-Rig Pro en Blender.
"""

import json
import os
import sys

import bpy

HUMANOID = {
    "Hips": ["hips", "pelvis", "root"],
    "Spine": ["spine"], "Chest": ["chest", "spine1", "spine2"],
    "Neck": ["neck"], "Head": ["head"],
    "LeftShoulder": ["leftshoulder", "lshoulder", "leftclavicle"],
    "LeftUpperArm": ["leftarm", "lupperarm", "leftupperarm"],
    "LeftLowerArm": ["leftforearm", "lforearm", "leftlowerarm"],
    "LeftHand": ["lefthand", "lhand"],
    "RightShoulder": ["rightshoulder", "rshoulder", "rightclavicle"],
    "RightUpperArm": ["rightarm", "rupperarm", "rightupperarm"],
    "RightLowerArm": ["rightforearm", "rforearm", "rightlowerarm"],
    "RightHand": ["righthand", "rhand"],
    "LeftUpperLeg": ["leftupleg", "lthigh", "leftthigh"],
    "LeftLowerLeg": ["leftleg", "lshin", "leftshin"],
    "LeftFoot": ["leftfoot", "lfoot"], "LeftToes": ["lefttoe", "ltoe"],
    "RightUpperLeg": ["rightupleg", "rthigh", "rightthigh"],
    "RightLowerLeg": ["rightleg", "rshin", "rightshin"],
    "RightFoot": ["rightfoot", "rfoot"], "RightToes": ["righttoe", "rtoe"],
}


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def parse_args():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="archivo .bvh o carpeta")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=0.01, help="cm->m = 0.01")
    ap.add_argument("--fps", type=int, default=30)
    return ap.parse_args(argv_after_dashes())


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def guess_humanoid(armature):
    names = [b.name for b in armature.data.bones]
    norm = {b: b.lower().replace("_", "").replace(".", "").replace(" ", "") for b in names}
    out, used = {}, set()
    for slot, hints in HUMANOID.items():
        for h in hints:
            hit = next((b for b in names if norm[b] == h and b not in used), None) \
                or next((b for b in names if h in norm[b] and b not in used), None)
            if hit:
                out[slot] = hit
                used.add(hit)
                break
    return out


def convert(path, outdir, scale, fps):
    clear_scene()
    bpy.context.scene.render.fps = fps
    bpy.ops.import_anim.bvh(
        filepath=path,
        global_scale=scale,
        rotate_mode="NATIVE",
        use_fps_scale=False,
        update_scene_fps=False,
        update_scene_duration=True,
    )
    arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    if arm is None:
        raise RuntimeError(f"sin armature tras importar {path}")

    stem = os.path.splitext(os.path.basename(path))[0]
    arm.name = stem
    if arm.animation_data and arm.animation_data.action:
        arm.animation_data.action.name = stem

    os.makedirs(outdir, exist_ok=True)
    fbx = os.path.join(outdir, stem + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=fbx,
        use_selection=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        global_scale=1.0,
        axis_forward="-Z",
        axis_up="Y",
        object_types={"ARMATURE"},
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        armature_nodetype="NULL",
    )
    return fbx, guess_humanoid(arm)


def main():
    a = parse_args()
    files = ([a.input] if a.input.lower().endswith(".bvh")
             else [os.path.join(r, f) for r, _, fs in os.walk(a.input)
                   for f in fs if f.lower().endswith(".bvh")])
    if not files:
        raise SystemExit(f"no encontre BVH en {a.input}")

    mapping = None
    done = []
    for p in sorted(files):
        rel = os.path.relpath(os.path.dirname(p), a.input if os.path.isdir(a.input) else os.path.dirname(a.input))
        outdir = os.path.join(a.out, rel) if rel not in (".", "") else a.out
        fbx, m = convert(p, outdir, a.scale, a.fps)
        mapping = mapping or m
        done.append(fbx)
        print("OK", fbx)

    if mapping:
        with open(os.path.join(a.out, "humanoid_map.json"), "w") as f:
            json.dump(mapping, f, indent=2)
        faltan = [k for k in HUMANOID if k not in mapping]
        print(f"\nhumanoid_map.json escrito ({len(mapping)}/{len(HUMANOID)} huesos).")
        if faltan:
            print("Sin detectar (mapealos a mano en el Avatar de Unity): " + ", ".join(faltan))
    print(f"\n{len(done)} FBX exportados a {a.out}")


if __name__ == "__main__":
    main()
