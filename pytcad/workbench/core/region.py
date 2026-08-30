"""Region: one named sub-area of a device domain.

A Region is a DOMAIN object -- a rectangle of material with a uniform
net doping -- not a meshed entity.  The solver still sees exactly one
mesh and one material per solved device (pytcad's own constraint); the
workbench composites regions onto that mesh at spec-build time, in
declaration order (later regions overwrite earlier ones where they
overlap).  Per-region materials become real physics only when a
heterostructure-capable backend exists (M7+); today the field is
carried honestly as metadata and validated against the library.
"""
import math
from dataclasses import dataclass


@dataclass
class Region:
    id: str
    name: str
    x_min: float = 0.0          # [cm]
    x_max: float = 0.0
    y_min: float = 0.0
    y_max: float = 0.0
    doping_cm3: float = 0.0     # signed net doping: + donors / - acceptors
    material: str = "SILICON"   # MaterialLibrary key
    # 3D device authoring, phase 1: None (default) = a 2D region,
    # UNCHANGED behavior for every existing caller. Both must be set
    # together to make this a genuine 3D region -- a half-specified z
    # extent is refused in validate() rather than silently treated as
    # 2D or defaulted.
    z_min: float = None
    z_max: float = None

    def is_3d(self):
        return self.z_min is not None and self.z_max is not None

    def validate(self):
        axes = [("x", self.x_min, self.x_max), ("y", self.y_min, self.y_max)]
        if self.z_min is not None or self.z_max is not None:
            if self.z_min is None or self.z_max is None:
                raise ValueError(
                    f"region '{self.id}': z_min and z_max must both be set "
                    "or both left None -- a half-specified z extent is "
                    "ambiguous (2D or 3D?), not defaulted")
            axes.append(("z", self.z_min, self.z_max))
        for axis, lo, hi in axes:
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise ValueError(
                    f"region '{self.id}': {axis} bounds must be finite")
            if lo >= hi:
                raise ValueError(
                    f"region '{self.id}': {axis}_min must be < {axis}_max "
                    f"({lo} >= {hi})")
        if not math.isfinite(self.doping_cm3):
            raise ValueError(
                f"region '{self.id}': doping must be finite")
