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

### 2. `pass2_action_library.json` — 190 clips · SOLO tras validar

Cubre la librería completa para armar cinemáticas: conversación a dos, peleas
con pares golpe/reacción, vida cotidiana, deporte y juego, baile y emotes,
contacto social, contenedores del hogar (refri, alacena, cajones), armas
blancas, muerte, amenaza y rendición, forcejeo y sigilo.

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
