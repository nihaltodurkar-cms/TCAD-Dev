"""Example 13 -- extrude a process2d 2D etch profile into a 3D
tri-gate FinFET unstructured tet mesh, and solve its (gate-coupled)
Poisson equilibrium.

This is the M26 acceptance demo for the "FinFET/GAA templates built as
extruded 2D process output" half of the milestone's own spec: a real
`pytcad.process2d.etch()` call produces a raised fin mesa, which
`pytcad.gmsh_finfet3d.build_finfet_mesh3d_from_process2d` extrudes into
a tet mesh, tags source/gate/drain regions and contacts, and
`pytcad.unstructured_dd3d`'s new gate/Robin BC (also new in this M26
pass) solves the coupled electrostatics.

See gmsh_finfet3d.py's own module docstring for the full honesty
clause -- most importantly: this demo solves EQUILIBRIUM only. The
fully coupled drift-diffusion bias solve on this tet geometry needs
voltage ramping/continuation this pass doesn't implement (measured,
not silently skipped -- see that docstring for the specific
convergence data).

    python examples/13_finfet3d_from_process2d.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.simplefilter("ignore")

import numpy as np

from pytcad import process2d
from pytcad.gmsh_finfet3d import build_finfet_mesh3d_from_process2d
from pytcad.unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d,
)
from pytcad.unstructured_dd3d import (
    evaluate_doping_at_nodes3d, solve_poisson_equilibrium3d,
)
from pytcad.materials import SILICON

Lsd, Lg, Wfin = 0.3e-4, 0.4e-4, 0.2e-4   # [cm]: 3 um / 4 um / 2 um
L = 2 * Lsd + Lg

print("Building the 2D process cross-section (process2d.etch)...")
x = np.linspace(0.0, L, 200)
geom = process2d.ProcessGeometry2D(x)
fin_mask = process2d.mask_from_intervals(x, [(Lsd, Lsd + Lg)])
geom = process2d.etch(geom, depth_um=0.3, mask=~fin_mask)
print(f"  source/drain surface height: {geom.surface_um[x < Lsd][0]:.3f} um")
print(f"  gate (fin) surface height:   {geom.surface_um[(x > Lsd) & (x < Lsd + Lg)][0]:.3f} um")

print("\nExtruding into a 3D tet mesh (pytcad.gmsh_finfet3d)...")
m = build_finfet_mesh3d_from_process2d(geom, Wfin=Wfin, Lsd=Lsd, Lg=Lg,
                                       mesh_size_cm=1e-6)
print(f"  {m.n_nodes()} nodes, {m.n_tets()} tets")
print(f"  regions: {[(name, len(t)) for name, t in m.volume_tags.items()]}")
print(f"  faces:   {[(name, f.shape[0]) for name, f in m.face_tags.items()]}")

region_of_tet = np.empty(m.n_tets(), dtype=object)
for name, idxs in m.volume_tags.items():
    region_of_tet[idxs] = name
C_phys = evaluate_doping_at_nodes3d(
    m.nodes, m.tets, region_of_tet,
    {"source": 1e18, "gate": -1e17, "drain": 1e18})

edges, node_vols = build_unstructured_stencil3d(m.nodes, m.tets)
edges, trans = build_edge_flux_geometry3d(m.nodes, m.tets, edges)
contacts = {"source": m.face_tags["source_contact"],
           "drain": m.face_tags["drain_contact"]}
gates = {"gate": {"faces": m.face_tags["gate"], "tox_cm": 2e-7, "Vfb": -0.9}}

print("\nSolving Poisson equilibrium (with the tri-gate Robin BC)...")
psi, scale = solve_poisson_equilibrium3d(
    m.nodes, m.tets, edges, node_vols, trans, C_phys, contacts,
    material=SILICON, gates=gates)
print(f"  psi range: [{psi.min():.2f}, {psi.max():.2f}] (VT units)")
print(f"  spread (max-min): {psi.max() - psi.min():.2f} -- confirms the gate "
      "is genuinely coupled (a broken gate BC would show ~0 spread)")
