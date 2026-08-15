"""Genera un BVH sintetico de caminata (con foot skate a proposito) para probar el pipeline.

  python make_test_bvh.py test_walk.bvh                     -> caminata sana, ~4.5 ciclos
  python make_test_bvh.py sick.bvh --freeze-after 1.5       -> un paso y congelado

`--freeze-after` reproduce el fallo real de los `loco_*`: las piernas se quedan
en la pose del instante indicado mientras el root SIGUE avanzando. Es el caso
que las metricas globales no ven (hay velocidad, luego "se mueve") y que solo
se caza midiendo relativo al root.
"""
import argparse
import numpy as np

FPS = 30
DUR = 5.0
T = int(FPS * DUR)
SPEED = 110.0   # cm/s hacia +Z  (mal calibrado a proposito -> genera skate)

HIER = """HIERARCHY
ROOT Hips
{
  OFFSET 0.000000 0.000000 0.000000
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT LeftUpLeg
  {
    OFFSET 9.000000 -5.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT LeftLeg
    {
      OFFSET 0.000000 -42.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT LeftFoot
      {
        OFFSET 0.000000 -41.000000 0.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT LeftToeBase
        {
          OFFSET 0.000000 -8.000000 12.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.000000 0.000000 5.000000
          }
        }
      }
    }
  }
  JOINT RightUpLeg
  {
    OFFSET -9.000000 -5.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT RightLeg
    {
      OFFSET 0.000000 -42.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT RightFoot
      {
        OFFSET 0.000000 -41.000000 0.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightToeBase
        {
          OFFSET 0.000000 -8.000000 12.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.000000 0.000000 5.000000
          }
        }
      }
    }
  }
  JOINT Spine
  {
    OFFSET 0.000000 10.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT Head
    {
      OFFSET 0.000000 45.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0.000000 12.000000 0.000000
      }
    }
  }
}
MOTION
"""

def main(out="test_walk.bvh", freeze_after=None, stop_root=False):
    t = np.arange(T) / FPS
    period = 1.1
    ph = 2 * np.pi * t / period
    # A partir de aqui la pose se congela: el indice de fase deja de avanzar.
    hold = int(freeze_after * FPS) if freeze_after else None
    rows = []
    for i in range(T):
        i_pose = i if hold is None else min(i, hold)
        hip_y = 92.0 + 1.6 * np.sin(2 * ph[i_pose])
        hip_z = SPEED * (t[i_pose] if (hold is not None and stop_root) else t[i])
        row = [0.0, hip_y, hip_z, 0.0, 0.0, 0.0]
        for sign, off in ((1, 0.0), (-1, np.pi)):
            a = ph[i_pose] + off
            thigh = 24.0 * np.sin(a)
            knee = -max(0.0, 38.0 * np.sin(a + 1.1))
            ankle = -0.5 * thigh - 0.4 * knee
            row += [0.0, -thigh, 0.0]     # UpLeg  (Zrot, Xrot, Yrot)
            row += [0.0, -knee, 0.0]      # Leg
            row += [0.0, ankle, 0.0]      # Foot
            row += [0.0, 0.0, 0.0]        # ToeBase
        row += [0.0, 2.0 * np.sin(ph[i_pose]), 0.0]   # Spine
        row += [0.0, 0.0, 3.0 * np.sin(ph[i_pose])]   # Head
        rows.append(row)

    with open(out, "w") as f:
        f.write(HIER)
        f.write(f"Frames: {T}\n")
        f.write(f"Frame Time: {1.0/FPS:.8f}\n")
        for r in rows:
            f.write(" ".join(f"{v:.6f}" for v in r) + "\n")
    print("escrito", out, T, "frames")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="test_walk.bvh")
    ap.add_argument("--freeze-after", type=float, default=None,
                    help="segundos tras los cuales la pose se congela")
    ap.add_argument("--stop-root", action="store_true",
                    help="congela tambien el avance del root")
    a = ap.parse_args()
    main(a.out, a.freeze_after, a.stop_root)
