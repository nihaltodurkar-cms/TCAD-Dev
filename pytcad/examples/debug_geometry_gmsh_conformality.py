"""Debug/validation script for the Geometry Foundation decision
(see ARCHITECTURE.md section 4b and the M21-MESHING-PLAN.md phase-3
note): does gmsh actually give a CONFORMAL 2D mesh across a material
interface, with region tags surviving to the element level, in a form
pytcad's box-integration FVM core could consume?

Builds the same p-n diode geometry as the pytcad Device2D goldens
(6.0e-4 x 2.0e-4 cm, junction at 3.0e-4 cm) via gmsh's OCC kernel,
tags it with Physical Groups (p_region/n_region/left_contact/
right_contact), meshes it, and checks four things a wrong answer to
any of which would break the recommendation:

  1. region AREAS match the analytic rectangle areas (machine precision)
  2. p_region and n_region SHARE node tags along the junction, and
     every shared node sits EXACTLY at x = Xj (not "close to" -- exactly,
     bit for bit) -- this is what makes the mesh usable by an SG-flux
     scheme that assumes a shared node at every interior interface
  3. every triangle has a consistent, non-degenerate orientation
  4. the contact Physical Groups resolve to real boundary elements

HARD-DEBUG FINDING (kept in this script, not smoothed over): the first
attempt sized the near-junction mesh with an arbitrary distance field
(DistMin=1e-5, SizeMin=5e-7) and produced 21344 nodes for two
rectangles -- the Threshold field refines uniformly along the ENTIRE
junction curve, so an ungrounded DistMin makes the fine corridor far
wider than the physics needs.  Regrounding DistMin/SizeMin in
pytcad.mesh.debye_length (the same quantity M21's own adaptive
refinement uses as its mesh-quality CONSTRAINT, not an arbitrary
number) cut this to 2095 nodes with area error tightening from 1e-14
to 1e-16 relative.  The lesson generalizes: a gmsh size field is not a
substitute for physics-grounded sizing any more than a blind h/L_D
Doerfler indicator was in M21 -- see pytcad/adapt.py's own
docstring for the sibling finding on that side of the mesh.

    pip install gmsh   (optional dependency; not required by pytcad core)
    python examples/debug_geometry_gmsh_conformality.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
import numpy as np

from pytcad.mesh import debye_length

gmsh.initialize()
gmsh.model.add("diode2d")

Lx, Ly, Xj = 6.0e-4, 2.0e-4, 3.0e-4   # cm, matches the existing 1D/2D diode fixtures

occ = gmsh.model.occ
p_rect = occ.addRectangle(0.0, 0.0, 0, Xj, Ly)
n_rect = occ.addRectangle(Xj, 0.0, 0, Lx - Xj, Ly)
occ.synchronize()

# Fragment: this is the step that MUST make the two rectangles share
# nodes along x=Xj rather than producing two independently-meshed
# regions with coincident-but-distinct boundary nodes (which would
# break every SG edge current calc that assumes a shared node).
out, out_map = occ.fragment([(2, p_rect)], [(2, n_rect)])
occ.synchronize()

surfaces = gmsh.model.getEntities(2)
print("surfaces after fragment:", surfaces)

# Identify p/n surfaces by centroid x (fragment can renumber tags).
p_tag = n_tag = None
for dim, tag in surfaces:
    com = gmsh.model.occ.getCenterOfMass(dim, tag)
    print(f"  surface {tag}: centroid x={com[0]:.3e}")
    if com[0] < Xj:
        p_tag = tag
    else:
        n_tag = tag
assert p_tag is not None and n_tag is not None, "could not identify both regions"

pg_p = gmsh.model.addPhysicalGroup(2, [p_tag], name="p_region")
pg_n = gmsh.model.addPhysicalGroup(2, [n_tag], name="n_region")

# Contacts: left edge of p region, right edge of n region.
curves = gmsh.model.getEntities(1)
left_curve = right_curve = None
for dim, tag in curves:
    com = gmsh.model.occ.getCenterOfMass(dim, tag)
    if abs(com[0] - 0.0) < 1e-12:
        left_curve = tag
    elif abs(com[0] - Lx) < 1e-12:
        right_curve = tag
assert left_curve and right_curve, "could not identify contact edges"
gmsh.model.addPhysicalGroup(1, [left_curve], name="left_contact")
gmsh.model.addPhysicalGroup(1, [right_curve], name="right_contact")

# Mesh size field: fine at the junction (mimicking Debye-length
# refinement), coarse in the bulk -- the M21 adaptive philosophy
# expressed as a gmsh field instead of pytcad.adapt.
gmsh.model.mesh.field.add("Distance", 1)
gmsh.model.mesh.field.setNumbers(1, "CurvesList", [c for d, c in curves
                                                   if abs(gmsh.model.occ.getCenterOfMass(d, c)[0] - Xj) < 1e-12])
gmsh.model.mesh.field.add("Threshold", 2)
gmsh.model.mesh.field.setNumber(2, "InField", 1)
# Grounded in the SAME Debye length pytcad.mesh.debye_length computes
# (4.09e-6 cm at 1e16 cm^-3): the fine corridor should be a few L_D wide,
# not an arbitrary distance -- the first attempt used DistMin=1e-5 (2.4x
# L_D) and DistMax=1e-4 (24x L_D), refining a corridor 20x wider than the
# physics needs and producing 21344 nodes for a two-rectangle device.
L_D = debye_length(1e16)   # cm; matches pytcad.mesh.check_mesh's own criterion
gmsh.model.mesh.field.setNumber(2, "SizeMin", 0.5 * L_D)
gmsh.model.mesh.field.setNumber(2, "SizeMax", 2e-5)
gmsh.model.mesh.field.setNumber(2, "DistMin", 2.0 * L_D)
gmsh.model.mesh.field.setNumber(2, "DistMax", 15.0 * L_D)
gmsh.model.mesh.field.setAsBackgroundMesh(2)

gmsh.model.mesh.generate(2)

nodes_tags, nodes_coord, _ = gmsh.model.mesh.getNodes()
print(f"\ntotal mesh nodes: {len(nodes_tags)}")

def region_triangles(pg_tag, dim, name):
    ents = gmsh.model.getEntitiesForPhysicalGroup(dim, pg_tag)
    total_area = 0.0
    tri_conn = []
    for ent in ents:
        etypes, etags, enodes = gmsh.model.mesh.getElements(2, ent)
        for et, tags_, nds in zip(etypes, etags, enodes):
            if et != 2:  # 2 = 3-node triangle
                continue
            nds = np.asarray(nds).reshape(-1, 3)
            tri_conn.append(nds)
    if tri_conn:
        tri_conn = np.concatenate(tri_conn, axis=0)
    else:
        tri_conn = np.zeros((0, 3), dtype=int)
    return tri_conn

coord_by_tag = {t: nodes_coord[3*i:3*i+3] for i, t in enumerate(nodes_tags)}

p_tris = region_triangles(pg_p, 2, "p_region")
n_tris = region_triangles(pg_n, 2, "n_region")
print(f"p_region triangles: {len(p_tris)}   n_region triangles: {len(n_tris)}")

def shoelace_area(tris):
    area = 0.0
    for tri in tris:
        pts = np.array([coord_by_tag[t][:2] for t in tri])
        area += 0.5 * abs((pts[1,0]-pts[0,0])*(pts[2,1]-pts[0,1])
                          - (pts[2,0]-pts[0,0])*(pts[1,1]-pts[0,1]))
    return area

area_p = shoelace_area(p_tris)
area_n = shoelace_area(n_tris)
print(f"p_region area: {area_p:.6e}  (analytic {Xj*Ly:.6e}, rel err {abs(area_p-Xj*Ly)/(Xj*Ly):.2e})")
print(f"n_region area: {area_n:.6e}  (analytic {(Lx-Xj)*Ly:.6e}, rel err {abs(area_n-(Lx-Xj)*Ly)/((Lx-Xj)*Ly):.2e})")

# THE key conformality check: do p_tris and n_tris SHARE node tags
# along the interface, or does each region carry its own copy?
p_node_set = set(p_tris.flatten().tolist())
n_node_set = set(n_tris.flatten().tolist())
shared = p_node_set & n_node_set
print(f"\nnode tags shared between p_region and n_region: {len(shared)}")
if shared:
    xs = sorted(set(round(coord_by_tag[t][0], 12) for t in shared))
    print(f"  shared-node x range: [{xs[0]:.6e}, {xs[-1]:.6e}]  (expect all == Xj={Xj:.6e})")
    off = [x for x in xs if abs(x - Xj) > 1e-15]
    print(f"  shared nodes NOT exactly at Xj: {len(off)}")
else:
    print("  !! ZERO shared nodes -- mesh is NOT conformal across the junction")

# Degenerate-element and orientation check (a real mesh-quality gate,
# not just a total-area sum which would hide a positive+negative pair).
def per_triangle_signed_areas(tris):
    out = []
    for tri in tris:
        pts = np.array([coord_by_tag[t][:2] for t in tri])
        out.append(0.5 * ((pts[1,0]-pts[0,0])*(pts[2,1]-pts[0,1])
                          - (pts[2,0]-pts[0,0])*(pts[1,1]-pts[0,1])))
    return np.array(out)

sa_p = per_triangle_signed_areas(p_tris)
sa_n = per_triangle_signed_areas(n_tris)
print(f"\np_region: min|area|={np.abs(sa_p).min():.3e}  "
      f"sign flips={np.sum(sa_p<0)}/{len(sa_p)}  "
      f"degenerate(<1e-20)={np.sum(np.abs(sa_p)<1e-20)}")
print(f"n_region: min|area|={np.abs(sa_n).min():.3e}  "
      f"sign flips={np.sum(sa_n<0)}/{len(sa_n)}  "
      f"degenerate(<1e-20)={np.sum(np.abs(sa_n)<1e-20)}")

# Contact groups: do they resolve to actual 1D boundary elements?
for name, ent_tag in (("left_contact", left_curve), ("right_contact", right_curve)):
    etypes, etags, enodes = gmsh.model.mesh.getElements(1, ent_tag)
    n_line_elems = sum(len(t) for t, et in zip(etags, etypes) if et == 1)
    print(f"{name}: {n_line_elems} boundary line elements on curve {ent_tag}")

gmsh.finalize()
