"""M34-S2 gates: nonlocal (effective-field) impact ionization, Device1D.

See pytcad/M34-PLAN.md section 3 and pytcad/ii_nonlocal.py.  The
published-value gates (lambda_e = 650 A from Slotboom et al. IEDM 1991,
the relaxation equation's step response, the uniform-field reduction,
the narrow-peak lag) live in tests/test_model_benchmarks.py.  This file
gates the coupling into Device1D: default-off identity, refusals, the
analytic Jacobian (M15 G-B methodology), the lambda -> 0 limit,
Slotboom's narrow-peak claim on a real junction, the plateau limit, and
convergence.  Every threshold below was set from a measured value
(2026-09-11), quoted in its docstring.
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
from pytcad.ionization import alpha_n, alpha_p, E_SWITCH_N, E_SWITCH_P
from pytcad.ii_nonlocal import effective_field, LAMBDA_E_SLOTBOOM_CM

LAM = LAMBDA_E_SLOTBOOM_CM


def _diode(h_max=4e-6, **m):
    """M15's one-sided abrupt junction (1e16 / 1e19), coarse mesh."""
    x = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=h_max)
    return Device1D(x, np.where(x < 3.0e-4, -1e16, 1e19), T=300.0,
                    models=Models(bgn=False, srh=True, **m))


def _ramp(dev, vmax, step=2.0):
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for v in np.arange(step, vmax + 1e-9, step):
            dev.solve_bias([-float(v), 0.0], NewtonOptions())
            if not dev.last_converged:
                bad.append(float(v))
    return bad


def _generation(dev, En, Ep):
    """Total II generation [scaled, box-integrated] at dev's state with
    the coefficients evaluated at the given node fields."""
    gs = dev._ii_compute_gs_frozen(dev.psi, dev.n, dev.p,
                                   alpha_n(En), alpha_p(Ep))
    return float(np.sum(gs[1:-1] * dev.dV[1:-1]))


@pytest.fixture(scope="module")
def s2_at_40():
    dev = _diode(impact=True, impact_nonlocal=True)
    return dev, _ramp(dev, 40.0)


@pytest.fixture(scope="module")
def local_at_40():
    dev = _diode(impact=True)
    return dev, _ramp(dev, 40.0)


def test_default_off_is_the_local_model():
    """impact_nonlocal defaults off, and an explicit False is the M15
    local model bit for bit."""
    assert Models().impact_nonlocal is False
    a = _diode(impact=True)
    b = _diode(impact=True, impact_nonlocal=False)
    assert not _ramp(a, 10.0) and not _ramp(b, 10.0)
    assert np.array_equal(a.psi, b.psi)
    assert np.array_equal(a.n, b.n)
    assert np.array_equal(a.p, b.p)


def test_requires_impact_and_a_positive_lambda():
    """The effective field only modifies the local impact model's
    coefficients: without impact=True the flag would silently do
    nothing, so it is refused; so is a non-positive length."""
    with pytest.raises(ValueError, match="impact=True"):
        _diode(impact_nonlocal=True)
    with pytest.raises(ValueError, match="> 0"):
        _diode(impact=True, impact_nonlocal=True, impact_lambda_n=0.0)


def test_device2d_and_device3d_refuse():
    """Device2D/Device3D have no coupled impact model to modify; the
    flag must raise, not be silently dropped (the M16 G-F pattern)."""
    from pytcad.mesh import uniform_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.device2d import Device2D
    from pytcad.device3d import Device3D
    from pytcad.mesh3d import Mesh3D
    mesh2d = Mesh2D(x=uniform_mesh(1e-4, 4), y=uniform_mesh(1e-4, 4))
    with pytest.raises(NotImplementedError, match="impact_nonlocal"):
        Device2D(mesh2d, np.full((5, 5), 1e15),
                 models=Models(impact_nonlocal=True))
    mesh3d = Mesh3D(x=uniform_mesh(1e-4, 2), y=uniform_mesh(1e-4, 2),
                    z=uniform_mesh(1e-4, 2))
    with pytest.raises(NotImplementedError, match="impact_nonlocal"):
        Device3D(mesh3d, np.full((3, 3, 3), 1e15),
                 models=Models(impact_nonlocal=True))


def test_reverse_ramp_converges_and_generation_is_live(s2_at_40):
    """A 2V-step reverse ramp to -40V converges at every step, and the
    generation the solver integrated is non-zero and finite."""
    dev, bad = s2_at_40
    assert not bad, f"no convergence at {bad}"
    gs = dev._ii_gs_cache
    assert gs is not None and np.all(np.isfinite(gs)) and gs.max() > 0.0


def test_fd_jacobian_m15_method(s2_at_40):
    """Analytic vs central FD with the M15 G-B methodology (randomly
    perturbed state, column-max normalization, 5e-5), on EVERY column
    rather than a sample.  The probe state must avoid both carriers'
    vOdM branch switches, for the effective field as well as the local
    one.

    One deliberate change from M15's probe: density columns step by
    1e-7*max(|u|, 1e-4) instead of 1e-7*max(|u|, 1).  An absolute 1e-7
    step is not small where n ~ 2e-6 sits beside an edge whose Jn
    crosses zero (the |J| smoothing's curvature): measured at node 91 at
    -40V, the FD error falls 1.1e-3 -> 3.4e-6 -> 3.2e-10 for steps
    1e-7 -> 1e-9 -> 1e-11, i.e. central-difference truncation, not a
    Jacobian error.  The 1e-4 floor keeps deep-minority columns
    (n ~ 1e-22) out of round-off: a purely relative step (1e-28 there)
    put the FD error at ~1e2."""
    dev, bad = s2_at_40
    assert not bad
    rng = np.random.default_rng(17)
    bc = dev._contact_values([-40.0, 0.0])
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.N)
    n = dev.n * (1 + 1e-3 * rng.standard_normal(dev.N))
    p = dev.p * (1 + 1e-3 * rng.standard_normal(dev.N))
    psi[0], psi[-1] = bc[0][0], bc[1][0]
    En = effective_field(dev.x, psi, dev.VT, LAM, "n")
    Ep = effective_field(dev.x, psi, dev.VT, LAM, "p")
    assert np.abs(En / E_SWITCH_N - 1.0).min() > 0.02
    assert np.abs(Ep / E_SWITCH_P - 1.0).min() > 0.02
    F0, J, *_ = dev._residual_jacobian(psi, n, p, bc)
    u = np.stack([psi, n, p], axis=1).ravel()
    worst = 0.0
    for c in range(u.size):
        step = (1e-7 * max(abs(u[c]), 1.0) if c % 3 == 0
                else 1e-7 * max(abs(u[c]), 1e-4))
        u2 = u.copy()
        u2[c] += step
        u1 = u.copy()
        u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3], u2[1::3], u2[2::3], bc)
        Fm_, *_ = dev._residual_jacobian(u1[0::3], u1[1::3], u1[2::3], bc)
        fd = (Fp_ - Fm_) / (2.0 * step)
        an = np.asarray(J[:, c].todense()).ravel()
        worst = max(worst, float(np.abs(fd - an).max()
                                 / (np.abs(an).max() + 1e-30)))
    assert worst <= 5e-5, f"FD-Jacobian gate: {worst:.3e} > 5e-5"


def test_effective_field_jacobian_matches_fd(s2_at_40):
    """ii_nonlocal.effective_field's own analytic d(E_eff)/d(psi) vs
    central FD, every column, at a perturbed state (no edge within a
    probe step of a direction change).  Measured: 8e-7."""
    dev, _ = s2_at_40
    rng = np.random.default_rng(3)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.N)
    for c in "np":
        _E, D = effective_field(dev.x, psi, dev.VT, LAM, c, jacobian=True)
        worst = 0.0
        for k in range(dev.N):
            a = psi.copy()
            a[k] += 1e-7
            b = psi.copy()
            b[k] -= 1e-7
            fd = (effective_field(dev.x, a, dev.VT, LAM, c)
                  - effective_field(dev.x, b, dev.VT, LAM, c)) / 2e-7
            den = max(np.abs(fd).max(), np.abs(D[:, k]).max(), 1e-300)
            worst = max(worst, np.abs(fd - D[:, k]).max() / den)
        assert worst < 1e-5, f"carrier {c}: {worst:.3e}"


def test_nonlocal_generation_below_local_at_the_same_bias(s2_at_40,
                                                          local_at_40):
    """At -40V the coupled nonlocal solve integrates LESS ionization
    than the local one (carriers lag the field over lambda), but the
    same order: in this junction the field varies over ~1 um, many
    lambdas, so the two models must stay close."""
    (dn, bad_n), (dl, bad_l) = s2_at_40, local_at_40
    assert not bad_n and not bad_l
    # Re-evaluate at each STORED solution first: the module fixture is
    # shared with the FD test, which leaves a perturbed state's source in
    # _ii_gs_cache (which test ran first in an xdist worker used to
    # decide what this gate read).
    for dev in (dn, dl):
        dev._ii_strength = 1.0
        dev._residual_jacobian(dev.psi, dev.n, dev.p,
                               dev._contact_values([-40.0, 0.0]))
    g_n = float(np.sum(dn._ii_gs_cache[1:-1] * dn.dV[1:-1]))
    g_l = float(np.sum(dl._ii_gs_cache[1:-1] * dl.dV[1:-1]))
    assert 0.5 < g_n / g_l < 1.0, f"ratio {g_n / g_l:.4f}"


def test_lambda_to_zero_recovers_local_at_first_order():
    """As lambda -> 0 the effective field at a node is its upstream
    edge's field (an upwind value) where the local model averages both
    adjacent edges, so the generation differs from local by an O(h)
    amount that must shrink under refinement.  Measured at h_max
    4e-6 / 1e-6: -3.45e-2 / -1.13e-2 (a factor of 3.1)."""
    errs = []
    for h_max in (4e-6, 1e-6):
        dev = _diode(h_max=h_max)
        assert not _ramp(dev, 30.0)
        Enode = dev._ii_compute_E_from_state(dev.psi)
        g_loc = _generation(dev, Enode, Enode)
        g_0 = _generation(dev,
                          effective_field(dev.x, dev.psi, dev.VT, 1e-14, "n"),
                          effective_field(dev.x, dev.psi, dev.VT, 1e-14, "p"))
        errs.append(abs(g_0 / g_loc - 1.0))
    assert errs[0] < 0.05
    assert errs[1] < errs[0] / 2.5


def test_narrow_field_peak_suppresses_ionization():
    """Slotboom 1991's claim on a real junction: at an abrupt
    1e18/1e18 p+n+ junction (field peak ~40 nm wide, below lambda),
    carriers leave the peak far colder than it.  Measured at -3V: peak
    E_eff 0.445 x peak E, generation 0.296 x the local model's."""
    x = graded_mesh(2.0e-5, [1.0e-5], h_min=2e-8, h_max=5e-7)
    dev = Device1D(x, np.where(x < 1e-5, -1e18, 1e18), T=300.0,
                   models=Models(bgn=False, srh=True))
    assert not _ramp(dev, 3.0, 0.5)
    Enode = dev._ii_compute_E_from_state(dev.psi)
    En = effective_field(dev.x, dev.psi, dev.VT, LAM, "n")
    Ep = effective_field(dev.x, dev.psi, dev.VT, LAM, "p")
    assert En.max() < 0.5 * Enode.max() and Ep.max() < 0.5 * Enode.max()
    ratio = _generation(dev, En, Ep) / _generation(dev, Enode, Enode)
    assert ratio < 0.5, f"G_nl/G_local = {ratio:.3f}"


def test_field_plateau_matches_the_local_field():
    """A p+ i n+ diode with a 4 um intrinsic region: well inside the
    field plateau (25 lambda from its upstream edge) the effective
    field equals the local one.  Measured: 9.9e-5 (the plateau itself
    varies by 0.3%)."""
    x = graded_mesh(5.0e-4, [0.5e-4, 4.5e-4], h_min=1e-7, h_max=2e-6)
    dop = np.where(x < 0.5e-4, -1e19, np.where(x > 4.5e-4, 1e19, 1e13))
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    assert not _ramp(dev, 40.0, 4.0)
    Enode = dev._ii_compute_E_from_state(dev.psi)
    En = effective_field(dev.x, dev.psi, dev.VT, LAM, "n")
    inner = (x > 0.5e-4 + 25 * LAM) & (x < 4.5e-4 - 2e-5)
    assert inner.sum() > 50
    assert np.abs(En[inner] / Enode[inner] - 1.0).max() < 1e-3
