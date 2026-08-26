"""The GUI-only, mutable structure/mesh model that sits ABOVE the
existing, unmodified DeviceSpec/MeshSpec boundary.

StructureModel/MeshModel never construct Device1D/Device2D/Device3D --
to_device_spec()/to_mesh_spec() do pure Python array compositing and
hand the result to the exact same DeviceSpec/MeshSpec solver_runner.py
already consumes. See the design spec section 3 for why "regions" means
named doping sub-areas of one silicon domain, never separate meshed
materials: Device2D takes exactly one mesh and one material for the
whole domain, and SILICON is the only Semiconductor instance pytcad
defines.
"""
from dataclasses import dataclass, field, asdict

import numpy as np

from .device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec


@dataclass
class RegionSpec:
    id: str
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    net_doping_cm3: float          # signed: + donor/n-type, - acceptor/p-type
    # M11-S5: MaterialLibrary key carried per region (canonical
    # uppercase default so authored paths and templates compare equal).
    # Emitted as DeviceSpec.region_materials for every non-silicon
    # region by to_device_spec().  Resolution is case-insensitive.
    material: str = "SILICON"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class BoundarySpec:
    edge: str                      # "left" | "right" | "top" | "bottom"
    range_lo: float = None
    range_hi: float = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class ContactModel:
    id: str
    name: str
    boundary: BoundarySpec
    V: float = 0.0

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["boundary"] = BoundarySpec.from_dict(d["boundary"])
        return cls(**d)


@dataclass
class GateModel:
    id: str
    name: str
    boundary: BoundarySpec
    tox_cm: float
    gate_type: str = "n+poly"      # "n+poly" | "p+poly" | "Al" | a float work function [eV]
    vfb_mode: str = "computed"     # "computed" | "manual"
    vfb_manual: float = None       # required when vfb_mode == "manual"
    V: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["boundary"] = BoundarySpec.from_dict(d["boundary"])
        return cls(**d)


@dataclass
class MeshModel:
    nx: int = 40
    ny: int = 24
    grading: str = "uniform"       # "uniform" | "graded"
    # graded mode reuses mesh.py's graded_mesh() exactly as-is:
    x_focus: list = None
    y_focus: list = None
    h_min: float = None
    h_max: float = None
    ratio: float = 1.15

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def to_mesh_spec(self, width_cm, height_cm):
        if self.grading == "uniform":
            x = np.linspace(0.0, width_cm, self.nx)
            y = np.linspace(0.0, height_cm, self.ny)
        elif self.grading == "graded":
            from pytcad.mesh import graded_mesh
            x_focus = self.x_focus if self.x_focus else [width_cm / 2.0]
            y_focus = self.y_focus if self.y_focus else [0.0]
            x = graded_mesh(width_cm, x_focus, self.h_min, self.h_max, self.ratio)
            y = graded_mesh(height_cm, y_focus, self.h_min, self.h_max, self.ratio)
        else:
            raise ValueError(f"unknown grading '{self.grading}'")
        return MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()})


@dataclass
class ValidationError:
    message: str
    object_id: str = None

    def to_dict(self):
        return asdict(self)


@dataclass
class StructureModel:
    width_cm: float
    height_cm: float
    material: str = "Silicon"      # read-only in the UI; the only value in v0.2
    regions: list = field(default_factory=list)
    contacts: list = field(default_factory=list)
    gates: list = field(default_factory=list)

    # -- list helpers (no undo awareness; see undo_stack.py) -----------
    def add_region(self, region):
        self.regions.append(region)

    def remove_region(self, region_id):
        self.regions = [r for r in self.regions if r.id != region_id]

    def find_region(self, region_id):
        return next((r for r in self.regions if r.id == region_id), None)

    def move_region(self, region_id, offset):
        """Shift a region by `offset` positions in compositing order
        (negative = earlier/lower priority, positive = later/higher
        priority -- see the module docstring on rasterize_doping: later
        overwrites earlier). Clamps at the list ends; no-ops if the
        region id is unknown."""
        idx = next((k for k, r in enumerate(self.regions) if r.id == region_id), None)
        if idx is None:
            return
        new_idx = max(0, min(len(self.regions) - 1, idx + offset))
        if new_idx == idx:
            return
        region = self.regions.pop(idx)
        self.regions.insert(new_idx, region)

    def add_contact(self, contact):
        self.contacts.append(contact)

    def remove_contact(self, contact_id):
        self.contacts = [c for c in self.contacts if c.id != contact_id]

    def find_contact(self, contact_id):
        return next((c for c in self.contacts if c.id == contact_id), None)

    def add_gate(self, gate):
        self.gates.append(gate)

    def remove_gate(self, gate_id):
        self.gates = [g for g in self.gates if g.id != gate_id]

    def find_gate(self, gate_id):
        return next((g for g in self.gates if g.id == gate_id), None)

    # -- serialization --------------------------------------------------
    def to_dict(self):
        return {
            "width_cm": self.width_cm, "height_cm": self.height_cm,
            "material": self.material,
            "regions": [r.to_dict() for r in self.regions],
            "contacts": [c.to_dict() for c in self.contacts],
            "gates": [g.to_dict() for g in self.gates],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            width_cm=d["width_cm"], height_cm=d["height_cm"],
            material=d.get("material", "Silicon"),
            regions=[RegionSpec.from_dict(r) for r in d.get("regions", [])],
            contacts=[ContactModel.from_dict(c) for c in d.get("contacts", [])],
            gates=[GateModel.from_dict(g) for g in d.get("gates", [])],
        )

    # -- validation -------------------------------------------------
    def validate(self, mesh_model):
        from .gate_vfb import get_gate_substrate_doping, NonUniformGateSubstrateDopingError
        errors = []
        if self.width_cm <= 0:
            errors.append(ValidationError("Domain width must be positive"))
        if self.height_cm <= 0:
            errors.append(ValidationError("Domain height must be positive"))
        if mesh_model.nx < 2:
            errors.append(ValidationError("Mesh Nx must be at least 2"))
        if mesh_model.ny < 2:
            errors.append(ValidationError("Mesh Ny must be at least 2"))

        seen = set()
        for r in self.regions:
            if r.id in seen:
                errors.append(ValidationError(f"Duplicate region id '{r.id}'", r.id))
            seen.add(r.id)
            if r.x_min >= r.x_max:
                errors.append(ValidationError(
                    f"Region '{r.name}' has zero or negative width", r.id))
            if r.y_min >= r.y_max:
                errors.append(ValidationError(
                    f"Region '{r.name}' has zero or negative height", r.id))
            if (r.x_min < 0 or r.x_max > self.width_cm
                    or r.y_min < 0 or r.y_max > self.height_cm):
                errors.append(ValidationError(
                    f"Region '{r.name}' extends outside the domain", r.id))

        seen = set()
        for c in self.contacts:
            if c.id in seen:
                errors.append(ValidationError(f"Duplicate contact id '{c.id}'", c.id))
            seen.add(c.id)
            if (c.boundary.range_lo is not None and c.boundary.range_hi is not None
                    and c.boundary.range_lo >= c.boundary.range_hi):
                errors.append(ValidationError(
                    f"Contact '{c.name}' has an empty boundary range", c.id))

        seen = set()
        mesh_spec = None
        for g in self.gates:
            if g.id in seen:
                errors.append(ValidationError(f"Duplicate gate id '{g.id}'", g.id))
            seen.add(g.id)
            if g.tox_cm is None or g.tox_cm <= 0:
                errors.append(ValidationError(
                    f"Gate '{g.name}' must have tox_cm > 0", g.id))
            if (g.boundary.range_lo is not None and g.boundary.range_hi is not None
                    and g.boundary.range_lo >= g.boundary.range_hi):
                errors.append(ValidationError(
                    f"Gate '{g.name}' has an empty boundary range", g.id))
            if g.vfb_mode == "manual" and g.vfb_manual is None:
                errors.append(ValidationError(
                    f"Gate '{g.name}' is in manual Vfb mode but has no Vfb value", g.id))
            elif g.vfb_mode == "computed" and self.width_cm > 0 and self.height_cm > 0 \
                    and mesh_model.nx >= 2 and mesh_model.ny >= 2:
                if mesh_spec is None:
                    mesh_spec = mesh_model.to_mesh_spec(self.width_cm, self.height_cm)
                try:
                    get_gate_substrate_doping(g, self, mesh_spec)
                except (NonUniformGateSubstrateDopingError, ValueError) as exc:
                    errors.append(ValidationError(str(exc), g.id))
        return errors

    # -- conversion to the v0.1 solver boundary -----------------
    def to_device_spec(self, mesh_model, T=300.0):
        from .gate_vfb import resolve_gate_vfb
        mesh_spec = mesh_model.to_mesh_spec(self.width_cm, self.height_cm)
        doping = rasterize_doping(self, mesh_spec)

        contacts = []
        for c in self.contacts:
            i, j = resolve_boundary_indices(c.boundary, mesh_spec)
            contacts.append(ContactSpec(name=c.name, kind="ohmic",
                                        nodes={"i": i.tolist(), "j": j.tolist()}, V=c.V))
        for g in self.gates:
            i, j = resolve_boundary_indices(g.boundary, mesh_spec)
            vfb = resolve_gate_vfb(g, self, mesh_spec, T)
            contacts.append(ContactSpec(name=g.name, kind="gate",
                                        nodes={"i": i.tolist(), "j": j.tolist()},
                                        V=g.V, tox_cm=g.tox_cm, Vfb=vfb))

        # bias is a SEPARATE field from each ContactSpec.V (mirroring
        # v0.1's _spec_from_device2d/mosfet_example_spec convention) --
        # solver_runner only solves at bias, and therefore only reports
        # terminal currents, when spec.bias is not None. Every contact
        # and gate's currently-configured V becomes its bias point, so
        # Run always solves at whatever voltages are set in the UI.
        bias = {c.name: c.V for c in self.contacts}
        bias.update({g.name: g.V for g in self.gates})

        # M11-S5: per-region materials ride the wire format -- one box
        # per non-silicon region, in declaration order (later entries
        # win on overlap, mirroring rasterize_doping).  Silicon regions
        # stay implicit (the spec-level material covers them), keeping
        # all-silicon specs byte-identical to their legacy form.
        rm = [{"material": r.material,
               "box": [max(r.x_min, 0.0), min(r.x_max, self.width_cm),
                       max(r.y_min, 0.0), min(r.y_max, self.height_cm)]}
              for r in self.regions
              if r.material.upper() not in ("SILICON", "SI")]
        return DeviceSpec(
            mesh=mesh_spec,
            doping=DopingSpec(kind="array", values=doping.tolist()),
            material="SILICON", T=T,
            contacts=contacts,
            bias=bias,
            region_materials=(rm if rm else None),
        )


def resolve_boundary_indices(boundary, mesh_spec):
    """Node (i, j) index arrays for a 2D boundary edge, optionally
    restricted to a coordinate sub-range along that edge.  Mirrors how
    build_mosfet() already computes i_source = np.where(mesh.x <= Lsd)[0]
    -- generalized to all four edges, resolved here rather than inside
    solver_runner so contacts/gates never carry raw indices in the GUI.

    Edge indices are NEVER assumed to be 0 or N-1 by position -- they are
    derived from np.argmin/argmax of the actual coordinate array. In
    practice pytcad's mesh.py (uniform_mesh/graded_mesh) always emits
    ascending arrays from 0 to L, so argmin is index 0 today -- but
    deriving it explicitly means a reversed or non-monotonic axis fails
    loudly (via the ambiguous-argmin/argmax picking *a* extremum node,
    which the dedicated test below would catch producing the wrong
    physical edge) rather than silently mislabeling top/bottom or
    left/right. 'top' is defined as the MIN-y edge (y=0 is the silicon
    surface where gates sit, per build_mosfet's j=np.zeros_like(i_gate));
    'bottom' is the MAX-y edge (the substrate, furthest from the
    surface)."""
    x = np.asarray(mesh_spec.axes["x"], dtype=float)
    y = np.asarray(mesh_spec.axes["y"], dtype=float)
    Nx, Ny = x.size, y.size

    if boundary.edge == "left":
        j = np.arange(Ny); i = np.full_like(j, int(np.argmin(x))); coord = y
    elif boundary.edge == "right":
        j = np.arange(Ny); i = np.full_like(j, int(np.argmax(x))); coord = y
    elif boundary.edge == "top":
        i = np.arange(Nx); j = np.full_like(i, int(np.argmin(y))); coord = x
    elif boundary.edge == "bottom":
        i = np.arange(Nx); j = np.full_like(i, int(np.argmax(y))); coord = x
    else:
        raise ValueError(f"unknown edge '{boundary.edge}'")

    if boundary.range_lo is not None or boundary.range_hi is not None:
        lo = boundary.range_lo if boundary.range_lo is not None else coord.min()
        hi = boundary.range_hi if boundary.range_hi is not None else coord.max()
        mask = (coord >= lo) & (coord <= hi)
        i, j = i[mask], j[mask]
    return i, j


def rasterize_doping(structure, mesh_spec):
    """Net doping [cm^-3], shape (Ny, Nx).  Regions apply in list order,
    later overwrites earlier, over a 0 cm^-3 background -- the same rule
    mosfet_doping() uses implicitly (background then source/drain
    painted over it), made explicit here."""
    x = np.asarray(mesh_spec.axes["x"], dtype=float)
    y = np.asarray(mesh_spec.axes["y"], dtype=float)
    doping = np.zeros((y.size, x.size))
    for region in structure.regions:
        xi = (x >= region.x_min) & (x <= region.x_max)
        yi = (y >= region.y_min) & (y <= region.y_max)
        doping[np.outer(yi, xi)] = region.net_doping_cm3
    return doping
