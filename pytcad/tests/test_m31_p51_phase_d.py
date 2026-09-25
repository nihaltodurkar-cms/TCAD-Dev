"""M31 P5-1 Phase D -- `NewtonOptions.linsolve="auto"`, the selection rule.

See `M31-P5-1-SOLVER-SELECTION-PLAN.md` section 4, Phase D, and
`linsolve.select_auto`'s own docstring for the evidence table this
gate file exercises. Only two `(dim, unstructured, coupled)`
combinations have positive evidence (B4: structured 3D equilibrium;
B9: 3D unstructured coupled DD); B8 (2D unstructured coupled) has an
explicit MEASURED "direct wins" entry; every other combination refuses
to "direct" for lack of evidence (Gate D-3).

THREE GATES
-----------
Gate D-1: the rule's chosen method agrees with `direct` to the
machine-precision standard section 1 already demonstrated, on real
fixtures -- not just the benchmark cases the evidence table was built
from.

Gate D-2: the rule is asked, for each configuration, what it would
choose and why, and the answer is asserted -- a non-empty, checkable
reason string naming real evidence (or its absence), never "trust me".

Gate D-3: the explicit refusal path -- a configuration with no
evidence, or below the smallest size actually measured for one that
has some, resolves to "direct".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import NewtonOptions
from pytcad.linsolve import select_auto, _AUTO_EVIDENCE


# ---------------------------------------------------------------- D-2/D-3
def test_every_evidenced_combo_returns_its_own_method_above_the_floor(monkeypatch):
    # Gates the evidence table, not this machine: pin PETSc/MUMPS as
    # available. Their absence is gated in tests/test_linsolve_no_petsc.py
    # and tests/test_linsolve_mumps.py.
    from pytcad import linsolve
    monkeypatch.setattr(linsolve, "petsc_available", lambda: True)
    monkeypatch.setattr(linsolve, "mumps_available", lambda: True)
    for (dim, unstructured, coupled), entry in _AUTO_EVIDENCE.items():
        method, reason = select_auto(dim, unstructured, coupled,
                                     dof=entry["min_dof"])
        assert method == entry["method"]
        assert reason, "Gate D-2: reason must never be empty"
        assert reason == entry["reason"]


@pytest.mark.parametrize("dim,unstructured,coupled", [
    # NARROWED by M31 P5-1 Phase A-2 (2026-09-10). This list used to
    # hold seven combinations; five of them -- (1,F,T), (2,F,T),
    # (2,T,F), (3,F,T) and (3,T,F) -- have since been MEASURED and now
    # have real entries, so asserting they are absent would assert the
    # opposite of the truth. They moved to
    # tests/test_m31_p51_phase_a2.py, which checks each against the
    # method and floor that were measured for it.
    #
    # These two remain genuinely unmeasured, and are the only cells left
    # that Gate D-3 guards for real: both are STRUCTURED EQUILIBRIUM
    # paths, and neither has a select_auto dispatch site at all --
    # Device1D.solve_equilibrium and Device2D.solve_equilibrium hardcode
    # method="direct" and never read opts.linsolve. So no selection rule
    # can reach them, and measuring them would produce a number no
    # caller could act on.
    (1, False, False),
    (2, False, False),
])
def test_unmeasured_combinations_refuse_to_direct(dim, unstructured, coupled):
    """Gate D-3: a combination that has not been measured -- including
    one that superficially resembles a measured one -- refuses rather
    than guessing."""
    assert (dim, unstructured, coupled) not in _AUTO_EVIDENCE
    method, reason = select_auto(dim, unstructured, coupled, dof=10**9)
    assert method == "direct"
    assert "no Phase A measurement exists" in reason
    assert "Gate D-3" in reason


@pytest.mark.parametrize("dim,unstructured,coupled", [(3, False, False), (3, True, True)])
def test_below_the_measured_floor_refuses_to_direct(dim, unstructured, coupled):
    # Phase A's own two entries. The floors added by Phase A-2 are
    # gated in tests/test_m31_p51_phase_a2.py, generically over the
    # whole table, so this stays a check on the ORIGINAL two rather
    # than drifting into a duplicate of that one.
    entry = _AUTO_EVIDENCE[(dim, unstructured, coupled)]
    method, reason = select_auto(dim, unstructured, coupled,
                                 dof=entry["min_dof"] - 1)
    assert method == "direct"
    assert "below the smallest size actually measured" in reason
    # The reason still names the ORIGINAL evidence, not just the refusal
    # -- Gate D-2 again: why there IS evidence, and why it isn't used.
    assert "Phase A" in reason


def test_b8_is_an_explicit_measured_refusal_not_an_absence():
    """B8 (2D unstructured coupled) is NOT merely unmeasured -- direct
    was measured to win. The reason must say so, distinctly from the
    generic "no measurement exists" refusal."""
    method, reason = select_auto(2, unstructured=True, coupled=True, dof=34023)
    assert method == "direct"
    assert "MEASURED" in reason
    assert "no Phase A measurement exists" not in reason


def test_newtonoptions_accepts_auto_without_validation_error():
    """NewtonOptions.linsolve has no enumerated-value validation (only
    precond/block_size do, Phase B) -- "auto" must construct cleanly."""
    NewtonOptions(linsolve="auto")


# ---------------------------------------------------------------- D-1 (plumbing + agreement)
def test_structured_3d_equilibrium_auto_reaches_petsc_and_agrees_with_direct():
    """B4's own configuration, on a small real Device3D fixture: `auto`
    at a DOF at or above B4's measured floor resolves to petsc and
    agrees with direct to the machine-precision standard section 1
    established."""
    pytest.importorskip("scipy")
    petsc4py = pytest.importorskip("petsc4py")
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D
    from pytcad.mesh import uniform_mesh

    # >= 4913 (B4's own measured floor) so auto actually recommends
    # petsc. Same construction as benchmarks/cases.py's own _b4.
    n = 17          # (n+1)^3 = 5832 >= 4913
    xs = uniform_mesh(1.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, n))
    Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    dop = np.where(Z < 0.2e-4, 1e19, -1e17)

    dev_d = Device3D(mesh, dop.ravel().copy())
    dev_d.solve_equilibrium(NewtonOptions(linsolve="direct"))

    dev_a = Device3D(mesh, dop.ravel().copy())
    dev_a.solve_equilibrium(NewtonOptions(linsolve="auto"))

    assert dev_a.last_auto_method == "petsc", \
        f"auto should have resolved to petsc at this DOF, got {dev_a.last_auto_method}"
    assert dev_a.last_auto_reason and "B4" in dev_a.last_auto_reason

    assert np.max(np.abs(dev_a.psi - dev_d.psi)) <= 1e-14, \
        "Gate D-1: auto's petsc result must agree with direct to 1e-14"


def test_structured_3d_equilibrium_auto_below_floor_stays_direct():
    """The SAME device shape, sized below B4's measured floor -- auto
    must refuse, not extrapolate down."""
    pytest.importorskip("scipy")
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D
    from pytcad.mesh import uniform_mesh

    n = 5           # (n+1)^3 = 216, well below 4913
    xs = uniform_mesh(1.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, n))
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), 1e16)
    dev = Device3D(mesh, dop.ravel())
    dev.solve_equilibrium(NewtonOptions(linsolve="auto"))
    assert dev.last_auto_method == "direct"
    assert "below the smallest size actually measured" in dev.last_auto_reason


def test_1d_and_2d_structured_auto_is_always_direct_and_bit_identical():
    """1D and 2D structured coupled solves must be bit-identical under
    "auto" to the caller having asked for "direct" outright, at any
    size, confirmed on a real coupled solve.

    The ASSERTIONS here are unchanged by M31 P5-1 Phase A-2; only the
    reason they hold is. When this was written, auto resolved to direct
    because Phase A had measured neither cell. Phase A-2 measured both
    (B2 and B3) and direct WON both, so the entries it added say
    "direct" and this gate keeps passing on evidence instead of on
    absence. Had 2D come out iterative, this test would have failed --
    which is the point of leaving it here rather than rewriting it."""
    from pytcad import Device1D, Models

    x = np.linspace(0.0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e17, 1e17)

    dev_d = Device1D(x, dop.copy(), T=300.0, models=Models(bgn=False, srh=True))
    dev_d.solve_bias([0.3, 0.0], NewtonOptions(linsolve="direct"))

    dev_a = Device1D(x, dop.copy(), T=300.0, models=Models(bgn=False, srh=True))
    dev_a.solve_bias([0.3, 0.0], NewtonOptions(linsolve="auto"))

    assert dev_a.last_auto_method == "direct"
    assert np.array_equal(dev_a.psi, dev_d.psi)
    assert np.array_equal(dev_a.n, dev_d.n)
    assert np.array_equal(dev_a.p, dev_d.p)


def test_unstructured_2d_auto_matches_direct_bit_identically():
    """B8's own core: auto resolves to "direct" (the measured winner)
    and is therefore trivially bit-identical to requesting "direct"."""
    gmsh = pytest.importorskip("gmsh")
    from pytcad.gmsh_mesh import build_diode_mesh
    from pytcad.region_resolver import resolve_regions, resolve_contacts
    from pytcad.unstructured_assembly import (
        build_unstructured_stencil, build_edge_flux_geometry)
    from pytcad.unstructured_poisson import evaluate_doping_at_nodes
    import pytcad.unstructured_dd as udd_mod

    mesh = build_diode_mesh(Lx=4.0e-4, Ly=1.0e-4, Xj=2.0e-4)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles, region_of_triangle,
                                 {"p_region": -1e17, "n_region": 1e17})
    bias = {"left_contact": 0.3, "right_contact": 0.0}

    psi_d, n_d, p_d, scale_d, _ = udd_mod.solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias, opts=NewtonOptions(linsolve="direct"))
    psi_a, n_a, p_a, scale_a, _ = udd_mod.solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias, opts=NewtonOptions(linsolve="auto"))

    assert scale_a["auto_method"] == "direct"
    assert "MEASURED" in scale_a["auto_reason"]
    assert np.array_equal(psi_d, psi_a)
    assert np.array_equal(n_d, n_a)
    assert np.array_equal(p_d, p_a)
    assert scale_a["linsolve_fallbacks"] == 0


def test_unstructured_3d_dd_auto_reaches_petsc_and_agrees_with_direct():
    """B9's own core, at full size (>= B9's measured floor): auto
    resolves to petsc and agrees with direct to the machine-precision
    standard section 1 established."""
    gmsh = pytest.importorskip("gmsh")
    petsc4py = pytest.importorskip("petsc4py")
    from pytcad.gmsh_mesh3d import build_diode_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    import pytcad.unstructured_dd3d as udd3d_mod

    mesh = build_diode_mesh3d(Lx=2.0e-4, Ly=5.0e-5, Lz=3.0e-5, Xj=1.0e-4,
                              Nd_scale=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = udd3d_mod.evaluate_doping_at_nodes3d(
        mesh.nodes, mesh.tets, region_of_tet,
        {"p_region": -1e17, "n_region": 1e17})
    contacts = {"left_contact": mesh.face_tags["left_contact"],
               "right_contact": mesh.face_tags["right_contact"]}
    bias = {"left_contact": 0.3, "right_contact": 0.0}
    assert mesh.nodes.shape[0] * 3 >= 2889, \
        "fixture must be at/above B9's measured floor for this gate to mean anything"

    psi_d, n_d, p_d, scale_d, _ = udd3d_mod.solve_bias3d(
        mesh.nodes, mesh.tets, edges, node_vols, trans, C, contacts, bias,
        opts=NewtonOptions(linsolve="direct"))
    psi_a, n_a, p_a, scale_a, _ = udd3d_mod.solve_bias3d(
        mesh.nodes, mesh.tets, edges, node_vols, trans, C, contacts, bias,
        opts=NewtonOptions(linsolve="auto"))

    assert scale_a["auto_method"] == "petsc"
    assert "B9" in scale_a["auto_reason"]
    assert np.max(np.abs(psi_d - psi_a)) <= 1e-12, \
        "Gate D-1: auto's petsc result must agree with direct to near machine precision"
