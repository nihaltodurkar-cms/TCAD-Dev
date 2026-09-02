"""M21 follow-up 3 (Task A) -- solution-adaptive refinement for the 3D
UNSTRUCTURED tetrahedral mesh (unstructured_dd3d.py), the 3D sibling of
adapt_unstructured.py -- same outer-loop shape (solve -> per-cell
indicator -> Doerfler mark -> gmsh remesh with an embedded-point size
field -> re-solve), same reused `combine()`/`mark_dorfler()` from
adapt.py, same INDICATOR_REGISTRY/compute_indicator machinery
(field/doping/current/solver-residual/user-defined) as
adapt_unstructured.py's own Task B addition -- ported one dimension
further: per-TRIANGLE indicators -> per-TET, gmsh 2D Distance/Threshold
fields seeded at marked triangle CENTROIDS -> 3D fields seeded at
marked tet centroids, `gmsh_mesh.build_diode_mesh`'s two-rectangle
geometry -> `gmsh_mesh3d.build_diode_mesh3d`'s two-box geometry.

HONEST SCALE STATEMENT (read this before using this module for
anything beyond what it was actually validated at):

  3D re-meshing + re-solving in a loop is expensive -- unstructured_
  assembly3d.py's own docstring already flags its pure-Python, per-edge
  circumcenter geometry as O(N_tets) with a non-trivial per-tet
  constant, and unstructured_dd3d.py's own base (non-adaptive) solve
  is markedly heavier than the 2D module's. This module's own tests
  (tests/test_adapt_unstructured3d.py) therefore use a DELIBERATELY
  SMALL validation geometry: an 8e-5 x 2.5e-5 x 2e-5 cm box
  (Lx x Ly x Lz), Xj=4e-5, Nd_scale=1e16 -- ~300 nodes / ~1000 tets at
  pass 0, growing to a few thousand tets by the last of 2-3 refinement
  passes, each pass's solve taking well under a second on this sandbox.
  This is enough to exercise real refinement DECISIONS (the marked
  region is a small, spatially concentrated subset of tets, not "all of
  them" or "none of them" -- see the indicator/marking tests) and a
  real outer-loop convergence check, but it is NOT validated at the
  thousands-of-nodes-per-pass scale a real 3D device simulation would
  use, and NOT validated for more than 3 refinement passes. A future
  session wanting a bigger validated scale should budget accordingly
  (each doubling of linear resolution multiplies the tet count, and
  hence per-pass solve cost, by roughly 8x in 3D) -- do not assume this
  module's behavior extrapolates to a domain 10-100x larger without
  re-validating.

  Indicator/marking correctness (Task B's field/doping/current/user-
  defined/solver-residual per-tet indicators) IS validated at this
  small scale exactly the way the 2D module validates its own
  indicators -- concentration near a known physical feature (the
  junction plane) is a scale-independent structural property, so this
  is a meaningful check even though the OUTER adaptive LOOP itself is
  only lightly validated (2-3 passes).

  Warm-starting (Task C.1) IS ported and tested the same way as the 2D
  module's (nearest-neighbour interpolation of the previous pass's
  converged psi/n/p onto the new mesh's nodes, via solve_bias3d's own
  `init=` kwarg -- see unstructured_dd3d.solve_bias3d's docstring).
"""
import warnings

import numpy as np

from .adapt import combine, mark_dorfler
from .gmsh_mesh3d import GmshMesh3D, _extract_current_model3d, _require_gmsh
from .unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d,
)
from .unstructured_dd3d import evaluate_doping_at_nodes3d, solve_bias3d


# ----------------------------------------------------------------------
#  Gradient primitive and PER-TET indicators (Task B ported to 3D)
# ----------------------------------------------------------------------
def _tet_gradient(mesh, values):
    """Per-tet CONSTANT gradient of a P1 scalar field -- 3D analogue of
    adapt_unstructured._tri_gradient (3x3 linear solve per tet instead
    of a 2x2 one). A degenerate (near-zero-volume) tet contributes a
    zero gradient rather than raising. Returns (n_tet, 3) array.
    """
    nodes_xyz = np.asarray(mesh.nodes, dtype=float)[:, :3]
    tet = np.asarray(mesh.tets, dtype=int)
    values = np.asarray(values, dtype=float)
    a = nodes_xyz[tet[:, 0]]
    e1 = nodes_xyz[tet[:, 1]] - a
    e2 = nodes_xyz[tet[:, 2]] - a
    e3 = nodes_xyz[tet[:, 3]] - a
    fa = values[tet[:, 0]]
    db = values[tet[:, 1]] - fa
    dc = values[tet[:, 2]] - fa
    dd = values[tet[:, 3]] - fa
    grad = np.zeros((tet.shape[0], 3))
    for k in range(tet.shape[0]):
        M = np.array([e1[k], e2[k], e3[k]])
        rhs = np.array([db[k], dc[k], dd[k]])
        try:
            grad[k] = np.linalg.solve(M, rhs)
        except np.linalg.LinAlgError:
            grad[k] = 0.0
    return grad


def indicator_curvature_tet(mesh, psi):
    """Per-tet smoothness indicator: max over the tet's 6 edges of
    h_edge*|dpsi| -- 3D analogue of adapt_unstructured.
    indicator_curvature_tri. Normalised by peak |psi|."""
    nodes_xyz = np.asarray(mesh.nodes, dtype=float)[:, :3]
    tet = np.asarray(mesh.tets, dtype=int)
    psi = np.asarray(psi, dtype=float)
    scale = max(float(np.max(np.abs(psi))), 1e-300)
    EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    out = np.zeros(tet.shape[0])
    for k, verts in enumerate(tet):
        vals = []
        for a, b in EDGES:
            i, j = verts[a], verts[b]
            h = np.linalg.norm(nodes_xyz[j] - nodes_xyz[i])
            vals.append(h * abs(psi[j] - psi[i]))
        out[k] = max(vals) / scale
    return out


def indicator_log_density_tet(mesh, n, p):
    """Per-tet max(|d ln n|, |d ln p|) over the tet's 6 edges -- 3D
    analogue of adapt_unstructured.indicator_log_density_tri."""
    tet = np.asarray(mesh.tets, dtype=int)
    n = np.maximum(np.asarray(n, dtype=float), 1e-300)
    p = np.maximum(np.asarray(p, dtype=float), 1e-300)
    ln_n, ln_p = np.log(n), np.log(p)
    EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    out = np.zeros(tet.shape[0])
    for k, verts in enumerate(tet):
        vals = []
        for a, b in EDGES:
            i, j = verts[a], verts[b]
            vals.append(max(abs(ln_n[j] - ln_n[i]), abs(ln_p[j] - ln_p[i])))
        out[k] = max(vals)
    return out


def default_indicator_unstructured3d(mesh, psi, n, p):
    """combine()'s equal-weight union of the curvature and log-density
    per-tet indicators -- 3D analogue of adapt_unstructured.
    default_indicator_unstructured."""
    eta_curv = indicator_curvature_tet(mesh, psi)
    eta_ld = indicator_log_density_tet(mesh, n, p)
    return combine([eta_curv, eta_ld])


def indicator_field_tet(mesh, psi):
    """FIELD indicator: |E| ~ |grad(psi)| per tet via `_tet_gradient`.
    3D analogue of adapt_unstructured.indicator_field_tri."""
    grad = _tet_gradient(mesh, psi)
    mag = np.linalg.norm(grad, axis=1)
    peak = max(float(np.max(mag)), 1e-300)
    return mag / peak


def indicator_doping_tet(mesh, C):
    """DOPING indicator: |grad(log10(max(|C|,floor)))| per tet. 3D
    analogue of adapt_unstructured.indicator_doping_tri."""
    C = np.asarray(C, dtype=float)
    floor = max(1.0, 1e-6 * float(np.max(np.abs(C))))
    log_absC = np.log10(np.maximum(np.abs(C), floor))
    grad = _tet_gradient(mesh, log_absC)
    mag = np.linalg.norm(grad, axis=1)
    peak = max(float(np.max(mag)), 1e-300)
    return mag / peak


def indicator_current_tet(mesh, solve_state):
    """CURRENT indicator: |Jn+Jp| per tet, same drift+diffusion
    continuum reconstruction as adapt_unstructured.indicator_current_tri
    (uniform mobility, `_tet_gradient`-reconstructed grad(psi)/grad(n)/
    grad(p); magnitude only, no divergence-residual variant -- same
    deferred scope as the 2D function). `solve_state`: dict with "psi",
    "n", "p" (physical units), "material", optional "T"."""
    from .device import thermal_voltage
    from .constants import Q
    material = solve_state["material"]
    T = solve_state.get("T", 300.0)
    VT = thermal_voltage(T)
    psi_phys = np.asarray(solve_state["psi"], dtype=float)
    n_phys = np.asarray(solve_state["n"], dtype=float)
    p_phys = np.asarray(solve_state["p"], dtype=float)

    tet = np.asarray(mesh.tets, dtype=int)
    n_tet_avg = n_phys[tet].mean(axis=1)
    p_tet_avg = p_phys[tet].mean(axis=1)

    grad_psi = _tet_gradient(mesh, psi_phys)
    grad_n = _tet_gradient(mesh, n_phys)
    grad_p = _tet_gradient(mesh, p_phys)

    mu_n, mu_p = material.mu_n_max, material.mu_p_max
    Dn, Dp = mu_n * VT, mu_p * VT
    E = -grad_psi
    Jn = Q * mu_n * n_tet_avg[:, None] * E + Q * Dn * grad_n
    Jp = Q * mu_p * p_tet_avg[:, None] * E - Q * Dp * grad_p
    mag = np.linalg.norm(Jn + Jp, axis=1)
    peak = max(float(np.max(mag)), 1e-300)
    return mag / peak


def indicator_solver_residual_tet(mesh, residual_node_history, tail_frac=0.5):
    """SOLVER-RESIDUAL indicator: same "residual stayed large longest"
    signal as adapt_unstructured.indicator_solver_residual_tri, reduced
    to per-tet by max over the tet's 4 vertices."""
    hist = np.asarray(residual_node_history, dtype=float)
    tet = np.asarray(mesh.tets, dtype=int)
    if hist.ndim != 2 or hist.shape[0] < 2:
        return np.zeros(tet.shape[0])
    n_iter = hist.shape[0]
    tail_start = max(int(np.ceil((1.0 - tail_frac) * n_iter)), 0)
    per_node = hist[tail_start:].mean(axis=0)
    per_tet = per_node[tet].max(axis=1)
    peak = max(float(np.max(per_tet)), 1e-300)
    return per_tet / peak


INDICATOR_REGISTRY3D = {
    "curvature": lambda mesh, s: indicator_curvature_tet(mesh, s["psi"]),
    "log_density": lambda mesh, s: indicator_log_density_tet(mesh, s["n"], s["p"]),
    "field": lambda mesh, s: indicator_field_tet(mesh, s["psi"]),
    "doping": lambda mesh, s: indicator_doping_tet(mesh, s["C"]),
    "current": lambda mesh, s: indicator_current_tet(mesh, s),
    "solver_residual": lambda mesh, s: indicator_solver_residual_tet(
        mesh, s["residual_node_history"]),
}


def compute_indicator3d(mesh, solve_state, kinds=("curvature", "log_density"),
                        weights=None, user_fns=None):
    """3D analogue of adapt_unstructured.compute_indicator -- see that
    function's docstring for the full solve_state key vocabulary and
    combine() semantics (identical here, mesh.tets instead of
    mesh.triangles)."""
    mats = []
    for k in kinds:
        if k not in INDICATOR_REGISTRY3D:
            raise ValueError(
                f"unknown indicator kind {k!r}; known kinds: "
                f"{sorted(INDICATOR_REGISTRY3D)}")
        mats.append(np.asarray(INDICATOR_REGISTRY3D[k](mesh, solve_state),
                               dtype=float))
    for fn in (user_fns or []):
        mats.append(np.asarray(fn(mesh, solve_state), dtype=float))
    if not mats:
        raise ValueError("compute_indicator3d needs at least one kind or user_fn")
    return combine(mats, weights=weights)


# ----------------------------------------------------------------------
#  gmsh remeshing driven by a spatially-varying 3D target-size field
# ----------------------------------------------------------------------
def _rebuild_diode_mesh3d_with_refinement(Lx, Ly, Lz, Xj, marked_centroids,
                                          base_size_min, base_size_max,
                                          refine_size):
    """3D analogue of adapt_unstructured._rebuild_diode_mesh_with_
    refinement: rebuilds gmsh_mesh3d.build_diode_mesh3d's exact two-box
    geometry, with an extra Distance(points)+Threshold field seeded at
    `marked_centroids` (physical (x, y, z) triples), MIN-combined with
    the junction's own base field.
    """
    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("diode3d_adapt")
        occ = gmsh.model.occ
        p_box = occ.addBox(0.0, 0.0, 0.0, Xj, Ly, Lz)
        n_box = occ.addBox(Xj, 0.0, 0.0, Lx - Xj, Ly, Lz)
        occ.synchronize()
        occ.fragment([(3, p_box)], [(3, n_box)])
        occ.synchronize()

        vols = gmsh.model.getEntities(3)
        p_tag = n_tag = None
        for dim, tag in vols:
            com = occ.getCenterOfMass(dim, tag)
            if com[0] < Xj:
                p_tag = tag
            else:
                n_tag = tag
        gmsh.model.addPhysicalGroup(3, [p_tag], name="p_region")
        gmsh.model.addPhysicalGroup(3, [n_tag], name="n_region")

        faces = gmsh.model.getEntities(2)
        left_face = right_face = None
        junction_faces = []
        for dim, tag in faces:
            com = occ.getCenterOfMass(dim, tag)
            if abs(com[0] - 0.0) < 1e-12:
                left_face = tag
            elif abs(com[0] - Lx) < 1e-12:
                right_face = tag
            if abs(com[0] - Xj) < 1e-9:
                junction_faces.append(tag)
        gmsh.model.addPhysicalGroup(2, [left_face], name="left_contact")
        gmsh.model.addPhysicalGroup(2, [right_face], name="right_contact")

        gmsh.model.mesh.field.add("Distance", 1)
        gmsh.model.mesh.field.setNumbers(1, "SurfacesList", junction_faces)
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", base_size_min)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", base_size_max)
        gmsh.model.mesh.field.setNumber(2, "DistMin", 3.0 * base_size_min)
        gmsh.model.mesh.field.setNumber(2, "DistMax", 6.0 * base_size_min)

        field_ids = [2]
        if len(marked_centroids) > 0:
            pt_tags = []
            for x, y, z in marked_centroids:
                pt = occ.addPoint(float(x), float(y), float(z))
                pt_tags.append(pt)
            occ.synchronize()
            for pt, (x, y, z) in zip(pt_tags, marked_centroids):
                target = p_tag if x < Xj else n_tag
                gmsh.model.mesh.embed(0, [pt], 3, target)
            gmsh.model.mesh.field.add("Distance", 3)
            gmsh.model.mesh.field.setNumbers(3, "PointsList", pt_tags)
            gmsh.model.mesh.field.add("Threshold", 4)
            gmsh.model.mesh.field.setNumber(4, "InField", 3)
            gmsh.model.mesh.field.setNumber(4, "SizeMin", refine_size)
            gmsh.model.mesh.field.setNumber(4, "SizeMax", base_size_max)
            gmsh.model.mesh.field.setNumber(4, "DistMin", refine_size)
            gmsh.model.mesh.field.setNumber(4, "DistMax", 8.0 * refine_size)
            field_ids.append(4)

        if len(field_ids) > 1:
            gmsh.model.mesh.field.add("Min", 5)
            gmsh.model.mesh.field.setNumbers(5, "FieldsList", field_ids)
            gmsh.model.mesh.field.setAsBackgroundMesh(5)
        else:
            gmsh.model.mesh.field.setAsBackgroundMesh(2)

        gmsh.model.mesh.generate(3)
        return _extract_current_model3d()
    finally:
        gmsh.finalize()


def _interpolate_nearest3d(old_nodes_xyz, old_values, new_nodes_xyz):
    """3D analogue of adapt_unstructured._interpolate_nearest."""
    from scipy.spatial import cKDTree
    tree = cKDTree(old_nodes_xyz)
    _, idx = tree.query(new_nodes_xyz)
    return np.asarray(old_values)[idx]


def adapt_solve_unstructured_3d(*, Lx=8.0e-5, Ly=2.5e-5, Lz=2.0e-5, Xj=4.0e-5,
                                Nd_scale=1e16, doping_by_region,
                                bias, material=None, T=300.0,
                                indicator=None, indicator_kinds=None,
                                indicator_weights=None, user_indicator_fns=None,
                                max_passes=3, tol=1e-3, theta=0.5,
                                refine_shrink=0.4, opts=None, warm_start=True):
    """Outer solve/refine/re-solve loop for the 3D unstructured diode
    fixture -- 3D analogue of adapt_unstructured.
    adapt_solve_unstructured_2d, identical API shape and indicator/
    warm-start options (see that function's docstring for the full
    parameter reference; not repeated here).

    DEFAULT GEOMETRY is deliberately the small validated scale this
    module's own docstring states (~300 nodes at pass 0) -- NOT
    unstructured_dd3d.py's own default diode geometry, which is too
    expensive for a multi-pass adaptive loop to re-mesh/re-solve
    `max_passes` times in reasonable sandbox time. Passing a larger
    Lx/Ly/Lz/smaller Nd_scale is possible but UNVALIDATED past this
    module's own test scale -- see the module docstring.

    Returns (psi, n, p, scale, terminal_current, mesh, history).
    """
    from .materials import SILICON
    material = material or SILICON
    from .mesh import debye_length
    base_min = 1.5 * debye_length(Nd_scale)
    base_max = 0.5 * min(Ly, Lz)

    marked_centroids = np.zeros((0, 3))
    refine_size = base_min
    history = []
    mesh = None
    result = None
    prev_q = None
    cause = "max_passes"
    prev_mesh_nodes = None
    prev_psi = prev_n = prev_p = None
    needs_residual = indicator_kinds is not None and "solver_residual" in indicator_kinds

    for it in range(max_passes):
        mesh = _rebuild_diode_mesh3d_with_refinement(
            Lx, Ly, Lz, Xj, marked_centroids, base_min, base_max, refine_size)

        edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
        edges, trans_geom = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
        region_of_tet = np.empty(mesh.n_tets(), dtype=object)
        for name, idx in mesh.volume_tags.items():
            region_of_tet[idx] = name
        C = evaluate_doping_at_nodes3d(mesh.nodes, mesh.tets, region_of_tet,
                                       doping_by_region)
        contacts = {"left_contact": mesh.face_tags["left_contact"],
                   "right_contact": mesh.face_tags["right_contact"]}

        init = None
        if warm_start and prev_mesh_nodes is not None:
            init = dict(
                psi=_interpolate_nearest3d(prev_mesh_nodes, prev_psi, mesh.nodes[:, :3]),
                n=_interpolate_nearest3d(prev_mesh_nodes, prev_n, mesh.nodes[:, :3]),
                p=_interpolate_nearest3d(prev_mesh_nodes, prev_p, mesh.nodes[:, :3]))

        solve_kwargs = dict(material=material, T=T, opts=opts, init=init)
        if needs_residual:
            psi, n, p, scale, I, diag = solve_bias3d(
                mesh.nodes, mesh.tets, edges, node_vols, trans_geom, C,
                contacts, bias=bias, return_diagnostics=True, **solve_kwargs)
        else:
            psi, n, p, scale, I = solve_bias3d(
                mesh.nodes, mesh.tets, edges, node_vols, trans_geom, C,
                contacts, bias=bias, **solve_kwargs)
            diag = None
        result = (psi, n, p, scale, I)

        prev_mesh_nodes = mesh.nodes[:, :3].copy()
        prev_psi, prev_n, prev_p = psi.copy(), n.copy(), p.copy()

        q = float(next(iter(I.values())))
        delta = np.inf if prev_q is None else abs(q - prev_q) / max(abs(q), 1e-300)
        entry = {"pass": it, "nodes": mesh.n_nodes(), "tets": mesh.n_tets(),
                "qoi": q, "delta": delta,
                "marked": int(marked_centroids.shape[0]), "cause": None,
                "n_newton_iter": (diag["n_iter"] if diag is not None else None)}
        history.append(entry)

        if prev_q is not None and delta <= tol:
            cause = "converged"
            break
        prev_q = q

        if indicator is not None:
            eta = indicator(mesh, psi, n, p)
        elif indicator_kinds is not None:
            solve_state = dict(
                psi=psi * scale["VT"], n=n * scale["Ns"], p=p * scale["Ns"],
                C=C, material=material, T=T)
            if diag is not None:
                solve_state["residual_node_history"] = diag["residual_node_history"]
            eta = compute_indicator3d(mesh, solve_state, kinds=indicator_kinds,
                                      weights=indicator_weights,
                                      user_fns=user_indicator_fns)
        else:
            eta = default_indicator_unstructured3d(mesh, psi, n, p)
        marked = mark_dorfler(eta, theta)
        if marked.size == 0:
            cause = "converged"
            break

        nodes_xyz = mesh.nodes[:, :3]
        tet = mesh.tets[marked]
        marked_centroids = nodes_xyz[tet].mean(axis=1)
        edge_lens = []
        EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
        for verts in tet:
            for a, b in EDGES:
                i, j = verts[a], verts[b]
                edge_lens.append(np.linalg.norm(nodes_xyz[j] - nodes_xyz[i]))
        refine_size = max(refine_shrink * float(np.median(edge_lens)),
                          1e-3 * base_min)
    else:
        cause = "max_passes"

    for entry in history:
        entry["cause"] = cause

    if cause == "max_passes":
        warnings.warn(
            f"adaptive unstructured3d refinement stopped on the pass "
            f"limit ({max_passes} passes); QoI had not converged to "
            f"tol={tol:g} (last delta {history[-1]['delta']:.3e})")

    psi, n, p, scale, I = result
    return psi, n, p, scale, I, mesh, history
