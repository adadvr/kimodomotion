"""progress_server.py — panel de avance del lote, en el navegador.

Levanta un servidor local que lee `raw/state.json` (lo que va escribiendo
generate_inproc.py tras cada generacion) y lo muestra actualizandose solo.
No necesita nada instalado: solo stdlib.

  python progress_server.py --raw C:\\kimodo_work\\raw \\
                            --catalog ..\\catalog\\kimodo_catalog.json

Luego abre http://localhost:8765

El ritmo y el ETA se calculan con las fechas de modificacion de los .bvh, que
es lo unico con marca temporal que deja el generador.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ARGS = None


def leer_estado():
    """Devuelve el resumen que consume el panel."""
    state_path = os.path.join(ARGS.raw, "state.json")
    state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            # el generador puede estar escribiendolo justo ahora
            pass

    with open(ARGS.catalog, encoding="utf-8") as f:
        cat = json.load(f)
    clips = cat["clips"]
    n_cand = ARGS.candidates or cat["defaults"].get("num_samples", 1)
    total = len(clips) * n_cand

    ok = [k for k, v in state.items() if v.get("ok")]
    fallo = {k: v.get("error", "?") for k, v in state.items() if not v.get("ok")}

    # Ritmo y ETA desde los mtime de los BVH.
    # Ojo: NO sirve (ultimo - primero) / n. La carpeta puede tener clips de un
    # smoke test previo o de un lote anterior, y ese hueco de horas dispara la
    # media. Usamos la MEDIANA de los intervalos de la ventana reciente, que
    # ignora tanto los archivos viejos como las pausas por reanudacion.
    bvhs = sorted(glob.glob(os.path.join(ARGS.raw, "*.bvh")), key=os.path.getmtime)
    ritmo_s = eta_min = None
    if len(bvhs) >= 3:
        ts = [os.path.getmtime(p) for p in bvhs[-16:]]
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
        if gaps:
            ritmo_s = gaps[len(gaps) // 2]
            eta_min = ritmo_s * max(0, total - len(ok)) / 60.0

    # estado por clip, agrupado por categoria
    por_cat = {}
    for c in clips:
        fila = {"id": c["id"], "policy": c.get("root_policy"),
                "dur": c.get("duration"), "cands": []}
        for k in range(n_cand):
            v = state.get(f"{c['id']}#{k}")
            if v is None:
                fila["cands"].append("pend")
            elif v.get("ok"):
                fila["cands"].append("ok")
            else:
                fila["cands"].append("fallo")
        por_cat.setdefault(c["category"], []).append(fila)

    ultimo = None
    if bvhs:
        ultimo = {"file": os.path.basename(bvhs[-1]),
                  "hace_s": round(time.time() - os.path.getmtime(bvhs[-1]))}

    return {
        "total": total, "ok": len(ok), "fallo": len(fallo),
        "pendientes": total - len(ok) - len(fallo),
        "errores": fallo, "ritmo_s": ritmo_s, "eta_min": eta_min,
        "por_cat": por_cat, "ultimo": ultimo, "n_cand": n_cand,
        "corriendo": bool(ultimo and ultimo["hace_s"] < 300),
    }


PAGINA = """<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Kimodo — avance del lote</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --tx:#1a1d21; --dim:#6b7280; --line:#e3e6ea;
  --ok:#1f9d55; --fallo:#d64545; --pend:#c7ccd3; --acc:#2f6feb;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#14171a; --panel:#1c2024; --tx:#e8eaed; --dim:#9aa2ad; --line:#2b3138;
  --ok:#35c46e; --fallo:#f0655f; --pend:#3a4149; --acc:#5b8dff;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;padding:24px}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:20px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.live{background:var(--ok);animation:p 1.6s infinite}
.idle{background:var(--dim)}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
.card .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.bar{height:10px;background:var(--pend);border-radius:99px;overflow:hidden;margin-bottom:22px;display:flex}
.bar i{display:block;height:100%}
.bar .b-ok{background:var(--ok)} .bar .b-f{background:var(--fallo)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);
  margin:22px 0 8px;font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;overflow:hidden}
td,th{padding:7px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase}
tr:last-child td{border-bottom:none}
.pol{font-size:11px;color:var(--dim);font-family:ui-monospace,monospace}
.c{display:inline-block;width:13px;height:13px;border-radius:3px;margin-right:4px;vertical-align:-2px}
.c-ok{background:var(--ok)} .c-fallo{background:var(--fallo)} .c-pend{background:var(--pend)}
.err{background:var(--panel);border:1px solid var(--fallo);border-radius:10px;padding:12px;margin-top:8px}
.err code{font-family:ui-monospace,monospace;font-size:12px;color:var(--fallo);display:block;
  margin:3px 0;word-break:break-word}
.foot{color:var(--dim);font-size:12px;margin-top:24px}
</style></head><body><div class="wrap">
<h1>Kimodo — avance del lote</h1>
<div class="sub" id="sub">cargando…</div>
<div class="cards" id="cards"></div>
<div class="bar" id="bar"></div>
<div id="cats"></div>
<div id="errs"></div>
<div class="foot">Se actualiza solo cada 4 s · lee <code>state.json</code></div>
</div>
<script>
const pct = (a,b) => b ? (100*a/b) : 0;
function render(d){
  const vivo = d.corriendo;
  document.getElementById('sub').innerHTML =
    `<span class="dot ${vivo?'live':'idle'}"></span>` +
    (vivo ? 'generando' : 'detenido o terminado') +
    (d.ultimo ? ` · último: <b>${d.ultimo.file}</b> hace ${d.ultimo.hace_s}s` : '') +
    ` · ${d.n_cand} candidato(s) por clip`;

  const eta = d.eta_min == null ? '—'
    : (d.eta_min > 60 ? (d.eta_min/60).toFixed(1)+' h' : Math.round(d.eta_min)+' min');
  const ritmo = d.ritmo_s == null ? '—' : d.ritmo_s.toFixed(0)+' s';
  document.getElementById('cards').innerHTML = [
    ['generadas', `${d.ok} <span style="font-size:15px;color:var(--dim)">/ ${d.total}</span>`],
    ['fallidas', d.fallo], ['pendientes', d.pendientes],
    ['por generación', ritmo], ['tiempo restante', eta],
  ].map(([l,n]) => `<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

  document.getElementById('bar').innerHTML =
    `<i class="b-ok" style="width:${pct(d.ok,d.total)}%"></i>` +
    `<i class="b-f" style="width:${pct(d.fallo,d.total)}%"></i>`;

  document.getElementById('cats').innerHTML = Object.entries(d.por_cat).map(([cat,filas]) => {
    const hechos = filas.filter(f => f.cands.every(c => c==='ok')).length;
    return `<h2>${cat} — ${hechos}/${filas.length} completos</h2><table>
      <tr><th>clip</th><th>política</th><th>dur</th><th>candidatos</th></tr>` +
      filas.map(f => `<tr><td>${f.id}</td><td class="pol">${f.policy}</td>
        <td class="pol">${f.dur}s</td>
        <td>${f.cands.map(c=>`<span class="c c-${c}" title="${c}"></span>`).join('')}</td></tr>`).join('') +
      `</table>`;
  }).join('');

  const es = Object.entries(d.errores);
  document.getElementById('errs').innerHTML = es.length
    ? `<h2>fallos (${es.length})</h2><div class="err">` +
      es.map(([k,v]) => `<code>${k} → ${v}</code>`).join('') + `</div>`
    : '';
}
async function tick(){
  try { render(await (await fetch('/api')).json()); } catch(e){}
  setTimeout(tick, 4000);
}
tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api"):
            cuerpo = json.dumps(leer_estado()).encode("utf-8")
            tipo = "application/json"
        else:
            cuerpo = PAGINA.encode("utf-8")
            tipo = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass  # sin ruido en consola


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="carpeta con state.json y los .bvh")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--candidates", type=int, default=None,
                    help="si no se pasa, usa num_samples del catalogo")
    ap.add_argument("--port", type=int, default=8765)
    ARGS = ap.parse_args()

    print(f"panel en http://localhost:{ARGS.port}   (Ctrl+C para parar)")
    HTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
