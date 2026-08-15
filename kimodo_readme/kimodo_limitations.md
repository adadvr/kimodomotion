# Kimodo — límites reales del modelo y del pipeline

Qué se puede pedirle a Kimodo (SOMA-RP) y qué no, con números medidos.
Sirve para no volver a diagnosticar lo mismo dos veces.

**Medido el 2026-08-15** sobre los 50 clips del catálogo 2.1 y 8 candidatos extra
de locomoción, con los detectores de `scripts/postprocess.py`. Todo lo de aquí
sale del `manifest.json` y del `qc_report.json`, no de estimaciones.

> Lee esto **antes** que [REGENERAR_LOCOMOCION.md](REGENERAR_LOCOMOCION.md). Ese
> documento describe bien un problema pasado (los clips v1/v2) pero propone una
> solución que las mediciones no respaldan — ver §2 y §3.

---

## 1. Techo de velocidad: ~3.0 m/s

**El modelo no genera locomoción más rápida que unos 3 m/s, se le pida como se le
pida.** `jog`, `run` y `sprint` colapsan en la misma velocidad.

| clip | velocidad esperada | medida | ciclos |
|---|---|---|---|
| `loco_walk_slow` | 0.8 | 0.78 | 4 |
| `loco_walk_neutral` | 1.2 | 1.18 | 4 |
| `loco_jog` | 2.4 | 2.21 | 4 |
| `loco_run` | 3.5 | **2.10** | 2 |
| `loco_sprint` | 5.5 | **2.97** | 2 |

Hasta el jog, la velocidad medida cuadra con la pedida. A partir de ahí se
despega y no vuelve.

Los 4 candidatos de `sprint`, con semillas distintas, salieron a **2.44 · 2.54 ·
2.88 · 2.97 m/s**. Los 4 de `run`, a **2.10 · 2.42 · 2.68 · 2.88**. Ninguno pasó
de 3.0. No es mala suerte de semilla: es el techo.

**Consecuencia práctica:** `run` y `sprint` son jogs con otra etiqueta. Si
necesitas velocidades reales de carrera, las salidas son retiming del clip en
Unity, mocap externo, o aceptar la velocidad medida y ajustar el controlador.
Ningún prompt lo arregla.

## 2. "In place" es una contradicción, y reforzarla la empeora

Kimodo aprendió de captura de movimiento real. Ahí "caminar" **siempre** viene
con un root que avanza — no existe otra cosa. La única captura que encaja con
"camina pero no avanza" es la de alguien que **da un paso y se detiene**.

Por eso los clips v1/v2, generados con `walking in place without moving forward`,
salían con un paso y congelados. El modelo no falló: resolvió una contradicción
de la forma más razonable que tenía.

**La solución NO es insistir más.** Un sufijo tipo:

> *continuous walking in place, both legs keep alternating strides during the
> entire clip, at least four full steps, never stopping or standing still*

mantiene la contradicción original y le añade dos encima: pide cuatro zancadas
completas **y** cero desplazamiento, y en un clip corto esa cadencia es de
sprint — imposible para un `walk_slow`. Los modelos de difusión no resuelven
contradicciones eligiendo la parte que te importa: promedian.

**Lo que sí funciona** (y es lo que hay en el catálogo desde la 2.0): pedir la
caminata de verdad, y quitar el desplazamiento después por aritmética.

```
mal:   "person walking at a normal casual pace, walking in place without
        moving forward, seamless loop, neutral relaxed style"

bien:  "A person walks forward at a casual pace."     + root_policy: strip_xz
```

El clip queda in-place por postproceso, no por convencimiento. Y de regalo
obtienes la velocidad real del ciclo, que la necesitas (§5).

Medido con los prompts buenos: `walk_neutral` 4 ciclos, `walk_slow` 4,
`walk_backward` 3, `jog` 4, `sneak_walk` 4, con **0 % de cola congelada** en
todos. El problema del paso único está resuelto en origen.

## 3. Recortar la cola congelada trata el síntoma

Un importador que corta el final muerto del clip te deja un clip **válido que
sigue sin tener ciclo**. Pasa todas las comprobaciones de limpieza —sin zancadas
no hay foot skate, así que las métricas salen inmejorables— y patina en Unity.

Ese fue exactamente el fallo: el QC daba **50/50 clips aprobados** incluyendo los
rotos, porque la comprobación de loop solo preguntaba *"¿encontré un periodo?"* y
el detector siempre encuentra alguno: ante un clip sin periodicidad se queda con
la ventana más corta permitida. `loco_sprint` pasaba con un "periodo" de 0.5 s y
un despegue por pie en cuatro segundos.

**Rechazar y regenerar, no recortar.** Ahora lo hace solo (§6).

## 4. Los idles se desvían pasados ~4 s

`loco_idle_breathing` a 6 s se congelaba desde el **frame 46 de 180** — el 74 %
final era una pose fija. Bajado a **4 s**, cola congelada 0 %.

Seis segundos de "estar de pie quieto" es más de lo que el modelo sostiene sin
inventarse algo. Para idles largos, genera corto y loopea.

### El constraint `pin_origin` no sujeta del todo

El constraint `root2d` clavado en (0,0) reduce la deriva pero no la elimina.
Medido sobre 8 candidatos de idles: **de 4.3 a 11.5 cm** de deriva horizontal.

No es un artefacto del postproceso: corriendo con `--no-skate-fix`, sin
corrección de foot skate, sigue en 6.8–7.6 cm. Y no baja regenerando.

**Pero no es un defecto del clip entregado.** Ese sale clavado —
`residual_xz_cm = 0.0` — con **0.010 cm/frame** de foot skate. Lo que mide
`max_root_drift_cm` es cuánto *quería* moverse el modelo antes de clavarlo. Por
eso el umbral está en 8.0 cm y no en los 3.0–5.0 originales, que estaban por
debajo de lo que el modelo puede dar.

## 5. El "gliding" tiene dos causas, no una

La primera es el ciclo ausente (§2). La segunda sobrevive aunque el ciclo sea
perfecto: **las velocidades asignadas a mano.**

Si el plugin desplaza un `run` a 3.5 m/s pero el clip real corre a 2.10, los pies
patinan — el avance y la cadencia no coinciden. Y por §1 esa discrepancia es
estructural en `run` y `sprint`.

El pipeline **mide** la velocidad del root sobre el clip completo, antes de
recortar el loop, y la escribe como `rootSpeedMs` en el manifest. Un loop bien
cerrado acaba casi donde empezó, así que su desplazamiento neto no dice nada del
ritmo real: por eso se mide antes.

**Usa `rootSpeedMs`, no la velocidad asignada.** Los valores del catálogo viven
en `expected_speed_m_s` solo para detectar desviaciones gruesas, con tolerancia
×2.

## 6. Lo que el QC detecta solo

Ya no hace falta leer curvas a mano. En `scripts/postprocess.py`:

| detector | qué caza |
|---|---|
| `gait_cycles` | despegues por pie, con antirrebote. Menos de 2 en un loop de marcha → rechazado |
| `frozen_tail_from_frame` | energía **relativa al root**, así que un clip que avanza con el cuerpo rígido también cae. Más del 25 % final muerto → rechazado |
| `max_leg_motion_deg` | que `freeze_legs` funcionó en los 16 clips `upper_*`. Medido: 0.0° |
| `max_root_drift_cm` | deriva del root pese al pin |
| `expect_heading_delta_deg` | giro neto. Medido: `turn_left` +95.2°, `turn_right` −96.2° |
| `peak_frames` | frames de la pose clave, para la hoja de contacto |

Dos detalles de calibración que conviene no tocar a ciegas:

- **El antirrebote de `gait_cycles` es 0.12 s**, calibrado contra el BVH
  sintético de `make_test_bvh.py` (4.5 zancadas reales en 5 s). A 0.08 s cuenta
  8–10 despegues por pie —el doble, porque el detector de contacto parpadea— y a
  0.16 s se come fases de vuelo reales y devuelve 0. A 0.12 s da 4–5.
- **El umbral de `frozen_tail` sale del percentil 90** de la energía, no de la
  mediana: si el 70 % del clip está congelado, la mediana ya vive dentro de la
  parte muerta y el detector no detectaría nada.

`make_test_bvh.py --freeze-after` fabrica el fallo a propósito, con el root
siguiendo en marcha, para verificar los detectores sin depender de la GPU.

## 7. El auto-mirror y la lateralidad semántica

Espejar los `upper_*` con el mirror humanoide de Unity duplica la librería
gratis, pero hay clips que no se espejan bien. De los 16 reales, yo excluiría:

- **`upper_check_watch`** — el reloj vive en una muñeca fija; en espejo el
  personaje se mira la muñeca vacía.
- **`upper_aim_pistol`** — si lleva funda en un lado fijo, el espejo rompe la
  continuidad con el draw/holster.
- **`upper_phone_answer` / `upper_phone_talk` / `upper_phone_hangup`** — o los
  tres o ninguno; si mezclas, contesta con una mano y cuelga con la otra.

El resto se espeja sin problema. Esto es criterio, no medición.

## 8. Resumen para decidir rápido

| quiero… | ¿se puede? |
|---|---|
| Caminatas y jog con ciclo limpio | **Sí.** 3–4 ciclos, 0 % congelado |
| Carrera o sprint a velocidad real | **No.** Techo en ~3 m/s. Retiming o mocap |
| Un clip in-place pidiéndolo en el prompt | **No.** Pídelo con avance y quítalo en postproceso |
| Idle de 6 s de una pieza | **No.** Se desvía pasados ~4 s. Genera corto y loopea |
| Root perfectamente clavado en generación | **No.** Quedan 4–11 cm de deriva; se clava en postproceso |
| Detectar clips rotos sin mirarlos | **Sí.** §6 |
