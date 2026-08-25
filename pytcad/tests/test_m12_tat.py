"""M12-S2: trap-assisted tunneling -- acceptance tests (RED, pending).

Per TUNNELING-PLAN.md section 5: TAT extends the recombination block of
Device1D._residual_jacobian with SRH-sign-convention trap kinetics plus
WKB escape factors.  These tests are the NAMED FIRST RED TESTS; they are
skipped until the core lands so the standing suite stays green.

Model (Hurkx-style, IEEE TED 39, 2090 (1992)):
    R_TAT = (n*p - n_ie^2) * g(F)
          / [ tau_p*(n + n_1*P_p) + tau_n*(p + p_1*P_n) ]
with WKB escape factors P_n/P_p = exp(-2 int kappa dx) over the
barrier between trap and contact, kappa from the local field;
g(F) is the field-enhancement factor from the same integral.
Traps OFF must reproduce plain SRH bit-identically (P == 0 reduces
exactly), which is what test_traps_off_bit_identical pins once live.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import Models

@pytest.fixture
def diode():
    from pytcad.device import Device1D
    from pytcad.mesh import graded_mesh
    x = graded_mesh(2e-4, [1e-4], h_min=1e-8, h_max=1e-6)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return Device1D(x, doping, T=300.0,
                    models=Models(bgn=True, srh=True))


def test_fd_jacobian_with_traps_enabled(diode):
    """THE first red test: analytic Jacobian vs finite differences on a
    trap-enabled biased device, sampled densely around the junction."""
    dev = diode
    dev.models.tat = True
    dev.solve_equilibrium()
    dev.solve_bias([0.0, 0.2])
    bc = [(dev.psi[0], dev.n[0], dev.p[0]),
          (dev.psi[-1], dev.n[-1], dev.p[-1])]
    F, J, _, _ = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)

    rng = np.random.default_rng(7)
    scale = np.maximum(np.abs(F), 1.0)
    worst = 0.0
    for col in rng.choice(range(3 * dev.N), size=80, replace=False):
        idx, kind = col // 3, col % 3
        d = 1e-6 * max(abs(dev.psi[idx]), abs(dev.n[idx]),
                       abs(dev.p[idx]), 1e-12)
        pp, nn, pn = dev.psi.copy(), dev.n.copy(), dev.p.copy()
        [pp, nn, pn][kind][idx] += d
        Fp, _, _, _ = dev._residual_jacobian(pp, nn, pn, bc)
        fd = (Fp - F) / d
        ana = np.asarray(J[:, col].todense()).ravel()
        worst = max(worst, float(np.max(np.abs(fd - ana) / scale)))
    assert worst < 5e-5, f"FD-vs-analytic worst relative error {worst:.3e}"


def test_traps_off_bit_identical(diode):
    """With tat=False the residual/Jacobian pair must be EXACTLY the
    SRH one -- same arrays, not just close."""
    dev = diode
    dev.solve_equilibrium()
    dev.solve_bias([0.0, 0.15])
    bc = [(dev.psi[0], dev.n[0], dev.p[0]),
          (dev.psi[-1], dev.n[-1], dev.p[-1])]
    F_srh, J_srh, _, _ = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    dev.models.tat = True
    F_tat, J_tat, _, _ = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    assert np.array_equal(F_srh, F_tat)
    assert (J_srh != J_tat).nnz == 0


def test_charge_neutrality_with_traps(diode):
    """Integrated bulk charge still balances the gate/contact charge --
    TAT moves carriers between bands, never creates net charge."""
    dev = diode
    dev.models.tat = True
    dev.solve_equilibrium()
    e = np.clip(dev.psi, -700, 700)
    rho_scaled = (dev.nie_s * np.exp(e) - dev.nie_s * np.exp(-e)
                  - dev.C)
    # equilibrium neutrality holds node-wise up to the update-based
    # Newton tolerance, judged RELATIVE to the local carrier scale
    carrier_scale = float(np.max(dev.n + dev.p))
    worst = float(np.max(np.abs(rho_scaled)))
    assert worst < 1e-4 * carrier_scale, \
        f"neutrality residual {worst:.3e} vs carrier scale {carrier_scale:.3e}"


def test_silc_style_field_enhancement_monotone(diode):
    """Published SILC/TAT behaviour: the field-enhancement factor
    (SRH denominator / TAT denominator) grows MONOTONICALLY with
    reverse-bias field.  Quantitative values reported on failure."""
    dev = diode
    dev.models.tat = True
    enhancements = []
    for vr in (-1.0, -2.0, -4.0):
        dev.solve_bias([0.0, vr])
        assert dev._Pn is not None
        den_srh = (dev.tau_p * dev.n + dev.tau_n * dev.p)
        den_tat = (dev.tau_p * (dev.n + dev.nie * dev._Pp)
                   + dev.tau_n * (dev.p + dev.nie * dev._Pn))
        enh = float(np.max(den_srh / den_tat))
        enhancements.append(enh)
    print("enhancements:", [f"{e:.3e}" for e in enhancements])
    assert all(e > 1.0 for e in enhancements), \
        f"TAT enhancement below unity: {enhancements}"
    assert enhancements[0] < enhancements[1] < enhancements[2], \
        f"enhancement not monotone with field: {enhancements}"
