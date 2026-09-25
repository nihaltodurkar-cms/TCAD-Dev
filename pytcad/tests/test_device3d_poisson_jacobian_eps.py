"""Device3D._residual_jacobian_poisson with position-dependent permittivity.

The residual's fluxes carry the harmonic-mean edge permittivity et_x/et_y/
et_z (M11-S4), but the equilibrium Jacobian's stencil weights did not:
FD check found |J_fd - J| / |J_fd| = 2.0 across an eps step (1.1e-9 with
uniform eps). Newton still reached the right root (F is exact) but took
40 steps instead of 7 at eps 11.7 -> 3.9, and 66 at 11.7 -> 2.0
(2026-09-25). The coupled Jacobian (wx_h = wx_area * et_x / hx) already
had the factor. With uniform eps et == 1.0 exactly, so that path cannot
move -- gated separately by md5 in the change record.
"""
import os, sys, dataclasses
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import Device3D, Mesh3D, Models, NewtonOptions
from pytcad.materials import SILICON


def _device(eps_right, n=(15, 5, 5)):
    nx, ny, nz = n
    xg = np.linspace(0, 1e-4, nx)
    yg = np.linspace(0, 0.3e-4, ny)
    zg = np.linspace(0, 0.3e-4, nz)
    right = dataclasses.replace(SILICON, name="Si-eps", eps_r=eps_right)
    mats = [SILICON if x < 0.5e-4 else right for _k in zg for _j in yg for x in xg]
    dop = np.broadcast_to(np.where(xg < 0.5e-4, -1e17, 1e17), (nz, ny, nx)).copy()
    dev = Device3D(Mesh3D(xg, yg, zg), dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True))
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk)
    dev.add_contact("r", i=np.full_like(jj, nx - 1), j=jj, k=kk)
    return dev, (nz, ny, nx)


@pytest.mark.parametrize("eps_right", [11.7, 3.9, 2.0])
def test_pj1_equilibrium_jacobian_matches_fd_across_eps_step(eps_right):
    dev, shp = _device(eps_right)
    psi = np.random.default_rng(0).uniform(-3.0, 3.0, shp)
    _, J = dev._residual_jacobian_poisson(psi)
    J = J.toarray()
    nz, ny, nx = shp
    # every interior node of one x-line, spanning the interface, plus
    # one node off-axis in y and z so all three directions are probed
    cols = [2 * ny * nx + 2 * nx + i for i in range(1, nx - 1)]
    cols += [1 * ny * nx + 3 * nx + 7, 3 * ny * nx + 1 * nx + 8]
    h = 1e-6
    for col in cols:
        e = np.zeros(psi.size)
        e[col] = h
        Fp, _ = dev._residual_jacobian_poisson(psi + e.reshape(shp))
        Fm, _ = dev._residual_jacobian_poisson(psi - e.reshape(shp))
        fd = (Fp.ravel() - Fm.ravel()) / (2 * h)
        err = np.max(np.abs(fd - J[:, col])) / np.max(np.abs(fd))
        assert err < 1e-6, f"column {col}: rel err {err:.2e}"


@pytest.mark.parametrize("eps_right", [3.9, 2.0])
def test_pj2_equilibrium_newton_is_quadratic_across_eps_step(eps_right):
    """Uniform-eps reference converges in 7 assemblies on this mesh; an
    exact Jacobian must not need more across an eps step."""
    ref, _ = _device(11.7, n=(31, 9, 9))
    dev, _ = _device(eps_right, n=(31, 9, 9))
    counts = []
    for d in (ref, dev):
        n = [0]
        inner = d._residual_jacobian_poisson

        def counted(psi, _i=inner, _n=n):
            _n[0] += 1
            return _i(psi)

        d._residual_jacobian_poisson = counted
        d.solve_equilibrium(NewtonOptions(linsolve="direct", max_iter=200))
        counts.append(n[0])
    assert counts[1] <= counts[0] + 1, counts
