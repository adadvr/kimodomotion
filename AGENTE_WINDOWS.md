# Brief para el agente de Windows — generar el catálogo base de animaciones con Kimodo

> Documento de traspaso. Léelo completo antes de ejecutar nada. Los pasos tienen
> puntos de verificación: si uno falla, **detente ahí** y reporta — no sigas al
> siguiente. La mayoría de los errores caros vienen de avanzar con algo roto.

---

## 1. Objetivo

Generar ~50 clips de animación humana con **Kimodo** (modelo de difusión de movimiento de NVIDIA, texto → movimiento), limpiarlos, organizarlos por categoría y exportarlos a FBX humanoide para un plugin de Unity.

El material de trabajo ya existe: hay un catálogo de prompts parametrizado y un pipeline de scripts. **No hay que diseñar nada, hay que ejecutarlo y vigilar la calidad.**

Entregable final: una carpeta `kimodo_animations/` organizada por categoría, con `manifest.json`, más los FBX.

---

## 2. Hardware confirmado

| | |
|---|---|
| GPU | NVIDIA RTX A2000 Laptop GPU |
| VRAM | 4096 MiB (4 GB) |
| Driver | 595.95 (soporta CUDA 12.x) |
| Disco | instalar en el interno, ~50 GB libres |

**Consecuencia crítica de los 4 GB:** Kimodo usa **Llama-3-8B-Instruct** como codificador de texto. En GPU eso pide ~17 GB de VRAM — imposible aquí. Hay que mandar el codificador a la CPU con `TEXT_ENCODER_DEVICE=cpu`, lo que baja el consumo de video a **menos de 3 GB**. Todos los scripts tienen el flag `--low-vram` que pone esa variable por ti.

**Verifica la RAM del sistema antes de empezar.** Con el codificador en CPU, Llama-3-8B vive en RAM: necesitas **16 GB mínimo**, 32 GB cómodo.

```powershell
Get-CimInstance Win32_ComputerSystem | Select @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB)}}
```

Si sale menos de 16 → **detente y reporta.** No hay forma de correrlo así; toca rentar GPU en la nube (ver `GUIA_VASTAI.md`).

**Antes de generar, cierra Unity, Chrome y cualquier cosa que use video.** Con 4 GB no hay margen: Unity sola puede ocupar 1 GB. Si la laptop tiene gráficos híbridos, manda el escritorio a la Intel integrada desde el panel de NVIDIA y deja la A2000 libre.

---

## 3. Requisito bloqueante: acceso a Llama-3

Sin esto no arranca nada, en ninguna máquina. Hazlo **primero**, porque la aprobación puede tardar.

1. Cuenta en [huggingface.co](https://huggingface.co).
2. Aceptar la licencia en [meta-llama/Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct). Suele aprobarse al instante.
3. Token tipo *read* en [Settings → Tokens](https://huggingface.co/settings/tokens). Empieza con `hf_`.

---

## 4. Instalación

En **Anaconda Prompt** (no PowerShell, para evitar problemas de activación de conda):

```bat
conda create -n kimodo python=3.10 -y
conda activate kimodo

pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install git+https://github.com/nv-tlabs/kimodo.git
pip install numpy scipy "huggingface_hub[cli]"

hf auth login
```

Si `hf` no existe (versiones viejas de `huggingface_hub`), usa `huggingface-cli login`.

### ✅ Verificación 1 — PyTorch ve la GPU

```bat
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Debe imprimir `True` y `NVIDIA RTX A2000 Laptop GPU`. Si dice `False`, se instaló la rueda de CPU: desinstala torch y reinstálalo con el índice `cu121` de arriba.

### ✅ Verificación 2 — Kimodo importa

```bat
python -c "from kimodo.model.load_model import load_model; from kimodo.exports.bvh import save_motion_bvh; print('kimodo ok')"
```

### Limpieza

```bat
pip cache purge
```

Recupera ~5 GB. Hazlo, que el disco va justo.

---

## 5. El pipeline: qué hace cada archivo

Descomprime `kimodo_pipeline.zip`. Contiene:

| archivo | qué hace |
|---|---|
| `catalog/kimodo_catalog.json` | **la fuente de verdad.** 50 clips: prompt, duración, política de root, si es loop, si lleva máscara, taxonomía y umbrales de QC |
| `scripts/generate_inproc.py` | **el que debes usar para generar.** Carga el modelo una vez y genera todo |
| `scripts/generate.py` | alternativa que llama al comando `kimodo_gen`. **No la uses aquí** (ver abajo) |
| `scripts/postprocess.py` | limpieza de un clip: contactos de pie, foot skate, suelo, root, loop, métricas |
| `scripts/bvhtools.py` | parser/writer/FK de BVH. No se ejecuta solo |
| `scripts/run_catalog.py` | procesa todo el lote, puntúa, elige el mejor candidato, organiza, escribe `manifest.json` |
| `scripts/to_fbx.py` | Blender headless: BVH → FBX para Unity |
| `scripts/make_test_bvh.py` | BVH sintético para probar el postproceso sin GPU |

**Por qué `generate_inproc.py` y no `generate.py`:** el comando `kimodo_gen` recarga los 16 GB del codificador de texto en cada llamada. Con 100 generaciones eso es más de una hora tirada. `generate_inproc.py` usa la API de Python y carga el modelo una sola vez.

---

## 6. Ejecución

### Paso 1 — prueba de humo (obligatorio)

```bat
conda activate kimodo
cd C:\ruta\a\kimodo_pipeline\scripts

python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --low-vram --candidates 1 --only loco_walk_neutral,loco_idle_breathing
```

La primera vez descarga ~16 GB de pesos: cuenta 15–30 min según tu internet. Esa descarga **no se repite**.

### ✅ Verificación 3 — salieron dos BVH

```bat
dir ..\raw\*.bvh
```

Deben existir `loco_walk_neutral__v0.bvh` y `loco_idle_breathing__v0.bvh`, cada uno de varios cientos de KB. Si están vacíos o no existen, lee el error que imprimió el script y **reporta antes de seguir**.

### Paso 2 — el catálogo completo

```bat
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --low-vram --candidates 2
```

100 generaciones. En una A2000 con el codificador en CPU, calcula **2–4 horas**. El script imprime el tiempo estimado restante.

Si se corta por lo que sea, **relánzalo con el mismo comando**: el progreso vive en `raw\state.json` y continúa donde iba.

Si vas con prisa, `--candidates 1` lo parte a la mitad, a costa de no tener variantes para elegir.

### Paso 3 — limpieza y organización

```bat
python run_catalog.py --catalog ..\catalog\kimodo_catalog.json --raw ..\raw --out ..\kimodo_animations
```

No usa GPU. Procesa cada candidato, lo puntúa, se queda con el mejor y organiza. Imprime una línea por clip: `OK` si pasó QC, `REV` si necesita revisión humana.

### Paso 4 — FBX

Requiere Blender instalado (la versión gratuita del sitio oficial).

```bat
"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" --background ^
    --python to_fbx.py -- --input ..\kimodo_animations --out ..\fbx
```

Tampoco usa GPU.

---

## 7. Cómo saber si un clip está bien

`run_catalog.py` escribe `kimodo_animations\qc_report.json` con métricas por clip. Las que importan:

| métrica | qué significa | valor aceptable |
|---|---|---|
| `foot_skate_mean_cm_per_frame` | cuánto se arrastra el pie mientras debería estar plantado | < 2 cm |
| `ground_penetration_cm` | qué tanto se hunde el pie bajo el suelo | < 2 cm |
| `loop_pose_error_cm` | qué tan lejos queda el último frame del primero | lo más bajo posible |
| `root_speed_m_per_s` | velocidad real del ciclo de caminata | 1.2–1.6 caminando, 3–5 corriendo |

Los clips marcados `REV` no están necesariamente mal: revísalos visualmente (Blender abre BVH directo) antes de descartarlos. Los clips con prop imaginario (linterna, pistola, caja) son los que más fallan — a esos súbeles `--candidates` y quédate con el mejor.

`root_speed_m_per_s` va también al `manifest.json`, y **es un dato de producción, no de diagnóstico**: el sistema que mueve al personaje en el juego tiene que usar esa velocidad. Si el clip camina a 1.35 m/s y el juego lo desplaza a 2 m/s, los pies patinan en pantalla aunque el BVH esté perfecto.

---

## 8. Lo que NO debes hacer

- **No edites los prompts para meter instrucciones tipo "in place", "seamless loop" o "feet planted".** Kimodo no entiende ese lenguaje; solo diluye la señal del texto y baja la calidad. Eso ya se resuelve con constraints (`root2d`) y con el postproceso.
- **No pases `--no-postprocess`.** Kimodo trae su propia optimización de foot skate y la queremos activa.
- **No uses `generate.py` en esta máquina** (recarga el modelo en cada clip).
- **No corras Blender ni el postproceso mientras generas.** Con 4 GB de VRAM compite por memoria.
- **No borres `raw\state.json`** salvo que quieras regenerar todo desde cero.
- **No cambies la escala al exportar FBX.** Los BVH de Kimodo están en centímetros y `to_fbx.py` ya aplica el 0.01 a metros. Si lo tocas, en Unity el personaje mide 170 unidades.

---

## 9. Errores conocidos

| síntoma | causa | qué hacer |
|---|---|---|
| `CUDA out of memory` | el codificador se fue a la GPU, o algo más la está usando | usa `--low-vram`; cierra Unity/Chrome; revisa con `nvidia-smi` qué ocupa la VRAM |
| `401` / `403` / `gated repo` | no aceptaste la licencia de Llama-3, o el token no tiene permiso | vuelve al paso 3 |
| `torch.cuda.is_available()` da `False` | se instaló la rueda de CPU | reinstala torch con el índice `cu121` |
| `no encontre el skeleton en el modelo` | la API cambió de nombre entre versiones | el propio error trae el comando de introspección: córrelo y reporta la salida |
| aviso `no pude convertir los constraints` | el nombre de la función de constraints cambió | no es bloqueante: el postproceso igual clava el root con `pin_origin`. Anótalo y sigue |
| `No pude identificar huesos de pierna` | los nombres del esqueleto no coinciden con la heurística | reporta con la lista de huesos del BVH; hay que pasar overrides a `detect_key_joints` |
| generación muy lenta | 100 pasos de difusión con el encoder en CPU | baja `diffusion_steps` a 50 en `catalog/kimodo_catalog.json` → `defaults` |
| RAM llena / swap | Llama-3-8B en CPU con menos de 16 GB | no hay arreglo local; ver `GUIA_VASTAI.md` |

---

## 10. Reglas del proyecto

- La salida se organiza en **`kimodo_animations/`** por categoría: `locomotion/`, `transition/`, `upper/`, `reaction/`. `run_catalog.py` ya lo hace.
- Solo archivos **BVH** como fuente (el FBX es derivado).
- **Si hay varios archivos del mismo clip, gana el de sufijo numérico más alto** (`clip 2.bvh` sobre `clip.bvh`). Es la regla del proyecto y `run_catalog.py` la implementa.
- Los candidatos perdedores no se borran: quedan en `_rejected/`.

---

## 11. Qué reportar al terminar

1. Cuántos clips pasaron QC de los 50 (lo imprime `run_catalog.py` al final).
2. La lista de clips en `REV` y por qué (qué métrica se pasó del umbral).
3. Los clips en `missing` del `manifest.json` — los que ni se generaron.
4. Cualquier aviso de la tabla de errores conocidos que haya aparecido.
5. Tiempo total y si hubo cortes.

---

## 12. Contexto: por qué el pipeline hace lo que hace

Vale la pena entender esto, porque es lo que separa un clip usable de uno que se ve mal en el juego.

**Kimodo genera desplazamiento de la cadera** (root motion). Un clip de caminata avanza de verdad en el espacio. Eso crea dos problemas para una librería de clips combinables:

1. Si reproduces ese clip sin aplicar root motion, el personaje se queda en el sitio pero las piernas siguen ejecutando el paso de avanzar → **patina**.
2. Si le pones la traslación en cero a lo bruto, el pie que está plantado en el suelo se arrastra hacia atrás durante todo el ciclo → **patina peor**.

La solución correcta parte de un principio físico: **mientras un pie está en contacto con el suelo, su velocidad horizontal es cero, y toda esa velocidad pertenece al root.** `postprocess.py` detecta los frames de contacto, integra la velocidad del pie plantado, se la transfiere al root, y hasta entonces separa las dos cosas: te deja un BVH *in-place* limpio para loopear, y un `.root.json` aparte con la trayectoria y la velocidad media real.

Por eso hay tres políticas de root en el catálogo, una por tipo de clip:

- `strip_xz` — loops de locomoción. Se genera con desplazamiento libre (el modelo camina mejor así) y se separa después.
- `pin_origin` — idles, acciones de torso, reacciones. Se pide al modelo que no se desplace, con un constraint `root2d` clavado en (0,0).
- `keep` — transiciones de una sola vez (sentarse, caer, esquivar). Ahí el desplazamiento **es** la acción y se conserva.

---

Referencias: [Kimodo](https://github.com/nv-tlabs/kimodo) · [instalación](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html) · [API del modelo](https://research.nvidia.com/labs/sil/projects/kimodo/docs/api_reference/model.html) · [export BVH](https://research.nvidia.com/labs/sil/projects/kimodo/docs/api_reference/exports.html) · [constraints](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/constraints.html)
