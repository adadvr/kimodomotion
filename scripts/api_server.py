"""api_server.py — genera clips Kimodo bajo peticion, con autenticacion.

Mantiene el modelo cargado (los 45s de carga se pagan UNA vez, al arrancar) y
atiende peticiones de generacion desde otra maquina. Las encola y las procesa de
una en una: con 4 GB de VRAM no caben dos generaciones simultaneas.

  set KIMODO_USER=adad
  set KIMODO_PASS=algo-largo-y-aleatorio
  python api_server.py --catalog ..\\catalog\\kimodo_catalog.json ^
                       --outdir C:\\kimodo_work\\api_out --low-vram

Endpoints (todos exigen autenticacion Basic):
  GET  /                 panel web
  GET  /api/trabajos     estado de la cola
  POST /api/generar      {"prompt": "...", "duration": 5.0, "policy": "strip_xz"}
  GET  /api/bvh/<id>     descarga el BVH resultante

SOBRE LA SEGURIDAD, leelo antes de exponerlo:

  * Las credenciales salen de KIMODO_USER / KIMODO_PASS. El servidor NO arranca
    sin ellas y nunca se guardan en el repo.
  * Basic auth viaja en base64, que NO es cifrado. Sobre HTTP plano en la red
    local, cualquiera que capture el trafico ve la contrasena. Si lo expones
    fuera, hazlo SIEMPRE detras de HTTPS (ngrok, Cloudflare Tunnel y similares
    terminan TLS por ti).
  * Por defecto escucha solo en 127.0.0.1. Abrirlo a la red es decision tuya:
    --host 0.0.0.0.
  * El nombre de archivo se deriva de un slug filtrado, nunca de la entrada
    cruda: no hay forma de escribir fuera de --outdir.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if "--low-vram" in sys.argv:
    os.environ["TEXT_ENCODER_DEVICE"] = "cpu"
os.environ.setdefault("TEXT_ENCODER_MODE", "local")

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import postprocess  # noqa: E402
from generate import build_constraints  # noqa: E402
from generate_inproc import (  # noqa: E402
    get_output_skeleton,
    get_skeleton,
    load_constraints,
)

ARGS = None
USER = PASS = None
MODELO = None            # se rellena en arrancar_worker()
COLA: "queue.Queue[str]" = queue.Queue()
TRABAJOS: dict[str, dict] = {}
LOCK = threading.Lock()

POLITICAS = ("strip_xz", "pin_origin", "keep")
MAX_PROMPT = 500
MAX_DURACION = 15.0
MIN_DURACION = 1.0
MAX_COLA = 50


# --------------------------------------------------------------------- helpers
def slug(texto: str) -> str:
    """Nombre de archivo seguro. Solo lo que sobreviva a esta lista blanca."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", texto.lower()).strip("_")
    return (s[:48] or "clip")


def autorizado(cabecera: str | None) -> bool:
    """Basic auth con comparacion en tiempo constante."""
    if not cabecera or not cabecera.startswith("Basic "):
        return False
    try:
        pareja = base64.b64decode(cabecera[6:]).decode("utf-8")
        usuario, _, clave = pareja.partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    # los dos compare_digest se evaluan siempre: no queremos que el tiempo de
    # respuesta revele si el usuario existe
    ok_u = hmac.compare_digest(usuario, USER)
    ok_p = hmac.compare_digest(clave, PASS)
    return ok_u and ok_p


def validar(cuerpo: dict) -> tuple[dict | None, str | None]:
    """Devuelve (peticion_limpia, error). Nada que venga de fuera se usa crudo."""
    prompt = str(cuerpo.get("prompt", "")).strip()
    if not prompt:
        return None, "falta 'prompt'"
    if len(prompt) > MAX_PROMPT:
        return None, f"'prompt' pasa de {MAX_PROMPT} caracteres"

    try:
        duracion = float(cuerpo.get("duration", 5.0))
    except (TypeError, ValueError):
        return None, "'duration' no es un numero"
    if not (MIN_DURACION <= duracion <= MAX_DURACION):
        return None, f"'duration' fuera de [{MIN_DURACION}, {MAX_DURACION}]"

    politica = str(cuerpo.get("policy", "keep"))
    if politica not in POLITICAS:
        return None, f"'policy' debe ser una de {POLITICAS}"

    try:
        candidatos = int(cuerpo.get("candidates", 1))
    except (TypeError, ValueError):
        return None, "'candidates' no es un entero"
    if not (1 <= candidatos <= 4):
        return None, "'candidates' fuera de [1, 4]"

    semilla = cuerpo.get("seed")
    if semilla is not None:
        try:
            semilla = int(semilla) % (2 ** 31 - 1)
        except (TypeError, ValueError):
            return None, "'seed' no es un entero"

    return {"prompt": prompt, "duration": duracion, "policy": politica,
            "candidates": candidatos, "seed": semilla}, None


def a_fbx(bvhs: list[str], jid: str) -> list[str]:
    """Convierte los BVH limpios a FBX llamando a Blender headless.

    to_fbx.py se ejecuta DENTRO de Blender (necesita `bpy`), asi que va por
    subproceso. Es CPU: no compite por la VRAM con la generacion.
    """
    if not bvhs:
        return []
    stage = os.path.join(ARGS.outdir, "_fbx_in", jid)
    os.makedirs(stage, exist_ok=True)
    for p in bvhs:                      # Blender recibe una carpeta, no archivos sueltos
        destino = os.path.join(stage, os.path.basename(p))
        with open(p, "rb") as o, open(destino, "wb") as n:
            n.write(o.read())

    salida = os.path.join(ARGS.outdir, "fbx")
    guion = os.path.join(os.path.dirname(os.path.abspath(__file__)), "to_fbx.py")
    r = subprocess.run(
        [ARGS.blender, "--background", "--python", guion, "--",
         "--input", stage, "--out", salida],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError("blender fallo: " + (r.stderr or r.stdout)[-400:])
    return [os.path.splitext(os.path.basename(p))[0] + ".fbx" for p in bvhs]


# ---------------------------------------------------------------------- worker
def arrancar_worker():
    """Carga el modelo una vez y consume la cola indefinidamente."""
    global MODELO
    import torch
    from kimodo.exports.bvh import save_motion_bvh
    from kimodo.model.load_model import load_model

    with open(ARGS.catalog, encoding="utf-8") as f:
        cat = json.load(f)
    d = cat["defaults"]
    fps = d["fps"]

    print(f"cargando modelo '{ARGS.model}' (text encoder en "
          f"{os.environ.get('TEXT_ENCODER_DEVICE', 'gpu')})...")
    t0 = time.time()
    modelo = load_model(modelname=ARGS.model, device=ARGS.device)
    esq_in = get_skeleton(modelo)
    esq_out = get_output_skeleton(modelo, esq_in)
    MODELO = modelo
    print(f"modelo listo en {time.time() - t0:.0f}s. Aceptando peticiones.\n")

    cdir = os.path.join(ARGS.outdir, "_constraints")
    crudo_dir = os.path.join(ARGS.outdir, "_crudo")
    os.makedirs(cdir, exist_ok=True)
    os.makedirs(crudo_dir, exist_ok=True)

    while True:
        jid = COLA.get()
        with LOCK:
            t = TRABAJOS[jid]
            t["estado"] = "generando"
            t["inicio"] = time.time()
        try:
            pet = t["peticion"]
            n_frames = int(round(pet["duration"] * fps))
            semilla = pet["seed"] if pet["seed"] is not None else uuid.uuid4().int % (2 ** 31 - 1)

            # los constraints se construyen igual que en el lote: reutilizamos
            # build_constraints() para que la API y el catalogo no diverjan
            clip = {"id": jid, "duration": pet["duration"], "root_policy": pet["policy"]}
            cpath = build_constraints(clip, fps, os.path.join(cdir, jid + ".json"))
            constraints = load_constraints(cpath, esq_in, ARGS.device)

            crudos = []
            for k in range(pet["candidates"]):
                torch.manual_seed(semilla + k)
                np.random.seed((semilla + k) % (2 ** 31))
                out = modelo(
                    prompts=[pet["prompt"]],      # lista, no string: ver generate_inproc.py
                    num_frames=n_frames,
                    num_denoising_steps=d["diffusion_steps"],
                    constraint_lst=constraints,
                    cfg_weight=d["cfg_weight"],
                    cfg_type=d["cfg_type"],
                    post_processing=True,
                    return_numpy=False,
                )
                destino = os.path.join(crudo_dir, f"{t['slug']}__{jid[:8]}__v{k}.bvh")
                save_motion_bvh(destino, out["local_rot_mats"], out["root_positions"],
                                skeleton=esq_out, fps=fps,
                                standard_tpose=d.get("bvh_standard_tpose", True))
                crudos.append(destino)

            # 2) postproceso: contactos de pie, suelo, politica de root, loop.
            #    Sin esto el clip patina en Unity, que es el problema que motivo
            #    todo el pipeline. El BVH limpio va a --outdir; el crudo se queda
            #    en _crudo/ por si hace falta comparar.
            with LOCK:
                t["estado"] = "postproceso"
            limpios, qc = [], []
            for ruta in crudos:
                rep = postprocess.process(
                    ruta, ARGS.outdir,
                    policy=pet["policy"],
                    loop="gait" if pet["policy"] == "strip_xz" else None,
                )
                limpios.append(os.path.join(ARGS.outdir, rep["clip"] + ".bvh"))
                qc.append({
                    "clip": rep["clip"],
                    "foot_skate_cm": rep["clean"]["foot_skate_mean_cm_per_frame"],
                    "ground_cm": rep["clean"]["ground_penetration_cm"],
                    "root_speed_m_s": rep.get("root_speed_m_per_s"),
                    "passed": rep["passed"]["all"],
                })

            # 3) FBX, que es lo que Unity puede importar de verdad
            fbx = []
            if ARGS.blender:
                with LOCK:
                    t["estado"] = "fbx"
                fbx = a_fbx(limpios, jid)

            with LOCK:
                t.update(estado="listo", seed=semilla, fin=time.time(),
                         archivos=[os.path.basename(p) for p in limpios],
                         fbx=fbx, qc=qc)
        except Exception as e:                                  # noqa: BLE001
            with LOCK:
                t.update(estado="error", error=f"{type(e).__name__}: {e}",
                         fin=time.time())
        finally:
            COLA.task_done()


# ------------------------------------------------------------------- servidor
PAGINA = """<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Kimodo — generar</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f6f7f9;--panel:#fff;--tx:#1a1d21;--dim:#6b7280;--line:#e3e6ea;
  --ok:#1f9d55;--err:#d64545;--acc:#2f6feb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#14171a;--panel:#1c2024;--tx:#e8eaed;--dim:#9aa2ad;--line:#2b3138;
  --ok:#35c46e;--err:#f0655f;--acc:#5b8dff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);padding:24px;
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:20px;margin:0 0 16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin-bottom:16px}
label{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--dim);margin-bottom:4px;font-weight:600}
textarea,select,input{width:100%;padding:9px 11px;border:1px solid var(--line);
  border-radius:7px;background:var(--bg);color:var(--tx);font:inherit;margin-bottom:12px}
textarea{resize:vertical;min-height:64px}
.row{display:flex;gap:12px}.row>div{flex:1}
button{background:var(--acc);color:#fff;border:0;border-radius:7px;padding:10px 18px;
  font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-size:11px;text-transform:uppercase}
tr:last-child td{border-bottom:none}
.e{font-size:11px;padding:2px 8px;border-radius:99px;font-weight:600}
.e-listo{background:var(--ok);color:#fff}.e-error{background:var(--err);color:#fff}
.e-generando{background:var(--acc);color:#fff}.e-encolado{background:var(--line);color:var(--dim)}
a{color:var(--acc)}code{font-family:ui-monospace,monospace;font-size:12px}
.hint{color:var(--dim);font-size:12px;margin-top:-6px;margin-bottom:12px}
</style></head><body><div class="wrap">
<h1>Kimodo — generar clip</h1>
<div class="card">
  <label>prompt</label>
  <textarea id="p" placeholder="A person walks forward at a casual pace."></textarea>
  <div class="hint">Corto, tercera persona, presente, una sola accion. Nada de
    "in place" ni "seamless loop": eso lo resuelve la politica de root.</div>
  <div class="row">
    <div><label>duracion (s)</label><input id="d" type="number" value="5" min="1" max="15" step="0.5"></div>
    <div><label>politica de root</label><select id="pol">
      <option value="keep">keep — one-shot, conserva el desplazamiento</option>
      <option value="strip_xz">strip_xz — loop de locomocion</option>
      <option value="pin_origin">pin_origin — idle / torso, sin desplazarse</option>
    </select></div>
    <div><label>candidatos</label><input id="c" type="number" value="1" min="1" max="4"></div>
  </div>
  <button id="b" onclick="enviar()">Generar</button>
</div>
<div class="card"><h1 style="font-size:13px;text-transform:uppercase;color:var(--dim)">cola</h1>
<table id="t"><tr><th>clip</th><th>estado</th><th>tiempo</th><th>archivos</th></tr></table></div>
</div>
<script>
async function enviar(){
  const b=document.getElementById('b'); b.disabled=true;
  try{
    const r=await fetch('/api/generar',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:document.getElementById('p').value,
        duration:parseFloat(document.getElementById('d').value),
        policy:document.getElementById('pol').value,
        candidates:parseInt(document.getElementById('c').value)})});
    const j=await r.json();
    if(!r.ok) alert('Error: '+(j.error||r.status));
  }catch(e){alert('Error: '+e)}
  b.disabled=false; refrescar();
}
async function refrescar(){
  try{
    const j=await (await fetch('/api/trabajos')).json();
    document.getElementById('t').innerHTML =
      '<tr><th>clip</th><th>estado</th><th>tiempo</th><th>archivos</th></tr>' +
      j.trabajos.map(t=>{
        const seg = t.fin&&t.inicio ? (t.fin-t.inicio).toFixed(0)+'s'
                  : t.inicio ? '…' : '';
        const enl = f => `<a href="/api/archivo/${encodeURIComponent(f)}">${f.split('__').pop()}</a>`;
        const links = [...(t.fbx||[]).map(enl), ...(t.archivos||[]).map(enl)].join(' ');
        const qc = (t.qc||[]).map(q =>
          `<code style="color:${q.passed?'var(--ok)':'var(--err)'}">` +
          `skate ${q.foot_skate_cm.toFixed(2)}cm · suelo ${q.ground_cm.toFixed(2)}cm` +
          (q.root_speed_m_s ? ` · ${q.root_speed_m_s.toFixed(2)}m/s` : '') + `</code>`).join('<br>');
        return `<tr><td><code>${t.slug}</code></td>
          <td><span class="e e-${t.estado}">${t.estado}</span></td>
          <td>${seg}</td>
          <td>${t.error?'<code>'+t.error+'</code>':links+(qc?'<br>'+qc:'')}</td></tr>`;
      }).join('');
  }catch(e){}
  setTimeout(refrescar,3000);
}
refrescar();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "kimodo"

    def _responder(self, codigo, cuerpo, tipo="application/json"):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo).encode("utf-8")
        elif isinstance(cuerpo, str):
            cuerpo = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _pedir_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="kimodo"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _auth_ok(self):
        if autorizado(self.headers.get("Authorization")):
            return True
        time.sleep(0.5)          # frena el barrido de contrasenas
        self._pedir_auth()
        return False

    def do_GET(self):
        if not self._auth_ok():
            return
        if self.path == "/":
            return self._responder(200, PAGINA, "text/html; charset=utf-8")
        if self.path == "/api/trabajos":
            with LOCK:
                ts = sorted(TRABAJOS.values(), key=lambda t: t["creado"], reverse=True)
                return self._responder(200, {"trabajos": ts[:40]})
        if self.path.startswith("/api/archivo/"):
            from urllib.parse import unquote
            pedido = unquote(self.path[len("/api/archivo/"):])
            # Solo servimos nombres que ESTE proceso escribio, comprobados contra
            # la tabla de trabajos y no contra el disco. Asi ni un ".." ni un
            # nombre inventado llegan a tocar el sistema de archivos.
            with LOCK:
                bvhs = {f for t in TRABAJOS.values() for f in t.get("archivos", [])}
                fbxs = {f for t in TRABAJOS.values() for f in t.get("fbx", [])}
            if pedido in fbxs:
                ruta, tipo = os.path.join(ARGS.outdir, "fbx", pedido), "application/octet-stream"
            elif pedido in bvhs:
                ruta, tipo = os.path.join(ARGS.outdir, pedido), "text/plain; charset=utf-8"
            else:
                return self._responder(404, {"error": "no encontrado"})
            if not os.path.exists(ruta):
                return self._responder(404, {"error": "aun no escrito"})
            with open(ruta, "rb") as f:
                return self._responder(200, f.read(), tipo)
        return self._responder(404, {"error": "ruta desconocida"})

    def do_POST(self):
        if not self._auth_ok():
            return
        if self.path != "/api/generar":
            return self._responder(404, {"error": "ruta desconocida"})
        if MODELO is None:
            return self._responder(503, {"error": "el modelo aun se esta cargando"})
        if COLA.qsize() >= MAX_COLA:
            return self._responder(429, {"error": f"cola llena ({MAX_COLA})"})

        largo = int(self.headers.get("Content-Length", 0))
        if largo <= 0 or largo > 64 * 1024:
            return self._responder(400, {"error": "cuerpo vacio o demasiado grande"})
        try:
            cuerpo = json.loads(self.rfile.read(largo))
        except json.JSONDecodeError:
            return self._responder(400, {"error": "JSON invalido"})

        pet, err = validar(cuerpo)
        if err:
            return self._responder(400, {"error": err})

        jid = uuid.uuid4().hex
        with LOCK:
            TRABAJOS[jid] = {"id": jid, "slug": slug(pet["prompt"]), "peticion": pet,
                             "estado": "encolado", "creado": time.time(),
                             "inicio": None, "fin": None, "archivos": []}
        COLA.put(jid)
        return self._responder(202, {"id": jid, "estado": "encolado",
                                     "por_delante": COLA.qsize() - 1})

    def log_message(self, *a):
        pass


def main():
    global ARGS, USER, PASS
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, help="de aqui salen fps, cfg y pasos")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--model", default="kimodo-soma-rp")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--low-vram", action="store_true")
    ap.add_argument("--blender", default="",
                    help="ruta a blender.exe; sin esto se sirve solo BVH, y "
                         "Unity necesita FBX")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = solo esta maquina (default); 0.0.0.0 = red")
    ARGS = ap.parse_args()

    USER = os.environ.get("KIMODO_USER")
    PASS = os.environ.get("KIMODO_PASS")
    if not USER or not PASS:
        sys.exit("Falta KIMODO_USER y/o KIMODO_PASS en el entorno. "
                 "Sin credenciales no arranco.")
    if len(PASS) < 12:
        sys.exit("KIMODO_PASS es demasiado corta: usa 12 caracteres o mas.")

    if ARGS.blender and not os.path.exists(ARGS.blender):
        sys.exit(f"no encuentro blender en {ARGS.blender}")
    if not ARGS.blender:
        print("AVISO: sin --blender solo se sirven BVH. Unity importa FBX.")

    os.makedirs(ARGS.outdir, exist_ok=True)
    threading.Thread(target=arrancar_worker, daemon=True).start()

    if ARGS.host != "127.0.0.1":
        print("AVISO: escuchando fuera de localhost. Basic auth NO va cifrado; "
              "exponlo solo detras de HTTPS (ngrok, Cloudflare Tunnel...).")
    print(f"API en http://{ARGS.host}:{ARGS.port}  (usuario: {USER})")
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
