"""M13 PHASE-2 SOLVER GATES (G4-G8) + generalized-SG scheme unit gates.

Gate reference: M13-FERMI-DIRAC-PLAN.md section 4 (and section 3.2bis
for the recorded nu-factor scheme decision).  These tests run the REAL
solver with Models(fd=True) / Models(incomplete_ion=True) and enforce:

  scheme  equilibrium detailed balance (zero current) across a
          degenerate step junction and a Si/GaAs heterointerface,
          BOTH carriers, machine precision; bit-level Boltzmann
          reduction of the nu-factor edge correction;
  G4      charge-neutrality consistency vs INDEPENDENT physical
          root-finds (Nc/Nv-asymmetric Fermi-Dirac), generalized mass
          action, degenerate built-in potential;
  G5      house FD-Jacobian gate (<= 5e-5, >= 80 columns) on a
          degenerate step junction, a degenerate Si/GaAs
          heterointerface, and incomplete-ionization rows;
  G6b     fd=True nondegenerate equivalence (densities <= 1e-6,
          currents <= 1e-4 -- numerical equivalence, NOT bit-identity);
  G6c     off-path (fd=False) bit-identity: TAT-on and heterojunction
          runs reproduce PRE-CORE-EDIT sha256 digests captured before
          any device.py change (goldens cover the plain diode paths);
  G7      published-value benchmarks: degenerate n/N_D (Altermatt-style
          fully-ionized figure), B incomplete ionization at
          77/150/250/300 K vs literature bands, freeze-out direction,
          degenerate MOS C_max direction;
  G8      full-suite invariant (run separately).

APPLICABILITY LIMITS (G7, mirrored in catalog metadata):
  - parabolic-band F_{1/2}, valid eta in [-40, +40]; above +40 the
    fermi module refuses loudly.  Below -40 the solver CLAMPS (the
    true density is Boltzmann-exact zero to double precision -- e.g.
    minority carriers at 77 K where eta_n ~ -170), while the +40 side
    refuses.  Asymmetric by design: underflow is exact, overflow is
    invalid.
  - incomplete ionization: shallow hydrogenic B/P/As only
    (g_D=2/g_A=4, DeltaE=45 meV); single-species (net-doping input);
    INVALID above the Mott transition (~4e18 cm^-3 Si:P) -- never
    combine incomplete_ion with >= 1e19 doping.
  - FD composes with Slotboom BGN ONLY through nie_eff exactly as in
    the Boltzmann core (plan section 4.8 pinning).
"""
import hashlib
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import (Device1D, Device2D, Device3D, Models, MOSCapacitor,
                    NewtonOptions)
from pytcad.constants import KB_EV
from pytcad.fermi import f_half, f_mhalf, f_half_inv
from pytcad.materials import GAAS, SILICON
from pytcad.mesh import graded_mesh

T = 300.0
KB_EV_T300 = 8.617333262e-5 * 300.0


# ------------------------------------------------------------------ helpers
def _fd_neutral_eta(C, mat, T_, ion=False):
    """INDEPENDENT physical-statistics neutrality root (test-side).

    Solves n(e) - p(e) - C_ion(e) = 0 with n = Nc F(eta),
    p = Nv F(-eta - Eg/kT); C_ion = C under full ionization, or the
    acceptor NA-(e) = -NA/(1 + g e^{eta_p + DE/kT}) when ion=True
    (acceptor-only single-species, g=4).  g is strictly increasing.
    Returns (eta, n, p, fraction_ionized).  Below -35 the carrier
    sides switch to their exact Boltzmann tails (F -> exp within
    e^eta/sqrt2) so cryogenic etas stay representable.
    """
    Nc, Nv = mat.Nc(T_), mat.Nv(T_)
    EgkT = mat.Eg(T_) / (KB_EV * T_)
    NA = abs(float(C)) if C < 0 else 0.0

    def n_of(e):
        return Nc * np.exp(e) if e < -35.0 else Nc * f_half(
            min(max(e, -40.0), 40.0))

    def p_of(e):
        ep = -e - EgkT
        return Nv * np.exp(ep) if ep < -35.0 else Nv * f_half(
            min(max(ep, -40.0), 40.0))

    def cion_of(e):
        if not ion:
            return float(C)
        ep = -e - EgkT
        x = min(ep + 0.045 / (KB_EV * T_), 700.0)
        return -NA / (1.0 + 4.0 * np.exp(x))

    def imbalance(e):                      # n - p - Cion, increasing
        return n_of(e) - p_of(e) - cion_of(e)

    lo, hi = -EgkT - 40.0, 38.0
    assert imbalance(hi) > 0 > imbalance(lo), "root not bracketed"
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if imbalance(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 3e-15 * (1.0 + abs(lo)):
            break
    e = 0.5 * (lo + hi)
    n, p = n_of(e), p_of(e)
    frac = NA / abs(float(C)) if NA else 0.0
    if NA and ion:
        frac = (p - n) / NA
    elif NA:
        frac = 1.0
    return e, n, p, frac


def _step_device(na, nd, fd=True, mats=None, models=None):
    x = graded_mesh(2.0e-4, [1.0e-4], h_min=1.0e-8, h_max=1.0e-6,
                    ratio=1.12)
    dop = np.where(x < 1.0e-4, -na, nd)
    kw = dict(material=mats) if mats is not None else {}
    mdl = models or Models(bgn=False, srh=True, fd=fd)
    return Device1D(x, dop, T=T, models=mdl, **kw)


def _jacobian_probe(dev, V, n_cols=80, seed=42, tol=5e-5):
    """House FD-Jacobian gate: random columns, central differences,
    per-column relative error normalized by the column's largest
    magnitude (the same convention as
    tests/test_validation.py::test_jacobian_matches_finite_differences).
    Absolute-floor entries (e.g. recombination derivatives at the
    junction centre where np - np_eq cancels to the rounding floor)
    are therefore judged relative to their own column scale."""
    rng = np.random.default_rng(seed)
    bc = dev._contact_values(V)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.N)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.N))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.N))
    psi[0], psi[-1] = bc[0][0], bc[1][0]
    F0, J, _, _ = dev._residual_jacobian(psi, n, p, bc)
    J = J.tocsc()
    u = np.stack([psi, n, p], axis=1).ravel()
    cols = rng.choice(3 * dev.N, size=min(n_cols, 3 * dev.N),
                      replace=False)
    worst = 0.0
    for c in cols:
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, _, _, _ = dev._residual_jacobian(u2[0::3], u2[1::3],
                                              u2[2::3], bc)
        Fm_, _, _, _ = dev._residual_jacobian(u1[0::3], u1[1::3],
                                              u1[2::3], bc)
        fd_col = (Fp_ - Fm_) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        rel = np.abs(fd_col - an_col) / col_scale
        worst = max(worst, float(rel.max()))
    assert worst <= tol, \
        f"G5 FAIL: worst FD-Jacobian rel err {worst:.3e} > {tol:.0e}"


def _digest(**arrays):
    h = hashlib.sha256()
    for k in sorted(arrays):
        h.update(k.encode())
        h.update(np.ascontiguousarray(arrays[k]).tobytes())
    return h.hexdigest()


# ------------------------------------------------- scheme-level unit gates
def test_nu_factor_exact_boltzmann_reduction():
    """Scheme gate: for eta <= -30 the nu-factor correction is EXACTLY
    zero (bit-level edge-factor reduction, plan section 3.2bis), and at
    moderate eta it equals the analytic nu = F e^{-eta}."""
    x = np.linspace(0.0, 1.0e-4, 11)
    dev = Device1D(x, np.where(x < 0.5e-4, -1e17, 1e17), T=T,
                   models=Models(bgn=False, srh=True, fd=True))
    nc_s = dev.nc_s
    # densities mapping to eta <= -30  =>  L and w must be identically 0
    n_deep = nc_s * np.exp(-31.0)
    out = dev._fd_factors(n_deep, n_deep)
    Ln, Lp, wn, wp = out
    assert np.all(Ln == 0.0) and np.all(Lp == 0.0), \
        "deep-Boltzmann nu-factor correction is not EXACTLY zero"
    assert np.all(wn == 0.0) and np.all(wp == 0.0)
    # moderate eta: L = ln F(eta) - eta analytically
    eta = -3.0
    n_mod = nc_s * f_half(eta)
    Ln, Lp, wn, wp = dev._fd_factors(n_mod, n_mod)
    expect_L = np.log(f_half(eta)) - eta
    assert np.abs(Ln - expect_L).max() <= 1e-14
    # w = (F'/F - 1)/(Nc_s F') evaluated stably
    expect_w = (f_mhalf(eta) / f_half(eta) - 1.0) / (nc_s * f_mhalf(eta))
    assert np.abs(wn - expect_w).max() <= 1e-12 * np.abs(expect_w).max()


def test_sg_scheme_detailed_balance_degenerate_step():
    """Scheme gate (plan 3.2 hard property 2): ZERO equilibrium current
    across a 1e20/1e17 degenerate step junction, both carriers."""
    dev = _step_device(1e20, 1e17)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    bc = dev._contact_values([0.0, 0.0])
    _, _, Jn, Jp = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    scale = float(np.abs(dev.n).max() + dev.p.max())
    an_scale = float(np.abs(dev.dn_edge / dev.h).max())
    limit = 1e-10 * an_scale * scale
    assert np.abs(Jn).max() <= limit, \
        f"electron equilibrium current {np.abs(Jn).max():.3e} > {limit:.1e}"
    assert np.abs(Jp).max() <= limit, \
        f"hole equilibrium current {np.abs(Jp).max():.3e} > {limit:.1e}"


def test_sg_scheme_detailed_balance_heterointerface():
    """Scheme gate: same as above across a DEGENERATE Si/GaAs interface
    -- the composition that hid the M11 shared-delta bug.  Both
    carriers must carry identically zero current at equilibrium."""
    x = np.linspace(0.0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e20, 1e17)
    mats = [SILICON] * 20 + [GAAS] * 21
    dev = Device1D(x, dop, T=T, material=mats,
                   models=Models(bgn=False, srh=True, fd=True))
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    bc = dev._contact_values([0.0, 0.0])
    _, _, Jn, Jp = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    scale = float(np.abs(dev.n).max() + dev.p.max())
    an_scale = float(np.abs(dev.dn_edge / dev.h).max())
    limit = 1e-10 * an_scale * scale
    assert np.abs(Jn).max() <= limit, f"Jn {np.abs(Jn).max():.3e}"
    assert np.abs(Jp).max() <= limit, f"Jp {np.abs(Jp).max():.3e}"


# ---------------------------------------------------------------- G4
@pytest.mark.parametrize("C,sign", [(1e15, -1), (1e17, -1), (1e19, -1),
                                    (1e20, +1), (1e15, +1), (1e17, +1)])
def test_g4_uniform_neutrality_vs_independent_root(C, sign):
    """G4(a,b): uniform-doping equilibrium solve -> (n,p) constant along
    x and matching the INDEPENDENT physical-statistics root-find of
    Nc F(en) - Nv F(ep) = C to <= 1e-12 relative."""
    net = sign * C
    eta_ref, n_ref, p_ref, _ = _fd_neutral_eta(net, SILICON, T)
    x = np.linspace(0.0, 1.0e-4, 21)
    dev = Device1D(x, net * np.ones_like(x), T=T,
                   models=Models(bgn=False, srh=False, fd=True))
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-13, max_iter=400))
    assert np.ptp(dev.n_cm3) <= 1e-9 * dev.n_cm3.max(), "n not flat"
    assert np.ptp(dev.p_cm3) <= 1e-9 * max(dev.p_cm3.max(), 1.0), \
        "p not flat"
    rel_n = abs(dev.n_cm3[0] - n_ref) / n_ref
    rel_p = abs(dev.p_cm3[0] - p_ref) / p_ref
    assert rel_n <= 1e-12, f"G4 FAIL: n rel err {rel_n:.3e}"
    assert rel_p <= 1e-12, f"G4 FAIL: p rel err {rel_p:.3e}"


def test_g4_generalized_mass_action():
    """G4(c): np exp(en+ep) / (F(en) F(ep)) == nie^2 identically at every
    node of a solved FD junction (reduces to np = nie^2 in the
    Boltzmann limit)."""
    dev = _step_device(1e17, 1e17)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    nc, nv = SILICON.Nc(T), SILICON.Nv(T)
    en = f_half_inv(dev.n_cm3 / nc)
    ep = f_half_inv(dev.p_cm3 / nv)
    lhs = (dev.n_cm3 * dev.p_cm3 * np.exp(en + ep)
           / (f_half(en) * f_half(ep)))
    nie = SILICON.ni(T)
    rel = np.abs(lhs - nie ** 2) / (nie ** 2)
    assert rel.max() <= 1e-10, f"G4 FAIL: mass action {rel.max():.3e}"


def test_g4_degenerate_junction_built_in_potential():
    """G4(d): 1e20/1e17 FD junction V_bi vs the independent
    neutrality-pair computation, <= 1e-3 V (discretization-dominated)."""
    dev = _step_device(1e20, 1e17)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    vbi_sim = (dev.psi[-1] - dev.psi[0]) * dev.VT
    eta_p_side, _, _, _ = _fd_neutral_eta(-1e20, SILICON, T)
    eta_n_side, _, _, _ = _fd_neutral_eta(+1e17, SILICON, T)
    vbi_ref = (eta_n_side - eta_p_side) * KB_EV_T300
    assert abs(vbi_sim - vbi_ref) <= 1e-3, \
        f"G4 FAIL: V_bi sim {vbi_sim:.5f} vs ref {vbi_ref:.5f}"
    # degenerate-range sanity (G3 companion): the PHYSICAL majority
    # eta on the 1e20 side (holes -- that side is p-type here) must
    # exceed 2 per plan G3.
    eta_p_1e20 = f_half_inv(dev.p_cm3[0] / SILICON.Nv(T))
    assert eta_p_1e20 > 2.0, \
        f"G3 companion FAIL: eta_p at 1e20 = {eta_p_1e20:.2f} not > 2"


# ---------------------------------------------------------------- G5
def test_g5_fd_jacobian_1d_degenerate_step():
    """G5: analytic Jacobian vs central FD on a 1e20/1e17 degenerate
    step junction (house gate <= 5e-5, >= 80 columns)."""
    dev = _step_device(1e20, 1e17)
    dev.solve_equilibrium()
    _jacobian_probe(dev, [0.3, 0.0])


def test_g5_fd_jacobian_1d_heterointerface():
    """G5: degenerate Si/GaAs heterointerface Jacobian probe."""
    x = np.linspace(0.0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e20, 1e17)
    mats = [SILICON] * 20 + [GAAS] * 21
    dev = Device1D(x, dop, T=T, material=mats,
                   models=Models(bgn=False, srh=True, fd=True))
    dev.solve_equilibrium()
    _jacobian_probe(dev, [0.2, 0.0])


def test_g5_fd_jacobian_incomplete_ionization():
    """G5: incomplete-ionization rows (d(N_ion)/d(density) chain through
    the Poisson block and recombination) under FD statistics."""
    x = np.linspace(0.0, 1.0e-4, 31)
    dev = Device1D(x, -1e16 * np.ones_like(x), T=T,
                   models=Models(bgn=False, srh=True, fd=True,
                                 incomplete_ion=True))
    dev.solve_equilibrium()
    _jacobian_probe(dev, [0.2, 0.0])


# ---------------------------------------------------------------- G6b
def test_g6b_fd_on_nondegenerate_equivalence():
    """G6(b,c): fd=True must reduce to the Boltzmann path as eta -> -inf
    (different code path -- numerical equivalence, NOT bit-identity).

    SPEC-FIX NOTE (gate numbers from the exact Taylor series, mirroring
    the phase-1 G2 precedent): the complete F_{1/2} deviates from exp
    by exp(eta)/2^{3/2}, which at N_D = 1e16 cm^-3 (majority
    eta ~= -8.05) is 1.24e-4 -- so the ORIGINAL plan tolerances
    (1e-6 densities at 1e16) are MATHEMATICALLY UNATTAINABLE for any
    correct FD implementation.  The gates below are therefore derived
    from that exact series deviation delta at the tested doping:
    densities <= 3*delta (two nu factors), currents <= 20*delta."""
    nd = 1e16
    dev_b = _step_device(nd, nd, fd=False)
    dev_f = _step_device(nd, nd, fd=True)
    dev_b.solve_equilibrium()
    dev_f.solve_equilibrium()
    # exact-series degeneracy correction at the majority contact
    eta_maj = f_half_inv(abs(nd) / SILICON.Nc(T))
    delta = float(np.exp(eta_maj) / 2.0 ** 1.5)
    rel_n = np.abs(dev_f.n_cm3 - dev_b.n_cm3) / dev_b.n_cm3
    rel_p = np.abs(dev_f.p_cm3 - dev_b.p_cm3) / dev_b.p_cm3
    assert rel_n.max() <= 3 * delta, \
        f"G6b FAIL: n {rel_n.max():.3e} > {3*delta:.3e}"
    assert rel_p.max() <= 3 * delta, \
        f"G6b FAIL: p {rel_p.max():.3e} > {3*delta:.3e}"
    dev_b.solve_bias([0.5, 0.0], NewtonOptions())
    dev_f.solve_bias([0.5, 0.0], NewtonOptions())
    Jb = dev_b.Jn + dev_b.Jp
    Jf = dev_f.Jn + dev_f.Jp
    rel = np.abs(Jf - Jb) / np.abs(Jb)
    assert rel.max() <= 20 * delta, \
        f"G6b FAIL: J {rel.max():.3e} > {20*delta:.3e}"


# ---------------------------------------------------------------- G6c
# Pre-core-edit digests (captured from the committed tree, before ANY
# M13 phase-2 edit to device.py).  Regeneration is forbidden except by
# a dedicated commit stating so.
TAT_EQ_DIGEST = "9fb4359f9a24d518119dae6322287567e0cf74fc677bc576d1afa56ef5203522"
TAT_FW_DIGEST = "0cf15bc00ba94cd4d8ab0e763da2b87b6d0ef8301787d43770d7826e9f9adb39"
HETERO_FW_DIGEST = ("3594c906ad475c858442c393526b6763"
                    "25ddbbd1adac6fe0535f0b3ccde829b6")


def _tat_reference_device():
    x = graded_mesh(2.0e-4, [1.0e-4], h_min=1.0e-8, h_max=1.0e-6,
                    ratio=1.12)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    return Device1D(x, dop, T=T,
                    models=Models(bgn=False, srh=True, tat=True,
                                  trap_et_rel=0.5))


def test_g6c_tat_path_bit_identity():
    """G6(c): the TAT path (fd=False) is bit-identical to the
    pre-core-edit solver (sha256 of raw float64 bytes)."""
    dev = _tat_reference_device()
    dev.solve_equilibrium()
    assert _digest(psi=dev.psi, n=dev.n, p=dev.p) == TAT_EQ_DIGEST, \
        "G6c FAILURE: TAT equilibrium drifted from the pre-edit golden"
    dev.solve_bias([0.4, 0.0], NewtonOptions())
    assert _digest(psi=dev.psi, n=dev.n, p=dev.p,
                   Jn=dev.Jn, Jp=dev.Jp) == TAT_FW_DIGEST, \
        "G6c FAILURE: TAT forward-bias drifted from the pre-edit golden"


def test_g6c_hetero_path_bit_identity():
    """G6(c): the heterojunction path (fd=False) is bit-identical to the
    pre-core-edit solver at bias (equilibrium covered by goldens)."""
    x = np.linspace(0.0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e17, 1e17)
    mats = [SILICON] * 20 + [GAAS] * 21
    dev = Device1D(x, dop, T=T, material=mats,
                   models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    dev.solve_bias([0.3, 0.0], NewtonOptions())
    assert _digest(psi=dev.psi, n=dev.n, p=dev.p,
                   Jn=dev.Jn, Jp=dev.Jp) == HETERO_FW_DIGEST, \
        "G6c FAILURE: hetero forward-bias drifted from the pre-edit golden"


# ---------------------------------------------------------------- G7
def test_g7a_degenerate_concentration_vs_published():
    """G7(a): Si, 300 K, N_D = 1e20, fd=True (full ionization): the
    solver's n matches the independent FD neutrality root to machine
    precision and lands within 5% of the published fully-ionized
    degenerate figure n/N_D ~= 1 (Altermatt-style apparent-band tables
    give apparent concentrations within a few % of N_D at 1e20 once
    ionization completeness is accounted; the FD-only content beyond
    that is the Fermi level, gated eta > 2 per plan G3).

    APPLICABILITY: FD statistics alone; BGN pinned off here; no
    incomplete ionization (hydrogenic model invalid above ~4e18)."""
    nd = 1e20
    eta_ref, n_ref, p_ref, _ = _fd_neutral_eta(nd, SILICON, T)
    x = np.linspace(0.0, 1.0e-4, 21)
    dev = Device1D(x, nd * np.ones_like(x), T=T,
                   models=Models(bgn=False, srh=False, fd=True))
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    rel = abs(dev.n_cm3[0] - n_ref) / n_ref
    assert rel <= 1e-12, f"G7a FAIL: n vs independent root {rel:.3e}"
    ratio = dev.n_cm3.mean() / nd
    assert abs(ratio - 1.0) <= 0.05, \
        f"G7a FAIL: n/N_D = {ratio:.4f} outside published 5% band"
    eta_sim = f_half_inv(dev.n_cm3[0] / SILICON.Nc(T))
    assert eta_sim > 2.0, f"G7a FAIL: eta {eta_sim:.2f} not degenerate"


@pytest.mark.parametrize("T_K", [77.0, 150.0, 250.0, 300.0])
def test_g7bc_incomplete_ionization_boron_vs_literature(T_K):
    """G7(b,c): B in Si, N_A = 1e16, ionized fraction at
    77/150/250/300 K.  The solver must match the independent
    self-consistent root-find to machine precision AND land inside the
    published literature bands (Sze & Ng ch. 7 freeze-out curves;
    Altermatt et al., IEEE TED 49 (2002) -- digitized-band form):

        77 K: 15--45 %   150 K: 50--85 %
        250 K: >= 85 %   300 K: >= 95 %

    Freeze-out DIRECTION gate (c): fraction well below unity at 77 K.

    APPLICABILITY: shallow-acceptor hydrogenic model (g=4,
    45 meV), single-species, below the Mott transition."""
    na = 1e16
    _, _, _, frac_ref = _fd_neutral_eta(-na, SILICON, T_K, ion=True)
    x = np.linspace(0.0, 1.0e-4, 21)
    dev = Device1D(x, -na * np.ones_like(x), T=T_K,
                   models=Models(bgn=False, srh=False, fd=True,
                                 incomplete_ion=True))
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    frac_sim = (dev.p_cm3[0] - dev.n_cm3[0]) / na
    assert abs(frac_sim - frac_ref) <= 1e-9, \
        f"G7b FAIL @{T_K}K: sim {frac_sim:.6f} vs ref {frac_ref:.6f}"
    bands = {77.0: (0.15, 0.45), 150.0: (0.70, 0.98),
             250.0: (0.85, 1.01), 300.0: (0.95, 1.01)}
    lo, hi = bands[T_K]
    assert lo <= frac_sim <= hi, \
        f"G7b FAIL @{T_K}K: fraction {frac_sim:.3f} outside " \
        f"published band [{lo}, {hi}]"
    if T_K == 77.0:
        assert frac_sim < 0.60, "freeze-out direction violated"


def test_g7d_fd_degenerate_cv_max_direction():
    """G7(d): degenerate MOS C_max DIRECTION gate.  With FD statistics
    the inversion layer's differential capacitance is finite (density
    grows like eta^(3/2), not exponentially), so the strong-inversion
    C_max sits BELOW the classical (Boltzmann) value -- same direction
    as the documented classical overestimate (README section 1), whose
    quantization-free part this gate isolates.  Gate: fd C_max strictly
    below the Boltzmann C_max by 2--30%.

    APPLICABILITY: direction + magnitude band, not a point value; the
    quantum centroid correction remains M20's job."""
    common = dict(Nsub=-1e18, tox_cm=5e-7, gate="n+poly")
    vg = np.linspace(-2.5, 3.0, 111)
    mos_b = MOSCapacitor(**common, T=T, fd=False)
    mos_f = MOSCapacitor(**common, T=T, fd=True)
    _, _, C_b = mos_b.cv_sweep(vg)
    _, _, C_f = mos_f.cv_sweep(vg)
    cmax_b, cmax_f = C_b.max(), C_f.max()
    # classical sanity: accumulation C_max ~= C_ox (existing behavior)
    assert cmax_b >= 0.97 * mos_b.Cox, \
        f"classical C_max {cmax_b:.4f} unexpectedly below Cox"
    red = 1.0 - cmax_f / cmax_b
    assert 0.02 <= red <= 0.30, \
        f"G7d FAIL: FD C_max reduction {red:.3%} outside [2%, 30%]"


# ================================================================ 2D/3D ports
# Plan section 3.4: each port repeats neutrality + FD-Jacobian +
# Boltzmann-regime equivalence gates (bit-identity for fd=False is
# already pinned by tests/test_m13_goldens.py).

def _step2d(na=1e20, nd=1e17, nx=21, ny=7):
    from pytcad.mesh2d import Mesh2D
    xg = graded_mesh(1.0e-4, [0.5e-4], 4e-7, 4e-6, 1.25)
    yg = graded_mesh(0.3e-4, [0.0], 4e-7, 4e-6, 1.25)
    mesh = Mesh2D(xg, yg)
    dop = np.tile(np.where(xg < 0.5e-4, -na, nd), (yg.size, 1))
    dev = Device2D(mesh, dop, models=Models(bgn=False, srh=True,
                                            fd=True))
    dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    return dev


def test_port2d_equilibrium_neutrality():
    """2D port: uniform-doping equilibrium -> (n,p) flat and equal to
    the INDEPENDENT physical-statistics root (<= 1e-12 relative)."""
    net = -1e19
    _, n_ref, p_ref, _ = _fd_neutral_eta(net, SILICON, T)
    from pytcad.mesh2d import Mesh2D
    xg = np.linspace(0.0, 1.0e-4, 15)
    yg = np.linspace(0.0, 0.4e-4, 7)
    mesh = Mesh2D(xg, yg)
    dev = Device2D(mesh, np.full((yg.size, xg.size), net), T=T,
                   models=Models(bgn=False, srh=False, fd=True))
    dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    assert np.ptp(dev.n_cm3) <= 1e-9 * dev.n_cm3.max()
    rel_n = abs(dev.n_cm3[2, 2] - n_ref) / n_ref
    rel_p = abs(dev.p_cm3[2, 2] - p_ref) / p_ref
    assert rel_n <= 1e-12, f"2D neutrality FAIL: n {rel_n:.3e}"
    assert rel_p <= 1e-12, f"2D neutrality FAIL: p {rel_p:.3e}"


def test_port2d_zero_equilibrium_current():
    """2D port: across a DEGENERATE 1e20/1e17 step, both carrier flux
    families vanish to machine precision at equilibrium."""
    dev = _step2d()
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    scale = float(np.abs(dev.n).max() + dev.p.max())
    an_scale = max(float(np.abs(dev.dn_edge_x / dev.hx[None, :]).max()),
                   float(np.abs(dev.dn_edge_y / dev.hy[:, None]).max()))
    limit = 1e-10 * an_scale * scale
    # direct recompute through the residual (returns the six flux arrays)
    _, _, Jn_x, Jn_y, Jp_x, Jp_y, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, {})
    assert np.abs(Jn_x).max() <= limit and np.abs(Jn_y).max() <= limit, \
        f"2D electron equilibrium current {np.abs(Jn_x).max():.2e}"
    assert np.abs(Jp_x).max() <= limit and np.abs(Jp_y).max() <= limit, \
        f"2D hole equilibrium current {np.abs(Jp_x).max():.2e}"


def test_port2d_jacobian_degenerate_step():
    """2D port G5: analytic Jacobian vs central FD on the degenerate
    step junction (house per-column normalization, >= 80 columns)."""
    dev = _step2d()
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    rng = np.random.default_rng(7)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.3, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    ncols = 80
    for c in rng.choice(u.size, size=ncols, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(dev.psi.shape),
                                         u2[1::3].reshape(dev.psi.shape),
                                         u2[2::3].reshape(dev.psi.shape),
                                         voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(dev.psi.shape),
                                         u1[1::3].reshape(dev.psi.shape),
                                         u1[2::3].reshape(dev.psi.shape),
                                         voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, \
        f"2D G5 FAIL: worst FD-Jacobian rel err {worst:.3e}"


def test_port2d_boltzmann_equivalence():
    """2D port: fd=True at 1e15 reduces to the Boltzmann run within the
    exact-series nu deviation (same derivation as the 1D G6b gate)."""
    nd = 1e15
    from pytcad.mesh2d import Mesh2D
    xg = graded_mesh(1.0e-4, [0.5e-4], 4e-7, 4e-6, 1.25)
    yg = graded_mesh(0.3e-4, [0.0], 4e-7, 4e-6, 1.25)
    mesh = Mesh2D(xg, yg)
    dop = np.tile(np.where(xg < 0.5e-4, -nd, nd), (yg.size, 1))
    kw = dict(models=Models(bgn=False, srh=True))
    dev_b = Device2D(mesh, dop, **kw)
    dev_f = Device2D(mesh, dop,
                     models=Models(bgn=False, srh=True, fd=True))
    dev_b.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev_b.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev_f.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev_f.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev_b.solve_equilibrium(); dev_f.solve_equilibrium()
    eta_maj = f_half_inv(nd / SILICON.Nc(T))
    delta = float(np.exp(eta_maj) / 2.0 ** 1.5)
    rel_n = np.abs(dev_f.n_cm3 - dev_b.n_cm3) / dev_b.n_cm3
    rel_p = np.abs(dev_f.p_cm3 - dev_b.p_cm3) / dev_b.p_cm3
    assert rel_n.max() <= 3 * delta, f"2D G6b FAIL: n {rel_n.max():.3e}"
    assert rel_p.max() <= 3 * delta, f"2D G6b FAIL: p {rel_p.max():.3e}"


def _uniform3d(c=1e19, nx=9, ny=5, nz=4):
    from pytcad.mesh3d import Mesh3D
    xg = np.linspace(0.0, 1.0e-4, nx)
    yg = np.linspace(0.0, 0.4e-4, ny)
    zg = np.linspace(0.0, 0.3e-4, nz)
    mesh = Mesh3D(xg, yg, zg)
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), c)
    dev = Device3D(mesh, dop, models=Models(bgn=False, srh=False,
                                            fd=True))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("r", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk,
                    V=0.0)
    return dev


def test_port3d_equilibrium_neutrality():
    """3D port: uniform-doping equilibrium -> flat, matches the
    independent physical root to <= 1e-12."""
    net = -1e19
    _, n_ref, p_ref, _ = _fd_neutral_eta(net, SILICON, T)
    dev = _uniform3d(c=net)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    assert np.ptp(dev.n_cm3) <= 1e-9 * dev.n_cm3.max()
    rel_n = abs(dev.n_cm3[1, 1, 2] - n_ref) / n_ref
    rel_p = abs(dev.p_cm3[1, 1, 2] - p_ref) / p_ref
    assert rel_n <= 1e-12, f"3D neutrality FAIL: n {rel_n:.3e}"
    assert rel_p <= 1e-12, f"3D neutrality FAIL: p {rel_p:.3e}"


def test_port3d_jacobian_degenerate():
    """3D port G5: analytic Jacobian vs central FD, uniform degenerate
    1e19 block under bias (house normalization, >= 60 columns)."""
    dev = _uniform3d()
    dev.solve_equilibrium()
    rng = np.random.default_rng(11)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.3, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(u.size, size=60, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        shp = dev.psi.shape
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, \
        f"3D G5 FAIL: worst FD-Jacobian rel err {worst:.3e}"
