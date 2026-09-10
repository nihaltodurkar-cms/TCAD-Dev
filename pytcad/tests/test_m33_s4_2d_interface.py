"""M33-S4 gates -- chi-aware band alignment ported to Device2D.

Plan: `pytcad/M33-S4-PLAN.md`. Straight port of Device1D's S1
(`tests/test_m33_interface.py`) to the 2D structured box-integration
core -- same derivation (`band_shift`, one per-node offset referenced
to node (0,0)), same gate shapes, narrowed to what a 2D grid adds
(interface EDGES in both x and y, a GateBC Robin term S1 had no
analogue for).
"""
import dataclasses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.materials import SILICON
from pytcad.mesh2d import Mesh2D


def _hetero_mesh(nx=25, ny=9):
    xg = np.linspace(0.0, 1.0e-4, nx)
    yg = np.linspace(0.0, 0.4e-4, ny)
    return Mesh2D(xg, yg), xg, yg


def _split_materials(xg, yg, x_split=0.5e-4, chi_right=4.05):
    right = dataclasses.replace(SILICON, name="Si-shifted", chi=chi_right)
    return [SILICON if x < x_split else right
            for _ in range(yg.size) for x in xg]


def _hetero(chi_right=4.05, band_offset="nie", junction="pn", nx=25, ny=9,
           bias=None, equilibrium_only=False):
    """pn (built-in absorbs most of a chi step) or isotype ("N-N", no
    built-in) junction, materials identical except chi_right -- mirrors
    test_m33_interface.py's own _hetero exactly, ported to 2D."""
    mesh, xg, yg = _hetero_mesh(nx, ny)
    if junction == "pn":
        dop = np.tile(np.where(xg < 0.5e-4, -1e17, 1e17), (yg.size, 1))
    else:
        dop = np.tile(np.full_like(xg, 1e17), (yg.size, 1))
    mats = _split_materials(xg, yg, chi_right=chi_right)
    dev = Device2D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True, band_offset=band_offset))
    dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    if not equilibrium_only:
        dev.solve_bias({"l": bias if bias is not None else 0.0})
    return dev


# Absolute floor [A/cm], measured (not a round number): the worst
# homojunction-equivalent (dchi swept -0.30..+0.30, band_offset=
# "affinity") equilibrium |Jn|/|Jp| max over both edge directions was
# 1.6e-10 A/cm (Newton's own stopping floor, not a balance violation --
# see M33-S4-PLAN.md / test_m33_interface.py's identical reasoning for
# the 1D floor). 1e-7 sits ~600x above it.
EQ_CURRENT_FLOOR = 1.0e-7


def _assert_balanced(dev):
    """G1: per carrier, separately, both edge directions."""
    _, _, Jn_x, Jn_y, Jp_x, Jp_y, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, {})
    Jn_max = max(np.abs(Jn_x).max(), np.abs(Jn_y).max()) * dev.J0
    Jp_max = max(np.abs(Jp_x).max(), np.abs(Jp_y).max()) * dev.J0
    assert Jn_max < EQ_CURRENT_FLOOR, \
        f"electron detailed balance broken: |Jn|max={Jn_max:.3e}"
    assert Jp_max < EQ_CURRENT_FLOOR, \
        f"hole detailed balance broken: |Jp|max={Jp_max:.3e}"


# ----------------------------------------------------------------------
# G1 -- equilibrium detailed balance, per carrier, both edge axes
# ----------------------------------------------------------------------
@pytest.mark.parametrize("dchi", [-0.30, -0.10, 0.0, 0.10, 0.30])
def test_g1_equilibrium_detailed_balance_per_carrier(dchi):
    dev = _hetero(chi_right=4.05 + dchi, band_offset="affinity",
                  junction="pn", equilibrium_only=True)
    _assert_balanced(dev)


# ----------------------------------------------------------------------
# G2 -- chi must actually move the 2D solution
# ----------------------------------------------------------------------
def test_g2_affinity_step_moves_the_solution():
    ref = _hetero(chi_right=4.05, band_offset="affinity", junction="pn",
                  bias=0.1)
    for dchi in (-0.20, +0.20):
        dev = _hetero(chi_right=4.05 + dchi, band_offset="affinity",
                      junction="pn", bias=0.1)
        moved = np.abs(dev.psi - ref.psi).max()
        assert moved > 1e-3, (
            f"chi step {dchi:+.2f} eV moved psi by only {moved:.3e}")
        Jr = ref.terminal_current("l")
        J = dev.terminal_current("l")
        assert abs(J / Jr - 1.0) > 1e-3, (
            f"chi step {dchi:+.2f} eV left J unchanged (ratio {J/Jr:.6f})")


def test_g2_pn_direction_is_physical():
    """Raising chi on the far side lowers Ec there -- forward current
    falls monotonically, same direction as the validated 1D result."""
    chis = [3.85, 3.95, 4.05, 4.15, 4.25]
    Js = [_hetero(chi_right=c, band_offset="affinity", junction="pn",
                  bias=0.4).terminal_current("l") for c in chis]
    assert all(a > b for a, b in zip(Js, Js[1:])), list(zip(chis, Js))


def test_g2_isotype_junction_barrier_is_symmetric_in_sign():
    """No p-n built-in to absorb the step -- current is MAXIMISED at
    dchi=0 and falls for BOTH signs (the signature a symmetric-nie
    gauge cannot produce), mirroring the 1D isotype gate."""
    J_lo = _hetero(chi_right=3.85, band_offset="affinity",
                   junction="isotype", bias=0.1).terminal_current("l")
    J_flat = _hetero(chi_right=4.05, band_offset="affinity",
                     junction="isotype", bias=0.1).terminal_current("l")
    J_hi = _hetero(chi_right=4.25, band_offset="affinity",
                   junction="isotype", bias=0.1).terminal_current("l")
    assert J_lo < J_flat and J_hi < J_flat, (J_lo, J_flat, J_hi)


# ----------------------------------------------------------------------
# G3 -- FD-Jacobian on the INTERFACE edges specifically
# ----------------------------------------------------------------------
def test_g3_fd_jacobian_on_interface_edges():
    """Not a random column sample (M14's lesson: random sampling missed
    the boundary rows where a real bug lived) -- every column touching
    the x-edge that crosses the material interface, for every row."""
    nx, ny = 25, 9
    mesh, xg, yg = _hetero_mesh(nx, ny)
    x_split = 0.5e-4
    i_split = int(np.searchsorted(xg, x_split))     # first node >= split
    dev = _hetero(chi_right=4.30, band_offset="affinity", junction="pn",
                  bias=0.3, equilibrium_only=False)
    rng = np.random.default_rng(7)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.3, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    shp = dev.psi.shape

    # every interface-edge endpoint node (i_split-1, i_split), every
    # row, all three components -- deterministic, not random.
    cols = []
    for j in range(ny):
        for i in (i_split - 1, i_split):
            k = j * nx + i
            cols.extend([3 * k, 3 * k + 1, 3 * k + 2])

    worst = 0.0
    for c in cols:
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"S4 GATE FAIL: FD-Jacobian rel err {worst:.3e} > 5e-5"


# ----------------------------------------------------------------------
# G4 -- bit-identity off-path
# ----------------------------------------------------------------------
def test_g4_legacy_gauge_reproduces_the_golden():
    """band_offset="nie" (the default) must be untouched by this
    change -- reconstruct-and-compare on the m13 golden itself lives in
    tests/test_m13_goldens.py; this is the in-file regression."""
    dev_default = _hetero(chi_right=4.30, band_offset="nie",
                          junction="pn", bias=0.4)
    dev_explicit_nie = _hetero(chi_right=3.55, band_offset="nie",
                               junction="pn", bias=0.4)
    assert np.array_equal(dev_default.psi, dev_explicit_nie.psi)
    assert np.array_equal(dev_default.n, dev_explicit_nie.n)
    assert np.array_equal(dev_default.p, dev_explicit_nie.p)


def test_g4_homojunction_is_bit_identical_between_gauges():
    """With ONE material everywhere, band_shift is identically zero, so
    the two gauges must agree bit-for-bit."""
    mesh, xg, yg = _hetero_mesh()
    dop = np.tile(np.where(xg < 0.5e-4, -1e17, 1e17), (yg.size, 1))
    out = []
    for bo in ("nie", "affinity"):
        dev = Device2D(mesh, dop, T=300.0,
                       models=Models(bgn=False, srh=True, band_offset=bo))
        dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
        dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
        dev.solve_equilibrium()
        dev.solve_bias({"l": 0.4})
        out.append((dev.psi, dev.n, dev.p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


def test_g4_default_is_the_legacy_gauge():
    assert Models().band_offset == "nie"


# ----------------------------------------------------------------------
# G5 -- GateBC Robin term composes correctly with the affinity gauge
# ----------------------------------------------------------------------
def _gated_device(chi_right, band_offset, nx=41, ny=15):
    xg = np.linspace(0.0, 2.0e-4, nx)
    yg = np.linspace(0.0, 0.5e-4, ny)
    mesh = Mesh2D(xg, yg)
    dop = np.tile(np.full_like(xg, -1e17), (yg.size, 1))    # p-substrate
    mats = _split_materials(xg, yg, x_split=1.0e-4, chi_right=chi_right)
    dev = Device2D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True, band_offset=band_offset))
    i_ch = np.arange(nx)
    dev.add_contact("s", i=[0], j=list(range(ny)), V=0.0)
    dev.add_contact("d", i=[nx - 1], j=list(range(ny)), V=0.0)
    dev.add_gate("g", i=i_ch, j=np.zeros_like(i_ch), tox_cm=1.0e-6,
                Vfb=-0.5, Vg=0.0)
    return dev


def test_g5_gate_bc_homojunction_bit_identical_between_gauges():
    """The psi_b_local fix must be a no-op for a homojunction under a
    real GateBC -- a regression check S1 had no analogue for (Device1D
    has no gate)."""
    out = []
    for bo in ("nie", "affinity"):
        dev = _gated_device(chi_right=4.05, band_offset=bo)
        dev.solve_equilibrium()
        dev.solve_bias({"s": 0.0, "d": 0.05, "g": 0.8})
        out.append((dev.psi, dev.n, dev.p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


def test_g5_gate_bc_fd_jacobian_with_a_chi_step_under_the_channel():
    """FD-Jacobian across the WHOLE device (gate rows included) with a
    genuine chi step under half the channel, affinity gauge live."""
    dev = _gated_device(chi_right=4.30, band_offset="affinity", nx=15, ny=7)
    dev.solve_equilibrium()
    dev.solve_bias({"s": 0.0, "d": 0.05, "g": 0.8})
    rng = np.random.default_rng(11)
    psi = dev.psi + 0.01 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.005 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.005 * rng.standard_normal(dev.p.shape))
    voltages = {"s": 0.0, "d": 0.05}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    shp = dev.psi.shape
    rng2 = np.random.default_rng(13)
    worst = 0.0
    for c in rng2.choice(u.size, size=60, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"S4 GATE FAIL: FD-Jacobian rel err {worst:.3e} > 5e-5"


# ----------------------------------------------------------------------
# G6 / G7 -- refusals
# ----------------------------------------------------------------------
def test_g6_thermionic_refuses_on_device2d():
    mesh, xg, yg = _hetero_mesh()
    dop = np.tile(np.where(xg < 0.5e-4, -1e17, 1e17), (yg.size, 1))
    with pytest.raises(NotImplementedError, match="[Tt]hermionic"):
        Device2D(mesh, dop, T=300.0,
                 models=Models(band_offset="affinity", thermionic=True))


def test_g7_affinity_with_fd_refuses_on_device2d():
    mesh, xg, yg = _hetero_mesh()
    dop = np.tile(np.where(xg < 0.5e-4, -1e17, 1e17), (yg.size, 1))
    with pytest.raises(NotImplementedError, match="fd"):
        Device2D(mesh, dop, T=300.0,
                 models=Models(band_offset="affinity", fd=True))
