"""M21 follow-up -- solution-adaptive refinement, PORTED from adapt.py's
DECISION logic (error indicator -> Doerfler marking -> outer solve/
refine/re-solve loop, same API shape as adapt.py's own adapt_solve_2d)
to the 2D UNSTRUCTURED triangle mesh (unstructured_dd.py).

Reused directly from adapt.py (imported, not re-implemented -- adapt.py
itself is untouched): `combine`, `mark_dorfler`. Both are already mesh-
topology-agnostic (they operate on a flat per-cell array), so nothing
about them needed porting.

PORTED (this module's own code, since adapt.py's own indicator/refine
functions are hard-coded to a tensor-product (Ny, Nx) cell grid and
cannot be reused as-is): per-TRIANGLE error indicators
(`indicator_curvature_tri`, `indicator_log_density_tri`), the 2D
analogues of adapt.py's `indicator_curvature`/`indicator_log_density`
computed per mesh EDGE and reduced to a per-triangle value by the
`max` over the triangle's 3 edges (an honest choice, not adapt.py's
own choice ported verbatim -- there is no "cell" in the 1D/2D
tensor-product sense on an unstructured mesh, only per-edge quantities
and the triangles that own them).

REFINEMENT METHOD (the task's own explicitly-preferred option (b)):
gmsh remeshing driven by a spatially-varying target-size field, NOT
manual triangle bisection. Each pass calls a fresh gmsh session,
rebuilds the SAME two-rectangle diode geometry gmsh_mesh.build_diode_
mesh already validates, embeds an explicit gmsh Point at every marked
triangle's centroid, and adds a Distance(these points)+Threshold field
(MIN-combined with the base junction-distance field) so gmsh's own
Delaunay remesher puts extra resolution exactly at the marked
centroids. This is fully general (works for ANY marked region shape,
not just "near the junction") -- CONFIRMED by this module's own tests,
not merely asserted.

HONEST SCOPE LIMITS, stated per this task's own instructions:

  - 2D ONLY. A 3D (tet-mesh) version was judged out of scope for this
    pass given the same pure-Python assembly cost that already made
    unstructured_dd3d.py's own junction validation incomplete (see
    that module's docstring) -- an adaptive OUTER LOOP would multiply
    that cost by max_passes. Not attempted here rather than delivered
    unvalidated.
  - No mesh-size MONOTONICITY guarantee across passes: gmsh's Delaunay
    remesher is not obligated to preserve every previous node, so a
    triangle far from any newly-marked centroid can occasionally come
    out slightly coarser or finer than the previous pass by chance,
    unlike adapt.py's own bisection refinement (refine_1d/refine_2d/
    refine_3d), which is monotone (never coarsens) by construction.
    Not a correctness bug -- gmsh remeshing from a background field is
    inherently a fresh triangulation each pass -- but a real behavioral
    difference from adapt.py's bisection convergence guarantees, so it
    is stated rather than silently assumed away.
  - Doping (and hence the Debye-length mesh-adequacy check adapt.py's
    own adapt_solve_2d performs before its error-indicator marking) is
    re-evaluated fresh each pass via evaluate_doping_at_nodes on the
    new mesh, but NO Debye-adequacy gate is implemented here -- only
    the error-indicator-driven Doerfler marking. A future session
    wanting exact parity with adapt_solve_2d's two-stage (Debye-first,
    then error-indicator) marking should add it the same way.
"""
import warnings

import numpy as np

from .adapt import combine, mark_dorfler
from .gmsh_mesh import GmshMesh, _extract_current_model, _require_gmsh
from .region_resolver import resolve_regions, resolve_contacts
from .unstructured_assembly import (
    build_unstructured_stencil, build_edge_flux_geometry,
)
from .unstructured_dd import evaluate_doping_at_nodes, solve_bias


def indicator_curvature_tri(mesh, psi):
    """Per-triangle smoothness indicator: max over the triangle's 3
    edges of h_edge^2 * |dpsi/h_edge| = h_edge*|dpsi| -- the 2D-
    unstructured analogue of adapt.py's indicator_curvature (which
    needs a 1D neighbour chain for a genuine second difference; a
    triangle mesh has no such chain, so this uses the FIRST difference
    scaled by edge length instead -- large where psi changes steeply
    over a short distance, e.g. across a depletion region). Normalised
    by the peak |psi| the same way adapt.py's own indicator does.
    """
    nodes_xy = np.asarray(mesh.nodes, dtype=float)[:, :2]
    tri = np.asarray(mesh.triangles, dtype=int)
    psi = np.asarray(psi, dtype=float)
    scale = max(float(np.max(np.abs(psi))), 1e-300)
    out = np.zeros(tri.shape[0])
    for k, (a, b, c) in enumerate(tri):
        vals = []
        for i, j in ((a, b), (b, c), (c, a)):
            h = np.linalg.norm(nodes_xy[j] - nodes_xy[i])
            vals.append(h * abs(psi[j] - psi[i]))
        out[k] = max(vals) / scale
    return out


def indicator_log_density_tri(mesh, n, p):
    """Per-triangle max(|d ln n|, |d ln p|) over the triangle's 3 edges
    -- direct 2D-unstructured analogue of adapt.py's indicator_log_
    density (per-edge |d ln n| there is already mesh-topology-agnostic;
    this just reduces edges to triangles by max, the same convention
    indicator_curvature_tri uses)."""
    tri = np.asarray(mesh.triangles, dtype=int)
    n = np.maximum(np.asarray(n, dtype=float), 1e-300)
    p = np.maximum(np.asarray(p, dtype=float), 1e-300)
    ln_n, ln_p = np.log(n), np.log(p)
    out = np.zeros(tri.shape[0])
    for k, (a, b, c) in enumerate(tri):
        vals = []
        for i, j in ((a, b), (b, c), (c, a)):
            vals.append(max(abs(ln_n[j] - ln_n[i]), abs(ln_p[j] - ln_p[i])))
        out[k] = max(vals)
    return out


def default_indicator_unstructured(mesh, psi, n, p):
    """combine()'s equal-weight union of the curvature and log-density
    triangle indicators -- the unstructured analogue of adapt.py's own
    default_indicator_2d."""
    eta_curv = indicator_curvature_tri(mesh, psi)
    eta_ld = indicator_log_density_tri(mesh, n, p)
    return combine([eta_curv, eta_ld])


def _rebuild_diode_mesh_with_refinement(Lx, Ly, Xj, Nd_scale,
                                        marked_centroids, base_size_min,
                                        base_size_max, refine_size):
    """Rebuild gmsh_mesh.build_diode_mesh's exact two-rectangle
    geometry, but with an EXTRA Distance(points)+Threshold field seeded
    at `marked_centroids` (physical (x, y) pairs) so gmsh's remesher
    puts `refine_size`-scale elements there, MIN-combined with the
    junction's own base field (so refinement only ever adds resolution,
    never removes the junction's existing floor).

    `marked_centroids`: (K, 2) array; K=0 reproduces build_diode_mesh's
    plain junction-only sizing (the first pass, before anything is
    marked).
    """
    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("diode2d_adapt")
        occ = gmsh.model.occ
        p_rect = occ.addRectangle(0.0, 0.0, 0, Xj, Ly)
        n_rect = occ.addRectangle(Xj, 0.0, 0, Lx - Xj, Ly)
        occ.synchronize()
        occ.fragment([(2, p_rect)], [(2, n_rect)])
        occ.synchronize()

        surfaces = gmsh.model.getEntities(2)
        p_tag = n_tag = None
        for dim, tag in surfaces:
            com = occ.getCenterOfMass(dim, tag)
            if com[0] < Xj:
                p_tag = tag
            else:
                n_tag = tag
        gmsh.model.addPhysicalGroup(2, [p_tag], name="p_region")
        gmsh.model.addPhysicalGroup(2, [n_tag], name="n_region")

        curves = gmsh.model.getEntities(1)
        left_curve = right_curve = None
        for dim, tag in curves:
            com = occ.getCenterOfMass(dim, tag)
            if abs(com[0] - 0.0) < 1e-12:
                left_curve = tag
            elif abs(com[0] - Lx) < 1e-12:
                right_curve = tag
        gmsh.model.addPhysicalGroup(1, [left_curve], name="left_contact")
        gmsh.model.addPhysicalGroup(1, [right_curve], name="right_contact")

        gmsh.model.mesh.field.add("Distance", 1)
        junction_curves = [c for d, c in curves
                          if abs(occ.getCenterOfMass(d, c)[0] - Xj) < 1e-12]
        gmsh.model.mesh.field.setNumbers(1, "CurvesList", junction_curves)
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", base_size_min)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", base_size_max)
        gmsh.model.mesh.field.setNumber(2, "DistMin", 2.0 * base_size_min)
        gmsh.model.mesh.field.setNumber(2, "DistMax", 15.0 * base_size_min)

        field_ids = [2]
        if len(marked_centroids) > 0:
            pt_tags = []
            for x, y in marked_centroids:
                pt = occ.addPoint(float(x), float(y), 0.0)
                pt_tags.append(pt)
            occ.synchronize()
            # embed each point in whichever surface actually contains it
            for pt, (x, y) in zip(pt_tags, marked_centroids):
                target = p_tag if x < Xj else n_tag
                gmsh.model.mesh.embed(0, [pt], 2, target)
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

        gmsh.model.mesh.generate(2)
        return _extract_current_model()
    finally:
        gmsh.finalize()


def adapt_solve_unstructured_2d(*, Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4,
                                Nd_scale=1e16, doping_by_region,
                                bias, material=None, T=300.0,
                                indicator=None, max_passes=4, tol=1e-3,
                                theta=0.5, refine_shrink=0.4, opts=None):
    """Outer solve/refine/re-solve loop for the 2D unstructured diode
    fixture -- API shape mirrors adapt.py's own adapt_solve_2d (a
    `history` list of per-pass dicts, a `cause` string, unconditional
    prev-QoI update, tol-gated stop). QoI is the left-contact terminal
    current, adapt.py's own `_qoi_2d`-equivalent choice for a device
    under bias (built-in potential would be the natural equilibrium-
    only choice; this signature always applies `bias`).

    Returns (psi, n, p, scale, terminal_current, mesh, history).

    refine_shrink: each pass's marked-triangle target size is
    `refine_shrink` times the CURRENT mesh's own median marked-triangle
    edge length -- a simple geometric-shrink schedule (not adapt.py's
    ratio=2.0 bisection factor, since gmsh remeshing has no discrete
    "bisect" step to mirror exactly; stated, not hidden).
    """
    from .materials import SILICON
    material = material or SILICON
    opts = opts
    L_D_scale = Nd_scale  # sizing reference, same as build_diode_mesh's own

    from .mesh import debye_length
    base_min = 0.5 * debye_length(L_D_scale)
    base_max = 2e-5

    marked_centroids = np.zeros((0, 2))
    refine_size = base_min
    history = []
    mesh = None
    result = None
    prev_q = None
    cause = "max_passes"

    for it in range(max_passes):
        mesh = _rebuild_diode_mesh_with_refinement(
            Lx, Ly, Xj, Nd_scale, marked_centroids, base_min, base_max,
            refine_size)

        regions = resolve_regions(mesh)
        contacts = resolve_contacts(mesh)
        edge_list, node_areas = build_unstructured_stencil(
            mesh.nodes, mesh.triangles)
        interior_edges, trans_geom = build_edge_flux_geometry(
            mesh.nodes, mesh.triangles, edge_list)
        region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
        for name, idx in regions.items():
            region_of_triangle[idx] = name
        C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                     region_of_triangle, doping_by_region)

        psi, n, p, scale, I = solve_bias(
            mesh.nodes, mesh.triangles, edge_list, node_areas,
            interior_edges, trans_geom, C, contacts, bias=bias,
            material=material, T=T, opts=opts)
        result = (psi, n, p, scale, I)

        q = float(next(iter(I.values())))
        delta = np.inf if prev_q is None else abs(q - prev_q) / max(abs(q), 1e-300)
        entry = {"pass": it, "nodes": mesh.n_nodes(),
                "triangles": mesh.n_triangles(), "qoi": q, "delta": delta,
                "marked": int(marked_centroids.shape[0]), "cause": None}
        history.append(entry)

        if prev_q is not None and delta <= tol:
            cause = "converged"
            break
        prev_q = q

        eta = (indicator(mesh, psi, n, p) if indicator is not None
              else default_indicator_unstructured(mesh, psi, n, p))
        marked = mark_dorfler(eta, theta)
        if marked.size == 0:
            cause = "converged"
            break

        nodes_xy = mesh.nodes[:, :2]
        tri = mesh.triangles[marked]
        marked_centroids = nodes_xy[tri].mean(axis=1)
        edge_lens = []
        for a, b, c in tri:
            for i, j in ((a, b), (b, c), (c, a)):
                edge_lens.append(np.linalg.norm(nodes_xy[j] - nodes_xy[i]))
        refine_size = max(refine_shrink * float(np.median(edge_lens)),
                          1e-3 * base_min)
    else:
        cause = "max_passes"

    for entry in history:
        entry["cause"] = cause

    if cause == "max_passes":
        warnings.warn(
            f"adaptive unstructured refinement stopped on the pass limit "
            f"({max_passes} passes); QoI had not converged to tol={tol:g} "
            f"(last delta {history[-1]['delta']:.3e})")

    psi, n, p, scale, I = result
    return psi, n, p, scale, I, mesh, history
