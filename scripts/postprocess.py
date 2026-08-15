"""
postprocess.py — limpieza de BVH de Kimodo para usarlos como bloques atomicos.

Hace, en este orden:
  1. FK y deteccion de contacto de pies (talon/punta por altura + velocidad).
  2. Correccion de foot skate por integracion de velocidad del root
     (durante el contacto el pie NO se mueve: el que se mueve es el root).
  3. Nivelado al suelo y correccion de penetracion.
  4. Politica de root:
       strip_xz    -> BVH in-place + curva de root en JSON (loops de locomocion)
       pin_origin  -> clava el root en el origen (idles / upper / reacciones)
       keep        -> deja el desplazamiento (transiciones one-shot)
  5. Opcional: congelar las piernas (clips de upper body enmascarados).
  6. Opcional: recorte de loop (busca el mejor par inicio/periodo) + blend ciclico.
  7. Metricas de QC en JSON.

Uso:
  python postprocess.py --input clip.bvh --outdir out --policy strip_xz --loop gait
  python postprocess.py --input clip.bvh --outdir out --policy pin_origin --freeze-legs

Dependencias: numpy, scipy
"""

from __future__ import annotations

import argparse
import json
import os
import numpy as np
from scipy.spatial.transform import Rotation as R, Slerp

from bvhtools import load_bvh, save_bvh, detect_key_joints, leg_joint_indices, BVH


# --------------------------------------------------------------- utilidades
def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    k = np.ones(win) / win
    pad = win // 2
    out = np.empty_like(x)
    for c in range(x.shape[1] if x.ndim > 1 else 1):
        col = x[:, c] if x.ndim > 1 else x
        padded = np.concatenate([np.full(pad, col[0]), col, np.full(pad, col[-1])])
        sm = np.convolve(padded, k, mode="same")[pad:pad + len(col)]
        if x.ndim > 1:
            out[:, c] = sm
        else:
            out = sm
    return out


def _yaw_of(rotmats: np.ndarray) -> np.ndarray:
    """Yaw (rad) alrededor de Y a partir del vector forward local +Z."""
    fwd = rotmats @ np.array([0.0, 0.0, 1.0])
    return np.arctan2(fwd[:, 0], fwd[:, 2])


# ------------------------------------------------------- contacto de pies
def detect_contacts(pos, keys, fps, ground, height_thr, speed_thr):
    """Devuelve dict lado -> bool[T] y las alturas usadas."""
    contacts = {}
    for side in ("left", "right"):
        idxs = [keys[k] for k in (f"{side}_ankle", f"{side}_toe") if k in keys]
        if not idxs:
            continue
        p = pos[:, idxs, :]                       # [T, n, 3]
        height = p[:, :, 1].min(axis=1) - ground
        vel = np.zeros(len(p))
        d = np.linalg.norm(np.diff(p[:, :, [0, 2]], axis=0), axis=2).min(axis=1) * fps
        vel[1:] = d
        vel[0] = vel[1] if len(vel) > 1 else 0.0
        contacts[side] = (height < height_thr) & (vel < speed_thr)
    return contacts


def _debounce(mask: np.ndarray, min_run: int) -> np.ndarray:
    """Elimina rachas mas cortas que min_run (parpadeos del detector de contacto).

    Sin esto contar despegues no sirve de nada: un solo frame en el que el
    detector duda parte un contacto en dos y suma un ciclo fantasma.
    """
    if min_run <= 1 or len(mask) == 0:
        return mask.copy()
    out = mask.copy()
    n, i = len(out), 0
    while i < n:
        j = i
        while j < n and out[j] == out[i]:
            j += 1
        if (j - i) < min_run and i > 0:       # la primera racha no tiene vecino previo
            out[i:j] = out[i - 1]
        i = j
    return out


def gait_cycles(contacts: dict, fps: float, min_run_s: float = 0.12) -> dict:
    """Cuenta despegues (contacto -> aire) por pie, con antirrebote.

    Un ciclo de marcha completo es un despegue por pie. Una caminata real de
    varios segundos da 3-5; un clip que da UN paso y se congela da 0 o 1, y ahi
    no hay ciclo que loopear por mucho que el detector de loop devuelva un
    periodo. `cycles` es el minimo de los dos pies: si solo oscila una pierna,
    tampoco es marcha.

    min_run_s = 0.12 esta calibrado, no elegido a ojo: contra el BVH sintetico de
    `make_test_bvh.py` (periodo 1.1 s en 5 s = 4.5 zancadas) 0.08 s cuenta 8-10
    despegues por pie —el doble— porque el detector de contacto parpadea, y 0.16 s
    ya se come fases de vuelo reales y devuelve 0. A 0.12 s salen 4-5, que es la
    verdad. Si cambias el fps o el detector de contacto, revisa esto.
    """
    min_run = max(2, int(round(min_run_s * fps)))
    per_side = {}
    for side, mask in contacts.items():
        m = _debounce(np.asarray(mask, dtype=bool), min_run)
        per_side[side] = int(np.sum(m[:-1] & ~m[1:])) if len(m) > 1 else 0
    return {
        "cycles": int(min(per_side.values())) if per_side else 0,
        "per_side": per_side,
        "debounce_frames": min_run,
    }


def frozen_tail(bvh: BVH, rel_thr: float = 0.10, abs_thr: float = 0.05):
    """Primer frame de la cola congelada. Devuelve (frame, fraccion_congelada).

    Se mide RELATIVO AL ROOT: en espacio global un clip que avanza con el cuerpo
    rigido tiene velocidad alta y parece vivo, que es justo el caso que hay que
    cazar. Si no hay cola congelada devuelve num_frames (o sea: "congelado desde
    el final", que es lo mismo que no estarlo).

    El umbral sale del percentil 90 de la energia, no de la mediana: si el 70%
    del clip esta congelado la mediana ya vive dentro de la parte congelada y el
    detector no detectaria nada.
    """
    feat = _pose_features(bvh)                # ya viene local al root
    T = len(feat)
    if T < 4:
        return T, 0.0
    njoints = max(1, feat.shape[1] // 3)
    e = np.zeros(T)
    e[1:] = np.linalg.norm(np.diff(feat, axis=0), axis=1) / np.sqrt(njoints)
    thr = max(abs_thr, rel_thr * float(np.percentile(e[1:], 90)))
    start = T
    for t in range(T - 1, 0, -1):
        if e[t] > thr:
            break
        start = t
    return int(start), round(float((T - start) / T), 4)


def leg_motion_deg(bvh: BVH) -> float:
    """Maxima desviacion angular de las piernas respecto al frame 0, en grados.

    Es la comprobacion de que `freeze_legs` hizo su trabajo en los clips de
    upper body enmascarados.
    """
    idxs = [i for i in leg_joint_indices(bvh) if i in bvh.rot_cols]
    if not idxs or bvh.num_frames < 2:
        return 0.0
    worst = 0.0
    for i in idxs:
        order = bvh.rot_order(i)
        rots = R.from_euler(order, bvh.rotations(i), degrees=True)
        worst = max(worst, float(np.degrees((rots[0].inv() * rots).magnitude()).max()))
    return round(worst, 3)


def heading_delta_deg(bvh: BVH) -> float:
    """Giro neto del root en grados (con signo, segun la convencion de _yaw_of)."""
    if bvh.num_frames < 2:
        return 0.0
    _, rot = bvh.forward_kinematics()
    yaw = np.unwrap(_yaw_of(rot[:, bvh.root]))
    return round(float(np.degrees(yaw[-1] - yaw[0])), 3)


def peak_frames(bvh: BVH, n: int = 3, min_sep_ratio: float = 0.12) -> list[int]:
    """Frames de maxima desviacion respecto a la pose media, separados entre si.

    Muestrear al 25/50/75% se pierde los gestos cortos: un punetazo al aire dura
    ~8 frames y cae entre dos muestras con facilidad. La pose clave vive en el
    pico de desviacion, no en un porcentaje fijo del clip. La separacion minima
    evita devolver tres frames del mismo instante.
    """
    feat = _pose_features(bvh)
    T = len(feat)
    if T == 0:
        return []
    d = np.linalg.norm(feat - feat.mean(axis=0), axis=1)
    sep = max(2, int(round(min_sep_ratio * T)))
    picked = []
    for t in np.argsort(-d):
        if len(picked) >= n:
            break
        if all(abs(int(t) - p) >= sep for p in picked):
            picked.append(int(t))
    return sorted(picked)


def auto_thresholds(pos, keys, fps):
    """Umbrales de contacto adaptados al clip (evita el 0% o el 100% de contacto)."""
    heights, speeds = [], []
    for side in ("left", "right"):
        idxs = [keys[k] for k in (f"{side}_ankle", f"{side}_toe") if k in keys]
        if not idxs:
            continue
        p = pos[:, idxs, :]
        heights.append(p[:, :, 1].min(axis=1))
        v = np.zeros(len(p))
        v[1:] = np.linalg.norm(np.diff(p[:, :, [0, 2]], axis=0), axis=2).min(axis=1) * fps
        v[0] = v[1] if len(v) > 1 else 0.0
        speeds.append(v)
    if not heights:
        return 3.0, 20.0, 0.0
    h = np.concatenate(heights)
    s = np.concatenate(speeds)
    ground = float(np.percentile(h, 2))
    span = float(np.percentile(h, 95) - ground)
    height_thr = max(1.0, 0.22 * span) if span > 1e-6 else 1.0
    low = s[h - ground < height_thr]
    speed_thr = float(np.clip(np.percentile(low, 65) if len(low) > 5 else 20.0, 4.0, 80.0))
    return height_thr, speed_thr, ground


def _foot_velocity(pos, keys, side, fps):
    idxs = [keys[k] for k in (f"{side}_ankle", f"{side}_toe") if k in keys]
    p = pos[:, idxs, :].mean(axis=1)              # [T,3]
    v = np.zeros_like(p)
    v[1:] = (p[1:] - p[:-1]) * fps
    return v


# ------------------------------------------------- correccion de foot skate
def fix_foot_skate(bvh: BVH, keys: dict, ground: float, height_thr: float,
                   speed_thr: float, smooth_win: int = 3):
    """Integra la velocidad del pie plantado y la resta del root.

    Es el arreglo real del "los pies se mueven de lugar": mientras un pie esta
    en contacto su velocidad horizontal debe ser 0; toda esa velocidad se pasa
    al root. No toca ninguna rotacion, asi que nunca rompe la pose.
    """
    pos, _ = bvh.forward_kinematics()
    fps = bvh.fps
    T = bvh.num_frames
    contacts = detect_contacts(pos, keys, fps, ground, height_thr, speed_thr)
    if not contacts:
        return np.zeros((T, 3)), contacts

    vels = {s: _foot_velocity(pos, keys, s, fps) for s in contacts}

    corr_vel = np.zeros((T, 3))
    for t in range(T):
        active = [vels[s][t] for s in contacts if contacts[s][t]]
        if active:
            v = np.mean(active, axis=0)
            corr_vel[t, 0] = -v[0]
            corr_vel[t, 2] = -v[2]

    corr_vel = _smooth(corr_vel, smooth_win)
    offset = np.cumsum(corr_vel, axis=0) / fps
    offset -= offset[0]

    tr = bvh.translations(bvh.root)
    bvh.set_translations(bvh.root, tr + offset)
    return offset, contacts


def fix_ground(bvh: BVH, keys: dict, smooth_win: int = 5):
    """Baja/sube el root para que el pie mas bajo toque el suelo sin penetrar."""
    pos, _ = bvh.forward_kinematics()
    foot_idx = [keys[k] for k in keys if k.endswith(("ankle", "toe"))]
    if not foot_idx:
        return 0.0, 0.0
    min_y = pos[:, foot_idx, 1].min(axis=1)
    ground = float(np.percentile(min_y, 5))       # suelo estimado
    penetration = np.maximum(0.0, ground - min_y)
    lift = _smooth(penetration.reshape(-1, 1), smooth_win).ravel()

    tr = bvh.translations(bvh.root)
    tr[:, 1] += lift - ground                     # nivela y corrige penetracion
    bvh.set_translations(bvh.root, tr)
    return ground, float(penetration.max())


# ------------------------------------------------------- politicas de root
def apply_root_policy(bvh: BVH, policy: str, strip_yaw: bool = True):
    """Devuelve la curva de root extraida (o None si policy == 'keep')."""
    if policy == "keep":
        return None

    _, rot = bvh.forward_kinematics()
    fps = bvh.fps
    tr = bvh.translations(bvh.root).copy()
    yaw = _yaw_of(rot[:, bvh.root])
    dyaw = np.unwrap(yaw) - yaw[0]

    curve = {
        "fps": fps,
        "frames": int(bvh.num_frames),
        "root_xz": tr[:, [0, 2]].tolist(),
        "root_y": tr[:, 1].tolist(),
        "heading_deg": np.degrees(dyaw).tolist(),
    }
    disp = tr[-1, [0, 2]] - tr[0, [0, 2]]
    dur = bvh.num_frames / fps
    curve["total_displacement"] = disp.tolist()
    curve["mean_speed_units_per_s"] = float(np.linalg.norm(disp) / max(dur, 1e-6))
    curve["mean_speed_m_per_s"] = curve["mean_speed_units_per_s"] / 100.0  # BVH de Kimodo en cm

    if strip_yaw and bvh.num_frames > 1:
        order = bvh.rot_order(bvh.root)
        cur = R.from_euler(order, bvh.rotations(bvh.root), degrees=True)
        undo = R.from_euler("Y", (-dyaw).reshape(-1, 1), degrees=False)
        bvh.set_rotations(bvh.root, (undo * cur).as_euler(order, degrees=True))

    tr[:, 0] = tr[0, 0]
    tr[:, 2] = tr[0, 2]
    bvh.set_translations(bvh.root, tr)
    return curve


def freeze_legs(bvh: BVH, ref_frame: int = 0, blend_frames: int = 6):
    """Congela las piernas en la pose de referencia (clips de upper body)."""
    idxs = leg_joint_indices(bvh)
    n = 0
    for i in idxs:
        if i not in bvh.rot_cols:
            continue
        rots = bvh.rotations(i).copy()
        ref = rots[ref_frame].copy()
        rots[:] = ref
        bvh.set_rotations(i, rots)
        n += 1
    return n


# ------------------------------------------------------------------- loops
def _pose_features(bvh: BVH):
    pos, _ = bvh.forward_kinematics()
    local = pos - pos[:, bvh.root: bvh.root + 1, :]
    return local.reshape(len(local), -1)


def find_loop(bvh: BVH, min_period_s=0.5, max_period_s=2.5, head_trim_s=0.5,
              vel_weight=2.0):
    """Busca (start, period) que minimicen la distancia de pose+velocidad."""
    feat = _pose_features(bvh)
    fps = bvh.fps
    T = len(feat)
    vel = np.zeros_like(feat)
    vel[1:] = feat[1:] - feat[:-1]

    p_min = max(2, int(min_period_s * fps))
    p_max = min(T - 2, int(max_period_s * fps))
    s_min = int(head_trim_s * fps)
    if p_max <= p_min or T <= p_min + s_min + 2:
        return None

    best = None
    for s in range(s_min, T - p_min - 1):
        for p in range(p_min, min(p_max, T - s - 1) + 1):
            d = np.linalg.norm(feat[s] - feat[s + p]) + vel_weight * np.linalg.norm(vel[s] - vel[s + p])
            # penaliza periodos muy cortos para no colapsar en microloops
            d = d / (1.0 + 0.15 * (p / fps))
            if best is None or d < best[0]:
                best = (float(d), s, p)
    return best


def cut_loop(bvh: BVH, start: int, period: int, blend_frames: int = 5) -> BVH:
    """Corta [start, start+period) y hace crossfade ciclico con slerp."""
    T = bvh.num_frames
    k = min(blend_frames, period // 4, max(0, T - (start + period)))
    out = bvh.slice_frames(start, start + period)

    if k > 0:
        tail_src = bvh.slice_frames(start + period, start + period + k)
        w = np.linspace(0.0, 1.0, k + 2)[1:-1]     # pesos internos
        for j in bvh.joints:
            i = j.index
            if i not in bvh.rot_cols:
                continue
            order = bvh.rot_order(i)
            a = R.from_euler(order, out.motion[period - k:period][:, bvh.rot_cols[i][0]], degrees=True)
            b = R.from_euler(order, tail_src.motion[:, bvh.rot_cols[i][0]], degrees=True)
            blended = []
            for n in range(k):
                key = R.concatenate([a[n], b[n]])
                blended.append(Slerp([0.0, 1.0], key)([w[n]])[0])
            out.motion[period - k:period, bvh.rot_cols[i][0]] = \
                R.concatenate(blended).as_euler(order, degrees=True)
        if bvh.has_translation(bvh.root):
            cols = bvh.pos_cols[bvh.root]
            a = out.motion[period - k:period][:, cols]
            b = tail_src.motion[:, cols]
            out.motion[period - k:period, cols] = a * (1 - w[:, None]) + b * w[:, None]
    return out


# ---------------------------------------------------------------- metricas
def measure(bvh: BVH, keys: dict, height_thr=None, speed_thr=None) -> dict:
    pos, _ = bvh.forward_kinematics()
    fps = bvh.fps
    foot_idx = [keys[k] for k in keys if k.endswith(("ankle", "toe"))]
    ah, asp, ground = auto_thresholds(pos, keys, fps)
    height_thr = ah if height_thr is None else height_thr
    speed_thr = asp if speed_thr is None else speed_thr
    contacts = detect_contacts(pos, keys, fps, ground, height_thr, speed_thr)

    skate = []
    for side, mask in contacts.items():
        idxs = [keys[k] for k in (f"{side}_ankle", f"{side}_toe") if k in keys]
        p = pos[:, idxs, :].mean(axis=1)
        d = np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1)
        m = mask[1:] & mask[:-1]
        if m.any():
            skate.append(d[m])
    skate_all = np.concatenate(skate) if skate else np.zeros(1)

    min_y = pos[:, foot_idx, 1].min(axis=1) if foot_idx else np.zeros(len(pos))
    pen = float(np.maximum(0.0, ground - min_y).max())

    jitter = float(np.linalg.norm(np.diff(pos, n=3, axis=0), axis=2).mean())

    feat = _pose_features(bvh)
    loop_err = float(np.linalg.norm(feat[0] - feat[-1]) / max(1, feat.shape[1] // 3) ** 0.5)

    contact_ratio = {s: round(float(m.mean()), 3) for s, m in contacts.items()}

    return {
        "frames": int(bvh.num_frames),
        "fps": round(fps, 3),
        "duration_s": round(bvh.num_frames / fps, 3),
        "foot_skate_mean_cm_per_frame": round(float(skate_all.mean()), 4),
        "foot_skate_max_cm_per_frame": round(float(skate_all.max()), 4),
        "foot_skate_mean_cm_per_s": round(float(skate_all.mean() * fps), 3),
        "ground_penetration_cm": round(pen, 4),
        "jitter_cm": round(jitter, 4),
        "loop_pose_error_cm": round(loop_err, 4),
        "contact_ratio": contact_ratio,
        "gait": gait_cycles(contacts, fps),
        "leg_motion_deg": leg_motion_deg(bvh),
        "peak_frames": peak_frames(bvh),
        "thresholds": {"height_cm": round(height_thr, 3), "speed_cm_s": round(speed_thr, 2)},
        "detected_joints": {k: bvh.joints[v].name for k, v in sorted(keys.items())},
    }


# -------------------------------------------------------------------- main
def _verdict(report: dict, clip_qc: dict) -> dict:
    """Compara las metricas limpias contra los umbrales del catalogo."""
    c = report.get("clean", {})
    checks = {}
    checks["foot_skate"] = c.get("foot_skate_mean_cm_per_frame", 99) <= clip_qc.get("max_foot_skate_cm", 2.0)
    checks["ground"] = c.get("ground_penetration_cm", 99) <= clip_qc.get("max_ground_penetration_cm", 2.0)
    if clip_qc.get("require_loop"):
        checks["loop"] = report.get("loop") is not None and "error" not in (report.get("loop") or {})

    # Ciclo de marcha. El check `loop` de arriba solo dice "encontre UN periodo",
    # y el detector siempre encuentra alguno: ante un clip sin periodicidad se
    # queda con la ventana mas corta permitida. Por eso los walks de un solo paso
    # pasaban el QC entero con 50/50. Esto se mide sobre el clip COMPLETO, no
    # sobre el loop ya recortado (un loop correcto dura un ciclo, no dos).
    if report.get("loop_kind") == "gait":
        checks["gait_cycles"] = (report.get("gait", {}).get("cycles", 0)
                                 >= clip_qc.get("min_gait_cycles", 2))

    # Cola congelada, tambien sobre el clip completo: el recorte del loop se la
    # lleva por delante y deja un clip *valido* que sigue sin tener movimiento.
    # Por defecto solo se exige a los loops; en un one-shot como
    # `react_collapse_knees` acabar quieto en el suelo es correcto. Cualquier
    # clip puede pedirlo con `max_frozen_tail_ratio` en su qc.
    ftr = report.get("frozen_tail_ratio")
    max_ftr = clip_qc.get("max_frozen_tail_ratio",
                          0.25 if clip_qc.get("require_loop") else None)
    if ftr is not None and max_ftr is not None:
        checks["frozen_tail"] = ftr <= max_ftr

    # --- umbrales del catalogo que hasta ahora no leia nadie ---
    if "max_leg_motion_deg" in clip_qc:
        checks["leg_motion"] = c.get("leg_motion_deg", 999) <= clip_qc["max_leg_motion_deg"]
    if "max_root_drift_cm" in clip_qc:
        checks["root_drift"] = report.get("root_drift_cm", 999) <= clip_qc["max_root_drift_cm"]
    if "expect_heading_delta_deg" in clip_qc:
        # Se compara la MAGNITUD: el signo depende de la convencion de ejes del
        # rig y un rig espejado invertiria el criterio sin que el clip este mal.
        # El signo real queda en `heading_delta_deg` del reporte para revisarlo.
        exp = abs(float(clip_qc["expect_heading_delta_deg"]))
        act = abs(float(report.get("heading_delta_deg", 0.0)))
        checks["heading"] = abs(act - exp) <= clip_qc.get("heading_tolerance_deg", 40.0)

    # El clip DEBE quedar quieto si su politica lo pide. Sin esta comprobacion,
    # un bug que aplicase la politica al joint equivocado pasaba el QC entero:
    # foot skate y penetracion salian perfectos porque se median bien, pero el
    # personaje seguia avanzando. Es exactamente lo que paso.
    if report.get("policy") in ("strip_xz", "pin_origin"):
        checks["in_place"] = report.get("residual_xz_cm", 999) <= 1.0

    # Velocidad de produccion: si es absurda, el controlador del personaje la
    # usara mal y los pies patinaran en pantalla aunque el BVH este limpio.
    v = report.get("root_speed_m_per_s")
    if report.get("policy") == "strip_xz" and v is not None:
        checks["root_speed"] = 0.2 <= v <= 8.0

    # Desviacion contra la velocidad esperada del catalogo. Tolerancia ancha (x2)
    # a proposito: la medida manda, esto solo caza el caso en que el clip no es
    # el movimiento que se pidio (un "sprint" que camina).
    exp_v = clip_qc.get("expected_speed_m_s")
    if exp_v and v is not None:
        checks["expected_speed"] = (exp_v / 2.0) <= v <= (exp_v * 2.0)

    checks["all"] = all(v for k, v in checks.items() if k != "all")
    return checks


def process(path, outdir, policy="strip_xz", loop=None, freeze=False,
            height_thr=None, speed_thr=None, blend=5, strip_yaw=True,
            min_period_s=0.5, max_period_s=2.5, head_trim_s=0.5, no_skate_fix=False):
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    bvh = load_bvh(path)
    keys = detect_key_joints(bvh)
    if not keys:
        raise SystemExit(f"No pude identificar huesos de pierna en {path}. "
                         f"Huesos: {bvh.names[:20]} ...")

    report = {"clip": stem, "policy": policy,
              "before": measure(bvh, keys, height_thr, speed_thr)}

    # 1) suelo + 2) foot skate, SIEMPRE en espacio global (si no, la metrica miente:
    #    en un clip in-place los pies tienen que deslizar por definicion).
    fix_ground(bvh, keys)
    if not no_skate_fix:
        pos, _ = bvh.forward_kinematics()
        ah, asp, _ = auto_thresholds(pos, keys, bvh.fps)
        fix_foot_skate(bvh, keys, 0.0,
                       ah if height_thr is None else height_thr,
                       asp if speed_thr is None else speed_thr)
        fix_ground(bvh, keys)

    # 3) piernas congeladas para clips de upper body enmascarados
    if freeze:
        report["frozen_leg_joints"] = freeze_legs(bvh)
        fix_ground(bvh, keys)

    # Guardamos el clip COMPLETO, ya corregido, antes de recortarlo: de aqui
    # sale la velocidad real del ciclo (ver mas abajo).
    pre_loop = bvh.slice_frames(0, bvh.num_frames)

    # 3b) metricas de la FUENTE COMPLETA. Van aqui y no en `clean` porque el
    # recorte del loop esconde justo los dos fallos que mas importan: se lleva la
    # cola congelada, y deja un periodo de un solo paso que parece un ciclo.
    _sp, _ = pre_loop.forward_kinematics()
    _ah, _asp, _ag = auto_thresholds(_sp, keys, pre_loop.fps)
    _sc = detect_contacts(_sp, keys, pre_loop.fps, _ag,
                          _ah if height_thr is None else height_thr,
                          _asp if speed_thr is None else speed_thr)
    report["loop_kind"] = loop
    report["source_frames"] = int(pre_loop.num_frames)
    report["gait"] = gait_cycles(_sc, pre_loop.fps)
    report["frozen_tail_from_frame"], report["frozen_tail_ratio"] = frozen_tail(pre_loop)
    report["heading_delta_deg"] = heading_delta_deg(pre_loop)
    if pre_loop.has_translation(pre_loop.root):
        _d = pre_loop.translations(pre_loop.root)[:, [0, 2]]
        report["root_drift_cm"] = round(float(np.abs(_d - _d[0]).max()), 4)

    # 4) recorte del loop (todavia en espacio global)
    loop_info = None
    if loop:
        rng = (min_period_s, max_period_s) if loop == "gait" else (max(min_period_s, 1.0),
                                                                   max(max_period_s, 4.0))
        found = find_loop(bvh, rng[0], rng[1], head_trim_s)
        if found:
            score, s, p = found
            bvh = cut_loop(bvh, s, p, blend_frames=blend)
            loop_info = {"start_frame": s, "period_frames": p,
                         "period_s": round(p / bvh.fps, 3), "match_score": round(score, 4)}
        else:
            loop_info = {"error": "no encontre un periodo valido; el clip es muy corto"}
    report["loop"] = loop_info

    # 5) metrica limpia ANTES de tocar el root (esta es la que vale para QC)
    report["clean"] = measure(bvh, keys, height_thr, speed_thr)

    # 6) politica de root
    # La velocidad se mide ANTES de cortar el loop: un loop bien cerrado acaba
    # casi donde empezo, asi que su desplazamiento neto no dice nada del ritmo
    # real de la caminata. `pre_loop` es el clip completo ya corregido de
    # contactos, que es donde vive la velocidad de produccion.
    if policy != "keep":
        v = apply_root_policy(pre_loop, policy, strip_yaw=False)
        if v:
            report["root_speed_m_per_s"] = round(v["mean_speed_m_per_s"], 4)

    curve = apply_root_policy(bvh, policy, strip_yaw=strip_yaw)
    report["root_curve"] = curve is not None
    if curve and "root_speed_m_per_s" not in report:
        report["root_speed_m_per_s"] = round(curve["mean_speed_m_per_s"], 4)

    # residuo de traslacion tras aplicar la politica: si la politica funciono,
    # el joint que lleva el movimiento tiene XZ constante
    if bvh.has_translation(bvh.root):
        _tr = bvh.translations(bvh.root)[:, [0, 2]]
        report["residual_xz_cm"] = round(float(np.abs(_tr - _tr[0]).max()), 4)
    report["final_loop_pose_error_cm"] = measure(bvh, keys, height_thr, speed_thr)["loop_pose_error_cm"]

    report["passed"] = _verdict(report, clip_qc={})

    out_bvh = os.path.join(outdir, f"{stem}.bvh")
    save_bvh(bvh, out_bvh)
    if curve:
        with open(os.path.join(outdir, f"{stem}.root.json"), "w") as f:
            json.dump(curve, f)
    with open(os.path.join(outdir, f"{stem}.qc.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--policy", default="strip_xz", choices=["strip_xz", "pin_origin", "keep"])
    ap.add_argument("--loop", default=None, choices=[None, "gait", "full"])
    ap.add_argument("--freeze-legs", action="store_true")
    ap.add_argument("--no-skate-fix", action="store_true")
    ap.add_argument("--no-strip-yaw", action="store_true")
    ap.add_argument("--height-thr", type=float, default=None, help="umbral de altura de contacto (unidades del BVH, cm en Kimodo)")
    ap.add_argument("--speed-thr", type=float, default=None, help="umbral de velocidad de contacto (unidades/s)")
    ap.add_argument("--blend", type=int, default=5)
    a = ap.parse_args()
    rep = process(a.input, a.outdir, a.policy, a.loop, a.freeze_legs,
                  a.height_thr, a.speed_thr, a.blend, not a.no_strip_yaw,
                  no_skate_fix=a.no_skate_fix)
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
