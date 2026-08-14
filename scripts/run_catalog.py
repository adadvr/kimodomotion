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


def score(report: dict) -> float:
    """Menor es mejor. Penaliza skate, penetracion, jitter y mal loop."""
    c = report.get("clean", {})
    s = c.get("foot_skate_mean_cm_per_frame", 99) * 10
    s += c.get("ground_penetration_cm", 99) * 5
    s += c.get("jitter_cm", 9) * 2
    lp = report.get("loop")
    if lp and "error" not in lp:
        s += lp.get("match_score", 0) * 0.5
    elif lp:
        s += 50
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
            rep["score"] = round(score(rep), 4)
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
            "qcPassed": best["passed"]["all"],
            **clip.get("taxonomy", {}),
        }
        manifest.append(entry)
        qc_all[cid] = {"winner": best["source"], "candidates": [r[0] for r in results]}
        flag = "OK " if best["passed"]["all"] else "REV"
        print(f"{flag} {cid}: {len(results)} cand, score={best['score']}, "
              f"skate={entry['footSkateCm']}cm/f, speed={entry['rootSpeedMs']}")

    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump({"version": cat["version"], "clips": manifest, "missing": missing}, f, indent=2)
    with open(os.path.join(a.out, "qc_report.json"), "w") as f:
        json.dump(qc_all, f, indent=2)

    ok = sum(1 for m in manifest if m["qcPassed"])
    print(f"\n{ok}/{len(manifest)} clips pasaron QC. Faltan por generar: {len(missing)}")
    if missing:
        print("  " + ", ".join(missing))


if __name__ == "__main__":
    main()
