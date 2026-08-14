#!/usr/bin/env bash
# vast_bootstrap.sh — deja lista una maquina de vast.ai para generar el catalogo.
#
# Uso (dentro de la maquina, en /workspace):
#   export HF_TOKEN=hf_xxxxxxxxxxxx
#   bash vast_bootstrap.sh smoke      # prueba con 1 clip  (~5 min, centavos)
#   bash vast_bootstrap.sh full       # catalogo completo
#   bash vast_bootstrap.sh pack       # empaqueta los BVH para descargar
#
# Antes de 'full' revisa que 'smoke' te haya dejado un .bvh valido.

set -euo pipefail
cd /workspace

CAND="${CANDIDATES:-2}"          # 2 variantes por clip. Subelo solo si te sobra saldo.
PIPE=/workspace/kimodo_pipeline
RAW=/workspace/raw

banner() { echo -e "\n\033[1;36m== $* ==\033[0m"; }
t0=$(date +%s)
trap 'echo -e "\n\033[1;33mtiempo total: $(( ($(date +%s)-t0)/60 )) min\033[0m"' EXIT

# ---------------------------------------------------------------- instalacion
setup() {
  banner "instalando kimodo"
  [ -f /workspace/.kimodo_ok ] && { echo "ya instalado, salto"; return; }

  apt-get update -qq && apt-get install -y -qq git zip unzip >/dev/null
  pip install -q --upgrade pip
  pip install -q "git+https://github.com/nv-tlabs/kimodo.git"
  pip install -q numpy scipy "huggingface_hub[cli]"

  if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: falta HF_TOKEN. El text encoder de Kimodo es Llama-3-8B (gated)."
    echo "  1. crea cuenta en huggingface.co"
    echo "  2. acepta la licencia en huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct"
    echo "  3. crea un token en huggingface.co/settings/tokens"
    exit 1
  fi
  hf auth login --token "$HF_TOKEN" --add-to-git-credential || \
    { mkdir -p ~/.cache/huggingface && echo -n "$HF_TOKEN" > ~/.cache/huggingface/token; }

  # descarga los pesos AHORA para que el reloj de generacion no incluya la descarga
  banner "precargando pesos (esto es lo que mas tarda: 10-15 min)"
  python -c "
from huggingface_hub import snapshot_download
snapshot_download('meta-llama/Meta-Llama-3-8B-Instruct',
                  allow_patterns=['*.json','*.safetensors','tokenizer*'])
print('llama ok')
"
  touch /workspace/.kimodo_ok
}

check_pipeline() {
  if [ ! -d "$PIPE" ]; then
    if [ -f /workspace/kimodo_pipeline.zip ]; then
      unzip -q -o /workspace/kimodo_pipeline.zip -d /workspace
    else
      echo "ERROR: sube kimodo_pipeline.zip a /workspace (arrastralo en la UI de vast, o scp)"
      exit 1
    fi
  fi
}

# ------------------------------------------------------------------- acciones
smoke() {
  setup; check_pipeline
  banner "prueba: 1 clip in-place + 1 clip con desplazamiento"
  cd "$PIPE/scripts"
  python generate.py --catalog ../catalog/kimodo_catalog.json --outdir "$RAW" \
      --backend cli --candidates 1 --only loco_walk_neutral,loco_idle_breathing
  ls -la "$RAW"/*.bvh 2>/dev/null || { echo "NO se genero ningun BVH — revisa el error de arriba"; exit 1; }
  python run_catalog.py --catalog ../catalog/kimodo_catalog.json \
      --raw "$RAW" --out /workspace/kimodo_animations
  echo -e "\nSi ves 'OK loco_walk_neutral' arriba, el pipeline funciona. Ahora: bash vast_bootstrap.sh full"
}

full() {
  setup; check_pipeline
  banner "catalogo completo ($CAND variantes por clip)"
  cd "$PIPE/scripts"
  python generate.py --catalog ../catalog/kimodo_catalog.json --outdir "$RAW" \
      --backend cli --candidates "$CAND"
  python run_catalog.py --catalog ../catalog/kimodo_catalog.json \
      --raw "$RAW" --out /workspace/kimodo_animations
  pack
}

pack() {
  banner "empaquetando"
  cd /workspace
  zip -qr kimodo_animations.zip kimodo_animations -x "*_work*"
  du -h kimodo_animations.zip
  echo "Descarga /workspace/kimodo_animations.zip y BORRA la instancia (no 'stop': el disco se sigue cobrando)."
}

case "${1:-smoke}" in
  setup) setup ;;
  smoke) smoke ;;
  full)  full ;;
  pack)  pack ;;
  *) echo "uso: bash vast_bootstrap.sh [smoke|full|pack]"; exit 1 ;;
esac
