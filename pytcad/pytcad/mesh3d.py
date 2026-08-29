"""Tensor-product 3D mesh: the 1D meshing rules from mesh.py, applied
independently along x, y, and z, and the outer-product control-volume
technique mesh2d.py already uses, extended one axis further.

Node k = kk*Nx*Ny + j*Nx + i (row-major, x fastest, y next, z slowest;
matches numpy's default C-order flattening of a (Nz,Ny,Nx) array).  A
node's neighbors in the flattened arrays used throughout device3d.py are
at k+-1 (x direction), k+-Nx (y direction), k+-Nx*Ny (z direction) -- a
7-point stencil.
"""

from dataclasses import dataclass
import numpy as np

from .mesh import debye_length
from .mesh2d import control_volume_widths


@dataclass
class Mesh3D:
    """Tensor-product non-uniform 3D mesh.  Build x, y, z independently
    with mesh.py's graded_mesh/uniform_mesh, then pass all three here.
    """
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        self.z = np.asarray(self.z, dtype=float)
        self.Nx = self.x.size
        self.Ny = self.y.size
        self.Nz = self.z.size
        self.N = self.Nx * self.Ny * self.Nz

        self.hx = np.diff(self.x)
        self.hy = np.diff(self.y)
        self.hz = np.diff(self.z)

        self.dVx = control_volume_widths(self.hx)
        self.dVy = control_volume_widths(self.hy)
        self.dVz = control_volume_widths(self.hz)

        # dV[kk,j,i] = dVz[kk]*dVy[j]*dVx[i], flattened row-major to match idx()
        vol = (self.dVz[:, None, None] * self.dVy[None, :, None]
               * self.dVx[None, None, :])
        self.dV = vol.ravel()

    def idx(self, i, j, k):
        """Flattened node index for grid position (i, j, k)."""
        return k * self.Nx * self.Ny + j * self.Nx + i


def check_mesh3d(mesh: Mesh3D, doping_xyz, eps_r=11.7, T=300.0, verbose=True):
    """Report the worst spacing-to-Debye-length ratio over all three axes.
    Aim for < ~1, same rule as check_mesh/check_mesh2d.

    doping_xyz : (Nz, Ny, Nx) array of net doping [cm^-3] at each mesh node.
    """
    doping_xyz = np.asarray(doping_xyz, dtype=float)
    LD = debye_length(np.abs(doping_xyz), eps_r, T)

    hx_ratio = mesh.hx[None, None, :] / np.minimum(LD[:, :, :-1], LD[:, :, 1:])
    hy_ratio = mesh.hy[None, :, None] / np.minimum(LD[:, :-1, :], LD[:, 1:, :])
    hz_ratio = mesh.hz[:, None, None] / np.minimum(LD[:-1, :, :], LD[1:, :, :])
    worst = max(float(hx_ratio.max()), float(hy_ratio.max()), float(hz_ratio.max()))
    if verbose:
        print(f"  nodes = {mesh.N} ({mesh.Nx} x {mesh.Ny} x {mesh.Nz}), "
              f"max h/L_D = {worst:.2f}")
    return worst
