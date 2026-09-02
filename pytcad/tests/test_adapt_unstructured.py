"""M21 follow-up -- solution-adaptive refinement on the 2D unstructured
triangle mesh (pytcad/adapt_unstructured.py). See that module's
docstring for the full scope statement (2D only; gmsh-remesh-driven
refinement, not manual bisection; no Debye-adequacy gate).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

gmsh = pytest.importorskip("gmsh")

from pytcad.gmsh_mesh import build_diode_mesh
from pytcad.region_resolver import resolve_regions, resolve_contacts
from pytcad.unstructured_assembly import (
    build_unstructured_stencil, build_edge_flux_geometry,
)
from pytcad.unstructured_dd import evaluate_doping_at_nodes, solve_bias
from pytcad.adapt_unstructured import (
    indicator_curvature_tri, indicator_log_density_tri,
    default_indicator_unstructured, adapt_solve_unstructured_2d,
    indicator_field_tri, indicator_doping_tri, indicator_current_tri,
    indicator_solver_residual_tri, compute_indicator, INDICATOR_REGISTRY,
)
from pytcad.adapt import mark_dorfler
from pytcad.materials import SILICON

warnings.simplefilter("ignore")

DOPING_BY_REGION = {"p_region": -1e17, "n_region": 1e17}


@pytest.fixture(scope="module")
def diode_bias_state():
    mesh = build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                 region_of_triangle, DOPING_BY_REGION)
    psi, n, p, scale, I = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.5, "right_contact": 0.0})
    return dict(mesh=mesh, psi=psi, n=n, p=p, C=C)


# ----------------------------------------------------------------------
#  indicator correctness
# ----------------------------------------------------------------------
def test_curvature_indicator_zero_on_uniform_psi(diode_bias_state):
    mesh = diode_bias_state["mesh"]
    psi_flat = np.ones(mesh.n_nodes())
    eta = indicator_curvature_tri(mesh, psi_flat)
    assert np.allclose(eta, 0.0), "a spatially-constant field has no error to flag"


def test_curvature_indicator_peaks_near_junction(diode_bias_state):
    """The real diode bias-solve's own psi field: the per-triangle
    indicator must be concentrated in the junction region (the
    depletion layer, where psi varies fastest), not uniform noise --
    otherwise Doerfler marking would just refine everywhere, which
    isn't ADAPTIVE refinement."""
    d = diode_bias_state
    mesh, psi = d["mesh"], d["psi"]
    eta = indicator_curvature_tri(mesh, psi)
    centroids = mesh.nodes[mesh.triangles].mean(axis=1)
    xs = centroids[:, 0]
    near_junction = np.abs(xs - 3.0e-4) < 3.0e-5
    far_from_junction = np.abs(xs - 3.0e-4) > 1.0e-4
    assert eta[near_junction].mean() > 5 * eta[far_from_junction].mean(), (
        f"junction mean={eta[near_junction].mean():.3e}, "
        f"bulk mean={eta[far_from_junction].mean():.3e} -- indicator is "
        "not actually concentrating at the depletion region")


def test_default_indicator_marks_a_minority_of_triangles(diode_bias_state):
    d = diode_bias_state
    mesh = d["mesh"]
    eta = default_indicator_unstructured(mesh, d["psi"], d["n"], d["p"])
    assert eta.shape == (mesh.n_triangles(),)
    marked = mark_dorfler(eta, theta=0.3)
    assert 0 < marked.size < mesh.n_triangles(), (
        "adaptive marking should flag SOME but not ALL triangles for "
        "this real (non-uniform) field")


# ----------------------------------------------------------------------
#  Task B: field / doping / current / user-defined indicators
# ----------------------------------------------------------------------
def _physical_solve_state(d, scale):
    return dict(psi=d["psi"] * scale["VT"], n=d["n"] * scale["Ns"],
               p=d["p"] * scale["Ns"], C=d["C"], material=SILICON, T=300.0)


@pytest.fixture(scope="module")
def diode_bias_full():
    """Same fixture as diode_bias_state, but also returns `scale` (for
    converting solve_bias's scaled psi/n/p to physical units) and the
    solve's diagnostics (Newton residual history) for the solver-
    residual indicator tests."""
    mesh = build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in resolve_regions(mesh).items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                 region_of_triangle, DOPING_BY_REGION)
    psi, n, p, scale, I, diag = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.5, "right_contact": 0.0},
        return_diagnostics=True)
    return dict(mesh=mesh, psi=psi, n=n, p=p, C=C, scale=scale, diag=diag)


def _junction_masks(mesh):
    centroids = mesh.nodes[mesh.triangles].mean(axis=1)
    xs = centroids[:, 0]
    return np.abs(xs - 3.0e-4) < 3.0e-5, np.abs(xs - 3.0e-4) > 1.0e-4


def test_field_indicator_peaks_near_junction(diode_bias_full):
    d = diode_bias_full
    psi_phys = d["psi"] * d["scale"]["VT"]
    eta = indicator_field_tri(d["mesh"], psi_phys)
    near, far = _junction_masks(d["mesh"])
    assert eta[near].mean() > 5 * eta[far].mean(), (
        "field indicator does not concentrate at the depletion region")


def test_doping_indicator_peaks_at_junction(diode_bias_full):
    d = diode_bias_full
    eta = indicator_doping_tri(d["mesh"], d["C"])
    near, far = _junction_masks(d["mesh"])
    assert eta[near].mean() > 10 * eta[far].mean(), (
        "doping indicator does not concentrate at the doping step")


def test_current_indicator_larger_near_junction_than_bulk(diode_bias_full):
    d = diode_bias_full
    state = _physical_solve_state(d, d["scale"])
    eta = indicator_current_tri(d["mesh"], state)
    near, far = _junction_masks(d["mesh"])
    assert np.all(np.isfinite(eta))
    assert eta[near].mean() > eta[far].mean(), (
        "current indicator should be larger where current actually "
        "flows/crowds (junction) than deep in the field-free bulk")


def test_user_defined_indicator_concentrates_where_requested(diode_bias_full):
    """A synthetic user-defined indicator that peaks near x=0.7*Lx must
    actually produce marking concentrated there -- proving the
    user_fns hook plugs into the same combine()/mark_dorfler machinery
    as the built-in indicators, not a parallel/inert path."""
    d = diode_bias_full
    mesh = d["mesh"]
    Lx = 6.0e-4
    target_x = 0.7 * Lx

    def near_x_indicator(mesh, solve_state):
        centroids = mesh.nodes[mesh.triangles].mean(axis=1)
        return np.exp(-((centroids[:, 0] - target_x) / (0.05 * Lx)) ** 2)

    state = _physical_solve_state(d, d["scale"])
    eta = compute_indicator(mesh, state, kinds=(), user_fns=[near_x_indicator])
    marked = mark_dorfler(eta, theta=0.5)
    assert marked.size > 0
    centroids = mesh.nodes[mesh.triangles].mean(axis=1)
    marked_x = centroids[marked, 0]
    assert abs(marked_x.mean() - target_x) < 0.1 * Lx, (
        f"marked-triangle mean x={marked_x.mean():.3e}, expected near "
        f"target_x={target_x:.3e}")


def test_solver_residual_indicator_distinct_from_field_indicator(diode_bias_full):
    """The solver-residual indicator must be a REAL, distinct signal --
    not simply a rescaled copy of the field indicator computed from the
    SAME converged solution. Check it is not (near-)identical after
    each is independently peak-normalised."""
    d = diode_bias_full
    mesh = d["mesh"]
    eta_field = indicator_field_tri(mesh, d["psi"] * d["scale"]["VT"])
    eta_res = indicator_solver_residual_tri(
        mesh, d["diag"]["residual_node_history"])
    assert eta_res.shape == eta_field.shape
    assert np.any(eta_res > 0)
    corr = np.corrcoef(eta_field, eta_res)[0, 1]
    assert corr < 0.99, (
        f"solver-residual indicator correlates {corr:.4f} with the field "
        "indicator -- suspiciously close to duplicating it rather than "
        "carrying distinct solver-convergence information")


def test_compute_indicator_combines_multiple_named_kinds(diode_bias_full):
    d = diode_bias_full
    state = _physical_solve_state(d, d["scale"])
    eta = compute_indicator(d["mesh"], state, kinds=("field", "doping"))
    assert eta.shape == (d["mesh"].n_triangles(),)
    assert np.isclose(eta.max(), 1.0)
    marked = mark_dorfler(eta, theta=0.3)
    assert 0 < marked.size < d["mesh"].n_triangles()


def test_compute_indicator_unknown_kind_raises():
    with pytest.raises(ValueError):
        compute_indicator(None, {}, kinds=("not_a_real_kind",))


# ----------------------------------------------------------------------
#  Task C.1: warm-starting from a coarser mesh's converged state
# ----------------------------------------------------------------------
def test_warm_start_reduces_newton_iterations():
    """Solving at V=0.5 warm-started from the SAME mesh's V=0.3
    converged state must take fewer (or equal) Newton iterations than
    a cold start at V=0.5 -- the concrete, measurable claim Task C.1
    makes. Same mesh both times (no interpolation noise) to isolate
    the warm-start effect from mesh-interpolation effects."""
    mesh = build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                 region_of_triangle, DOPING_BY_REGION)

    psi0, n0, p0, _, _, diag0 = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.3, "right_contact": 0.0},
        return_diagnostics=True)

    _, _, _, _, _, diag_cold = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.5, "right_contact": 0.0},
        return_diagnostics=True)

    _, _, _, _, _, diag_warm = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.5, "right_contact": 0.0},
        init=dict(psi=psi0, n=n0, p=p0), return_diagnostics=True)

    assert diag_warm["n_iter"] <= diag_cold["n_iter"], (
        f"warm start ({diag_warm['n_iter']} iters) did not beat or match "
        f"cold start ({diag_cold['n_iter']} iters)")
    assert diag_warm["n_iter"] < diag_cold["n_iter"], (
        "warm start should measurably reduce Newton iterations for this "
        f"fixture (cold={diag_cold['n_iter']}, warm={diag_warm['n_iter']})")


def test_solve_bias_default_return_signature_unchanged():
    """return_diagnostics=False (the default) must reproduce the
    ORIGINAL 5-tuple return -- no default-behavior change."""
    mesh = build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16)
    contacts = resolve_contacts(mesh)
    regions = resolve_regions(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                 region_of_triangle, DOPING_BY_REGION)
    result = solve_bias(
        mesh.nodes, mesh.triangles, edge_list, node_areas, interior_edges,
        trans_geom, C, contacts, bias={"left_contact": 0.3, "right_contact": 0.0})
    assert len(result) == 5


# ----------------------------------------------------------------------
#  outer loop: convergence and termination
# ----------------------------------------------------------------------
@pytest.mark.slow
def test_adaptive_loop_terminates_and_converges():
    psi, n, p, scale, I, mesh, history = adapt_solve_unstructured_2d(
        Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16,
        doping_by_region=DOPING_BY_REGION,
        bias={"left_contact": 0.5, "right_contact": 0.0},
        max_passes=4, tol=2e-2, theta=0.3)
    assert len(history) <= 4
    assert history[-1]["cause"] in ("converged", "max_passes")
    # node count must be non-decreasing across passes (each pass either
    # adds resolution or the loop has already stopped)
    node_counts = [h["nodes"] for h in history]
    assert node_counts == sorted(node_counts)


@pytest.mark.slow
def test_adaptive_refinement_improves_accuracy_vs_uniform_final_mesh():
    """The adaptive loop's FINAL pass must be at least as close to a
    converged reference terminal current as its OWN first (coarse,
    unrefined) pass -- i.e. refinement is actually doing useful work,
    not just changing the answer arbitrarily. Reference: a separately
    built, uniformly fine mesh (small Nd_scale => small target size
    everywhere, not just near the junction)."""
    from pytcad.gmsh_mesh import build_diode_mesh
    ref_mesh = build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=3e15)
    regions = resolve_regions(ref_mesh)
    contacts = resolve_contacts(ref_mesh)
    edge_list, node_areas = build_unstructured_stencil(
        ref_mesh.nodes, ref_mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        ref_mesh.nodes, ref_mesh.triangles, edge_list)
    region_of_triangle = np.empty(ref_mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(ref_mesh.nodes, ref_mesh.triangles,
                                 region_of_triangle, DOPING_BY_REGION)
    _, _, _, _, I_ref = solve_bias(
        ref_mesh.nodes, ref_mesh.triangles, edge_list, node_areas,
        interior_edges, trans_geom, C, contacts,
        bias={"left_contact": 0.5, "right_contact": 0.0})
    I_reference = I_ref["left_contact"]

    psi, n, p, scale, I, mesh, history = adapt_solve_unstructured_2d(
        Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16,
        doping_by_region=DOPING_BY_REGION,
        bias={"left_contact": 0.5, "right_contact": 0.0},
        max_passes=3, tol=1e-6, theta=0.3)   # tiny tol -> run all 3 passes

    err_first = abs(history[0]["qoi"] - I_reference) / abs(I_reference)
    err_last = abs(history[-1]["qoi"] - I_reference) / abs(I_reference)
    assert err_last <= err_first, (
        f"refinement did not improve accuracy: first-pass err={err_first:.3e}, "
        f"final-pass err={err_last:.3e} (reference I={I_reference:.4e})")
