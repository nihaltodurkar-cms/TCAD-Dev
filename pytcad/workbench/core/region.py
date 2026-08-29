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

    def validate(self):
        for axis, lo, hi in (("x", self.x_min, self.x_max),
                             ("y", self.y_min, self.y_max)):
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
