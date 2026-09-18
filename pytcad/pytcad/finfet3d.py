"""M26 -- 3D tri-gate FinFET template on the structured (tensor-product)
Device3D/Mesh3D path.

HONEST SCOPE STATEMENT (read this before trusting a number out of this
module):

  * M26's own spec calls for "unstructured 3D (tets) on top of
    M21/M22" with "FinFET/GAA templates built as extruded 2D process
    output."  This module does NOT do that.  It builds the FinFET
    directly with closed-form doping (same technique as mosfet.py's
    build_mosfet, generalized one axis further) on the existing
    structured, tensor-product Device3D/Mesh3D core -- the same
    "structured-mesh slice first, general mesh later" pattern already
    used for M23 (process2d.py). A real gmsh-tet fin geometry with a
    wrap-around gate BC on the unstructured path
    (pytcad/unstructured_dd3d.py) does not exist yet -- that solver
    currently supports ohmic contacts only, no Robin/gate BC at all.
    Likewise, extruding pytcad.process2d's mask-driven mesa etch into
    a 3D fin cross-section has no glue code yet. Both are real,
    disclosed future work, not silently dropped.

  * The tri-gate itself (top + two sidewall Robin/GateBC faces, one
    oxide capacitance kappa per face) is genuine, already-exercised
    Device3D machinery (device3d.py's GateBC/add_gate, proven on the
    'y' and 'z' normal axes independently in examples/06_3d_mosfet.py
    and the GUI's finfet_3d_example_spec) -- just newly packaged here
    as a reusable pytcad-core builder instead of being GUI-only.

  * Source/drain/channel doping is the same closed-form Gaussian x
    erfc analytic profile mosfet.py uses (mosfet_doping), tiled
    uniformly along the fin-width (z) axis -- there is no fin-specific
    corner rounding, no 3D process simulation, and no short-channel
    quantum confinement correction (density-gradient is Device1D/
    MOSCapacitor-only per device3d.py's own constructor guard).

  * The M26 acceptance criterion "FinFET electrostatics vs published
    TCAD-literature curves (DIBL/SSE trends)" is interpreted, and
    delivered, as a LITERATURE-TREND gate: short-channel FinFETs
    documented in the literature (e.g. Colinge, "FinFETs and Other
    Multi-Gate Transistors") show DIBL and subthreshold swing that
    both worsen (increase) as gate length shrinks, because the gate
    loses electrostatic control over the channel potential.  This
    module's acceptance test (see test_model_benchmarks.py) checks
    that qualitative trend on two channel lengths of an otherwise
    identical tri-gate FinFET -- it is NOT a quantitative match to any
    specific published I-V curve.
"""

import numpy as np

from .mesh import graded_mesh
from .mesh2d import Mesh2D
from .mesh3d import Mesh3D
from .device3d import Device3D
from .device import Models, NewtonOptions
from .mosfet import mosfet_doping
from .moscap import flatband_voltage
from .materials import SILICON


def build_finfet3d(Lg, Lsd, Hfin, Wfin, tox_cm, Na, Nsd_peak,
                    sigma_y=None, sigma_lat=None, gate="n+poly", Qf=0.0,
                    T=300.0, material=SILICON, NX=10, NY=6, NZ=6,
                    mesh_ratio=1.15, dg=False, dg_gamma=1.0):
    """Build a ready-to-solve n-channel tri-gate FinFET Device3D.

    Domain: x in [0, 2*Lsd+Lg] (source | gate | drain), y in [0, Hfin]
    (fin top surface at y=0, "depth" running into the fin), z in
    [0, Wfin] (the two fin sidewalls at z=0 and z=Wfin).  The gate
    wraps the top face (y=0, normal_axis='y') and both sidewalls
    (z=0 and z=Wfin, normal_axis='z') over the channel x-range only.
    Source/drain/body contacts are ohmic. See this module's docstring
    for the full honesty clause.

    NX/NY/NZ set graded_mesh's h_min/h_max targets per axis, not the
    final node count directly -- with three independently graded axes
    the realised node count is substantially larger than NX*NY*NZ (see
    mosfet_3d example in the GUI for measured numbers at production
    scale). Use small NX/NY/NZ for fast acceptance-gate runs.

    dg/dg_gamma : M42-S4 (2026-09-18): Models(dg=..., dg_gamma=...)
    passthrough, so a caller can solve this SAME tri-gate geometry's
    density-gradient-corrected equilibrium (see
    tests/test_m42_s4_finfet_confinement.py). dg=False (the default)
    reproduces the EXACT pre-M42-S4 Models() -- Models(dg=False,
    dg_gamma=1.0) and Models() are field-for-field identical, so this
    is additive, not a behavior change, for every existing caller.
    dg=True is equilibrium-only (Device3D.solve_bias refuses it,
    matching Device1D/Device2D) -- id_vg_sweep_3d below is therefore
    incompatible with dg=True, same restriction M42 has everywhere.
    """
    sigma_y = sigma_y if sigma_y is not None else Lg / 4.0
    sigma_lat = sigma_lat if sigma_lat is not None else Lg / 4.0

    L = 2 * Lsd + Lg
    x = graded_mesh(L, [Lsd, Lsd + Lg],
                     h_min=L / (NX * 20), h_max=L / NX, ratio=mesh_ratio)
    y = graded_mesh(Hfin, [0.0],
                     h_min=Hfin / (NY * 20), h_max=Hfin / NY, ratio=mesh_ratio)
    z = graded_mesh(Wfin, [0.0, Wfin],
                     h_min=Wfin / (NZ * 20), h_max=Wfin / NZ, ratio=mesh_ratio)
    nz = z.size

    mesh2 = Mesh2D(x, y)
    dop2d, ntot2d = mosfet_doping(mesh2, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat)
    doping = np.tile(dop2d, (nz, 1, 1))
    ntotal = np.tile(ntot2d, (nz, 1, 1))

    mesh3 = Mesh3D(x, y, z)
    dev = Device3D(mesh3, doping, Ntotal=ntotal, T=T, material=material,
                   models=Models(dg=dg, dg_gamma=dg_gamma))

    i_src = np.where(x <= Lsd)[0]
    i_drn = np.where(x >= Lsd + Lg)[0]
    i_gate = np.where((x > Lsd) & (x < Lsd + Lg))[0]

    # Source/drain/body ohmic contacts: full fin cross-section (all j,
    # all k) at the source/drain x-columns, and the fin-bottom face
    # (j = Ny-1) for body -- same convention device3d.py's own tests
    # use for a "bottom of the device" contact.
    src_i, src_j, src_k = np.meshgrid(i_src, np.arange(mesh3.Ny), np.arange(nz), indexing='ij')
    drn_i, drn_j, drn_k = np.meshgrid(i_drn, np.arange(mesh3.Ny), np.arange(nz), indexing='ij')
    dev.add_contact("source", src_i.ravel(), src_j.ravel(), src_k.ravel(), V=0.0)
    dev.add_contact("drain", drn_i.ravel(), drn_j.ravel(), drn_k.ravel(), V=0.0)

    body_i, body_k = np.meshgrid(np.arange(mesh3.Nx), np.arange(nz), indexing='ij')
    dev.add_contact("body", body_i.ravel(),
                     np.full(body_i.size, mesh3.Ny - 1), body_k.ravel(), V=0.0)

    Vfb = flatband_voltage(-Na, tox_cm, gate, Qf, T, material)

    # Top gate: y=0 face over the channel x-range, all k (corner nodes
    # at k=0/k=Nz-1 belong here, not to the side gates, to avoid
    # double-counting the oxide capacitance there).
    top_i, top_k = np.meshgrid(i_gate, np.arange(nz), indexing='ij')
    dev.add_gate("gate_top", top_i.ravel(), np.zeros(top_i.size, dtype=int),
                 top_k.ravel(), tox_cm=tox_cm, Vfb=Vfb, normal_axis='y')

    # Side gates: z=0 and z=Wfin-1 faces over the channel x-range,
    # excluding j=0 (already claimed by the top gate above).
    j_side = np.arange(1, mesh3.Ny)
    left_i, left_j = np.meshgrid(i_gate, j_side, indexing='ij')
    dev.add_gate("gate_left", left_i.ravel(), left_j.ravel(),
                 np.zeros(left_i.size, dtype=int),
                 tox_cm=tox_cm, Vfb=Vfb, normal_axis='z')
    right_i, right_j = np.meshgrid(i_gate, j_side, indexing='ij')
    dev.add_gate("gate_right", right_i.ravel(), right_j.ravel(),
                 np.full(right_i.size, nz - 1, dtype=int),
                 tox_cm=tox_cm, Vfb=Vfb, normal_axis='z')

    return dev


def build_fin_corner_slab(Ly, Lz, tox_cm, Na, Vfb, T=300.0, material=SILICON,
                          NY=6, NZ=6, mesh_ratio=1.3, dg=True, dg_gamma=1.0,
                          gaa=False):
    """M42-S4 (2026-09-18): a controlled fin-CORNER geometry for the
    density-gradient confinement demonstration section 10.8 asks for --
    "confinement from two faces at once in a fin corner."

    SAME gate topology and corner-avoidance convention as
    build_finfet3d's tri-gate (top face at y=0 claims BOTH corner
    columns z=0/z=Nz-1, to avoid double-counting the oxide Robin term
    there; the two side faces at z=0/z=Wfin start at y=1) -- but with
    UNIFORM p-type doping and a DIRECTLY parameterized Vfb (one value,
    applied to all three gates) instead of build_finfet3d's Gaussian
    source/drain profile, exactly mirroring how S2's own
    test_m42_s2_gate_bc.py `_build_gated_device` isolates the single-
    gate confinement question from MOSFET-specific doping complexity.
    A short, uniform x-axis (3 nodes, non-degenerate spacing -- see
    test_m42_s2_gate_bc.py's own `_transverse_mesh` docstring for why
    an exactly-uniform mesh+doping combination can stall the coupled
    Newton solve) stands in for the along-fin direction, which this
    demonstration does not need to vary.

    Returns a solved (dg=True by default) Device3D. The physically
    meaningful comparison is the DENSITY SUPPRESSION RATIO
    (classical n / DG n) at the first real (non-gate-pinned) node
    adjacent to the CORNER (j=1, k=1 -- one step in from both the top
    face and a side face at once) vs. adjacent to a FLAT face away
    from any corner (j=1, k=Nz//2 -- one step from the top face only).
    See tests/test_m42_s4_finfet_confinement.py for the actual
    comparison and its literature framing (Colinge's fin-corner
    effect, already cited in this module's own M26 docstring) --
    reported as a QUALITATIVE TREND per section 10.8, not a
    quantitative match to any published curve (M14-G-A's standing
    lesson: no such curve was sought or found).

    gaa=True (added same day, closing the "no GAA geometry" gap named
    in the S4 handoff): wraps a FOURTH gate face (y=Ly, "bottom") in
    addition to top/left/right, i.e. a genuine gate-all-around cross-
    section -- same Robin/GateBC machinery, no new physics. Since all
    four lateral faces are now gated, the ohmic reference contact
    moves from the y=Ny-1 face (no longer free) to the i=0 END face
    instead (all j, k) -- a long-axis contact, not a lateral one, so
    it does not compete with any gate for surface nodes. Corner-
    avoidance convention generalizes symmetrically: top/bottom each
    claim their own full k-range INCLUDING both corners; left/right
    claim only the strictly-interior j-range (excluding j=0 AND
    j=Ny-1, both already claimed)."""
    x_t = np.array([0.0, 0.4e-4, 1e-4])
    y = graded_mesh(Ly, [0.0], h_min=Ly / (NY * 30), h_max=Ly / NY,
                     ratio=mesh_ratio)
    z = graded_mesh(Lz, [0.0, Lz], h_min=Lz / (NZ * 30), h_max=Lz / NZ,
                     ratio=mesh_ratio)
    mesh = Mesh3D(x_t, y, z)
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), -abs(Na))
    dev = Device3D(mesh, dop, T=T, material=material,
                   models=Models(bgn=False, dg=dg, dg_gamma=dg_gamma))

    ii = np.arange(mesh.Nx)
    if gaa:
        far_j, far_k = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz),
                                   indexing='ij')
        dev.add_contact("far", np.zeros(far_j.size, dtype=int),
                        far_j.ravel(), far_k.ravel(), V=0.0)
    else:
        far_i, far_k = np.meshgrid(ii, np.arange(mesh.Nz), indexing='ij')
        dev.add_contact("far", far_i.ravel(),
                        np.full(far_i.size, mesh.Ny - 1), far_k.ravel(), V=0.0)

    top_i, top_k = np.meshgrid(ii, np.arange(mesh.Nz), indexing='ij')
    dev.add_gate("top", top_i.ravel(), np.zeros(top_i.size, dtype=int),
                 top_k.ravel(), tox_cm=tox_cm, Vfb=Vfb, normal_axis='y')

    j_side = (np.arange(1, mesh.Ny - 1) if gaa else np.arange(1, mesh.Ny))
    left_i, left_j = np.meshgrid(ii, j_side, indexing='ij')
    dev.add_gate("left", left_i.ravel(), left_j.ravel(),
                 np.zeros(left_i.size, dtype=int),
                 tox_cm=tox_cm, Vfb=Vfb, normal_axis='z')
    right_i, right_j = np.meshgrid(ii, j_side, indexing='ij')
    dev.add_gate("right", right_i.ravel(), right_j.ravel(),
                 np.full(right_i.size, mesh.Nz - 1, dtype=int),
                 tox_cm=tox_cm, Vfb=Vfb, normal_axis='z')

    if gaa:
        bot_i, bot_k = np.meshgrid(ii, np.arange(mesh.Nz), indexing='ij')
        dev.add_gate("bottom", bot_i.ravel(),
                     np.full(bot_i.size, mesh.Ny - 1, dtype=int),
                     bot_k.ravel(), tox_cm=tox_cm, Vfb=Vfb, normal_axis='y')

    dev.solve_equilibrium(NewtonOptions(max_iter=400))
    return dev


def id_vg_sweep_3d(dev, Vg_list, Vds, opts: NewtonOptions = None, verbose=True):
    """Ramp all three tri-gate faces together at fixed Vds, source and
    body held at 0 V.  Returns Id [A] at each Vg (real Amps -- see
    Device3D.terminal_current's own docstring; this is a full 3D
    device, not per-unit-width like Device2D). Reseeds each solve from
    the previous converged point, same pattern as mosfet.py's
    id_vg_sweep."""
    opts = opts or NewtonOptions()
    dev.solve_equilibrium(opts)
    Id = []
    for Vg in Vg_list:
        dev.solve_bias({"drain": Vds, "gate_top": Vg,
                         "gate_left": Vg, "gate_right": Vg}, opts)
        I = dev.terminal_current("drain")
        Id.append(I)
        if verbose:
            print(f"  Vg = {Vg:+.3f} V   Id = {I:+.6e} A")
    return np.array(Id)
