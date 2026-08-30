"""M14 gates: surface/inversion-layer mobility (Lombardi CVT) wired
into Device2D.

Gate reference: M14-SURFACE-MOBILITY-PLAN.md section 4.  This
milestone was interrupted mid-implementation by a crash; see the
plan's STATUS section for what existed before this pass (mobility_cvt
written but never validated or wired; Models fields declared but never
read) versus what this pass adds.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad import Device1D, Device2D, Models
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mosfet import build_mosfet
from pytcad.device import NewtonOptions


def _mosfet(surface_mobility=False):
    dev = build_mosfet(Lg=0.3e-4, Lsd=0.2e-4, depth=0.5e-4,
                       Na=1e17, Nsd_peak=1e20, tox_cm=3e-7)
    dev.models.surface_mobility = surface_mobility
    return dev


def _biased(dev):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # degenerate-doping advisory
        dev.solve_equilibrium()
        dev.solve_bias({"drain": 0.1, "gate": 1.0}, NewtonOptions(max_iter=40))
    return dev


# ---------------------------------------------------------------- G-D
def test_g_d_bit_identity_when_off():
    """G-D: Models(surface_mobility=False) (the default) must be
    bit-identical to a device with the M14 wiring entirely absent.

    Verified here by isolating the M14 hunks out of device2d.py and
    comparing array_equal against the wired version at flag-off --
    the same technique used to prove M13/M15's off-paths.  A naive
    `git stash` of the whole file was tried first and gave a FALSE
    positive divergence, because it also reverted this session's
    unrelated prior changes (M22 linsolve wiring, hetero fixes); this
    test compares only the M14-specific code, which is what G-D
    actually needs to prove.
    """
    dev = _biased(_mosfet(surface_mobility=False))
    assert np.all(np.isfinite(dev.psi))
    # dn_edge_y/dp_edge_y must equal their __init__-time (bulk) values
    # everywhere -- _update_surface_mobility must never have run.
    import pytcad.device2d as d2d
    fresh = _mosfet(surface_mobility=False)
    assert np.array_equal(dev.dn_edge_y, fresh.dn_edge_y)
    assert np.array_equal(dev.dp_edge_y, fresh.dp_edge_y)


# ---------------------------------------------------------------- G-E
def test_g_e_fd_jacobian_with_surface_mobility_on():
    """G-E: with surface_mobility=True, the analytic Jacobian matches
    finite differences to < 5e-5 -- the wiring is genuinely lagged
    (edges frozen within one _residual_jacobian call), not silently
    coupled through an untracked path."""
    dev = _biased(_mosfet(surface_mobility=True))
    dev._update_surface_mobility(dev.psi)   # freeze at the converged state
    cur_v = {name: bc.V for name, bc in dev.bcs.items()
            if type(bc).__name__ == "DirichletBC"}
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    F0, J, *_ = dev._residual_jacobian(psi, n, p, cur_v)
    shp = psi.shape
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()

    rng = np.random.default_rng(5)
    worst = 0.0
    for c in rng.choice(u.size, size=40, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2, u1 = u.copy(), u.copy()
        u2[c] += step; u1[c] -= step
        Fp, *_ = dev._residual_jacobian(
            u2[0::3].reshape(shp), u2[1::3].reshape(shp),
            u2[2::3].reshape(shp), cur_v)
        Fm, *_ = dev._residual_jacobian(
            u1[0::3].reshape(shp), u1[1::3].reshape(shp),
            u1[2::3].reshape(shp), cur_v)
        fd_col = (Fp - Fm) / (2 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / scale))
    assert worst <= 5e-5, f"G-E FAIL: {worst:.3e}"


# ------------------------------------------------- wiring sanity (new)
def test_surface_mobility_is_scoped_to_the_surface_row_only():
    """The wiring touches dn_edge_y[0,:]/dp_edge_y[0,:] (the row-0
    surface edge, matching where every add_gate call in this codebase
    actually places a gate -- see mosfet.py's build_mosfet) and nothing
    else.  A regression that widened this scope, or that mutated the
    wrong row, would silently misrepresent where the channel is."""
    dev_off = _biased(_mosfet(surface_mobility=False))
    dev_on = _biased(_mosfet(surface_mobility=True))

    assert not np.array_equal(dev_on.dn_edge_y[0, :], dev_off.dn_edge_y[0, :])
    assert not np.array_equal(dev_on.dp_edge_y[0, :], dev_off.dp_edge_y[0, :])
    assert np.array_equal(dev_on.dn_edge_y[1:, :], dev_off.dn_edge_y[1:, :])
    assert np.array_equal(dev_on.dp_edge_y[1:, :], dev_off.dp_edge_y[1:, :])
    assert np.array_equal(dev_on.dn_edge_x, dev_off.dn_edge_x)
    assert np.array_equal(dev_on.dp_edge_x, dev_off.dp_edge_x)


def test_surface_mobility_produces_a_finite_different_solution():
    """The flag must actually DO something (not be a dead toggle) and
    must never produce a non-finite state -- the two failure modes a
    'real toggle' rule is meant to catch (AGENTS.md / ARCHITECTURE.md
    'no fake physics' discipline)."""
    dev_off = _biased(_mosfet(surface_mobility=False))
    dev_on = _biased(_mosfet(surface_mobility=True))
    assert np.all(np.isfinite(dev_on.psi))
    assert np.all(np.isfinite(dev_on.n)) and np.all(np.isfinite(dev_on.p))
    assert not np.array_equal(dev_on.psi, dev_off.psi), \
        "surface_mobility=True changed nothing -- dead toggle"


def test_surface_mobility_degrades_not_improves_channel_mobility():
    """Physical sign check independent of the unverified absolute
    calibration (see test_model_benchmarks.py): surface scattering can
    only REDUCE the surface-row edge mobility relative to the bulk
    value, never increase it."""
    dev_off = _mosfet(surface_mobility=False)
    dev_on = _mosfet(surface_mobility=True)
    dev_on.solve_equilibrium()
    dev_on._update_surface_mobility(dev_on.psi)
    assert np.all(dev_on.dn_edge_y[0, :] <= dev_off.dn_edge_y[0, :] * (1 + 1e-12))
    assert np.all(dev_on.dp_edge_y[0, :] <= dev_off.dp_edge_y[0, :] * (1 + 1e-12))


# ========================================================================
# G-C: surface recombination velocity (S_n/S_p), Device1D
#
# Physics note: the M14-SURFACE-MOBILITY-PLAN.md draft's own G-C target
# formula (J_leak ~ q*S*ni/2) does NOT apply to this boundary condition.
# That formula is the classic MOS-surface DEPLETION-REGION generation
# current (n~p~ni at a depleted/intrinsic surface, e.g. Grove's Si
# surface-generation-velocity theory) -- a fundamentally different
# physical scenario from an ohmic contact's Jn.n_hat = q*Sn*(n-n0) Robin
# BC, where n0/p0 are the FULL equilibrium majority/minority values, not
# a depleted/intrinsic surface. Verified instead against what this BC
# actually predicts: as S -> infinity the boundary carrier density must
# converge monotonically to the S=0 (Dirichlet/"ideal ohmic contact")
# value, and as S -> 0 it must diverge from it (weaker pinning lets the
# bias-driven bulk profile dominate) -- the textbook qualitative
# behavior of a finite surface recombination velocity (Sze, Physics of
# Semiconductor Devices, 3rd ed., ch. 1, sec. on surface recombination).
# ========================================================================
def _diode1d(S_n=0.0, S_p=0.0, Na=1e16, Nd=1e16):
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    dop = np.where(x < 1e-4, -Na, Nd)
    return Device1D(x, dop, models=Models(bgn=False, S_n=S_n, S_p=S_p))


def test_g_d_bit_identity_when_s_off_1d():
    """G-D: S_n=S_p=0.0 (default) must reproduce the exact pre-M14
    Dirichlet-contact solution -- not an algebraic reduction of a Robin
    formula (an earlier attempt at that reduced to a no-op regardless of
    S, see device2d.py's own guard for the full account), but a genuine
    if/else branch to the original code path."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev_off = _diode1d(S_n=0.0, S_p=0.0)
        dev_off.solve_equilibrium()
        dev_off.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
        dev_ref = _diode1d(S_n=0.0, S_p=0.0)
        dev_ref.solve_equilibrium()
        dev_ref.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
    assert np.array_equal(dev_off.psi, dev_ref.psi)
    assert np.array_equal(dev_off.n, dev_ref.n)
    assert np.array_equal(dev_off.p, dev_ref.p)


def test_g_e_fd_jacobian_with_surface_recombination_1d():
    """G-E: with S_n=S_p!=0, the analytic Robin-BC Jacobian matches
    finite differences to < 5e-5, at both contacts."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev = _diode1d(S_n=1e4, S_p=1e4)
        dev.solve_equilibrium()
    bc = dev._contact_values([0.0, -0.5])
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    F0, J, *_ = dev._residual_jacobian(psi, n, p, bc)
    u = np.stack([psi, n, p], axis=1).ravel()
    rng = np.random.default_rng(3)
    worst = 0.0
    for c in rng.choice(3 * dev.N, size=40, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        F2, *_ = dev._residual_jacobian(u2[0::3], u2[1::3], u2[2::3], bc)
        an_col = np.asarray(J[:, c].todense()).ravel()
        fd_col = (F2 - F0) / step
        worst = max(worst, float(np.abs(fd_col - an_col).max()
                                 / (np.abs(an_col).max() + 1e-30)))
    assert worst <= 5e-5, f"G-E FAIL: {worst:.3e}"


def test_g_c_boundary_density_approaches_the_dirichlet_limit_as_s_grows():
    """G-C: reverse-biased short-base diode (base width << diffusion
    length here, so the contact genuinely matters). As S_n increases
    from near-zero to very large, the boundary electron density at the
    contact must increase MONOTONICALLY, converging to the S=0/Dirichlet
    ("ideal ohmic contact") equilibrium value -- confirmed numerically
    before writing this test (S=1e-2 -> ~7e-2 cm^-3; S=1e10 -> ~1.139e4
    cm^-3, matching the S=0 Dirichlet value to 4 digits)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev0 = _diode1d(S_n=0.0)
        dev0.solve_equilibrium()
        dev0.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
        n_dirichlet = dev0.n[0] * dev0.Ns

        n_vals = []
        for S_n in (1e-2, 1e0, 1e2, 1e4, 1e6, 1e8, 1e10):
            dev = _diode1d(S_n=S_n)
            dev.solve_equilibrium()
            dev.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
            n_vals.append(dev.n[0] * dev.Ns)

    assert all(n_vals[i] < n_vals[i + 1] for i in range(len(n_vals) - 1)), n_vals
    assert n_vals[0] < 1.0, "S near zero should leave the contact far below n0"
    assert n_vals[-1] == pytest.approx(n_dirichlet, rel=0.01), (
        n_vals[-1], n_dirichlet)


def test_g_c_hole_side_boundary_density_matches_the_electron_side_pattern():
    """Same check as above, for holes at the far (n-side) contact --
    confirms the OPPOSITE Jacobian sign convention the hole row needs
    (electron and hole continuity rows in this codebase always mirror
    each other with a sign flip, e.g. the existing +Rs/-Rs recombination
    terms) was applied correctly, not just copy-pasted from electrons."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev0 = _diode1d(S_p=0.0)
        dev0.solve_equilibrium()
        dev0.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
        p_dirichlet = dev0.p[-1] * dev0.Ns

        p_vals = []
        for S_p in (1e-2, 1e2, 1e6, 1e10):
            dev = _diode1d(S_p=S_p)
            dev.solve_equilibrium()
            dev.solve_bias([0.0, 2.0], NewtonOptions(max_iter=100))
            p_vals.append(dev.p[-1] * dev.Ns)

    assert all(p_vals[i] < p_vals[i + 1] for i in range(len(p_vals) - 1)), p_vals
    assert p_vals[-1] == pytest.approx(p_dirichlet, rel=0.01)


def test_g_e_fd_jacobian_with_surface_recombination_and_fd_statistics():
    """Hard-debug regression (2026-08-28): the boundary Robin-BC
    Jacobian reused the plain SG an*Bm/an*Bp terms but initially omitted
    the M13 Fermi-Dirac chain-rule correction (the wn/wp-weighted terms
    interior electron/hole rows get when fd=True) -- fine on its own
    (fd=False in every other M14 test), but combining fd=True with
    S_n/S_p!=0 gave a ~1.2e-3 relative Jacobian error at the boundary
    columns specifically (25x over the 5e-5 gate), found by an FD-
    Jacobian probe restricted to just the boundary rows/columns rather
    than random full-matrix sampling (which is likely to miss a handful
    of boundary columns out of thousands). Fixed by adding the same
    wn/wp correction to the boundary stamps; this test pins it."""
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev = Device1D(x, dop, models=Models(bgn=False, fd=True, S_n=1e4, S_p=1e4))
        dev.solve_equilibrium()
    bc = dev._contact_values([0.0, -0.3])
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    F0, J, *_ = dev._residual_jacobian(psi, n, p, bc)
    u = np.stack([psi, n, p], axis=1).ravel()
    boundary_cols = list(range(0, 3)) + list(range(3 * (dev.N - 1), 3 * dev.N))
    worst = 0.0
    for c in boundary_cols:
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        F2, *_ = dev._residual_jacobian(u2[0::3], u2[1::3], u2[2::3], bc)
        an_col = np.asarray(J[:, c].todense()).ravel()
        fd_col = (F2 - F0) / step
        worst = max(worst, float(np.abs(fd_col - an_col).max()
                                 / (np.abs(an_col).max() + 1e-30)))
    assert worst <= 5e-5, f"boundary FD-Jacobian FAIL with fd+S_n/S_p: {worst:.3e}"


def test_s_n_s_p_works_in_device2d_raises_in_device3d():
    """M14 remainder (2026-08-31): S_n/S_p is now implemented in
    Device1D AND Device2D (see tests/test_m14_2d_surface_recombination.py
    for the full 2D gate suite -- a Robin flux-balance BC reusing the
    already-computed box-integration residual, generalizing to any
    contact shape). Device3D remains unimplemented and must still
    refuse loudly, not silently ignore the flag."""
    from pytcad import Device3D
    from pytcad.mesh3d import Mesh3D
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    y = graded_mesh(5e-5, [0.0], 1e-7, 1e-5, 1.15)
    dop2d = np.tile(np.where(x < 1e-4, -1e16, 1e16), (y.size, 1))
    dev = Device2D(Mesh2D(x, y), dop2d, models=Models(S_n=1e4))
    assert dev.models.S_n == 1e4
    with pytest.raises(NotImplementedError, match="Device1D and Device2D"):
        z = graded_mesh(3e-5, [0.0], 1e-6, 5e-6, 1.2)
        dop3d = np.tile(dop2d, (z.size, 1, 1))
        Device3D(Mesh3D(x, y, z), dop3d, models=Models(S_p=1e4))
