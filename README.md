# Revisión del catálogo Kimodo + pipeline automatizado

## 1. Veredicto rápido

La **estructura** del catálogo está muy bien: la separación locomoción / transiciones / upper-body enmascarable / reacciones es exactamente como se diseña una librería combinable, y sacar la personalidad a style layers en vez de hornearla en los clips es la decisión correcta.

Lo que **no** funciona es la capa de prompts. El catálogo intenta resolver con texto tres cosas que Kimodo no controla por texto: que el clip sea in-place, que sea loopeable y que empiece y termine en pose neutra. Kimodo (el modelo de NVIDIA, `nv-tlabs/kimodo`) está entrenado con descripciones cortas y literales de mocap; frases meta como *"seamless loop"*, *"walking in place without moving forward"* o *"starts and ends with arms relaxed at the sides"* no las entiende — solo diluyen la señal del texto y te bajan la calidad del clip. Esas tres cosas se resuelven con **constraints** y **postproceso**, que es justo lo que Kimodo sí expone.

---

## 2. Los 9 cambios concretos

**1. Fuera los sufijos globales.** Los dos bloques de "suffix to APPEND" hay que borrarlos. Prompt bueno para Kimodo: `A person walks forward at a casual pace.` Corto, tercera persona, presente, una sola acción.

**2. "In place" se pide con constraints, no con palabras.** Kimodo acepta un `constraints.json` con un constraint `root2d` y `smooth_root_2d` clavado en `[0,0]` durante todo el clip. Eso sí obliga al modelo a no desplazarse. Para idles, upper actions y reacciones es lo que hay que usar (ya lo genera `generate.py`).

**3. Pero para locomoción, NO lo uses.** El modelo camina mucho mejor cuando puede avanzar de verdad. Genera libre y quítale el desplazamiento después — que además te da la velocidad real del ciclo, que necesitas para el PathFollow. Es la decisión que tomaste: in-place + curva de root aparte.

**4. Las duraciones son muy cortas.** 1.5–3 s para un loop no alcanza: necesitas al menos dos ciclos completos para poder cortar uno limpio y hacer el crossfade. Subí locomoción a 4–6 s y las upper loops a 5–6 s. El default del CLI (5 s) es un buen número.

**5. Las bookends neutras sí se pueden forzar — con `fullbody` keyframes.** Generas una vez un idle neutro, extraes una pose del NPZ y la reutilizas como constraint `fullbody` en el frame 0 y en el último frame de todas las transiciones. Eso hace que encadenen sin pop de verdad, no "porque el prompt lo pidió". Es el siguiente paso que te recomiendo (el catálogo ya marca qué clip lleva `bookends`).

**6. Kimodo ya te da los contactos de pie.** El NPZ trae `foot_contacts [T,4]` (talón y punta, ambos pies) además de `posed_joints`, `global_rot_mats` y `smooth_root_pos`. Guarda **siempre el NPZ además del BVH**: con los contactos reales el arreglo de foot skate es exacto en vez de heurístico. Y no pases `--no-postprocess`: por defecto Kimodo ya corre su propia optimización de foot skate.

**7. El pipeline de ingest asume un FBX que Kimodo no exporta.** Kimodo escribe NPZ, AMASS NPZ, CSV (G1) y BVH (solo modelos SOMA, con `--bvh`). El FBX lo tienes que producir tú — está resuelto en `to_fbx.py` con Blender headless, con la escala cm→m y los ejes que Unity espera.

**8. Faltan dos vueltas en las transiciones.** Tienes `trans_stand_to_sit_floor` sin el regreso, y `trans_lean_wall_in` sin el `_out`. Si el sistema encadena transiciones, el personaje se queda atrapado en esos dos estados. Yo agregaría además `loco_walk_start` y `loco_walk_stop`: el arranque y el frenado son lo que más se nota como "robótico" en un juego, y no salen de un loop.

**9. Falta política de variación.** Un clip generado no es un clip bueno. El catálogo ahora lleva `base_seed`, N candidatos por clip con seeds derivados deterministas, y umbrales de QC por clip (`max_foot_skate_cm`, `max_ground_penetration_cm`, `require_loop`). Los clips con prop (linterna, pistola, caja) fallan más: súbeles los candidatos.

---

## 3. El problema de los pies, explicado

Lo que estás viendo tiene dos causas distintas y se arreglan diferente:

**Causa A — el root motion está horneado.** Kimodo genera desplazamiento de la cadera. Si importas ese clip en Unity con *Apply Root Motion* apagado, el personaje se queda en el sitio pero las piernas siguen ejecutando el paso de avanzar → patina. Si además le quitas el XZ a lo bruto (poniendo la traslación a cero), el pie que está plantado se arrastra hacia atrás todo el ciclo. Esto es lo que casi seguro te está pasando.

**Causa B — foot skate real del modelo.** El pie no llega a estar exactamente quieto durante el contacto aunque el root sea correcto.

El arreglo correcto para las dos es el mismo principio: **mientras un pie está en contacto, su velocidad horizontal tiene que ser 0, y toda esa velocidad pertenece al root.** `postprocess.py` detecta los contactos, integra la velocidad del pie plantado, se la pasa al root, y *después* separa: te deja un BVH in-place limpio y un `.root.json` con la trayectoria y la velocidad media real en m/s.

Y el detalle que muerde en runtime: **esa velocidad tiene que ser la misma que use tu PathFollow.** Si el clip camina a 1.35 m/s y tu sistema mueve el personaje a 2 m/s, vuelve el patinaje aunque el BVH esté perfecto. Por eso `rootSpeedMs` va en el manifest — úsalo como la velocidad base del clip y escala la reproducción, no la traslación.

Los clips one-shot (sentarse, caer, esquivar) **no** llevan strip: ahí el desplazamiento es parte de la acción y va con `keep`.

---

## 4. Cómo se usa

```bash
pip install numpy scipy
```

### Paso 1 — generar

```bash
# Con Kimodo local (GPU NVIDIA, ~17 GB VRAM o menos con TEXT_ENCODER_DEVICE=cpu)
python generate.py --catalog ../catalog/kimodo_catalog.json --outdir ../raw --backend cli

# Con un endpoint REST (kimodo-api self-host en :9551, PORUZ, o tu propio wrapper)
python generate.py --catalog ../catalog/kimodo_catalog.json --outdir ../raw \
    --backend rest --endpoint http://localhost:9551/generate --sleep 2

# Sin backend: genera la hoja de trabajo para la demo web
python generate.py --catalog ../catalog/kimodo_catalog.json --outdir ../raw --backend manual
```

El modo `manual` escribe un `*.todo.json` por candidato con el prompt exacto, la duración, el seed, el archivo de constraints y el nombre con el que tienes que guardar la descarga. Es tedioso pero determinista, y el resto del pipeline no cambia.

El estado va en `raw/state.json`: si se corta, vuelves a lanzarlo y sigue donde iba.

### Paso 2 — limpiar y organizar

```bash
python run_catalog.py --catalog ../catalog/kimodo_catalog.json --raw ../raw --out ../kimodo_animations
```

Procesa cada candidato, lo puntúa (foot skate + penetración + jitter + calidad de loop), se queda con el mejor, lo organiza por categoría y escribe `manifest.json` y `qc_report.json`. Si hay varios archivos del mismo clip (`clip.bvh`, `clip 2.bvh`), gana el de sufijo más alto — la regla que ya usabas.

Un clip suelto:

```bash
python postprocess.py --input clip.bvh --outdir out --policy strip_xz --loop gait
python postprocess.py --input clip.bvh --outdir out --policy pin_origin --freeze-legs
```

### Paso 3 — FBX para Unity

```bash
blender --background --python to_fbx.py -- --input ../kimodo_animations --out ../fbx
```

Escala cm→m, ejes `-Z forward / Y up`, sin leaf bones (rompen el automapeo de Humanoid), y te escribe `humanoid_map.json` con el mapeo de huesos detectado para que configures el Avatar una vez y lo reuses con *Copy From Other Avatar*.

---

## 5. Archivos

| archivo | qué hace |
|---|---|
| `catalog/kimodo_catalog.json` | los 46 clips con prompts reescritos, duración, política de root, loop, máscara, taxonomía y umbrales de QC |
| `scripts/generate.py` | driver de generación por lotes (CLI / REST / manual), seeds, reintentos, estado reanudable, constraints automáticos |
| `scripts/postprocess.py` | contactos, foot skate, suelo, políticas de root, congelado de piernas, corte de loop con crossfade, métricas |
| `scripts/bvhtools.py` | parser / writer / FK de BVH y detección de huesos por nombre |
| `scripts/run_catalog.py` | lote completo: procesa, puntúa, elige ganador, organiza por categoría, manifest |
| `scripts/to_fbx.py` | Blender headless: BVH → FBX humanoide para Unity |
| `scripts/make_test_bvh.py` | BVH sintético con foot skate a propósito, para probar el pipeline sin GPU |

---

## 6. Lo que todavía no está

- **Bookends neutras con `fullbody` keyframes** (punto 5): hace falta generar el idle neutro primero y extraer la pose del NPZ. Es media hora de trabajo y mejora mucho el encadenado.
- **Usar `foot_contacts` del NPZ** en vez de la heurística de altura/velocidad. La heurística funciona, pero los contactos del modelo son mejores.
- **IK de dos huesos** para el residuo de skate. El método actual corrige por el root, nunca rompe la pose, pero deja residuo cuando los dos pies están en contacto con errores opuestos.
- **Retargeting real** a tu esqueleto. `to_fbx.py` exporta el esqueleto de Kimodo y deja que Unity haga el mapeo Humanoid; si necesitas tu rig exacto, eso se hace en Unity o con Auto-Rig Pro.

---

Fuentes: [Kimodo (nv-tlabs)](https://github.com/nv-tlabs/kimodo) · [CLI](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/cli.html) · [Constraints JSON](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/constraints.html) · [Output formats](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/output_formats.html) · [Generation parameters](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/configuration.html)
