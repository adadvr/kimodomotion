# PASS 1 v2 — Validación, segunda vuelta · 4 clips

Catálogo para los scripts: **`catalog/pass1_v2_validation.json`**

```
python scripts/generate.py    --catalog ../catalog/pass1_v2_validation.json --outdir ../raw_pass1v2
python scripts/run_catalog.py --catalog ../catalog/pass1_v2_validation.json --raw ../raw_pass1v2 --out ../kimodo_animations_pass1v2
```

## Qué pasó en la primera vuelta

La cadena completa funcionó: los 6 clips entraron sin rechazos, la taxonomía nueva
(Combat / Contact / Talk) llegó correcta, el emparejamiento detectó los pares solo,
los personajes quedaron a **1.10 m exactos** enfrentados y los dos impactos cayeron
en el **mismo instante**.

Pero el golpe no conectaba. Medido en Unity:

| Medición | Valor | Debería |
|---|---|---|
| Alcance del jab (extensión sobre la guardia) | **15 cm** | 40-50 cm |
| Desplazamiento del defensor dentro de su clip | **1 m hacia atrás** | ~15 cm |
| Distancia puño-cara en el impacto | **152 cm** | < 15 cm |

Con esos dos clips no hay corrección posible: el brazo mide 60 cm.

## Las dos causas, y lo que cambia

**1. El golpe no pedía extensión.** El prompt decía *"throws a fast straight punch"*.
`straight punch` es el **nombre** del golpe, no una instrucción — y el modelo entrega
el gesto mínimo que satisface la frase: una finta. Ahora el prompt lo pide explícito:

> A person throws a straight punch with the right hand, **fully extending the arm
> forward at head height**, then pulls it back to the chest.

**2. La reacción se iba de rango.** El prompt pedía *"staggers half a step backward"*
y el modelo entregó un metro. Peor: ese desplazamiento se hornea en los **huesos**
(la pelvis viaja de 1.12 a 2.13 mientras el root no se mueve), así que el plugin no
puede descontarlo. Ahora:

> A person's head snaps back from a punch to the face, rocking onto the back foot
> **without stepping away**.

…y con `root_policy: pin_origin` en vez de `keep`.

## Los 4 clips

| clip | prompt | dur | root |
|---|---|---|---|
| `fight_jab_give` | A person throws a straight punch with the right hand, fully extending the arm forward at head height, then pulls it back to the chest. | 2.0 | pin_origin |
| `fight_jab_receive` | A person's head snaps back from a punch to the face, rocking onto the back foot without stepping away. | 2.0 | pin_origin |
| `contact_handshake_give` | A person extends the right arm forward until it is straight, shakes twice and lowers it. | 3.0 | pin_origin |
| `contact_handshake_receive` | A person extends the right arm forward until it is straight, shakes twice and lowers it, feet planted. | 3.0 | pin_origin |

**`talk_explain_measured` y `upper_reach_mid_right` salieron bien: no los regeneres.**

## Otras dos cosas medidas

- **El generador entrega ~35 % más largo de lo pedido** (2.5 s → 3.37 s; 4 s → 4.77 s).
  Las duraciones de arriba ya vienen recortadas para compensar.
- **Los one-shots traen ~38 % de cola sin movimiento al final.** No es un defecto que
  el ingest rechace (un one-shot puede acabar parado), pero acorta el clip útil — otra
  razón para pedir duraciones cortas.

## Lo que ya no tienes que acertar

`contactAt` pasó a ser solo una pista. Desde esta ronda el plugin **mide** el instante
real del contacto sobre el clip: busca el frame de máxima extensión hacia el oponente,
proyectada sobre el frente del cuerpo, para que una guardia alta no cuente como golpe.
En la primera vuelta ya corrigió sola la reacción, del 25 % declarado al 46 % real.

## Qué verifico cuando me pases los BVH

1. El alcance del jab supera 35 cm sobre la guardia.
2. El defensor no se desplaza más de 20 cm dentro de su clip.
3. Con el par montado, la distancia puño-cara en el impacto baja de 15 cm.

Si los tres pasan, el pass 2 sale sin más cambios: sus 61 pares ya llevan estas mismas
correcciones aplicadas automáticamente.

---

## Añadido: test de género (3 clips)

Los 606 clips del catálogo dicen **"A person"**. Hacer versión masculina y femenina
de todo serían 1212 clips, y eso solo tiene sentido si el generador de verdad cambia
el movimiento según el sujeto.

Estos tres clips lo responden con 12 generaciones en vez de con 606:

| clip | prompt |
|---|---|
| `loco_walk_test_person` | A person walks forward at a casual pace. |
| `loco_walk_test_man` | A man walks forward at a casual pace. |
| `loco_walk_test_woman` | A woman walks forward at a casual pace. |

**Cómo lo leo cuando me los pases:** mido ancho de paso, balanceo de cadera, balanceo
de brazos y cadencia en los tres. Si `man` y `woman` salen a menos de un 10 % del
control, el generador ignora el sujeto y no duplicamos nada. Si difieren de verdad,
la recomendación no es duplicar los 606 — sería hacer variantes `_m`/`_f` solo donde
el dimorfismo se nota:

- **Sí**: locomoción (caminar, correr, trotar), idles de pie y sentado, bailes,
  algunos gestos sociales. Unos 90 clips → 180.
- **No**: abrir una puerta, teclear, apuñalar, conducir, casi todos los one-shots
  técnicos. Ahí el movimiento lo dicta el objeto, no el cuerpo.

Y una advertencia: aunque el generador responda al sujeto, el clip se **retargetea**
a tu personaje en Unity, así que parte del dimorfismo (altura, anchura de cadera) ya
lo aporta el propio rig. Lo que aportaría el clip es el estilo del paso, no la
proporción.
