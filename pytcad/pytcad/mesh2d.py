"""Tensor-product 2D mesh: the 1D meshing rules from mesh.py, applied
independently along x and y.

Node k = j*Nx + i (row-major, x fastest).  A node's neighbors in the
flattened arrays used throughout device2d.py are at k+-1 (x direction)
and k+-Nx (y direction) -- a 5-point stencil.
"""

from dataclasses import dataclass, field
import numpy as np

from .mesh import debye_length


def control_volume_widths(h):
    """Box-integration control-volume width at each 1D node, given the
    array of spacings h between consecutive nodes (length n-1 for n nodes).
    Interior nodes get the average of their two neighboring half-intervals;
    endpoint nodes get one half-interval -- same rule device.py already
    uses to build its 1D dV.
    """
    h = np.asarray(h, dtype=float)
    dv = np.zeros(h.size + 1)
    dv[1:-1] = 0.5 * (h[:-1] + h[1:])
    dv[0] = 0.5 * h[0]
    dv[-1] = 0.5 * h[-1]
    return dv


@dataclass
class Mesh2D:
    """Tensor-product non-uniform 2D mesh.  Build x and y independently
    with mesh.py's graded_mesh/uniform_mesh, then pass both here.
    """
    x: np.ndarray
    y: np.ndarray

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        self.Nx = self.x.size
        self.Ny = self.y.size
        self.N = self.Nx * self.Ny

        self.hx = np.diff(self.x)
        self.hy = np.diff(self.y)

        self.dVx = control_volume_widths(self.hx)
        self.dVy = control_volume_widths(self.hy)

        # dV[j,i] = dVy[j]*dVx[i], flattened row-major (x fastest) to match idx()
        self.dV = np.outer(self.dVy, self.dVx).ravel()

    def idx(self, i, j):
        """Flattened node index for grid position (i, j)."""
        return j * self.Nx + i


def check_mesh2d(mesh: Mesh2D, doping_xy, eps_r=11.7, T=300.0, verbose=True):
    """Report the worst spacing-to-Debye-length ratio over both axes.
    Aim for < ~1, same rule as check_mesh in 1D.

    doping_xy : (Ny, Nx) array of net doping [cm^-3] at each mesh node.
    """
    doping_xy = np.asarray(doping_xy, dtype=float)
    LD = debye_length(np.abs(doping_xy), eps_r, T)   # (Ny, Nx)

    hx_ratio = mesh.hx[None, :] / np.minimum(LD[:, :-1], LD[:, 1:])
    hy_ratio = mesh.hy[:, None] / np.minimum(LD[:-1, :], LD[1:, :])
    worst = max(float(hx_ratio.max()), float(hy_ratio.max()))
    if verbose:
        print(f"  nodes = {mesh.N} ({mesh.Nx} x {mesh.Ny}), max h/L_D = {worst:.2f}")
    return worst
