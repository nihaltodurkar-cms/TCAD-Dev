"""M13 G6a goldens: bit-identity of the fd=False (default) path.

These golden files were captured from the PRE-M13-CORE-EDIT solver
(commit 1b4e7bc tree, before any device.py/device2d.py/device3d.py
change).  Every later M13 gate (and any future core refactor) must
reproduce them EXACTLY (np.array_equal) with Models(fd=False).

Regenerate ONLY with PYTCAD_REGEN_M13_GOLDENS=1 and a dedicated
commit message saying so -- never silently.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "goldens", "m13")
REGEN = os.environ.get("PYTCAD_REGEN_M13_GOLDENS") == "1"


def _golden_path(name):
    return os.path.join(GOLDEN_DIR, name + ".npz")


def _save(name, **arrays):
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    np.savez(_golden_path(name), **arrays)


def _load(name):
    if not os.path.exists(_golden_path(name)):
        pytest.skip(f"golden {name}.npz missing -- regenerate with "
                    "PYTCAD_REGEN_M13_GOLDENS=1")
    return np.load(_golden_path(name))


def _compare(name, **arrays):
    if REGEN:
        _save(name, **arrays)
        return
    gold = _load(name)
    for key, val in arrays.items():
        assert key in gold, f"golden {name} missing key {key}"
        assert np.array_equal(gold[key], val), \
            f"G6a BIT-IDENTITY FAILURE: golden {name}:{key} changed"


# ---------------------------------------------------------------- fixtures
def _diode_1d():
    from pytcad import Device1D, Models, NewtonOptions
    from pytcad.mesh import graded_mesh
    x = graded_mesh(2.0e-4, [1.0e-4], h_min=1.0e-8, h_max=1.0e-6,
                    ratio=1.12)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=True, auger=True))
    return dev, NewtonOptions


def _hetero_1d():
    from pytcad import Device1D, Models
    from pytcad.device import NewtonOptions
    from pytcad.materials import SILICON, GAAS
    x = np.linspace(0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e17, 1e17)
    mats = [SILICON] * 20 + [GAAS] * 21
    dev = Device1D(x, dop, T=300.0, material=mats,
                   models=Models(bgn=True, srh=True))
    return dev, NewtonOptions


# ---------------------------------------------------------------- 1D
def test_golden_1d_diode_equilibrium_and_bias():
    dev, NewtonOptions = _diode_1d()
    dev.solve_equilibrium()
    _compare("diode1d_eq", psi=dev.psi, n=dev.n, p=dev.p)
    dev.solve_bias([0.6, 0.0], NewtonOptions())
    _compare("diode1d_fwd", psi=dev.psi, n=dev.n, p=dev.p,
             Jn=dev.Jn, Jp=dev.Jp)


def test_golden_1d_hetero_equilibrium():
    dev, NewtonOptions = _hetero_1d()
    dev.solve_equilibrium()
    _compare("hetero1d_eq", psi=dev.psi, n=dev.n, p=dev.p)


# ---------------------------------------------------------------- 2D
def test_golden_2d_diode_equilibrium():
    pytest.importorskip("scipy")
    from pytcad import Device2D, Models
    from pytcad.mesh2d import Mesh2D
    from pytcad.mesh import graded_mesh

    x = graded_mesh(1.0e-4, [0.5e-4], 5e-7, 5e-6, 1.2)
    y = graded_mesh(0.5e-4, [0.0], 5e-7, 5e-6, 1.2)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 0.5e-4, -1e17, 1e17), (y.size, 1))
    dev = Device2D(mesh, dop, models=Models(bgn=False))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)),
                    V=0.0)
    dev.solve_equilibrium()
    _compare("diode2d_eq", psi=dev.psi, n=dev.n, p=dev.p)


# ---------------------------------------------------------------- 3D
def test_golden_3d_resistor_equilibrium():
    pytest.importorskip("scipy")
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D
    from pytcad.mesh import graded_mesh

    x = np.linspace(0.0, 1.0e-4, 9)
    y = graded_mesh(0.5e-4, [0.0], 1e-6, 5e-6, 1.3)
    z = np.linspace(0.0, 0.5e-4, 5)
    mesh = Mesh3D(x, y, z)
    dop = np.zeros((mesh.Nz, mesh.Ny, mesh.Nx))
    dev = Device3D(mesh, dop, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj,
                    k=kk, V=0.1)
    dev.solve_equilibrium()
    _compare("resistor3d_eq", psi=dev.psi, n=dev.n, p=dev.p)
