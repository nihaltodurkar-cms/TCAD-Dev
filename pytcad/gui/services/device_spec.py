"""The GUI/backend boundary.

These dataclasses are the ONLY thing that crosses from the GUI process
into the solver subprocess.  They are plain Python + JSON: no Qt import,
no pytcad import.  That is deliberate -- it keeps the boundary usable
from a notebook or a shell script, and keeps the GUI replaceable (see
design spec section 20).

The same DeviceSpec is also the content of a saved project's device file
(design spec section 8), so any field added here must stay
JSON-serializable.
"""
from dataclasses import dataclass, field, asdict
import json


@dataclass
class MeshSpec:
    """Geometry ONLY -- axis node positions [cm] and nothing else.

    No doping, no contacts, no material: those live on DeviceSpec.  This
    mirrors pytcad's own Mesh/Device split and must stay true as the GUI
    grows, so that mesh editing never accidentally becomes physics
    editing.
    """
    dimensionality: int
    axes: dict

    def shape(self):
        """Array shape for fields on this mesh, in pytcad's node order:
        (Nx,) in 1D, (Ny, Nx) in 2D, (Nz, Ny, Nx) in 3D."""
        if self.dimensionality == 1:
            return (len(self.axes["x"]),)
        if self.dimensionality == 2:
            return (len(self.axes["y"]), len(self.axes["x"]))
        if self.dimensionality == 3:
            return (len(self.axes["z"]), len(self.axes["y"]), len(self.axes["x"]))
        raise ValueError(f"dimensionality must be 1, 2 or 3, got {self.dimensionality}")


@dataclass
class DopingSpec:
    """Net doping N_D - N_A [cm^-3] as a nested list matching
    MeshSpec.shape().

    kind is "array" in v0.1 -- the only supported form.  It exists so a
    later version can add e.g. "regions" (a list of analytic region
    definitions) without changing the surrounding structure.
    """
    kind: str
    values: list
    ntotal: list = None      # total ionised impurity conc.; None -> |values|


@dataclass
class ContactSpec:
    """One terminal.  nodes holds the grid indices it covers: {"i": [...]}
    in 1D, plus "j" in 2D, plus "k" in 3D.

    tox_cm/Vfb/normal_axis apply to kind == "gate" only.  normal_axis is
    3D-only and ignored below that.
    """
    name: str
    kind: str                 # "ohmic" | "gate"
    nodes: dict
    V: float = 0.0
    tox_cm: float = None
    Vfb: float = None
    normal_axis: str = "z"


def _default_models():
    return {"doping_mobility": True, "field_mobility": False,
            "srh": True, "auger": True, "bgn": True}


@dataclass
class DeviceSpec:
    mesh: MeshSpec
    doping: DopingSpec
    material: str = "SILICON"          # v0.1: the only recognized value
    T: float = 300.0
    models: dict = field(default_factory=_default_models)
    contacts: list = field(default_factory=list)
    bias: dict = None                  # {contact_name: V}; None = equilibrium only

    # -- serialization ------------------------------------------------
    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(
            mesh=MeshSpec(**d["mesh"]),
            doping=DopingSpec(**d["doping"]),
            material=d.get("material", "SILICON"),
            T=d.get("T", 300.0),
            models=d.get("models") or _default_models(),
            contacts=[ContactSpec(**c) for c in d.get("contacts", [])],
            bias=d.get("bias"),
        )

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def from_json(cls, path):
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
