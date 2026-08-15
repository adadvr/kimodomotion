# Kimodo — Regenerar los 14 clips de locomoción (v3)

> **⚠️ Desactualizado — lee [kimodo_limitations.md](kimodo_limitations.md) primero.**
>
> Este plan se escribió antes de tener mediciones. Contrastado el 2026-08-15 contra
> los 50 clips del catálogo 2.1:
>
> - **No fallan los 14, fallaban 3.** Las caminatas que aquí se dan por rotas tienen
>   3–4 ciclos de marcha y 0 % de cola congelada (`walk_neutral` 4, `jog` 4,
>   `walk_slow` 4, `sneak_walk` 4).
> - **El sufijo `in place` reforzado que se propone abajo reintroduce el problema.**
>   Mantiene la contradicción "camina sin avanzar" y le suma una cadencia imposible.
>   El catálogo 2.0 ya quitó esos prompts, y por eso las caminatas salen sanas.
> - **Ya está arreglado por pipeline**, no a mano: 50/50 pasan QC. `loco_sprint` pasó
>   de 1 ciclo a 2, y `loco_idle_breathing` de 74 % congelado a 0 %.
>
> Lo que sigue siendo válido de este documento: los nombres de archivo, que el FBX
> va plano en `Assets/eea_base_motion/`, y el criterio visual del §"Cómo saber si
> salió bien". El diagnóstico y los prompts, no.

## ¿Por qué regenerar?

Los clips de caminar/correr de las tandas v1 y v2 salieron con **UN solo paso y
luego el personaje se queda congelado** el resto del clip. Lo confirmamos
leyendo las curvas: el muslo nunca vuelve a alternar hacia atrás. Un clip así
no puede loopear como caminata — en Unity se ve que el personaje "patina"
(se desliza por el piso con las piernas casi quietas).

**La causa es el prompt**: "walking in place, seamless loop" no le bastó al
modelo — genera el inicio de la acción y sostiene la pose. Hay que pedirle
EXPLÍCITAMENTE movimiento continuo, zancadas alternadas y un mínimo de pasos.

Todo lo demás (transiciones, reacciones, acciones de brazos) salió bien y
**NO se regenera**.

## Reglas de oro (aplican a los 14)

1. **Copiar el prompt COMPLETO tal cual** — la parte final en cada prompt es la
   que arregla el problema, no la recortes.
2. **Exportar FBX** con **exactamente el mismo nombre de archivo** que se
   indica (snake_case, sin espacios). El nombre ES el identificador: al soltar
   el archivo en Unity todo se actualiza solo.
3. Duración: no importa que kimodo rellene a 8.3s — el importador recorta la
   cola congelada automáticamente. Lo que importa es que la ACCIÓN dure lo más
   posible (mínimo 4 pasos completos).
4. Sin cámara, sin props, estilo neutro (la personalidad la ponemos en Unity
   con style layers).
5. Si un resultado sale otra vez con "un paso y se queda quieto", regenerarlo
   ahí mismo con otra semilla antes de exportar — se nota a simple vista en el
   preview de kimodo: las piernas deben estar SIEMPRE intercambiándose.

## Los 14 prompts (copiar y pegar completos)

### Caminatas y carreras
El sufijo clave de este grupo es:
`continuous walking in place, both legs keep alternating strides during the
entire clip, at least four full steps, never stopping or standing still,
seamless loop`

1. → **`loco_walk_neutral.fbx`**
   ```
   person walking at a normal casual pace, arms swinging naturally, looking straight ahead, continuous walking in place, both legs keep alternating strides during the entire clip, at least four full steps, never stopping or standing still, seamless loop, neutral relaxed style
   ```

2. → **`loco_walk_slow.fbx`**
   ```
   person walking very slowly and calmly, relaxed arms, continuous walking in place, both legs keep alternating strides during the entire clip, at least four full steps, never stopping or standing still, seamless loop
   ```

3. → **`loco_walk_backward.fbx`**
   ```
   person walking backwards carefully, arms slightly out for balance, continuous walking in place, both legs keep alternating strides during the entire clip, at least four full steps, never stopping or standing still, seamless loop
   ```

4. → **`loco_jog.fbx`**
   ```
   person jogging at a light steady pace, elbows bent, continuous jogging in place, both legs keep alternating strides during the entire clip, at least six full steps, never stopping or standing still, seamless loop
   ```

5. → **`loco_run.fbx`**
   ```
   person running fast with determination, arms pumping, continuous running in place, both legs keep alternating strides during the entire clip, at least six full steps, never stopping or standing still, seamless loop
   ```

6. → **`loco_sprint.fbx`**
   ```
   person sprinting at maximum effort, leaning forward, arms pumping hard, continuous sprinting in place, both legs keep alternating strides during the entire clip, at least six full steps, never stopping or standing still, seamless loop
   ```

7. → **`loco_sneak_walk.fbx`**
   ```
   person sneaking forward slowly in a crouched careful walk, knees bent, quiet careful steps, continuous sneaking in place, both legs keep alternating strides during the entire clip, at least four full steps, never stopping or standing still, seamless loop
   ```

### Idles (aquí el problema era que se congelaban — pedir movimiento sutil CONTINUO)
Sufijo clave: `subtle continuous idle movement during the entire clip, never
freezing or holding a static pose, seamless loop`

8. → **`loco_idle_breathing.fbx`**
   ```
   person standing relaxed, breathing visibly, slight weight shifts from foot to foot, occasional small head movement, subtle continuous idle movement during the entire clip, never freezing or holding a static pose, seamless loop
   ```

9. → **`loco_idle_alert.fbx`**
   ```
   person standing alert and tense, scanning around slowly, shifting weight, hands ready, subtle continuous idle movement during the entire clip, never freezing or holding a static pose, seamless loop
   ```

10. → **`loco_crouch_idle.fbx`**
    ```
    person crouching low and holding the crouch, balancing with small continuous adjustments, staying crouched the whole clip, subtle continuous idle movement during the entire clip, never freezing or holding a static pose, seamless loop
    ```

### Giros y arranque/parada (one-shots — aquí pedir la acción COMPLETA)

11. → **`loco_turn_left.fbx`**
    ```
    person turning 90 degrees to the left in place with natural footsteps, stepping through the whole turn, starts and ends standing in a neutral relaxed pose
    ```

12. → **`loco_turn_right.fbx`**
    ```
    person turning 90 degrees to the right in place with natural footsteps, stepping through the whole turn, starts and ends standing in a neutral relaxed pose
    ```

13. → **`loco_walk_start.fbx`**
    ```
    person transitioning from standing still into a continuous walk, taking at least three full steps after starting, walking in place, never stopping once started
    ```

14. → **`loco_walk_stop.fbx`**
    ```
    person walking in place with alternating strides for at least three steps and then coming to a natural stop, ending standing in a neutral relaxed pose
    ```

## Entrega

1. Exportar los 14 FBX a una carpeta (ej. `kimodo_fbx_v3/`) — nombres EXACTOS
   de arriba, sin prefijos de carpeta en el nombre del archivo.
2. Pasarla a la Mac y copiar los .fbx a:
   `FaceTrackingApp/Assets/eea_base_motion/` (reemplazan a los viejos).
3. En Unity todo se re-ingesta solo (o Claude corre `kimodo_ingest`); la
   auditoría de curvas confirma en segundos si ahora sí traen ciclo.

## Cómo saber si salió bien ANTES de exportar

En el preview de kimodo, durante TODO el clip:
- Caminatas/carreras: las piernas nunca dejan de intercambiarse; los brazos
  balancean en oposición a las piernas.
- Idles: el cuerpo nunca se queda clavado — respira, cambia el peso.
- Si en algún momento el personaje queda estático más de ~1 segundo → mala
  generación, tirar y regenerar con otra semilla.
