"""
run_catalog.py — procesa todos los BVH crudos segun el catalogo, elige el mejor
candidato por clip, los organiza por categoria y escribe el manifest para
`register_gesture_batch`.

  python run_catalog.py --catalog ../catalog/kimodo_catalog.json \
                        --raw ../raw --out ../kimodo_animations

Estructura de salida:
  kimodo_animations/
    locomotion/loco_walk_neutral.bvh
    locomotion/loco_walk_neutral.root.json
    transition/...
    upper/...
    reaction/...
    _rejected/...            <- candidatos que no pasaron QC (no se borran)
    manifest.json
    qc_report.json

Regla de desempate de nombres: si hay varios archivos para el mismo clip
(clip.bvh, clip 2.bvh, clip__v3.bvh), gana el de sufijo numerico mas alto.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postprocess import process, _verdict     # noqa: E402


def suffix_rank(path: str) -> int:
    """'clip 2.bvh' -> 2 ; 'clip__v3.bvh' -> 3 ; 'clip.bvh' -> 0."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"(?:__v|[ _-])(\d+)$", stem)
    return int(m.group(1)) if m else 0


def candidates_for(raw_dir: str, clip_id: str) -> list[str]:
    pats = [f"{clip_id}.bvh", f"{clip_id}__v*.bvh", f"{clip_id} *.bvh", f"{clip_id}_*.bvh"]
    files = []
    for p in pats:
        files += glob.glob(os.path.join(raw_dir, "**", p), recursive=True)
    return sorted(set(files), key=suffix_rank, reverse=True)


def score(report: dict, clip_qc: dict | None = None) -> float:
    """Menor es mejor. Penaliza skate, penetracion, jitter, mal loop y falta de ciclo."""
    clip_qc = clip_qc or {}
    c = report.get("clean", {})
    s = c.get("foot_skate_mean_cm_per_frame", 99) * 10
    s += c.get("ground_penetration_cm", 99) * 5
    s += c.get("jitter_cm", 9) * 2
    lp = report.get("loop")
    if lp and "error" not in lp:
        s += lp.get("match_score", 0) * 0.5
    elif lp:
        s += 50

    # Entre dos candidatos igual de limpios gana el que tenga marcha de verdad.
    # Sin esto el desempate premia al clip congelado: sin zancadas no hay skate,
    # asi que sus metricas de limpieza salen inmejorables.
    #
    # El premio por ciclos NO se satura en el umbral de QC. Con `>= 2` a secas,
    # en loco_run ganaba un candidato de 2 ciclos a 2.10 m/s frente a otro de 5
    # ciclos a 2.68 m/s: los dos pasaban, y el resto del score lo decidia el foot
    # skate. Mas ciclos es mas material del que recortar el loop, y por tanto
    # mejor clip de produccion.
    if report.get("loop_kind") == "gait":
        cyc = report.get("gait", {}).get("cycles", 0)
        s += max(0, 2 - cyc) * 25
        s -= min(cyc, 6) * 5

    # Solo penaliza la cola congelada en clips que LOOPEAN, igual que el veredicto
    # de QC. Aplicandolo a todos, un one-shot como trans_stand_to_sit_chair
    # prefiere el candidato que se sigue moviendo despues de sentarse; acabar
    # quieto ahi es lo correcto, no un defecto. Cambiaba 10 ganadores por esto.
    if report.get("loop_kind"):
        s += report.get("frozen_tail_ratio", 0.0) * 40

    # Deriva: entre dos candidatos igual de limpios gana el que menos derive.
    # Sin esto el desempate la ignoraba y en loco_crouch_idle ganaba un candidato
    # de 10.5 cm frente a otro de 7.3.
    #
    # Se aplica SOLO a los clips que declaran `max_root_drift_cm`, no a todos los
    # pin_origin. Probado sobre los 23 pin_origin: como la deriva no correlaciona
    # con la calidad del clip clavado, el foot skate medio de los 7 que cambiaban
    # de ganador subia de 0.083 a 0.102 cm/frame y el error de loop empeoraba en 4
    # de 7. El desempate solo debe optimizar lo que el catalogo declara que le
    # importa a ese clip.
    if clip_qc.get("max_root_drift_cm"):
        s += report.get("root_drift_cm", 0.0) * 2

    # NO se desempata por cercania a `expected_speed_m_s`, aunque sea tentador.
    # El runtime consume la velocidad MEDIDA (`rootSpeedMs`), no la asignada a
    # mano en el catalogo, asi que acercarse a la asignada no aporta nada. Y
    # cuesta: probado con peso 20, elegia un loco_sneak_walk con 0.59 cm/frame de
    # foot skate en vez de uno con 0.13 solo por quedar 0.12 m/s mas cerca. El
    # skate se ve en pantalla; esos 0.12 m/s no los ve nadie.
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-all", action="store_true",
                    help="conserva todos los candidatos procesados, no solo el ganador")
    a = ap.parse_args()

    with open(a.catalog) as f:
        cat = json.load(f)

    tmp = os.path.join(a.out, "_work")
    rej = os.path.join(a.out, "_rejected")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(rej, exist_ok=True)

    manifest, qc_all, missing = [], {}, []

    for clip in cat["clips"]:
        cid = clip["id"]
        cands = candidates_for(a.raw, cid)
        if not cands:
            missing.append(cid)
            print(f"--  {cid}: sin candidatos")
            continue

        results = []
        for src in cands:
            work = os.path.join(tmp, os.path.splitext(os.path.basename(src))[0])
            try:
                rep = process(
                    src, work,
                    policy=clip.get("root_policy", "keep"),
                    loop=clip.get("loop_cycle") if clip.get("loop") else None,
                    freeze=clip.get("mask") == "upper_body",
                    head_trim_s=clip.get("loop_trim_head_s", 0.5),
                )
            except Exception as e:                          # noqa: BLE001
                print(f"!!  {cid}: fallo {os.path.basename(src)} -> {e}")
                continue
            rep["source"] = src
            rep["passed"] = _verdict(rep, clip.get("qc", {}))
            rep["score"] = round(score(rep, clip.get("qc", {})), 4)
            results.append((rep, work))

        if not results:
            missing.append(cid)
            continue

        results.sort(key=lambda r: (not r[0]["passed"]["all"], r[0]["score"]))
        best, best_dir = results[0]

        dest = os.path.join(a.out, clip["category"])
        os.makedirs(dest, exist_ok=True)
        stem = os.path.splitext(os.path.basename(best["source"]))[0]
        shutil.copy(os.path.join(best_dir, stem + ".bvh"), os.path.join(dest, cid + ".bvh"))
        root_json = os.path.join(best_dir, stem + ".root.json")
        if os.path.exists(root_json):
            shutil.copy(root_json, os.path.join(dest, cid + ".root.json"))

        for rep, wdir in results[1:]:
            s = os.path.splitext(os.path.basename(rep["source"]))[0]
            if a.keep_all and os.path.exists(os.path.join(wdir, s + ".bvh")):
                shutil.copy(os.path.join(wdir, s + ".bvh"), os.path.join(rej, s + ".bvh"))

        entry = {
            "id": cid,
            "category": clip["category"],
            "file": os.path.join(clip["category"], cid + ".bvh"),
            "prompt": clip["prompt"],
            "rootPolicy": clip.get("root_policy"),
            "isLoop": bool(clip.get("loop")),
            "mask": clip.get("mask"),
            "durationS": best["clean"]["duration_s"],
            "fps": best["clean"]["fps"],
            "rootSpeedMs": best.get("root_speed_m_per_s"),
            "footSkateCm": best["clean"]["foot_skate_mean_cm_per_frame"],
            "loopErrorCm": best.get("final_loop_pose_error_cm"),
            "gaitCycles": best.get("gait", {}).get("cycles"),
            "frozenTailRatio": best.get("frozen_tail_ratio"),
            "headingDeltaDeg": best.get("heading_delta_deg"),
            "rootDriftCm": best.get("root_drift_cm"),
            "legMotionDeg": best["clean"].get("leg_motion_deg"),
            "peakFrames": best["clean"].get("peak_frames"),
            "expectedSpeedMs": clip.get("qc", {}).get("expected_speed_m_s"),
            "qcPassed": best["passed"]["all"],
            "qcFailed": [k for k, v in best["passed"].items() if k != "all" and not v],
            **clip.get("taxonomy", {}),
        }
        manifest.append(entry)
        qc_all[cid] = {"winner": best["source"], "candidates": [r[0] for r in results]}
        flag = "OK " if best["passed"]["all"] else "REV"
        gait = f", gait={entry['gaitCycles']}" if entry["gaitCycles"] is not None else ""
        why = f"  <- {', '.join(entry['qcFailed'])}" if entry["qcFailed"] else ""
        print(f"{flag} {cid}: {len(results)} cand, score={best['score']}, "
              f"skate={entry['footSkateCm']}cm/f, speed={entry['rootSpeedMs']}{gait}{why}")

    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump({"version": cat["version"], "clips": manifest, "missing": missing}, f, indent=2)
    with open(os.path.join(a.out, "qc_report.json"), "w") as f:
        json.dump(qc_all, f, indent=2)

    ok = sum(1 for m in manifest if m["qcPassed"])
    print(f"\n{ok}/{len(manifest)} clips pasaron QC. Faltan por generar: {len(missing)}")
    if missing:
        print("  " + ", ".join(missing))

    by_check = {}
    for m in manifest:
        for k in m["qcFailed"]:
            by_check.setdefault(k, []).append(m["id"])
    if by_check:
        print("\nFallos por comprobacion:")
        for k, ids in sorted(by_check.items(), key=lambda kv: -len(kv[1])):
            print(f"  {k:<15} {len(ids):>3}  {', '.join(ids[:6])}"
                  + (" ..." if len(ids) > 6 else ""))


if __name__ == "__main__":
    main()
