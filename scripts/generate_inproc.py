"""
generate_inproc.py — genera TODO el catalogo cargando el modelo UNA sola vez.

Por que existe: `kimodo_gen` es un comando, y cada vez que lo llamas vuelve a
cargar el modelo de texto (Llama-3-8B, ~16 GB) desde disco. Con 50 clips x 2
variantes eso son 100 cargas. En un disco externo USB son HORAS tiradas a la
basura. Este script usa la API de Python: carga una vez, genera 100 veces.

  python generate_inproc.py --catalog ../catalog/kimodo_catalog.json \
                            --outdir ../raw --candidates 2 --low-vram

Guarda por cada generacion:
  clip__vN.bvh   el BVH (lo que consume el resto del pipeline)
  clip__vN.npz   el crudo, incluidos `foot_contacts` del modelo

Igual que generate.py, el progreso vive en state.json y se puede reanudar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Debe ir ANTES de importar kimodo: manda el text encoder a la CPU (VRAM <3 GB).
# Lo lee LLM2VecEncoder.__init__ en kimodo/model/llm2vec/llm2vec_wrapper.py.
if "--low-vram" in sys.argv:
    os.environ["TEXT_ENCODER_DEVICE"] = "cpu"

# TEXT_ENCODER_MODE por defecto es "auto": intenta levantar un TextEncoderAPI
# remoto, espera a que falle, y recien ahi cae al encoder local. Aqui siempre
# corremos local, asi que nos ahorramos ese sondeo en cada arranque.
os.environ.setdefault("TEXT_ENCODER_MODE", "local")

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate import seed_for, build_constraints  # noqa: E402


def get_skeleton(model):
    """El nombre del atributo cambio entre versiones; probamos los candidatos."""
    for attr in ("skeleton", "skel", "_skeleton"):
        s = getattr(model, attr, None)
        if s is not None:
            return s
    for holder in ("motion_repr", "representation", "cfg", "config"):
        h = getattr(model, holder, None)
        if h is not None and getattr(h, "skeleton", None) is not None:
            return h.skeleton
    raise RuntimeError(
        "no encontre el skeleton en el modelo. Corre esto y pasame la salida:\n"
        "  python -c \"from kimodo.model.load_model import load_model; "
        "m=load_model('soma',device='cpu'); print([a for a in dir(m) if 'skel' in a.lower()])\""
    )


def get_output_skeleton(model, skeleton):
    """El esqueleto de la SALIDA, que NO es el mismo que el de entrada.

    Kimodo genera internamente en `somaskel30`, pero antes de devolver convierte
    la salida a `somaskel77` (kimodo_model.py:553). Hay dos esqueletos en juego:

      * el de entrada (30) -> lo necesitan los constraints, que se consumen
        dentro del modelo
      * el de salida (77)  -> lo necesita save_motion_bvh

    Si le pasas el de 30 al export, motion_to_bvh ve `name == "somaskel30"` e
    intenta convertir por segunda vez algo que ya viene en 77:
      "shape mismatch: value tensor of shape [T,77,3,3] cannot be broadcast
       to indexing result of shape [T,30,3,3]"
    """
    out = getattr(model, "output_skeleton", None)
    if out is not None:
        return out
    return getattr(skeleton, "somaskel77", skeleton)


def load_constraints(path, skeleton, device=None):
    """Convierte el JSON de constraints al objeto que espera la API.

    La funcion real es `kimodo.constraints.load_constraints_lst(path_or_data,
    skeleton, device=None, dtype=None)`; acepta la ruta del JSON directamente y
    mapea cada `type` via TYPE_TO_CLASS ("root2d" -> Root2DConstraintSet).

    Necesita el `skeleton` (los ConstraintSet lo reciben en `from_dict`), por eso
    esto se llama DESPUES de cargar el modelo y no al construir el JSON.
    """
    if not path or not os.path.exists(path):
        return []
    from kimodo.constraints import load_constraints_lst
    try:
        return load_constraints_lst(path, skeleton, device=device)
    except Exception as e:                                      # noqa: BLE001
        # No es fatal: sin constraint el clip se genera con desplazamiento libre y
        # el postproceso lo clava con pin_origin (peor, pero usable). Lo que NO
        # queremos es tirar un lote de 3 horas por un clip.
        print(f"  aviso: no pude cargar los constraints de {os.path.basename(path)} "
              f"({type(e).__name__}: {e}); genero sin ellos")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--candidates", type=int, default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--category", default="")
    # "soma" es ambiguo: el registro tiene kimodo-soma-rp Y kimodo-soma-seed, y
    # resolve_model_name() puede elegir mal. Usamos el short_key exacto, que es
    # ademas el DEFAULT_MODEL de kimodo/model/registry.py.
    ap.add_argument("--model", default="kimodo-soma-rp")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--low-vram", action="store_true",
                    help="TEXT_ENCODER_DEVICE=cpu -> VRAM <3 GB (laptops de 4-6 GB)")
    ap.add_argument("--no-npz", action="store_true", help="no guardar el .npz crudo")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    import torch
    from kimodo.model.load_model import load_model
    from kimodo.exports.bvh import save_motion_bvh

    with open(a.catalog) as f:
        cat = json.load(f)
    d = cat["defaults"]
    fps = d["fps"]
    n_cand = a.candidates or d.get("num_samples", 1)

    clips = cat["clips"]
    if a.only:
        want = {s.strip() for s in a.only.split(",") if s.strip()}
        clips = [c for c in clips if c["id"] in want]
    if a.category:
        clips = [c for c in clips if c["category"] == a.category]

    os.makedirs(a.outdir, exist_ok=True)
    cdir = os.path.join(a.outdir, "_constraints")
    os.makedirs(cdir, exist_ok=True)
    state_path = os.path.join(a.outdir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}

    print(f"cargando modelo '{a.model}' en {a.device} "
          f"(text encoder en {os.environ.get('TEXT_ENCODER_DEVICE', 'gpu')})...")
    t0 = time.time()
    model = load_model(modelname=a.model, device=a.device)
    skeleton = get_skeleton(model)              # entrada (somaskel30): constraints
    out_skeleton = get_output_skeleton(model, skeleton)   # salida (somaskel77): BVH
    print(f"modelo listo en {time.time() - t0:.0f}s. Esta carga NO se repite.")
    print(f"esqueleto: entrada={getattr(skeleton, 'name', '?')} "
          f"salida={getattr(out_skeleton, 'name', '?')}\n")

    total, done, t_start = len(clips) * n_cand, 0, time.time()
    for clip in clips:
        cpath = build_constraints(clip, fps, os.path.join(cdir, clip["id"] + ".json"))
        constraints = load_constraints(cpath, skeleton, a.device)
        for k in range(n_cand):
            done += 1
            key = f"{clip['id']}#{k}"
            stem = os.path.join(a.outdir, f"{clip['id']}__v{k}")
            if state.get(key, {}).get("ok") and not a.force:
                print(f"[{done}/{total}] skip {key}")
                continue

            seed = seed_for(clip["id"], d["base_seed"], k)
            n_frames = int(round(clip["duration"] * fps))
            eta = ((time.time() - t_start) / max(1, done - 1)) * (total - done) / 60
            print(f"[{done}/{total}] {key}  {n_frames}f  seed={seed}  "
                  f"(faltan ~{eta:.0f} min) :: {clip['prompt'][:60]}")

            try:
                torch.manual_seed(seed)
                np.random.seed(seed % (2 ** 31))
                out = model(
                    # OJO: lista de 1, NO un string suelto. Con un string, Kimodo
                    # entra por el `else` de kimodo_model.py:484 y activa
                    # `tosqueeze`, que quita la dimension de batch en la 531...
                    # pero dos lineas mas abajo su propio post_process_motion la
                    # exige de vuelta (postprocess.py:214, assert dim()==5) y
                    # revienta con "local_rot_mats should be 5D". Son dos rutas
                    # del codigo de Kimodo que no encajan entre si.
                    # Con una lista entra por la 478: num_samples=1 y sin squeeze.
                    prompts=[clip["prompt"]],
                    num_frames=n_frames,
                    num_denoising_steps=d["diffusion_steps"],
                    constraint_lst=constraints,
                    cfg_weight=d["cfg_weight"],
                    cfg_type=d["cfg_type"],
                    post_processing=True,      # la optimizacion de foot skate de Kimodo
                    # OJO: NO poner return_numpy=True. save_motion_bvh() ->
                    # motion_to_bvh() arranca con local_rot_mats.detach(), y un
                    # ndarray no tiene .detach() -> AttributeError en el 1er clip.
                    # Pedimos tensores y convertimos a numpy solo para el .npz.
                    return_numpy=False,
                )
                save_motion_bvh(stem + ".bvh", out["local_rot_mats"], out["root_positions"],
                                skeleton=out_skeleton, fps=fps,
                                standard_tpose=d.get("bvh_standard_tpose", True))
                if not a.no_npz:
                    arrs = {}
                    for kk, v in out.items():
                        if not hasattr(v, "detach"):
                            continue
                        arr = v.detach().cpu().numpy()
                        # quitamos el batch de 1 para que el npz quede [T,...]:
                        # asi `foot_contacts` sale [T,4] como dice el README.
                        if arr.ndim > 1 and arr.shape[0] == 1:
                            arr = arr[0]
                        arrs[kk] = arr
                    np.savez_compressed(stem + ".npz", **arrs)
                state[key] = {"ok": True, "seed": seed, "file": stem + ".bvh",
                              "prompt": clip["prompt"], "duration": clip["duration"],
                              "policy": clip.get("root_policy")}
            except Exception as e:                          # noqa: BLE001
                print(f"    FALLO: {e}")
                state[key] = {"ok": False, "error": str(e), "seed": seed}

            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)

    ok = sum(1 for v in state.values() if v.get("ok"))
    print(f"\nlisto: {ok}/{len(state)} en {(time.time() - t_start) / 60:.0f} min -> {a.outdir}")
    print("ahora: python run_catalog.py --catalog ... --raw ... --out ../kimodo_animations")


if __name__ == "__main__":
    main()
