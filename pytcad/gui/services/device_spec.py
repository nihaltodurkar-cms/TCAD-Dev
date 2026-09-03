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
        # Mirror voltages()'s own rounding here rather than either (a) a
        # fresh raw division, which can land a hair above an integer
        # purely from float imprecision (e.g. 99999.0000000001 > 100000)
        # and falsely reject a sweep voltages() would happily produce at
        # exactly MAX_SWEEP_POINTS, or (b) calling voltages()/n_points()
        # directly, which would materialize the full point list -- with
        # a pathological (huge range, tiny step) input that's exactly
        # the unbounded-memory cost this check exists to reject BEFORE
        # incurring it.
        k = (self.stop - self.start) / self.step
        n = (int(round(k)) + 1 if abs(k - round(k)) < 1e-9
             else int(math.floor(k)) + 1)
        if n > MAX_SWEEP_POINTS:
            raise ValueError(
                f"sweep would need {n} points; the limit is "
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


WAVEFORM_KINDS = ("step", "ramp", "pulse", "constant")


@dataclass
class WaveformSpec:
    """A per-contact bias-vs-time waveform (M17 phase 3 wire format).

    Field meaning depends on `kind` (mirrors pytcad.transient's
    StepWaveform/RampWaveform/PulseWaveform constructors exactly, just
    JSON-flattened onto one shape instead of one class per kind):
      "step":     v0 until t0, then v1 (t1 unused)
      "ramp":     linear v0 -> v1 over [t0, t1]
      "pulse":    v0 outside [t0, t0+t1), v1 inside it (t1 = width)
      "constant": always v0 (v1/t0/t1 unused)
    """
    kind: str
    v0: float = 0.0
    v1: float = 0.0
    t0: float = 0.0
    t1: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError(
                f"waveform configuration must be an object, got {type(d).__name__}")
        try:
            spec = cls(kind=d["kind"], v0=float(d.get("v0", 0.0)),
                       v1=float(d.get("v1", 0.0)), t0=float(d.get("t0", 0.0)),
                       t1=float(d.get("t1", 0.0)))
        except KeyError as exc:
            raise ValueError(f"waveform configuration is missing field {exc}") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid waveform configuration: {exc}") from None
        spec.validate()
        return spec

    def validate(self):
        if self.kind not in WAVEFORM_KINDS:
            raise ValueError(
                f"waveform kind '{self.kind}' must be one of {WAVEFORM_KINDS}")
        for label, v in (("v0", self.v0), ("v1", self.v1),
                         ("t0", self.t0), ("t1", self.t1)):
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"waveform {label} must be finite, got {v!r}")
        if self.kind == "ramp" and self.t1 <= self.t0:
            raise ValueError(
                f"ramp waveform needs t1 ({self.t1}) > t0 ({self.t0})")
        if self.kind == "pulse" and self.t1 <= 0.0:
            raise ValueError(f"pulse waveform needs width t1 > 0, got {self.t1}")


@dataclass
class TransientSpec:
    """A single-contact time-domain run (M17 phase 3).

    Mirrors SweepSpec's role: `contact` is ramped in TIME (not voltage)
    following `waveform`; every OTHER contact holds its DeviceSpec.bias
    voltage, same convention pytcad.transient.solve_transient itself
    already defaults to for any contact not mentioned in its own
    `waveforms` dict.
    """
    contact: str
    waveform: WaveformSpec
    t_end: float
    dt0: float
    theta: float = 1.0

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError(
                f"transient configuration must be an object, got {type(d).__name__}")
        try:
            spec = cls(contact=d["contact"],
                       waveform=WaveformSpec.from_dict(d["waveform"]),
                       t_end=float(d["t_end"]), dt0=float(d["dt0"]),
                       theta=float(d.get("theta", 1.0)))
        except KeyError as exc:
            raise ValueError(f"transient configuration is missing field {exc}") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid transient configuration: {exc}") from None
        spec.validate_values()
        return spec

    def validate_values(self):
        self.waveform.validate()
        for label, v in (("t_end", self.t_end), ("dt0", self.dt0),
                         ("theta", self.theta)):
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"transient {label} must be finite, got {v!r}")
        if self.t_end <= 0.0:
            raise ValueError(f"transient t_end must be > 0, got {self.t_end}")
        if self.dt0 <= 0.0:
            raise ValueError(f"transient dt0 must be > 0, got {self.dt0}")
        if not (0.0 <= self.theta <= 1.0):
            raise ValueError(f"transient theta must be in [0, 1], got {self.theta}")

    def validate(self, contact_names):
        """Raise ValueError with an actionable message on any spec that
        cannot be executed.  `contact_names` is the list of names the
        enclosing DeviceSpec actually registers."""
        names = list(contact_names)
        if not isinstance(self.contact, str) or not self.contact \
                or self.contact not in names:
            raise ValueError(
                f"transient contact '{self.contact}' is not a registered "
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


def _validate_region_materials(entries):
    """Structural validation of the region_materials wire field:
    every entry carries a non-empty string material and a box of 2 or
    4 finite coordinates.  Registry lookup happens at the domain
    boundary; here we only guarantee lossless JSON round-trips."""
    if not isinstance(entries, list):
        raise ValueError("region_materials must be a list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) \
                or not isinstance(entry.get("material"), str) \
                or not entry["material"]:
            raise ValueError(
                f"region_materials[{i}] needs a 'material' string")
        box = entry.get("box")
        if not isinstance(box, (list, tuple)) or len(box) not in (2, 4, 6) \
                or not all(isinstance(v, (int, float)) for v in box):
            raise ValueError(
                f"region_materials[{i}].box must be [x0,x1], "
                "[x0,x1,y0,y1] or [x0,x1,y0,y1,z0,z1] in cm")


def _default_models():
    # M13: fd / incomplete_ion join the wire-format defaults (OFF),
    # keeping the invariant that this dict equals
    # ModelCatalog.default_config() and covers every Models dataclass
    # flag the solver exposes through the catalog.
    return {"doping_mobility": True, "field_mobility": False,
            "srh": True, "auger": True, "bgn": True,
            "fd": False, "incomplete_ion": False,
            "impact": False, "btbt": False,
            "surface_mobility": False, "dg": False}


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
    # M17 phase 3: optional single-contact time-domain waveform run.
    # Mutually exclusive with `sweep` -- AppController.run() enforces
    # this before a job is ever started; _solve_all checks `transient`
    # before `sweep` so a spec that somehow carries both still resolves
    # deterministically rather than silently picking one.
    transient: TransientSpec = None
    # M11-S2: optional per-region material overrides (heterostructure
    # wire format).  Each entry: {"material": <library key>, "box":
    # [x0, x1] (1D) | [x0, x1, y0, y1] (2D)} in cm, mesh-aligned.
    # None/absent = uniform device material everywhere.  KNOWN non-
    # silicon materials are carried LOSSLESSLY; both solver backends
    # refuse to solve them until the M11-S3 heterojunction core exists.
    region_materials: list = None
    # v0.6 Phase 2c: which SolverBackend id (workbench/solvers/base.py)
    # runs this job.  Additive, like every other DeviceSpec field: an
    # old job file simply lacks the key and defaults to "pytcad" here
    # too, so nothing about pre-2c behavior changes.
    backend: str = "pytcad"

    # -- serialization ------------------------------------------------
    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        sweep = d.get("sweep")
        transient = d.get("transient")
        rm = d.get("region_materials")
        if rm is not None:
            _validate_region_materials(rm)
        return cls(
            mesh=MeshSpec(**d["mesh"]),
            doping=DopingSpec(**d["doping"]),
            material=d.get("material", "SILICON"),
            region_materials=rm,
            T=d.get("T", 300.0),
            models=d.get("models") or _default_models(),
            contacts=[ContactSpec(**c) for c in d.get("contacts", [])],
            bias=d.get("bias"),
            # Strict parse path (final review M-5): same float coercion
            # and load-time validation project_store uses, not a bare
            # SweepSpec(**dict).
            sweep=SweepSpec.from_dict(sweep) if sweep else None,
            transient=TransientSpec.from_dict(transient) if transient else None,
            backend=d.get("backend", "pytcad"),
        )

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def from_json(cls, path):
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
