"""M31 P5-1 Phase C -- fallback parity for the four unstructured loops.

See `M31-P5-1-SOLVER-SELECTION-PLAN.md` section 4, Phase C. Before this
phase, `unstructured_poisson.solve_poisson_equilibrium`,
`unstructured_dd.solve_bias`, and both Newton loops in
`unstructured_dd3d.py` (`solve_poisson_equilibrium3d`, `solve_bias3d`)
called `solve_linear` bare: a non-converged iterative method raised
`LinearSolveError` straight out of the whole solve, on whichever Newton
iterate happened to trip it. The structured cores (`device.py`,
`device2d.py`, `device3d.py`) already degrade gracefully -- this phase
gives the four unstructured loops the identical try/except shape.

TWO GATES
---------
Gate C-1: a solve whose iterative method fails on EVERY iterate still
completes, and its result is `np.array_equal` to the all-direct solve
of the identical fixture -- the fallback path must compute exactly what
`method="direct"` from the start would have, not merely "something
plausible."

Gate C-2: the fallback is REPORTED, not silent. Every affected
function's returned dict gains `linsolve_fallbacks` (an int count),
zero when `opts.linsolve="direct"` (the default -- never enters the
except branch, so this is an additive key, not a behavior change) and
equal to the true number of per-iterate fallbacks otherwise.

HOW "ALWAYS FAILS" IS FORCED, DETERMINISTICALLY
--------------------------------------------------
Rather than hunt for a genuinely ill-conditioned fixture (Phase A found
this is fixture- and even iterate-dependent, not reliably reproducible
on demand), each test patches the module's own `solve_linear` name to
raise `LinearSolveError` immediately for any non-"direct" method and
delegate to the real function for "direct" -- a controlled, fast,
100%-reproducible way to force the fallback path on every single
iterate without needing an actually-hard matrix.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import NewtonOptions
from pytcad.linsolve import LinearSolveError


def _force_iterative_failure(monkeypatch, module):
    """Patch `module.solve_linear` so any non-"direct" method raises
    immediately (no real Krylov work attempted) and "direct" is
    untouched -- forces the fallback path on every Newton iterate."""
    real = module.solve_linear

    def flaky(A, b, *, method="direct", **kwargs):
        if method != "direct":
            raise LinearSolveError("forced failure for Phase C gate C-1/C-2")
        return real(A, b, method=method, **kwargs)

    monkeypatch.setattr(module, "solve_linear", flaky)


# ---------------------------------------------------------------- 2D Poisson
def _poisson2d_fixture():
    from pytcad.gmsh_mesh import build_diode_mesh
    from pytcad.region_resolver import resolve_regions, resolve_contacts
    from pytcad.unstructured_assembly import (
        build_unstructured_stencil, build_edge_flux_geometry)
    from pytcad.unstructured_poisson import evaluate_doping_at_nodes

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
    return dict(nodes=mesh.nodes, triangles=mesh.triangles, edge_list=edge_list,
               node_areas=node_areas, interior_edges=interior_edges,
               trans_geom=trans_geom, C_phys=C, contacts=contacts)


def test_2d_poisson_fallback_matches_direct_and_is_reported(monkeypatch):
    gmsh = pytest.importorskip("gmsh")
    import pytcad.unstructured_poisson as up_mod

    fx = _poisson2d_fixture()
    psi_direct, scale_direct = up_mod.solve_poisson_equilibrium(
        **fx, opts=NewtonOptions(linsolve="direct"))
    assert scale_direct["linsolve_fallbacks"] == 0

    _force_iterative_failure(monkeypatch, up_mod)
    psi_fb, scale_fb = up_mod.solve_poisson_equilibrium(
        **fx, opts=NewtonOptions(linsolve="gmres"))

    assert np.array_equal(psi_direct, psi_fb), \
        "Gate C-1: 100%-fallback result must equal the all-direct solve"
    assert scale_fb["linsolve_fallbacks"] > 0, \
        "Gate C-2: the fallback must be reported, not silent"


# ---------------------------------------------------------------- 2D DD
def test_2d_dd_fallback_matches_direct_and_is_reported(monkeypatch):
    gmsh = pytest.importorskip("gmsh")
    import pytcad.unstructured_dd as udd_mod

    fx = _poisson2d_fixture()
    bias = {"left_contact": 0.3, "right_contact": 0.0}

    psi_d, n_d, p_d, scale_d, _ = udd_mod.solve_bias(
        fx["nodes"], fx["triangles"], fx["edge_list"], fx["node_areas"],
        fx["interior_edges"], fx["trans_geom"], fx["C_phys"], fx["contacts"],
        bias, opts=NewtonOptions(linsolve="direct"))
    assert scale_d["linsolve_fallbacks"] == 0

    _force_iterative_failure(monkeypatch, udd_mod)
    psi_fb, n_fb, p_fb, scale_fb, _ = udd_mod.solve_bias(
        fx["nodes"], fx["triangles"], fx["edge_list"], fx["node_areas"],
        fx["interior_edges"], fx["trans_geom"], fx["C_phys"], fx["contacts"],
        bias, opts=NewtonOptions(linsolve="gmres"))

    assert np.array_equal(psi_d, psi_fb)
    assert np.array_equal(n_d, n_fb)
    assert np.array_equal(p_d, p_fb)
    assert scale_fb["linsolve_fallbacks"] > 0


# ---------------------------------------------------------------- 3D Poisson
def _mesh3d_fixture():
    from pytcad.gmsh_mesh3d import build_diode_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    import pytcad.unstructured_dd3d as udd3d_mod

    mesh = build_diode_mesh3d(Lx=1.0e-4, Ly=2.5e-5, Lz=1.5e-5, Xj=0.5e-4,
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
    return dict(nodes=mesh.nodes, tets=mesh.tets, edges=edges,
               node_vols=node_vols, trans=trans, C=C, contacts=contacts)


def test_3d_poisson_fallback_matches_direct_and_is_reported(monkeypatch):
    gmsh = pytest.importorskip("gmsh")
    import pytcad.unstructured_dd3d as udd3d_mod

    fx = _mesh3d_fixture()
    psi_d, scale_d = udd3d_mod.solve_poisson_equilibrium3d(
        fx["nodes"], fx["tets"], fx["edges"], fx["node_vols"], fx["trans"],
        fx["C"], fx["contacts"], opts=NewtonOptions(linsolve="direct"))
    assert scale_d["linsolve_fallbacks"] == 0

    _force_iterative_failure(monkeypatch, udd3d_mod)
    psi_fb, scale_fb = udd3d_mod.solve_poisson_equilibrium3d(
        fx["nodes"], fx["tets"], fx["edges"], fx["node_vols"], fx["trans"],
        fx["C"], fx["contacts"], opts=NewtonOptions(linsolve="gmres"))

    assert np.array_equal(psi_d, psi_fb)
    assert scale_fb["linsolve_fallbacks"] > 0


# ---------------------------------------------------------------- 3D DD
def test_3d_dd_fallback_matches_direct_and_is_reported(monkeypatch):
    gmsh = pytest.importorskip("gmsh")
    import pytcad.unstructured_dd3d as udd3d_mod

    fx = _mesh3d_fixture()
    bias = {"left_contact": 0.3, "right_contact": 0.0}

    psi_d, n_d, p_d, scale_d, _ = udd3d_mod.solve_bias3d(
        fx["nodes"], fx["tets"], fx["edges"], fx["node_vols"], fx["trans"],
        fx["C"], fx["contacts"], bias, opts=NewtonOptions(linsolve="direct"))
    assert scale_d["linsolve_fallbacks"] == 0

    _force_iterative_failure(monkeypatch, udd3d_mod)
    psi_fb, n_fb, p_fb, scale_fb, _ = udd3d_mod.solve_bias3d(
        fx["nodes"], fx["tets"], fx["edges"], fx["node_vols"], fx["trans"],
        fx["C"], fx["contacts"], bias, opts=NewtonOptions(linsolve="gmres"))

    assert np.array_equal(psi_d, psi_fb)
    assert np.array_equal(n_d, n_fb)
    assert np.array_equal(p_d, p_fb)
    assert scale_fb["linsolve_fallbacks"] > 0


# ------------------------------------------------- direct-failure still raises
@pytest.mark.parametrize("module_name,func_name,kwargs_builder", [
    ("unstructured_poisson", "solve_poisson_equilibrium", "poisson2d"),
    ("unstructured_dd", "solve_bias", "dd2d"),
])
def test_a_failing_direct_solve_still_raises(monkeypatch, module_name,
                                             func_name, kwargs_builder):
    """The `if opts.linsolve == "direct": raise` guard: when the
    REQUESTED method is already "direct" and it fails, there is nothing
    to fall back to -- the error must propagate, not be swallowed or
    looped on forever."""
    gmsh = pytest.importorskip("gmsh")
    import importlib
    mod = importlib.import_module(f"pytcad.{module_name}")

    def always_fails(A, b, *, method="direct", **kwargs):
        raise LinearSolveError("forced failure -- direct itself fails")

    monkeypatch.setattr(mod, "solve_linear", always_fails)

    fx = _poisson2d_fixture()
    opts = NewtonOptions(linsolve="direct")
    with pytest.raises(LinearSolveError):
        if kwargs_builder == "poisson2d":
            mod.solve_poisson_equilibrium(**fx, opts=opts)
        else:
            mod.solve_bias(fx["nodes"], fx["triangles"], fx["edge_list"],
                           fx["node_areas"], fx["interior_edges"],
                           fx["trans_geom"], fx["C_phys"], fx["contacts"],
                           {"left_contact": 0.3, "right_contact": 0.0},
                           opts=opts)
