"""M26 -- extrude a pytcad.process2d 2D process cross-section into a 3D
tri-gate FinFET unstructured tet mesh.

This is the piece of M26's own spec ("FinFET/GAA templates built as
extruded 2D process output") that `pytcad/finfet3d.py` explicitly did
NOT attempt (that module builds a structured tensor-product FinFET
directly from closed-form doping, not from process2d at all). This
module closes that gap on the UNSTRUCTURED (tet) mesh path, paired
with `unstructured_dd3d.py`'s new gate/Robin BC support.

HONEST SCOPE STATEMENT:

  * `pytcad.process2d`'s own convention (see that module's docstring)
    is a per-column "string model": a mask-driven etch produces a
    height profile that is PIECEWISE CONSTANT across each masked
    region (no conformal sidewall slope, no corner rounding). As of
    M35-S6 (2026-09-18), `_staircase_face` builds the REAL per-column
    staircase surface within each of the three x-regions (source/gate/
    drain) directly from `geom.surface_um`/`geom.x` -- a more complex
    in-region profile (e.g. a second etch step within the gate region)
    is now reproduced exactly, not flattened to a regional median. This
    is still NOT a general polyline/conformal-slope extrusion (no
    sloped sidewalls, no corner rounding -- process2d's string model
    has neither to extrude in the first place), and it does not extend
    to a genuinely 3D (z-varying) surface -- that needs M35-S5's 3D
    level set meshed directly, which this function does not do.
  * Doping is UNIFORM per region (source/gate/drain), each a fixed
    concentration supplied by the caller -- this function does NOT
    extrude a 2D process2d IMPLANT array (a smoothly-varying 2D doping
    field); it reuses unstructured_dd3d.evaluate_doping_at_nodes3d's
    existing per-region-constant convention (the same one
    gmsh_mesh3d.build_diode_mesh3d already uses). Extruding an actual
    process2d implant profile into 3D doping remains future work.
  * The tri-gate wrap (top + two sidewalls) is registered as ONE
    combined "gate" face group (concatenated, not three separate
    `gates` dict entries) -- see unstructured_assembly3d.
    boundary_face_node_weights3d's own docstring for why: the top
    face and each sidewall share an edge at the fin's top corner, and
    registering them separately would double-count that shared edge's
    oxide capacitance.
  * CONVERGENCE, stated honestly: the resulting mesh's Poisson-only
    equilibrium solve (`unstructured_dd3d.solve_poisson_equilibrium3d`)
    converges cleanly (confirmed in tests/test_m26_finfet3d.py). The
    fully COUPLED drift-diffusion bias solve
    (`unstructured_dd3d.solve_bias3d`), applied directly from V=0 to a
    real n+/p-/n+ source/gate/drain doping contrast in one Newton call
    (no voltage ramping/continuation), was measured to converge slowly
    or not at all within a few hundred iterations on a first-pass tet
    mesh at typical doping contrasts (1e18/1e17) -- current
    conservation (source = -drain) still held at every measured point,
    so the iterate was tracking a physically sensible trajectory, it
    simply didn't reach this module's tight `tol_update` within a
    bounded iteration count. Robust convergence here needs either a
    voltage-ramped/warm-started bias sweep (the same pattern
    finfet3d.py's own `id_vg_sweep_3d` already uses successfully on
    the STRUCTURED path) or continuation/damping improvements to the
    tet-mesh Newton loop itself -- both are disclosed future work, not
    silently glossed over.
  * M35-S6 (2026-09-18) added `sample_doping_3d_from_process2d`, which
    replaces the uniform-per-region doping constant above with a REAL
    2D `process2d.implant_2d` field, bilinearly interpolated at each
    node's (x,y) and extruded (z-independent) -- a genuine improvement
    over the per-region constant, but it is still an EXTRUSION of a 2D
    field, not a simulated 3D implant, and it is opt-in (the original
    `evaluate_doping_at_nodes3d` per-region-constant path is untouched
    and still what `build_finfet_mesh3d_from_process2d` itself uses).
    The MEDIAN-height geometry flattening described above was NOT
    fixed in the same pass -- a real (non-flattened) 3D geometry needs
    either a genuine polyline/CAD surface built from `geom.surface_um`
    or M35-S5's 3D level set meshed directly, both deferred as a
    separate, larger piece of work (cost-driven cut, recorded in
    M35-3D-PROCESS-PLAN.md section 16).
"""
import numpy as np


def sample_doping_3d_from_process2d(nodes, mesh_x, mesh_y, C):
    """M35-S6 (doping half only -- see module docstring's honesty
    clause): per-node net doping [cm^-3] for a 3D tet mesh, sampled
    from a REAL 2D `process2d.implant_2d` field instead of one uniform
    constant per region.

    nodes        : (N,3) mesh node coordinates [cm]; only (x,y) are
                   used.
    mesh_x, mesh_y, C : exactly `process2d.implant_2d`'s own inputs/
                   output convention (C[j,i] at (mesh_y[j], mesh_x[i])).

    This EXTRUDES the real 2D field along z (bilinear interpolation at
    each node's own (x,y), ignoring its z) -- it does not simulate a
    genuinely z-varying 3D implant, since no 3D implant physics is
    built here or claimed. Nodes outside the implant grid's (x,y) span
    are clamped to the nearest edge value rather than raising, since a
    tet mesh's node coordinates need not land exactly inside that span.
    """
    from scipy.interpolate import RegularGridInterpolator
    nodes = np.asarray(nodes, dtype=float)
    mesh_x = np.asarray(mesh_x, dtype=float)
    mesh_y = np.asarray(mesh_y, dtype=float)
    interp = RegularGridInterpolator((mesh_y, mesh_x), np.asarray(C, dtype=float))
    x_clamped = np.clip(nodes[:, 0], mesh_x.min(), mesh_x.max())
    y_clamped = np.clip(nodes[:, 1], mesh_y.min(), mesh_y.max())
    return interp(np.column_stack([y_clamped, x_clamped]))


def _require_gmsh():
    try:
        import gmsh  # noqa: F401
        return gmsh
    except ImportError as exc:
        raise ImportError(
            "this feature requires the optional 'gmsh' package "
            f"(pip install gmsh): {exc}") from exc


def _staircase_face(occ, x_vals, top_vals, x_lo, x_hi, y_bottom):
    """A closed 2D OCC face bounded below by y=y_bottom and above by the
    REAL piecewise-constant staircase through (x_vals, top_vals) --
    process2d's own string-model convention (each column has its own
    constant height; adjacent columns can differ arbitrarily) -- rather
    than one flat top at the region's median height. Consecutive equal-
    height samples collapse into one run (avoids zero-length/degenerate
    edges); the first/last sample's x is snapped to the region's exact
    (x_lo, x_hi) boundary so adjacent regions still fragment cleanly.

    M35-S6 (2026-09-18): replaces the earlier `occ.addRectangle`-per-
    region flat-top approximation this module used through S5's first
    pass -- see the module's own honesty-clause docstring for the
    record of what this fixes."""
    xs = np.asarray(x_vals, dtype=float).copy()
    ys = np.asarray(top_vals, dtype=float)
    xs[0] = x_lo
    xs[-1] = x_hi

    top_pts = [(xs[0], ys[0])]
    cur_y = ys[0]
    for i in range(1, xs.size):
        if ys[i] != cur_y:
            top_pts.append((xs[i], cur_y))     # end of the previous flat run
            top_pts.append((xs[i], ys[i]))     # start of the new one
            cur_y = ys[i]
    top_pts.append((xs[-1], cur_y))

    p_bl = occ.addPoint(x_lo, y_bottom, 0.0)
    p_br = occ.addPoint(x_hi, y_bottom, 0.0)
    top_tags = [occ.addPoint(px, py, 0.0) for px, py in top_pts]

    lines = [occ.addLine(p_bl, p_br), occ.addLine(p_br, top_tags[-1])]
    for k in range(len(top_tags) - 1, 0, -1):
        lines.append(occ.addLine(top_tags[k], top_tags[k - 1]))
    lines.append(occ.addLine(top_tags[0], p_bl))

    loop = occ.addCurveLoop(lines)
    return occ.addPlaneSurface([loop])


def build_finfet_mesh3d_from_process2d(geom, Wfin, Lsd, Lg, body_depth_um=0.2,
                                       mesh_size_cm=None):
    """Extrude a process2d ProcessGeometry2D's fin cross-section into a
    3D tri-gate FinFET tet mesh.

    geom       : pytcad.process2d.ProcessGeometry2D, already etched so
                 its surface_um(x) profile is raised over the gate
                 region relative to source/drain (e.g. via
                 `process2d.etch(flat_geom, depth_um, mask=~fin_mask)`).
    Wfin       : fin width (z-extent) [cm].
    Lsd, Lg    : source/drain and gate x-extents [cm] -- must match how
                 `geom`'s mask was built (geom.x spans [0, 2*Lsd+Lg]).
    body_depth_um : additional substrate depth [um] below the LOWEST
                 point of the etched profile, for the body/bulk contact.
    mesh_size_cm : override the default (fin-height/20-ish) mesh size.

    Returns (GmshMesh3D-like object with volume_tags {"source","gate",
    "drain"} and face_tags {"source_contact","drain_contact",
    "body_contact","gate"}). Raises ImportError if gmsh is not
    installed, ValueError if `geom.x` doesn't actually span the
    requested [0, 2*Lsd+Lg] source/gate/drain split.

    Geometry is now the REAL per-column staircase surface (see
    `_staircase_face`), not a 3-region median-height flattening.
    """
    from .gmsh_mesh3d import GmshMesh3D, _extract_current_model3d
    from .process2d import _UM_TO_CM

    x = geom.x
    L = 2.0 * Lsd + Lg
    if x.max() < L - 1e-15 or x.min() > 0.0 + 1e-15:
        raise ValueError(
            f"geom.x spans [{x.min():.3e}, {x.max():.3e}] cm, which does "
            f"not cover the requested [0, {L:.3e}] source+gate+drain span")

    src_mask = x <= Lsd
    gate_mask = (x > Lsd) & (x < Lsd + Lg)
    drn_mask = x >= Lsd + Lg
    if not (src_mask.any() and gate_mask.any() and drn_mask.any()):
        raise ValueError(
            "geom.x does not have sample points in all three of the "
            "source/gate/drain regions -- use a finer geom.x grid")

    h_max_um = float(np.max(geom.surface_um))
    h_min_um = float(np.min(geom.surface_um))
    y_bottom = (h_max_um - h_min_um) * _UM_TO_CM + body_depth_um * _UM_TO_CM
    top_all = (h_max_um - geom.surface_um) * _UM_TO_CM   # per-column top y, cm

    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("finfet3d_from_process2d")
        occ = gmsh.model.occ
        src_rect = _staircase_face(occ, x[src_mask], top_all[src_mask], 0.0, Lsd, y_bottom)
        gate_rect = _staircase_face(occ, x[gate_mask], top_all[gate_mask], Lsd, Lsd + Lg, y_bottom)
        drn_rect = _staircase_face(occ, x[drn_mask], top_all[drn_mask], Lsd + Lg, L, y_bottom)
        occ.fragment([(2, src_rect)], [(2, gate_rect), (2, drn_rect)])
        occ.synchronize()

        faces2d = gmsh.model.getEntities(2)

        def face_center(tag):
            return occ.getCenterOfMass(2, tag)

        def classify_x(cx):
            if cx < Lsd:
                return "source"
            if cx < Lsd + Lg:
                return "gate"
            return "drain"

        region_of_face2d = {}
        for _, tag in faces2d:
            cx, cy, cz = face_center(tag)
            region_of_face2d[tag] = classify_x(cx)

        extruded_vols = {}
        for _, tag in faces2d:
            out = occ.extrude([(2, tag)], 0.0, 0.0, Wfin)
            vol_tags = [t for d, t in out if d == 3]
            extruded_vols[tag] = vol_tags[0]
        occ.synchronize()

        volume_tags = {"source": [], "gate": [], "drain": []}
        for face2d_tag, vol_tag in extruded_vols.items():
            volume_tags[region_of_face2d[face2d_tag]].append(vol_tag)
        for name, tags in volume_tags.items():
            gmsh.model.addPhysicalGroup(3, tags, name=name)

        vol_of_region = {name: set(tags) for name, tags in volume_tags.items()}

        def owning_regions(face_tag):
            up, _down = gmsh.model.getAdjacencies(2, face_tag)
            regions = set()
            for name, vols in vol_of_region.items():
                if any(int(v) in vols for v in up):
                    regions.add(name)
            return regions

        all_faces = gmsh.model.getEntities(2)
        source_contact, drain_contact = [], []
        body_faces, gate_top, gate_side = [], [], []
        for _, tag in all_faces:
            cx, cy, cz = face_center(tag)
            regions = owning_regions(tag)
            if abs(cx - 0.0) < 1e-12 and "source" in regions:
                source_contact.append(tag)
            elif abs(cx - L) < 1e-12 and "drain" in regions:
                drain_contact.append(tag)
            elif abs(cy - y_bottom) < 1e-9:
                body_faces.append(tag)
            elif "gate" in regions and regions == {"gate"} and Lsd < cx < Lsd + Lg:
                # end-cap faces (the whole z=0 / z=Wfin cross-section) are
                # unambiguous by z alone; every OTHER gate-only lateral
                # face is part of the top/riser wrap -- with a real
                # (possibly multi-level) staircase surface (M35-S6),
                # there is no single `top_gate` y-value to check against
                # any more, so ALL non-end-cap, non-body gate faces are
                # collected together (flat top runs AND internal risers
                # between height levels both get the same gate coupling).
                if abs(cz - 0.0) < 1e-9 or abs(cz - Wfin) < 1e-9:
                    gate_side.append(tag)
                else:
                    gate_top.append(tag)

        for name, tags in (("source_contact", source_contact),
                          ("drain_contact", drain_contact),
                          ("body_contact", body_faces),
                          ("gate_top", gate_top),
                          ("gate_side", gate_side)):
            if not tags:
                raise RuntimeError(
                    f"build_finfet_mesh3d_from_process2d: could not identify "
                    f"any faces for {name!r} -- geometry construction failed")
            gmsh.model.addPhysicalGroup(2, tags, name=name)

        L_D_hint = mesh_size_cm or max(1e-6, min(Lg, Wfin, y_bottom) / 15.0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", L_D_hint)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 3.0 * L_D_hint)

        gmsh.model.mesh.generate(3)
        mesh = _extract_current_model3d()
    finally:
        gmsh.finalize()

    # combine the two gate face-tag groups the caller registered
    # separately (needed above only to VERIFY they were both found)
    # into ONE array -- see this module's own honesty clause on why a
    # wrap-around gate must be a single combined face list.
    mesh.face_tags["gate"] = np.concatenate(
        [mesh.face_tags.pop("gate_top"), mesh.face_tags.pop("gate_side")], axis=0)
    return mesh
