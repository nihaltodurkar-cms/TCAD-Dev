"""M34-S7 gate: Device1D's stiff-path Newton solves end at a fixed point.

M34-S6 found (M34-S6-PLAN.md section 5) that Device1D.solve_bias, with a
generation model on (impact / btbt / btbt_nonlocal -- the paths that run
M15's strength ladder and backtracking line search), judged convergence
on the line-search-DAMPED update.  A small step passes that test with the
Newton correction still large: on M15's own diode at -30V the returned
state carried 0.698 of the discrete solution's current (M = 1.066
reported, 1.5275 at the fixed point), its full correction still 6e-6.

The gate: the state solve_bias returns is a fixed point of the device's
own undamped Newton step -- the full correction, in the M11-S5 floored
metric the stiff paths now use, is below 1e-6, and the contact current
does not move (1e-8).  The raw (unfloored) metric cannot be the test:
measured, it sits at O(1) on the n+ side's p ~ 1e-19 holes at every step.
"""
import os
import sys
import warnings

import numpy as np
import pytest
from scipy.sparse.linalg import spsolve

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.dirichlet import eliminate_csr
from pytcad.mesh import graded_mesh


def _m15():
    """M15's one-sided junction (test_m15_ionization's _diode geometry)."""
    x = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=4e-6)
    return Device1D(x, np.where(x < 3.0e-4, -1e16, 1e19), T=300.0,
                    models=Models(bgn=False, srh=True, impact=True))


def _tunnel(**flag):
    """test_m16_btbt / test_m34_s1_nonlocal_btbt's 5e19 tunnel diode."""
    x = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
    return Device1D(x, np.where(x < 5.0e-6, -5e19, 5e19), T=300.0,
                    models=Models(bgn=False, srh=True, **flag))


CASES = {
    "M15-impact": (_m15, np.arange(2.0, 30.0 + 1e-9, 2.0)),
    "M16-btbt": (lambda: _tunnel(btbt=True), np.arange(0.2, 1.2 + 1e-9, 0.2)),
    "M34-btbt_nonlocal": (lambda: _tunnel(btbt_nonlocal=True),
                          np.arange(0.5, 2.0 + 1e-9, 0.5)),
}


@pytest.mark.parametrize("case", list(CASES))
def test_solve_bias_returns_a_newton_fixed_point(case):
    make, biases = CASES[case]
    dev = make()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for v in biases:
            dev.solve_bias([-float(v), 0.0], NewtonOptions())
            assert dev.last_converged, f"{case}: no convergence at -{v} V"
    bc = dev._contact_values([-float(biases[-1]), 0.0])
    psi, n, p = dev.psi, dev.n, dev.p
    F, J, Jn, Jp = dev._residual_jacobian(psi, n, p, bc)
    j0 = Jn[0] + Jp[0]
    Jd, rhs = eliminate_csr(J, -F, dev._dirichlet_rows)
    du = spsolve(Jd.tocsc(), rhs)
    n1 = np.clip(n + du[1::3], 0.1 * n, 10.0 * n)
    p1 = np.clip(p + du[2::3], 0.1 * p, 10.0 * p)
    corr = max(np.abs(du[0::3]).max(),
               (np.abs(n1 - n) / np.maximum(n, 1e-10)).max(),
               (np.abs(p1 - p) / np.maximum(p, 1e-10)).max())
    _, _, Jn1, Jp1 = dev._residual_jacobian(psi + du[0::3], n1, p1, bc)
    moved = abs((Jn1[0] + Jp1[0]) / j0 - 1.0)
    assert corr < 1e-6 and moved < 1e-8, \
        f"{case}: full correction {corr:.2e}, current moved {moved:.2e}"
