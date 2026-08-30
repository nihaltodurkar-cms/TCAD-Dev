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
from pytcad.mosfet import _sd_profile


@dataclass
class RegionSpec:
    id: str
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    net_doping_cm3: float          # signed: + donor/n-type, - acceptor/p-type
    # 3D device authoring, phase 1: None (default) = a 2D region,
    # UNCHANGED behavior for every existing caller. Both must be set
    # together (validated in StructureModel.to_device_spec()) -- a
    # half-specified z extent is refused, not defaulted.
    z_min: float = None
    z_max: float = None
    # M11-S5: MaterialLibrary key carried per region (canonical
    # uppercase default so authored paths and templates compare equal).
    # Emitted as DeviceSpec.region_materials for every non-silicon
    # region by to_device_spec().  Resolution is case-insensitive.
    material: str = "SILICON"

    # Per-region doping PROFILE, beyond uniform (GUI README "Planned"
    # item): "uniform" (default, exactly today's behavior -- the flat
    # net_doping_cm3 fill) or "gaussian_erfc", reusing mosfet_doping()'s
    # own Gaussian-in-depth x erfc-lateral-rolloff shape (pytcad/mosfet.py
    # _sd_profile) as a region option instead of a separate formula.
    # The four profile_* fields are required (and validated, in
    # rasterize_doping) only when doping_profile != "uniform"; net_doping_cm3
    # is ignored in that case (profile_peak_cm3's sign takes over).
    doping_profile: str = "uniform"
    profile_peak_cm3: float = None       # signed peak, like net_doping_cm3
    profile_sigma_y: float = None        # depth straggle [cm], from y_min
    profile_sigma_lat: float = None      # lateral straggle [cm]
    profile_edge_x: float = None         # mask-edge x position [cm]
    profile_high_side: str = "left"      # "left" | "right" -- see _sd_profile

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class BoundarySpec:
    edge: str                      # "left" | "right" | "top" | "bottom",
                                   # plus "front" | "back" (z-normal
                                   # faces, 3D device authoring phase 1)
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
    # 3D device authoring, phase 1: None (default) = a 2D mesh,
    # UNCHANGED behavior. Set nz (and optionally z_focus) to get a 3D
    # MeshSpec from to_mesh_spec() -- see its depth_cm parameter below.
    nz: int = None
    z_focus: list = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def to_mesh_spec(self, width_cm, height_cm, depth_cm=None):
        """depth_cm=None (default) returns the unchanged 2D MeshSpec.
        Passing depth_cm requires self.nz to also be set (both-or-
        neither, same convention RegionSpec's z_min/z_max use) and
        returns a 3D MeshSpec instead."""
        is_3d = depth_cm is not None
        if is_3d and self.nz is None:
            raise ValueError(
                "to_mesh_spec: depth_cm given but MeshModel.nz is None -- "
                "both must be set together for a 3D mesh")
        if not is_3d and self.nz is not None:
            raise ValueError(
                "to_mesh_spec: MeshModel.nz is set but depth_cm is None -- "
                "both must be set together for a 3D mesh")
        if self.grading == "uniform":
            x = np.linspace(0.0, width_cm, self.nx)
            y = np.linspace(0.0, height_cm, self.ny)
            z = np.linspace(0.0, depth_cm, self.nz) if is_3d else None
        elif self.grading == "graded":
            from pytcad.mesh import graded_mesh
            x_focus = self.x_focus if self.x_focus else [width_cm / 2.0]
            y_focus = self.y_focus if self.y_focus else [0.0]
            x = graded_mesh(width_cm, x_focus, self.h_min, self.h_max, self.ratio)
            y = graded_mesh(height_cm, y_focus, self.h_min, self.h_max, self.ratio)
            if is_3d:
                z_focus = self.z_focus if self.z_focus else [0.0]
                z = graded_mesh(depth_cm, z_focus, self.h_min, self.h_max, self.ratio)
            else:
                z = None
        else:
            raise ValueError(f"unknown grading '{self.grading}'")
        if is_3d:
            return MeshSpec(dimensionality=3, axes={
                "x": x.tolist(), "y": y.tolist(), "z": z.tolist()})
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
    # 3D device authoring, phase 1: None (default) = a 2D structure,
    # UNCHANGED behavior. Setting depth_cm makes to_device_spec() build
    # a 3D DeviceSpec instead -- scoped to ohmic contacts + uniform
    # doping only, the SAME scope resistor_3d_example_spec() (the only
    # existing GUI-reachable 3D device) already established: no gates,
    # no gaussian_erfc profile in 3D this phase (both refused loudly in
    # validate()/to_device_spec(), not silently ignored).
    depth_cm: float = None

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
            "depth_cm": self.depth_cm,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            width_cm=d["width_cm"], height_cm=d["height_cm"],
            material=d.get("material", "Silicon"),
            regions=[RegionSpec.from_dict(r) for r in d.get("regions", [])],
            contacts=[ContactModel.from_dict(c) for c in d.get("contacts", [])],
            gates=[GateModel.from_dict(g) for g in d.get("gates", [])],
            depth_cm=d.get("depth_cm"),
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
        is_3d = self.depth_cm is not None
        if is_3d and self.gates:
            # 3D device authoring, phase 1: ohmic contacts only, no
            # gates -- the SAME scope resistor_3d_example_spec() (the
            # only existing GUI-reachable 3D device) already has.
            # Gate flatband-voltage resolution (resolve_gate_vfb) is
            # written against 2D structures; extending it is real work
            # left for a future phase, not guessed here.
            raise ValueError(
                "3D device authoring (depth_cm set) does not support "
                "gates in this phase -- remove all gates or clear "
                "depth_cm for a 2D device")
        mesh_spec = mesh_model.to_mesh_spec(
            self.width_cm, self.height_cm, self.depth_cm if is_3d else None)
        doping = rasterize_doping(self, mesh_spec)

        contacts = []
        for c in self.contacts:
            idx = resolve_boundary_indices(c.boundary, mesh_spec)
            if is_3d:
                i, j, k = idx
                nodes = {"i": i.tolist(), "j": j.tolist(), "k": k.tolist()}
            else:
                i, j = idx
                nodes = {"i": i.tolist(), "j": j.tolist()}
            contacts.append(ContactSpec(name=c.name, kind="ohmic",
                                        nodes=nodes, V=c.V))
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
        # 3D regions emit a 6-coordinate box [x0,x1,y0,y1,z0,z1] --
        # already anticipated by DeviceSpec's own wire-format validator
        # (_validate_region_materials accepts len(box) in (2,4,6)).
        if is_3d:
            rm = [{"material": r.material,
                  "box": [max(r.x_min, 0.0), min(r.x_max, self.width_cm),
                          max(r.y_min, 0.0), min(r.y_max, self.height_cm),
                          max(r.z_min, 0.0), min(r.z_max, self.depth_cm)]}
                 for r in self.regions
                 if r.material.upper() not in ("SILICON", "SI")]
        else:
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
    """Node (i, j) index arrays for a 2D boundary edge, or (i, j, k) for
    a 3D one (3D device authoring, phase 1 -- dispatches on
    mesh_spec.dimensionality), optionally restricted to a coordinate
    sub-range along that edge (2D only -- see the 3D branch's own
    docstring for why range restriction isn't supported there yet).
    Mirrors how build_mosfet() already computes
    i_source = np.where(mesh.x <= Lsd)[0] -- generalized to all edges,
    resolved here rather than inside solver_runner so contacts/gates
    never carry raw indices in the GUI.

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
    surface). 'front'/'back' (3D only) are the MIN-z/MAX-z edges,
    following the same min-first convention."""
    if mesh_spec.dimensionality == 3:
        return _resolve_boundary_indices_3d(boundary, mesh_spec)

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
        raise ValueError(f"unknown edge '{boundary.edge}' for a 2D device")

    if boundary.range_lo is not None or boundary.range_hi is not None:
        lo = boundary.range_lo if boundary.range_lo is not None else coord.min()
        hi = boundary.range_hi if boundary.range_hi is not None else coord.max()
        mask = (coord >= lo) & (coord <= hi)
        i, j = i[mask], j[mask]
    return i, j


def _resolve_boundary_indices_3d(boundary, mesh_spec):
    """The 6-face 3D generalization. Range restriction is NOT supported
    this phase (raised, not silently ignored): a face has TWO free
    lateral axes, and this phase's BoundarySpec (range_lo/range_hi) has
    no way to say which one a range restricts -- a real gap, not an
    oversight, left for phase 2 (GUI wiring) to resolve with a UI
    decision, not guessed here."""
    if boundary.range_lo is not None or boundary.range_hi is not None:
        raise ValueError(
            f"boundary '{boundary.edge}': range restriction on a 3D "
            "contact face is not supported in this phase (a face has "
            "two free lateral axes; there is no way yet to say which "
            "one a range restricts) -- leave range_lo/range_hi as None")
    x = np.asarray(mesh_spec.axes["x"], dtype=float)
    y = np.asarray(mesh_spec.axes["y"], dtype=float)
    z = np.asarray(mesh_spec.axes["z"], dtype=float)
    Nx, Ny, Nz = x.size, y.size, z.size

    if boundary.edge == "left":
        fixed_axis, fixed_idx, free_shape = "i", int(np.argmin(x)), (Ny, Nz)
    elif boundary.edge == "right":
        fixed_axis, fixed_idx, free_shape = "i", int(np.argmax(x)), (Ny, Nz)
    elif boundary.edge == "top":
        fixed_axis, fixed_idx, free_shape = "j", int(np.argmin(y)), (Nx, Nz)
    elif boundary.edge == "bottom":
        fixed_axis, fixed_idx, free_shape = "j", int(np.argmax(y)), (Nx, Nz)
    elif boundary.edge == "front":
        fixed_axis, fixed_idx, free_shape = "k", int(np.argmin(z)), (Nx, Ny)
    elif boundary.edge == "back":
        fixed_axis, fixed_idx, free_shape = "k", int(np.argmax(z)), (Nx, Ny)
    else:
        raise ValueError(f"unknown edge '{boundary.edge}' for a 3D device")

    if fixed_axis == "i":
        jj, kk = np.meshgrid(np.arange(Ny), np.arange(Nz), indexing="ij")
        j, k = jj.ravel(), kk.ravel()
        i = np.full_like(j, fixed_idx)
    elif fixed_axis == "j":
        ii, kk = np.meshgrid(np.arange(Nx), np.arange(Nz), indexing="ij")
        i, k = ii.ravel(), kk.ravel()
        j = np.full_like(i, fixed_idx)
    else:
        ii, jj = np.meshgrid(np.arange(Nx), np.arange(Ny), indexing="ij")
        i, j = ii.ravel(), jj.ravel()
        k = np.full_like(i, fixed_idx)
    return i, j, k


def _validate_profile_region(region):
    """Fail loud, not silent: a non-uniform region missing its shape
    parameters is a configuration error, never a 0/NaN doping value."""
    for name in ("profile_peak_cm3", "profile_sigma_y",
                 "profile_sigma_lat", "profile_edge_x"):
        v = getattr(region, name)
        if v is None or not np.isfinite(v):
            raise ValueError(
                f"region '{region.name}': doping_profile="
                f"'{region.doping_profile}' requires a finite {name}")
    if region.profile_sigma_y <= 0.0 or region.profile_sigma_lat <= 0.0:
        raise ValueError(
            f"region '{region.name}': profile_sigma_y/profile_sigma_lat "
            "must be > 0")
    if region.profile_high_side not in ("left", "right"):
        raise ValueError(
            f"region '{region.name}': profile_high_side must be "
            f"'left' or 'right', got {region.profile_high_side!r}")


def rasterize_doping(structure, mesh_spec):
    """Net doping [cm^-3], shape (Ny, Nx) for 2D or (Nz, Ny, Nx) for 3D
    (3D device authoring, phase 1 -- dispatches on
    mesh_spec.dimensionality).  Regions apply in list order, later
    overwrites earlier, over a 0 cm^-3 background -- the same rule
    mosfet_doping() uses implicitly (background then source/drain
    painted over it), made explicit here.

    Each region is either "uniform" (the flat net_doping_cm3 fill) or
    "gaussian_erfc" (mosfet_doping()'s own Gaussian-in-depth x
    erfc-lateral-rolloff shape, straggle measured from THIS region's
    y_min -- i.e. the region's own top edge stands in for the mask/
    surface _sd_profile normally measures depth from) -- 2D ONLY;
    a 3D region must be "uniform" (refused loudly otherwise, an honest
    phase-1 simplification, not a silent fallback)."""
    if mesh_spec.dimensionality == 3:
        return _rasterize_doping_3d(structure, mesh_spec)

    x = np.asarray(mesh_spec.axes["x"], dtype=float)
    y = np.asarray(mesh_spec.axes["y"], dtype=float)
    doping = np.zeros((y.size, x.size))
    for region in structure.regions:
        xi = (x >= region.x_min) & (x <= region.x_max)
        yi = (y >= region.y_min) & (y <= region.y_max)
        mask = np.outer(yi, xi)
        if region.doping_profile == "uniform":
            doping[mask] = region.net_doping_cm3
        elif region.doping_profile == "gaussian_erfc":
            _validate_profile_region(region)
            depth = np.maximum(y - region.y_min, 0.0)
            shaped = _sd_profile(
                x, depth, region.profile_edge_x, region.profile_sigma_y,
                region.profile_sigma_lat, abs(region.profile_peak_cm3),
                region.profile_high_side)
            sign = 1.0 if region.profile_peak_cm3 >= 0.0 else -1.0
            doping[mask] = (sign * shaped)[mask]
        else:
            raise ValueError(
                f"region '{region.name}': unknown doping_profile "
                f"{region.doping_profile!r} (expected 'uniform' or "
                "'gaussian_erfc')")
    return doping


def _rasterize_doping_3d(structure, mesh_spec):
    x = np.asarray(mesh_spec.axes["x"], dtype=float)
    y = np.asarray(mesh_spec.axes["y"], dtype=float)
    z = np.asarray(mesh_spec.axes["z"], dtype=float)
    doping = np.zeros((z.size, y.size, x.size))
    for region in structure.regions:
        if region.doping_profile != "uniform":
            raise ValueError(
                f"region '{region.name}': doping_profile "
                f"{region.doping_profile!r} is not supported for a 3D "
                "region in this phase -- only 'uniform' is (refused "
                "loudly, not silently applied as a 2D-shaped profile)")
        xi = (x >= region.x_min) & (x <= region.x_max)
        yi = (y >= region.y_min) & (y <= region.y_max)
        zi = (z >= region.z_min) & (z <= region.z_max)
        mask = zi[:, None, None] & yi[None, :, None] & xi[None, None, :]
        doping[mask] = region.net_doping_cm3
    return doping
