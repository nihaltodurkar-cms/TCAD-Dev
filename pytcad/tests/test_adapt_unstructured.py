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
)
from pytcad.adapt import mark_dorfler

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
