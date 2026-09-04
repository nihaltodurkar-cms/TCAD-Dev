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
    workbench.adapters.spec.spec_from_domain(): this predates the 3D
    device-authoring domain model (workbench/core/region.py's
    z_min/z_max, workbench/core/device.py's front/back faces) added in
    3D device authoring phase 1. That path now exists and produces a
    bit-identical DeviceSpec for this exact geometry (see
    tests/test_workbench_m1.py's 3D-authoring golden-parity test) --
    this function is kept as the GUI's own hand-built demo/foundation
    example, not because the adapter path is missing.

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
        bias={"source": 0.0, "drain": 0.0, "body": 0.0, "gate": 0.0},
        # v0.6 Phase 2f: this is a homojunction device (plain SILICON
        # throughout -- doping is the only thing that changes), so
        # region_materials has nothing to key off; structure_regions
        # tiles the SAME source/channel/drain x-split i_src/i_gate/
        # i_drn above already computed, full y/z extent each, so the
        # 3D viewer's exploded-view feature has real named parts to
        # separate.
        structure_regions=[
            {"name": "source", "box": [0.0, Lsd, 0.0, depth, 0.0, W]},
            {"name": "channel", "box": [Lsd, Lsd + Lg, 0.0, depth, 0.0, W]},
            {"name": "drain", "box": [Lsd + Lg, L, 0.0, depth, 0.0, W]},
        ])


def finfet_3d_example_spec():
    """3D tri-gate FinFET: gate wraps around top and two sides of a narrow fin.

    Geometry:
    - Lg=30 nm gate, Lsd=20 nm source/drain extensions
    - Hfin=30 nm fin height, Wfin=20 nm fin width
    - tox=2 nm gate oxide, n+ poly gate
    - Na=1e17 cm^-3 p-type body/channel
    - Nsd=1e19 cm^-3 n+ source/drain

    Tri-gate: top (j=0, normal_axis='y') + two sides (k=0 and k=Nz-1,
    normal_axis='z').  Corner nodes belong exclusively to the top gate
    to avoid double-counting the oxide capacitance.

    NX/NY/NZ=10/6/6 only set graded_mesh's h_min/h_max targets, not the
    final node count directly: graded_mesh's arc-length construction
    (see pytcad/mesh.py) realises however many nodes the requested
    grading ratio actually needs, which for three independently graded
    axes comes out much denser than the naive NX*NY*NZ=360 -- ~39,000
    nodes measured directly. Still constructs and solves on the UI
    thread in well under a second; the equilibrium+bias Newton solve
    itself is the slow part (tens of seconds), not construction.
    """
    from pytcad.mesh import graded_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.mosfet import mosfet_doping
    from pytcad.moscap import flatband_voltage
    from pytcad.materials import SILICON

    Lg = 3e-6
    Lsd = 2e-6
    Hfin = 3e-6
    Wfin = 2e-6
    tox_cm = 2e-7
    Na = 1e17
    Nsd_peak = 1e19
    sigma_y = 5e-7
    sigma_lat = 2e-7

    NX, NY, NZ = 10, 6, 6
    L = 2 * Lsd + Lg

    x = graded_mesh(L, [Lsd, Lsd + Lg],
                    h_min=L / (NX * 20), h_max=L / NX, ratio=1.15)
    y = graded_mesh(Hfin, [0.0],
                    h_min=Hfin / (NY * 20), h_max=Hfin / NY, ratio=1.15)
    # Focused at the two gated sidewalls (z=0, z=Wfin), not the fin
    # centre: that's where the side-gate Robin BCs actually sit and
    # where the accumulation/depletion charge gradient is steepest,
    # mirroring the y-axis's own focus at y=0 for the top gate.
    z = graded_mesh(Wfin, [0.0, Wfin],
                    h_min=Wfin / (NZ * 20), h_max=Wfin / NZ, ratio=1.15)
    nz = z.size

    mesh2 = Mesh2D(x, y)
    dop2d, ntot2d = mosfet_doping(mesh2, Lsd, Lg, Na, Nsd_peak,
                                   sigma_y, sigma_lat)
    doping = np.tile(dop2d, (nz, 1, 1))
    ntotal = np.tile(ntot2d, (nz, 1, 1))

    i_src = np.where(x <= Lsd)[0].tolist()
    i_drn = np.where(x >= Lsd + Lg)[0].tolist()
    i_gate = np.where((x > Lsd) & (x < Lsd + Lg))[0].tolist()
    Vfb = flatband_voltage(-Na, tox_cm, "n+poly", 0.0, 300.0, SILICON)

    top_gate = _top_face_node_indices(i_gate, nz)

    left_i, left_j, left_k = [], [], []
    for i_idx in i_gate:
        for j_idx in range(1, y.size):
            left_i.append(i_idx)
            left_j.append(j_idx)
            left_k.append(0)
    left_gate = {"i": left_i, "j": left_j, "k": left_k}

    right_i, right_j, right_k = [], [], []
    for i_idx in i_gate:
        for j_idx in range(1, y.size):
            right_i.append(i_idx)
            right_j.append(j_idx)
            right_k.append(nz - 1)
    right_gate = {"i": right_i, "j": right_j, "k": right_k}

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist(),
                          ntotal=ntotal.tolist()),
        contacts=[
            ContactSpec(name="source", kind="ohmic",
                        nodes=_top_face_node_indices(i_src, nz), V=0.0),
            ContactSpec(name="drain", kind="ohmic",
                        nodes=_top_face_node_indices(i_drn, nz), V=0.0),
            ContactSpec(name="body", kind="ohmic",
                        nodes=_bottom_face_node_indices(x.size, y.size, nz),
                        V=0.0),
            ContactSpec(name="gate_top", kind="gate",
                        nodes=top_gate,
                        V=0.0, tox_cm=tox_cm, Vfb=Vfb, normal_axis="y"),
            ContactSpec(name="gate_left", kind="gate",
                        nodes=left_gate,
                        V=0.0, tox_cm=tox_cm, Vfb=Vfb, normal_axis="z"),
            ContactSpec(name="gate_right", kind="gate",
                        nodes=right_gate,
                        V=0.0, tox_cm=tox_cm, Vfb=Vfb, normal_axis="z"),
        ],
        bias={"source": 0.0, "drain": 0.0, "body": 0.0,
              "gate_top": 0.0, "gate_left": 0.0, "gate_right": 0.0},
        # v0.6 Phase 2f: same homojunction reasoning as mosfet_3d_
        # example_spec's own structure_regions -- tiles the same
        # source/channel(fin-under-gate)/drain x-split i_src/i_gate/
        # i_drn above, full y/z (fin) extent each.
        structure_regions=[
            {"name": "source", "box": [0.0, Lsd, 0.0, Hfin, 0.0, Wfin]},
            {"name": "channel",
             "box": [Lsd, Lsd + Lg, 0.0, Hfin, 0.0, Wfin]},
            {"name": "drain", "box": [Lsd + Lg, L, 0.0, Hfin, 0.0, Wfin]},
        ])


def pn_junction_3d_example_spec():
    """3D asymmetric PN junction diode with Gaussian-graded junction.

    - p-side: Na=1e16 cm^-3 (light doping, wide depletion)
    - n-side: Nd=1e19 cm^-3 (heavy doping, narrow depletion)
    - Junction at x=800 nm, Gaussian grading sigma=10 nm
    - Domain: 2000 nm x 1000 nm x 500 nm (2 um x 1 um x 0.5 um)

    Shows the 3D depletion region and I-V characteristics.  The heavy
    asymmetry (1e19/1e16 = 1000:1) makes the depletion region extend
    almost entirely into the lightly-doped p-side -- a realistic,
    well-understood TCAD benchmark. The p-side must be wide enough to
    hold that depletion region: at this doping the one-sided depletion
    width is W = sqrt(2*eps_s*Vbi/(q*Na)) ~ 340 nm, so the 800 nm p-side
    here leaves headroom before the anode contact; a domain scaled down
    to ~80 nm (an earlier draft of this docstring) would have put the
    contact inside the depletion region itself.

    NX/NY/NZ=16/8/6 are graded_mesh's h_min/h_max targets, not the
    final node count (see finfet_3d_example_spec()'s docstring above
    for why those differ) -- ~33,000 nodes measured directly, not the
    naive 16*8*6=768.
    """
    from pytcad.mesh import graded_mesh
    from pytcad.materials import SILICON
    from scipy.special import erf

    L = 2e-4
    H = 1e-4
    W = 5e-5
    x_junc = 8e-5
    Na = 1e16
    Nd = 1e19
    sigma = 1e-6

    NX, NY, NZ = 16, 8, 6

    x = graded_mesh(L, [x_junc],
                    h_min=L / (NX * 20), h_max=L / NX, ratio=1.15)
    y = graded_mesh(H, [0.0],
                    h_min=H / (NY * 20), h_max=H / NY, ratio=1.15)
    z = graded_mesh(W, [W / 2],
                    h_min=W / (NZ * 20), h_max=W / NZ, ratio=1.15)

    doping_1d = (Nd * (1 + erf((x - x_junc) / sigma)) / 2
                 - Na * (1 - erf((x - x_junc) / sigma)) / 2)
    doping = np.tile(doping_1d, (z.size, y.size, 1))

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="anode", kind="ohmic",
                        nodes=_x_face_node_indices(0, y.size, z.size),
                        V=0.0),
            ContactSpec(name="cathode", kind="ohmic",
                        nodes=_x_face_node_indices(x.size - 1, y.size,
                                                    z.size),
                        V=0.0),
        ],
        bias={"anode": 0.0, "cathode": 0.0},
        # v0.6 Phase 2f: plain SILICON throughout (doping-only
        # junction, same reasoning as mosfet_3d_example_spec's own
        # structure_regions) -- p-side/n-side split at the same
        # x_junc the Gaussian doping profile above is centered on,
        # full y/z extent each.
        structure_regions=[
            {"name": "p_side", "box": [0.0, x_junc, 0.0, H, 0.0, W]},
            {"name": "n_side", "box": [x_junc, L, 0.0, H, 0.0, W]},
        ])


def bjt_3d_example_spec():
    """3D vertical NPN bipolar junction transistor.

    All three regions are plain SILICON -- doping type/level is the only
    thing that changes across the emitter/base/collector junctions, so
    this is a homojunction BJT, not a heterojunction one. (A true HBT
    needs a bandgap-engineered material change, e.g. a SiGe base or an
    AlGaAs/GaAs emitter-base junction -- see workbench/core/templates.py
    for that device, built from actual heterostructure materials. This
    function models the ordinary silicon case and is named accordingly.)

    Structure (top to bottom):
    - Emitter: n+ Nd=1e19, ~300 nm thick
    - Base:    p  Na=5e17, ~400 nm thick
    - Collector: n Nd=5e16, ~800 nm thick

    Contacts:
    - Emitter:  top face (j=0), full x-z extent
    - Base:     left side face (k=0), j range within the base only
    - Collector: bottom face (j=Ny-1), full x-z extent

    Shows 3D bipolar carrier transport with vertical current flow.
    The base contact on a side face exercises a contact topology
    different from the MOSFET's top-surface-only pattern.

    NX/NY/NZ=6/7/4 are graded_mesh's h_min/h_max targets, not the final
    node count (see finfet_3d_example_spec()'s docstring above for why
    those differ) -- ~40,600 nodes measured directly, not the naive
    6*7*4=168. Measured directly end to end (equilibrium + bias, both
    converging cleanly): ~150 s, the slowest of the 3D examples here
    despite having the fewest input NX/NY/NZ -- pytcad's Device3D solve
    cost is dominated by the REALISED node count, not that nominal
    input. (An earlier NX/NY/NZ=10/12/6 draft realised ~72,000 nodes
    and did not finish an equilibrium solve in over 30 minutes; this is
    the first parameter choice confirmed to actually complete.)
    """
    from pytcad.mesh import graded_mesh
    from pytcad.materials import SILICON

    L = 2e-4
    H = 1.5e-4
    W = 5e-5
    H_emit = 3e-5
    H_base = 4e-5

    Nd_emit = 1e19
    Na_base = 5e17
    Nd_coll = 5e16

    NX, NY, NZ = 6, 7, 4

    x = graded_mesh(L, [L / 2],
                    h_min=L / (NX * 20), h_max=L / NX, ratio=1.15)
    y = graded_mesh(H, [H_emit, H_emit + H_base],
                    h_min=H / (NY * 20), h_max=H / NY, ratio=1.15)
    z = graded_mesh(W, [W / 2],
                    h_min=W / (NZ * 20), h_max=W / NZ, ratio=1.15)

    doping = np.zeros((z.size, y.size, x.size))
    for j in range(y.size):
        if y[j] < H_emit:
            doping[:, j, :] = Nd_emit
        elif y[j] < H_emit + H_base:
            doping[:, j, :] = -Na_base
        else:
            doping[:, j, :] = Nd_coll

    ii, kk = np.meshgrid(np.arange(x.size), np.arange(z.size),
                          indexing="ij")
    ii, kk = ii.ravel().tolist(), kk.ravel().tolist()

    j_base = [j for j in range(y.size)
              if H_emit <= y[j] < H_emit + H_base]
    bi, bj, bk = [], [], []
    for i_idx in range(x.size):
        for j_idx in j_base:
            bi.append(i_idx)
            bj.append(j_idx)
            bk.append(0)

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="emitter", kind="ohmic",
                        nodes={"i": ii, "j": [0] * len(ii), "k": kk},
                        V=0.0),
            ContactSpec(name="base", kind="ohmic",
                        nodes={"i": bi, "j": bj, "k": bk},
                        V=0.0),
            ContactSpec(name="collector", kind="ohmic",
                        nodes={"i": ii,
                               "j": [y.size - 1] * len(ii), "k": kk},
                        V=0.0),
        ],
        bias={"emitter": 0.0, "base": 0.0, "collector": 0.0},
        # v0.6 Phase 2f: a homojunction BJT (module docstring above --
        # plain SILICON throughout), same reasoning as mosfet_3d_
        # example_spec's own structure_regions -- tiles the same
        # emitter/base/collector y-layering H_emit/H_base above
        # already computed, full x/z extent each.
        structure_regions=[
            {"name": "emitter", "box": [0.0, L, 0.0, H_emit, 0.0, W]},
            {"name": "base",
             "box": [0.0, L, H_emit, H_emit + H_base, 0.0, W]},
            {"name": "collector",
             "box": [0.0, L, H_emit + H_base, H, 0.0, W]},
        ])


def moscap_3d_example_spec():
    """3D MOS capacitor: a single gate over a uniformly doped p-type
    substrate, with one ohmic body contact on the back face -- no
    source/drain, no lateral variation at all along x or z. The
    simplest possible 3D gated structure: isolates the gate Robin BC
    and its C-V behaviour from mosfet_3d's smooth doping profile and
    extra ohmic contacts, and a natural target for a gate-voltage
    sweep to see a textbook C-V curve.

    - Substrate: p-type, Na=1e17 cm^-3, uniform
    - tox=5 nm, n+ poly gate (same tox/gate-type as mosfet_3d, so the
      two share a directly comparable flatband voltage)
    - Domain: 500 nm x 300 nm deep x 500 nm

    Mesh: ~10x10x10 = 1000 nodes, graded toward the gated surface
    (y=0) where the depletion/inversion physics happens -- the same
    y-axis convention mosfet_3d and finfet_3d use for their top gate.
    """
    from pytcad.mesh import graded_mesh, uniform_mesh
    from pytcad.moscap import flatband_voltage
    from pytcad.materials import SILICON

    L = 5e-5
    W = 5e-5
    depth = 3e-5
    Na = 1e17
    tox_cm = 5e-7

    NX, NY, NZ = 10, 10, 10

    x = uniform_mesh(L, NX)
    y = graded_mesh(depth, [0.0],
                    h_min=depth / (NY * 20), h_max=depth / NY, ratio=1.15)
    z = uniform_mesh(W, NZ)
    nz = z.size

    doping = np.full((nz, y.size, x.size), -Na)
    Vfb = flatband_voltage(-Na, tox_cm, "n+poly", 0.0, 300.0, SILICON)

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="gate", kind="gate",
                        nodes=_top_face_node_indices(
                            list(range(x.size)), nz),
                        V=0.0, tox_cm=tox_cm, Vfb=Vfb, normal_axis="y"),
            ContactSpec(name="body", kind="ohmic",
                        nodes=_bottom_face_node_indices(x.size, y.size, nz),
                        V=0.0),
        ],
        bias={"gate": 0.0, "body": 0.0})


def _x_face_node_indices_jrange(i, j_list, nz):
    """Every (i, j, k) node at x-index `i`, restricted to the y-indices
    in j_list, as the flat {"i", "j", "k"} lists ContactSpec.nodes
    expects. Used by jfet_3d_example_spec() below: its source/drain
    contacts sit only on the n-channel portion of the x=0/x=L end
    faces, not on the p+ gate region underneath -- unlike
    _x_face_node_indices()'s full-face contacts (resistor_3d,
    pn_junction_3d), where the whole end face is one uniform region."""
    jj, kk = np.meshgrid(np.asarray(j_list, dtype=int), np.arange(nz),
                         indexing="ij")
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    return {"i": [i] * len(jj), "j": jj, "k": kk}


def jfet_3d_example_spec():
    """3D n-channel junction field-effect transistor (JFET).

    A single p+ gate diffusion sits BELOW an n-type channel (a
    "buried-channel"/MESA JFET geometry): the gate-channel p-n
    junction's depletion region -- reverse-biased by Vgs -- eats into
    the lightly-doped n-channel from below and pinches it off, the
    textbook JFET mechanism (Sze & Ng ch. 6), in contrast to mosfet_3d
    and finfet_3d's MOS (oxide-isolated Robin BC) gates: this gate is
    an actual ohmic contact on a real p-n junction, no Robin BC at all.

    - Channel: n-type, Nd=1e16 cm^-3, 600 nm thick
    - Gate: p+, Na=1e18 cm^-3, 200 nm thick (below the channel)
    - Gaussian(erf)-graded gate-channel junction, sigma=10 nm
    - Channel length 1 um, width 500 nm

    At Vgs=0 the built-in potential alone (Vbi ~= 0.83 V for this
    doping pair) already depletes ~330 nm of the 600 nm channel from
    the gate junction (one-sided depletion width
    W = sqrt(2*eps_s*Vbi/(q*Nd)) with Na >> Nd putting nearly all of
    it on the channel side), leaving a ~270 nm conducting channel open
    -- normally-on depletion-mode behaviour, closing further as a
    reverse Vgs is applied via the Sweeps panel.

    Source and drain are ohmic contacts on the n-channel ends only
    (not the gate underneath); the gate contact sits on the p+
    region's far face, reusing _bottom_face_node_indices() exactly as
    bjt_3d_example_spec()'s collector does.

    Mesh: ~12x10x6 = 720 nodes.
    """
    from pytcad.mesh import graded_mesh, uniform_mesh
    from scipy.special import erf

    L = 1e-4
    W = 5e-5
    Hch = 6e-5
    Hgate = 2e-5
    H = Hch + Hgate
    Nd_ch = 1e16
    Na_gate = 1e18
    sigma = 1e-6

    NX, NY, NZ = 12, 10, 6

    x = uniform_mesh(L, NX)
    y = graded_mesh(H, [Hch],
                    h_min=H / (NY * 20), h_max=H / NY, ratio=1.15)
    z = uniform_mesh(W, NZ)
    nz = z.size

    doping_1d = (Nd_ch * (1 - erf((y - Hch) / sigma)) / 2
                 - Na_gate * (1 + erf((y - Hch) / sigma)) / 2)
    doping = np.tile(doping_1d[None, :, None], (nz, 1, x.size))

    j_channel = np.where(y <= Hch)[0].tolist()

    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="source", kind="ohmic",
                        nodes=_x_face_node_indices_jrange(0, j_channel, nz),
                        V=0.0),
            ContactSpec(name="drain", kind="ohmic",
                        nodes=_x_face_node_indices_jrange(
                            x.size - 1, j_channel, nz),
                        V=0.0),
            ContactSpec(name="gate", kind="ohmic",
                        nodes=_bottom_face_node_indices(x.size, y.size, nz),
                        V=0.0),
        ],
        bias={"source": 0.0, "drain": 0.0, "gate": 0.0},
        # v0.6 Phase 2f: plain SILICON throughout (the n-channel/p+
        # gate junction here is doping-only, same reasoning as
        # mosfet_3d_example_spec's own structure_regions) -- tiles the
        # same channel/gate y-layering Hch above already computed,
        # full x/z extent each.
        structure_regions=[
            {"name": "channel", "box": [0.0, L, 0.0, Hch, 0.0, W]},
            {"name": "gate", "box": [0.0, L, Hch, H, 0.0, W]},
        ])


EXAMPLES = {"mosfet_2d": mosfet_example_spec,
           "diode_1d": diode_1d_example_spec,
           "resistor_2d": resistor_2d_example_spec,
           "resistor_3d": resistor_3d_example_spec,
           "mosfet_3d": mosfet_3d_example_spec,
           "finfet_3d": finfet_3d_example_spec,
           "pn_junction_3d": pn_junction_3d_example_spec,
           "bjt_3d": bjt_3d_example_spec,
           "moscap_3d": moscap_3d_example_spec,
           "jfet_3d": jfet_3d_example_spec}


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
