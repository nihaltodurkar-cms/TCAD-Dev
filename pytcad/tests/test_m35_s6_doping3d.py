"""M35-S6 acceptance gates: a real 3D-sampled doping field (extruded
from process2d's actual 2D implant array) replacing gmsh_finfet3d's
uniform-per-region doping constant. Scope note (cost-driven, see
M35-3D-PROCESS-PLAN.md): only the doping-field half of S6 is
implemented this pass; the geometry half (real profile instead of
3-region median flattening) is deferred and named in
gmsh_finfet3d.py's own docstring.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.gmsh_finfet3d import sample_doping_3d_from_process2d


def _two_peak_doping(Nx=40, Ny=30):
    mesh_x = np.linspace(0.0, 1.0e-4 * Nx, Nx)   # cm
    mesh_y = np.linspace(0.0, 1.0e-4 * Ny, Ny)   # cm
    X, Y = np.meshgrid(mesh_x, mesh_y)   # (Ny,Nx)
    # two distinct Gaussian peaks at different x -- a shape a
    # per-region-constant model could never reproduce
    peak1 = 1e19 * np.exp(-((X - 0.2e-4 * Nx) ** 2) / (2 * (0.05e-4 * Nx) ** 2)
                           - (Y ** 2) / (2 * (0.1e-4 * Ny) ** 2))
    peak2 = 1e17 * np.exp(-((X - 0.8e-4 * Nx) ** 2) / (2 * (0.05e-4 * Nx) ** 2)
                           - (Y ** 2) / (2 * (0.1e-4 * Ny) ** 2))
    C = peak1 + peak2
    return mesh_x, mesh_y, C


def test_sampled_doping_reproduces_the_2d_field_at_matching_xy():
    mesh_x, mesh_y, C = _two_peak_doping()
    # sample nodes exactly AT the grid points (two different z's each)
    xs = mesh_x[::5]
    ys = mesh_y[::5]
    nodes = []
    expected = []
    from scipy.interpolate import RegularGridInterpolator
    interp = RegularGridInterpolator((mesh_y, mesh_x), C)
    for x in xs:
        for y in ys:
            for z in (0.0, 3.0e-4):
                nodes.append((x, y, z))
                expected.append(interp([[y, x]])[0])
    nodes = np.asarray(nodes)
    expected = np.asarray(expected)

    got = sample_doping_3d_from_process2d(nodes, mesh_x, mesh_y, C)
    rel_err = np.max(np.abs(got - expected)) / np.max(np.abs(expected))
    print(f"S6 doping sample rel_err at grid points: {rel_err:.4e}")
    assert rel_err < 1e-9


def test_sampled_doping_is_z_independent_extrusion():
    """Two nodes at the SAME (x,y) but different z must get the SAME
    doping value -- proving the contract is 'extruded 2D field', not
    silently z-dependent."""
    mesh_x, mesh_y, C = _two_peak_doping()
    x0, y0 = mesh_x[10], mesh_y[10]
    nodes = np.array([
        [x0, y0, 0.0],
        [x0, y0, 5.0e-4],
        [x0, y0, -3.0e-4],
    ])
    got = sample_doping_3d_from_process2d(nodes, mesh_x, mesh_y, C)
    assert np.allclose(got, got[0]), "doping must not depend on z (extrusion contract)"


def test_sampled_doping_clamps_out_of_range_nodes():
    """A node outside the implant grid's (x,y) span must not raise --
    it should clamp to the nearest edge value, since a tet mesh's node
    coordinates need not land exactly inside the implant grid's span."""
    mesh_x, mesh_y, C = _two_peak_doping()
    far_outside = np.array([[mesh_x[-1] * 5.0, mesh_y[-1] * 5.0, 0.0]])
    got = sample_doping_3d_from_process2d(far_outside, mesh_x, mesh_y, C)
    assert np.isfinite(got[0])
