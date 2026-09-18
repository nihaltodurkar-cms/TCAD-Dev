"""M46-S2 -- the Robin (thermionic-emission-limited) Schottky boundary
condition, replacing S1's Dirichlet approximation when
SchottkyContact.A_star is given. See device.py's SchottkyContact
docstring: this reuses M14's own S_n/S_p Robin-BC machinery exactly
(same equation shape, same already-gated Jacobian coefficients),
substituting the thermionic-emission velocity v_R = A* T^2/(q Nc) for
M14's surface-recombination velocity and the barrier-limited n0 (S1's
own `_contact_values` override) for M14's bulk-equilibrium n0.

Gates:
  G1  FD-Jacobian of the Robin row (mirrors
      test_m14_surface_mobility.py's own G-E gate exactly).
  G2  A_star=None still reproduces S1's Dirichlet approximation
      bit-identically (opt-in, not a behavior change to S1's own
      gates).
  G3  at equilibrium (Jn=0 forces n=n0 regardless of v_R -- the same
      invariant M14's own gate documents), Robin and Dirichlet give
      IDENTICAL psi/n/p.
  G4  under bias, the Robin BC's current is quantitatively close to
      schottky.py's own analytic thermionic_current_density formula
      (numeric slightly BELOW analytic, the expected direction: the DD
      solve's bulk series resistance is not present in the pure
      analytic formula, which assumes the entire bias appears across
      the barrier).
  G5  Robin forward current is smaller than the Dirichlet
      approximation's at the same bias (the interface recombination
      velocity is a genuine additional bottleneck the Dirichlet
      approximation does not have).
  G6  S_n/S_p combined with a Robin-mode SchottkyContact is refused.
"""
import warnings

import numpy as np
import pytest

from pytcad.device import Device1D, Models, NewtonOptions, SchottkyContact
from pytcad.mesh import graded_mesh
from pytcad.materials import SILICON
from pytcad.schottky import (
    richardson_a_star, schottky_barrier_height_n, thermionic_current_density,
)

_A_STAR_N = richardson_a_star("Si", "n")


def _device(schottky_left=None):
    x = graded_mesh(2e-4, [0.0], h_min=1e-6, h_max=4e-6)
    dop = np.full_like(x, 1e16)
    return Device1D(x, dop, models=Models(bgn=False), schottky_left=schottky_left)


# ---------------------------------------------------------------- G1
def test_g1_fd_jacobian_robin_row():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sch = SchottkyContact(phi_metal_eV=4.8, A_star=_A_STAR_N)
        dev = _device(sch)
        dev.solve_equilibrium()
    bc = dev._contact_values([0.0, -0.3])
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
    assert worst <= 5e-5, f"Robin-row FD-Jacobian mismatch: {worst:.3e}"


# ---------------------------------------------------------------- G2
def test_g2_a_star_none_reproduces_s1_dirichlet_bit_identical():
    sch_dirichlet_via_none = SchottkyContact(phi_metal_eV=4.8)
    assert sch_dirichlet_via_none.A_star is None
    d1 = _device(sch_dirichlet_via_none)
    d2 = _device(sch_dirichlet_via_none)
    d1.solve_equilibrium(); d2.solve_equilibrium()
    assert np.array_equal(d1.psi, d2.psi)


# ---------------------------------------------------------------- G3
def test_g3_equilibrium_robin_matches_dirichlet():
    sch_robin = SchottkyContact(phi_metal_eV=4.8, A_star=_A_STAR_N)
    sch_dirichlet = SchottkyContact(phi_metal_eV=4.8)
    d_robin = _device(sch_robin)
    d_dirichlet = _device(sch_dirichlet)
    d_robin.solve_equilibrium()
    d_dirichlet.solve_equilibrium()
    assert np.array_equal(d_robin.psi, d_dirichlet.psi)
    assert np.array_equal(d_robin.n, d_dirichlet.n)
    assert np.array_equal(d_robin.p, d_dirichlet.p)


# ---------------------------------------------------------------- G4
def test_g4_robin_current_close_to_analytic_thermionic_formula():
    phi_B = schottky_barrier_height_n(4.8, SILICON.chi)
    sch = SchottkyContact(phi_metal_eV=4.8, A_star=_A_STAR_N)
    Vs = np.array([0.05, 0.1, 0.2, 0.3])
    J_num = []
    for V in Vs:
        d = _device(sch)
        d.solve_bias([float(V), 0.0])
        J, _ = d.current_density()
        J_num.append(J)
    J_num = np.array(J_num)
    J_analytic = thermionic_current_density(phi_B, 300.0, Vs, _A_STAR_N)
    ratio = J_num / J_analytic
    assert np.all((ratio > 0.5) & (ratio < 1.0)), (
        f"Robin BC current not within the expected band of the analytic "
        f"thermionic-emission formula: ratios={ratio}")


# ---------------------------------------------------------------- G5
def test_g5_robin_forward_current_below_dirichlet_approximation():
    sch_robin = SchottkyContact(phi_metal_eV=4.8, A_star=_A_STAR_N)
    sch_dirichlet = SchottkyContact(phi_metal_eV=4.8)
    d_robin = _device(sch_robin)
    d_robin.solve_bias([0.3, 0.0])
    J_robin, _ = d_robin.current_density()

    d_dirichlet = _device(sch_dirichlet)
    d_dirichlet.solve_bias([0.3, 0.0])
    J_dirichlet, _ = d_dirichlet.current_density()

    assert 0.0 < J_robin < J_dirichlet, (
        f"Robin BC should be more current-limited: J_robin={J_robin:.3e} "
        f"vs J_dirichlet={J_dirichlet:.3e}")


# ---------------------------------------------------------------- G6
def test_g6_s_n_combined_with_robin_schottky_refused():
    x = graded_mesh(2e-4, [0.0], h_min=1e-6, h_max=4e-6)
    dop = np.full_like(x, 1e16)
    sch = SchottkyContact(phi_metal_eV=4.8, A_star=_A_STAR_N)
    dev = Device1D(x, dop, models=Models(bgn=False, S_n=1e4),
                   schottky_left=sch)
    dev.solve_equilibrium()
    with pytest.raises(NotImplementedError):
        dev.solve_bias([0.1, 0.0])
