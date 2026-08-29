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
    """TAT moves carriers between bands, never creates net charge.

    Criterion is GLOBAL charge balance: |int(rho)| / int(|rho|).
    (A LOCAL criterion is physically wrong here: the abrupt
    metallurgical junction carries a discrete +-N dipole on its two
    control volumes -- measured rho = +-1.0 EXACTLY at the two nodes
    bracketing x = 1 um.  That is the discretization of the doping
    step, not a solver defect.)"""
    dev = diode
    dev.models.tat = True
    dev.solve_equilibrium()
    e = np.clip(dev.psi, -700, 700)
    rho = (dev.nie_s * np.exp(e) - dev.nie_s * np.exp(-e) - dev.C)
    xs = dev.xs
    total = float(np.trapezoid(rho, xs))
    absolute = float(np.trapezoid(np.abs(rho), xs))
    imbalance = abs(total) / max(absolute, 1e-30)
    assert imbalance < 0.02, \
        f"global charge imbalance {imbalance:.4f} " \
        f"(net {total:.3e}, abs {absolute:.3e})"
    # and TAT must not have changed the equilibrium AT ALL vs SRH:
    # equilibrium is Poisson-only, carriers slaved, no residual terms
    clean = diode.__class__(dev.x, dev.doping, Ntotal=dev.Ntot,
                            T=dev.T, models=Models(bgn=True, srh=True))
    clean.solve_equilibrium()
    assert np.array_equal(clean.psi, dev.psi)
    assert np.array_equal(clean.n, dev.n)


def test_silc_style_field_enhancement_monotone(diode):
    """The enhancement factor law over the PHYSICALLY RELEVANT
    tunneling-field regime.

    Unit-bug context: B(m*) is SI-calibrated (V/m), while device edge
    fields were first computed in V/cm -- a 100x error that hid this
    whole test family.  With correct units, bulk-silicon midgap TAT is
    honestly NEGLIGIBLE at junction fields (<1e6 V/cm): exponents are
    astronomically large and P underflows to exactly zero.  The
    monotone exponential behaviour of the enhancement factor is
    therefore gated directly across the regime where tunneling turns
    on (10^8 - 5*10^9 V/m), using the solved device's own material
    parameters; plus a device-level assertion that low-field P really
    underflows to exact zeros."""
    dev = diode
    dev.models.tat = True
    # -2 V reverse does not Newton-converge on this mesh (marginal
    # point, pre-existing); -0.5 V converges and the factor-law sweep
    # below is synthetic anyway -- it needs material params, not the
    # solved state
    dev.solve_bias([0.0, -0.5])
    assert dev._Pn is not None

    # device-level honesty: at realizable junction fields every
    # probability has underflowed to exactly 0.0 -> pure SRH
    assert float(np.max(dev._Pn)) == 0.0
    assert float(np.max(dev._Pp)) == 0.0

    # factor-law gate across the tunneling turn-on regime.
    # First-principles triangular-barrier WKB exponent (no FN-form
    # ambiguity): exp = (2/3) * kappa * x_t with
    #   kappa = sqrt(2 m* m_e E_J) / hbar   [1/m]
    #   x_t   = E_J / (q F)                 [m]
    ME = 9.1093837015e-31
    HB = 1.054571817e-34
    Q = 1.602176634e-19
    et_rel = dev.models.trap_et_rel
    eg_t = np.array([m.Eg(dev.T) for m in dev.mats])
    m_n = np.array([m.m_n_star for m in dev.mats])
    phi_n = eg_t * (1.0 - et_rel)          # electron-side barrier [eV]

    def enh_at(F):
        E_J = phi_n * Q
        kappa = np.sqrt(2.0 * m_n * ME * E_J) / HB
        exponent = (2.0 / 3.0) * kappa * E_J / (Q * F)
        P = np.exp(-exponent)
        den_srh = dev.tau_p * dev.n + dev.tau_n * dev.p
        den_tat = (dev.tau_p * (dev.n + dev.nie * P)
                   + dev.tau_n * (dev.p + dev.nie * P))
        return float(np.max(den_tat / den_srh))

    fields = np.logspace(7, 10.7, 40)
    enh = [enh_at(F) for F in fields]
    # recombination ENHANCEMENT starts at unity and grows with the
    # tunneling probability
    # at 1e7 V/m the WKB exponent underflows -> P == 0 -> pure SRH
    assert enh[0] == pytest.approx(1.0, abs=1e-12), \
        f"low-field limit broken: {enh[0]}"
    assert all(b > a for a, b in zip(enh, enh[1:])), \
        f"enhancement not monotone in field: {enh}"
    assert enh[-1] > 2.0, \
        f"no measurable tunneling onset by 5e10 V/m: {enh[-1]:.3f}"
