# PASS 1 — Validación · 6 clips

**Genera ESTO primero.** El catálogo que comen los scripts es
`catalog/pass1_validation.json`; este MD es el mismo contenido en legible.

Son 6 clips que existen solo para probar las convenciones nuevas antes de
lanzar los 352 del pass 2. Si algo de la convención está mal, aquí cuesta
6 generaciones descubrirlo, no 352.

```
python scripts/generate.py    --catalog ../catalog/pass1_validation.json --outdir ../raw_pass1
python scripts/run_catalog.py --catalog ../catalog/pass1_validation.json --raw ../raw_pass1 --out ../kimodo_animations_pass1
```

## Qué se valida

| # | clip | qué prueba |
|---|---|---|
| 1-2 | `contact_handshake_give` / `_receive` | par de dos personajes con contacto suave |
| 3-4 | `fight_jab_give` / `_receive` | par de combate: el puño tiene que conectar con la reacción |
| 5 | `talk_explain_measured` | categoría `talk` como loop de upper body |
| 6 | `upper_reach_mid_right` | reach direccional para el sistema de grips de props |

## Los prompts

| clip | prompt | duración | root | loop |
|---|---|---|---|---|
| `contact_handshake_give` | A person extends their right hand forward, shakes it twice, and lowers it. | 4.0 | pin_origin | no |
| `contact_handshake_receive` | A person reaches forward with their right hand, shakes it twice, and lowers it. | 4.0 | pin_origin | no |
| `fight_jab_give` | A person throws a fast straight punch with their left hand and pulls it back into a boxing guard. | 2.5 | pin_origin | no |
| `fight_jab_receive` | A person's head snaps back from a punch to the face and they stagger half a step backward. | 2.5 | **keep** | no |
| `talk_explain_measured` | A person talks and gestures calmly with both hands at chest height. | 5.0 | pin_origin | **sí** (upper_body) |
| `upper_reach_mid_right` | A person reaches forward at chest height with their right hand and closes it around an object. | 3.5 | pin_origin | no (upper_body) |

`fight_jab_receive` usa `keep` a propósito: el traspié hacia atrás **es** la
reacción y no debe fijarse al origen.

## El dato que hace que un par funcione: `contactAt`

Tu generador solo puede medir contactos de **pie** (`peakFrames`). Lo que tiene
que coincidir en un par es el **puño con la cara**. Por eso cada mitad declara,
dentro de `taxonomy`:

```json
"pairId": "fight_jab", "pairRole": "give", "contactAt": 0.4
```

`contactAt` es la fracción de la duración donde ocurre el contacto. El plugin la
convierte a frame y desplaza el clip `receive` para que ambos instantes caigan
en el mismo momento del timeline. Sin ese dato el par se alinea por el arranque
y el golpe llega antes que la reacción.

`run_catalog.py` ya copia el bloque `taxonomy` completo al manifest de salida,
así que estos campos llegan al plugin **sin tocar tus scripts**.

## Qué hago yo con el resultado

Me pasas la carpeta de salida (BVH/FBX + `manifest.json`) y la ingiero en Unity:

- el par debe emparejarse solo por el sufijo `_give`/`_receive`,
- los dos personajes deben quedar a la distancia de contacto correcta
  (apretón 0.9 m, puñetazo 1.1 m) mirándose,
- y en el frame del impacto el puño debe estar en la cara, no en el aire.

Con eso verificado, lanzas `pass2_action_library.json` (352 clips) de una sola vez.
