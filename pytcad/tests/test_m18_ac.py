"""M18 phase 1 acceptance gates -- small-signal AC analysis on Device1D.

See M18-AC-PLAN.md for scope. pytcad/ac.py drives Device1D through its
own _residual_jacobian from OUTSIDE device.py (same pattern
continuation.py/transient.py already use) -- these gates exercise that
module, not a device.py change, since none was made.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Device1D, Device2D, Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.constants import Q
from pytcad.ac import ac_sweep, _storage_matrix
from pytcad.transient import _step_residual_jacobian

warnings.simplefilter("ignore")


def _diode(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    dop = np.where(x < xj, -Na, Nd)
    return Device1D(x, dop, models=Models(bgn=False, **kw))


def _n_side_charge(device, xj=1e-4):
    """q * sum((n-p)*dx) over x >= xj only -- the charge on ONE side
    of the metallurgical junction, the quantity whose bias derivative
    is the junction capacitance. (The TOTAL device charge nets to ~0
    since both quasi-neutral bulk regions individually cancel their
    own doping -- confirmed directly while designing this gate: it is
    NOT a usable capacitance proxy, only the one-sided charge is.)"""
    dx = device.dV * device.LD
    n_phys, p_phys = device.n * device.Ns, device.p * device.Ns
    mask = device.x >= xj
    return Q * np.sum((n_phys - p_phys)[mask] * dx[mask])


# ---------------------------------------------------------------- G-CONSISTENCY
def test_g_consistency_storage_matrix_matches_transient():
    """G-CONSISTENCY: ac.py's Cmat (the coefficient of j*omega in
    J_ac) is numerically identical to transient.py's already-FD-gated
    storage-term Jacobian addition, evaluated with dt_s=1.0 -- stands
    in for a fresh FD-Jacobian derivation (the affine map u -> J0*u +
    j*w*Cmat*u trivially reproduces Cmat under an FD probe, so an
    independent-formula equivalence check is more informative here)."""
    dev = _diode()
    dev.solve_equilibrium()
    dev.solve_bias([0.3, 0.0])
    psi, n, p = dev.psi, dev.n, dev.p
    bc = ((psi[0], n[0], p[0]), (psi[-1], n[-1], p[-1]))
    idx_n = 3 * np.arange(1, dev.N - 1) + 1
    idx_p = 3 * np.arange(1, dev.N - 1) + 2

    F0, J0, _, _ = dev._residual_jacobian(psi, n, p, bc)
    Ft, Jt, _, _ = _step_residual_jacobian(
        dev, psi, n, p, bc, n, p, None, dev.dV, 1.0, 1.0, idx_n, idx_p)
    Cmat = _storage_matrix(dev, dev.dV)

    diff = (Jt - J0) - Cmat
    assert np.max(np.abs(diff.toarray())) < 1e-9


# ---------------------------------------------------------------- G-LOWF
def test_g_lowf_matches_quasi_static_dc():
    """G-LOWF (ARCHITECTURE-mandated): at f -> 0, ac_sweep's Re(Y) and
    C must match, respectively, a finite-difference dI/dV and dQ/dV
    computed via two independent nearby solve_bias() calls -- an
    entirely separate, already-validated numerical path. This single
    gate independently validates both Cmat and the current-sensitivity
    vector S at once."""
    V0 = 0.3
    opts = NewtonOptions(tol_update=1e-13, max_iter=200)

    dev = _diode()
    dev.solve_equilibrium(opts)
    dev.solve_bias([V0, 0.0], opts)
    res = ac_sweep(dev, np.array([1.0]))  # 1 Hz: deep in the low-f plateau

    dV_step = 1e-5
    dev1 = _diode(); dev1.solve_equilibrium(opts); dev1.solve_bias([V0 - dV_step, 0.0], opts)
    dev2 = _diode(); dev2.solve_equilibrium(opts); dev2.solve_bias([V0 + dV_step, 0.0], opts)
    I1, _ = dev1.current_density()
    I2, _ = dev2.current_density()
    dIdV = (I2 - I1) / (2 * dV_step)

    Q1, Q2 = _n_side_charge(dev1), _n_side_charge(dev2)
    dQdV = (Q2 - Q1) / (2 * dV_step)

    rel_G = abs(res.G[0] - dIdV) / abs(dIdV)
    rel_C = abs(res.C[0] - dQdV) / abs(dQdV)
    assert rel_G < 1e-2, f"G(f->0)={res.G[0]:.6e} vs dI/dV={dIdV:.6e} (rel {rel_G:.2e})"
    assert rel_C < 1e-2, f"C(f->0)={res.C[0]:.6e} vs dQ/dV={dQdV:.6e} (rel {rel_C:.2e})"


# ---------------------------------------------------------------- G-JUNCTION-C
def test_g_junction_c_matches_analytic_depletion_formula():
    """G-JUNCTION-C: at equilibrium (V=0), ac_sweep's low-f C on an
    abrupt Na=Nd=1e17 diode matches the textbook abrupt-junction
    depletion capacitance C_j = eps/W, W = sqrt(2*eps*Vbi/q *
    (1/Na+1/Nd)) -- the same Vbi formula test_validation.py's own
    test_built_in_potential already gates independently. No such
    junction-C gate previously existed anywhere in the repo (confirmed
    during planning). Some discrepancy is expected: the formula
    assumes an infinite one-sided structure, this device is finite --
    report the measured error rather than assume a tight tolerance."""
    Na = Nd = 1e17
    dev = _diode(Na=Na, Nd=Nd)
    dev.solve_equilibrium()
    res = ac_sweep(dev, np.array([1.0]))

    Vbi = dev.VT * np.log(Na * Nd / dev.ni ** 2)
    W = np.sqrt(2.0 * dev.eps * Vbi / Q * (1.0 / Na + 1.0 / Nd))
    Cj_analytic = dev.eps / W

    rel = abs(res.C[0] - Cj_analytic) / Cj_analytic
    assert rel < 0.10, (
        f"AC junction C={res.C[0]:.6e} vs analytic C_j={Cj_analytic:.6e} "
        f"(rel {rel:.2%}) -- measured ~3.3% during development")


# ---------------------------------------------------------------- G-ROLLOFF
def test_g_rolloff_diffusion_capacitance_decreases_with_frequency():
    """G-ROLLOFF: sweeping several decades of frequency on a
    forward-biased diode must show a genuine roll-off -- C(f)
    decreasing by a clear order-of-magnitude-scale factor from low to
    high f, staying finite throughout the swept (non-pathological)
    range.

    Honest limit (M17's own precedent, ARCHITECTURE.md/M17-TRANSIENT-
    PLAN.md section 5): M17 tried and explicitly abandoned a
    quantitative Qs~=I_F*tau_p stored-charge formula as sign-ambiguous
    and off by a factor of several -- so this gate does NOT assume a
    clean tau_p pole to match against quantitatively, only the
    qualitative roll-off signature ARCHITECTURE.md's literature
    awareness calls for. Measured during development: C drops from
    ~1.05e-7 F/cm^2 at 1 kHz to ~1.2e-8 F/cm^2 at ~1e11 Hz (~8.5x);
    well beyond ~3e11 Hz the complex solve loses numerical fidelity
    (C crosses zero and goes slightly negative near 1e12 Hz) --
    genuinely beyond the model's validity at these mesh/timescales,
    not gated, and the swept range below stays clear of it.
    """
    opts = NewtonOptions()
    dev = _diode()
    dev.solve_equilibrium(opts)
    dev.solve_bias([0.4, 0.0], opts)

    freqs = np.logspace(3, 11, 12)
    res = ac_sweep(dev, freqs)

    assert np.all(np.isfinite(res.C))
    assert np.all(np.isfinite(res.G))
    assert np.all(res.G > 0), "conductance must stay positive (passive device)"

    C_lo, C_hi = res.C[0], res.C[-1]
    assert C_lo / C_hi > 5.0, (
        f"C did not roll off: C(1kHz)={C_lo:.3e}, C(1e11Hz)={C_hi:.3e}")
    G_lo, G_hi = res.G[0], res.G[-1]
    assert G_hi / G_lo > 1e5, (
        f"G did not rise with frequency as expected: G(1kHz)={G_lo:.3e}, "
        f"G(1e11Hz)={G_hi:.3e}")


# ---------------------------------------------------------------- G-LIVE-STATE
def test_g_live_state_reflects_current_operating_point():
    """G-LIVE-STATE (mirrors M15/M16's ordering/live-state-gates-first
    convention): ac_sweep at two different DC bias points must give
    measurably different Y -- catches a stale-DC-point bug (e.g.
    accidentally reusing a cached Jacobian across calls)."""
    dev = _diode()
    dev.solve_equilibrium()
    dev.solve_bias([0.0, 0.0])
    res0 = ac_sweep(dev, np.array([1.0]))

    dev.solve_bias([0.3, 0.0])
    res1 = ac_sweep(dev, np.array([1.0]))

    assert abs(res1.Y[0] - res0.Y[0]) / abs(res0.Y[0]) > 0.1


# ---------------------------------------------------------------- G-SCOPE-REFUSAL
def test_g_scope_refusal_2d():
    """G-SCOPE-REFUSAL: ac_sweep must refuse a Device2D explicitly --
    2D/3D AC analysis is out of scope this phase, and a silent wrong
    answer would be worse than a clear error (same convention as
    M16's G-F / M21's 3D+gates refusal)."""
    x = np.linspace(0.0, 2e-4, 11)
    y = np.linspace(0.0, 1e-4, 11)
    mesh = Mesh2D(x, y)
    dop = np.full((11, 11), 1e17)
    dev2d = Device2D(mesh, dop, models=Models(bgn=False))
    with pytest.raises(TypeError):
        ac_sweep(dev2d, np.array([1.0]))
