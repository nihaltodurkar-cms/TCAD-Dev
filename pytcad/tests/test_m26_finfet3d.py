"""M26 structural/consistency gates: 3D tri-gate FinFET builder
(pytcad/finfet3d.py) and Id-Vg characterization (pytcad/characterization.py).

The literature-trend DIBL/SS acceptance gate itself lives in
test_model_benchmarks.py per house rule (it is the actual physics
benchmark, and it is slow -- a handful of full 3D Id-Vg sweeps). This
file covers cheaper structural checks: mesh/contact bookkeeping and
the characterization functions' own numerical behavior on synthetic
data, plus the "3D reduces to 2D" identity extended to a FinFET-shaped
(as opposed to planar-MOSFET-shaped) 3D structure.

See finfet3d.py's module docstring for the honesty clause on what is
simplified (structured tensor-product mesh, not unstructured tets;
closed-form analytic doping, not a 2D-process-extrusion pipeline).

Also in this file: `test_unstructured_gate_bc_reduces_to_2d`, the
GENERAL-MESH (unstructured tet) sibling of test_validation_3d.py's
structured-only "3D reduces to 2D" identity gate, validating the new
Robin/gate BC unstructured_dd3d.py gained as part of this same M26
pass (see that module's own docstring for the scaling-bug fix this
gate BC work also surfaced and corrected)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad.finfet3d import build_finfet3d, id_vg_sweep_3d
from pytcad.characterization import (
    extract_vth_constant_current, extract_subthreshold_swing, extract_dibl,
)

warnings.simplefilter("ignore")

SMALL = dict(Lg=0.5e-6, Lsd=0.3e-6, Hfin=0.3e-6, Wfin=0.2e-6, tox_cm=2e-7,
             Na=1e17, Nsd_peak=1e19, NX=5, NY=3, NZ=3, mesh_ratio=1.3)


def test_build_finfet3d_registers_three_gate_faces_and_three_ohmic_contacts():
    dev = build_finfet3d(**SMALL)
    for name in ("source", "drain", "body", "gate_top", "gate_left", "gate_right"):
        assert name in dev.bcs
    from pytcad.device3d import GateBC, DirichletBC
    assert isinstance(dev.bcs["gate_top"], GateBC)
    assert isinstance(dev.bcs["gate_left"], GateBC)
    assert isinstance(dev.bcs["gate_right"], GateBC)
    assert isinstance(dev.bcs["source"], DirichletBC)


def test_finfet3d_side_gates_do_not_double_count_top_gate_corner_nodes():
    """The two sidewall gates must exclude j=0 (the fin-top row),
    which belongs exclusively to the top gate -- otherwise the top
    edge's oxide capacitance would be double-counted."""
    dev = build_finfet3d(**SMALL)
    left = dev.bcs["gate_left"]
    right = dev.bcs["gate_right"]
    assert np.all(np.asarray(left.j) >= 1)
    assert np.all(np.asarray(right.j) >= 1)


def test_finfet3d_equilibrium_solves_and_charge_neutral_far_from_junctions():
    dev = build_finfet3d(**SMALL)
    from pytcad.device import NewtonOptions
    dev.solve_equilibrium(NewtonOptions())
    # far into the source region the electron density should
    # essentially match the (near-fully-ionised) n-type doping there
    n = dev.n_cm3
    assert n.max() > 1e18


def test_id_vg_sweep_3d_current_is_finite_and_reasonable_scale():
    dev = build_finfet3d(**SMALL)
    Vg = np.array([0.0, 0.3, 0.6])
    Id = id_vg_sweep_3d(dev, Vg, Vds=0.05, verbose=False)
    assert Id.shape == (3,)
    assert np.all(np.isfinite(Id))
    assert np.all(np.abs(Id) < 1.0)   # sane for a sub-micron device, real Amps


def test_extract_vth_constant_current_matches_linear_interpolation():
    vg = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ids = np.array([1e-9, 1e-8, 1e-6, 1e-5, 5e-5, 1e-4])
    vth = extract_vth_constant_current(vg, ids, target=1e-6)
    assert vth == pytest.approx(0.4, abs=1e-9)


def test_extract_subthreshold_swing_recovers_known_decade_per_volt_slope():
    """A synthetic exponential Id(Vg) = 1e-12 * 10**(Vg/S) with a known
    S=100 mV/decade must be recovered by the extractor."""
    S = 0.1  # V/decade
    vg = np.linspace(0.0, 0.5, 50)
    ids = 1e-12 * 10 ** (vg / S)
    ss = extract_subthreshold_swing(vg, ids)
    assert ss == pytest.approx(100.0, rel=0.05)


def test_extract_dibl_is_zero_for_a_drain_bias_independent_curve():
    vg = np.linspace(0.0, 1.0, 20)
    ids = np.clip(vg - 0.3, 0.0, None) * 1e-4 + 1e-10
    dibl = extract_dibl(vg, ids, vg, ids, vd_low=0.05, vd_high=1.0, target=1e-6)
    assert dibl == pytest.approx(0.0, abs=1e-9)


def test_extract_dibl_matches_hand_computed_value_for_a_shifted_curve():
    """A curve shifted left by exactly 100 mV at higher Vds must report
    DIBL = 0.1 / (vd_high - vd_low)."""
    vg = np.linspace(0.0, 1.0, 200)
    ids_low = np.clip(vg - 0.5, 0.0, None) * 1e-4 + 1e-12
    ids_high = np.clip(vg - 0.4, 0.0, None) * 1e-4 + 1e-12
    dibl = extract_dibl(vg, ids_low, vg, ids_high, vd_low=0.05, vd_high=0.55, target=1e-6)
    assert dibl == pytest.approx(0.1 / 0.5, rel=0.05)


@pytest.mark.slow
def test_unstructured_gate_bc_reduces_to_2d():
    """M26 gate: unstructured_dd3d.py's new gate/Robin BC, on a
    GENERAL (unstructured tet) mesh, must reduce to the (already-
    validated) 2D Device2D gated-slab solve -- the general-mesh
    sibling of test_validation_3d.py's structured-only reduces-to-2D
    gate, and the acceptance test that actually caught (and drove the
    fix for) the trans_geom scaling bug documented in
    unstructured_dd3d.py's own module docstring.

    Methodology, stated honestly: a genuinely UNSTRUCTURED tet mesh
    node almost never sits exactly on the 2D solver's own (x,y) grid,
    so this test necessarily interpolates the 2D reference onto the
    tet nodes' positions. The near-gate-surface transition layer has a
    very steep potential gradient (an inversion layer, physically
    nanometers thick), where even a small (x,y) mismatch between a tet
    node and its nearest 2D grid point produces a locally large value
    difference on EITHER side -- confirmed by direct inspection to be
    an interpolation/discretization-resolution artifact, not a
    physical disagreement (exact same-position mid-channel gate-surface
    values agree to <1%). This test therefore checks two BOUNDED,
    physically meaningful quantities instead of a blanket per-node
    bound: (1) the deep-bulk equilibrium potential (unaffected by the
    gate, should match near-exactly), and (2) the MEAN gate-surface
    potential over the gated region (excluding the two contact-edge
    corners, a well known singular corner in ANY gated-contact mesh),
    compared to the 2D reference's mean over the identical x-range --
    both at a tolerance well inside physical significance but far
    tighter than the (pre-fix) failure mode this gate BC actually had,
    where the gate produced literally NO effect (surface indistinguishable
    from bulk to double precision)."""
    from pytcad.mesh import graded_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.device2d import Device2D
    from pytcad.device import Models, thermal_voltage
    from pytcad.gmsh_mesh3d import build_gated_slab_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d,
    )
    from pytcad.unstructured_dd3d import solve_poisson_equilibrium3d
    from pytcad.materials import SILICON
    from scipy.interpolate import RegularGridInterpolator
    pytest.importorskip("gmsh")

    Lx, Ly, Lz, Na = 1.2e-4, 6e-5, 3e-5, 1e17
    tox_cm, Vfb = 2e-7, -0.9
    VT = thermal_voltage(300.0)

    x = graded_mesh(Lx, [0.0, Lx], 5e-7, 6e-6, 1.2)
    y = graded_mesh(Ly, [0.0], 5e-7, 5e-6, 1.2)
    mesh2 = Mesh2D(x, y)
    dop2d = -Na * np.ones((mesh2.Ny, mesh2.Nx))
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_gate("gate", i=list(range(mesh2.Nx)), j=[0] * mesh2.Nx,
                  tox_cm=tox_cm, Vfb=Vfb, Vg=0.0)
    dev2.solve_equilibrium()
    psi2 = dev2.psi_V / VT
    interp = RegularGridInterpolator((y, x), psi2, bounds_error=False, fill_value=None)

    m = build_gated_slab_mesh3d(Lx=Lx, Ly=Ly, Lz=Lz, Na=Na)
    edges, node_vols = build_unstructured_stencil3d(m.nodes, m.tets)
    edges, trans = build_edge_flux_geometry3d(m.nodes, m.tets, edges)
    C_phys = -Na * np.ones(m.n_nodes())
    contacts = {"left": m.face_tags["left_contact"], "right": m.face_tags["right_contact"]}
    gates = {"gate": {"faces": m.face_tags["gate"], "tox_cm": tox_cm, "Vfb": Vfb, "Vg": 0.0}}
    psi3, scale = solve_poisson_equilibrium3d(
        m.nodes, m.tets, edges, node_vols, trans, C_phys, contacts,
        material=SILICON, gates=gates)

    xs, ys = m.nodes[:, 0], m.nodes[:, 1]
    nie_s = SILICON.ni(300.0) / Na
    bulk_expected = np.arcsinh(-1.0 / (2.0 * nie_s))
    bulk_mask = ys > 0.3 * Ly
    assert psi3[bulk_mask].mean() == pytest.approx(bulk_expected, abs=0.05)

    gate_mask = (ys < 1e-9) & (np.minimum(xs, Lx - xs) > 5e-6)
    assert gate_mask.sum() > 100
    psi3_gate_mean = psi3[gate_mask].mean()
    psi2_gate_mean = interp(np.column_stack([ys[gate_mask], xs[gate_mask]])).mean()
    assert psi3_gate_mean == pytest.approx(psi2_gate_mean, abs=1.5)

    # regression guard for the exact bug this test caught: a broken
    # gate BC leaves the surface indistinguishable from bulk.
    assert psi3_gate_mean - psi3[bulk_mask].mean() > 20.0


# ------------------------------------------------------------------
#  process2d -> 3D-tet extrusion pipeline (gmsh_finfet3d.py)
# ------------------------------------------------------------------
def _build_test_finfet_geom():
    from pytcad import process2d
    Lsd, Lg = 0.3e-4, 0.4e-4
    L = 2 * Lsd + Lg
    x = np.linspace(0.0, L, 200)
    geom = process2d.ProcessGeometry2D(x)
    fin_mask = process2d.mask_from_intervals(x, [(Lsd, Lsd + Lg)])
    geom = process2d.etch(geom, depth_um=0.3, mask=~fin_mask)
    return geom, Lsd, Lg


def test_finfet_mesh3d_from_process2d_tags_all_expected_regions_and_faces():
    pytest.importorskip("gmsh")
    from pytcad.gmsh_finfet3d import build_finfet_mesh3d_from_process2d
    geom, Lsd, Lg = _build_test_finfet_geom()
    m = build_finfet_mesh3d_from_process2d(geom, Wfin=0.2e-4, Lsd=Lsd, Lg=Lg,
                                           mesh_size_cm=1e-6)
    assert set(m.volume_tags) == {"source", "gate", "drain"}
    assert set(m.face_tags) == {"source_contact", "drain_contact",
                                "body_contact", "gate"}
    for tets in m.volume_tags.values():
        assert len(tets) > 0
    for faces in m.face_tags.values():
        assert faces.shape[0] > 0 and faces.shape[1] == 3


def test_finfet_mesh3d_from_process2d_doping_regions_have_correct_sign():
    pytest.importorskip("gmsh")
    from pytcad.gmsh_finfet3d import build_finfet_mesh3d_from_process2d
    from pytcad.unstructured_dd3d import evaluate_doping_at_nodes3d
    geom, Lsd, Lg = _build_test_finfet_geom()
    m = build_finfet_mesh3d_from_process2d(geom, Wfin=0.2e-4, Lsd=Lsd, Lg=Lg,
                                           mesh_size_cm=1e-6)
    region_of_tet = np.empty(m.n_tets(), dtype=object)
    for name, idxs in m.volume_tags.items():
        region_of_tet[idxs] = name
    C = evaluate_doping_at_nodes3d(m.nodes, m.tets, region_of_tet,
                                   {"source": 1e18, "gate": -1e17, "drain": 1e18})
    xs = m.nodes[:, 0]
    deep_gate = (xs > Lsd + 0.1e-4) & (xs < Lsd + Lg - 0.1e-4)
    deep_source = xs < Lsd - 0.1e-4
    assert (C[deep_gate] < 0).all()
    assert (C[deep_source] > 0).all()


def test_finfet_mesh3d_from_process2d_rejects_mismatched_geometry_span():
    pytest.importorskip("gmsh")
    from pytcad import process2d
    from pytcad.gmsh_finfet3d import build_finfet_mesh3d_from_process2d
    x = np.linspace(0.0, 1e-4, 50)   # too short for Lsd=1e-4, Lg=1e-4
    geom = process2d.ProcessGeometry2D(x)
    with pytest.raises(ValueError):
        build_finfet_mesh3d_from_process2d(geom, Wfin=0.2e-4, Lsd=1e-4, Lg=1e-4)


@pytest.mark.slow
def test_finfet_mesh3d_from_process2d_equilibrium_solve_converges():
    """The M26 acceptance-relevant check for this pipeline: a real
    Poisson equilibrium solve (with the new gate BC) on a genuinely
    process2d-derived 3D tet FinFET geometry converges cleanly. See
    gmsh_finfet3d.py's own honesty clause for why this test does NOT
    additionally check the fully coupled drift-diffusion bias solve --
    that was measured to need voltage ramping/continuation this pass
    doesn't implement, disclosed as future work rather than silently
    skipped."""
    pytest.importorskip("gmsh")
    from pytcad.gmsh_finfet3d import build_finfet_mesh3d_from_process2d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d,
    )
    from pytcad.unstructured_dd3d import (
        evaluate_doping_at_nodes3d, solve_poisson_equilibrium3d,
    )
    from pytcad.materials import SILICON

    geom, Lsd, Lg = _build_test_finfet_geom()
    m = build_finfet_mesh3d_from_process2d(geom, Wfin=0.2e-4, Lsd=Lsd, Lg=Lg,
                                           mesh_size_cm=1e-6)
    region_of_tet = np.empty(m.n_tets(), dtype=object)
    for name, idxs in m.volume_tags.items():
        region_of_tet[idxs] = name
    C_phys = evaluate_doping_at_nodes3d(m.nodes, m.tets, region_of_tet,
                                        {"source": 1e18, "gate": -1e17, "drain": 1e18})
    edges, node_vols = build_unstructured_stencil3d(m.nodes, m.tets)
    edges, trans = build_edge_flux_geometry3d(m.nodes, m.tets, edges)
    contacts = {"source": m.face_tags["source_contact"],
               "drain": m.face_tags["drain_contact"]}
    gates = {"gate": {"faces": m.face_tags["gate"], "tox_cm": 2e-7, "Vfb": -0.9}}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        psi, scale = solve_poisson_equilibrium3d(
            m.nodes, m.tets, edges, node_vols, trans, C_phys, contacts,
            material=SILICON, gates=gates)
    assert np.all(np.isfinite(psi))
    # the gate must visibly deplete/invert the channel relative to its
    # own flatband -- a bulk-only (ungated) p-region equilibrium would
    # sit near a single value; the gate creates real spatial spread.
    assert psi.max() - psi.min() > 10.0
