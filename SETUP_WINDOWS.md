# Instalación en Windows — lo que realmente funciona

Este documento reemplaza la sección 4 de [`dev.md`](dev.md). Los comandos de ahí
fallan en varios puntos; abajo está la secuencia verificada, con el porqué de cada
desvío para que nadie los "corrija" de vuelta.

Verificado en: Windows 11 Pro 26200, RTX A2000 Laptop (4 GB), 31.7 GB RAM,
driver 595.95.

---

## Secuencia verificada

```powershell
# 1. Miniconda (winget)
winget install --id Anaconda.Miniconda3 --accept-package-agreements --silent

# 2. Entorno — OJO: -c conda-forge, ver nota 1
conda create -n kimodo python=3.10 -y --override-channels -c conda-forge

# 3. CMake real (NO el de pip), ver nota 4
conda install -n kimodo -y --override-channels -c conda-forge "cmake<4"

# 4. torch — OJO: --extra-index-url y version fijada, ver nota 2
conda activate kimodo
pip install "torch==2.5.1+cu121" --extra-index-url https://download.pytorch.org/whl/cu121

# 5. Resto
pip install numpy scipy huggingface_hub
pip install "git+https://github.com/nv-tlabs/kimodo.git"

# 6. Blender — ZIP portable, NO el instalador, ver nota 5
#    Descomprimido en C:\kimodo_work\tools\blender-5.2.0-windows-x64\
```

---

## Las cinco trampas

### 1. conda y los Términos de Servicio de Anaconda

`conda create` sin `--override-channels -c conda-forge` falla con
`CondaToSNonInteractiveError`: los canales `repo.anaconda.com` exigen aceptar un
ToS con implicaciones de uso comercial. conda-forge no lo requiere y trae los
mismos paquetes.

### 2. `pip install torch --index-url ...` falla

`--index-url` **reemplaza** PyPI en vez de añadirse. `torch` necesita
`typing_extensions`, que solo está como tarball fuente en el índice de PyTorch, y
su dependencia de build `flit_core` no existe ahí:

```
ERROR: No matching distribution found for flit_core<4,>=3.11
```

Falla **después** de bajar los 2.4 GB del wheel. Se arregla con
`--extra-index-url` y fijando `torch==2.5.1+cu121` — el sufijo `+cu121` impide que
pip resuelva a la build de CPU desde PyPI.

### 3. El entorno ve site-packages del usuario

Hay un `%APPDATA%\Roaming\Python\Python310\site-packages` con paquetes viejos
(p. ej. `filelock 3.9.0`, cuando kimodo pide `>=3.20.3`) que se cuela en el env.
Exportar `PYTHONNOUSERSITE=1` antes de cualquier `pip` o `python` del proyecto.

### 4. kimodo compila una extensión C++, y el CMake de pip no sirve

`setup.py` construye `MotionCorrection` (pybind11 + Eigen) vía CMake. Dos cosas:

- **No uses `pip install cmake`**: es un shim de Python, y bajo el aislamiento de
  build de pip revienta con `ModuleNotFoundError: No module named 'cmake'`.
  El binario de conda-forge no tiene ese problema.
- **CMake debe ser < 4**: el build hace `FetchContent` de pybind11 v2.11.1, que
  declara `cmake_minimum_required(VERSION 3.4)`, y CMake 4 lo rechaza.

El compilador C++ lo aporta Visual Studio Build Tools 2022, que ya estaba en la
máquina. `motion_correction` **no es opcional**: lo importa
`kimodo/postprocess.py:313`, que es el `post_processing=True` que el brief exige.

### 5. El instalador de Blender falla; usa el ZIP

El MSI (winget) muere en la acción `RegisterBlender` con error 1603 y hace
rollback completo. Da igual: `to_fbx.py` se ejecuta *dentro* de Blender
(`blender.exe --background --python`), así que el portable sirve y no necesita
asociaciones de archivo ni entradas de registro.

---

## Verificaciones

```powershell
$env:PYTHONNOUSERSITE="1"

# 1. PyTorch ve la GPU
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# -> 2.5.1+cu121 True NVIDIA RTX A2000 Laptop GPU

# 2. kimodo y la extension compilada importan
python -c "from kimodo.model.load_model import load_model; from kimodo.exports.bvh import save_motion_bvh; from kimodo.constraints import load_constraints_lst; import motion_correction; print('ok')"

# 3. Blender headless
& C:\kimodo_work\tools\blender-5.2.0-windows-x64\blender.exe --background --version
# -> Blender 5.2.0 LTS
```

### Prueba de las fases 3 y 4 sin GPU ni HuggingFace

`make_test_bvh.py` genera un BVH sintético con foot skate deliberado. Sirve para
validar postproceso y export FBX antes de tener acceso al modelo:

```powershell
python scripts\make_test_bvh.py C:\kimodo_work\test\test_walk.bvh
python scripts\postprocess.py --input C:\kimodo_work\test\test_walk.bvh `
    --outdir C:\kimodo_work\test\out --policy strip_xz --loop gait
& $blender --background --python scripts\to_fbx.py -- `
    --input C:\kimodo_work\test\out --out C:\kimodo_work\test\fbx
```

Resultado esperado: `passed.all = true`, foot skate baja de ~1.96 a ~1.08
cm/frame, `root_speed_m_per_s` ~1.37, y un FBX de ~220 KB.

Nota: `make_test_bvh.py` no usa argparse — trata `sys.argv[1]` como ruta de
salida. `--help` le hace escribir un archivo llamado `--help`.

---

## 6. El pagefile, el disco y el crash 0xC0000005

Síntoma: al cargar el text encoder, el proceso muere sin excepción de Python con
código `-1073741819` (`0xC0000005`, violación de acceso), típicamente en los
primeros parámetros del `Loading weights: 6/290`.

No es un bug de kimodo ni de versiones (`transformers 5.1.0` pide `torch>=2.4`,
y 2.5.1 cumple). Es **agotamiento del límite de commit de Windows**.

Llama-3-8B en bf16 pide ~16 GB en una sola reserva. El límite de commit es
`RAM + archivo de paginación`. Cuando se agota, las reservas fallan y el código
nativo que no comprueba el retorno revienta con violación de acceso en vez de
lanzar `MemoryError`.

La trampa: el pagefile puede estar **configurado** a 32 GB y **asignado** solo a
2 GB, porque no cabe en el disco. Se ve así:

```powershell
Get-CimInstance Win32_PageFileSetting | Select Name, InitialSize, MaximumSize
# -> 32868 / 0        <- lo configurado
Get-CimInstance Win32_PageFileUsage   | Select Name, AllocatedBaseSize
# -> 2048             <- lo que Windows realmente pudo crear
Get-CimInstance Win32_OperatingSystem |
    Select @{n='CommitLimitGB';e={[math]::Round($_.TotalVirtualMemorySize/1MB,1)}},
           @{n='CommitLibreGB';e={[math]::Round($_.FreeVirtualMemory/1MB,1)}}
```

Si `AllocatedBaseSize` es mucho menor que `InitialSize`, **el problema es disco,
no configuración**. Subir el ajuste no sirve de nada hasta liberar espacio.

### Arreglo

```powershell
# 1. Liberar disco. La cache de pip suele tener el wheel de torch (2.4 GB) y mas:
python -m pip cache purge      # aqui libero 17.7 GB
conda clean -a -y

# 2. Fijar un pagefile que quepa (16 GB basta; 32 GB dejaria el disco al limite).
#    Requiere admin y REINICIAR.
$pf = Get-CimInstance Win32_PageFileSetting -Filter "Name='c:\\pagefile.sys'"
Set-CimInstance -InputObject $pf -Property @{ InitialSize = 16384; MaximumSize = 16384 }
```

Resultado: límite de commit ~47.7 GB en una máquina de 31.7 GB de RAM, con ~26 GB
de disco libre. Margen de sobra para las 100 generaciones del lote completo, que
mantienen los 16 GB reservados durante horas.

Nota: cerrar aplicaciones es un parche, no una solución. En esta máquina el mayor
consumidor era VS Code, y si el agente corre dentro de VS Code no se puede cerrar
sin matar la sesión.

---

## Acceso a Llama-3 (bloqueante, trámite manual)

Kimodo usa `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp`, que **no** está
gated — pero es un adaptador LoRA cuyo `adapter_config.json` apunta a
`meta-llama/Meta-Llama-3-8B-Instruct`, y ese sí es **`gated=manual`**: revisión
manual de Meta, no aprobación automática como dice `dev.md`.

1. Solicitar acceso en https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
2. Token *read* en https://huggingface.co/settings/tokens
3. `hf auth login`

El token no se commitea: `.gitignore` excluye `huttinface.md`, `.env` y `hf_token*`.
