# Passes de generación — librería de acciones

## Orden de trabajo

### 1. `pass1_validation.json` — 6 clips · GENERAR PRIMERO

Existe para validar las convenciones nuevas antes de gastar 190 generaciones:

- **Pares de dos personajes** (`contact_handshake_*`, `fight_jab_*`): dos clips
  que el plugin empareja y sincroniza por el instante del contacto.
- **Categoría `talk`** como loop de upper body.
- **Reach direccional** para el sistema de grips de props.

```
python scripts/generate.py    --catalog ../catalog/pass1_validation.json --outdir ../raw_pass1
python scripts/run_catalog.py --catalog ../catalog/pass1_validation.json --raw ../raw_pass1 --out ../kimodo_animations_pass1
```

Luego los FBX/BVH + `manifest.json` van a `Assets/eea_base_motion/` del proyecto
Unity y se corre `kimodo_ingest`. **Qué debe verse**: el apretón y el golpe
emparejados, con el puño conectando en la reacción y los personajes a la
distancia correcta.

### 2. `pass2_action_library.json` — 540 clips · SOLO tras validar

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
| Pares 2 personajes | 61 pares: apretón, abrazo, entrega, corte de pelo, afeitado, examen médico, vendaje, inyección, baile en pareja (giro, dip, alzada), cargar entre dos, susurro, consuelo, esposar, foto, brindis, empujón de borracho, separar una pelea, bendición, sujetar en un ritual, mano en la boca, registro, arrastrar del cuello |

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
