# Correr el catálogo en vast.ai con $1.15

## ¿Alcanza? Sí, pero hay que elegir bien la máquina

Lo que te van a cobrar son **tres cosas**, no una:

| concepto | cuánto | cómo controlarlo |
|---|---|---|
| GPU por hora | $0.13–0.40/h en una RTX 4090 | filtra por precio, ordena por `$/hr` |
| **Internet de bajada** | varía por host, **es el que te puede matar** | filtra hosts con inet barato o gratis |
| Disco | ~$0.10/GB al mes | pide 60 GB, y **borra** la instancia al final |

El gasto real de tu trabajo:

- Descarga de pesos: ~20 GB (Llama-3-8B pesa 16 GB — es el text encoder de Kimodo). **Esto es lo caro si el host cobra bandwidth.**
- Generación: 50 clips × 2 variantes = 100 clips × ~25 s ≈ **45 minutos de GPU**.
- Descarga de resultados: unos pocos MB. Nada.

**Estimado: $0.50–0.90.** Con $1.15 te alcanza, con margen, si sigues las reglas de abajo.

---

## Antes de rentar: el trámite de Hugging Face

Kimodo usa **Llama-3-8B-Instruct** para entender el texto del prompt, y ese modelo está restringido. Sin esto no arranca en ninguna máquina:

1. Crea cuenta en [huggingface.co](https://huggingface.co) (gratis).
2. Entra a [meta-llama/Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) y acepta la licencia. La aprobación suele ser inmediata.
3. Crea un token en [Settings → Tokens](https://huggingface.co/settings/tokens) (tipo *read*). Cópialo, empieza con `hf_`.

Haz esto **antes** de rentar. Si la aprobación tarda, no quemas saldo esperando.

---

## Elegir la máquina

En el buscador de vast.ai:

- **GPU:** RTX 4090 o RTX 3090. Con 24 GB te sobra.
- **Precio:** menos de $0.30/h.
- **Disco:** 60 GB.
- **Internet de bajada:** ordena o filtra por este número. Busca hosts con **inet down barato o en $0.00** y velocidad decente (>200 Mbps). Este es el filtro más importante con tu presupuesto.
- **Imagen (template):** cualquiera de PyTorch 2.x con CUDA. `pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime` funciona.

---

## Los pasos

**1.** Sube `kimodo_pipeline.zip` a `/workspace` (arrástralo en la UI de vast, o `scp`).

**2.** Abre la terminal de la instancia y corre:

```bash
cd /workspace
unzip -o kimodo_pipeline.zip
export HF_TOKEN=hf_tu_token_aqui
bash kimodo_pipeline/scripts/vast_bootstrap.sh smoke
```

Esto instala todo, descarga los pesos y genera **2 clips de prueba**. Tarda 15–20 min (casi todo es la descarga) y cuesta centavos.

**Si ves `OK loco_walk_neutral`, funciona.** Si no, párate ahí y revisa el error — no lances el catálogo completo con algo roto, que ahí es donde se va el dinero.

**3.** El catálogo completo:

```bash
bash kimodo_pipeline/scripts/vast_bootstrap.sh full
```

~45 min. Al terminar te deja `/workspace/kimodo_animations.zip` con los BVH limpios, organizados por categoría y con el `manifest.json`.

**4.** Descarga el zip.

**5.** ⚠️ **BORRA la instancia** (botón de basura), no le des solo *Stop*. Una instancia detenida sigue cobrando el disco.

---

## Si vas justo de saldo

- `CANDIDATES=1 bash kimodo_pipeline/scripts/vast_bootstrap.sh full` → la mitad de tiempo, pero sin variantes para elegir. Los clips con prop (linterna, pistola, caja) van a salir peor.
- Genera por categoría y descarga entre tandas:
  ```bash
  cd /workspace/kimodo_pipeline/scripts
  python generate.py --catalog ../catalog/kimodo_catalog.json --outdir /workspace/raw \
      --backend cli --candidates 2 --category locomotion
  ```
  El progreso se guarda en `raw/state.json`: si se corta o borras la máquina, al relanzar sigue donde iba.

---

## El FBX se hace en tu Mac, no en vast

No gastes GPU en eso. Bajas los BVH, instalas Blender en el Mac y corres:

```bash
blender --background --python to_fbx.py -- --input kimodo_animations --out fbx
```

Fuentes: [precios de vast.ai](https://docs.vast.ai/documentation/instances/pricing) · [RTX 4090 en vast.ai](https://vast.ai/pricing/gpu/RTX-4090) · [instalación de Kimodo](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html)
