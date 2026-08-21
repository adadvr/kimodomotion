# Orden de trabajo — PASS 2 · 657 clips

> Para el agente de Windows. El brief general (instalación, VRAM, verificaciones)
> está en `AGENTE_WINDOWS.md` y **no cambia**. Esto es solo qué generar ahora.

## Qué hay que hacer

Generar el catálogo completo de la librería de acciones: **657 clips**.

```powershell
git pull                       # el commit debe ser e9e5168 o posterior
cd scripts

# 1. generar (lo largo)
python generate.py    --catalog ../catalog/pass2_action_library.json --outdir ../raw_pass2 --low-vram

# 2. limpiar, elegir el mejor candidato por clip y organizar
python run_catalog.py --catalog ../catalog/pass2_action_library.json --raw ../raw_pass2 --out ../kimodo_animations_pass2

# 3. exportar a FBX humanoide
python to_fbx.py --in ../kimodo_animations_pass2 --out ../kimodo_animations_pass2/fbx
```

**El catálogo es el JSON.** Los `.md` de esta carpeta son documentación, no entrada
de ningún script.

## Además: 3 clips sueltos de test

En la misma tanda, generar también estos tres de `pass1_v2_validation.json`
(quedaron fuera de la entrega anterior):

```powershell
python generate.py --catalog ../catalog/pass1_v2_validation.json --outdir ../raw_gtest --low-vram --only loco_walk_test_person,loco_walk_test_man,loco_walk_test_woman
```

Si `--only` no existe en el script, genera el catálogo entero de `pass1_v2` (son 7
clips, 4 de ellos ya entregados: no pasa nada por repetirlos).

Son la misma caminata con el sujeto cambiado (`person` / `man` / `woman`) y sirven
para medir si el modelo responde al género. De eso depende que 51 clips de estilo
del catálogo valgan la pena o no.

## Presupuesto

657 clips × `num_samples: 4` = **2628 generaciones**. Si eso es demasiado para una
primera vuelta, baja `num_samples` a `2` en el bloque `defaults` del JSON: son 1314
y siempre se puede regenerar después lo que salga flojo.

## Verificación antes de entregar

`run_catalog.py` escribe `qc_report.json`. Revisa dos cosas:

1. **Rechazados.** Los que caen en `_rejected/` no se entregan: se **regeneran**, no
   se recortan. Las causas típicas son un loop de locomoción sin ciclo de marcha o
   una cola congelada de más del 25 %.
2. **Cuántos clips faltan** respecto a los 657. El `manifest.json` de salida trae un
   campo `missing` con los que no encontraron candidato.

Si más del 10 % falla, **detente y reporta** antes de exportar FBX: probablemente
haya algo sistemático mal y no vale la pena procesar el resto.

## Qué entregar

Un zip con la carpeta `kimodo_animations_pass2/` completa, es decir:

```
kimodo_animations_pass2/
  manifest.json          <- IMPRESCINDIBLE, sin él el plugin no sabe emparejar
  qc_report.json
  combat/  contact/  locomotion/  transition/  upper/  reaction/  talk/
  fbx/                   <- los FBX, en las mismas subcarpetas
  _rejected/             <- inclúyelo, sirve para diagnosticar
```

El `manifest.json` tiene que llevar, por cada clip, los campos `pairId`, `pairRole`
y `contactAt` que vienen del bloque `taxonomy` del catálogo. `run_catalog.py` ya los
copia solo — solo hay que comprobar que están.

## Contexto: por qué los prompts están escritos así

Estos prompts vienen de dos rondas de medición en Unity. Dos reglas que **no hay que
"mejorar"** al vuelo:

- **Los golpes terminan con `the arm completely straight at full reach`** y **no
  mencionan la retracción.** Pedir extender *y* retraer hace que el modelo promedie
  y entregue una finta: medido, 7 cm de alcance en vez de 40.
- **Las reacciones llevan `without stepping away` y `root_policy: pin_origin`.** Sin
  eso retroceden un metro dentro del propio clip, horneado en los huesos, y el
  personaje se sale del alcance de quien le pega.

Si un clip sale mal, repórtalo con su id y su medición — no reescribas el prompt sin
avisar, porque el catálogo va sincronizado con el plugin de Unity.
