"""M43 phase 4 (2026-09-16): thermal_grid.py's pure-Python oracle
(`_residual_jacobian_grid_py`) was REMOVED at the user's explicit
request -- there is no second implementation left to diff against.
What remains here: reproducibility (same input, called twice, bit-
identical output) on the sole compiled path, kept as a real
determinism gate -- correctness itself (FD-Jacobian, reduction
identity, BC ordering) is already covered by tests/test_m43_thermal2d.py
and test_m43_thermal3d.py, which do not need an oracle either.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import _accel
from pytcad.materials import SILICON
from pytcad.thermal import ThermalBC
from pytcad import thermal_grid as tg
from pytcad.thermal2d import solve_electrothermal_2d
from pytcad.thermal3d import solve_electrothermal_3d

pytestmark = pytest.mark.skipif(
    not _accel.HAVE_ACCEL, reason="pytcad._core is not built")


def _case_2d(seed=0):
    rng = np.random.default_rng(seed)
    Nx, Ny = 9, 6
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 6e-4, Ny)
    T = 300.0 + 40.0 * rng.standard_normal((Ny, Nx))
    H = 1e3 * np.abs(rng.standard_normal((Ny, Nx)))
    bcs = [(ThermalBC.resistance(2.0), ThermalBC.adiabatic()),
           (ThermalBC.isothermal(), ThermalBC.resistance(3.0))]
    return [y, x], T, H, bcs


def _case_3d(seed=1):
    rng = np.random.default_rng(seed)
    Nx, Ny, Nz = 6, 4, 3
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 5e-4, Ny)
    z = np.linspace(0.0, 4e-4, Nz)
    T = 300.0 + 40.0 * rng.standard_normal((Nz, Ny, Nx))
    H = 1e3 * np.abs(rng.standard_normal((Nz, Ny, Nx)))
    # deliberately mixes all 3 BC kinds across all 3 axes, so a corner
    # is shared by isothermal/resistance/adiabatic simultaneously.
    bcs = [(ThermalBC.resistance(1.5), ThermalBC.isothermal()),
           (ThermalBC.resistance(2.0), ThermalBC.adiabatic()),
           (ThermalBC.isothermal(), ThermalBC.resistance(3.0))]
    return [z, y, x], T, H, bcs


@pytest.mark.parametrize("case", [_case_2d, _case_3d], ids=["2D", "3D"])
def test_residual_jacobian_grid_is_reproducible(case):
    """Same input, called twice: bit-identical F and dense Jacobian --
    the kernel is pure arithmetic (the one transcendental, kappa_th, is
    evaluated once in Python before the call), so nondeterminism here
    would be a real bug (e.g. an uninitialized-memory read)."""
    coords, T, H, bcs = case()
    F_a, J_a = tg._residual_jacobian_grid(coords, T, H, SILICON, 300.0, bcs)
    F_b, J_b = tg._residual_jacobian_grid(coords, T, H, SILICON, 300.0, bcs)
    assert np.array_equal(F_a, F_b), "residual F not reproducible"
    assert np.array_equal(J_a.toarray(), J_b.toarray()), \
        "Jacobian not reproducible"


def test_solve_electrothermal_2d_is_reproducible():
    """End-to-end: a full outer-Gummel-loop electrothermal solve on a
    real Device2D, called twice, must converge to the bit-identical
    temperature profile -- confirms reproducibility survives being
    called repeatedly inside a Newton loop inside an outer loop."""
    from pytcad import Device2D, Models
    from pytcad.mesh2d import Mesh2D
    from pytcad.mesh import graded_mesh

    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    dop = np.where(x < 1e-4, -1e17, 1e17)

    def build(T):
        y = np.linspace(0.0, 1e-4, 4)
        mesh = Mesh2D(x, y)
        dev = Device2D(mesh, np.tile(dop, (4, 1)), T=T, models=Models(bgn=False))
        dev.add_contact("l", i=[0], j=list(range(4)), V=0.0)
        dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(4)), V=0.0)
        return dev

    def run():
        _, T_profile, _ = solve_electrothermal_2d(
            build, {"l": 0.55, "r": 0.0}, 300.0,
            ThermalBC.resistance(50.0), ThermalBC.resistance(50.0),
            ThermalBC.adiabatic(), ThermalBC.adiabatic(), SILICON, max_outer=30)
        return T_profile

    a = run()
    b = run()
    assert np.array_equal(a, b), "electrothermal 2D result not reproducible"


def test_solve_electrothermal_3d_is_reproducible():
    """3D analogue of the above."""
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D

    x = np.linspace(0.0, 2.0e-4, 17)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    Ny, Nz = 4, 4

    def build(T):
        y = np.linspace(0.0, 1e-4, Ny)
        z = np.linspace(0.0, 1e-4, Nz)
        mesh = Mesh3D(x=x, y=y, z=z)
        dop3 = np.broadcast_to(dop, (Nz, Ny, x.size)).copy()
        dev = Device3D(mesh, dop3, T=T, models=Models(bgn=False))
        kk, jj = np.meshgrid(range(Nz), range(Ny), indexing="ij")
        face = list(zip(jj.ravel(), kk.ravel()))
        dev.add_contact("l", i=[0] * len(face), j=[f[0] for f in face],
                         k=[f[1] for f in face], V=0.0)
        dev.add_contact("r", i=[mesh.Nx - 1] * len(face),
                         j=[f[0] for f in face], k=[f[1] for f in face], V=0.0)
        return dev

    def run():
        _, T_profile, _ = solve_electrothermal_3d(
            build, {"l": 0.55, "r": 0.0}, 300.0,
            ThermalBC.resistance(50.0), ThermalBC.resistance(50.0),
            ThermalBC.resistance(200.0), ThermalBC.resistance(200.0),
            ThermalBC.resistance(200.0), ThermalBC.resistance(200.0),
            SILICON, max_outer=30)
        return T_profile

    a = run()
    b = run()
    assert np.array_equal(a, b), "electrothermal 3D result not reproducible"
