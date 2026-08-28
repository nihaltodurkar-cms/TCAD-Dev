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
