"""M33 gates -- heterojunction interface physics.

Plan, the finding that motivated it, and honest limits:
`pytcad/M33-INTERFACE-PLAN.md`.

S1 (this file, first half) fixes a real gap found by measurement:
`Device1D`'s heterojunction transport was parameterised by `nie` alone,
which encodes Nc/Nv/Eg but NOT electron affinity -- so a step in `chi`
at a heterointerface changed the solution by EXACTLY zero, for a step
as large as 0.5 eV. `chi_arr` was built and then read only by
`band_diagram()`, a post-processing accessor. G2 below is that probe
turned into a gate; its absence is what let the gap exist.
"""
import os, sys, dataclasses
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import Device1D, Models
from pytcad.mesh import graded_mesh
from pytcad.materials import SILICON


def _hetero(chi_right=4.05, band_offset="nie", Eg0_right=None, bias=0.4,
            equilibrium_only=False):
    """Si / Si-with-shifted-band device.  The ONLY difference between
    the two materials is what the test asks for, so any change in the
    answer is attributable."""
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    kw = {"name": "Si-shifted", "chi": chi_right}
    if Eg0_right is not None:
        kw["Eg0"] = Eg0_right
    right = dataclasses.replace(SILICON, **kw)
    mats = [SILICON if xi < 1.0e-4 else right for xi in x]
    dev = Device1D(x, dop, material=mats,
                   models=Models(bgn=False, band_offset=band_offset))
    dev.solve_equilibrium()
    if not equilibrium_only:
        dev.solve_bias([bias, 0.0])
    return dev


# The equilibrium residual current floor, in A/cm^2. Set from
# measurement, not from a round number: the SAME device as a
# homojunction in the LEGACY gauge -- i.e. with no M33 term in play at
# all -- reports |Jn|max = 1.09e-9 and |Jp|max = 3.16e-10 at zero bias,
# because that is where `solve_bias`'s Newton stops, not because
# detailed balance is violated. 1e-7 sits ~100x above that floor and
# still ~1000x below a real break.
#
# DELIBERATELY ABSOLUTE, NOT RELATIVE TO THE DEVICE'S OWN FORWARD
# CURRENT. That normalisation looks more natural and is VACUOUS: with a
# sign error injected into the hole delta, the zero-bias |Jp| rose from
# 3.2e-10 to 1.354e-01 (nine orders) -- but J(0.4V) rose to 1.1e+03 too,
# so the ratio came out 1.75e-07, i.e. BETTER than the correct code.
# Measured by injecting that exact bug and re-running before this
# tolerance was chosen.
EQ_CURRENT_FLOOR = 1.0e-7


def _assert_balanced(dev):
    """G1: per carrier, separately. M11-S3's record is that a shared
    delta passes an FD-Jacobian check and still breaks hole detailed
    balance, so a combined Jn+Jp assertion would not catch it."""
    assert np.abs(dev.Jn).max() < EQ_CURRENT_FLOOR, \
        f"electron detailed balance broken: |Jn|max={np.abs(dev.Jn).max():.3e}"
    assert np.abs(dev.Jp).max() < EQ_CURRENT_FLOOR, \
        f"hole detailed balance broken: |Jp|max={np.abs(dev.Jp).max():.3e}"


# ----------------------------------------------------------------------
# G2 -- chi must actually move the solution
# ----------------------------------------------------------------------
def test_g2_affinity_step_moves_the_solution():
    """THE GATE WHOSE ABSENCE LET THE GAP EXIST.  Measured before the
    fix: max|dpsi| was 0.000e+00 and J/J_ref was 1.000000 for a 0.5 eV
    conduction-band step."""
    ref = _hetero(chi_right=4.05, band_offset="affinity")
    psi_ref = ref.psi.copy()
    J_ref, _ = ref.current_density()

    for dchi in (-0.20, +0.20):
        dev = _hetero(chi_right=4.05 + dchi, band_offset="affinity")
        J, _ = dev.current_density()
        moved = np.abs(dev.psi - psi_ref).max()
        assert moved > 1e-3, (
            f"chi step {dchi:+.2f} eV moved psi by only {moved:.3e} -- "
            "affinity is not reaching the equations")
        assert abs(J / J_ref - 1.0) > 1e-3, (
            f"chi step {dchi:+.2f} eV left J unchanged (ratio "
            f"{J / J_ref:.6f})")


def test_g2_affinity_step_direction_is_physical():
    """Direction, on a forward-biased p-n diode with the n-side's
    affinity varied.

    RAISING chi on the n-side lowers Ec there, which RAISES the
    conduction-band step electrons must climb to reach the p-side, so
    forward current FALLS. Monotonic across 0.4 eV, measured
    2.749e-4 -> 2.650e-4 A/cm^2.

    The magnitude is only ~1% per 0.1 eV, which is correct and worth
    stating so it does not read as a weak coupling: a RIGID shift of
    both band edges on one side is largely absorbed by the built-in
    potential re-equilibrating at fixed applied bias. The isotype gate
    below is where a band offset shows its full size."""
    chis = [3.85, 3.95, 4.05, 4.15, 4.25]
    Js = [_hetero(chi_right=c, band_offset="affinity").current_density()[0]
          for c in chis]
    assert all(a > b for a, b in zip(Js, Js[1:])), list(zip(chis, Js))
    assert Js[0] / Js[-1] > 1.02, (Js[0], Js[-1])


def test_g2_isotype_junction_barrier_is_symmetric_in_sign():
    """The sharpest signature that a REAL conduction-band offset exists
    in the equations, and the one the legacy gauge cannot produce.

    An isotype n-N junction has no p-n built-in potential to absorb a
    band step, so ANY step -- either sign -- puts a barrier/notch in the
    majority-carrier path and cuts the current. Current is therefore
    MAXIMISED at zero offset and falls off on BOTH sides. Measured:
    6.42e3 A/cm^2 at dchi=0, 4.34e3 at -0.20 eV, 3.11e3 at +0.20 eV --
    a factor ~2, not the ~1% of the p-n case.

    A one-sided or monotonic assertion would be much weaker: sign
    symmetry about zero is a shape a leak or a units slip does not
    reproduce."""
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    dop = np.full_like(x, 1e17)          # n-N, no p-n junction

    def run(chi_r):
        right = dataclasses.replace(SILICON, name="r", chi=chi_r)
        mats = [SILICON if xi < 1.0e-4 else right for xi in x]
        d = Device1D(x, dop, material=mats,
                     models=Models(bgn=False, band_offset="affinity"))
        d.solve_equilibrium()
        d.solve_bias([0.1, 0.0])
        return d.current_density()[0]

    J_flat = run(4.05)
    J_lo, J_hi = run(3.85), run(4.25)
    assert J_lo < J_flat and J_hi < J_flat, (J_lo, J_flat, J_hi)
    assert J_flat / J_lo > 1.2 and J_flat / J_hi > 1.2, (J_lo, J_flat, J_hi)


def test_g2_legacy_nie_gauge_still_ignores_chi_and_says_so():
    """The legacy path is kept bit-identical ON PURPOSE, so its
    chi-blindness is pinned rather than silently fixed -- a caller who
    asks for "nie" gets exactly the pre-M33 answer."""
    a = _hetero(chi_right=4.05, band_offset="nie")
    b = _hetero(chi_right=3.55, band_offset="nie")
    assert np.array_equal(a.psi, b.psi)
    assert np.array_equal(a.n, b.n)
    assert np.array_equal(a.p, b.p)


# ----------------------------------------------------------------------
# G1 -- equilibrium detailed balance, PER CARRIER SEPARATELY
# ----------------------------------------------------------------------
# M11-S3's own record: a shared delta passes an FD-Jacobian check and
# still breaks hole detailed balance.  A combined Jn+Jp check would not
# catch that, so each carrier is asserted on its own.
@pytest.mark.parametrize("dchi", [-0.30, -0.10, 0.0, +0.10, +0.30])
def test_g1_equilibrium_detailed_balance_per_carrier(dchi):
    # Zero applied bias IS equilibrium, and it goes through the real
    # solve_bias path, so Jn/Jp are the published per-edge currents
    # rather than something this test recomputed for itself.
    dev = _hetero(chi_right=4.05 + dchi, band_offset="affinity", bias=0.0)
    _assert_balanced(dev)


@pytest.mark.parametrize("dEg", [-0.20, +0.20])
def test_g1_equilibrium_detailed_balance_across_a_gap_step(dEg):
    """The other axis: a pure Eg step at fixed chi.  Electrons should
    see NO barrier (chi equal) and holes the full gap difference -- the
    exact case the symmetric-nie gauge splits 50:50 and gets wrong."""
    dev = _hetero(chi_right=4.05, Eg0_right=SILICON.Eg0 + dEg,
                  band_offset="affinity", bias=0.0)
    _assert_balanced(dev)


# ----------------------------------------------------------------------
# G4 -- bit-identity off-path
# ----------------------------------------------------------------------
def test_g4_homojunction_is_bit_identical_between_gauges():
    """With ONE material everywhere both correction terms are
    identically zero, so the two gauges must agree bit-for-bit -- not
    approximately."""
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    out = []
    for bo in ("nie", "affinity"):
        d = Device1D(x, dop, models=Models(bgn=False, band_offset=bo))
        d.solve_equilibrium()
        d.solve_bias([0.4, 0.0])
        out.append((d.psi, d.n, d.p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


def test_g4_default_is_the_legacy_gauge():
    assert Models().band_offset == "nie"


def test_models_refuses_an_unknown_band_offset():
    """Refuse, don't ignore -- the Models.driving_force pattern."""
    with pytest.raises(ValueError, match="band_offset"):
        Models(band_offset="bogus")


# ======================================================================
# S2 -- thermionic-emission interface flux
# ======================================================================
def _te_dev(chi_right=4.35, thermionic=True, K_scale=1.0, bias=0.1,
            dop=None):
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    dop = np.full_like(x, 1e17) if dop is None else dop
    right = dataclasses.replace(SILICON, name="r", chi=chi_right)
    mats = [SILICON if xi < 1.0e-4 else right for xi in x]
    dev = Device1D(x, dop, material=mats,
                   models=Models(bgn=False, band_offset="affinity",
                                 thermionic=thermionic))
    if thermionic and K_scale != 1.0:
        # The emission velocity is the model's one physical knob; the
        # limit K -> inf is what must reproduce drift-diffusion.
        dev._te_Kn = dev._te_Kn * K_scale
        dev._te_Kp = dev._te_Kp * K_scale
    dev.solve_equilibrium()
    dev.solve_bias([bias, 0.0])
    return dev


def test_s2_emission_velocity_matches_the_closed_form():
    """v = sqrt(kT/(2 pi m_DOS)) with m_DOS recovered from Nc, checked
    against the same closed form computed independently here."""
    from pytcad.device import emission_velocity
    from pytcad.constants import KB_EV, Q
    T = 300.0
    hbar = 1.054571817e-34
    h = 2.0 * np.pi * hbar
    kT = KB_EV * Q * T
    Nc_si = SILICON.Nc(T) * 1e6
    m_dos = (Nc_si / 2.0) ** (2.0 / 3.0) * h * h / (2.0 * np.pi * kT)
    v_ref = np.sqrt(kT / (2.0 * np.pi * m_dos)) * 100.0
    assert emission_velocity(SILICON.Nc(T), T) == pytest.approx(v_ref,
                                                                rel=1e-12)
    # Sanity: a thermal velocity, order 1e6-1e7 cm/s.
    assert 1e5 < v_ref < 1e8, v_ref


def test_s2_emission_velocity_differs_from_tabulated_A_star_as_documented():
    """The 1.92x silicon discrepancy is EXPECTED (Richardson mass vs DOS
    mass, six-valley conduction band) and is pinned so it is a known
    quantity rather than a surprise -- see emission_velocity's docstring
    and schottky.py's own warning about A*."""
    from pytcad.device import emission_velocity
    from pytcad.schottky import richardson_a_star
    from pytcad.constants import Q
    T = 300.0
    v_dos = emission_velocity(SILICON.Nc(T), T)
    v_astar = richardson_a_star("Si", "n") * T ** 2 / (Q * SILICON.Nc(T))
    assert v_astar / v_dos == pytest.approx(1.92, rel=0.02)


def test_s2_te_reduces_to_drift_diffusion_as_velocity_grows():
    """G-5: the limit that proves TE is a GENERALISATION of the SG edge
    and not a replacement for it.  An infinitely fast emitter cannot
    limit anything, so the interface must stop mattering."""
    J_dd, _ = _te_dev(thermionic=False).current_density()
    ratios = []
    for K in (1.0e3, 1.0e5, 1.0e7):
        J_te, _ = _te_dev(thermionic=True, K_scale=K).current_density()
        ratios.append(J_te / J_dd)
    # Monotonic, and converging to 1 -- but to within ~1%, not exactly.
    # Measured [0.976, 1.0029, 1.0032]. The limit slightly EXCEEDS the
    # drift-diffusion answer and that is correct: K -> inf is an ideal
    # zero-resistance interface, whereas the SG edge it replaces keeps a
    # finite drift-diffusion resistance. One edge out of a few hundred
    # is worth a few tenths of a percent, which is what shows up.
    assert ratios[0] < ratios[1] <= ratios[2], ratios
    assert abs(ratios[-1] - 1.0) < 0.01, ratios
    assert ratios[0] < 0.99, ratios      # and it really was limiting


def test_s2_te_is_flux_limiting():
    """G-6: at its real emission velocity the interface CUTS current
    relative to drift-diffusion.  If TE ever raised it, the model would
    be adding carriers rather than limiting them."""
    J_dd, _ = _te_dev(thermionic=False).current_density()
    J_te, _ = _te_dev(thermionic=True).current_density()
    assert 0.0 < J_te < J_dd, (J_te, J_dd)


def test_s2_te_limiting_deepens_with_the_barrier():
    """The suppression must track dEc, not just exist."""
    prev = None
    for dchi in (0.0, 0.15, 0.30):
        J_dd, _ = _te_dev(chi_right=4.05 + dchi,
                          thermionic=False).current_density()
        J_te, _ = _te_dev(chi_right=4.05 + dchi,
                          thermionic=True).current_density()
        r = J_te / J_dd
        if prev is not None:
            assert r < prev, (dchi, r, prev)
        prev = r


@pytest.mark.parametrize("dchi", [-0.30, +0.30])
def test_s2_detailed_balance_holds_with_te_on(dchi):
    """G-1 again with the interface flux active. The TE form was derived
    FROM detailed balance, so switching it on must not degrade
    equilibrium.

    Gated RELATIVE TO THE SAME DEVICE WITH TE OFF, not against
    _assert_balanced's absolute floor, and the reason is measured: this
    isotype fixture carries ~6e3 A/cm^2 where the p-n diode that floor
    was calibrated on carries ~2.7e-4, and at a 0.3 eV step the SG flux
    is a difference of two nearly-equal large terms. Its equilibrium
    residual is ~2e-7 WITH TE OFF (1.645e-7 measured) and does not
    shrink when Newton is tightened from 1e-6 to 1e-14 -- it is
    catastrophic cancellation at ~1.7e-11 relative, not a balance
    violation. Comparing on-vs-off on the identical device is immune to
    that, and a sign error in the TE coefficients would still show up
    as orders of magnitude (the injected-bug probe moved |Jp| by nine)."""
    off = _te_dev(chi_right=4.05 + dchi, thermionic=False, bias=0.0)
    on = _te_dev(chi_right=4.05 + dchi, thermionic=True, bias=0.0)
    for carrier in ("Jn", "Jp"):
        r_off = float(np.abs(getattr(off, carrier)).max())
        r_on = float(np.abs(getattr(on, carrier)).max())
        assert r_on < 10.0 * max(r_off, 1e-18), (carrier, r_on, r_off)


# --- refusals ---------------------------------------------------------
def test_s2_thermionic_requires_the_affinity_gauge():
    with pytest.raises(ValueError, match="affinity"):
        Models(thermionic=True, band_offset="nie")


def test_s2_thermionic_refuses_a_homojunction():
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    with pytest.raises(ValueError, match="homojunction"):
        Device1D(x, np.full_like(x, 1e17),
                 models=Models(bgn=False, band_offset="affinity",
                               thermionic=True))


def test_s2_thermionic_refuses_impact_ionization():
    x = graded_mesh(2.0e-4, [1.0e-4], 1.0e-8, 1.0e-6, 1.12)
    right = dataclasses.replace(SILICON, name="r", chi=4.35)
    mats = [SILICON if xi < 1.0e-4 else right for xi in x]
    with pytest.raises(NotImplementedError, match="impact"):
        Device1D(x, np.full_like(x, 1e17), material=mats,
                 models=Models(bgn=False, band_offset="affinity",
                               thermionic=True, impact=True))
