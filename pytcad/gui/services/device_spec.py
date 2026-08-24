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
import math

# A sweep is serialized point-by-point into the job JSON on the UI
# thread; beyond this it is a hang/OOM, not a simulation. (Final review
# finding M-4.)
MAX_SWEEP_POINTS = 100_000


@dataclass
class SweepSpec:
    """A single-contact voltage sweep.

    v0.4 semantics: the named contact (or gate -- gates are biased by
    name too) is ramped from `start` to `stop` in `step`; every OTHER
    contact holds its DeviceSpec.bias voltage (or its ContactSpec.V
    default where bias does not mention it).  The solver reuses one warm-
    started device across points, mirroring pytcad's own iv_sweep /
    id_vg_sweep pattern.

    This lives on the JSON boundary: plain dataclass, no Qt, no numpy.
    """
    contact: str
    start: float
    stop: float
    step: float

    def voltages(self):
        """Inclusive ramp start -> stop.  The endpoint survives IEEE
        rounding (0.3/0.1 == 2.999...e0 must still yield 4 points)."""
        k = (self.stop - self.start) / self.step
        n = int(round(k)) + 1 if abs(k - round(k)) < 1e-9 else int(math.floor(k)) + 1
        return [self.start + i * self.step for i in range(n)]

    def n_points(self):
        return len(self.voltages())

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        """Structural parse with load-time errors -- used by project
        persistence, where a corrupt sweep must fail with an actionable
        message rather than surfacing later as a failed solver job."""
        if not isinstance(d, dict):
            raise ValueError(
                f"sweep configuration must be an object, got {type(d).__name__}")
        try:
            spec = cls(contact=d["contact"], start=float(d["start"]),
                       stop=float(d["stop"]), step=float(d["step"]))
        except KeyError as exc:
            raise ValueError(f"sweep configuration is missing field {exc}") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid sweep configuration: {exc}") from None
        spec.validate_values()
        return spec

    def validate_values(self):
        """Everything checkable WITHOUT knowing the contact registry."""
        for label, v in (("start", self.start), ("stop", self.stop),
                         ("step", self.step)):
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"sweep {label} must be finite, got {v!r}")
        if self.step == 0:
            raise ValueError("sweep step must be nonzero")
        if self.start == self.stop:
            raise ValueError(
                "a sweep needs at least 2 points; start == stop "
                f"({self.start}) gives 1")
        if (self.stop - self.start) * self.step < 0:
            raise ValueError(
                f"sweep step {self.step} does not move from start "
                f"{self.start} toward stop {self.stop}")
        n = abs((self.stop - self.start) / self.step) + 1
        if n > MAX_SWEEP_POINTS:
            raise ValueError(
                f"sweep would need ~{int(n):g} points; the limit is "
                f"{MAX_SWEEP_POINTS} (increase the step)")

    def validate(self, contact_names):
        """Raise ValueError with an actionable message on any spec that
        cannot be executed.  `contact_names` is the list of names the
        enclosing DeviceSpec actually registers."""
        names = list(contact_names)
        if not isinstance(self.contact, str) or not self.contact \
                or self.contact not in names:
            raise ValueError(
                f"sweep contact '{self.contact}' is not a registered "
                f"contact (have: {', '.join(names) or 'none'})")
        self.validate_values()


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
    sweep: SweepSpec = None            # v0.4: optional single-contact voltage ramp

    # -- serialization ------------------------------------------------
    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        sweep = d.get("sweep")
        return cls(
            mesh=MeshSpec(**d["mesh"]),
            doping=DopingSpec(**d["doping"]),
            material=d.get("material", "SILICON"),
            T=d.get("T", 300.0),
            models=d.get("models") or _default_models(),
            contacts=[ContactSpec(**c) for c in d.get("contacts", [])],
            bias=d.get("bias"),
            # Strict parse path (final review M-5): same float coercion
            # and load-time validation project_store uses, not a bare
            # SweepSpec(**dict).
            sweep=SweepSpec.from_dict(sweep) if sweep else None,
        )

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def from_json(cls, path):
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
