# Correr Kimodo en tu laptop HP (RTX A2000 / 4 GB de video, 32 GB de RAM)

## Veredicto: sí corre, y es la mejor opción que tienes

Tu combinación es **mejor** para esto que la de mucha gente con una tarjeta más grande, porque el cuello de botella real de Kimodo no es la GPU: son los 16 GB que ocupa el modelo de texto (Llama-3-8B). Ese modelo lo mandas a la RAM del sistema, y tú tienes **32 GB** — de sobra.

| requisito | lo que pide | lo que tienes |
|---|---|---|
| VRAM con `TEXT_ENCODER_DEVICE=cpu` | < 3 GB | 4 GB ✅ |
| RAM del sistema | ~16 GB | 32 GB ✅ |
| Disco | ~25 GB | (revisa) |

Sin esa variable pediría 17 GB de VRAM y no arrancaría. Con ella, corre.

**Lo que ganas:** no gastas los $1.15 de vast.ai, y puedes generar todas las variantes que quieras sin mirar el reloj. Si un clip sale feo, lo vuelves a tirar con otro seed y ya.

**Lo que pierdes:** velocidad. Calcula ~40–90 segundos por clip en vez de ~25. Para el catálogo completo (50 clips × 2 variantes) son **2 a 3 horas** — pero las dejas corriendo y te vas.

---

## Instalación (Windows, ~40 min casi todo descargas)

### Antes de nada: el trámite de Hugging Face

1. Cuenta en [huggingface.co](https://huggingface.co).
2. Acepta la licencia en [meta-llama/Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct). Aprobación casi inmediata.
3. Token *read* en [Settings → Tokens](https://huggingface.co/settings/tokens). Empieza con `hf_`.

*(Si la licencia te la niegan o tarda, más abajo está el plan B sin modelo restringido.)*

### Los comandos

Instala [Miniconda](https://docs.conda.io/en/latest/miniconda.html) y abre **Anaconda Prompt**:

```bat
conda create -n kimodo python=3.10 -y
conda activate kimodo

:: PyTorch con CUDA (esto es lo que usa tu RTX)
pip install torch --index-url https://download.pytorch.org/whl/cu121

pip install git+https://github.com/nv-tlabs/kimodo.git
pip install numpy scipy "huggingface_hub[cli]"

hf auth login
:: pega tu token cuando lo pida
```

### La prueba de fuego

```bat
set TEXT_ENCODER_DEVICE=cpu
kimodo_gen "A person walks forward." --duration 5.0 --bvh --output prueba
```

La primera vez descarga ~16 GB de pesos, así que tardará. Si al final tienes un `prueba.bvh`, **ya está todo hecho** — el resto es solo lanzar el catálogo.

> Abre el Administrador de tareas mientras corre. Si ves la VRAM pegada en 4 GB y el disco a tope, es que **no** tomó la variable: la GPU está intentando cargar el modelo de texto. Ciérralo y revisa el `set`.

---

## Espacio en disco (instalación en el disco interno)

Con **50 GB libres alcanza**, pero sin lujos:

| qué | tamaño |
|---|---|
| Pesos de Llama-3-8B (el text encoder) | ~16 GB |
| Pesos del modelo de movimiento | ~1–2 GB |
| PyTorch + CUDA + dependencias | ~6 GB |
| Caché de pip (temporal) | ~5 GB |

Son ~28 GB, y te quedan unos 20 libres. Dos cosas para no quedarte corto:

```bat
:: después de instalar, libera la caché de pip (~5 GB)
pip cache purge
```

Y los BVH generados no pesan nada (unos pocos MB en total), así que por ahí no te preocupes.

---

## Generar el catálogo

```bat
conda activate kimodo
cd C:\ruta\a\kimodo_pipeline\scripts

:: prueba con 2 clips primero
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --low-vram --candidates 1 --only loco_walk_neutral,loco_idle_breathing

:: si eso salió bien, el catálogo completo (déjalo corriendo)
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --low-vram --candidates 2

:: limpieza + organización (esto no usa GPU, lo puedes correr hasta en la Mac)
python run_catalog.py --catalog ..\catalog\kimodo_catalog.json --raw ..\raw --out ..\kimodo_animations
```

**Usa `generate_inproc.py`, no `generate.py`.** La diferencia: `generate.py` llama al comando `kimodo_gen` una vez por clip, y cada llamada recarga los 16 GB del modelo de texto. `generate_inproc.py` usa la API de Python y lo carga **una sola vez** para las 100 generaciones. En disco interno eso te ahorra una hora larga; en un disco externo te ahorraría cinco.

El flag `--low-vram` pone `TEXT_ENCODER_DEVICE=cpu` por ti, así que no depende de que te acuerdes del `set`.

Si se corta (se reinicia, se cierra, lo que sea): **relánzalo igual**. El progreso vive en `raw\state.json` y sigue donde iba.

---

## Plan B: sin el modelo restringido

Si el acceso a Llama-3 se complica, hay un [encoder NF4 de la comunidad](https://gist.github.com/Aero-Ex/3affd23c4c9632dbff3045f4ae3655ec) que lo reemplaza: no está restringido, pesa mucho menos, y trae un flag `--offload` pensado justo para tarjetas de menos de 8 GB. Es una instalación más manual (hay que apuntar una ruta a mano en un archivo del repo) pero te salta todo el trámite.

---

## Después: el FBX

Blender en la misma laptop, no necesita GPU:

```bat
blender --background --python to_fbx.py -- --input ..\kimodo_animations --out ..\fbx
```

---

## Si algo falla

| síntoma | causa casi segura |
|---|---|
| `CUDA out of memory` | no tomó `TEXT_ENCODER_DEVICE=cpu` |
| `401` / `gated repo` al descargar | falta aceptar la licencia de Llama-3 o el token está mal |
| Va lentísimo y la GPU está al 0% | PyTorch se instaló sin CUDA. Verifica: `python -c "import torch; print(torch.cuda.is_available())"` → tiene que decir `True` |
| `kimodo_gen` no se reconoce | falta `conda activate kimodo` |

Fuentes: [Kimodo (nv-tlabs)](https://github.com/nv-tlabs/kimodo) · [instalación](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html) · [encoder NF4 alternativo](https://gist.github.com/Aero-Ex/3affd23c4c9632dbff3045f4ae3655ec)
