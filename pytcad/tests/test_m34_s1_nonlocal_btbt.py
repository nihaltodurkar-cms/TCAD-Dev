"""M34-S1 gates: nonlocal path Kane BTBT in Device1D.

STATUS: NOT SIGNED OFF -- see pytcad/M34-S1-PLAN.md sections 6/7.
`Models(btbt_nonlocal=True)` is wired into device.py and produces a
real, non-negligible physical effect on a real reverse-biased diode
(confirmed directly), and is bit-identical off-path (G1 below), but
the analytic Jacobian has NOT been shown to match a finite-difference
probe to this project's house tolerance (5e-5, see e.g. test_m16_btbt.py
and test_m15_ionization.py's own FD-Jacobian gates). test_g4_fd_jacobian
below is an OPENLY FAILING test recording that gap as the explicit
blocker per CLAUDE.md's dirty-tree rule ("Working tree may be left
dirty ONLY with openly-failing tests and a precise handoff note in
history.md") -- it is deliberately NOT xfail'd: this is an internal
implementation gap to be fixed, not an external blocker to accept
(contrast M14 G-A's paywall xfail).

Do not loosen this test's tolerance to make it pass, and do not treat a
green run of this file as sign-off for M34-S1 -- the whole point of
this test is that it stays red until the Jacobian is actually fixed
(most likely suspect per the plan: the kappa-floor edge exclusion that
fixed two real singularity bugs may also be silently dropping a small
but nonzero FD-visible sensitivity through the excluded edges).
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.mesh import graded_mesh


def _tunnel_diode(btbt_nonlocal=False, na=5e19, nd=5e19):
    x = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
    dop = np.where(x < 5.0e-6, -na, nd)
    return Device1D(x, dop, T=300.0,
                     models=Models(bgn=False, srh=True,
                                   btbt_nonlocal=btbt_nonlocal))


def test_g1_off_bit_identity():
    """Models(btbt_nonlocal=False) is bit-identical to the plain
    solver -- the same default-off convention every prior milestone's
    gate list opens with (M15 G-A, M16 G-A)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev_a = _tunnel_diode(btbt_nonlocal=False)
        dev_a.solve_equilibrium()
        dev_a.solve_bias([-2.0, 0.0], NewtonOptions())

        dev_b = Device1D(dev_a.x, dev_a.C * dev_a.Ns, T=300.0,
                          models=Models(bgn=False, srh=True))
        dev_b.solve_equilibrium()
        dev_b.solve_bias([-2.0, 0.0], NewtonOptions())
    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)


def test_g2_nonlocal_produces_a_real_nonzero_effect():
    """Sanity floor before the Jacobian gate below even matters: the
    nonlocal term must actually move the solution on a real diode at
    high reverse bias (confirmed directly during implementation --
    this pins that finding as a permanent regression check). Threshold
    is the actually-measured single-shot (-6V direct from equilibrium,
    no bias ramp) effect size, ~0.017, not a round number -- a
    bias-ramped run showed a much larger effect (~4.8) but that is a
    different, path-dependent Newton state, not this test's setup."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev_off = _tunnel_diode(btbt_nonlocal=False)
        dev_off.solve_equilibrium()
        dev_off.solve_bias([-6.0, 0.0], NewtonOptions())

        dev_on = _tunnel_diode(btbt_nonlocal=True)
        dev_on.solve_equilibrium()
        dev_on.solve_bias([-6.0, 0.0], NewtonOptions())
    assert dev_on.last_converged
    assert np.abs(dev_off.psi - dev_on.psi).max() > 1.0e-3


def test_g4_fd_jacobian():
    """OPENLY FAILING -- the explicit M34-S1 blocker (see module
    docstring and M34-S1-PLAN.md section 7). Worst-case relative
    mismatch measured 2026-09-11: ~7.4e-3 (0.74%), vs. this project's
    house FD-Jacobian tolerance of 5e-5 used throughout M15/M16/M20.
    Do not raise the tolerance to make this pass -- fix the Jacobian,
    most likely the kappa-floor edge exclusion in
    Device1D._btbt_nl_window_contribution / btbt.nonlocal_btbt_window
    silently dropping a nonzero FD-visible sensitivity.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev = _tunnel_diode(btbt_nonlocal=True)
        dev.solve_equilibrium()
        dev.solve_bias([-6.0, 0.0], NewtonOptions())
        psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
        bc = dev._contact_values([-6.0, 0.0])
        dev._btbt_nl_window = None
        F0, J0, _, _ = dev._residual_jacobian(psi, n, p, bc)
        windows = dev._btbt_nl_window

    eps = 1e-6
    rng = np.random.default_rng(0)
    cols = rng.choice(dev.N, size=min(60, dev.N), replace=False)
    worst = 0.0
    for k in cols:
        psi2 = psi.copy()
        psi2[k] += eps
        dev._btbt_nl_window = windows   # frozen, as within one Newton iterate
        F1, _, _, _ = dev._residual_jacobian(psi2, n, p, bc)
        fd_col = (F1 - F0) / eps
        an_col = np.asarray(J0[:, 3 * k].todense()).flatten()
        denom = max(np.abs(fd_col).max(), np.abs(an_col).max(), 1e-300)
        worst = max(worst, np.abs(fd_col - an_col).max() / denom)

    assert worst < 5e-5, (
        f"M34-S1 FD-Jacobian gate FAILS as expected (blocker, not a "
        f"regression): worst relative mismatch {worst:.3e} > 5e-5. "
        f"See M34-S1-PLAN.md section 8 -- do not sign off, do not "
        f"loosen this tolerance.")
