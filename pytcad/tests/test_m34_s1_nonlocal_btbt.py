"""M34-S1 gates: nonlocal path Kane BTBT in Device1D.

See pytcad/M34-PLAN.md section 2 (current design) and M34-S1-PLAN.md
(history). Gate map:
  G1  test_g1_off_bit_identity             default-off bit-identity
  G2  tests/test_model_benchmarks.py       exact uniform-field reduction
  G3  test_g3_transmission_bracketed       WKB exponent between the
                                           uniform-field values at the
                                           path's extreme fields
  G4  test_g4_fd_jacobian[_all_columns]    analytic vs FD Jacobian, 5e-5
  G4b test_g4b_jacobian_sparsity           entries only in own rows/cols
  G5  test_g5_pair_conservation            one electron per hole
  G6  test_g6_bias_ramp_converges          0.5V and 0.25V ramps
  G6b test_g6b_path_independence           both ramps, same -6V state
  G7  tests/test_model_benchmarks.py       tunnel length vs Eg/(qF)
test_g2_nonlocal_produces_a_real_nonzero_effect predates the plan's
numbering (a sanity floor, not the plan's G2).

Do not loosen the 5e-5 FD tolerance to make a red G4 pass.
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


def _ramp(step, stop=-6.0):
    """0 -> stop in `step` volts; returns (device, list of non-converged V)."""
    dev = _tunnel_diode(btbt_nonlocal=True)
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for V in np.arange(-step, stop - 1e-9, -step):
            dev.solve_bias([float(V), 0.0], NewtonOptions())
            if not dev.last_converged:
                bad.append(round(float(V), 3))
    return dev, bad


def _on_off_at(V):
    """A converged btbt_nonlocal=True state at bias V (reached by a 0.5V
    ramp), a plain device on the SAME mesh/doping, and both
    residual/Jacobian pairs evaluated at that one state with the paths
    re-located there."""
    dev_on, bad = _ramp(0.5, V)
    assert not bad, f"ramp to {V} did not converge at {bad}"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev_off = Device1D(dev_on.x, dev_on.C * dev_on.Ns, T=300.0,
                           models=Models(bgn=False, srh=True))
        psi, n, p = dev_on.psi.copy(), dev_on.n.copy(), dev_on.p.copy()
        bc = dev_on._contact_values([V, 0.0])
        dev_on._btbt_nl_paths = None
        F_on, J_on, _, _ = dev_on._residual_jacobian(psi, n, p, bc)
        F_off, J_off, _, _ = dev_off._residual_jacobian(psi, n, p, bc)
    return dev_on, (psi, n, p, bc), (F_on, J_on), (F_off, J_off)


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
    """Sanity floor: the nonlocal term must actually move the solution
    on a real diode at high reverse bias."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev_off = _tunnel_diode(btbt_nonlocal=False)
        dev_off.solve_equilibrium()
        dev_off.solve_bias([-6.0, 0.0], NewtonOptions())
    dev_on, bad = _ramp(0.5)
    assert not bad
    assert np.abs(dev_off.psi - dev_on.psi).max() > 1.0e-3


def test_segment_integrals_finite_on_adversarial_inputs():
    """The exact WKB segment integrals and their derivatives stay FINITE
    and non-negative for any finite (da, db): denormal-small deltas at a
    turning point, exact band edges, flat and near-flat segments, values
    far outside the gap. A Newton iterate can wander anywhere, and one
    inf times the strength ladder's zero is a NaN residual (a 0.25V
    ramp died that way at -0.75V, 2026-09-11)."""
    from pytcad.btbt import segment_integrals, M0_SI, Q_SI
    rng = np.random.default_rng(1)
    vals = np.concatenate([
        [0.0, 1.0, 5e-324, 1e-310, 1e-300, 1e-30, 1e-12, 1e-11,
         1.0 - 1e-16, 1.0 + 1e-16, 1.0 - 1e-11, -1e-300, 0.5,
         0.5 + 1e-11, -3.0, 7.0],
        rng.uniform(-2.0, 3.0, 150)])
    da, db = np.meshgrid(vals, vals)
    da, db = da.ravel(), db.ravel()
    L = np.full(da.shape, 1e-9)
    # underflow to a denormal is benign; divide/invalid/overflow are not
    with np.errstate(divide="raise", invalid="raise", over="raise"):
        out = segment_integrals(da, db, L, 1.12 * Q_SI, 0.1554 * M0_SI)
    for o in out:
        assert np.all(np.isfinite(o))
    assert np.all(out[0] >= 0.0) and np.all(out[1] >= 0.0)


@pytest.mark.parametrize("V", [-3.0, -6.0])
def test_g3_transmission_bracketed(V):
    """For a band that is piecewise linear along the path, the exact
    WKB exponent 2*int(kappa ds) is a harmonic mean over the segment
    fields of the uniform-field exponent, so it must lie between eq
    (8)'s exponent at the path's MAX and MIN barrier field. A theorem
    about the quadrature, not a calibration."""
    dev, (psi, *_), _, _ = _on_off_at(V)
    from pytcad.btbt import M0_SI, HBAR_SI, Q_SI
    mat = dev.mats[0]
    mc, mv = mat.m_n_star * M0_SI, mat.m_p_star * M0_SI
    mr = 1.0 / (1.0 / mc + 1.0 / mv)
    Eg = mat.Eg(dev.T) * Q_SI
    ev = dev._btbt_nl_eval(psi)
    assert ev.reached.all() and ev.G.size > 0

    def expo(F):
        return np.pi * np.sqrt(mr) * Eg ** 1.5 / (2.0 * Q_SI * F * HBAR_SI)
    two_ik = 2.0 * ev.Ik
    assert np.all(two_ik >= expo(ev.fmax) * (1.0 - 1e-12))
    assert np.all(two_ik <= expo(ev.fmin) * (1.0 + 1e-12))


def test_g4_fd_jacobian():
    """Analytic vs finite-difference Jacobian at the house 5e-5
    tolerance (M15/M16/M20's own FD gates), 60 random psi columns at
    -6V. This was the M34-S1 blocker (7.4e-3, start-node column
    missing) until 2026-09-11. Do not raise the tolerance to make this
    pass; fix the Jacobian."""
    dev, (psi, n, p, bc), (F0, J0), _ = _on_off_at(-6.0)
    paths = dev._btbt_nl_paths
    eps = 1e-6
    rng = np.random.default_rng(0)
    cols = rng.choice(dev.N, size=min(60, dev.N), replace=False)
    worst = 0.0
    for k in cols:
        psi2 = psi.copy()
        psi2[k] += eps
        dev._btbt_nl_paths = paths      # frozen, as within one Newton solve
        F1, _, _, _ = dev._residual_jacobian(psi2, n, p, bc)
        fd_col = (F1 - F0) / eps
        an_col = np.asarray(J0[:, 3 * k].todense()).flatten()
        denom = max(np.abs(fd_col).max(), np.abs(an_col).max(), 1e-300)
        worst = max(worst, np.abs(fd_col - an_col).max() / denom)
    assert worst < 5e-5, (
        f"M34-S1 FD-Jacobian gate: worst relative mismatch {worst:.3e} "
        f"> 5e-5. See M34-PLAN.md -- do not loosen this tolerance.")


@pytest.mark.parametrize("V", [-2.0, -4.0, -6.0])
def test_g4_fd_jacobian_all_columns(V):
    """Same FD gate on EVERY psi column (a random sample can miss the
    few path start nodes that carried the original defect) across the
    reverse-bias range, paths frozen as within one Newton solve.
    Nonempty paths are asserted so the gate cannot pass vacuously."""
    dev, (psi, n, p, bc), (F0, J0), _ = _on_off_at(V)
    paths = dev._btbt_nl_paths
    assert paths.n_paths > 0
    eps = 1e-6
    worst = 0.0
    for k in range(dev.N):
        psi2 = psi.copy()
        psi2[k] += eps
        dev._btbt_nl_paths = paths
        F1, _, _, _ = dev._residual_jacobian(psi2, n, p, bc)
        fd_col = (F1 - F0) / eps
        an_col = np.asarray(J0[:, 3 * k].todense()).flatten()
        denom = max(np.abs(fd_col).max(), np.abs(an_col).max(), 1e-300)
        worst = max(worst, np.abs(fd_col - an_col).max() / denom)
    assert worst < 5e-5, f"V={V}: worst relative mismatch {worst:.3e}"


def test_g4b_jacobian_sparsity():
    """The nonlocal block touches only: the hole row of each path's
    start node, and the electron rows of the nodes its crossing can
    move over (its own span); and only psi columns the path reads (its
    span, its start-gradient stencil, and the global psi extrema that
    set eq (12)'s km^2). It never depends on n or p."""
    dev, (psi, *_), (_, J_on), (_, J_off) = _on_off_at(-6.0)
    paths = dev._btbt_nl_paths
    assert paths.n_paths > 0
    ext = {3 * int(np.argmin(psi)), 3 * int(np.argmax(psi))}
    allowed = {}
    for p in range(paths.n_paths):
        nodes = paths.nodes_of_path(p)
        cols = set(3 * nodes) | ext
        allowed.setdefault(3 * int(paths.start[p]) + 2, set()).update(cols)
        for nd in nodes:
            allowed.setdefault(3 * int(nd) + 1, set()).update(cols)
    dJ = (J_on - J_off).tocoo()
    nz = dJ.data != 0.0
    assert nz.any()
    for r, c in zip(dJ.row[nz], dJ.col[nz]):
        assert c in allowed.get(r, ()), f"unexpected entry ({r}, {c})"


@pytest.mark.parametrize("V", [-2.0, -6.0])
def test_g5_pair_conservation(V):
    """One tunneling event makes exactly one electron-hole pair
    (Esseni 2017 section 2.1, eq (1) and figure 2). The box-integrated
    electron injection summed over the device must equal the hole
    injection. Before 2026-09-11 the electron row was weighted by
    dV[j0] instead of dV[i0]: 26% more electrons than holes at -6V."""
    dev, (psi, *_), (F_on, _), (F_off, _) = _on_off_at(V)
    ev = dev._btbt_nl_eval(psi)
    assert ev.G.size > 0
    # Dirichlet stamping would overwrite a deposit on a contact row.
    dep_nodes = ev.dep.tocoo().col
    assert dep_nodes.min() >= 1 and dep_nodes.max() <= dev.N - 2
    assert dev._btbt_nl_paths.start.min() >= 1
    d = F_on - F_off
    assert np.all(d[0::3] == 0.0)             # Poisson rows untouched
    electrons = d[1::3].sum()
    holes = -d[2::3].sum()
    assert electrons > 0.0
    assert electrons == pytest.approx(holes, rel=1e-12)


@pytest.mark.parametrize("step", [0.5, 0.25])
def test_g6_bias_ramp_converges(step):
    """solve_bias with btbt_nonlocal=True converges at every step of a
    0 -> -6V ramp, and the converged state is consistent with its own
    tunnel paths (re-located after convergence: same start set, no
    truncated path). Before the exact quadrature the 0.25V ramp failed
    EARLIER than the 0.5V one (-1.25V vs -5.5V). A ramp rather than a
    direct solve: a direct 0 -> -5V solve stalls in the strength
    ladder's 0.0 stage for M15 and M16 alike (pre-existing)."""
    dev, bad = _ramp(step)
    assert not bad, f"no convergence at V={bad}"
    assert dev.last_btbt_nl_stable
    assert dev._btbt_nl_paths.n_paths > 0


def test_g6b_path_independence():
    """The -6V state must not depend on how it was reached: every
    potential-dependent quantity is live and the paths are re-located
    at the converged state, so a 0.5V ramp and a 0.25V ramp must agree
    to Newton tolerance.

    Densities are compared against the local total carrier density
    n + p, not relative to themselves. Deep-minority holes on the n+
    side sit at p ~ 3e-20 (scaled; ~1 cm^-3), where their rows'
    residual contribution is far below the other rows' round-off, so
    their RELATIVE value is undetermined in double precision; plain
    drift-diffusion shares that property. Measured 2026-09-11: psi
    agrees to 7e-15, |dn|, |dp| to ~1e-15 of n + p, and the terminal
    current exactly, while p/p differs by 23% at those nodes."""
    a, bad_a = _ramp(0.5)
    b, bad_b = _ramp(0.25)
    assert not bad_a and not bad_b
    tot = a.n + a.p
    assert np.abs(a.psi - b.psi).max() < 1e-9
    assert (np.abs(a.n - b.n) / tot).max() < 1e-9
    assert (np.abs(a.p - b.p) / tot).max() < 1e-9
    ja, jb = a.current_density()[0], b.current_density()[0]
    assert ja == pytest.approx(jb, rel=1e-9)
