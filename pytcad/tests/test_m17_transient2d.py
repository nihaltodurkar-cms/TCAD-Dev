"""M17 phase 2 acceptance gates -- transient (time-dependent) Device2D.

See M17-TRANSIENT-PLAN.md section 1 (Phase 2). pytcad/transient2d.py
drives Device2D through its own _residual_jacobian from OUTSIDE
device2d.py (same externally-driven pattern as Phase 1's transient.py
and continuation.py) -- these gates exercise that module, not a
device2d.py change, since none was made.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.device2d import Device2D
from pytcad.constants import Q
from pytcad.transient2d import (
    solve_transient, TransientResult2D, _step_residual_jacobian,
    _non_contact_flat_index,
)
from pytcad.transient import StepWaveform

warnings.simplefilter("ignore")


def _diode2d(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, Ly=5e-5, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    y = graded_mesh(Ly, [0.0], 1e-7, 1e-5, 1.15)
    dop1d = np.where(x < xj, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    mesh = Mesh2D(x, y)
    dev = Device2D(mesh, dop2d, models=Models(bgn=False, **kw))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    return dev


def _uniform2d(Nd=1e15, L=2e-4, Ly=5e-5, nx=41, ny=11):
    x = np.linspace(0.0, L, nx)
    y = np.linspace(0.0, Ly, ny)
    mesh = Mesh2D(x, y)
    dop = np.full((ny, nx), Nd)
    dev = Device2D(mesh, dop, models=Models(bgn=False))
    dev.add_contact("left", i=[0], j=list(range(ny)), V=0.0)
    dev.add_contact("right", i=[nx - 1], j=list(range(ny)), V=0.0)
    return dev


# ----------------------------------------------------------------------
def test_fd_jacobian_matches_numerical():
    """G-FD: the analytic 2D transient Jacobian (theta-scheme storage
    term on top of Device2D's own analytic J) must match a numerical
    Jacobian of the same transient residual."""
    dev = _diode2d()
    dev.solve_equilibrium()
    k_free = _non_contact_flat_index(dev)
    dV = dev.dV
    dt_s = 1.0

    rng = np.random.default_rng(0)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 1e-3 * rng.standard_normal(dev.p.shape))
    voltages = {"left": 0.2, "right": 0.0}

    F0, J0, *_ = _step_residual_jacobian(
        dev, psi, n, p, voltages, dev.n, dev.p, None, None, dV, dt_s, 1.0,
        k_free)
    J0 = J0.toarray()

    Ny, Nx = dev.Ny, dev.Nx
    N3 = 3 * Ny * Nx
    # a random SUBSET of columns -- the full N3xN3 dense FD check is too
    # slow/large at this mesh size (same concern test_validation_2d.py's
    # own dd_jacobian test documents for Device2D's steady Jacobian).
    cols = rng.choice(N3, size=60, replace=False)
    u0 = np.stack([psi, n, p], axis=-1).ravel()
    h = 1e-7
    for k in cols:
        u_p = u0.copy(); u_p[k] += h
        u_m = u0.copy(); u_m[k] -= h
        Fp, *_ = _step_residual_jacobian(
            dev, u_p[0::3].reshape(Ny, Nx), u_p[1::3].reshape(Ny, Nx),
            u_p[2::3].reshape(Ny, Nx), voltages, dev.n, dev.p, None, None,
            dV, dt_s, 1.0, k_free)
        Fm, *_ = _step_residual_jacobian(
            dev, u_m[0::3].reshape(Ny, Nx), u_m[1::3].reshape(Ny, Nx),
            u_m[2::3].reshape(Ny, Nx), voltages, dev.n, dev.p, None, None,
            dV, dt_s, 1.0, k_free)
        col_fd = (Fp - Fm) / (2 * h)
        scale = np.maximum(np.abs(J0[:, k]), 1.0)
        assert np.max(np.abs(J0[:, k] - col_fd) / scale) < 2e-3


# ----------------------------------------------------------------------
def test_steady_state_consistency_reference():
    """G5: one very large backward-Euler step from a perturbed state,
    under a fixed bias, must relax to the same converged state
    Device2D.solve_bias reaches for that bias directly."""
    dev = _diode2d()
    dev.solve_equilibrium()
    ref = _diode2d()
    ref.solve_equilibrium()
    ref.solve_bias({"left": 0.3, "right": 0.0})

    dev.solve_bias({"left": 0.05, "right": 0.0})
    result = solve_transient(dev, waveforms={"left": 0.3, "right": 0.0},
                              t_end=1.0, dt0=1e-3, dt_min=1e-12,
                              dt_max=1e6, growth=2.0)
    assert result.times[-1] == pytest.approx(1.0)
    j_dev = dev.Jn_x + dev.Jp_x
    j_ref = ref.Jn_x + ref.Jp_x
    assert np.max(np.abs(j_dev - j_ref)) / (np.max(np.abs(j_ref)) + 1e-30) < 0.05


# ----------------------------------------------------------------------
def test_charge_conservation_reference():
    """G4: at every accepted step, the sum of ALL contact terminal
    currents must equal d/dt of the total stored mobile charge -- the
    2D generalization of the box-integration telescoping identity
    Phase 1 already validated in 1D, now over an arbitrary number of
    contacts rather than just two array ends."""
    dev = _diode2d()
    dev.solve_equilibrium()
    result = solve_transient(
        dev, waveforms={"left": StepWaveform(0.0, 0.3, t_step=0.0)},
        t_end=2e-7, dt0=1e-9, dt_min=1e-15)

    Q_t = result.stored_charge(dev)
    dQ = np.diff(Q_t)
    dt = np.diff(result.times)
    I_left = result.terminal_current["left"][1:]
    I_right = result.terminal_current["right"][1:]
    # Device2D.terminal_current()'s own convention is "positive =
    # current INTO the device" at EVERY contact independently (unlike
    # 1D's single continuous edge-flux array) -- derived here from the
    # box-integration telescoping identity (sum of F_n_raw over ALL
    # nodes is a pure algebraic constant regardless of Newton
    # convergence, since interior divergence terms cancel pairwise by
    # construction) and confirmed numerically: net stored-charge growth
    # equals the NEGATIVE of the total current declared to be flowing
    # into the device at all contacts combined, dQ/dt == -(I_left +
    # I_right), not I_right - I_left (that was 1D's array-difference
    # convention, which does not carry over to 2D's per-contact "into
    # the device" sign).
    I_total_in = I_left + I_right
    lhs = dQ / dt
    assert np.allclose(lhs, -I_total_in, rtol=1e-3, atol=1e-9)


# ----------------------------------------------------------------------
def test_dielectric_relaxation_reference():
    """G1: a small excess-charge perturbation on a uniformly doped,
    zero-bias 2D slab decays with tau = eps/sigma, same physics as
    Phase 1's 1D gate, now verified on a genuinely 2D mesh (non-trivial
    y-direction box integration in play, not just a y-invariant
    reduction)."""
    dev = _uniform2d()
    dev.solve_equilibrium()
    mid = (dev.Ny // 2, dev.Nx // 2)
    sigma = Q * (dev.mu_n0[mid] * dev.n_cm3[mid]
                 + dev.mu_p0[mid] * dev.p_cm3[mid])
    tau = dev.eps / sigma

    n0 = dev.n.copy()
    dev.n = n0 * 1.002

    result = solve_transient(dev, waveforms={}, t_end=6 * tau,
                              dt0=tau / 40, dt_min=tau / 1e6,
                              dt_max=tau / 8, growth=1.2)

    dn = result.n_hist[:, mid[0], mid[1]] - n0[mid]
    keep = np.abs(dn) > 1e-3 * np.abs(dn[0])
    t_fit, dn_fit = result.times[keep], dn[keep]
    slope, _ = np.polyfit(t_fit, np.log(np.abs(dn_fit)), 1)
    tau_fit = -1.0 / slope

    assert tau_fit == pytest.approx(tau, rel=0.25)
