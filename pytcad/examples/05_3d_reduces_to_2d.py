"""3D solver core validation: extrude a validated 2D p-n junction
uniformly in z, solve in 3D, and compare against the 2D result.

    python examples/05_3d_reduces_to_2d.py   -> 3d_reduces_to_2d.png

This is the dimensional-reduction check from the 3D solver core design
spec, made visual: the whole point of Sub-project A is that a z-invariant
3D structure must reproduce the existing, already-validated 2D solver
exactly.  No new device physics here -- this is a correctness
demonstration, not a new capability showcase (that comes in later
sub-projects: FinFET, GAA nanowire, GAA nanosheet).

Mesh is deliberately coarser than the 1D/2D examples' own x-resolution
(same coarsening applied in tests/test_validation_3d.py's reduction
tests): a 3D mesh multiplies node count across all three axes, so the
1D/2D-style fine spacing that is fine in those dimensionalities becomes
impractical here.  Both the 2D and 3D solves run on the IDENTICAL (x,y)
mesh, so this coarseness is common to both sides of the comparison and
cancels out of the reported error -- it does not weaken the validation.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib.pyplot as plt

from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.device import Models

x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
z = graded_mesh(3e-5, [0.0], 2e-6, 8e-6, 1.2)

dop1d = np.where(x < 1e-4, -1e17, 1e17)
dop2d = np.tile(dop1d, (y.size, 1))
dop3d = np.tile(dop2d, (z.size, 1, 1))

mesh2 = Mesh2D(x, y)
dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False))
dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
dev2.solve_equilibrium()
dev2.solve_bias({"left": 0.5, "right": 0.0})

mesh3 = Mesh3D(x, y, z)
dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
jj, kk = jj.ravel(), kk.ravel()
dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
dev3.solve_equilibrium()
dev3.solve_bias({"left": 0.5, "right": 0.0})

psi3_mid = dev3.psi_V[mesh3.Nz // 2, :, :]     # central z-plane
psi2 = dev2.psi_V
err_psi = np.abs(psi3_mid - psi2)

Jtot3_mid = (dev3.Jn_x + dev3.Jp_x)[mesh3.Nz // 2, :, :]
Jtot2 = dev2.Jn_x + dev2.Jp_x
err_J = np.abs(Jtot3_mid - Jtot2)

fig, axes = plt.subplots(2, 2, figsize=(10, 8))
im0 = axes[0, 0].imshow(psi2, aspect="auto", origin="lower")
axes[0, 0].set_title("2D potential [V]")
fig.colorbar(im0, ax=axes[0, 0])

im1 = axes[0, 1].imshow(psi3_mid, aspect="auto", origin="lower")
axes[0, 1].set_title("3D potential, central z-plane [V]")
fig.colorbar(im1, ax=axes[0, 1])

im2 = axes[1, 0].imshow(err_psi, aspect="auto", origin="lower")
axes[1, 0].set_title(f"|psi_3D - psi_2D|  (max {err_psi.max():.2e} V)")
fig.colorbar(im2, ax=axes[1, 0])

im3 = axes[1, 1].imshow(err_J, aspect="auto", origin="lower")
axes[1, 1].set_title(f"|J_3D - J_2D|  (max {err_J.max():.2e} A/cm^2)")
fig.colorbar(im3, ax=axes[1, 1])

fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "3d_reduces_to_2d.png")
fig.savefig(out, dpi=120)
print(f"wrote {os.path.abspath(out)}")
print(f"max |psi_3D - psi_2D| = {err_psi.max():.3e} V")
print(f"max |J_3D - J_2D|     = {err_J.max():.3e} A/cm^2")
