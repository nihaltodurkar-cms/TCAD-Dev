"""M42-S3's compiled dg_grid kernel (core/src/dg/grid.cpp,
`_accel.core.dg_grid_lambda_rows`) vs. its pure-Python oracle,
`pytcad.dg_grid._dg_lambda_rows_py`. Unlike the P2/P4/M34-S4/M43
kernels CLAUDE.md's "C++ engine" section declares REQUIRED, this
kernel is OPTIONAL (M31's original graceful-fallback default) --
nothing about M42 asked for the fallback's removal, so both paths
stay in the tree and this gate is what keeps them honest against
each other, not a substitute for requiring the extension.

Skipped entirely if `_core` is not built (there is a real
pure-Python path to fall back to, unlike the required kernels'
own accel-parity tests, which skip on the same condition for a
different reason -- they would have nothing left to run at all).
"""
import numpy as np
import pytest

from pytcad import _accel
from pytcad import dg_grid
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.device import Models, NewtonOptions
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.mesh import graded_mesh

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL, reason="pytcad._core not built")


def _solve_with(monkeypatch, forced_impl, build_and_solve):
    monkeypatch.setattr(dg_grid, "dg_lambda_rows", forced_impl)
    return build_and_solve()


def test_2d_ohmic_bit_identical(monkeypatch):
    def build():
        x = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6, 1.2)
        y = graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6, 1.2)
        mesh = Mesh2D(x, y)
        dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
        dev = Device2D(mesh, dop, models=Models(bgn=False, dg=True))
        dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
        dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
        dev.solve_equilibrium(NewtonOptions(max_iter=200))
        return dev

    dev_accel = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_accel, build)
    dev_py = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_py, build)
    assert np.array_equal(dev_accel.psi, dev_py.psi)
    assert np.array_equal(dev_accel._dg_Lam_n, dev_py._dg_Lam_n)
    assert np.array_equal(dev_accel._dg_Lam_p, dev_py._dg_Lam_p)


def test_2d_gated_bit_identical(monkeypatch):
    def build():
        x = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6, 1.2)
        y = graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6, 1.2)
        mesh = Mesh2D(x, y)
        dop = np.full((y.size, x.size), -1e17)
        dev = Device2D(mesh, dop, models=Models(bgn=False, dg=True))
        dev.add_contact("body", i=[0], j=list(range(mesh.Ny)), V=0.0)
        dev.add_gate("gate", i=list(range(mesh.Nx)), j=[mesh.Ny - 1],
                     tox_cm=2e-7, Vfb=-0.9, Vg=0.0)
        dev.solve_equilibrium(NewtonOptions(max_iter=300))
        return dev

    dev_accel = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_accel, build)
    dev_py = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_py, build)
    assert np.array_equal(dev_accel.psi, dev_py.psi)
    assert np.array_equal(dev_accel._dg_Lam_n, dev_py._dg_Lam_n)
    assert np.array_equal(dev_accel._dg_Lam_p, dev_py._dg_Lam_p)


def test_3d_ohmic_bit_identical(monkeypatch):
    def build():
        x = np.linspace(0.0, 2e-5, 9)
        y = np.linspace(0.0, 1e-5, 7)
        z = np.linspace(0.0, 1e-5, 6)
        mesh = Mesh3D(x, y, z)
        dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), -1e17)
        dev = Device3D(mesh, dop, models=Models(bgn=False, dg=True))
        jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
        jj, kk = jj.ravel(), kk.ravel()
        dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
        dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
        dev.solve_equilibrium(NewtonOptions(max_iter=200))
        return dev

    dev_accel = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_accel, build)
    dev_py = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_py, build)
    assert np.array_equal(dev_accel.psi, dev_py.psi)
    assert np.array_equal(dev_accel._dg_Lam_n, dev_py._dg_Lam_n)
    assert np.array_equal(dev_accel._dg_Lam_p, dev_py._dg_Lam_p)


def test_3d_gated_bit_identical(monkeypatch):
    def build():
        x = np.linspace(0.0, 2e-5, 9)
        y = np.linspace(0.0, 1e-5, 7)
        z = np.linspace(0.0, 1e-5, 6)
        mesh = Mesh3D(x, y, z)
        dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), -1e17)
        dev = Device3D(mesh, dop, models=Models(bgn=False, dg=True))
        jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
        jj, kk = jj.ravel(), kk.ravel()
        dev.add_contact("body", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
        ii, kk2 = np.meshgrid(np.arange(mesh.Nx), np.arange(mesh.Nz))
        ii, kk2 = ii.ravel(), kk2.ravel()
        dev.add_gate("gate", i=ii, j=np.full_like(ii, mesh.Ny - 1), k=kk2,
                     tox_cm=2e-7, Vfb=-0.9, Vg=0.0, normal_axis="y")
        dev.solve_equilibrium(NewtonOptions(max_iter=300))
        return dev

    dev_accel = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_accel, build)
    dev_py = _solve_with(monkeypatch, dg_grid._dg_lambda_rows_py, build)
    assert np.array_equal(dev_accel.psi, dev_py.psi)
    assert np.array_equal(dev_accel._dg_Lam_n, dev_py._dg_Lam_n)
    assert np.array_equal(dev_accel._dg_Lam_p, dev_py._dg_Lam_p)
