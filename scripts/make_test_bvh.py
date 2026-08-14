"""Genera un BVH sintetico de caminata (con foot skate a proposito) para probar el pipeline."""
import numpy as np, sys

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

def main(out="test_walk.bvh"):
    t = np.arange(T) / FPS
    period = 1.1
    ph = 2 * np.pi * t / period
    rows = []
    for i in range(T):
        hip_y = 92.0 + 1.6 * np.sin(2 * ph[i])
        hip_z = SPEED * t[i]
        row = [0.0, hip_y, hip_z, 0.0, 0.0, 0.0]
        for sign, off in ((1, 0.0), (-1, np.pi)):
            a = ph[i] + off
            thigh = 24.0 * np.sin(a)
            knee = -max(0.0, 38.0 * np.sin(a + 1.1))
            ankle = -0.5 * thigh - 0.4 * knee
            row += [0.0, -thigh, 0.0]     # UpLeg  (Zrot, Xrot, Yrot)
            row += [0.0, -knee, 0.0]      # Leg
            row += [0.0, ankle, 0.0]      # Foot
            row += [0.0, 0.0, 0.0]        # ToeBase
        row += [0.0, 2.0 * np.sin(ph[i]), 0.0]   # Spine
        row += [0.0, 0.0, 3.0 * np.sin(ph[i])]   # Head
        rows.append(row)

    with open(out, "w") as f:
        f.write(HIER)
        f.write(f"Frames: {T}\n")
        f.write(f"Frame Time: {1.0/FPS:.8f}\n")
        for r in rows:
            f.write(" ".join(f"{v:.6f}" for v in r) + "\n")
    print("escrito", out, T, "frames")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_walk.bvh")
