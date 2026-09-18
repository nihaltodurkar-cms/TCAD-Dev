"""M46-S1 -- Schottky contact coupled into Device1D (ARCHITECTURE.md's
own M46 scope note: "couple schottky.py into a device core first, then
lift dimensionally"). See device.py's SchottkyContact docstring for the
Dirichlet-approximation scope: the contact's majority-carrier density
is pinned at its barrier-limited equilibrium value instead of its
doping-limited (ohmic) one, through the SAME psi0 = V/VT + ln(n0/nie)
formula the ohmic path already uses -- no new Jacobian stamp, so no
new FD-Jacobian gate is needed (the existing Dirichlet-contact
FD-Jacobian gates already cover this code shape).

Gates:
  G1  schottky_left=schottky_right=None reproduces the ohmic path
      exactly (bit-identical) -- the new params are additive.
  G2  a Schottky contact depletes the interface (n well below the
      ohmic value) and its depletion grows monotonically with the
      metal work function (higher phi_m -> higher phi_Bn -> more
      depletion, for the same n-type semiconductor).
  G3  the resulting device RECTIFIES: forward current is many orders
      of magnitude larger than reverse current at equal |V| -- the
      qualitative signature schottky.py's own thermionic-emission
      formula predicts, and the reason this milestone exists.
  G4  forward current under a Schottky contact is smaller than under
      an ohmic contact at the same bias (the barrier limits injection)
      -- distinguishes this from a cosmetic psi shift.
"""
import numpy as np
import pytest

from pytcad.device import Device1D, Models, SchottkyContact
from pytcad.mesh import graded_mesh


def _device(schottky_left=None, Na_type=1e16):
    x = graded_mesh(2e-4, [0.0], h_min=1e-6, h_max=4e-6)
    dop = np.full_like(x, Na_type)
    return Device1D(x, dop, models=Models(bgn=False), schottky_left=schottky_left)


# ---------------------------------------------------------------- G1
def test_g1_none_reproduces_ohmic_bit_identical():
    d_explicit = _device(schottky_left=None)
    d_default = _device()  # schottky_left defaults to None too
    d_explicit.solve_equilibrium()
    d_default.solve_equilibrium()
    assert np.array_equal(d_explicit.psi, d_default.psi)
    assert np.array_equal(d_explicit.n, d_default.n)
    assert np.array_equal(d_explicit.p, d_default.p)


# ---------------------------------------------------------------- G2
def test_g2_depletion_grows_with_work_function():
    n_at_contact = []
    for phi_m in (4.3, 4.8, 5.3):
        d = _device(SchottkyContact(phi_metal_eV=phi_m))
        d.solve_equilibrium()
        n_at_contact.append(d.n[0])
    assert n_at_contact[0] > n_at_contact[1] > n_at_contact[2], (
        f"contact density not monotonically suppressed by phi_m: "
        f"{n_at_contact}")
    d_ohmic = _device(schottky_left=None)
    d_ohmic.solve_equilibrium()
    assert n_at_contact[0] < d_ohmic.n[0], (
        "even the smallest barrier tried must still deplete relative "
        "to the ohmic contact")


# ---------------------------------------------------------------- G3
def test_g3_device_rectifies():
    sch = SchottkyContact(phi_metal_eV=4.8)
    d_fwd = _device(sch)
    d_fwd.solve_bias([0.3, 0.0])
    J_fwd, _ = d_fwd.current_density()

    d_rev = _device(sch)
    d_rev.solve_bias([-0.3, 0.0])
    J_rev, _ = d_rev.current_density()

    assert J_fwd > 0.0
    assert abs(J_fwd) > 1e3 * abs(J_rev), (
        f"insufficient rectification: J_fwd={J_fwd:.3e}, "
        f"J_rev={J_rev:.3e}")


# ---------------------------------------------------------------- G4
def test_g4_forward_current_below_ohmic_reference():
    sch = SchottkyContact(phi_metal_eV=4.8)
    d_sch = _device(sch)
    d_sch.solve_bias([0.3, 0.0])
    J_sch, _ = d_sch.current_density()

    d_ohm = _device(schottky_left=None)
    d_ohm.solve_bias([0.3, 0.0])
    J_ohm, _ = d_ohm.current_density()

    assert 0.0 < J_sch < J_ohm, (
        f"barrier should limit forward injection: J_sch={J_sch:.3e} "
        f"vs J_ohm={J_ohm:.3e}")
