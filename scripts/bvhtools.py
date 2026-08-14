"""
bvhtools.py — parser / writer / FK minimo pero correcto para BVH.

Pensado para los BVH que exporta Kimodo (esqueleto somaskel77, unidades en cm,
Y-up, +Z forward), pero funciona con cualquier BVH estandar.

Dependencias: numpy, scipy
"""

from __future__ import annotations

import re
import numpy as np
from scipy.spatial.transform import Rotation as R

ROT_CHANNELS = ("Xrotation", "Yrotation", "Zrotation")
POS_CHANNELS = ("Xposition", "Yposition", "Zposition")
_AXIS = {"Xrotation": "X", "Yrotation": "Y", "Zrotation": "Z"}


class Joint:
    __slots__ = ("name", "offset", "channels", "parent", "children", "index", "is_end")

    def __init__(self, name, offset, channels, parent, index, is_end=False):
        self.name = name
        self.offset = np.asarray(offset, dtype=np.float64)
        self.channels = list(channels)
        self.parent = parent          # index del padre, -1 para la raiz
        self.children = []
        self.index = index
        self.is_end = is_end

    def __repr__(self):
        return f"<Joint {self.name} parent={self.parent} ch={len(self.channels)}>"


class BVH:
    """Contenedor de un BVH: jerarquia + matriz de movimiento."""

    def __init__(self, joints, motion, frame_time):
        self.joints: list[Joint] = joints
        self.motion: np.ndarray = np.asarray(motion, dtype=np.float64)  # [T, C]
        self.frame_time: float = float(frame_time)
        self._build_channel_index()

    # ------------------------------------------------------------------ info
    @property
    def num_frames(self) -> int:
        return self.motion.shape[0]

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time if self.frame_time > 0 else 30.0

    @property
    def names(self) -> list[str]:
        return [j.name for j in self.joints]

    def index_of(self, name: str) -> int:
        for j in self.joints:
            if j.name == name:
                return j.index
        raise KeyError(name)

    # --------------------------------------------------------------- canales
    def _build_channel_index(self):
        """Mapa joint -> posicion de cada canal dentro de la fila de motion."""
        self.rot_cols = {}   # jidx -> (cols[3], order_str)  p.ej. ([3,4,5], "ZXY")
        self.pos_cols = {}   # jidx -> cols[3] en orden X,Y,Z
        c = 0
        for j in self.joints:
            rc, order = [], ""
            pc = [None, None, None]
            for ch in j.channels:
                if ch in ROT_CHANNELS:
                    rc.append(c)
                    order += _AXIS[ch]
                elif ch in POS_CHANNELS:
                    pc[POS_CHANNELS.index(ch)] = c
                c += 1
            if len(rc) == 3:
                self.rot_cols[j.index] = (rc, order)
            if all(v is not None for v in pc):
                self.pos_cols[j.index] = pc
        self.num_channels = c

    def rotations(self, jidx: int) -> np.ndarray:
        """Angulos de Euler [T,3] en el orden de canales declarado (grados)."""
        cols, _ = self.rot_cols[jidx]
        return self.motion[:, cols]

    def set_rotations(self, jidx: int, values: np.ndarray):
        cols, _ = self.rot_cols[jidx]
        self.motion[:, cols] = values

    def rot_order(self, jidx: int) -> str:
        return self.rot_cols[jidx][1]

    def translations(self, jidx: int) -> np.ndarray:
        """Traslacion [T,3] en XYZ (grados/unidades del archivo)."""
        return self.motion[:, self.pos_cols[jidx]]

    def set_translations(self, jidx: int, values: np.ndarray):
        self.motion[:, self.pos_cols[jidx]] = values

    @property
    def root(self) -> int:
        return 0

    def has_translation(self, jidx: int) -> bool:
        return jidx in self.pos_cols

    # -------------------------------------------------------------------- FK
    def forward_kinematics(self):
        """Devuelve (positions [T,J,3], rotmats [T,J,3,3]) en espacio mundo.

        J incluye los End Site como joints (para poder medir la punta del pie).
        """
        T = self.num_frames
        J = len(self.joints)
        pos = np.zeros((T, J, 3))
        rot = np.zeros((T, J, 3, 3))

        for j in self.joints:
            i = j.index
            if i in self.rot_cols:
                order = self.rot_order(i)
                local_rot = R.from_euler(order, self.rotations(i), degrees=True).as_matrix()
            else:
                local_rot = np.tile(np.eye(3), (T, 1, 1))

            local_off = np.tile(j.offset, (T, 1))
            if self.has_translation(i):
                local_off = local_off + self.translations(i)

            if j.parent < 0:
                rot[:, i] = local_rot
                pos[:, i] = local_off
            else:
                p = j.parent
                rot[:, i] = rot[:, p] @ local_rot
                pos[:, i] = pos[:, p] + np.einsum("tij,tj->ti", rot[:, p], local_off)

        return pos, rot

    # ---------------------------------------------------------------- copias
    def copy(self) -> "BVH":
        joints = []
        for j in self.joints:
            nj = Joint(j.name, j.offset.copy(), list(j.channels), j.parent, j.index, j.is_end)
            joints.append(nj)
        for j in joints:
            if j.parent >= 0:
                joints[j.parent].children.append(j.index)
        return BVH(joints, self.motion.copy(), self.frame_time)

    def slice_frames(self, start: int, end: int) -> "BVH":
        out = self.copy()
        out.motion = self.motion[start:end].copy()
        return out


# ====================================================================== parse
_NUM = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?")


def load_bvh(path) -> BVH:
    with open(path, "r", errors="ignore") as f:
        text = f.read()

    hier_txt, motion_txt = re.split(r"\bMOTION\b", text, maxsplit=1)
    tokens = hier_txt.replace("{", " { ").replace("}", " } ").split()

    joints: list[Joint] = []
    stack: list[int] = []
    i = 0
    end_counter = 0

    while i < len(tokens):
        tok = tokens[i]
        if tok in ("ROOT", "JOINT"):
            name = tokens[i + 1]
            parent = stack[-1] if stack else -1
            j = Joint(name, (0, 0, 0), [], parent, len(joints))
            joints.append(j)
            if parent >= 0:
                joints[parent].children.append(j.index)
            i += 2
        elif tok == "End":  # End Site
            parent = stack[-1]
            end_counter += 1
            j = Joint(f"{joints[parent].name}_End", (0, 0, 0), [], parent, len(joints), is_end=True)
            joints.append(j)
            joints[parent].children.append(j.index)
            i += 2  # "End" "Site"
        elif tok == "{":
            stack.append(len(joints) - 1)
            i += 1
        elif tok == "}":
            stack.pop()
            i += 1
        elif tok == "OFFSET":
            joints[-1].offset = np.array([float(tokens[i + 1]), float(tokens[i + 2]), float(tokens[i + 3])])
            i += 4
        elif tok == "CHANNELS":
            n = int(tokens[i + 1])
            joints[stack[-1]].channels = tokens[i + 2: i + 2 + n]
            i += 2 + n
        else:
            i += 1

    m = re.search(r"Frames:\s*(\d+)", motion_txt)
    num_frames = int(m.group(1)) if m else 0
    m = re.search(r"Frame Time:\s*([0-9.eE+-]+)", motion_txt)
    frame_time = float(m.group(1)) if m else 1.0 / 30.0

    data_start = motion_txt.find("Frame Time:")
    data_txt = motion_txt[motion_txt.find("\n", data_start) + 1:]
    rows = [ln for ln in data_txt.strip().splitlines() if ln.strip()]
    motion = np.array([[float(v) for v in ln.split()] for ln in rows], dtype=np.float64)
    if num_frames and motion.shape[0] != num_frames:
        motion = motion[:num_frames] if motion.shape[0] > num_frames else motion

    return BVH(joints, motion, frame_time)


# ====================================================================== write
def save_bvh(bvh: BVH, path):
    lines = ["HIERARCHY"]

    def emit(jidx, depth):
        j = bvh.joints[jidx]
        pad = "  " * depth
        if j.is_end:
            lines.append(f"{pad}End Site")
            lines.append(f"{pad}{{")
            lines.append(f"{pad}  OFFSET {j.offset[0]:.6f} {j.offset[1]:.6f} {j.offset[2]:.6f}")
            lines.append(f"{pad}}}")
            return
        kw = "ROOT" if j.parent < 0 else "JOINT"
        lines.append(f"{pad}{kw} {j.name}")
        lines.append(f"{pad}{{")
        lines.append(f"{pad}  OFFSET {j.offset[0]:.6f} {j.offset[1]:.6f} {j.offset[2]:.6f}")
        lines.append(f"{pad}  CHANNELS {len(j.channels)} {' '.join(j.channels)}")
        for c in j.children:
            emit(c, depth + 1)
        lines.append(f"{pad}}}")

    emit(0, 0)
    lines.append("MOTION")
    lines.append(f"Frames: {bvh.num_frames}")
    lines.append(f"Frame Time: {bvh.frame_time:.8f}")
    for row in bvh.motion:
        lines.append(" ".join(f"{v:.6f}" for v in row))

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# =================================================== deteccion de huesos clave
_SIDE = {"left": r"^(l|left)", "right": r"^(r|right)"}
_PART = {
    "hip":   r"(upleg|upperleg|thigh|femur|hip)",
    "knee":  r"(lowerleg|leg|knee|shin|tibia|calf)",
    "ankle": r"(foot|ankle)",
    "toe":   r"(toe|ball)",
}
# El orden importa: primero lo mas especifico, y cada joint se consume una sola vez.
_ORDER = ["toe", "ankle", "hip", "knee"]

# Huesos que el sistema de mascara considera "pierna" (para clips upper-body)
LEG_HINTS = ("leg", "thigh", "femur", "knee", "shin", "tibia", "foot", "ankle", "toe", "ball", "hip")


def detect_key_joints(bvh: BVH, overrides: dict | None = None) -> dict:
    """Heuristica de nombres -> indices de joints. Devuelve solo lo que encuentra.

    `overrides` permite forzar el mapeo cuando el esqueleto usa nombres raros:
    {"left_ankle": "l_foot_jnt", ...}
    """
    found = {}
    used = set()
    lowered = [(j.index, j.name.lower().replace("_", "").replace(" ", "").replace(".", ""))
               for j in bvh.joints if j.index != 0 and not j.is_end]

    for part in _ORDER:
        for side, spat in _SIDE.items():
            key = f"{side}_{part}"
            pat = spat + r".*" + _PART[part]
            hits = [i for i, n in lowered if re.search(pat, n) and i not in used]
            if hits:
                # el mas profundo en la cadena suele ser el correcto para toe/ankle,
                # el mas superficial para hip
                hits.sort(key=lambda i: _depth(bvh, i), reverse=(part in ("toe", "ankle")))
                found[key] = hits[0]
                used.add(hits[0])

    if overrides:
        for k, name in overrides.items():
            try:
                found[k] = bvh.index_of(name)
            except KeyError:
                pass
    return found


def _depth(bvh: BVH, idx: int) -> int:
    d, cur = 0, idx
    while bvh.joints[cur].parent >= 0:
        cur = bvh.joints[cur].parent
        d += 1
    return d


def leg_joint_indices(bvh: BVH) -> list[int]:
    out = []
    for j in bvh.joints:
        n = j.name.lower()
        if j.index != 0 and any(h in n for h in LEG_HINTS):
            out.append(j.index)
    return out
