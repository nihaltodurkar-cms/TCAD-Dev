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
    region (no conformal sidewall slope, no corner rounding). This
    function reads a caller-supplied `ProcessGeometry2D` and samples
    the MEDIAN surface height within each of the three x-regions
    (source / gate / drain) -- for a genuine single-mask-etched fin
    this recovers the exact (piecewise-constant) shape process2d
    produced; it will silently flatten a more complex profile (e.g. a
    LOCOS bird's-beak taper) to its regional median, which is honestly
    disclosed here rather than attempted as a general polyline
    extrusion (out of scope for this pass).
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
"""
import numpy as np


def _require_gmsh():
    try:
        import gmsh  # noqa: F401
        return gmsh
    except ImportError as exc:
        raise ImportError(
            "this feature requires the optional 'gmsh' package "
            f"(pip install gmsh): {exc}") from exc


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

    h_src_um = float(np.median(geom.surface_um[src_mask]))
    h_gate_um = float(np.median(geom.surface_um[gate_mask]))
    h_drn_um = float(np.median(geom.surface_um[drn_mask]))
    h_max_um = max(h_src_um, h_gate_um, h_drn_um)
    h_min_um = min(h_src_um, h_gate_um, h_drn_um)

    y_bottom = (h_max_um - h_min_um) * _UM_TO_CM + body_depth_um * _UM_TO_CM
    top_src = (h_max_um - h_src_um) * _UM_TO_CM
    top_gate = (h_max_um - h_gate_um) * _UM_TO_CM
    top_drn = (h_max_um - h_drn_um) * _UM_TO_CM

    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("finfet3d_from_process2d")
        occ = gmsh.model.occ
        src_rect = occ.addRectangle(0.0, top_src, 0.0, Lsd, y_bottom - top_src)
        gate_rect = occ.addRectangle(Lsd, top_gate, 0.0, Lg, y_bottom - top_gate)
        drn_rect = occ.addRectangle(Lsd + Lg, top_drn, 0.0, Lsd, y_bottom - top_drn)
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
                if abs(cy - top_gate) < 1e-9:
                    gate_top.append(tag)
                elif abs(cz - 0.0) < 1e-9 or abs(cz - Wfin) < 1e-9:
                    gate_side.append(tag)

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
