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

### 2. `pass2_action_library.json` — 352 clips · SOLO tras validar

Una sola tanda, para no volver a generar en trozos. Cubre:

| bloque | contenido |
|---|---|
| Acción y conflicto | peleas con pares golpe/reacción, armas blancas, forcejeo, estrangulamiento, amenaza y rendición, muerte y consecuencias |
| Conversación | 11 loops de habla + reacciones de escucha, interrupción, desacuerdo |
| Vida cotidiana | comer, beber, dormir, despertar, teclear, leer, asearse |
| Hogar | refrigerador, alacena, cajones, servir, fregar, microondas, basura |
| Vestirse y aseo | audífonos, gorra, gafas, chaqueta, zapatos, mochila, bufanda, guantes, reloj, cinturón, peinarse, maquillarse, afeitarse |
| Vehículos | abrir puerta y entrar, cinturón, conducir, retrovisor, maletero, moto, bicicleta, autobús, taxi |
| Oficios | barbería (tijeras, secador, capa), cocina (picar, remover, sartén, amasar), taller (llave, capó, martillo, taladro), clínica (estetoscopio, vendaje, inyección), caja, limpieza, pintura |
| Oficina | escribir, firmar, sellar, pasar páginas, presentar, videollamada, archivar |
| Calle y compras | carrito, estantes, pagar con tarjeta, cola, paraguas, escaleras mecánicas, cruzar, selfie, fumar |
| Deporte | pesas, flexiones, abdominales, cinta, saco, estiramientos, yoga, escalada, remo, arco, golf, tenis |
| Estados | borracho, mareado, con frío, con calor, nervioso, impaciente, llorando, riendo, estornudo, tos, bostezo, alivio |
| Cuidado | acariciar un perro, cargar un bebé, alzar a un niño, dar de comer, regar |
| Baile y emotes | 10 loops de baile + 14 emotes |
| Pares 2 personajes | 43 pares: apretón, abrazo, choque de manos, entrega, corte de pelo, afeitado, examen médico, vendaje, inyección, baile en pareja, cargar entre dos, susurro, consuelo, choque casual, esposar, foto, ir de la mano, corregir postura, brindis |

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
