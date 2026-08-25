# Passes de generación — librería de acciones

## Orden de trabajo

### 1. `pass1_v2_validation.json` — 4 clips · GENERAR PRIMERO

Segunda vuelta del piloto. La primera validó toda la cadena (ingest, taxonomía,
emparejamiento, distancia 1.10 m exacta, sincronía de impactos) pero los dos clips
de combate no servían para un golpe conectado: el jab extendía **15 cm** el brazo y
la reacción retrocedía **1 metro** dentro del clip, dejando 152 cm entre puño y cara.

Los prompts corregidos piden la **extensión explícita** del brazo o la pierna, y las
reacciones llevan **"without stepping away"** con el root fijado. Detalle completo en
`PASS1_V2_VALIDACION.md`.

```
python scripts/generate.py    --catalog ../catalog/pass1_v2_validation.json --outdir ../raw_pass1v2
python scripts/run_catalog.py --catalog ../catalog/pass1_v2_validation.json --raw ../raw_pass1v2 --out ../kimodo_animations_pass1v2
```

`talk_explain_measured` y `upper_reach_mid_right` salieron bien en la primera vuelta
y no hay que regenerarlos. El catálogo de la primera vuelta queda como
`pass1_validation.json` para referencia.

### 2. `pass2_action_library.json` — 657 clips · SOLO tras validar

Una sola tanda, para no volver a generar en trozos.

| bloque | contenido |
|---|---|
| Acción y conflicto | peleas con pares golpe/reacción, armas blancas, forcejeo, estrangulamiento, amenaza y rendición, muerte y consecuencias |
| Conversación | loops de habla + reacciones de escucha, interrupción, desacuerdo |
| Vida cotidiana y hogar | comer, beber, dormir, teclear, leer, asearse, refrigerador, alacena, cajones, fregar, microondas |
| Vestirse y aseo | audífonos, gorra, gafas, chaqueta, cordones, mochila, guantes, reloj, peinarse, maquillarse, afeitarse |
| Vehículos | abrir puerta y entrar, cinturón, conducir, retrovisor, maletero, moto, bicicleta, autobús, taxi |
| Oficios | barbería (tijeras, secador, capa), cocina, taller, clínica, caja, limpieza, pintura |
| Oficina | escribir, firmar, sellar, presentar, videollamada, archivar |
| Calle y compras | carrito, estantes, tarjeta, cola, paraguas, escaleras mecánicas, selfie, fumar |
| Deporte | pesas, flexiones, cinta, saco, yoga, escalada, remo, arco, golf, tenis |
| Estados corporales | borracho, mareado, con frío, con prisa, nervioso, llorando, estornudo, bostezo |
| Cuidado | acariciar un perro, cargar un bebé, alzar a un niño, dar de comer, regar |
| Supervivencia | encender fuego, beber de un río, escalar, saltar un hueco, manta, torniquete, otear, pedir auxilio, huir mirando atrás |
| Fiesta y borrachera | cerveza en vaso, botella y lata, brindis, fondo blanco, bailar y saltar, cantar, vomitar, romper una botella, aventar vasos y sillas |
| Ritual y horror | arrodillarse a rezar, persignarse, postrarse, velas, ofrenda, incensario, salmodia, procesión, símbolo en el suelo, poseído (arqueo, convulsión, caminar antinatural, gatear al revés) |
| Crimen y acecho | jefe dando órdenes, chasquear los dedos, gesto de degüello, golpear la mesa, contar dinero, puro y whisky; acechar, limpiar la hoja, afilarla, lavarse las manos, cavar de noche |
| Música | guitarra (rasgueo, punteo, solo), batería, bajo, piano, violín, arpa, flauta, saxo, trompeta, acordeón, dirigir, cantar con micro |
| Danza y escena | ballet (plié, pirueta, arabesque, jeté, bourrée), folklor (zapateado, faldas, palmas, círculo), contemporánea (rodar, caída, contracción), claqué, vals, flamenco, declamar, monólogo, muerte teatral, reverencia |
| Locomoción avanzada | arrancar a correr, frenar derrapando, girar en carrera, giro de 180 en carrera, salto con carrera, salto vertical, caer y rodar, saltar obstáculos |
| Acrobacias y parkour | voltereta adelante, atrás y lateral, rueda, flic-flac, mortal atrás, pino, deslizarse, correr por la pared, saltar una barandilla, trepar una cornisa |
| Estilo por género | El caminar (contoneo, tacones, pasarela, con bolso, con abrigo cruzado), la postura de pie y al sentarse, los gestos de manos y pelo (recogerse el pelo tras la oreja, coleta, moño, cepillarse, pendientes, uñas, reír tapándose la boca, hablar con las manos suaves) y las acciones con accesorios (ponerse y quitarse tacones, bolso al hombro, buscar en el bolso, posar, ajustarse la bufanda, ponerse el abrigo). 43 femeninos + 8 masculinos de contraste, con sufijo `_f` / `_m` |
| Artes marciales | posturas (guardia, del jinete), palma, codo, revés, rodillazo, patada frontal alta, circular, giratoria, de hacha, lateral, barrido, patada en salto, kata, bloqueos y esquivas |
| Pares 2 personajes | 67 pares: apretón, abrazo, entrega, corte de pelo, afeitado, examen médico, vendaje, inyección, baile en pareja (giro, dip, alzada), cargar entre dos, susurro, consuelo, esposar, foto, brindis, empujón de borracho, separar una pelea, bendición, sujetar en un ritual, mano en la boca, registro, arrastrar del cuello |

## Convención de pares

Una acción de dos personajes se genera en **dos mitades**: `<base>_give` (quien
inicia) y `<base>_receive` (quien recibe). El bloque `taxonomy` de cada mitad
lleva `pairId`, `pairRole` y `contactAt` — la fracción del clip donde ocurre el
contacto. `run_catalog.py` ya copia `taxonomy` entero al manifest, así que esos
campos llegan al plugin sin tocar los scripts.

`contactAt` es lo que hace que el golpe conecte: el generador solo puede medir
contactos de PIE (`peakFrames`), y lo que tiene que coincidir es el puño con la
cara. Sin ese dato el par se alinea por el arranque y el golpe llega tarde.

## Reglas heredadas del catálogo 2.1

- Prompt declarativo corto. Nunca "seamless loop", "in place" ni "starts and
  ends neutral" en el texto: eso son `root_policy`, `loop`, `bookends` y QC.
- Techo real ~3 m/s: pedir sprint da un trote. Retimar el clip, no acelerar.
- Un loop de locomoción sin ciclo de marcha se **regenera**, no se recorta.
- Idles máximo 4 s.

## Correcciones medidas en el piloto, ya aplicadas a los 657

| Qué se midió | v1 | v2 | Qué cambió en el catálogo |
|---|---|---|---|
| La reacción se alejaba dentro de su clip | 100 cm | **3 cm** | `without stepping away` + `root_policy: pin_origin` en las 53 reacciones que no deben viajar |
| Duración entregada vs pedida | +35 % | exacta | duraciones de los pares recortadas un 28 % |
| Cola sin movimiento al final | 38 % | 0 % | duraciones cortas |
| Extensión del brazo al golpear | 15 cm | 7 cm | **formula reforzada** (ver abajo) |

La extensión es la que resistió. En v2 el prompt decía *"fully extending the arm
forward at head height, then pulls it back to the chest"* y aun así dio 7 cm. Dos
sospechas, las dos corregidas en los 64 clips que golpean:

1. **Pedía dos acciones opuestas** (extender Y retraer) y el modelo promedia. La
   retracción se elimina del prompt — el plugin puede recortar o sostener la cola.
2. **Una acción pesa menos que un estado.** Ahora la extensión se declara como la
   condición del brazo en el pico, y va al **final** de la frase:

   > A person throws a heavy straight cross with the rear hand, hips rotating fully
   > through the punch, **the arm completely straight at full reach.**

Si aun así el modelo no extiende, es un techo suyo con los golpes y el remate va por
autoría: para eso está la ronda de herramientas de trayectorias e inbetween.


## Lecciones del pass 2 (aplicadas en 3.2-pass2-lessons)

- **El scorer ya mide extension** (`strike_reach_cm` en run_catalog.py): en combate
  con role give, 1 punto por cm — la limpieza solo desempata entre golpes que llegan.
  En el pass 2 el scorer ciego habria entregado el golpe flojo en 11 de 16 clips.
- **El sujeto del prompt no cambia el estilo** (medido en _gtest: la semilla pesa mas
  que decir man/woman, y el esqueleto es siempre el mismo). El estilo se pide con la
  instruccion de movimiento explicita, nunca con el sustantivo.
- **Instrucciones que compiten se promedian**: "hips rotating fully" + "at full reach"
  dio un cross corto en los 4 candidatos. Una sola orden dominante por clip.
- `generate_inproc.py` siempre (una carga de modelo por bloque); `to_fbx.py` acepta
  `--in` y `--input`, y corre DENTRO de blender:
  `blender --background --python to_fbx.py -- --input <carpeta> --out <fbx> --scale 0.01`
