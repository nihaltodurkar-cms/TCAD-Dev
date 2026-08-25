"""DomainDevice: the workbench's domain representation of a device.

Pure data -- no Qt, and no solver imports.  DeviceSpec REMAINS the
wire/project format (gui/services/device_spec.py); DomainDevice is its
derived domain view plus the region-authored shape the future Device
Builder will edit.  Two legal shapes:

  IMPORTED  (from a v0.1 spec): explicit mesh axes + array doping +
            node-index contacts, exactly as the solver boundary defines
            them today.
  AUTHORED  (region-based): named rectangular regions over a width x
            height domain with a mesh hint (nx/ny/grading); contacts
            described by domain edges.  Conversion to a spec DELEGATES
            to the existing StructureModel.to_device_spec() builder --
            never a reimplementation.

Physics configuration lives here as `models`, validated against the
ModelCatalog; the catalog's default_config() is byte-identical to the
wire format's defaults.
"""
import math
from dataclasses import dataclass, field

from .catalog import ModelCatalog
from .materials import LIBRARY
from .region import Region


@dataclass
class Boundary:
    """A device edge or edge segment: "left"|"right"|"top"|"bottom",
    optionally restricted to [range_lo, range_hi] along that edge [cm]."""
    edge: str
    range_lo: float = None
    range_hi: float = None


@dataclass
class ContactDef:
    id: str
    name: str
    kind: str                          # "ohmic" | "gate"
    V: float = 0.0
    # AUTHORED devices describe contacts geometrically:
    boundary: Boundary = None
    # IMPORTED devices carry the resolved node map instead:
    nodes: dict = None                 # {"i": [...], "j": [...], ...}
    # gate-only physics/metal description:
    tox_cm: float = None               # oxide thickness [cm]
    gate_type: str = "n+poly"          # "n+poly"|"p+poly"|"Al"| work fn [eV]
    vfb_mode: str = "computed"         # "computed" | "manual"
    vfb_manual: float = None           # flatband voltage when mode=="manual"

    _EDGES = ("left", "right", "top", "bottom")

    def validate(self):
        if self.kind not in ("ohmic", "gate"):
            raise ValueError(
                f"contact '{self.id}': unknown kind '{self.kind}'")
        if self.boundary is None and self.nodes is None:
            raise ValueError(
                f"contact '{self.id}': needs either a boundary (authored) "
                "or a node map (imported)")
        if self.boundary is not None and \
                self.boundary.edge not in self._EDGES:
            raise ValueError(
                f"contact '{self.id}': unknown boundary edge "
                f"'{self.boundary.edge}'")
        if self.kind == "gate":
            if self.vfb_mode == "manual" and self.vfb_manual is None:
                raise ValueError(
                    f"gate '{self.id}': vfb_mode 'manual' needs vfb_manual")
            if self.boundary is not None and \
                    not (self.tox_cm is not None and self.tox_cm > 0):
                raise ValueError(
                    f"gate '{self.id}': tox_cm must be positive")


@dataclass
class DomainDevice:
    id: str
    name: str
    dimensionality: int = 2
    T: float = 300.0                   # lattice temperature [K]
    material: str = "SILICON"          # domain-wide material (library key;
                                       # imported structures may carry their
                                       # own legacy label -- single-material
                                       # devices are a documented M1 limit)
    models: dict = field(default_factory=ModelCatalog.default_config)

    # -- authored geometry ---------------------------------------------
    width_cm: float = None
    height_cm: float = None
    mesh_nx: int = None
    mesh_ny: int = None
    mesh_grading: str = "uniform"      # "uniform" | "graded"
    mesh_grading_params: dict = field(default_factory=dict)
    regions: list = field(default_factory=list)

    # -- imported geometry (v0.1 spec shape) ----------------------------
    axes: dict = None                  # {"x": [...cm], ...}
    explicit_doping: list = None       # nested list, signed net doping
    ntotal: list = None                # total ionised impurity, or None

    contacts: list = field(default_factory=list)
    bias: dict = None                  # {contact_name: V}; None=equilibrium

    def validate(self):
        if self.dimensionality not in (1, 2, 3):
            raise ValueError(
                f"dimensionality must be 1, 2 or 3, got "
                f"{self.dimensionality}")
        if not (math.isfinite(self.T) and self.T > 0):
            raise ValueError(f"T must be finite and positive, got {self.T}")
        # Case-insensitive library membership: legacy labels like
        # StructureModel's 'Silicon' are legal, unknown names are not.
        try:
            LIBRARY.get(self.material)
        except KeyError:
            raise ValueError(
                f"unknown material '{self.material}' (available: "
                f"{', '.join(LIBRARY.names())})") from None
        ModelCatalog.validate(self.models)

        for c in self.contacts:
            c.validate()

        if self.axes is None:
            # AUTHORED shape: regions over an extent with a mesh hint
            if self.dimensionality != 2:
                raise ValueError(
                    "region-authored devices are 2D in this milestone")
            if not (self.width_cm and self.width_cm > 0 and
                    self.height_cm and self.height_cm > 0):
                raise ValueError("region path needs positive width_cm/"
                                 "height_cm")
            if not (isinstance(self.mesh_nx, int) and self.mesh_nx >= 2 and
                    isinstance(self.mesh_ny, int) and self.mesh_ny >= 2):
                raise ValueError(
                    "region path needs integer mesh_nx/mesh_ny >= 2")
            if not self.regions:
                raise ValueError("region path needs at least one region")
            for r in self.regions:
                r.validate()
                # Fail loudly rather than silently solving the wrong
                # material: multi-material regions need a backend that
                # supports heterostructures (none does today).
                if r.material not in LIBRARY.names():
                    raise ValueError(
                        f"region '{r.id}': unknown material "
                        f"'{r.material}' (available: "
                        f"{', '.join(LIBRARY.names())})")
                # M11-S1: heterogeneous KNOWN materials are now legal in
                # the domain layer.  Solvability is enforced downstream:
                # adapters (spec.py) and solver backends still refuse
                # non-silicon jobs until the M11-S3 heterojunction core
                # exists.  Validation stays the registry check only.
        else:
            # IMPORTED shape: explicit axes + array doping
            if not self.axes:
                raise ValueError("imported device needs non-empty axes")
            missing = [a for a in ("x", "y", "z")[:self.dimensionality]
                       if a not in self.axes or len(self.axes[a]) == 0]
            if missing:
                raise ValueError(
                    f"a {self.dimensionality}D device needs non-empty "
                    f"axes {sorted(('x', 'y', 'z')[:self.dimensionality])}; "
                    f"missing/empty: {missing}")
            if self.explicit_doping is None:
                raise ValueError(
                    "an imported (axes-defined) device needs "
                    "explicit_doping")
