"""Built-in example structures, expressed as DeviceSpecs.

Note what this module does NOT do: it does not teach solver_runner about
MOSFETs.  build_mosfet() is called here, once, purely to get a
ready-made Device2D whose mesh/doping/contacts are then read off into a
GENERIC DeviceSpec.  The subprocess only ever sees that generic spec, so
adding examples later never accumulates special cases at the process
boundary (design spec section 12).

build_mosfet() runs no solver -- it only constructs -- so this is fast
and safe to call on the UI thread.
"""
import numpy as np

from pytcad.mosfet import build_mosfet
from pytcad.device2d import DirichletBC, GateBC

from .device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec


def _spec_from_device2d(dev, bias=None):
    """Read a constructed Device2D back out into a generic DeviceSpec."""
    contacts = []
    for name, bc in dev.bcs.items():
        nodes = {"i": np.asarray(bc.i, dtype=int).ravel().tolist(),
                 "j": np.asarray(bc.j, dtype=int).ravel().tolist()}
        if isinstance(bc, GateBC):
            # kappa = eps_ox*LD/(eps_s*tox) -- invert it to recover tox_cm,
            # so the spec stays a physical description rather than a
            # snapshot of pytcad's internal scaling.
            from pytcad.constants import EPS0
            from pytcad.moscap import EPS_OX_R
            tox_cm = (EPS_OX_R * EPS0) * dev.LD / (dev.eps * bc.kappa)
            contacts.append(ContactSpec(name=name, kind="gate", nodes=nodes,
                                        V=bc.Vg, tox_cm=tox_cm, Vfb=bc.Vfb))
        elif isinstance(bc, DirichletBC):
            contacts.append(ContactSpec(name=name, kind="ohmic",
                                        nodes=nodes, V=bc.V))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2,
                      axes={"x": dev.mesh.x.tolist(), "y": dev.mesh.y.tolist()}),
        doping=DopingSpec(kind="array", values=dev.doping.tolist(),
                          ntotal=dev.Ntot.tolist()),
        contacts=contacts,
        bias=bias,
    )


def mosfet_example_spec():
    """A 2D n-channel MOSFET at a single bias point.

    Geometry matches examples/04_mosfet_idvg.py (the validated structure
    whose source/drain tails do not merge under the gate), at a coarser
    nx/ny: ~7.7k nodes solves in about a second, which is long enough to
    demonstrate a non-blocking UI and short enough to stay pleasant.

    Chosen over the 1D diode because it exercises ohmic contacts AND a
    gate, covering more of the ContactSpec path for one extra step.
    """
    dev = build_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=1e17, Nsd_peak=1e19,
                       tox_cm=5e-7, gate="n+poly", sigma_y=5e-6, sigma_lat=1e-6,
                       nx=80, ny=40)
    return _spec_from_device2d(dev, bias={"drain": 0.05, "gate": 1.0,
                                          "source": 0.0, "body": 0.0})


def diode_1d_example_spec():
    """A 1D forward-biased p-n diode at a single bias point.

    Deliberately Device1D's own shape (mesh dimensionality=1, two ohmic
    contacts at the end nodes, no gate -- Device1D has no gate/contact
    registry at all, see solver_runner.py's build_bcs()). An asymmetric
    one-sided junction (light p-side sets the depletion width, matching
    the pattern tests/test_m15_ionization.py's _one_sided() already
    uses) so the exported doping profile is a realistic, non-trivial
    step rather than a toy symmetric one.
    """
    x = np.linspace(0.0, 6e-4, 240)
    doping = np.where(x < 3e-4, -1e16, 1e19)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="anode", kind="ohmic",
                              nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="cathode", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.6)],
        bias={"anode": 0.0, "cathode": 0.6})


def resistor_2d_example_spec():
    """A uniform 2D n-type resistor bar: two ohmic contacts on opposite
    edges, no junction and no gate -- the simplest possible 2D device,
    useful as a fast/cheap counterpart to the MOSFET example and as a
    minimal case for exercising the devsim backend (which refuses gates
    and non-default region_materials but accepts exactly this shape).

    Built via the same DomainDevice + spec_from_domain() path the
    Device Builder templates use (workbench/core/templates.py's
    _build_pn_diode is the closest sibling), rather than constructing a
    DeviceSpec by hand -- so mesh/doping-array construction and
    boundary-node resolution are never reimplemented here.
    """
    from workbench.adapters.spec import spec_from_domain
    from workbench.core.device import Boundary, ContactDef, DomainDevice
    from workbench.core.region import Region

    w, h = 4e-4, 1e-4
    dev = DomainDevice(
        id="resistor_2d", name="2D resistor", dimensionality=2,
        width_cm=w, height_cm=h, mesh_nx=80, mesh_ny=20,
        regions=[Region("bar", "N-type bar", 0.0, w, 0.0, h, 1e17)],
        contacts=[
            ContactDef(id="left_c", name="left", kind="ohmic", V=0.0,
                      boundary=Boundary(edge="left")),
            ContactDef(id="right_c", name="right", kind="ohmic", V=0.1,
                      boundary=Boundary(edge="right")),
        ],
    )
    # bias is derived from each ContactDef's V by to_device_spec() on
    # this authored path -- no need to set DomainDevice.bias separately.
    return spec_from_domain(dev)


def _x_face_node_indices(i, ny, nz):
    """Every (i, j, k) node on the x=const face at index `i`, as the
    flat {"i", "j", "k"} lists ContactSpec.nodes expects for a 3D
    device. Local to this module: the same construction is hand-rolled
    several times over in pytcad's own 3D benchmarks/tests/examples
    with no shared helper there, and pytcad/*.py is frozen core (see
    AGENTS.md) -- not something this GUI-side module can refactor into.
    This at least stops gui/services/examples.py from growing its own
    second copy as more 3D examples are added here."""
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    return {"i": [i] * len(jj), "j": jj, "k": kk}


def resistor_3d_example_spec():
    """A uniform 3D n-type resistor bar: two ohmic contacts on the
    opposite x-faces, no junction and no gate -- the 3D analogue of
    resistor_2d_example_spec(). 3D-VISUALIZATION-PLAN.md Phase 1's
    foundation example: the first (and, as of this writing, only) GUI
    path to a Device3D.

    Built directly against MeshSpec/ContactSpec rather than through
    workbench.adapters.spec.spec_from_domain(): that adapter's AUTHORED
    (Region/ContactDef) path only builds 2D StructureModels today (see
    structure_from_domain(), hardcoded dimensionality=2) -- there is no
    DomainDevice->DeviceSpec path for 3D yet, so contact-face node
    indices are resolved here by hand instead of reusing that machinery.

    Small mesh (12x8x8 = 768 nodes) so it solves in well under a second
    -- a demo, not a stress test.
    """
    nx, ny, nz = 12, 8, 8
    x = np.linspace(0.0, 4e-4, nx)
    y = np.linspace(0.0, 1e-4, ny)
    z = np.linspace(0.0, 1e-4, nz)
    doping = np.full((nz, ny, nx), 1e17)

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                     axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic",
                              nodes=_x_face_node_indices(0, ny, nz), V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes=_x_face_node_indices(nx - 1, ny, nz), V=0.1)],
        bias={"left": 0.0, "right": 0.1})


def _top_face_node_indices(i_list, nz):
    """Every (i, j=0, k) node on the y=0 (top-surface) face for a given
    set of x-indices, as the flat {"i", "j", "k"} lists ContactSpec.nodes
    expects. Same rationale as _x_face_node_indices above for staying
    local to this module rather than reaching into frozen pytcad/*.py."""
    ii, kk = np.meshgrid(np.asarray(i_list, dtype=int), np.arange(nz),
                         indexing="ij")
    ii, kk = ii.ravel().tolist(), kk.ravel().tolist()
    return {"i": ii, "j": [0] * len(ii), "k": kk}


def _bottom_face_node_indices(nx, ny, nz):
    """Every (i, j=ny-1, k) node on the substrate's bottom face -- the
    body/bulk contact every real (4-terminal) MOSFET needs, same as
    pytcad/mosfet.py::build_mosfet's own "body" contact at j=Ny-1."""
    ii, kk = np.meshgrid(np.arange(nx), np.arange(nz), indexing="ij")
    ii, kk = ii.ravel().tolist(), kk.ravel().tolist()
    return {"i": ii, "j": [ny - 1] * len(ii), "k": kk}


def mosfet_3d_example_spec():
    """A realistic 3D n-channel MOSFET: Lg=600 nm gate, Lsd=300 nm
    source/drain, 200 nm deep substrate, W=1 um channel width,
    Na=1e17 cm^-3 p-channel, Nsd=1e19 cm^-3 n+ source/drain, 5 nm gate
    oxide, n+ poly gate -- the same cross-section validated in
    examples/04_mosfet_idvg.py and tests/test_validation_2d.py, now
    extruded across a real device width with the gate as a true 3D
    Robin boundary condition (ContactSpec(kind="gate", normal_axis="y")
    on the top surface). See examples/06_3d_mosfet.py for the full
    derivation, mesh-quality discussion (M21 adaptive refinement), and
    the two independent validation checks (dimensional consistency vs.
    the 2D solver; threshold voltage and subthreshold swing vs. Sze &
    Ng / Taur & Ning published formulas) this exact structure passed.

    Fixed (non-adaptive) mesh here, deliberately: this is a UI quick-
    load example that must construct instantly on the UI thread, like
    every other EXAMPLES entry -- running the M21 adaptive-refinement
    driver (multiple full 3D solves) does not belong behind a menu
    click. The fixed mesh below (NX=18/NY=9/NZ=8 grading parameters,
    ~15,800 actual nodes) is the same one examples/06_3d_mosfet.py
    started from before adding adaptive refinement, and it already
    produces the validated, physically clean Id-Vg curve that example
    reports -- adaptive refinement improved mesh QUALITY (worst h/L_D
    96 -> 48), not correctness.

    Loads unbiased (Vg=0, Vds=0); use the Sweeps panel for an Id-Vg
    transfer curve, same as the 2D MOSFET examples.
    """
    from pytcad.mesh import graded_mesh, uniform_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.mosfet import mosfet_doping
    from pytcad.moscap import flatband_voltage
    from pytcad.materials import SILICON

    Lg, Lsd, depth = 6e-5, 3e-5, 2e-5
    W = 1e-4
    Na, Nsd_peak = 1e17, 1e19
    tox_cm = 5e-7
    sigma_y, sigma_lat = 5e-6, 1e-6
    NX, NY, NZ = 18, 9, 8

    L = 2 * Lsd + Lg
    x = graded_mesh(L, [Lsd, Lsd + Lg], h_min=L / (NX * 20), h_max=L / NX, ratio=1.15)
    y = graded_mesh(depth, [0.0], h_min=depth / (NY * 20), h_max=depth / NY, ratio=1.15)
    z = uniform_mesh(W, NZ)
    nz = z.size

    mesh2 = Mesh2D(x, y)
    dop2d, ntot2d = mosfet_doping(mesh2, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat)
    doping = np.tile(dop2d, (nz, 1, 1))
    ntotal = np.tile(ntot2d, (nz, 1, 1))

    i_src = np.where(x <= Lsd)[0].tolist()
    i_drn = np.where(x >= Lsd + Lg)[0].tolist()
    i_gate = np.where((x > Lsd) & (x < Lsd + Lg))[0].tolist()
    Vfb = flatband_voltage(-Na, tox_cm, "n+poly", 0.0, 300.0, SILICON)

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                     axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist(),
                          ntotal=ntotal.tolist()),
        contacts=[
            ContactSpec(name="source", kind="ohmic",
                       nodes=_top_face_node_indices(i_src, nz), V=0.0),
            ContactSpec(name="drain", kind="ohmic",
                       nodes=_top_face_node_indices(i_drn, nz), V=0.0),
            ContactSpec(name="body", kind="ohmic",
                       nodes=_bottom_face_node_indices(x.size, y.size, nz), V=0.0),
            ContactSpec(name="gate", kind="gate",
                       nodes=_top_face_node_indices(i_gate, nz),
                       V=0.0, tox_cm=tox_cm, Vfb=Vfb, normal_axis="y"),
        ],
        bias={"source": 0.0, "drain": 0.0, "body": 0.0, "gate": 0.0})


EXAMPLES = {"mosfet_2d": mosfet_example_spec,
           "diode_1d": diode_1d_example_spec,
           "resistor_2d": resistor_2d_example_spec,
           "resistor_3d": resistor_3d_example_spec,
           "mosfet_3d": mosfet_3d_example_spec}


from .structure_model import BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel


def mosfet_example_structure():
    """A second, honestly-simpler representative MOSFET, built from
    uniform rectangular regions to exercise the Structure/Mesh workbench.
    Deliberately NOT a rectangular decomposition of build_mosfet()'s
    smooth Gaussian/erfc profile -- see the design spec section 17.5.

    Geometry: 1.2e-4 cm wide (matching mosfet_example_spec's domain),
    2e-5 cm deep. Source: x in [0, 3e-5]. Gate: x in [3e-5, 9e-5].
    Drain: x in [9e-5, 1.2e-4]. Channel background covers the full width;
    source/drain regions are listed after it so they overwrite it in
    their own x-range (see rasterize_doping's list-order rule).
    """
    width_cm, height_cm = 1.2e-4, 2e-5
    Lsd, Lg = 3e-5, 6e-5

    structure = StructureModel(width_cm=width_cm, height_cm=height_cm, regions=[
        RegionSpec("channel", "Channel", 0.0, width_cm, 0.0, height_cm, -1e17),
        RegionSpec("source", "Source", 0.0, Lsd, 0.0, height_cm, 1e19),
        RegionSpec("drain", "Drain", Lsd + Lg, width_cm, 0.0, height_cm, 1e19),
    ], contacts=[
        ContactModel("source_c", "source", BoundarySpec("top", 0.0, Lsd), V=0.0),
        ContactModel("drain_c", "drain", BoundarySpec("top", Lsd + Lg, width_cm), V=0.05),
        ContactModel("body_c", "body", BoundarySpec("bottom"), V=0.0),
    ], gates=[
        GateModel("gate", "gate", BoundarySpec("top", Lsd, Lsd + Lg),
                  tox_cm=5e-7, gate_type="n+poly", vfb_mode="computed", V=1.0),
    ])
    mesh = MeshModel(nx=80, ny=40, grading="uniform")
    return structure, mesh


STRUCTURE_EXAMPLES = {"mosfet_2d_structure": mosfet_example_structure}
