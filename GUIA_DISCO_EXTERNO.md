# Instalar Kimodo con el disco externo (interno con 50 GB libres)

## Cuánto espacio pide en realidad

| qué | tamaño | dónde ponerlo |
|---|---|---|
| Pesos de Llama-3-8B (el text encoder) | ~16 GB | **externo** |
| Pesos del modelo de movimiento | ~1–2 GB | externo |
| PyTorch + CUDA + dependencias | ~6 GB | interno o externo |
| Caché de pip durante la instalación | ~5 GB | externo (o bórralo después) |

Total ~25–30 GB. En tus 50 GB internos *cabe*, pero te deja el disco al filo y Windows se pone lento cuando le queda poco. **Mándalo todo al externo.**

## El detalle que sí importa: no recargues el modelo 100 veces

Aquí hay una trampa. El comando `kimodo_gen` carga el modelo de texto (16 GB) **cada vez que lo llamas**. Si los pesos están en un disco externo USB, cada carga son 2–3 minutos de lectura. Con 100 generaciones eso son **más de 4 horas leyendo disco** — más que generando.

Por eso agregué `generate_inproc.py`: usa la API de Python, carga el modelo **una sola vez** y genera las 100 sin volver a tocar esos 16 GB. Con el disco externo no es una optimización bonita, es la diferencia entre 3 horas y 8.

```bat
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --candidates 2 --low-vram
```

Te va imprimiendo el tiempo estimado que falta. Guarda también el `.npz` de cada clip, que trae los contactos de pie que calculó el propio modelo.

## Mandar todo al externo

Suponiendo que el externo sea `E:` — cambia la letra por la tuya:

```bat
mkdir E:\kimodo\hf
mkdir E:\kimodo\pipcache

:: los 16 GB de pesos se van aquí
setx HF_HOME "E:\kimodo\hf"
setx PIP_CACHE_DIR "E:\kimodo\pipcache"

:: cierra y vuelve a abrir la terminal para que tomen efecto
```

Y el entorno de Python también en el externo:

```bat
conda create -p E:\kimodo\env python=3.10 -y
conda activate E:\kimodo\env

pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install git+https://github.com/nv-tlabs/kimodo.git
pip install numpy scipy "huggingface_hub[cli]"
hf auth login
```

Verifica que sí se fue al externo antes de descargar 16 GB al lugar equivocado:

```bat
python -c "import os,huggingface_hub as h; print(h.constants.HF_HUB_CACHE)"
```

Tiene que decir algo con `E:\kimodo\hf`. Si sigue diciendo `C:\Users\...`, cerraste mal la terminal — `setx` solo aplica a las ventanas nuevas.

## Advertencias del disco externo

- **Que sea SSD, no un disco de platos.** Con un HDD USB la carga inicial se va a 5–8 minutos. Sigue funcionando (es una sola vez con `generate_inproc.py`), pero duele.
- **No lo desconectes a media generación.** Si el externo se duerme o se desconecta, el proceso truena. El progreso está en `raw\state.json`, así que relanzas y sigue — pero perdiste el clip en curso.
- En Configuración de Windows, desactiva la suspensión del disco USB para esa unidad.

## El orden completo

```bat
conda activate E:\kimodo\env
set TEXT_ENCODER_DEVICE=cpu
cd C:\ruta\a\kimodo_pipeline\scripts

:: 1. prueba: 2 clips
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --candidates 1 --low-vram --only loco_walk_neutral,loco_idle_breathing

:: 2. catálogo completo (déjalo corriendo)
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --candidates 2 --low-vram

:: 3. limpieza y organización
python run_catalog.py --catalog ..\catalog\kimodo_catalog.json --raw ..\raw --out ..\kimodo_animations
```

El paso 3 no usa GPU ni toca los 16 GB — ese lo puedes correr en la Mac si prefieres.

Fuentes: [API del modelo](https://research.nvidia.com/labs/sil/projects/kimodo/docs/api_reference/model.html) · [export a BVH](https://research.nvidia.com/labs/sil/projects/kimodo/docs/api_reference/exports.html) · [instalación](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html)
