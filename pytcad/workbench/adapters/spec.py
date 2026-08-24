"""Adapters between the workbench domain core and the wire format.

DeviceSpec (gui/services/device_spec.py) REMAINS the wire/project
format -- this module derives DomainDevices from it and back.  The
import direction (workbench -> gui.services.device_spec) is deliberate
and safe: that module is plain data with zero Qt imports.  Relocating
the DTO to a neutral home is a later, mechanical migration and is
explicitly NOT part of M1.

Equivalence rule: for region-authored devices we never reimplement
doping rasterization, boundary-index resolution, or gate-Vfb physics --
spec_from_domain() rebuilds the StructureModel/MeshModel pair and calls
the EXISTING to_device_spec() builder, so output equality holds by
construction.
"""
from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
)
from gui.services.structure_model import (
    BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec,
    StructureModel,
)

from ..core.device import Boundary, ContactDef, DomainDevice
from ..core.region import Region


# ----------------------------------------------------------------------
#  helpers
# ----------------------------------------------------------------------
def _copy_nodes(nodes):
    return {k: list(v) for k, v in nodes.items()} if nodes else None


def _copy_nested(values):
    return [list(row) if hasattr(row, "__iter__") else row
            for row in values]


def _boundary_from_def(b: Boundary):
    return None if b is None else BoundarySpec(
        edge=b.edge, range_lo=b.range_lo, range_hi=b.range_hi)


def _def_from_boundary(b: BoundarySpec):
    return None if b is None else Boundary(
        edge=b.edge, range_lo=b.range_lo, range_hi=b.range_hi)


# ----------------------------------------------------------------------
#  spec  ->  domain   (IMPORTED shape)
# ----------------------------------------------------------------------
def domain_from_device_spec(spec: DeviceSpec, id="imported",
                            name="Imported device") -> DomainDevice:
    """Derive an IMPORTED-shape DomainDevice from a v0.1 DeviceSpec
    (explicit axes, array doping, node-map contacts).  Lossless: the
    round trip back through spec_from_domain() reproduces the original
    spec exactly."""
    contacts = [
        ContactDef(
            id=c.name, name=c.name, kind=c.kind, V=c.V,
            nodes=_copy_nodes(c.nodes),
            tox_cm=c.tox_cm,
            # an imported gate's Vfb is already resolved; carry it as a
            # fixed manual value so rebuilding reproduces it exactly
            vfb_mode="manual" if c.kind == "gate" else "computed",
            vfb_manual=c.Vfb if c.kind == "gate" else None,
        )
        for c in spec.contacts
    ]
    domain = DomainDevice(
        id=id, name=name,
        dimensionality=spec.mesh.dimensionality,
        T=spec.T, material=spec.material,
        models=dict(spec.models),
        axes={k: list(v) for k, v in spec.mesh.axes.items()},
        explicit_doping=_copy_nested(spec.doping.values),
        ntotal=(list(spec.doping.ntotal)
                if spec.doping.ntotal is not None else None),
        contacts=contacts,
        bias=dict(spec.bias) if spec.bias is not None else None,
    )
    domain.validate()          # unknown materials/config fail at import
    return domain


# ----------------------------------------------------------------------
#  structure/mesh  <->  domain   (AUTHORED shape)
# ----------------------------------------------------------------------
def domain_from_structure(structure: StructureModel, mesh_model: MeshModel,
                          id="authored", name="Authored device") -> DomainDevice:
    """Derive an AUTHORED-shape DomainDevice from the Structure/Mesh
    workbench models (regions over width x height, edge-defined
    contacts, mesh hint).  Lossless: structure_from_domain() on the
    result reproduces both input models exactly."""
    regions = [
        Region(
            id=r.id, name=r.name,
            x_min=r.x_min, x_max=r.x_max, y_min=r.y_min, y_max=r.y_max,
            doping_cm3=r.net_doping_cm3,
        )
        for r in structure.regions
    ]
    contacts = [
        ContactDef(id=c.id, name=c.name, kind="ohmic", V=c.V,
                   boundary=_def_from_boundary(c.boundary))
        for c in structure.contacts
    ]
    contacts += [
        ContactDef(id=g.id, name=g.name, kind="gate", V=g.V,
                   boundary=_def_from_boundary(g.boundary),
                   tox_cm=g.tox_cm, gate_type=g.gate_type,
                   vfb_mode=g.vfb_mode, vfb_manual=g.vfb_manual)
        for g in structure.gates
    ]
    domain = DomainDevice(
        id=id, name=name,
        dimensionality=2,
        T=300.0,
        material=structure.material,
        width_cm=structure.width_cm, height_cm=structure.height_cm,
        mesh_nx=mesh_model.nx, mesh_ny=mesh_model.ny,
        mesh_grading=mesh_model.grading,
        # every grading parameter carried verbatim so MeshModel equality
        # survives the round trip (ratio has a default; pass it anyway)
        mesh_grading_params={
            "x_focus": mesh_model.x_focus, "y_focus": mesh_model.y_focus,
            "h_min": mesh_model.h_min, "h_max": mesh_model.h_max,
            "ratio": mesh_model.ratio},
        regions=regions, contacts=contacts,
    )
    domain.validate()          # unknown materials/config fail at import
    return domain


def structure_from_domain(dev: DomainDevice):
    """Rebuild (StructureModel, MeshModel) from an authored DomainDevice.
    Raises ValueError on non-silicon region materials -- honest failure
    until a heterostructure-capable backend exists."""
    dev.validate()
    regions = [
        RegionSpec(id=r.id, name=r.name,
                   x_min=r.x_min, x_max=r.x_max,
                   y_min=r.y_min, y_max=r.y_max,
                   net_doping_cm3=r.doping_cm3)
        for r in dev.regions
    ]
    contacts = [
        ContactModel(id=c.id, name=c.name,
                     boundary=_boundary_from_def(c.boundary), V=c.V)
        for c in dev.contacts if c.kind == "ohmic"
    ]
    gates = [
        GateModel(id=g.id, name=g.name,
                  boundary=_boundary_from_def(g.boundary),
                  tox_cm=g.tox_cm, gate_type=g.gate_type,
                  vfb_mode=g.vfb_mode, vfb_manual=g.vfb_manual, V=g.V)
        for g in dev.contacts if g.kind == "gate"
    ]
    structure = StructureModel(
        width_cm=dev.width_cm, height_cm=dev.height_cm,
        material=dev.material,
        regions=regions, contacts=contacts, gates=gates)
    mesh_model = MeshModel(nx=dev.mesh_nx, ny=dev.mesh_ny,
                           grading=dev.mesh_grading,
                           **dev.mesh_grading_params)
    return structure, mesh_model


# ----------------------------------------------------------------------
#  domain  ->  spec
# ----------------------------------------------------------------------
def _contact_spec_from_def(c: ContactDef) -> ContactSpec:
    if c.nodes is None:
        raise ValueError(
            f"contact '{c.id}': array-doped devices need node-map "
            "contacts (resolve boundaries first)")
    kwargs = {}
    if c.kind == "gate":
        kwargs = {"tox_cm": c.tox_cm,
                  "Vfb": c.vfb_manual if c.vfb_mode == "manual" else None}
    return ContactSpec(name=c.name, kind=c.kind, nodes=_copy_nodes(c.nodes),
                       V=c.V, **kwargs)


def spec_from_domain(dev: DomainDevice) -> DeviceSpec:
    """Build the wire-format DeviceSpec from a DomainDevice.

    IMPORTED shape: direct reconstruction.  AUTHORED shape: delegates to
    the EXISTING StructureModel.to_device_spec() builder so rasterize
    order, boundary indices and gate-Vfb resolution are identical by
    construction; only `models`/`T` are applied from the domain object
    afterwards."""
    dev.validate()
    if dev.axes is not None:
        # IMPORTED shape: direct reconstruction of the wire object
        return DeviceSpec(
            mesh=MeshSpec(dimensionality=dev.dimensionality,
                          axes={k: list(v) for k, v in dev.axes.items()}),
            doping=DopingSpec(kind="array",
                              values=_copy_nested(dev.explicit_doping),
                              ntotal=(list(dev.ntotal)
                                      if dev.ntotal is not None else None)),
            material=dev.material, T=dev.T,
            models=dict(dev.models),
            contacts=[_contact_spec_from_def(c) for c in dev.contacts],
            bias=dict(dev.bias) if dev.bias is not None else None,
        )

    # AUTHORED shape: delegate to the EXISTING builder -- identical
    # output by construction (rasterize order, boundary indices, gate
    # Vfb resolution all live there and only there).
    structure, mesh_model = structure_from_domain(dev)
    out = structure.to_device_spec(mesh_model, T=dev.T)
    out.models = dict(dev.models)
    return out
