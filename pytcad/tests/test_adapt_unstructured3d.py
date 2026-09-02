"""M21 follow-up 3 (Task A) -- solution-adaptive refinement on the 3D
unstructured tet mesh (pytcad/adapt_unstructured3d.py). See that
module's docstring for the full scope statement, including the
DELIBERATELY SMALL validated geometry scale.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

gmsh = pytest.importorskip("gmsh")

from pytcad.gmsh_mesh3d import build_diode_mesh3d
from pytcad.unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d,
)
from pytcad.unstructured_dd3d import evaluate_doping_at_nodes3d, solve_bias3d
from pytcad.adapt_unstructured3d import (
    indicator_curvature_tet, indicator_log_density_tet,
    indicator_field_tet, indicator_doping_tet, indicator_current_tet,
    indicator_solver_residual_tet, compute_indicator3d, default_indicator_unstructured3d,
    adapt_solve_unstructured_3d,
)
from pytcad.adapt import mark_dorfler
from pytcad.materials import SILICON

warnings.simplefilter("ignore")

# small, sandbox-fast geometry -- see adapt_unstructured3d.py's own
# module docstring HONEST SCALE STATEMENT
GEOM = dict(Lx=8.0e-5, Ly=2.5e-5, Lz=2.0e-5, Xj=4.0e-5)
DOPING_BY_REGION = {"p_region": -1e16, "n_region": 1e16}


@pytest.fixture(scope="module")
def diode3d_bias_state():
    mesh = build_diode_mesh3d(Nd_scale=1e16, **GEOM)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = evaluate_doping_at_nodes3d(mesh.nodes, mesh.tets, region_of_tet,
                                   DOPING_BY_REGION)
    contacts = {"left_contact": mesh.face_tags["left_contact"],
               "right_contact": mesh.face_tags["right_contact"]}
    psi, n, p, scale, I, diag = solve_bias3d(
        mesh.nodes, mesh.tets, edges, node_vols, trans, C, contacts,
        bias={"left_contact": 0.3, "right_contact": 0.0}, material=SILICON,
        return_diagnostics=True)
    return dict(mesh=mesh, psi=psi, n=n, p=p, C=C, scale=scale, diag=diag)


def _junction_masks(mesh):
    centroids = mesh.nodes[mesh.tets].mean(axis=1)
    xs = centroids[:, 0]
    Xj = GEOM["Xj"]
    return np.abs(xs - Xj) < 0.15 * Xj, np.abs(xs - Xj) > 0.6 * Xj


def _physical_state(d):
    return dict(psi=d["psi"] * d["scale"]["VT"], n=d["n"] * d["scale"]["Ns"],
               p=d["p"] * d["scale"]["Ns"], C=d["C"], material=SILICON, T=300.0)


# ----------------------------------------------------------------------
#  per-tet indicator correctness
# ----------------------------------------------------------------------
def test_curvature_indicator_zero_on_uniform_psi(diode3d_bias_state):
    mesh = diode3d_bias_state["mesh"]
    eta = indicator_curvature_tet(mesh, np.ones(mesh.n_nodes()))
    assert np.allclose(eta, 0.0)


def test_field_indicator_peaks_near_junction(diode3d_bias_state):
    d = diode3d_bias_state
    eta = indicator_field_tet(d["mesh"], d["psi"] * d["scale"]["VT"])
    near, far = _junction_masks(d["mesh"])
    assert near.sum() > 0 and far.sum() > 0
    assert eta[near].mean() > 3 * eta[far].mean(), (
        f"junction mean={eta[near].mean():.3e}, bulk mean={eta[far].mean():.3e}")


def test_doping_indicator_peaks_at_junction(diode3d_bias_state):
    d = diode3d_bias_state
    eta = indicator_doping_tet(d["mesh"], d["C"])
    near, far = _junction_masks(d["mesh"])
    assert eta[near].mean() > 5 * eta[far].mean()


def test_current_indicator_finite_and_larger_near_junction(diode3d_bias_state):
    d = diode3d_bias_state
    eta = indicator_current_tet(d["mesh"], _physical_state(d))
    near, far = _junction_masks(d["mesh"])
    assert np.all(np.isfinite(eta))
    assert eta[near].mean() > eta[far].mean()


def test_user_defined_indicator_concentrates_where_requested(diode3d_bias_state):
    d = diode3d_bias_state
    mesh = d["mesh"]
    target_x = 0.7 * GEOM["Lx"]

    def near_x_indicator(mesh, solve_state):
        centroids = mesh.nodes[mesh.tets].mean(axis=1)
        return np.exp(-((centroids[:, 0] - target_x) / (0.05 * GEOM["Lx"])) ** 2)

    eta = compute_indicator3d(mesh, _physical_state(d), kinds=(),
                              user_fns=[near_x_indicator])
    marked = mark_dorfler(eta, theta=0.5)
    assert marked.size > 0
    centroids = mesh.nodes[mesh.tets].mean(axis=1)
    marked_x = centroids[marked, 0]
    assert abs(marked_x.mean() - target_x) < 0.15 * GEOM["Lx"]


def test_solver_residual_indicator_distinct_from_field_indicator(diode3d_bias_state):
    d = diode3d_bias_state
    mesh = d["mesh"]
    eta_field = indicator_field_tet(mesh, d["psi"] * d["scale"]["VT"])
    eta_res = indicator_solver_residual_tet(mesh, d["diag"]["residual_node_history"])
    assert eta_res.shape == eta_field.shape
    assert np.any(eta_res > 0)
    corr = np.corrcoef(eta_field, eta_res)[0, 1]
    assert corr < 0.99


def test_default_indicator_marks_a_minority_of_tets(diode3d_bias_state):
    d = diode3d_bias_state
    mesh = d["mesh"]
    eta = default_indicator_unstructured3d(mesh, d["psi"], d["n"], d["p"])
    assert eta.shape == (mesh.n_tets(),)
    marked = mark_dorfler(eta, theta=0.3)
    assert 0 < marked.size < mesh.n_tets()


# ----------------------------------------------------------------------
#  warm start (Task C.1 ported to 3D)
# ----------------------------------------------------------------------
def test_warm_start_reduces_newton_iterations_3d(diode3d_bias_state):
    d = diode3d_bias_state
    mesh = d["mesh"]
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    contacts = {"left_contact": mesh.face_tags["left_contact"],
               "right_contact": mesh.face_tags["right_contact"]}

    _, _, _, _, _, diag_cold = solve_bias3d(
        mesh.nodes, mesh.tets, edges, node_vols, trans, d["C"], contacts,
        bias={"left_contact": 0.5, "right_contact": 0.0}, material=SILICON,
        return_diagnostics=True)
    _, _, _, _, _, diag_warm = solve_bias3d(
        mesh.nodes, mesh.tets, edges, node_vols, trans, d["C"], contacts,
        bias={"left_contact": 0.5, "right_contact": 0.0}, material=SILICON,
        init=dict(psi=d["psi"], n=d["n"], p=d["p"]), return_diagnostics=True)

    assert diag_warm["n_iter"] <= diag_cold["n_iter"]


# ----------------------------------------------------------------------
#  outer adaptive loop -- small-scale integration
# ----------------------------------------------------------------------
@pytest.mark.slow
def test_adaptive_loop_3d_terminates_and_refines():
    psi, n, p, scale, I, mesh, history = adapt_solve_unstructured_3d(
        doping_by_region=DOPING_BY_REGION,
        bias={"left_contact": 0.3, "right_contact": 0.0},
        max_passes=2, tol=1e-6, theta=0.3)
    assert len(history) <= 2
    node_counts = [h["nodes"] for h in history]
    assert node_counts == sorted(node_counts)
    if len(history) > 1:
        assert 0 < history[1]["marked"] < history[0]["tets"], (
            "second pass should mark a MINORITY of pass-0 tets, not "
            "all/none -- otherwise this isn't ADAPTIVE refinement")


@pytest.mark.slow
def test_adaptive_loop_3d_with_indicator_kinds_and_residual():
    """Same small integration run, but requesting the Task B named
    kinds INCLUDING the Task C solver-residual signal end-to-end,
    through the outer loop's own diagnostics wiring (not just the
    indicator function in isolation)."""
    psi, n, p, scale, I, mesh, history = adapt_solve_unstructured_3d(
        doping_by_region=DOPING_BY_REGION,
        bias={"left_contact": 0.3, "right_contact": 0.0},
        max_passes=2, tol=1e-6, theta=0.3,
        indicator_kinds=("field", "doping", "solver_residual"))
    assert len(history) <= 2
    assert history[0]["n_newton_iter"] is not None
