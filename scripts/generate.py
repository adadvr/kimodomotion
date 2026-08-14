"""
generate.py — driver de generacion por lotes para el catalogo Kimodo.

Tres backends, misma interfaz:

  --backend cli    -> llama a `kimodo_gen` (repo nv-tlabs/kimodo, necesita GPU NVIDIA)
  --backend rest   -> POST a un endpoint HTTP (kimodo-api self-host, PORUZ, tu propio wrapper)
  --backend manual -> NO genera: escribe una hoja de trabajo con el prompt, la duracion,
                      el seed y el nombre de archivo exacto para pegarlos en la demo web
                      y te valida/renombra lo que descargues.

Caracteristicas:
  * estado reanudable en `state.json` (si se corta, sigue donde iba)
  * N candidatos por clip con seeds derivados y deterministas
  * constraints automaticos: root2d clavado en el origen para los clips `pin_origin`
  * respeta rate limits con --sleep y reintentos con backoff

Uso tipico:
  python generate.py --catalog ../catalog/kimodo_catalog.json --outdir ../raw --backend cli
  python generate.py --catalog ../catalog/kimodo_catalog.json --outdir ../raw --backend manual
  python generate.py --catalog ... --backend rest --endpoint http://localhost:9551/generate
  python generate.py --catalog ... --only loco_walk_neutral,react_dodge
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


# ----------------------------------------------------------------- helpers
def seed_for(clip_id: str, base_seed: int, k: int) -> int:
    h = hashlib.sha1(f"{clip_id}:{k}".encode()).hexdigest()
    return (base_seed + int(h[:8], 16)) % (2 ** 31 - 1)


def build_constraints(clip: dict, fps: int, path: str) -> str | None:
    """Genera el JSON de constraints. Para `pin_origin` clava la trayectoria 2D
    del root en (0,0) en toda la duracion: es la unica forma fiable de pedirle a
    Kimodo que NO camine. Escribirlo en el prompt no funciona."""
    if clip.get("root_policy") != "pin_origin":
        return None
    n = int(round(clip["duration"] * fps))
    idx = list(range(0, n, max(1, n // 12)))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    data = [{
        "type": "root2d",
        "frame_indices": idx,
        "smooth_root_2d": [[0.0, 0.0] for _ in idx],
        "global_root_heading": [[0.0, 1.0] for _ in idx],
    }]
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------- backends
def run_cli(clip, seed, out_stem, defaults, constraints, extra_args, low_vram=False):
    cmd = [
        "kimodo_gen", clip["prompt"],
        "--model", defaults["model"],
        "--duration", str(clip["duration"]),
        "--diffusion_steps", str(defaults["diffusion_steps"]),
        "--seed", str(seed),
        "--output", out_stem,
        "--cfg_type", defaults["cfg_type"],
        "--cfg_weight", *[str(w) for w in defaults["cfg_weight"]],
    ]
    if defaults.get("bvh"):
        cmd.append("--bvh")
    if defaults.get("bvh_standard_tpose"):
        cmd.append("--bvh_standard_tpose")
    if constraints:
        cmd += ["--constraints", constraints]
    cmd += extra_args
    env = dict(os.environ)
    if low_vram:
        # manda el text encoder (Llama-3-8B) a la CPU: la VRAM baja de ~17 GB a <3 GB.
        # Imprescindible en laptops de 4-6 GB. Necesita ~16 GB de RAM de sistema.
        env["TEXT_ENCODER_DEVICE"] = "cpu"
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-800:] or "kimodo_gen fallo sin stderr")
    return out_stem + ".bvh"


def run_rest(clip, seed, out_stem, defaults, constraints, endpoint, api_key, timeout):
    payload = {
        "prompt": clip["prompt"],
        "duration": clip["duration"],
        "seed": seed,
        "format": "bvh",
        "model": defaults["model"],
        "diffusion_steps": defaults["diffusion_steps"],
    }
    if constraints:
        with open(constraints) as f:
            payload["constraints"] = json.load(f)
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {api_key}"} if api_key else {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        ctype = r.headers.get("Content-Type", "")

    # Respuesta binaria directa
    if "json" not in ctype:
        ext = ".bvh" if b"HIERARCHY" in body[:200] else ".npz"
        path = out_stem + ext
        with open(path, "wb") as f:
            f.write(body)
        return path

    # Respuesta JSON: puede traer una URL de descarga o un job id
    data = json.loads(body)
    url = data.get("bvh_url") or data.get("download_url") or data.get("url")
    if not url:
        raise RuntimeError(f"respuesta JSON sin URL de descarga: {list(data)[:8]}")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        path = out_stem + ".bvh"
        with open(path, "wb") as f:
            f.write(r.read())
    return path


def run_manual(clip, seed, out_stem, defaults, constraints):
    """No genera nada: deja la instruccion exacta para la demo web."""
    note = {
        "file_esperado": os.path.basename(out_stem) + ".bvh",
        "prompt": clip["prompt"],
        "duration_s": clip["duration"],
        "seed": seed,
        "cfg_type": defaults["cfg_type"],
        "cfg_weight": defaults["cfg_weight"],
        "diffusion_steps": defaults["diffusion_steps"],
        "constraints_file": os.path.basename(constraints) if constraints else None,
        "export": "BVH (marca 'standard T-pose' si la UI lo ofrece)",
    }
    with open(out_stem + ".todo.json", "w") as f:
        json.dump(note, f, indent=2, ensure_ascii=False)
    return None


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--backend", default="manual", choices=["cli", "rest", "manual"])
    ap.add_argument("--endpoint", default=os.environ.get("KIMODO_ENDPOINT", ""))
    ap.add_argument("--api-key", default=os.environ.get("KIMODO_API_KEY", ""))
    ap.add_argument("--candidates", type=int, default=None,
                    help="cuantas variantes por clip (default: num_samples del catalogo)")
    ap.add_argument("--only", default="", help="ids separados por coma")
    ap.add_argument("--category", default="", help="filtra por categoria")
    ap.add_argument("--sleep", type=float, default=0.0, help="segundos entre generaciones (rate limit)")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--force", action="store_true", help="regenera aunque ya exista")
    ap.add_argument("--low-vram", action="store_true",
                    help="TEXT_ENCODER_DEVICE=cpu -> baja la VRAM de ~17GB a <3GB. "
                         "Usalo en laptops de 4-6 GB de video (necesita ~16 GB de RAM).")
    ap.add_argument("extra", nargs="*", help="flags extra que se pasan tal cual a kimodo_gen")
    a = ap.parse_args()

    with open(a.catalog) as f:
        cat = json.load(f)
    defaults = cat["defaults"]
    fps = defaults["fps"]
    n_cand = a.candidates or defaults.get("num_samples", 1)

    clips = cat["clips"]
    if a.only:
        wanted = {s.strip() for s in a.only.split(",") if s.strip()}
        clips = [c for c in clips if c["id"] in wanted]
    if a.category:
        clips = [c for c in clips if c["category"] == a.category]

    os.makedirs(a.outdir, exist_ok=True)
    cdir = os.path.join(a.outdir, "_constraints")
    os.makedirs(cdir, exist_ok=True)
    state_path = os.path.join(a.outdir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}

    total = len(clips) * n_cand
    done = 0
    for clip in clips:
        cpath = build_constraints(clip, fps, os.path.join(cdir, clip["id"] + ".json"))
        for k in range(n_cand):
            done += 1
            key = f"{clip['id']}#{k}"
            stem = os.path.join(a.outdir, f"{clip['id']}__v{k}")
            if state.get(key, {}).get("ok") and not a.force:
                print(f"[{done}/{total}] skip {key}")
                continue
            seed = seed_for(clip["id"], defaults["base_seed"], k)
            print(f"[{done}/{total}] {key} seed={seed} :: {clip['prompt'][:70]}")

            last_err = None
            for attempt in range(a.retries):
                try:
                    if a.backend == "cli":
                        out = run_cli(clip, seed, stem, defaults, cpath, a.extra, a.low_vram)
                    elif a.backend == "rest":
                        if not a.endpoint:
                            sys.exit("--endpoint es obligatorio con --backend rest")
                        out = run_rest(clip, seed, stem, defaults, cpath,
                                       a.endpoint, a.api_key, a.timeout)
                    else:
                        out = run_manual(clip, seed, stem, defaults, cpath)
                    state[key] = {"ok": True, "seed": seed, "file": out,
                                  "prompt": clip["prompt"], "duration": clip["duration"],
                                  "policy": clip.get("root_policy")}
                    last_err = None
                    break
                except Exception as e:                      # noqa: BLE001
                    last_err = str(e)
                    wait = 2 ** attempt * 3
                    print(f"    fallo ({e}); reintento en {wait}s")
                    time.sleep(wait)
            if last_err:
                state[key] = {"ok": False, "error": last_err, "seed": seed}

            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)
            if a.sleep:
                time.sleep(a.sleep)

    ok = sum(1 for v in state.values() if v.get("ok"))
    print(f"\nlisto: {ok}/{len(state)} generaciones marcadas ok -> {state_path}")
    if a.backend == "manual":
        print("Backend manual: revisa los *.todo.json, generalos en la demo web y "
              "guarda el BVH con el nombre indicado en 'file_esperado'.")


if __name__ == "__main__":
    main()
