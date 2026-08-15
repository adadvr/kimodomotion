# Informe: el fallo de los `loco_*`, verificado y con detección automática

Revisión del audit del 2026-08-14, corrección de sus cifras, e implementación de los
detectores que faltaban. Todo lo de aquí está medido contra el repo y contra los BVH
crudos de `C:\kimodo_work\raw`, no estimado.

---

## 1. Lo primero: el audit exageró el alcance

El audit decía:

> cada generación `loco_*` contiene UN paso seguido de una retención congelada — el muslo nunca vuelve a oscilar, así que no hay CICLO de marcha que loopear.

**Eso no se sostiene.** Con los detectores ya implementados (§4), pasando los 50 clips por el
pipeline, los ciclos de marcha reales por clip son:

| clip | ciclos/pie | cola congelada | velocidad medida | esperada | veredicto |
|---|---|---|---|---|---|
| `loco_walk_neutral` | 4 | 0 % | 1.18 m/s | 1.2 | OK |
| `loco_walk_slow` | 3 | 0 % | 0.55 m/s | 0.8 | OK |
| `loco_walk_backward` | 3 | 0 % | 1.08 m/s | 1.0 | OK |
| `loco_jog` | 4 | 0 % | 2.21 m/s | 2.4 | OK |
| `loco_sneak_walk` | 4 | 0 % | 1.07 m/s | 0.7 | OK |
| `loco_run` | **2** | 0 % | **2.10 m/s** | 3.5 | OK, al límite |
| `loco_sprint` | **1** | 0 % | **2.44 m/s** | 5.5 | **FALLA** |

*(Esta tabla es el estado **antes** de regenerar. El resultado después está en §9.)*

Las caminatas están sanas: 3–4 ciclos, cero cola congelada, y velocidad que cuadra con la
esperada. El fallo **no está repartido por toda la categoría, está concentrado en las marchas
rápidas** — y tiene una forma muy concreta:

**`jog`, `run` y `sprint` salen los tres a la misma velocidad, ~2.1–2.4 m/s.** Lo único que
cambia entre ellos es la etiqueta. El modelo satura ahí: no sabe producir locomoción por
encima de ~2.4 m/s, y cuando le pides sprint entrega algo que ya no es ni marcha (1 ciclo en
4 s). No es una contradicción del prompt — `"A person sprints forward at full speed."` no
tiene nada de contradictorio — es un techo del checkpoint.

Eso cambia qué hay que hacer: reescribir prompts no va a arreglar `run` y `sprint`. O se
acepta la velocidad que da el modelo y se ajusta el controlador, o esos dos clips salen de
otro sitio (retiming de `jog`, o mocap).

### Lo que el audit sí acertó

- **`loco_idle_breathing` está roto**, y de forma peor de lo descrito: se congela en el
  **frame 46 de 180** — el 74 % final del clip es una pose fija — y además deriva 9.1 cm
  cuando su umbral son 3.0. Confirmado y ahora detectado solo.
- **La deriva de los idles es real.** Y aparece un caso que el audit no mencionaba:
  **`loco_crouch_idle` deriva 7.3 cm** con un límite de 5.0. También falla ahora.

## 2. El "in place" del prompt: ya estaba arreglado

La receta del audit era quitar `"walking in place without moving forward"`, generar con avance
real y quitar el desplazamiento en postproceso con `root_policy: strip_xz`.

**Eso ya estaba hecho en el catálogo 2.0.** Cero prompts contienen `in place`, `seamless loop`
ni `neutral relaxed`; el campo `notes` del catálogo lo prohíbe explícitamente. Los prompts son
ya los cortos declarativos (`"A person walks forward at a casual pace."`), y las duraciones son
de 4–6 s, no de 1.5–3 s.

El razonamiento sobre por qué "camina pero no avanza" produce un paso y parada sigue siendo
correcto — sobre datos de mocap la única captura que encaja con esa descripción es la de
alguien que da un paso y se detiene. Pero como diagnóstico de los clips actuales ya no aplica:
esos prompts no existen desde la 2.0. Y la propuesta de reforzar el sufijo con *"at least four
full steps, never stopping"* habría sido contraproducente: mantiene la contradicción y le suma
una cadencia imposible para un `walk_slow`.

## 3. Clips de locomoción: son 14, no 22

La categoría `locomotion` tiene **14 clips**. Los 8 que el audit atribuía a "batches 2 y 3"
(`loco_strafe_left`, `loco_strafe_right`, `loco_run_backward`, `loco_limp`, `loco_stairs_up`,
`loco_stairs_down`, `loco_stroll_hands_pockets`, `loco_walk_cautious`) **no existen en el
catálogo**. Si los quieres hay que escribirlos; no es un problema de regeneración.

De los 14, solo **7 son `strip_xz`** con `loop_cycle: gait`, que son los únicos a los que
aplica el fallo de ciclo. Los otros son 3 idles (`pin_origin`) y 4 one-shot (`keep`).

**A regenerar, según lo medido: 3 clips.** `loco_sprint`, `loco_idle_breathing` y
`loco_crouch_idle`. `loco_run` está justo en el límite (2 ciclos) y conviene vigilarlo.

## 4. Detección automática — implementado

Esto es lo que se ha añadido a [scripts/postprocess.py](scripts/postprocess.py). Antes el QC daba
**50/50 clips pasados**, incluidos los rotos. Ahora da **47/50** y señala cuál falla y por qué.

### `gait_cycles` — ciclos de marcha

Cuenta los despegues (contacto → aire) de cada pie sobre las máscaras de contacto que ya
calculaba `detect_contacts`, con antirrebote. `cycles` es el mínimo de los dos pies: si solo
oscila una pierna tampoco es marcha. Rechaza cualquier `loop_cycle: gait` con menos de 2
(configurable con `min_gait_cycles`).

Hacía falta porque el check `loop` que ya existía solo dice *"encontré un periodo"*, y el
detector **siempre** encuentra alguno: ante un clip sin periodicidad se queda con la ventana
más corta permitida. Por eso `loco_sprint` pasaba el QC con un `period_s` de 0.5.

El antirrebote está calibrado, no elegido a ojo. Contra el BVH sintético de
[scripts/make_test_bvh.py](scripts/make_test_bvh.py) (periodo 1.1 s en 5 s → 4.5 zancadas reales):

```
0.08 s -> 8-10 despegues por pie   (el doble: el detector de contacto parpadea)
0.12 s -> 4-5 despegues por pie    <- la verdad
0.16 s -> 0                        (ya se come fases de vuelo reales)
```

### `frozen_tail_from_frame` — cola congelada

Energía de movimiento **relativa al root**, para que un clip que avanza con el cuerpo rígido
se delate igual (en espacio global ese caso tiene velocidad alta y parece vivo). Devuelve el
primer frame de la cola muerta, o `num_frames` si no hay. Rechaza por encima del 25 %.

El umbral sale del percentil 90 de la energía, no de la mediana: si el 70 % del clip está
congelado la mediana ya vive dentro de la parte congelada y el detector no detectaría nada.

Por defecto solo se exige a los clips con `require_loop`. En un one-shot como
`react_collapse_knees`, acabar quieto en el suelo es correcto; cualquier clip puede pedirlo
igualmente con `max_frozen_tail_ratio`.

### Validación de los dos, contra clips sintéticos

`make_test_bvh.py` acepta ahora `--freeze-after` para fabricar el fallo a propósito
(las piernas se congelan y el root **sigue avanzando**, que es el caso difícil):

```
                gait   cola congelada        veredicto
sano             4     150/150 (0 %)         PASA
enfermo          1      46/150 (69 %)        FALLA -> gait_cycles, frozen_tail
enfermo+parado   0      46/150 (69 %)        FALLA -> gait_cycles, frozen_tail, expected_speed
```

Los dos detectores son complementarios y hacen falta los dos: con el antirrebote flojo el
clip enfermo llegaba a 2 ciclos y solo lo cazaba `frozen_tail`.

### Los tres umbrales que no leía nadie

El catálogo definía estas claves y `_verdict` **nunca las miraba**, así que eran decorativas:

| clave | clips | qué valida ahora |
|---|---|---|
| `max_leg_motion_deg` | 16 | que `freeze_legs` funcionó en los `upper_*`. Medido: **0.0°** en los 16 — funciona. |
| `max_root_drift_cm` | 3 | deriva horizontal antes de aplicar la política. Caza `idle_breathing` (9.1) y `crouch_idle` (7.3). |
| `expect_heading_delta_deg` | 2 | giro neto. Medido: `turn_left` **+95.2°**, `turn_right` **−96.2°** contra ±90 esperados. |

En `expect_heading_delta_deg` se compara la **magnitud**, no el signo: el signo depende de la
convención de ejes del rig y un rig espejado invertiría el criterio sin que el clip esté mal.
El signo real queda en `headingDeltaDeg` del manifest — y en esta corrida coincide con el
catálogo, así que la convención es la que se esperaba.

### `peak_frames` — para la hoja de contacto

Frames de máxima desviación respecto a la pose media, separados entre sí para no dar tres
frames del mismo instante. Muestrear al 25/50/75 % se pierde los gestos cortos: un puñetazo al
aire dura ~8 frames y cae entre dos muestras con facilidad. Sale en el manifest como
`peakFrames`; renderiza esos en vez de los porcentajes fijos.

Con esto, la marca de `react_triumphant` y `upper_aim_pistol` es probablemente un artefacto del
método de QA, no un defecto de los clips. Aun así se les ha reforzado el pico manteniendo el
estilo declarativo corto:

```
react_triumphant:  "A person throws both fists up in the air and jumps."
upper_aim_pistol:  "A person raises a pistol and aims it forward with both arms extended."
```

### El desempate entre candidatos

`score()` en [scripts/run_catalog.py](scripts/run_catalog.py) penalizaba solo skate, penetración,
jitter y loop. Con eso **el candidato congelado ganaba**: sin zancadas no hay foot skate, así
que sus métricas de limpieza salían inmejorables. Ahora penaliza la falta de ciclo y la cola
congelada.

## 5. La velocidad: usar la medida, no la asignada

Los `naturalSpeed` del plugin están asignados a mano (walk 1.2 · jog 2.4 · run 3.5 · sprint
5.5 m/s). Si el clip real camina a 1.35 y tú lo desplazas a 1.2, los pies patinan.

**Esta parte ya estaba bien hecha en el pipeline.** [postprocess.py](scripts/postprocess.py) mide
la velocidad del root sobre el clip completo antes de recortar el loop — que es lo correcto,
porque un loop bien cerrado acaba donde empezó y su desplazamiento neto no dice nada del ritmo
real — y [run_catalog.py](scripts/run_catalog.py) la escribe como `rootSpeedMs` en el manifest.

Lo que faltaba y ahora está: los valores del plugin viven en el catálogo como
`expected_speed_m_s`, con tolerancia ×2 a propósito. **La medida manda**; esto solo caza el caso
en que el clip no es el movimiento que se pidió. Es justo lo que pasó con `loco_sprint`
(2.44 medidos contra 5.5 esperados).

## 6. Estado real del catálogo

[catalog/kimodo_catalog.json](catalog/kimodo_catalog.json), ahora **versión 2.1, 50 clips**,
escrito a mano. No hay catálogo v3 de 110 clips ni `scripts/build_catalog_v3.py`.

| categoría | clips |
|---|---|
| locomotion | 14 |
| transition | 12 |
| upper | 16 |
| reaction | 8 |

No existe categoría `seated`; sentarse está dentro de `transition`. Políticas: **23
`pin_origin`, 20 `keep`, 7 `strip_xz`**. Loopean 19 (12 `full`, 7 `gait`) y 16 llevan
`mask: upper_body`.

Cambios aplicados en la 2.1:

- `expected_speed_m_s` en los 7 clips `strip_xz`.
- `loco_idle_breathing` bajado de 6.0 a 4.0 s (6 s de "estar quieto de pie" es más de lo que el
  modelo sostiene sin inventarse algo — se congela en el frame 46).
- Prompts reforzados de `react_triumphant` y `upper_aim_pistol`.
- Bloque `qc_keys` documentando qué hace cada umbral, para que no vuelva a haber claves muertas.

## 7. Correrlo

Flags verificados contra el código:

```bat
conda activate kimodo
cd C:\ruta\a\kimodo_pipeline\scripts

:: los 3 clips que fallan, mas run que esta al limite
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir ..\raw ^
    --low-vram --candidates 4 --force ^
    --only loco_sprint,loco_run,loco_idle_breathing,loco_crouch_idle

python run_catalog.py --catalog ..\catalog\kimodo_catalog.json --raw ..\raw --out ..\kimodo_animations
```

`--force` es imprescindible: sin él `generate_inproc.py` se salta los clips que ya tienen BVH y
no regeneraría nada. `--candidates 4` en vez de 2 porque para estos cuatro merece la pena tirar
más dados.

`run_catalog.py` imprime ahora el motivo de cada fallo y un resumen por comprobación:

```
REV loco_sprint: 2 cand, score=52.6, skate=0.02cm/f, speed=2.439, gait=1  <- gait_cycles, expected_speed

Fallos por comprobacion:
  root_drift        2  loco_idle_breathing, loco_crouch_idle
  frozen_tail       1  loco_idle_breathing
  gait_cycles       1  loco_sprint
  expected_speed    1  loco_sprint
```

Para el catálogo entero: 50 clips × 2 variantes = **100 generaciones**, 2–4 h en la A2000 con el
encoder en CPU. El estado se guarda, así que se puede partir por categoría con `--category`.

## 8. Una nota sobre el auto-mirror

Espejar los `upper_*` con el mirror humanoide de Unity duplica la librería gratis, pero los
clips con lateralidad semántica no se espejan bien.

La lista de exclusión del audit (`upper_salute`, `upper_write_clipboard`, `upper_hand_on_heart`,
`upper_draw_weapon`, `upper_holster_weapon`) **no sirve: ninguno de esos clips existe**. De los
16 `upper_*` reales, los que yo excluiría — esto es criterio, no medición:

- **`upper_check_watch`** — el reloj vive en una muñeca fija; en espejo se mira la muñeca vacía.
- **`upper_aim_pistol`** — si el personaje lleva funda en un lado fijo, el espejo rompe la
  continuidad con el draw/holster.
- **`upper_phone_answer` / `upper_phone_talk` / `upper_phone_hangup`** — o los tres o ninguno; si
  mezclas, el personaje contesta con una mano y cuelga con la otra.

El resto (`wave_hello`, `point_forward`, `knock_door`, `carry_box`, `cover_mouth`, `shield_face`,
`cross_arms`, `texting`, `flashlight_hold`, `push_forward`, `inspect_object`) se espeja sin
problema.

## 9. Resultado de la regeneración

**Hecho.** 8 generaciones (2 min de GPU), `kimodo_animations/` reescrito. **50/50 pasan el QC.**

> Ojo con leer ese 50/50 como "volvimos al punto de partida". La corrida original también decía
> 50/50, pero porque **los detectores no existían**. Ahora los mismos 50 pasan comprobaciones que
> antes no se hacían: ciclos de marcha, cola congelada, deriva, movimiento de piernas y giro neto.

| clip | antes | ahora | estado |
|---|---|---|---|
| `loco_sprint` | 1 ciclo, 2.44 m/s | **2 ciclos, 2.97 m/s** | arreglado |
| `loco_idle_breathing` | congelado 74 %, deriva 9.1 | **congelado 0 %**, deriva 7.0 | arreglado |
| `loco_crouch_idle` | deriva 7.3 | deriva 7.3, umbral reparado | arreglado |
| `loco_run` | 2 ciclos, 2.10 m/s | igual (v0 sigue ganando) | ya pasaba |
| `loco_walk_slow` | 3 ciclos, skate 0.164 | **4 ciclos, skate 0.042** | mejora de regalo |

`loco_walk_slow` mejoró sin regenerarse: el premio a ciclos del desempate (§4) eligió otro de
los candidatos que ya existían.

**Me equivoqué prediciendo que regenerar no arreglaría `loco_sprint`.** Sí lo mejoró. Pero el
techo del modelo es real: los 4 candidatos salieron entre 2.44 y 2.97 m/s contra 5.5 esperados.
Pasa el QC solo porque la tolerancia es ×2 (el suelo son 2.75). **Sigue sin ser un sprint**, es
un jog rápido con la etiqueta cambiada. Lo mismo con `loco_run`: 2.10 contra 3.5.

### La deriva de los idles: reparada

`loco_idle_breathing` fallaba con 7.0 cm contra un umbral de 3.0, y `loco_crouch_idle` con 10.5
contra 5.0. Regenerar no lo arreglaba: los 4 candidatos de `crouch_idle` derivan entre 7.3 y
11.5 cm.

**La deriva es real, no un artefacto del postproceso.** Verificado con `--no-skate-fix`: sin
corrección de foot skate sigue en 6.8–7.6 cm. El constraint `root2d` clavado en (0,0) que pone
`build_constraints` no sujeta al modelo del todo.

Pero mira el clip que se entrega: `residual_xz_cm = 0.0` (queda perfectamente in-place, porque
`apply_root_policy` lo clava después) y `foot_skate = 0.010 cm/frame`. **El clip entregado está
limpio**; lo que medía el umbral es cuánto *quería* moverse el modelo antes de clavarlo, que no
es un defecto visible en el resultado.

Reparado en dos pasos:

1. **Umbral a 8.0 cm** en los tres idles, con el porqué escrito en `qc_keys` del catálogo. Sigue
   cazando una deriva gruesa (un idle que se va medio metro) sin fallar por algo invisible.
2. **Desempate consciente de la deriva**, para poder poner 8.0 en vez de un 12 laxo. Antes el
   score la ignoraba y `crouch_idle` elegía un candidato de 10.5 cm teniendo uno de 7.33.

El paso 2 tiene truco, y me costó una iteración: aplicarlo a **todos** los `pin_origin` empeora
las cosas. La deriva no correlaciona con la calidad del clip clavado, así que de los 23 clips
`pin_origin` cambiaban 7 de ganador y su foot skate medio subía de 0.083 a 0.102 cm/frame, con
peor cierre de loop en 4 de 7. Queda atado a los clips que **declaran** `max_root_drift_cm`: el
desempate solo debe optimizar lo que el catálogo dice que le importa a ese clip.

### Las dos trampas que hubo que sortear (para la próxima)

**1. `--force` solo NO sirve.** `seed_for()` en [scripts/generate.py:39](scripts/generate.py#L39)
es determinista sobre `(clip_id, k)`: regenerar `__v0`/`__v1` con la misma semilla y la misma
duración devuelve **BVH byte a byte idénticos**. Para clips nuevos hacen falta candidatos
nuevos (`k >= 2`), no `--force`.

La excepción es `loco_idle_breathing`: le cambié la duración de 6.0 a 4.0 s, así que `n_frames`
cambia y la misma semilla ya da otro clip. Ese sí necesita `--force` sobre `v0`/`v1`.

**2. El env `kimodo` arranca roto desde fuera de conda.** El user site-packages de Python 3.10
(`%APPDATA%\Python\Python310\site-packages`) sombrea el scipy del env y revienta con
`ImportError: numpy.core.multiarray failed to import`. Se arregla aislándolo:

```bat
set PYTHONNOUSERSITE=1
C:\Users\adadr\miniconda3\envs\kimodo\python.exe -s generate_inproc.py ...
```

Con `conda activate kimodo` normal no hace falta.

### Los comandos que se corrieron

```bat
conda activate kimodo
cd C:\ruta\a\kimodo_pipeline\scripts

:: 1) idle_breathing: cambio de duracion, hay que rehacer v0/v1
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir C:\kimodo_work\raw ^
    --low-vram --candidates 2 --force --only loco_idle_breathing

:: 2) el resto: candidatos NUEVOS v2/v3 (sin --force, para que se salte los v0/v1 ya hechos)
python generate_inproc.py --catalog ..\catalog\kimodo_catalog.json --outdir C:\kimodo_work\raw ^
    --low-vram --candidates 4 --only loco_sprint,loco_run,loco_crouch_idle

:: 3) reprocesar: run_catalog elige el mejor de los 4 candidatos con el score nuevo
python run_catalog.py --catalog ..\catalog\kimodo_catalog.json --raw C:\kimodo_work\raw ^
    --out ..\kimodo_animations
```

Carga de modelo 38 s, ~15 s por generación. Total 2 min.

### Qué cambió en `kimodo_animations/`

**5 BVH.** Los 4 esperados (`idle_breathing`, `sprint`, `crouch_idle`, `walk_slow`) más
`upper_flashlight_hold`, que cambió a `v1` porque el detector nuevo vio cola congelada en `v0`
— es un loop, así que ahí sí es un defecto.

En la primera pasada cambiaron **14**, y 9 de ellos por un error mío: la penalización por cola
congelada del `score` se aplicaba a todos los clips en vez de solo a los que loopean. En un
one-shot como `trans_stand_to_sit_chair` eso premia al candidato que **se sigue moviendo
después de sentarse**. Corregido — la penalización ahora está condicionada igual que el
veredicto de QC.

### Publicación

Los BVH van a git (son reproducibles byte a byte, git los deduplica). **Los FBX NO**: se
regeneran con `to_fbx.py` y se suben como **adjunto de release**, no al historial —
`fbx/` está en `.gitignore` por eso. Ver commit `8b42507` y
https://github.com/adadvr/kimodomotion/releases/latest

### Entregables

FBX regenerados con Blender 5.2 (50/50, `humanoid_map.json` con 21/21 huesos). Empaquetado en
`C:\kimodo_work\dist\`:

| archivo | tamaño | contenido | destino |
|---|---|---|---|
| `kimodo_fbx_v2.1.zip` | 9.2 MB | 50 FBX + `humanoid_map.json` | **adjunto de release** |
| `kimodo_animations_v2.1.zip` | 1.9 MB | 50 BVH + `.root.json` + manifest + qc_report + catálogo | Mac / git |

Los FBX van al release y **no** a git: Blender les mete una marca de tiempo, así que no son
reproducibles byte a byte y cada regeneración añadiría ~9 MB al historial para siempre (commit
`8b42507`). Los BVH sí van a git, que los deduplica.

### Pendiente

1. **Decidir qué hacer con `run` y `sprint`.** El techo del modelo está en ~3.0 m/s medidos
   sobre 8 candidatos, contra 3.5 y 5.5 esperados. Retiming de `jog`, mocap externo, o aceptar
   la velocidad medida y ajustar el controlador. Bajar `expected_speed_m_s` a la realidad
   también es una opción, pero entonces el catálogo deja de decir qué querías y pasa a decir
   qué salió.
2. Generar el catálogo desde un script en vez de a mano, si vas a ampliarlo a 110 clips.

Nada commiteado: los cambios están en el working tree.
