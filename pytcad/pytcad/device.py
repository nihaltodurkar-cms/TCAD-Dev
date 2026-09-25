"""1D drift-diffusion device simulator (the "device TCAD" half of the tool).

THE EQUATIONS
-------------
We solve the classical van Roosbroeck system, self-consistently, in steady
state:

    Poisson        d/dx ( eps dpsi/dx ) = -q ( p - n + N_D^+ - N_A^- )
    electrons      dJn/dx = +q R
    holes          dJp/dx = -q R
    constitutive   Jn = q mu_n n E + q D_n dn/dx = q mu_n n dpsi/dx? ...

written in the drift-diffusion form with Einstein relation D = mu kT/q:

    Jn = q D_n ( -n dpsi/dx / V_T + dn/dx ) * (-1)   [sign per convention]
    Jp = -q D_p ( p dpsi/dx / V_T + dp/dx )

Symbols:
    psi   electrostatic potential [V]        n, p   carrier densities [cm^-3]
    Jn,Jp current densities [A/cm^2]         R      net recombination [cm^-3 s^-1]
    N_D^+, N_A^-  ionised dopant densities [cm^-3]  (full ionisation assumed)
    eps   permittivity [F/cm]                V_T = kT/q

Assumptions and their limits:
  * Boltzmann statistics -- breaks down above ~1e19 cm^-3 (degeneracy);
    the code warns you when the doping crosses that.
  * Full dopant ionisation -- fails at cryogenic temperature.
  * Classical (no quantisation) -- an inversion layer in a modern MOSFET is
    a ~2 nm quantum well; the classical result puts the charge centroid at
    the interface and overestimates gate capacitance by ~10-20%.
  * Steady state, isothermal, no impact ionisation or tunnelling.

DISCRETISATION
--------------
Box (finite-volume) integration on a non-uniform 1D mesh.  Currents on the
interfaces use the Scharfetter-Gummel scheme, which integrates the
drift-diffusion equation exactly under the assumption that J and E are
constant across one cell:

    Jn_{i+1/2} = (q D_n / h) [ n_{i+1} B(d) - n_i B(-d) ],  d = (psi_{i+1}-psi_i)/V_T

with the Bernoulli function B(x) = x / (e^x - 1).  This is the single most
important numerical ingredient: naive central differencing of the drift term
oscillates and goes negative as soon as the potential drop across a cell
exceeds ~2 V_T (52 mV), which happens everywhere in a depletion region.

SCALING
-------
Newton on the raw variables is hopeless: psi ~ 1, n ~ 1e20, R ~ 1e25.  We use
the de Mari scaling
    psi -> psi/V_T,  n,p -> n/n_i,  x -> x/L_D,  L_D = sqrt(eps V_T/(q n_i))
which brings every residual to order unity.
"""

import os
import warnings

from dataclasses import dataclass

import numpy as np

# M12-S2 physical constants for the WKB escape factors
Q_E_CONST = 1.602176634e-19       # C
HBAR_CONST = 1.054571817e-34      # J s
M_E_CONST = 9.1093837015e-31      # kg
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve


def emission_velocity(N_dos_cm3, T):
    """M33-S2: thermionic emission velocity [cm/s] for a band whose
    effective DOS is `N_dos_cm3` (Nc for electrons, Nv for holes).

        v = sqrt(kT / (2 pi m_DOS))

    m_DOS is recovered from the material's OWN band DOS through
    `N = 2 (2 pi m kT / h^2)^{3/2}`, so this needs no new material
    constant and cannot drift away from the Nc/Nv the rest of the
    solver uses. Algebraically it is the familiar `v = A* T^2 / (q N)`
    with `A* = 4 pi q m k^2 / h^3` -- the same formula, expressed
    through the mass that N itself implies.

    IT DOES NOT REPRODUCE A TABULATED A*, AND THAT IS EXPECTED RATHER
    THAN A DEFECT. Measured for silicon at 300 K: this returns
    2.575e6 cm/s where `richardson_a_star("Si","n") * T^2 / (q Nc)`
    gives 4.950e6 -- a factor 1.92. The cause is exactly what
    `schottky.py`'s own module docstring warns about: A* is governed by
    the RICHARDSON mass, not the DOS mass, and silicon's six-valley
    conduction band separates the two. Nc = 2.86e19 implies
    m_DOS = 1.09 m0, while A* = 252 A/(cm^2 K^2) implies 2.1 m0, and
    2.1/1.09 = 1.92. So a tabulated A* is the more accurate number for
    Si SPECIFICALLY, while this form is the one that stays consistent
    with the Nc the solver actually uses and is defined for every
    material including alloys. Treat the velocity as good to about a
    factor of two on silicon; see M33-INTERFACE-PLAN.md section 7.

    Deriving m_DOS from N rather than reading a tabulated A* also
    sidesteps a real trap: that table is keyed on SHORT names ("Si",
    "GaAs") while Semiconductor.name holds full ones ("Silicon"), so
    richardson_a_star(mat.name, "n") raises KeyError for every real
    material object -- and an alloy like AlGaAs has no entry at all.
    """
    N_si = np.asarray(N_dos_cm3, dtype=float) * 1.0e6          # m^-3
    h = 2.0 * np.pi * HBAR_CONST
    kT = KB_EV * Q_E_CONST * T                                 # J
    m_dos = (N_si / 2.0) ** (2.0 / 3.0) * h * h / (2.0 * np.pi * kT)
    return np.sqrt(kT / (2.0 * np.pi * m_dos)) * 100.0         # cm/s

# M31 P4b: symmetric Dirichlet elimination (row AND column) so the
# assembled Jacobian is transposable -- see pytcad/dirichlet.py.
from .dirichlet import eliminate_csr

from . import linsolve

from .constants import KB, KB_EV, Q, EPS0, thermal_voltage
from .schottky import schottky_barrier_height_n as _schottky_barrier_height_n
from .fermi import (
    FERMI_ETA_MAX, FERMI_ETA_MIN, f_half, f_half_inv, f_mhalf,
)
from .ionization import alpha_n as _ii_alpha_n
from .ionization import alpha_p as _ii_alpha_p
from .ionization import dalpha_dE as _ii_dalpha_dE
from .ionization import Q_E as _II_Q
from .btbt import btbt_generation as _btbt_G
from .btbt import dbtbt_dF as _btbt_dG
from .btbt import M0_SI as _NL_M0, Q_SI as _NL_Q
from .nonlocal_path import build_1d as _nl_build_1d
from .nonlocal_path import evaluate as _nl_evaluate
from .ii_nonlocal import effective_field as _ii_eff_field
from .ii_nonlocal import LAMBDA_E_SLOTBOOM_CM as _II_LAMBDA_E

# M15 R1b, ATTEMPT 3 (2026-08-28): impact-ionization generation is
# coupled DIRECTLY into the Newton residual/Jacobian every iterate
# (dG/dpsi, dG/dn, dG/dp folded into _residual_jacobian, chain-ruled
# through the same SG flux partials already computed there) -- no
# frozen source, no outer fixed-point loop.  This Jacobian is UNCHANGED
# from attempts 1 and 2 (both FD-Jacobian-validated); what changed is
# giving pytcad.continuation.arc_length_sweep's corrector its OWN
# generation-strength ramp (see arc_length_sweep's `strength_stages`
# parameter), rather than relying on solve_bias's ladder, which the
# corrector never calls into (that composition gap was attempt 2's
# failure).  A generation-strength continuation ladder is kept for
# Newton robustness navigating the stiff avalanche onset -- see
# _II_STAGES below -- but it now ramps a single scalar multiplying the
# LIVE, fully-coupled term, not a cached array.
_II_STAGES = (0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0)
# M34-S7: the stiff paths' line search halves at most this many times
# (lam >= 2^-10) before taking the full step.  A smaller step cannot
# cover the Newton correction within max_iter = 100, and at a merit on
# its round-off floor such steps "pass" the decrease test by noise --
# measured: M16's tunnel diode at -0.2V accepted lam = 4.8e-7 every
# iteration (merit 1.3e-28 -> 1.3e-28) and never moved.  Was 40.
_LS_MAX_HALVINGS = 10
# M34-S7: the line search is a globalization device for the stiff onset
# (updates of O(1)); once the full Newton correction is below this (psi
# within 1e-3 VT, densities within 0.1%, where the exponentials are
# linear) Newton takes full steps.  Near convergence the merit sits on
# its round-off floor and accepts partial steps by noise, which stops
# the quadratic finish -- measured: M15's diode at -40V, stage 0.7, took
# lam = 1/8..1/64 for 100 iterations at merit 4.2e-26 with a ~1e-8
# correction left, where full steps close (1e-8 -> 1e-15 at -30V).
_LS_NEWTON_REGION = 1e-3
# M34-S7: density floor of the stiff paths' update test (M11-S5's 1e-10
# elsewhere).  The test demands |dn| < tol_update * floor below it, i.e.
# 1e-18 at 1e-10 -- tighter than double precision resolves there:
# measured, sub-floor densities in converged II solves sit in a round-off
# limit cycle of 2-5e-18 (M15 at -32V: p = 3.1e-11; M34-S2 at -20V: p
# 1.1e-17 <-> 1.6e-17 on the n+ side, period 2) with the residual at
# round-off and the current fixed to every digit.  At 1e-8 a sub-floor
# density carries <= 1e-8 of the local charge (M11-S5's own argument) and
# its tolerance, 1e-16, is 20x the measured cycle.
_STIFF_DENSITY_FLOOR = 1e-8
# The leading 0.0 stage is a plain drift-diffusion Newton solve (no
# generation at all) at the NEW bias before any coupling turns on.  It
# replaces the old frozen-source model's implicit protection against
# the contact-stamping field spike: solve_bias stamps psi[0]/psi[-1] to
# the new bias while interior nodes still hold the OLD bias's converged
# profile, so the cell adjacent to the contact reads a transient field
# of order (bias step)/(cell width) -- MV/cm scale for the nm-scale
# contact cells this milestone's test devices use -- until Newton
# relaxes it away.  The frozen model never saw this because it computed
# gs from the smooth PRE-stamp state once and cached it; live coupling
# has no such protection, so without a generation-free relaxation pass
# first, alpha(E) evaluated at that transient spike injects enormous
# spurious generation at iteration 0 and Newton can lock onto a bogus
# high-field state pinned at the contact instead of the real solution
# (verified: E-field at the contact-adjacent node reached ~4e6 V/cm at
# a bias where the impact=False device -- solving the identical contact
# stamp with no generation term at all -- settles at ~2.6e-8 V/cm).

# R1b coupling also chain-rules dG/dn, dG/dp through sign(Jn)/sign(Jp)
# (section 1's spec: "including sign(J) factors, valid away from J=0
# crossings").  In practice an edge current crosses zero SOMEWHERE in
# every biased diode (electron and hole current trade off along the
# device), so a literal sign()/abs() makes |Jn|/|Jp| non-differentiable
# at points Newton's own iterates land on or near -- not a rare probe-
# state edge case but a routine occurrence that stalled the Newton
# backtracking outright (verified: an iterate at a node with a ~1e-9-
# scaled Jp sitting on a ~50-scaled slope, i.e. a hair from its zero
# crossing, made every trial step a non-descent direction).  Both
# |J| and sign(J) are smoothed with a fixed tiny regularizer:
#   smooth_abs(J)  = sqrt(J^2 + eps^2)
#   smooth_sign(J) = J / sqrt(J^2 + eps^2)
# eps is _II_J_EPS_REL times the LARGER of the two edge-current arrays'
# max magnitude for that residual evaluation, so it scales with whatever
# current regime the device is in and only perturbs the immediate
# neighbourhood of an exact zero crossing (a 1e-6 relative deviation
# everywhere else is far below the 5e-5 FD-Jacobian gate and orders of
# magnitude below the physics being resolved).
_II_J_EPS_REL = 1e-6


def _ii_smooth_abs(J, eps):
    return np.sqrt(J * J + eps * eps)


def _ii_smooth_sign(J, eps):
    return J / np.sqrt(J * J + eps * eps)
from .materials import (
    SILICON, Semiconductor, mobility_caughey_thomas, mobility_field,
    nie_effective, lifetime_scharfetter, recombination,
)

# Moved to kernels.py -- pure, mesh-free, vectorized primitives that
# device2d/device3d/unstructured_dd*/moscap were importing out of this
# module.  Re-exported here so every existing import site keeps working.
from .kernels import (  # noqa: E402  (re-export, must follow the imports above)
    D0_REF, bernoulli, dbernoulli, fd_density, fd_ddensity_deta,
)

# M44: coupled electron energy balance reuses M29's already-gated local
# closure inverse (effective_field_from_temperature) and TAU_W_N -- see
# M44-HYDRODYNAMIC-PLAN.md Slice 0, Finding 3.
from . import hydrodynamic as _hydro


def fd_node_factors(nc_s, nv_s, n, p):
    """nu-factor SG quantities on ARBITRARILY shaped density grids
    (shared by the 1D/2D/3D cores; plan section 3.2bis).

    L_x = ln nu_x with nu = F(eta) exp(-eta); w_x = dL/d(density) in
    the cancellation-safe form (F'/F - 1)/(Nc_s F').  For eta <= -30
    both are set to EXACT 0.0 (deep-Boltzmann edges reproduce the
    Boltzmann scheme bit-for-bit), and those nodes never enter
    f_half_inv at all."""
    thr = float(f_half(-30.0))
    Ln = np.zeros_like(n)
    Lp = np.zeros_like(p)
    wn = np.zeros_like(n)
    wp = np.zeros_like(p)
    # broadcast DOS against the density grid so scalar-DOS cores
    # (2D/3D) and per-node arrays (1D heterojunctions) both work
    den_n = np.broadcast_to(np.asarray(nc_s, dtype=float), np.shape(n))
    den_p = np.broadcast_to(np.asarray(nv_s, dtype=float), np.shape(p))
    mn = (n / den_n) > thr
    mp = (p / den_p) > thr
    if bool(mn.any()):
        en = f_half_inv(np.maximum(n[mn], 1e-300) / den_n[mn])
        Fn = f_half(en)
        dFn = f_mhalf(en)
        Ln[mn] = np.log(Fn) - en
        wn[mn] = (dFn / Fn - 1.0) / (den_n[mn] * dFn)
    if bool(mp.any()):
        ep = f_half_inv(np.maximum(p[mp], 1e-300) / den_p[mp])
        Fp = f_half(ep)
        dFp = f_mhalf(ep)
        Lp[mp] = np.log(Fp) - ep
        wp[mp] = (dFp / Fp - 1.0) / (den_p[mp] * dFp)
    return Ln, Lp, wn, wp


def ionized_dE_kt(T):
    """Shallow-dopant ionization energy in units of kT.

    45 meV hydrogenic B/P/As, the single M13 number -- shared so the
    1D core, the 2D/3D cores (M41) and the neutrality roots cannot
    drift apart."""
    return 0.045 / (KB_EV * T)


def ionized_eta_doping(nd, na, eta_n, eta_p, ded_kt):
    """Net IONIZED doping from the reduced Fermi energies (M13).

        N_D+ = N_D / (1 + 2 e^{eta_n + dE/kT})
        N_A- = N_A / (1 + 4 e^{eta_p + dE/kT})

    Returns (cion, dcion_deta_n, dcion_deta_p) with cion = ND+ - NA-,
    all scaled the same way nd/na are.  Split out of Device1D's
    `_ionized_C` (M41) so the 2D/3D cores and every neutrality-root
    bisection evaluate ONE formula; the exponent clamps are the 1D
    ones, unchanged."""
    ed_n = np.exp(np.minimum(eta_n + ded_kt, 700.0))
    ea_p = np.exp(np.minimum(eta_p + ded_kt, 700.0))
    ndp = nd / (1.0 + 2.0 * ed_n)
    nam = na / (1.0 + 4.0 * ea_p)
    dndp_deta = -2.0 * ed_n / (1.0 + 2.0 * ed_n) ** 2 * nd
    dnam_deta = -4.0 * ea_p / (1.0 + 4.0 * ea_p) ** 2 * na
    return ndp - nam, dndp_deta, -dnam_deta


def ionized_doping(nd, na, n, p, nc_s, nv_s, T):
    """Net ionized doping and its derivatives wrt the SLOT DENSITIES.

    The density chain is d(eta)/d(density) = 1/(Nc_s F'(eta)), with the
    exact tail derivative exp(eta) below the validated range
    (consistent with fd_density's piecewise policy).  Independent of
    the `fd` flag by design -- see Models.incomplete_ion.

    Returns (cion, d cion/dn, d cion/dp)."""
    en = f_half_inv(np.maximum(n, 1e-300) / nc_s)
    ep = f_half_inv(np.maximum(p, 1e-300) / nv_s)
    cion, dc_den, dc_dep = ionized_eta_doping(nd, na, en, ep,
                                              ionized_dE_kt(T))
    tail_n = np.exp(np.minimum(en, 700.0))
    tail_p = np.exp(np.minimum(ep, 700.0))
    den_n = np.where(en >= FERMI_ETA_MIN,
                     f_mhalf(np.clip(en, FERMI_ETA_MIN,
                                     FERMI_ETA_MAX)), tail_n)
    den_p = np.where(ep >= FERMI_ETA_MIN,
                     f_mhalf(np.clip(ep, FERMI_ETA_MIN,
                                     FERMI_ETA_MAX)), tail_p)
    detn = 1.0 / np.maximum(nc_s * den_n, 1e-300)
    detp = 1.0 / np.maximum(nv_s * den_p, 1e-300)
    return cion, dc_den * detn, dc_dep * detp


def fd_ohmic_values(C, nc_s, nv_s, ln_gn, eg_kt, V, VT, ion=None):
    """FD ohmic-contact values for ARBITRARY node sets (vectorized
    bisection; the exact Boltzmann closed form is recovered as
    F -> exp).  All inputs broadcast against each other; C is the SCALED
    net doping at the contact nodes.  Returns (psi0, n0, p0) scaled.

    `ion`, if given, is (nd, na, T): the neutrality root then balances
    the net IONIZED doping ND+(e) - NA-(e) instead of C (M13 incomplete
    ionization, lifted to 2D/3D by M41).  `ion=None` is the full-
    ionization path every pre-M41 caller uses, bit-identical."""
    C = np.asarray(C, dtype=float)

    def dens(e):
        return fd_density(nc_s, np.minimum(e, FERMI_ETA_MAX)), \
            fd_density(nv_s, np.minimum(-e - eg_kt, FERMI_ETA_MAX))

    lo = -eg_kt - (FERMI_ETA_MAX - FERMI_ETA_MIN) - 1.0
    hi = np.full(np.shape(C), float(FERMI_ETA_MAX))

    def g(e):
        n_, p_ = dens(e)
        if ion is None:
            return n_ - p_ - C
        # the eta-space form, evaluated at the SAME clamped etas the
        # densities above use -- identical to Device1D's own
        # _fd_neutral_eta, which this replaces for 2D/3D contacts
        nd, na, T_ = ion
        c_, _, _ = ionized_eta_doping(
            nd, na, np.minimum(e, FERMI_ETA_MAX),
            np.minimum(-e - eg_kt, FERMI_ETA_MAX), ionized_dE_kt(T_))
        return n_ - p_ - c_

    flo, fhi = g(lo), g(hi)
    if np.any(flo > 0) or np.any(fhi < 0):
        raise ValueError(
            "FD contact neutrality root not bracketed at a contact "
            "(doping outside the model's validated regime?)")
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        left = g(mid) < 0
        lo = np.where(left, mid, lo)
        hi = np.where(left, hi, mid)
        if np.all(hi - lo < 3e-15 * (1.0 + np.abs(lo))):
            break
    e0 = 0.5 * (lo + hi)
    if np.any(e0 > FERMI_ETA_MAX - 2.0):
        raise ValueError(
            "FD contact eta beyond the validated range; refusing "
            "(M13 G7 applicability limit).")
    n0, p0 = dens(e0)
    psi0 = V / VT + e0 + ln_gn
    return psi0, n0, p0


# ----------------------------------------------------------------------
#  Solver options
# ----------------------------------------------------------------------
@dataclass
class Models:
    doping_mobility: bool = True
    field_mobility: bool = False   # lagged; enable for high-field devices
    srh: bool = True
    # M12-S2: trap-assisted tunneling (Hurkx-style field-enhanced SRH,
    # plan-specified form with WKB escape probabilities in the
    # denominator).  Default OFF => bit-identical to plain SRH.
    tat: bool = False
    trap_et_rel: float = 0.5          # trap level as fraction of Eg
    # M13 phase 2: Fermi-Dirac carrier statistics (parabolic-band
    # F_{1/2}, nu-factor generalized SG -- plan section 3.2bis).
    # Default OFF => bit-identical to Boltzmann (G6a goldens).
    fd: bool = False
    # M13 phase 2: incomplete dopant ionization (shallow B/P/As,
    # degeneracy factors g_D=2 / g_A=4, DeltaE=45 meV).  Independent
    # of fd; 1D only in this milestone.  Hydrogenic model: invalid
    # above the Mott transition (~4e18 cm^-3) and for compensated
    # profiles (net-doping input carries no species split).
    incomplete_ion: bool = False
    # M15: local van Overstraeten-de Man impact ionization.  Default
    # OFF => bit-identical to the plain solver (goldens).
    impact: bool = False
    # M34-S2: nonlocal (effective-field) impact ionization -- M15's
    # alpha evaluated at a per-carrier effective field from the
    # relaxation equation lambda dE_eff/ds + E_eff = |E| along the
    # carrier's drift direction (pytcad/ii_nonlocal.py; Slotboom et al.,
    # IEDM 1991: lambda_e = 650 A).  Requires impact=True.  lambda_p =
    # lambda_n is a named simplification.  Default OFF => the local M15
    # model, bit-identical.  1D only (Device2D/3D implement `impact`
    # since M34-S6 but still refuse this flag).
    impact_nonlocal: bool = False
    impact_lambda_n: float = _II_LAMBDA_E     # cm
    impact_lambda_p: float = _II_LAMBDA_E     # cm
    # M16: local Kane band-to-band tunneling (Hurkx 1992 Si
    # coefficients, G = A F^2 exp(-B/F)).  Default OFF => bit-identical
    # to the plain solver (goldens).  1D only; Device2D/3D raise.
    btbt: bool = False
    # M34-S1: nonlocal PATH Kane BTBT (Esseni et al. 2017,
    # doi:10.1088/1361-6641/aa6fca, eqs 9/11/12 -- see
    # M34-S1-PLAN.md).  Homojunction 1D ONLY (raises otherwise).
    # INDEPENDENT of `btbt` above: this is a first-principles WKB path
    # integral, NOT calibrated against and not numerically comparable
    # to KANE_A_SI/KANE_B_SI's empirical Hurkx fit -- see
    # pytcad/btbt.py's module docstring.  Reduces exactly to its own
    # published uniform-field closed form (eq 8) -- gated in
    # tests/test_model_benchmarks.py.  Window node spans frozen once
    # per solve_bias call (same cadence `_update_tat_probabilities`
    # uses); psi across each span is live in the residual AND the
    # Jacobian.  Default OFF => bit-identical to the plain solver
    # (goldens).
    btbt_nonlocal: bool = False
    # M20: density-gradient quantum correction (Ancona-Stafford form,
    # quantum potential on the slaved equilibrium densities -- see
    # pytcad/dg.py and M20-DENSITY-GRADIENT-PLAN.md).  Default OFF =>
    # bit-identical (goldens).  EQUILIBRIUM-ONLY in this milestone:
    # solve_bias raises on dg=True (DG transport is out of scope);
    # Device2D/Device3D raise on construction.
    dg: bool = False
    dg_gamma: float = 1.0        # Ancona calibration factor (1 = Bohm)
    auger: bool = True
    bgn: bool = True               # bandgap narrowing
    # M14: surface / inversion-layer mobility (Lombardi CVT).
    # Default OFF => bit-identical to the solver without surface
    # scattering (golden gate G-D).  Applied lagged in the Newton
    # loop on 2D devices with a gate contact; raises in 1D/3D.
    surface_mobility: bool = False
    # M14: driving-force choice for high-field mobility in 2D.
    # "field" (default): parallel electric field E (existing behavior).
    # "quasi_fermi": grad(quasi-Fermi) = grad(phi_n) or grad(phi_p),
    # the Sentaurus convention for multi-directional current flow.
    driving_force: str = "field"
    # M33-S1: which band-alignment gauge the heterojunction edge terms
    # use.  "nie" (default) is the PRE-M33 behaviour, kept bit-identical:
    # transport is parameterised by the effective intrinsic
    # concentration alone, which encodes Nc/Nv/Eg but NOT electron
    # affinity, so it splits a band offset symmetrically between Ec and
    # Ev.  "affinity" uses the physical band edges, so chi actually
    # reaches the equations.  See pytcad/M33-INTERFACE-PLAN.md sec 2 for
    # the measurement that found the gap (a 0.5 eV chi step moved the
    # solution by EXACTLY zero).
    band_offset: str = "nie"
    # M33-S2: thermionic-emission interface flux at an abrupt
    # heterointerface, replacing the drift-diffusion (Scharfetter-
    # Gummel) flux on material-change edges ONLY. Requires
    # band_offset="affinity": TE's entire content is the flux limit
    # imposed by dEc, so running it in a gauge that cannot represent
    # dEc would be calibrating a barrier the equations do not have.
    thermionic: bool = False
    # M14: surface recombination velocity at contacts [cm/s], Robin BC
    # Jn.n_hat = q*S_n*(n-n0), Jp.n_hat = q*S_p*(p-p0). S_n = S_p = 0
    # (default) => no surface recombination, bit-identical to the plain
    # Dirichlet contact (verified: (1.0 + 0.0) == 1.0 exactly, no
    # branching needed in the residual/Jacobian). Wired in Device1D and
    # Device2D; Device3D raises (never in the M14 plan's scope for this
    # feature -- see device3d.py's own guard, not this shared one).
    S_n: float = 0.0
    S_p: float = 0.0
    # M44: coupled electron energy balance (Tn), appended as a 4th DOF
    # block (indices 3*N..4*N-1) rather than reindexing the existing
    # 3*N psi/n/p system -- the base block's math and indices are
    # UNCHANGED by this flag (default False => bit-identical, verified
    # by reconstruct-and-compare, see M44-HYDRODYNAMIC-PLAN.md).
    # Electron-only (hole energy balance, Tp, is out of scope -- see
    # the plan's "Scope decision"). The new Tn row's own coefficients
    # that come from psi/n (the local field and current used in the
    # Joule-heating source and the Tn-dependent thermal conductivity)
    # are LAGGED one outer Newton iterate, exactly like
    # Models.field_mobility's own already-accepted mu_n/mu_p lag --
    # this keeps the Tn block's Jacobian an honest, FD-verified
    # TRIDIAGONAL-IN-THETA block with no fabricated cross-derivatives
    # into the psi/n/p columns (those columns are genuinely zero: the
    # lagged coefficients are plain numpy snapshots, not functions of
    # the current Newton iterate, so a full FD-Jacobian sweep over
    # psi/n/p/theta correctly finds no dependence there).
    energy_balance: bool = False
    # When energy_balance is on, its OWN mobility path (Tn -> effective
    # field via hydrodynamic.effective_field_from_temperature -> the
    # SAME materials.mobility_field Canali model) is used instead of
    # field_mobility's local-field mobility -- these are two different
    # sources of the same target quantity, mixing them isn't
    # physically meaningful. Set both flags with intent, not by
    # accident: energy_balance always wins, field_mobility is ignored,
    # not silently composed.

    def __post_init__(self):
        # driving_force is declared and documented as controlling real
        # physics but has no consumer: Canali/mobility_field() (the only
        # place a "driving force" argument exists) is unconditionally
        # NotImplementedError in Device2D/Device3D, and Device1D's plain
        # "field" convention is the only one implemented anywhere.
        # Refuse loudly rather than silently no-op, same as
        # impact/incomplete_ion do for a dimensionality that can't honor
        # them.
        if self.thermionic and self.band_offset != "affinity":
            raise ValueError(
                "Models(thermionic=True) requires band_offset='affinity'. "
                "Thermionic emission is a statement about the band "
                "discontinuity; the legacy 'nie' gauge cannot represent "
                "one (a chi step moves nothing there), so the barrier "
                "would be fictitious. Refusing rather than silently "
                "modelling a barrier of zero.")
        if self.band_offset not in ("nie", "affinity"):
            raise ValueError(
                f"Models.band_offset={self.band_offset!r} is not "
                "recognised -- use 'nie' (legacy symmetric-nie gauge) "
                "or 'affinity' (physical band edges). Refusing rather "
                "than silently picking one.")
        if self.driving_force != "field":
            raise NotImplementedError(
                f"Models.driving_force={self.driving_force!r} is not "
                "implemented -- only the default 'field' driving force "
                "is wired into the mobility model.")
        if self.energy_balance and (self.impact or self.btbt
                                    or self.btbt_nonlocal):
            raise NotImplementedError(
                "Models(energy_balance=True) combined with impact/btbt/"
                "btbt_nonlocal is not implemented in M44 Slice 1: those "
                "flags drive solve_bias's stiff-generation strength-"
                "ladder + backtracking line search, which does not yet "
                "account for the new Tn unknown (the line search's own "
                "merit function is evaluated on a 3*N-only residual "
                "call). Refusing rather than silently ignoring Tn's "
                "update inside that path.")


@dataclass
class NewtonOptions:
    max_iter: int = 100
    tol_update: float = 1e-8       # max scaled update
    tol_residual: float = 1e-10
    max_dpsi: float = 5.0          # damping cap on scaled potential update
    verbose: bool = False
    # M22: linear-solve method for the Newton update.  "direct" is
    # scipy spsolve, EXACTLY -- the default, bit-identical to every
    # pre-M22 solve (gated: tests/test_m22_linsolve.py G1).  "gmres" /
    # "bicgstab" precondition with ILU and are gated to agree with the
    # direct solution within linsolve_rtol (G3), never to return a
    # non-converged iterate silently (G4).
    #
    # M31 P5-1 Phase D: "auto" resolves to a concrete method via
    # linsolve.select_auto's evidence table (real Phase A measurements
    # only -- never a guess), independently at every call site that
    # supports it (every coupled solve_bias, plus device3d.py's
    # structured-3D and the two SCALAR unstructured equilibrium paths).
    # A (dim, unstructured, coupled) combination that has never been
    # measured resolves to "direct" (Gate D-3's explicit refusal, not a
    # default guess).
    #
    # 2026-09-13: default changed "direct" -> "auto" at the user's
    # explicit request (make the PETSc-backed C++ path the default
    # wherever the evidence table says it wins; unmeasured shapes keep
    # falling back to plain "direct" via Gate D-3). This breaks bit-
    # identity for any test that assumed NewtonOptions()'s default
    # equals scipy spsolve exactly (M22 G1's own documented guarantee) --
    # PETSc/iterative solves agree with "direct" only to linsolve_rtol,
    # not bit-for-bit. Any caller that still needs the old guarantee
    # must pass linsolve="direct" explicitly.
    linsolve: str = "auto"
    linsolve_rtol: float = 1e-10
    # M31 P5-1 Phase B: expose the preconditioner flavor and block size
    # that every COUPLED (psi/n/p-interleaved) Newton loop's
    # `solve_linear` call previously hardcoded (`block_size=3`, no
    # `precond`) -- see M31-P5-1-SOLVER-SELECTION-PLAN.md section 3.
    # Defaults reproduce that hardcoding EXACTLY (Gate B-1): a caller
    # that never sets these two fields gets bit-identical behavior to
    # every pre-Phase-B solve, on every fixture, ACCEL on or off.
    #
    # Only the coupled solves read this field -- the SCALAR
    # Poisson-equilibrium solves (Device1D/2D/3D's own
    # solve_equilibrium, unstructured_poisson.py,
    # unstructured_dd3d.py's equilibrium sub-solve, moscap.py) never
    # hardcoded a block_size (there is no psi/n/p interleaving to
    # block on) and continue not passing one, regardless of what this
    # field holds -- setting block_size here has NO EFFECT on those
    # solves. That asymmetry is deliberate, not an oversight: passing
    # block_size=3 into a one-unknown-per-node system would group three
    # unrelated nodes' potentials into a fake "block", which is simply
    # wrong, not merely unhelpful.
    precond: str = "auto"
    block_size: int | None = 3
    # OPT-IN SuperLU column ordering (scipy spsolve's permc_spec) for
    # STRUCTURED Device2D.solve_bias's direct Newton solve -- nothing
    # else reads it. None (default) is the exact pre-existing call, no
    # permc_spec passed. Measured end to end, 2026-09-25 (Windows, full
    # benchmark sizes), "MMD_AT_PLUS_A" vs the default COLAMD: B3 4.09s
    # -> 2.56s, B6 0.57s -> 0.41s -- but B10 (nonlocal BTBT) 13.3s ->
    # 49.4s and B8 (unstructured) 3.6s -> 870.6s. The best ordering
    # depends on the matrix structure, so this is never a default.
    direct_ordering: str | None = None

    def __post_init__(self):
        # Refuse an unreachable preconditioner flavor loudly rather than
        # silently ignoring it -- this project has already been bitten
        # once by a silently-ignored NewtonOptions.linsolve (the reason
        # M31 P5-0 exists: opts.linsolve reached nothing until the
        # unstructured cores were rewired to read it). Mirrors
        # linsolve.solve_linear's own `_PRECOND` contract exactly, so a
        # value this accepts can never be rejected one layer down.
        if self.precond not in ("auto", "block_jacobi", "schur"):
            raise ValueError(
                f"NewtonOptions.precond={self.precond!r} is not a known "
                "preconditioner flavor -- choose from 'auto', "
                "'block_jacobi', 'schur' (linsolve.solve_linear's own "
                "precond= contract).")
        if self.block_size is not None and (
                not isinstance(self.block_size, int) or self.block_size <= 0):
            raise ValueError(
                f"NewtonOptions.block_size={self.block_size!r} must be "
                "a positive int or None.")
        if self.direct_ordering is not None and self.direct_ordering not in (
                "COLAMD", "MMD_AT_PLUS_A", "MMD_ATA", "NATURAL"):
            raise ValueError(
                f"NewtonOptions.direct_ordering={self.direct_ordering!r} is "
                "not a SuperLU column ordering -- choose from None, "
                "'COLAMD', 'MMD_AT_PLUS_A', 'MMD_ATA', 'NATURAL'.")


@dataclass
class SchottkyContact:
    """M46-S1/S2: a metal-semiconductor (Schottky) contact spec for
    Device1D's `schottky_left`/`schottky_right` constructor params --
    couples pytcad.schottky's already-validated barrier-height physics
    (Sze & Ng ch. 3) into the device Newton core, per ARCHITECTURE.md's
    M46 scope note ("couple schottky.py into a device core first").

    phi_metal_eV : metal work function [eV] (Schottky-Mott rule input).
    A_star       : Richardson constant [A/(cm^2 K^2)]. `None` (the
                   default) selects M46-S1's DIRICHLET approximation
                   (below); a real value selects M46-S2's ROBIN
                   (thermionic-emission-limited) boundary condition,
                   both described below. Either way this is the
                   MAJORITY carrier's own effective Richardson
                   constant (see schottky.py's RICHARDSON_A_STAR_TABLE
                   for published per-material/per-carrier values) --
                   the caller's responsibility to pick the one that
                   matches whichever carrier this node's doping sign
                   makes majority, exactly as schottky_iv's own A_star
                   argument already requires.

    A_star=None (M46-S1, DIRICHLET approximation): the contact node's
    majority-carrier density is pinned at its barrier-limited
    equilibrium value (Nc or Nv times exp(-phi_B/kT)), referenced
    through the SAME psi0 = V/VT + ln(n0/nie) formula _contact_values
    already uses for an ohmic contact, just with a barrier-derived n0
    instead of a doping-derived one. Reproduces the correct built-in
    potential / depletion physics and the qualitative rectifying
    asymmetry a real Schottky junction shows, but not a finite
    interface recombination velocity.

    A_star given (M46-S2, ROBIN boundary condition): the majority
    carrier's Dirichlet row is REPLACED by a flux-balance equation,
    J_majority(edge) + v_R*(n_or_p(node) - n0_or_p0) = 0, with
    v_R = A* T^2 / (q * Nc_or_Nv) -- thermionic emission (Sze & Ng)
    restated as a surface recombination velocity, mirroring EXACTLY
    the equation shape M14's own Models(S_n=..., S_p=...) surface-
    recombination Robin BC already implements and gates (device.py's
    "Dirichlet contacts (Robin on n/p...)" block); n0/p0 is the SAME
    barrier-limited value the Dirichlet approximation above uses. The
    minority carrier stays Dirichlet at its mass-action value,
    unchanged. Refused in combination with a nonzero Models.S_n/S_p
    (both would compete for the same boundary row; S_n/S_p are global
    to both contacts in this module's own existing design)."""
    phi_metal_eV: float
    A_star: float = None


# ----------------------------------------------------------------------
#  Device
# ----------------------------------------------------------------------
class Device1D:
    """A 1D two-terminal semiconductor device with ohmic contacts.

    Parameters
    ----------
    x        : node positions [cm], ascending
    doping   : net doping N_D - N_A at each node [cm^-3] (positive = n-type)
    Ntotal   : total ionised impurity concentration for mobility/lifetime
               models [cm^-3]; defaults to |doping|
    """

    def __init__(self, x, doping, Ntotal=None, T=300.0,
                 material: Semiconductor = SILICON,
                 models: Models = None,
                 schottky_left: "SchottkyContact" = None,
                 schottky_right: "SchottkyContact" = None):
        self.schottky_left = schottky_left
        self.schottky_right = schottky_right
        self.x = np.asarray(x, dtype=float)
        self.N = self.x.size
        self.doping = np.asarray(doping, dtype=float)
        self.Ntot = np.abs(self.doping) if Ntotal is None else np.asarray(Ntotal, float)
        self.T = T
        # M11-S3: a single Semiconductor keeps the classic behavior; a
        # per-node sequence defines a heterostructure.  All material
        # fields below become node arrays in that case, and eps(x)
        # enters the Poisson flux form.
        #
        # M33 CORRECTION: this comment used to say "chi/Eg enter the
        # currents through position-dependent nie". That is true of Eg
        # and FALSE of chi. `nie` is sqrt(Nc*Nv)*exp(-Eg/2kT) and
        # contains no affinity at all, so under the default
        # band_offset="nie" gauge a step in chi changes the solution by
        # EXACTLY zero (measured: 0.000e+00 for a 0.5 eV step) and the
        # band offset actually solved is a symmetric split of dEg.
        # Set Models(band_offset="affinity") for the physical band
        # edges -- see M33-INTERFACE-PLAN.md section 2.
        if isinstance(material, Semiconductor):
            self.mats = [material] * len(np.atleast_1d(doping))
        else:
            self.mats = [m for m in material]
            if len(self.mats) != len(np.atleast_1d(doping)):
                raise ValueError(
                    "material list length must match the mesh")
            if not all(isinstance(m, Semiconductor) for m in self.mats):
                raise TypeError("material entries must be Semiconductor")
        self.mat = self.mats[0] if isinstance(material, Semiconductor) \
            else material
        self.models = models or Models()

        if self.Ntot.max() > 1e19 and not getattr(self.models, "fd", False):
            warnings.warn(
                "Doping exceeds ~1e19 cm^-3: Boltzmann statistics used here "
                "overestimate the carrier density. Treat results in the "
                "degenerate regions as qualitative."
            )

        self.VT = thermal_voltage(T)
        self.eps_arr = np.array([m.eps_r * EPS0 for m in self.mats])
        self.chi_arr = np.array([m.chi for m in self.mats])
        self.Eg0_arr = np.array([m.Eg0 for m in self.mats])
        self.eps = self.eps_arr[0]          # reference (legacy attribute)
        self.ni = self.mats[0].ni(T)

        # Concentration scale.  Using n_i (the classical de Mari choice)
        # makes the scaled majority density ~1e7 and the Poisson residual
        # loses ~8 digits to cancellation.  Scaling by the peak doping keeps
        # every majority-carrier term at order unity.
        self.Ns = max(float(np.abs(self.doping).max()), self.ni)
        self.LD = np.sqrt(self.eps * self.VT / (Q * self.Ns))
        self.J0 = Q * D0_REF * self.Ns / self.LD      # current scale [A/cm^2]
        self.R0 = D0_REF * self.Ns / self.LD**2       # rate scale [cm^-3 s^-1]

        # --- scaled geometry ---
        self.xs = self.x / self.LD
        self.h = np.diff(self.xs)
        self.dV = np.zeros(self.N)
        self.dV[1:-1] = 0.5 * (self.h[:-1] + self.h[1:])
        self.dV[0] = 0.5 * self.h[0]
        self.dV[-1] = 0.5 * self.h[-1]

        # --- scaled material fields ---
        self.C = self.doping / self.Ns
        # per-material grouping: each Semiconductor's parameter set is
        # applied only on its own nodes (arrays stay node-ordered)
        self.nie = np.empty(self.N)
        self.mu_n0 = np.empty(self.N)
        self.mu_p0 = np.empty(self.N)
        self.tau_n = np.empty(self.N)
        self.tau_p = np.empty(self.N)
        seen_mats = []                               # identity-unique, ordered
        for mm in self.mats:
            if not any(mm is m2 for m2 in seen_mats):
                seen_mats.append(mm)
        for m in seen_mats:
            nodes = np.array([mm is m for mm in self.mats])
            nt = self.Ntot[nodes]
            self.nie[nodes] = nie_effective(nt, m, T, self.models.bgn)
            self.mu_n0[nodes] = (
                mobility_caughey_thomas(nt, m, T, "n")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_n_max))
            self.mu_p0[nodes] = (
                mobility_caughey_thomas(nt, m, T, "p")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_p_max))
            self.tau_n[nodes] = lifetime_scharfetter(nt, m.tau_n0,
                                                     m.tau_Nref)
            self.tau_p[nodes] = lifetime_scharfetter(nt, m.tau_p0,
                                                     m.tau_Nref)
        self.nie_s = self.nie / self.Ns

        # --- M13: physical band-DOS arrays for Fermi-Dirac statistics.
        # The Boltzmann core works in the symmetric-nie gauge; FD needs
        # the true Nc/Nv-asymmetric statistics:
        #     n = Nc F(eta_n),  eta_n = psi - phi_n - ln(Nc/nie)
        #     p = Nv F(eta_p),  eta_p = -psi + phi_p - ln(Nv/nie)
        # which reproduces nie*exp(+-psi) exactly in the Boltzmann
        # limit and keeps every M11 ln(nie) edge factor intact.
        self.nc_s = np.empty(self.N)
        self.nv_s = np.empty(self.N)
        self.ln_gn = np.empty(self.N)
        self.ln_gp = np.empty(self.N)
        self.eg_kt = np.empty(self.N)
        for m in seen_mats:
            nodes = np.array([mm is m for mm in self.mats])
            self.nc_s[nodes] = m.Nc(T) / self.Ns
            self.nv_s[nodes] = m.Nv(T) / self.Ns
            self.ln_gn[nodes] = np.log(
                self.nc_s[nodes] / self.nie_s[nodes])
            self.ln_gp[nodes] = np.log(
                self.nv_s[nodes] / self.nie_s[nodes])
            self.eg_kt[nodes] = m.Eg(T) / (KB_EV * T)
        # --- M33-S1: band-alignment shift `s` -------------------------
        # The whole affinity gauge is ONE per-node offset. With
        #   s = ln(Nc/nie) + chi/VT
        # the carrier laws become n = nie*exp(psi + s) and
        # p = nie*exp(-(psi + s)), i.e. exactly the legacy nie-gauge
        # forms with psi -> psi + s. Two consequences worth stating:
        #   * n*p = nie^2 still, identically -- mass action is gauge
        #     free, so nothing downstream of the densities changes.
        #   * BOTH carriers take the SAME sign of correction, unlike
        #     M11-S3's ln(nie) factors which are opposite. That is the
        #     physics: a rigid band shift moves Ec and Ev together,
        #     whereas a gap change moves them apart. (Cross-check that
        #     the two derivations agree: ln_gn + ln_gp == Eg/kT
        #     identically, which is what makes the per-carrier and
        #     unified forms the same expression.)
        # Only DIFFERENCES of s are physical, so it is referenced to
        # node 0 -- which also keeps psi numerically comparable between
        # gauges (chi/VT alone is ~156) and makes s identically 0 for a
        # homojunction, so the legacy path is bit-identical by
        # construction rather than by tolerance.
        if self.models.band_offset == "affinity":
            if getattr(self.models, "fd", False) or \
                    getattr(self.models, "incomplete_ion", False):
                raise NotImplementedError(
                    "Models(band_offset='affinity') with fd/"
                    "incomplete_ion is refused: the FD eta-space "
                    "contact solver and the neutral-guess bisection "
                    "both carry their own ln(Nc/nie) offsets, and "
                    "composing them with the affinity shift has not "
                    "been derived or gated here. Refusing rather than "
                    "shipping an unvalidated composition (the M20 "
                    "dg+fd precedent).")
            if getattr(self.models, "dg", False):
                raise NotImplementedError(
                    "Models(band_offset='affinity', dg=True) is refused "
                    "(unvalidated composition).")
            s = self.ln_gn + self.chi_arr / self.VT
            self.band_shift = s - s[0]
        else:
            self.band_shift = np.zeros(self.N)

        if self.models.thermionic and getattr(self.models, "impact", False):
            # The frozen-generation path drives impact ionization off
            # per-edge |J| computed through the drift-diffusion form
            # only; composing a TE interface flux with it was not
            # derived or gated here.
            raise NotImplementedError(
                "Models(thermionic=True, impact=True) is refused: the "
                "frozen impact-ionization source is built from the "
                "drift-diffusion edge currents and does not know about "
                "the thermionic interface flux (unvalidated "
                "composition).")

        # --- M33-S2: thermionic-emission interface edges ---------------
        # An edge is a heterointerface iff its two nodes carry different
        # Semiconductor objects. Identity, not equality: two materials
        # with the same numbers but built separately are still one
        # interface as far as the user's model is concerned, and this
        # matches how `seen_mats` above already groups nodes.
        self._te_edge = np.array(
            [self.mats[i] is not self.mats[i + 1]
             for i in range(self.N - 1)], dtype=bool)
        if self.models.thermionic:
            if not self._te_edge.any():
                raise ValueError(
                    "Models(thermionic=True) but the device is a "
                    "homojunction -- there is no interface to apply a "
                    "thermionic flux to. Refusing rather than silently "
                    "doing nothing.")
            nc = self.nc_s * self.Ns          # physical Nc [cm^-3]
            nv = self.nv_s * self.Ns
            vn = emission_velocity(nc, T)
            vp = emission_velocity(nv, T)
            # Harmonic mean of the two sides' emission velocities. Any
            # SINGLE velocity keeps the flux detailed-balanced (the
            # Nc1/Nc2 factor in the interface coefficients is what does
            # that), so the choice is a modelling one -- and the
            # harmonic mean is the one that is symmetric under reversing
            # the mesh, which a one-sided choice is not, and it matches
            # the hmean convention `dn_edge` already uses for edge
            # diffusivities.
            def _hmean(a):
                return 2.0 * a[:-1] * a[1:] / (a[:-1] + a[1:])
            # K = v * LD / D0_REF is the exact analogue of the
            # drift-diffusion edge coefficient an = (D/D0_REF)/h_scaled,
            # with an emission velocity replacing D/length. Derived from
            # J0 = q*D0_REF*Ns/LD: K = q*v*Ns/J0.
            self._te_Kn = _hmean(vn) * self.LD / D0_REF
            self._te_Kp = _hmean(vp) * self.LD / D0_REF
            self._te_dlnNc = np.log(self.nc_s[1:] / self.nc_s[:-1])
            self._te_dlnNv = np.log(self.nv_s[1:] / self.nv_s[:-1])
            self._te_rNc = self.nc_s[:-1] / self.nc_s[1:]
            self._te_rNv = self.nv_s[:-1] / self.nv_s[1:]

        # M34-S1: nonlocal path BTBT is homojunction-only (S1 scope --
        # see M34-S1-PLAN.md section 1). Reuses the SAME `_te_edge`
        # heterointerface detector M33-S2 already built above.
        if getattr(self.models, "btbt_nonlocal", False):
            if self._te_edge.any():
                raise NotImplementedError(
                    "Models(btbt_nonlocal=True) is homojunction-only "
                    "(M34-S1 scope) -- this device has a heterointerface. "
                    "Refusing rather than silently applying a "
                    "single-material formula across a hetero boundary.")

        # M34-S2: the nonlocal effective field only modifies the local
        # impact model's coefficients, so it needs that model on.
        if getattr(self.models, "impact_nonlocal", False):
            if not getattr(self.models, "impact", False):
                raise ValueError(
                    "Models(impact_nonlocal=True) modifies the impact-"
                    "ionization coefficients and needs Models(impact=True) "
                    "as well.")
            for lam in (self.models.impact_lambda_n,
                        self.models.impact_lambda_p):
                if not lam > 0.0:
                    raise ValueError(
                        f"impact_lambda_n/p must be > 0 cm, got {lam}")

        # M13 incomplete ionization: dopant split from the net doping.
        # Single-species assumption (majority side carries all dopants);
        # documented in Models.incomplete_ion.
        self.nd_arr = np.maximum(self.doping, 0.0) / self.Ns   # scaled N_D
        self.na_arr = np.maximum(-self.doping, 0.0) / self.Ns  # scaled N_A

        # interface (harmonic-mean) diffusivities, scaled
        self._set_edge_diffusivity(self.mu_n0, self.mu_p0)

        # M44: coupled electron energy balance scaling constants.
        # theta = Tn/T (dimensionless, ==1 at lattice temperature).
        # Steady-state energy balance (Grasser/Tang/Kosina/Selberherr,
        # Proc. IEEE 91(2) 2003, Eqs. 58-59, div/dt terms dropped for a
        # steady bias solve):
        #   d(W)/dx = E.Jn - n*(3/2)*kB*(Tn-TL)/tau_w
        #   W       = -(5/2)*(kB*Tn/q)*Jn - kappa_n(Tn)*dTn/dx
        #   kappa_n = (5/2)*(kB/q)^2 * (q*mu_n*n) * Tn      [Wiedemann-
        #             Franz-type closure; the "5/2" nondegenerate-gas
        #             coefficient is the SAME one multiplying the
        #             convective term above -- cross-checked against
        #             the same source's Eq. (65) discussion of why
        #             the three-moment model uses one shared 5/2
        #             factor for both terms]
        # Nondimensionalized by the existing J0/VT/LD/Ns scales (energy
        # flux scale W0 = J0*VT, source scale Q0 = W0/LD):
        #   ALPHA_RELAX * n_s * (theta-1)  <->  n*(3/2)kB(Tn-TL)/tau_w / Q0
        #   KAPPA0 * mu_n0*n_s*theta       <->  kappa_n(Tn) * T / (LD*Q0)
        # (see M44-HYDRODYNAMIC-PLAN.md Slice 1 for the full derivation)
        self._ALPHA_RELAX = (1.5 * KB * self.T * self.Ns * self.LD
                             / (_hydro.TAU_W_N * self.J0 * self.VT))
        self._KAPPA0 = (2.5 * (KB * KB / Q) * self.Ns * self.T * self.T
                        / (self.LD * self.J0 * self.VT))
        self.Tn = None       # physical carrier temperature [K], None off

        self.psi = None
        self.n = None
        self.p = None
        # M15 frozen impact-ionization field/source (per bias solve;
        # cleared by solve_equilibrium -- no generation at V=0 gauge)
        self._ii_E = None
        self._ii_gs = None
        # M15: last generation source array _residual_jacobian actually
        # computed and integrated (live, fully-coupled -- see R1b fix
        # above), kept for introspection/tests.  None whenever
        # Models.impact is False; never read back into the residual.
        self._ii_gs_cache = None
        # M15 generation-strength continuation multiplier; see _II_STAGES.
        self._ii_strength = 1.0
        # M16: last BTBT generation source array [physical cm^-3 s^-1]
        # the residual actually integrated (live, fully-coupled like
        # the M15 R1b II source).  None whenever Models.btbt is False;
        # never read back into the residual.
        self._btbt_gs_cache = None
        # M34-S1: frozen nonlocal-BTBT tunnel windows -- located once
        # per solve_bias call (lazily, on first residual evaluation,
        # same None-cache cadence as `_Pn`/`_Pp` below), then held
        # fixed through that call's Newton iterations.  Reset to None
        # at the same points `_btbt_gs_cache` is reset.
        self._btbt_nl_paths = None
        # M12-S2 frozen-field WKB escape probabilities (None until the
        # first TAT-enabled residual evaluation freezes them)
        self._Pn = None
        self._Pp = None
        # M22 phase 2: convergence status of the last solve_bias call.
        self.last_converged = None
        # M34-S1: outcome of solve_bias's post-convergence path refresh
        self.last_btbt_nl_refreshes = 0
        self.last_btbt_nl_stable = None
        self.last_newton_err = None

    # ------------------------------------------------------------------
    def _eps_tilde_edge(self):
        """Harmonic-mean scaled permittivity on edges, normalized by the
        FIRST material's eps so a uniform device gives exactly 1.0
        everywhere and every residual reduces to its original form."""
        et_n = self.eps_arr / self.eps_arr[0]
        return 2.0 * et_n[:-1] * et_n[1:] / (et_n[:-1] + et_n[1:])

    def _set_edge_diffusivity(self, mu_n, mu_p):
        """Einstein relation D = mu V_T; harmonic mean onto the interfaces.

        Harmonic averaging (rather than arithmetic) is the right choice for a
        flux-continuous quantity across an abrupt change in mobility.
        """
        def hmean(a):
            return 2.0 * a[:-1] * a[1:] / (a[:-1] + a[1:])
        self.dn_edge = hmean(mu_n) * self.VT / D0_REF
        self.dp_edge = hmean(mu_p) * self.VT / D0_REF

    # ------------------------------------------------------------------
    #  M13 Fermi-Dirac core helpers
    # ------------------------------------------------------------------
    def _fd_eta(self, n, p):
        """Physical reduced Fermi energies from the slot densities.

        eta_n = f_half_inv(n / Nc_s), eta_p = f_half_inv(p / Nv_s).
        Pure functions of the density unknowns (the psi dependence is
        implicit in the Newton iterate)."""
        en = f_half_inv(np.maximum(n, 1e-300) / self.nc_s)
        ep = f_half_inv(np.maximum(p, 1e-300) / self.nv_s)
        return en, ep

    def _fd_factors(self, n, p):
        """nu-factor SG quantities per node (plan section 3.2bis).

        L_x = ln nu_x with nu = F(eta) exp(-eta); the SG edge arguments
        gain +dL_n (electrons) and -dL_p (holes).  w_x = dL/d(density)
        in the cancellation-safe form (F'/F - 1)/(Nc_s F').  For
        eta <= -30 both are set to EXACT 0.0: the true |L| there is
        below e^-30/sqrt(2) ~ 5e-14, so deep-Boltzmann edges reproduce
        today's deltas bit-for-bit.  Nodes that far out are never sent
        through f_half_inv at all (their factor is zero by definition),
        which keeps the hot path proportional to the number of
        moderately-degenerate nodes only."""
        return fd_node_factors(self.nc_s, self.nv_s, n, p)

    def _ionized_C(self, n, p):
        """Incomplete-ionization net ionized doping (scaled) and its
        derivatives wrt the scaled slot densities.

            N_D+ = N_D / (1 + g_D e^{eta_n + dEd/kT}),   g_D = 2
            N_A- = N_A / (1 + g_A e^{eta_p + dEa/kT}),   g_A = 4

        Shallow hydrogenic B/P/As only (dE = 45 meV); single-species
        (majority side carries all dopants).

        M41 factored the body out to the module-level `ionized_doping`
        so Device2D/Device3D evaluate the SAME formula rather than a
        third copy of it; this method is the 1D binding."""
        return ionized_doping(self.nd_arr, self.na_arr, n, p,
                              self.nc_s, self.nv_s, self.T)

    def _fd_neutral_eta(self, C):
        """Vectorized ohmic-contact / bulk-equilibrium root in eta.

        Solves g(e) = n(e) - p(e) - C_ion(e) = 0 node-by-node, where
        C_ion is the net IONIZED doping: identically C under full
        ionization, otherwise ND+(e) - NA-(e) from the incomplete-
        ionization model (single-species per node, so g is strictly
        increasing -- each component rises with e).  C is the length-N
        array of scaled net doping.  Used for ohmic contact values and
        the equilibrium initial guess."""
        lo = -self.eg_kt - (FERMI_ETA_MAX - FERMI_ETA_MIN) - 1.0
        hi = np.full(self.N, float(FERMI_ETA_MAX))

        def g(e):
            # upper-side clamp keeps the evaluation inside the
            # validated range even at the extreme bracket ends (the
            # root itself sits far away; the sign there is unambiguous)
            n_ = fd_density(self.nc_s, np.minimum(e, FERMI_ETA_MAX))
            p_ = fd_density(self.nv_s,
                            np.minimum(-e - self.eg_kt,
                                       FERMI_ETA_MAX))
            if getattr(self.models, "incomplete_ion", False):
                cion, _, _ = ionized_eta_doping(
                    self.nd_arr, self.na_arr,
                    np.minimum(e, FERMI_ETA_MAX),
                    np.minimum(-e - self.eg_kt, FERMI_ETA_MAX),
                    ionized_dE_kt(self.T))
            else:
                cion = C
            return n_ - p_ - cion

        flo, fhi = g(lo), g(hi)
        if np.any(flo > 0) or np.any(fhi < 0):
            raise ValueError(
                "FD contact neutrality root not bracketed; doping "
                "outside the model's validated regime?")
        for _ in range(300):
            mid = 0.5 * (lo + hi)
            left = g(mid) < 0
            lo = np.where(left, mid, lo)
            hi = np.where(left, hi, mid)
            if np.all(hi - lo < 3e-15 * (1.0 + np.abs(lo))):
                break
        res = 0.5 * (lo + hi)
        # a root pinned to the +40 saturation boundary means the state
        # itself is outside the validated model range -- refuse loudly
        if np.any(res > FERMI_ETA_MAX - 2.0):
            raise ValueError(
                "FD neutrality eta beyond the validated range; refusing "
                "(M13 G7 applicability limit).")
        return res

    def _fd_contact_values(self, V):
        """FD ohmic contacts: local neutrality with physical-statistics
        mass action n0 = Nc F(e), p0 = Nv F(-e - Eg/kT), and
        psi0 = V/V_T + e + ln(Nc/nie) -- reduces exactly to the
        Boltzmann form as F -> exp."""
        e_nodes = self._fd_neutral_eta(self.C)
        out = []
        for i, node in enumerate((0, self.N - 1)):
            e0 = float(e_nodes[node])
            n0 = float(fd_density(self.nc_s[node], e0))
            ep0 = -e0 - self.eg_kt[node]
            p0 = float(fd_density(self.nv_s[node], ep0))
            psi0 = V[i] / self.VT + e0 + self.ln_gn[node]
            out.append((float(psi0), float(n0), float(p0)))
        return out

    def _contact_values(self, V):
        """Ohmic contact: local charge neutrality + thermal equilibrium.

            n0 - p0 = C,   n0 p0 = n_ie^2
        =>  n0 = 0.5 [ C + sqrt(C^2 + 4 n_ie^2) ]
            psi = V/V_T + ln(n0 / n_ie)

        Always evaluate the MAJORITY carrier from the square root and get the
        minority one from the mass-action law.  Doing it the other way round
        subtracts two nearly equal numbers -- for C/n_ie ~ 1e7 the minority
        density comes out with only two correct digits.
        """
        out = []
        # M13: the FD contact solver handles incomplete ionization too,
        # and reduces exactly to the Boltzmann closed form below, so any
        # ionization-enabled run routes through it (flag independence).
        if getattr(self.models, "fd", False) or \
                getattr(self.models, "incomplete_ion", False):
            return self._fd_contact_values(V)
        schottky_sides = (self.schottky_left, self.schottky_right)
        for side, i in enumerate((0, self.N - 1)):
            sch = schottky_sides[side]
            C, nie = self.C[i], self.nie_s[i]
            if sch is not None:
                # M46-S1: barrier-limited majority density instead of
                # local-neutrality's doping-limited one -- see
                # SchottkyContact's own docstring for the Dirichlet-
                # approximation scope. Majority side still follows the
                # SEMICONDUCTOR's own doping sign at this node (a
                # Schottky contact on an n-type node barriers electrons;
                # on a p-type node it barriers holes), matching Sze &
                # Ng's phi_Bn/phi_Bp complementary-barrier convention.
                phi_m = sch.phi_metal_eV
                chi_eV = self.chi_arr[i]
                if C >= 0.0:
                    phi_B = _schottky_barrier_height_n(phi_m, chi_eV)
                    n0 = self.nc_s[i] * np.exp(-phi_B / (KB_EV * self.T))
                    p0 = nie * nie / n0
                else:
                    Eg_eV = self.mats[i].Eg(self.T)
                    phi_Bn = _schottky_barrier_height_n(phi_m, chi_eV)
                    phi_B = Eg_eV - phi_Bn
                    p0 = self.nv_s[i] * np.exp(-phi_B / (KB_EV * self.T))
                    n0 = nie * nie / p0
            else:
                root = np.sqrt(C * C + 4.0 * nie * nie)
                if C >= 0.0:                 # n-type: electrons are majority
                    n0 = 0.5 * (C + root)
                    p0 = nie * nie / n0
                else:                        # p-type: holes are majority
                    p0 = 0.5 * (-C + root)
                    n0 = nie * nie / p0
            # M33-S1: n0/p0 come from local neutrality + mass action and
            # are gauge-free; only psi0's reference moves, by -s[i].
            psi0 = (V[side] / self.VT + np.log(n0 / nie)
                    - self.band_shift[i])
            out.append((psi0, n0, p0))
        return out

    # ------------------------------------------------------------------
    #  Equilibrium (Poisson only, carriers slaved to psi)
    # ------------------------------------------------------------------
    def solve_equilibrium(self, opts: NewtonOptions = None):
        opts = opts or NewtonOptions()
        h, dV, C, nie = self.h, self.dV, self.C, self.nie_s
        et = self._eps_tilde_edge()
        fd = getattr(self.models, "fd", False)
        ion = getattr(self.models, "incomplete_ion", False)
        # M20: density-gradient quantum correction (equilibrium-only;
        # see Models.dg).  dg=True delegates to _solve_equilibrium_dg_
        # coupled, a genuinely COUPLED Newton solve of (psi, Lambda_n,
        # Lambda_p) together -- see that method's docstring, and
        # moscap.py's identical MOSCapacitor reformulation, for why an
        # earlier LAGGED outer-fixed-point scheme was replaced
        # (M20-DENSITY-GRADIENT-PLAN.md section 6).  dg+fd and
        # dg+incomplete_ion stay refused (joint density law not
        # derived/validated; plan section 5).
        dg = getattr(self.models, "dg", False)
        if dg and fd:
            raise NotImplementedError(
                "Models(dg=True, fd=True) is refused: the DG correction "
                "and FD statistics compose through a joint density law "
                "that has not been derived/validated here "
                "(M20-DENSITY-GRADIENT-PLAN.md sec 5).")
        if dg and ion:
            # The ionization chain (dcden/dcdp) is built on the
            # CLASSICAL densities; the DG correction would silently
            # discard it in the dnp overwrite below.  Refuse rather
            # than compose two corrections nobody validated together.
            raise NotImplementedError(
                "Models(dg=True, incomplete_ion=True) is refused "
                "(unvalidated composition; M20 plan sec 5).")
        if dg:
            return self._solve_equilibrium_dg_coupled(opts)

        if fd or ion:
            # M13: eta-space neutral guess (the Boltzmann arcsinh form
            # overshoots badly when ln(Nc/nie) is large -- e.g. GaAs,
            # cryogenic T); psi = eta + ln(Nc/nie) per node.
            psi = self._fd_neutral_eta(C) + self.ln_gn
        else:
            # M33-S1: the neutral guess is a statement about the
            # CARRIER law, so it lands in the shifted variable; -s
            # brings it back to the electrostatic potential the Poisson
            # flux below is written in.
            psi = np.arcsinh(C / (2.0 * nie)) - self.band_shift
        bc = self._contact_values([0.0, 0.0])
        psi[0], psi[-1] = bc[0][0], bc[1][0]

        for it in range(opts.max_iter):
            if fd:
                # M13: FD equilibrium densities slaved to psi
                # (phi_n = phi_p = 0):  n = Nc F(psi - ln(Nc/nie)),
                # p = Nv F(-psi - Eg/kT - ln(Nv/nie)).
                # Clamp to FERMI_ETA_MAX before evaluating, matching the
                # np.minimum(..., FERMI_ETA_MAX) guard used for the same
                # quantity elsewhere in this file (e.g. the neutral-guess
                # bisection above): a transient Newton overshoot must not
                # abort the whole solve when the converged answer would
                # be valid -- fd_density/fd_ddensity_deta still refuse
                # loudly for any eta that is genuinely out of range once
                # this loop actually converges.
                en = np.minimum(psi - self.ln_gn, FERMI_ETA_MAX)
                ep = np.minimum(-psi - self.ln_gp, FERMI_ETA_MAX)
                n = fd_density(self.nc_s, en)
                p = fd_density(self.nv_s, ep)
                dnp = (fd_ddensity_deta(self.nc_s, en)
                       + fd_ddensity_deta(self.nv_s, ep))
            else:
                # M33-S1: carriers are slaved to psi + s, not psi.
                psi_c = psi + self.band_shift
                n = nie * np.exp(np.clip(psi_c, -700, 700))
                p = nie * np.exp(np.clip(-psi_c, -700, 700))
                dnp = n + p
            # M13: incomplete ionization under EITHER statistics;
            # rho = n - p - C_ion with the slaved-density chain
            # d(rho)/d(psi) = (1-dcden)*dn/dpsi + (1+dcdp)*|dp/dpsi|
            # (eta_p falls as psi rises, cancelling the carrier sign).
            c_eff = C
            if getattr(self.models, "incomplete_ion", False):
                cion, dcden, dcdp = self._ionized_C(n, p)
                c_eff = cion
                if fd:
                    fddn = fd_ddensity_deta(
                        self.nc_s,
                        np.minimum(psi - self.ln_gn, FERMI_ETA_MAX))
                    fddp = fd_ddensity_deta(
                        self.nv_s,
                        np.minimum(-psi - self.ln_gp, FERMI_ETA_MAX))
                    dnp = dnp - dcden * fddn + dcdp * fddp
                else:
                    dnp = dnp - dcden * n + dcdp * p

            F = np.zeros(self.N)
            F[1:-1] = (et[1:] * (psi[2:] - psi[1:-1]) / h[1:]
                   - et[:-1] * (psi[1:-1] - psi[:-2]) / h[:-1]
                   - dV[1:-1] * (n[1:-1] - p[1:-1]
                                 - c_eff[1:-1]))
            F[0] = psi[0] - bc[0][0]
            F[-1] = psi[-1] - bc[1][0]

            main = np.zeros(self.N)
            lower = np.zeros(self.N - 1)
            upper = np.zeros(self.N - 1)
            main[1:-1] = (-et[1:] / h[1:] - et[:-1] / h[:-1]
                          - dV[1:-1] * dnp[1:-1])
            upper[1:] = et[1:] / h[1:]
            lower[:-1] = et[:-1] / h[:-1]
            main[0] = main[-1] = 1.0
            upper[0] = 0.0
            lower[-1] = 0.0

            rows = np.concatenate([np.arange(self.N),
                                   np.arange(1, self.N),
                                   np.arange(self.N - 1)])
            cols = np.concatenate([np.arange(self.N),
                                   np.arange(self.N - 1),
                                   np.arange(1, self.N)])
            vals = np.concatenate([main, lower, upper])
            A = csr_matrix((vals, (rows, cols)), shape=(self.N, self.N))
            # Symmetric Dirichlet elimination: both contact ROWS are
            # already e_k (main[0]=main[-1]=1, upper[0]=lower[-1]=0),
            # but their COLUMNS still carry the neighbour couplings
            # lower[0] and upper[-1]. Substituting those out leaves the
            # same system with a transposable matrix -- see
            # pytcad/dirichlet.py.
            A, eq_rhs = eliminate_csr(A, -F, np.array([0, self.N - 1]))

            # linsolve.solve_linear(method="direct") no longer
            # reformats A before calling spsolve (that reformatting was
            # itself the bug -- see linsolve.py), so this is now
            # actually bit-identical to the raw spsolve(A, -F) call
            # while adding the finiteness/singularity checks every
            # other Newton loop in this file already goes through.
            d, _ = linsolve.solve_linear(A, eq_rhs, method="direct")
            d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
            psi = psi + d
            if opts.verbose:
                print(f"    eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
            if np.abs(d).max() < opts.tol_update:
                break
        else:
            warnings.warn("Equilibrium Poisson solve did not converge.")

        self._ii_gs = None               # no II source at equilibrium
        self._ii_gs_cache = None         # clear frozen generation cache
        self._btbt_gs_cache = None       # M16: no BTBT source at V=0 gauge
        self._btbt_nl_paths = None      # M34-S1: same, nonlocal windows
        self._dg_Lam_n = None
        self._dg_Lam_p = None
        self.psi = psi
        if fd:
            # The clamp above in the loop protects against a TRANSIENT
            # overshoot during iteration; it must not also silently
            # accept a CONVERGED eta genuinely outside the validated
            # range -- that would defeat fd_density's own "no silent
            # extrapolation" refusal (M13 G7) for exactly the states it
            # exists to catch, not just the states it was supposed to
            # protect. Check the raw, unclamped eta here instead of
            # clamping-and-forgetting.
            en_raw = psi - self.ln_gn
            ep_raw = -psi - self.ln_gp
            if np.any(en_raw > FERMI_ETA_MAX) or np.any(ep_raw > FERMI_ETA_MAX):
                raise ValueError(
                    f"FD equilibrium converged to eta_n={en_raw.max():.1f} / "
                    f"eta_p={ep_raw.max():.1f}, beyond +{FERMI_ETA_MAX:.0f}: "
                    "outside the validated Fermi-integral range (M13 G7 "
                    "applicability).  Refusing to extrapolate.")
            self.n = fd_density(self.nc_s, en_raw)
            self.p = fd_density(self.nv_s, ep_raw)
        else:
            self.n = nie * np.exp(np.clip(psi, -700, 700))
            self.p = nie * np.exp(np.clip(-psi, -700, 700))
        if self.models.energy_balance:
            # M44: zero current at equilibrium => zero Joule heating =>
            # theta==1 is the EXACT steady-state solution of the energy
            # balance equation (both the source and flux terms vanish
            # identically), not an approximation -- no new equation is
            # solved here.
            self.Tn = np.full(self.N, self.T)
        return self

    # ------------------------------------------------------------------
    #  M20 coupled-Newton density-gradient equilibrium solve
    # ------------------------------------------------------------------
    def _dg_residual_jacobian_eq(self, psi, Lam_n, Lam_p, bc, gamma=None):
        """M20 coupled-Newton DG residual/Jacobian for equilibrium.

        Same architecture as MOSCapacitor._dg_residual_jacobian (see
        that method's docstring for the full derivation) -- unknowns
        interleaved [psi_i, Lambda_n_i, Lambda_p_i] per node,
        replacing the lagged outer fixed point. Two differences from
        the MOSCapacitor version, both from Device1D's own physics:
        (1) the Poisson row uses the permittivity-weighted edge
        conductance et[] (heterostructure-aware) instead of a bare
        1/h; (2) BOTH boundary nodes are pure Dirichlet OHMIC CONTACTS
        (psi[0]=bc[0][0], psi[-1]=bc[1][0]), not a Si/SiO2 interface,
        so the Lambda boundary rows stay the plain Lambda=0 Neumann
        choice -- the MOSCapacitor hard-wall fix (forcing Lambda to
        its clamp at the interface) is specific to a real oxide
        boundary and does NOT apply here; an ohmic contact's classical
        density is not sharply peaked at the boundary node the way a
        strong-inversion MOS surface is, so the wrong-sign pathology
        that motivated that fix has no equivalent here.

        Returns (F [3N], J [3N x 3N] csr_matrix).
        """
        from .dg import _dg_prefactor
        N = self.N
        VT = self.VT
        gamma = getattr(self.models, "dg_gamma", 1.0) if gamma is None else gamma
        h, dV, C, nie = self.h, self.dV, self.C, self.nie_s
        et = self._eps_tilde_edge()

        e = np.clip(psi, -700, 700)
        n = nie * np.exp(e) * np.exp(-Lam_n / VT)
        p = nie * np.exp(-e) * np.exp(-Lam_p / VT)
        dnp = n + p
        rho = n - p - C

        h_phys = np.diff(self.x)                       # cm, PHYSICAL
        m_n = np.array([m.m_n_star for m in self.mats])
        m_p = np.array([m.m_p_star for m in self.mats])
        pref_n = _dg_prefactor(m_n, gamma) * 1e4
        pref_p = _dg_prefactor(m_p, gamma) * 1e4

        gn = np.sqrt(np.maximum(n, 1e-300))
        gp = np.sqrt(np.maximum(p, 1e-300))

        F = np.zeros(3 * N)
        rows, cols, vals = [], [], []

        def add(r, c, v):
            rows.append(r); cols.append(c); vals.append(v)

        def ip(i): return 3 * i
        def iln(i): return 3 * i + 1
        def ilp(i): return 3 * i + 2

        # ---- Poisson rows: pure Dirichlet at both contacts ----------
        F[ip(0)] = psi[0] - bc[0][0]
        add(ip(0), ip(0), 1.0)
        F[ip(N - 1)] = psi[N - 1] - bc[1][0]
        add(ip(N - 1), ip(N - 1), 1.0)

        if N >= 3:
            i = np.arange(1, N - 1)
            F[3 * i] = (et[i] * (psi[i + 1] - psi[i]) / h[i]
                        - et[i - 1] * (psi[i] - psi[i - 1]) / h[i - 1]
                        - dV[i] * rho[i])
        for i in range(1, N - 1):
            add(ip(i), ip(i - 1), et[i - 1] / h[i - 1])
            add(ip(i), ip(i),
                -et[i] / h[i] - et[i - 1] / h[i - 1] - dV[i] * dnp[i])
            add(ip(i), ip(i + 1), et[i] / h[i])
            add(ip(i), iln(i), dV[i] * n[i] / VT)
            add(ip(i), ilp(i), -dV[i] * p[i] / VT)

        # ---- Lambda_n / Lambda_p rows --------------------------------
        # Boundary nodes: Lambda = 0 (Neumann -- ohmic contacts, see
        # docstring; NOT the MOSCapacitor hard-wall treatment).
        for idxb in (iln, ilp):
            F[idxb(0)] = (Lam_n if idxb is iln else Lam_p)[0]
            add(idxb(0), idxb(0), 1.0)
            F[idxb(N - 1)] = (Lam_n if idxb is iln else Lam_p)[N - 1]
            add(idxb(N - 1), idxb(N - 1), 1.0)

        for i in range(1, N - 1):
            hm, hp = h_phys[i - 1], h_phys[i]
            c0 = 2.0 / (hm + hp)

            for g, Lam, pref, idx, sign in (
                (gn, Lam_n, pref_n, iln, +1.0),
                (gp, Lam_p, pref_p, ilp, -1.0),
            ):
                dd_i = c0 * ((g[i + 1] - g[i]) / hp - (g[i] - g[i - 1]) / hm)
                F[idx(i)] = Lam[i] * g[i] + pref[i] * dd_i

                dg_dpsi_i = sign * g[i] / 2.0
                dg_dLam_i = -g[i] / (2.0 * VT)
                dg_dpsi_im1 = sign * g[i - 1] / 2.0
                dg_dLam_im1 = -g[i - 1] / (2.0 * VT)
                dg_dpsi_ip1 = sign * g[i + 1] / 2.0
                dg_dLam_ip1 = -g[i + 1] / (2.0 * VT)

                ddd_dgi = -c0 * (1.0 / hp + 1.0 / hm)
                ddd_dgim1 = c0 / hm
                ddd_dgip1 = c0 / hp

                add(idx(i), ip(i),
                    Lam[i] * dg_dpsi_i + pref[i] * ddd_dgi * dg_dpsi_i)
                add(idx(i), idx(i),
                    g[i] + Lam[i] * dg_dLam_i + pref[i] * ddd_dgi * dg_dLam_i)
                add(idx(i), ip(i - 1), pref[i] * ddd_dgim1 * dg_dpsi_im1)
                add(idx(i), (iln(i - 1) if idx is iln else ilp(i - 1)),
                    pref[i] * ddd_dgim1 * dg_dLam_im1)
                add(idx(i), ip(i + 1), pref[i] * ddd_dgip1 * dg_dpsi_ip1)
                add(idx(i), (iln(i + 1) if idx is iln else ilp(i + 1)),
                    pref[i] * ddd_dgip1 * dg_dLam_ip1)

        J = csr_matrix((vals, (rows, cols)), shape=(3 * N, 3 * N))
        # Pinned rows of the coupled (psi, Lambda_n, Lambda_p) system:
        # psi at both ohmic contacts, Lambda at both ends (the Lambda=0
        # boundary the quantum potential is defined with).
        self._dg_dirichlet_rows_eq = np.array(
            [3 * 0, 3 * (N - 1),
             1, 2, 3 * (N - 1) + 1, 3 * (N - 1) + 2], dtype=int)
        return F, J

    def _dg_newton_solve_eq(self, psi, Lam_n, Lam_p, bc, gamma, max_iter, tol):
        """One coupled-Newton solve at FIXED gamma from a warm start.
        Mirrors MOSCapacitor._dg_newton_solve exactly -- see that
        method's docstring. Never raises on non-convergence/singular
        step; reports via the `converged` flag instead."""
        for _ in range(max_iter):
            F, J = self._dg_residual_jacobian_eq(psi, Lam_n, Lam_p, bc, gamma=gamma)
            Jd, rhs = eliminate_csr(J, -F, self._dg_dirichlet_rows_eq)
            try:
                d, _ = linsolve.solve_linear(Jd.tocsc(), rhs, method="direct")
            except linsolve.LinearSolveError:
                return psi, Lam_n, Lam_p, False
            if not np.all(np.isfinite(d)):
                return psi, Lam_n, Lam_p, False
            d_psi = np.clip(d[0::3], -5.0, 5.0)
            d_ln = np.clip(d[1::3], -10.0 * self.VT, 10.0 * self.VT)
            d_lp = np.clip(d[2::3], -10.0 * self.VT, 10.0 * self.VT)
            psi = psi + d_psi
            Lam_n = Lam_n + d_ln
            Lam_p = Lam_p + d_lp
            err = max(np.abs(d_psi).max(), np.abs(d_ln).max(), np.abs(d_lp).max())
            if err < tol:
                return psi, Lam_n, Lam_p, True
        return psi, Lam_n, Lam_p, False

    def _solve_equilibrium_dg_coupled(self, opts: NewtonOptions):
        """M20 coupled-Newton DG equilibrium solve: (psi, Lambda_n,
        Lambda_p) solved SIMULTANEOUSLY, replacing the lagged outer
        fixed-point scheme -- see MOSCapacitor._solve_psi_dg_coupled's
        docstring for the full architecture and the gamma-continuation
        rationale (a one-shot solve at full target gamma does not
        reliably converge; ramping gamma from 0 with warm-restarting
        does, the same pattern device.py's own M15/M16 stiff-
        generation solve_bias already uses).
        """
        C, nie = self.C, self.nie_s
        psi = np.arcsinh(C / (2.0 * nie))          # neutral-bulk guess
        bc = self._contact_values([0.0, 0.0])
        psi[0], psi[-1] = bc[0][0], bc[1][0]
        Lam_n = np.zeros(self.N)
        Lam_p = np.zeros(self.N)

        target_gamma = getattr(self.models, "dg_gamma", 1.0)
        stages = [0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0]
        k = 0
        retries_at_stage = 0
        converged_final = True
        while k < len(stages):
            gamma_k = target_gamma * stages[k]
            psi_new, Ln_new, Lp_new, ok = self._dg_newton_solve_eq(
                psi, Lam_n, Lam_p, bc, gamma_k, opts.max_iter, opts.tol_update)
            if ok:
                psi, Lam_n, Lam_p = psi_new, Ln_new, Lp_new
                k += 1
                retries_at_stage = 0
                continue
            retries_at_stage += 1
            if retries_at_stage > 20:
                converged_final = False
                break
            stages.insert(k, 0.5 * (stages[k - 1] if k > 0 else 0.0) + 0.5 * stages[k])
        if not converged_final:
            warnings.warn("M20 DG equilibrium coupled-Newton solve did not "
                          "converge (gamma continuation stalled).")

        self._ii_gs = None
        self._ii_gs_cache = None
        self._btbt_gs_cache = None
        self._btbt_nl_paths = None
        self._dg_Lam_n = Lam_n
        self._dg_Lam_p = Lam_p
        self.psi = psi
        self.n = nie * np.exp(np.clip(psi, -700, 700)) * np.exp(-Lam_n / self.VT)
        self.p = nie * np.exp(np.clip(-psi, -700, 700)) * np.exp(-Lam_p / self.VT)
        if self.models.energy_balance:
            self.Tn = np.full(self.N, self.T)   # zero current => theta==1 exactly
        return self

    # ------------------------------------------------------------------
    #  Coupled residual and Jacobian
    # ------------------------------------------------------------------
    def _update_tat_probabilities(self, psi=None):
        """M12-S2 FROZEN-FIELD WKB escape probabilities P_n/P_p.

        Trap-to-band tunneling through the field-lowered triangular
        barrier: P = exp(-B phi^1.5 / F) with
            B(m*) = 4 sqrt(2 m* q) / (3 hbar),
        phi = half-gap (midgap trap), F = local physical field taken
        from the CURRENT potential.  Probabilities are FROZEN for the
        duration of a Newton solve (computed once per solve_bias call);
        the analytic Jacobian therefore omits dP/dpsi -- the documented
        frozen-field approximation.  At realistic low fields the
        exponent underflows and P == 0.0 exactly, reducing TAT to
        plain SRH."""
        if psi is None:
            psi = self.psi
        if psi is None:
            psi = np.zeros(self.N)
        edge_F_cm = np.abs(np.diff(psi)) * self.VT / (self.LD * self.h)
        # B(m*) above is SI-calibrated -> convert V/cm to V/m
        edge_F = edge_F_cm * 100.0
        F = np.empty(self.N)
        F[1:-1] = 0.5 * (edge_F[:-1] + edge_F[1:])
        F[0], F[-1] = edge_F[0], edge_F[-1]
        et_rel = getattr(self.models, "trap_et_rel", 0.5)
        phi_n = self.Eg0_arr * (1.0 - et_rel)     # eV, electron side
        phi_p = self.Eg_arr if False else None    # placeholder replaced below
        # hole-side barrier uses Eg(T) -- build per-node Eg(T) here
        eg_t = np.array([m.Eg(self.T) for m in self.mats])
        phi_p = eg_t * et_rel
        m_n = np.array([m.m_n_star for m in self.mats])
        m_p = np.array([m.m_p_star for m in self.mats])
        B_n = 4.0 * np.sqrt(2.0 * m_n * Q_E_CONST) / (3.0 * HBAR_CONST)
        B_p = 4.0 * np.sqrt(2.0 * m_p * Q_E_CONST) / (3.0 * HBAR_CONST)
        safe_F = np.maximum(F, 1.0)
        self._Pn = np.exp(-B_n * phi_n ** 1.5 / safe_F)
        self._Pp = np.exp(-B_p * phi_p ** 1.5 / safe_F)

    def _ii_compute_E_from_state(self, psi):
        """Compute node-centered electric field magnitudes from psi.
        
        Returns E_node array [V/cm] for use in alpha(E) lookup.
        The field is the average of adjacent edge fields.
        """
        N = self.N
        c_edge = self.VT / (self.LD * self.h)
        e_mag = np.abs(np.diff(psi)) * c_edge
        E_node = np.empty(N); E_node[0], E_node[-1] = e_mag[0], e_mag[-1]
        E_node[1:-1] = 0.5 * (e_mag[:-1] + e_mag[1:])
        return E_node

    def _ii_compute_gs_frozen(self, psi, n, p, alpha_n, alpha_p):
        """Compute the generation-source VALUE gs(psi, n, p, alpha).

        gs = Kgen * (alpha_n * Sn + alpha_p * Sp)   [scaled units]
        where Sn/Sp are node-centered incident-edge |J| sums
        [physical A/cm^2] and Kgen = 0.5 / (q * R0).  alpha_n/alpha_p
        are passed in (evaluated by the caller from whatever E it wants
        -- this function is agnostic to whether that E is live or a
        snapshot).  Returns gs [scaled cm^-3 s^-1].

        R1b fix (2026-08-28): _residual_jacobian now calls this with a
        LIVE alpha(E) every Newton iterate and adds the matching
        analytic dG/dpsi, dG/dn, dG/dp terms itself -- this function
        only ever computes the value, never a frozen/cached one.  Name
        kept for continuity with the ionization-source formula; nothing
        about the computation itself is frozen.
        """
        N = self.N
        h = self.h
        dn_e = self.dn_edge
        dp_e = self.dp_edge
        # SG edge currents from the given state.  These MUST use the
        # same Scharfetter-Gummel deltas as _residual_jacobian: under
        # Fermi-Dirac statistics the residual carries the M13 nu-factor
        # edge differences, and reconstructing |Jn|/|Jp| without them
        # overstates the generation source by ~13 orders of magnitude
        # (impact+fd ran away at -12 V before this was matched).
        dlnnie = np.log(self.nie_s[1:] / self.nie_s[:-1])
        # M33-S1: the frozen-generation path recomputes the SG deltas
        # independently of _residual_jacobian, so it needs the same
        # band-alignment shift or an affinity-gauge run would drive
        # impact ionization off the WRONG edge currents. Identically
        # zero on the legacy path.
        _ds = self.band_shift[1:] - self.band_shift[:-1]
        delta = (psi[1:] - psi[:-1]) + dlnnie + _ds
        delta_p = (psi[1:] - psi[:-1]) - dlnnie + _ds
        if getattr(self.models, "fd", False):
            Ln, Lp, _wn, _wp = self._fd_factors(n, p)
            delta = delta + (Ln[1:] - Ln[:-1])
            delta_p = delta_p - (Lp[1:] - Lp[:-1])
        Bp = bernoulli(delta)
        Bm = bernoulli(-delta)
        Bp_h = bernoulli(delta_p)
        Bm_h = bernoulli(-delta_p)
        an = dn_e / h
        ap = dp_e / h
        Jn = an * (n[1:] * Bp - n[:-1] * Bm)
        Jp = -ap * (p[1:] * Bm_h - p[:-1] * Bp_h)
        # Node-centered incident-edge |J| sums [physical A/cm^2].
        # Smoothed (see _II_J_EPS_REL) so the generation source stays
        # differentiable across an edge's zero-current crossing --
        # matched exactly by the analytic Jacobian in _residual_jacobian.
        j_eps = _II_J_EPS_REL * max(float(np.abs(Jn).max()),
                                     float(np.abs(Jp).max()), 1e-300)
        aJn_ph = _ii_smooth_abs(Jn, j_eps) * self.J0
        aJp_ph = _ii_smooth_abs(Jp, j_eps) * self.J0
        Sn = np.empty(N); Sn[0], Sn[-1] = aJn_ph[0], aJn_ph[-1]
        Sn[1:-1] = aJn_ph[:-1] + aJn_ph[1:]
        Sp = np.empty(N); Sp[0], Sp[-1] = aJp_ph[0], aJp_ph[-1]
        Sp[1:-1] = aJp_ph[:-1] + aJp_ph[1:]
        Kgen = 0.5 / (_II_Q * self.R0)
        return Kgen * (alpha_n * Sn + alpha_p * Sp)

    def _btbt_nl_params(self):
        """M34-S1: (Eg [J], mr, mc, mv [kg]) of the (homojunction)
        material -- __init__ refuses a heterointerface."""
        mat = self.mats[0]
        mc = mat.m_n_star * _NL_M0
        mv = mat.m_p_star * _NL_M0
        return mat.Eg(self.T) * _NL_Q, 1.0 / (1.0 / mc + 1.0 / mv), mc, mv

    def _btbt_nl_build_paths(self, psi):
        """M34-S1: locate the nonlocal-BTBT tunnel paths at `psi`.

        Only this GEOMETRY is frozen for the Newton solve that follows
        (solve_bias re-locates it after convergence).  A path starts on
        every edge (i0, i0+1) with forward band bending whose field
        clears 1e3 V/cm -- below that eq (11)'s exp(-2 int kappa)
        underflows anyway -- and from which psi rises by Eg/VT further
        on (the band reaches the conduction band).  Its span runs past
        that delta = 1 node until delta >= 1.5 or the device end, so a
        psi that relaxes during Newton does not truncate it; edges past
        the live crossing contribute exactly zero.
        """
        N = self.N
        thr = self.mats[0].Eg(self.T) / self.VT
        c_edge = self.VT / (self.LD * self.h)        # V/cm per unit psi
        psi_max = float(psi.max())
        starts, ends = [], []
        # Interior nodes only, as for M15/M16: the Dirichlet stamping
        # overwrites the contact rows, so neither a start (holes) nor a
        # crossing (electrons) may sit on a contact node, and a path whose
        # delta = 1 crossing would reach one is not located.
        for i0 in range(1, N - 2):
            dpsi0 = psi[i0 + 1] - psi[i0]
            if dpsi0 <= 0.0 or dpsi0 * c_edge[i0] < 1.0e3:
                continue
            if psi_max - psi[i0] < thr:
                continue
            j = i0 + 1
            while j < N and psi[j] - psi[i0] < thr:
                j += 1
            if j > N - 2:
                continue
            k = j
            while k < N - 2 and psi[k] - psi[i0] < 1.5 * thr:
                k += 1
            starts.append(i0)
            ends.append(k)
        return _nl_build_1d(self.x * 1e-2, starts, ends)      # cm -> m

    def _btbt_nl_eval(self, psi):
        """M34-S1: evaluate the frozen paths at a live psi
        (pytcad/nonlocal_path.py)."""
        Eg_J, mr, mc, mv = self._btbt_nl_params()
        return _nl_evaluate(self._btbt_nl_paths, psi, self.VT, Eg_J,
                            mr, mc, mv)

    def _residual_jacobian(self, psi, n, p, bc, theta=None, n_lag=None,
                           Jn_lag=None, Qheat_lag=None):
        N, h, dV, C = self.N, self.h, self.dV, self.C
        dn_e, dp_e = self.dn_edge, self.dp_edge

        # M11-S3: band-offset-aware SG deltas.  ln(nie) edge factors make
        # the current vanish identically at equilibrium even across an
        # abrupt material change; derivatives wrt psi are unchanged
        # because nie is fixed under the Newton update.
        # M11-S3 band-offset-aware SG deltas.  Electrons and holes need
        # OPPOSITE nie-factor signs (calibrated against equilibrium
        # detailed balance on every edge):
        #   electron: delta_n = dpsi + dln(nie_s)
        #   hole:     delta_p = dpsi - dln(nie_s)
        dlnnie = np.log(self.nie_s[1:] / self.nie_s[:-1])
        # M33-S1: the affinity gauge adds ONE edge term, the SAME for
        # both carriers (see band_shift's construction in __init__ for
        # why the sign is shared here and opposite for dlnnie). It is
        # identically zero in the legacy gauge and for a homojunction,
        # so the off-path is bit-identical by construction. Like
        # dlnnie it is constant under the Newton update, so no Jacobian
        # column changes -- the same argument M11-S3 makes above.
        ds = self.band_shift[1:] - self.band_shift[:-1]
        delta = (psi[1:] - psi[:-1]) + dlnnie + ds     # electrons
        delta_p = (psi[1:] - psi[:-1]) - dlnnie + ds   # holes
        # --- M13: Fermi-Dirac nu-factor SG (plan section 3.2bis) ---
        # eta recovered from the density iterate; the SG argument gains
        # the degeneracy-factor edge difference with CARRIER-SPECIFIC
        # opposite signs:
        #   electron: delta_n = dpsi + dln(nie_s) + dL_n
        #   hole:     delta_p = dpsi - dln(nie_s) - dL_p
        # At phi = const this makes Delta ln(n) == delta_n identically,
        # so the equilibrium edge current vanishes to machine precision,
        # across degenerate steps AND heterointerfaces.  For eta <= -30
        # L and w are exactly 0.0, so deep-Boltzmann edges are
        # bit-identical to the Boltzmann scheme.  The psi-columns of
        # the Jacobian are UNCHANGED (delta_tilde depends on psi exactly
        # like delta); only the density columns gain w terms.
        fd = getattr(self.models, "fd", False)
        if fd:
            Ln, Lp, wn, wp = self._fd_factors(n, p)
            nu_n = np.exp(Ln)
            nu_p = np.exp(Lp)
            delta = delta + (Ln[1:] - Ln[:-1])
            delta_p = delta_p - (Lp[1:] - Lp[:-1])
        else:
            Ln = Lp = wn = wp = None
            nu_n = nu_p = None
        Bp, Bm = bernoulli(delta), bernoulli(-delta)
        dBp, dBm = dbernoulli(delta), dbernoulli(-delta)
        Bp_h, Bm_h = bernoulli(delta_p), bernoulli(-delta_p)
        dBp_h, dBm_h = dbernoulli(delta_p), dbernoulli(-delta_p)
        et = self._eps_tilde_edge()

        an = dn_e / h
        ap = dp_e / h
        if self.models.thermionic:
            # ---- M33-S2: thermionic-emission interface flux ----------
            # On a material-change edge the drift-diffusion flux is
            # REPLACED by an emission-limited one. It is written into
            # the SAME five slots the SG flux uses (a, B+, B-, dB+, dB-)
            # so every downstream Jacobian expression -- including the
            # M15 impact coupling -- works unchanged and no new branch
            # appears anywhere below this point.
            #
            # Form (electrons), derived from detailed balance rather
            # than quoted, because getting the Nc factor wrong is
            # invisible except at equilibrium:
            #     Jn = K [ n2 * g2 - n1 * g1 ]
            #     g1 = min(1, e^u),  g2 = (Nc1/Nc2) min(1, e^-u)
            #     u  = delta_n - dln(Nc)   ( = -dEc/kT )
            # g1/g2 = (Nc2/Nc1) e^u = e^delta_n identically, and
            # delta_n IS d(ln n) at equilibrium, so the flux vanishes
            # there for ANY Nc1, Nc2 -- which is why a single emission
            # velocity is used rather than one per side (a two-velocity
            # form is only detailed-balanced when A*1 == A*2).
            # min()/max() make this C0 but not C1 at u = 0; the kink is
            # mild (the derivative drops to zero on one side) and the
            # existing Newton backtracking handles it.
            te = self._te_edge
            u = delta - self._te_dlnNc
            g1 = np.minimum(1.0, np.exp(np.clip(u, -700, 700)))
            g2 = self._te_rNc * np.minimum(
                1.0, np.exp(np.clip(-u, -700, 700)))
            # dJn/d(delta) must enter as an*(n2*dBp + n1*dBm), so
            # dBp = dg2/ddelta and dBm = -dg1/ddelta. Both are <= 0,
            # matching the sign of the Bernoulli derivatives they
            # replace (B' < 0 everywhere).
            dg2 = np.where(u > 0.0, -g2, 0.0)
            dg1 = np.where(u < 0.0, -g1, 0.0)
            w = -delta_p - self._te_dlnNv
            h1 = np.minimum(1.0, np.exp(np.clip(w, -700, 700)))
            h2 = self._te_rNv * np.minimum(
                1.0, np.exp(np.clip(-w, -700, 700)))
            dh2 = np.where(w > 0.0, -h2, 0.0)
            dh1 = np.where(w < 0.0, -h1, 0.0)

            an = np.where(te, self._te_Kn, an)
            ap = np.where(te, self._te_Kp, ap)
            Bp = np.where(te, g2, Bp)
            Bm = np.where(te, g1, Bm)
            dBp = np.where(te, dg2, dBp)
            dBm = np.where(te, dg1, dBm)
            Bm_h = np.where(te, h2, Bm_h)
            Bp_h = np.where(te, h1, Bp_h)
            dBm_h = np.where(te, dh2, dBm_h)
            dBp_h = np.where(te, dh1, dBp_h)
        Jn = an * (n[1:] * Bp - n[:-1] * Bm)
        Jp = -ap * (p[1:] * Bm_h - p[:-1] * Bp_h)

        # recombination (unscaled physical densities)
        n_phys, p_phys = n * self.Ns, p * self.Ns
        # M13: FD equilibrium product np_eq = nie^2 nu_n nu_p (exact at
        # equilibrium because eta_n + eta_p = -Eg/kT identically there;
        # -> nie^2 as nu -> 1).  Chain-rule derivatives wrt the SCALED
        # slot densities converted to physical units.
        npq_args = {}
        if fd:
            npq = self.nie ** 2 * nu_n * nu_p          # physical [cm^-3]
            # chain-rule derivatives wrt the SCALED slot densities,
            # converted to physical-per-physical for recombination():
            # d(npq)/d n_phys = (dnpq/dn_scaled)/Ns
            dnpq_dns = self.nie ** 2 * nu_p * nu_n * wn    # per scaled n
            dnpq_dps = self.nie ** 2 * nu_n * nu_p * wp    # per scaled p
            npq_args = dict(np_eq=npq,
                            dnpq_dn=dnpq_dns / self.Ns,
                            dnpq_dp=dnpq_dps / self.Ns)
        R = np.empty_like(n_phys); dRdn = np.empty_like(n_phys)
        dRdp = np.empty_like(n_phys)
        for m in {id(mm): mm for mm in self.mats}.values():
            nodes = np.array([mm is m for mm in self.mats])
            args = {k: v[nodes] for k, v in npq_args.items()}
            R[nodes], dRdn[nodes], dRdp[nodes] = recombination(
                n_phys[nodes], p_phys[nodes], self.nie[nodes],
                self.tau_n[nodes], self.tau_p[nodes], m,
                auger=self.models.auger, **args)
        if not self.models.srh:
            R = np.zeros_like(R); dRdn = np.zeros_like(R); dRdp = np.zeros_like(R)

        # --- M12-S2 trap-assisted tunneling (plan section 5) -----------
        # R_TAT = (n p - nie^2) / [taup(n + nie Pp) + taun(p + nie Pn)]
        # with FROZEN-FIELD WKB probabilities Pn/Pp.  Reduces exactly
        # to SRH wherever P == 0 (all low-field points underflow).
        if getattr(self.models, "tat", False):
            if self._Pn is None or self._Pp is None:
                self._update_tat_probabilities(psi)
        else:
            self._Pn = self._Pp = None
        # tunneling-assisted capture ON TOP OF the thermal n1/p1
        # baselines: P == 0 everywhere reduces EXACTLY to SRH -- the
        # all-zero case must leave the SRH arrays UNTOUCHED so that
        # traps-off is deterministically bit-identical
        if getattr(self.models, "tat", False) and (
                bool(self._Pn.any()) or bool(self._Pp.any())):
            # M13+TAT: same FD driving-force correction as SRH/Auger
            # (np_eq = nie^2 nu_n nu_p); composition with frozen-field
            # TAT stays declared-untested until M15/M16 (plan section 8)
            nie2 = npq_args["np_eq"] if fd else self.nie * self.nie
            dqdn = dnpq_dns / self.Ns if fd else 0.0
            dqdp = dnpq_dps / self.Ns if fd else 0.0
            den = (self.tau_p * (n_phys + self.nie * (1.0 + self._Pp))
                   + self.tau_n * (p_phys + self.nie * (1.0 + self._Pn)))
            excess = n_phys * p_phys - nie2
            R = excess / den
            dRdn = ((p_phys - dqdn) * den - excess * self.tau_p) \
                / (den * den)
            dRdp = ((n_phys - dqdp) * den - excess * self.tau_n) \
                / (den * den)
        Rs = R / self.R0
        dRs_dn = dRdn * self.Ns / self.R0      # d(R/R0)/d(n/Ns)
        dRs_dp = dRdp * self.Ns / self.R0

        # --- M15: local impact ionization (van Overstraeten-de Man).
        # R1b fix (2026-08-28): the generation source is computed LIVE
        # from the current (psi, n, p) every Newton iterate -- no
        # frozen/cached source, no outer fixed-point loop.  The model
        # flag is authoritative: impact=False never reads or writes
        # self._ii_gs_cache, so a cache left over from an earlier
        # impact=True solve cannot leak into an impact=False residual.
        ii_enabled = getattr(self.models, "impact", False)
        self._ii_gs_cache = None   # overwritten below once computed if enabled
        # M16: same stale-source protection for BTBT -- the flag is
        # authoritative, a leftover cache never enters the residual.
        btbt_enabled = getattr(self.models, "btbt", False)
        self._btbt_gs_cache = None

        F = np.zeros(3 * N)
        rows, cols, vals = [], [], []

        def add(r, c, v):
            r = np.atleast_1d(np.asarray(r))
            c = np.atleast_1d(np.asarray(c))
            v = np.broadcast_to(np.asarray(v, dtype=float), r.shape)
            rows.append(r); cols.append(c); vals.append(np.array(v))

        i = np.arange(1, N - 1)

        # --- Poisson ---
        # M13 incomplete ionization: rho = n - p - C_ion(n, p)
        # (works under Boltzmann statistics too -- flag independence)
        if getattr(self.models, "incomplete_ion", False):
            cion, dcden, dcdp = self._ionized_C(n, p)
            F[3 * i] = (et[1:] * (psi[2:] - psi[1:-1]) / h[1:]
                        - et[:-1] * (psi[1:-1] - psi[:-2]) / h[:-1]
                        - dV[1:-1] * (n[1:-1] - p[1:-1] - cion[1:-1]))
        else:
            cion = dcden = dcdp = None
            F[3 * i] = (et[1:] * (psi[2:] - psi[1:-1]) / h[1:]
                        - et[:-1] * (psi[1:-1] - psi[:-2]) / h[:-1]
                        - dV[1:-1] * (n[1:-1] - p[1:-1] - C[1:-1]))
        add(3 * i, 3 * i, -et[1:] / h[1:] - et[:-1] / h[:-1])
        add(3 * i, 3 * (i + 1), et[1:] / h[1:])
        add(3 * i, 3 * (i - 1), et[:-1] / h[:-1])
        if cion is not None:
            add(3 * i, 3 * i + 1, -dV[1:-1] * (1.0 - dcden[1:-1]))
            add(3 * i, 3 * i + 2, dV[1:-1] * (1.0 + dcdp[1:-1]))
        else:
            add(3 * i, 3 * i + 1, -dV[1:-1])
            add(3 * i, 3 * i + 2, dV[1:-1])

        # --- electron continuity:  Jn_{i+1/2} - Jn_{i-1/2} - R dV = 0 ---
        F[3 * i + 1] = Jn[1:] - Jn[:-1] - Rs[1:-1] * dV[1:-1]
        add(3 * i + 1, 3 * i + 1, -an[1:] * Bm[1:] - an[:-1] * Bp[:-1]
            - dRs_dn[1:-1] * dV[1:-1])
        add(3 * i + 1, 3 * (i + 1) + 1, an[1:] * Bp[1:])
        add(3 * i + 1, 3 * (i - 1) + 1, an[:-1] * Bm[:-1])
        add(3 * i + 1, 3 * i + 2, -dRs_dp[1:-1] * dV[1:-1])
        dJn_dpsiR = an * (n[1:] * dBp + n[:-1] * dBm)      # d Jn_{k+1/2}/d psi_{k+1}
        add(3 * i + 1, 3 * i, -dJn_dpsiR[1:] - dJn_dpsiR[:-1])
        add(3 * i + 1, 3 * (i + 1), dJn_dpsiR[1:])
        add(3 * i + 1, 3 * (i - 1), dJn_dpsiR[:-1])
        if fd:
            # M13: density columns gain the d(delta_tilde)/dn chain.
            # Per edge (verified against finite differences):
            #   d(Jn_edge)/d(n_{k+1}) = an(Bp + Sn w_{k+1})
            #   d(Jn_edge)/d(n_k)     = an(-Bm - Sn w_k)
            # (delta_n carries +L_k - L_{k+1}, so d(delta)/d(n_k)=-w);
            # row flips give central -w(an S)_both, outer +an S w.
            Sn = n[1:] * dBp + n[:-1] * dBm
            add(3 * i + 1, 3 * i + 1,
                -wn[1:-1] * (an[1:] * Sn[1:] + an[:-1] * Sn[:-1]))
            add(3 * i + 1, 3 * (i + 1) + 1, an[1:] * Sn[1:] * wn[2:])
            add(3 * i + 1, 3 * (i - 1) + 1,
                an[:-1] * Sn[:-1] * wn[:-2])

        # --- hole continuity:  Jp_{i+1/2} - Jp_{i-1/2} + R dV = 0 ---
        F[3 * i + 2] = Jp[1:] - Jp[:-1] + Rs[1:-1] * dV[1:-1]

        add(3 * i + 2, 3 * i + 2, ap[1:] * Bp_h[1:] + ap[:-1] * Bm_h[:-1]
            + dRs_dp[1:-1] * dV[1:-1])
        add(3 * i + 2, 3 * (i + 1) + 2, -ap[1:] * Bm_h[1:])
        add(3 * i + 2, 3 * (i - 1) + 2, -ap[:-1] * Bp_h[:-1])
        add(3 * i + 2, 3 * i + 1, dRs_dn[1:-1] * dV[1:-1])
        # d(delta_p)/d(psi_{k+1}) = +1 like the electron side, because the
        # minus from the hole Boltzmann exponent cancels the minus in the
        # delta definition -- verified by the FD-Jacobian test
        dJp_dpsiR = ap * (p[1:] * dBm_h + p[:-1] * dBp_h)
        add(3 * i + 2, 3 * i, -dJp_dpsiR[1:] - dJp_dpsiR[:-1])
        add(3 * i + 2, 3 * (i + 1), dJp_dpsiR[1:])
        add(3 * i + 2, 3 * (i - 1), dJp_dpsiR[:-1])
        if fd:
            # M13 hole mirror: delta_tilde_p carries -dL_p, so every
            # w-term enters with the OPPOSITE sign to the electron
            # block (carrier-specific -- the property the M11 lesson
            # and the G5 hetero gate protect).
            Sp = p[1:] * dBm_h + p[:-1] * dBp_h
            # Verified per-edge: d(Jp_edge)/d(p_{k+1}) =
            # -ap(Bm_h + Sp w_{k+1}), d(Jp_edge)/d(p_k) =
            # +ap(Bp_h + Sp w_k); row flips give
            # central w(ap_r Sp_r + ap_l Sp_l), right -ap Sp w,
            # left -ap Sp w.
            add(3 * i + 2, 3 * i + 2,
                wp[1:-1] * (ap[1:] * Sp[1:] + ap[:-1] * Sp[:-1]))
            add(3 * i + 2, 3 * (i + 1) + 2,
                -ap[1:] * Sp[1:] * wp[2:])
            add(3 * i + 2, 3 * (i - 1) + 2,
                -ap[:-1] * Sp[:-1] * wp[:-2])

        # --- M15 impact-ionization generation (R1b: fully coupled) -----
        # MUST come after BOTH continuity rows above: those assign with
        # `=`, so a generation term added before them is silently
        # discarded (the defect that made II inert at every bias).
        # Interior nodes only -- the Dirichlet stamping below overwrites
        # rows 0 and N-1, so boundary generation cannot be represented.
        #
        # G_i = Kgen*(alpha_n(E_i)*Sn_i + alpha_p(E_i)*Sp_i), with
        # E_i the node field (avg of adjacent edge fields), Sn_i/Sp_i
        # the node-centered incident-edge |Jn|/|Jp| sums.  Full chain
        # rule: dG/dpsi through d(alpha)/dE (E0 kink documented in the
        # test) AND through d|J|/dpsi (sign(J) times the SAME dJ/dpsi
        # partials already built above for the continuity Jacobian);
        # dG/dn through d|Jn|/dn only (Sn depends on n, not p); dG/dp
        # through d|Jp|/dp only.  No frozen-field approximation.
        if ii_enabled:
            # M34-S2: with impact_nonlocal the coefficients see a per-
            # carrier EFFECTIVE field (pytcad/ii_nonlocal.py) instead of
            # the local node field.  Its psi-dependence is dense (every
            # upstream edge) and is stamped separately below.
            ii_nl = getattr(self.models, "impact_nonlocal", False)
            if ii_nl:
                En_ii, Dn_ii = _ii_eff_field(
                    self.x, psi, self.VT, self.models.impact_lambda_n, "n",
                    jacobian=True)
                Ep_ii, Dp_ii = _ii_eff_field(
                    self.x, psi, self.VT, self.models.impact_lambda_p, "p",
                    jacobian=True)
            else:
                E_node = self._ii_compute_E_from_state(psi)
                En_ii = Ep_ii = E_node
            alpha_n_E = _ii_alpha_n(En_ii)
            alpha_p_E = _ii_alpha_p(Ep_ii)
            gs_full = self._ii_compute_gs_frozen(
                psi, n, p, alpha_n_E, alpha_p_E)
            strength = getattr(self, "_ii_strength", 1.0)
            self._ii_gs_cache = (gs_full * strength).copy()

            F[3 * i + 1] += strength * gs_full[1:-1] * dV[1:-1]
            F[3 * i + 2] -= strength * gs_full[1:-1] * dV[1:-1]

            dalpha_n_E = _ii_dalpha_dE(En_ii, "n")
            dalpha_p_E = _ii_dalpha_dE(Ep_ii, "p")
            alpha_n_i = alpha_n_E[1:-1]; alpha_p_i = alpha_p_E[1:-1]
            dalpha_n_i = dalpha_n_E[1:-1]; dalpha_p_i = dalpha_p_E[1:-1]

            # Node field E_i = 0.5*(e_mag[i-1] + e_mag[i]); e_mag_k =
            # |psi_{k+1}-psi_k| * c_edge_k.
            c_edge = self.VT / (self.LD * h)
            dpsi_edge = psi[1:] - psi[:-1]
            s_edge = np.sign(dpsi_edge)
            dEedge_dleft = -s_edge * c_edge     # d(e_mag_k)/d psi_k
            dEedge_dright = s_edge * c_edge     # d(e_mag_k)/d psi_{k+1}
            dEi_dpsi_L = 0.5 * dEedge_dleft[:-1]
            dEi_dpsi_M = 0.5 * (dEedge_dright[:-1] + dEedge_dleft[1:])
            dEi_dpsi_R = 0.5 * dEedge_dright[1:]
            if ii_nl:
                # the alpha(E_eff) chain is dense; stamped after the
                # tridiagonal block below, so zero it here
                dEi_dpsi_L = dEi_dpsi_M = dEi_dpsi_R = np.zeros(N - 2)

            # Smoothed |J|/sign(J) -- see _II_J_EPS_REL.  j_eps must be
            # computed identically to _ii_compute_gs_frozen's (same
            # formula, same Jn/Jp) so gs_full's value and this block's
            # derivative are evaluating literally the same function.
            j_eps = _II_J_EPS_REL * max(float(np.abs(Jn).max()),
                                         float(np.abs(Jp).max()), 1e-300)
            aJn_ph = _ii_smooth_abs(Jn, j_eps) * self.J0
            aJp_ph = _ii_smooth_abs(Jp, j_eps) * self.J0
            Sn_i = aJn_ph[:-1] + aJn_ph[1:]
            Sp_i = aJp_ph[:-1] + aJp_ph[1:]
            sgn_Jn = _ii_smooth_sign(Jn, j_eps)
            sgn_Jp = _ii_smooth_sign(Jp, j_eps)

            # Per-edge d(Jn_edge)/d* -- same quantities already built
            # above for the electron-continuity Jacobian.
            dJn_dpsi_L = -dJn_dpsiR
            dJn_dpsi_R = dJn_dpsiR
            dJn_dn_L = -an * Bm
            dJn_dn_R = an * Bp
            if fd:
                dJn_dn_L = dJn_dn_L - an * Sn[:len(an)] * wn[:-1]
                dJn_dn_R = dJn_dn_R + an * Sn[:len(an)] * wn[1:]

            dJp_dpsi_L = -dJp_dpsiR
            dJp_dpsi_R = dJp_dpsiR
            dJp_dp_L = ap * Bp_h
            dJp_dp_R = -ap * Bm_h
            if fd:
                dJp_dp_L = dJp_dp_L + ap * Sp[:len(ap)] * wp[:-1]
                dJp_dp_R = dJp_dp_R - ap * Sp[:len(ap)] * wp[1:]

            dSn_dpsi_L = sgn_Jn[:-1] * dJn_dpsi_L[:-1] * self.J0
            dSn_dpsi_M = (sgn_Jn[:-1] * dJn_dpsi_R[:-1]
                          + sgn_Jn[1:] * dJn_dpsi_L[1:]) * self.J0
            dSn_dpsi_R = sgn_Jn[1:] * dJn_dpsi_R[1:] * self.J0
            dSn_dn_L = sgn_Jn[:-1] * dJn_dn_L[:-1] * self.J0
            dSn_dn_M = (sgn_Jn[:-1] * dJn_dn_R[:-1]
                        + sgn_Jn[1:] * dJn_dn_L[1:]) * self.J0
            dSn_dn_R = sgn_Jn[1:] * dJn_dn_R[1:] * self.J0

            dSp_dpsi_L = sgn_Jp[:-1] * dJp_dpsi_L[:-1] * self.J0
            dSp_dpsi_M = (sgn_Jp[:-1] * dJp_dpsi_R[:-1]
                          + sgn_Jp[1:] * dJp_dpsi_L[1:]) * self.J0
            dSp_dpsi_R = sgn_Jp[1:] * dJp_dpsi_R[1:] * self.J0
            dSp_dp_L = sgn_Jp[:-1] * dJp_dp_L[:-1] * self.J0
            dSp_dp_M = (sgn_Jp[:-1] * dJp_dp_R[:-1]
                        + sgn_Jp[1:] * dJp_dp_L[1:]) * self.J0
            dSp_dp_R = sgn_Jp[1:] * dJp_dp_R[1:] * self.J0

            Kgen = 0.5 / (_II_Q * self.R0)

            def _dG_dpsi(dEi, dSn, dSp):
                return Kgen * (dalpha_n_i * dEi * Sn_i + alpha_n_i * dSn
                               + dalpha_p_i * dEi * Sp_i + alpha_p_i * dSp)

            dG_dpsi_L = strength * _dG_dpsi(dEi_dpsi_L, dSn_dpsi_L, dSp_dpsi_L)
            dG_dpsi_M = strength * _dG_dpsi(dEi_dpsi_M, dSn_dpsi_M, dSp_dpsi_M)
            dG_dpsi_R = strength * _dG_dpsi(dEi_dpsi_R, dSn_dpsi_R, dSp_dpsi_R)
            dG_dn_L = strength * Kgen * alpha_n_i * dSn_dn_L
            dG_dn_M = strength * Kgen * alpha_n_i * dSn_dn_M
            dG_dn_R = strength * Kgen * alpha_n_i * dSn_dn_R
            dG_dp_L = strength * Kgen * alpha_p_i * dSp_dp_L
            dG_dp_M = strength * Kgen * alpha_p_i * dSp_dp_M
            dG_dp_R = strength * Kgen * alpha_p_i * dSp_dp_R

            dVi = dV[1:-1]
            add(3 * i + 1, 3 * (i - 1), dVi * dG_dpsi_L)
            add(3 * i + 1, 3 * i, dVi * dG_dpsi_M)
            add(3 * i + 1, 3 * (i + 1), dVi * dG_dpsi_R)
            add(3 * i + 1, 3 * (i - 1) + 1, dVi * dG_dn_L)
            add(3 * i + 1, 3 * i + 1, dVi * dG_dn_M)
            add(3 * i + 1, 3 * (i + 1) + 1, dVi * dG_dn_R)
            add(3 * i + 1, 3 * (i - 1) + 2, dVi * dG_dp_L)
            add(3 * i + 1, 3 * i + 2, dVi * dG_dp_M)
            add(3 * i + 1, 3 * (i + 1) + 2, dVi * dG_dp_R)

            add(3 * i + 2, 3 * (i - 1), -dVi * dG_dpsi_L)
            add(3 * i + 2, 3 * i, -dVi * dG_dpsi_M)
            add(3 * i + 2, 3 * (i + 1), -dVi * dG_dpsi_R)
            add(3 * i + 2, 3 * (i - 1) + 1, -dVi * dG_dn_L)
            add(3 * i + 2, 3 * i + 1, -dVi * dG_dn_M)
            add(3 * i + 2, 3 * (i + 1) + 1, -dVi * dG_dn_R)
            add(3 * i + 2, 3 * (i - 1) + 2, -dVi * dG_dp_L)
            add(3 * i + 2, 3 * i + 2, -dVi * dG_dp_M)
            add(3 * i + 2, 3 * (i + 1) + 2, -dVi * dG_dp_R)
            if ii_nl:
                # M34-S2: dG_i/dpsi_k through alpha(E_eff) for every k
                # upstream of node i: Kgen*(alpha_n'(E_n,i) Sn_i
                # dE_n,i/dpsi_k + alpha_p'(E_p,i) Sp_i dE_p,i/dpsi_k)
                cn = strength * Kgen * dVi * dalpha_n_i * Sn_i
                cp = strength * Kgen * dVi * dalpha_p_i * Sp_i
                dense = cn[:, None] * Dn_ii[1:-1] + cp[:, None] * Dp_ii[1:-1]
                # Most of this block is numerically nothing: alpha'
                # underflows away from high field and the upstream
                # weights decay as exp(-d/lambda).  Entries below 1e-15
                # of the block's largest are dropped -- far under the
                # 5e-5 FD-Jacobian gate, and they otherwise put ~N^2
                # entries into every Jacobian.
                amax = float(np.abs(dense).max()) if dense.size else 0.0
                r_nz, c_nz = np.nonzero(np.abs(dense) > 1e-15 * amax)
                d_nz = dense[r_nz, c_nz]
                rows.append(3 * (r_nz + 1) + 1)
                cols.append(3 * c_nz)
                vals.append(d_nz)
                rows.append(3 * (r_nz + 1) + 2)
                cols.append(3 * c_nz)
                vals.append(-d_nz)

        # --- M16 band-to-band tunneling (local Kane, live-coupled) -----
        # SAME ordering invariant as the M15 II block above: after BOTH
        # continuity row assignments (they assign with `=`, so anything
        # added earlier is silently discarded) and BEFORE the Dirichlet
        # stamping (which overwrites rows 0 and N-1, so boundary
        # generation cannot be represented -- interior nodes only).
        #
        # G_i = A * E_i^2 * exp(-B / E_i)   [cm^-3 s^-1, physical]
        # with E_i the SAME node field the II block uses
        # (_ii_compute_E_from_state -- avg of adjacent edge-field
        # magnitudes), computed LIVE from psi every Newton iterate.
        # Full chain rule through dE_i/dpsi_j only: G depends on the
        # state through E(psi) alone (no carrier-density dependence,
        # unlike II -- BTBT is a field-driven source).  G is C-infinity
        # in E (no piecewise switch), so the FD-Jacobian probe has no
        # kink windows to avoid.
        if btbt_enabled:
            E_node = self._ii_compute_E_from_state(psi)
            G_btbt = _btbt_G(E_node)                # physical cm^-3 s^-1
            strength = getattr(self, "_ii_strength", 1.0)
            self._btbt_gs_cache = (G_btbt * strength).copy()

            # Scaled source: G/R0 enters the residual in scaled units.
            dGs_dpsi = _btbt_dG(E_node) / self.R0 * strength

            # Node field E_i = 0.5*(e_mag[i-1] + e_mag[i]); e_mag_k =
            # |psi_{k+1}-psi_k| * c_edge_k -- identical chain to the II
            # block (verified there against the FD Jacobian).
            c_edge = self.VT / (self.LD * h)
            dpsi_edge = psi[1:] - psi[:-1]
            s_edge = np.sign(dpsi_edge)
            dEedge_dleft = -s_edge * c_edge     # d(e_mag_k)/d psi_k
            dEedge_dright = s_edge * c_edge     # d(e_mag_k)/d psi_{k+1}
            dEi_dpsi_L = 0.5 * dEedge_dleft[:-1]
            dEi_dpsi_M = 0.5 * (dEedge_dright[:-1] + dEedge_dleft[1:])
            dEi_dpsi_R = 0.5 * dEedge_dright[1:]

            dGi_L = dGs_dpsi[1:-1] * dEi_dpsi_L
            dGi_M = dGs_dpsi[1:-1] * dEi_dpsi_M
            dGi_R = dGs_dpsi[1:-1] * dEi_dpsi_R

            F[3 * i + 1] += strength * G_btbt[1:-1] / self.R0 * dV[1:-1]
            F[3 * i + 2] -= strength * G_btbt[1:-1] / self.R0 * dV[1:-1]

            dVi = dV[1:-1]
            add(3 * i + 1, 3 * (i - 1), dVi * dGi_L)
            add(3 * i + 1, 3 * i, dVi * dGi_M)
            add(3 * i + 1, 3 * (i + 1), dVi * dGi_R)
            add(3 * i + 2, 3 * (i - 1), -dVi * dGi_L)
            add(3 * i + 2, 3 * i, -dVi * dGi_M)
            add(3 * i + 2, 3 * (i + 1), -dVi * dGi_R)

        # --- M34-S1: nonlocal path BTBT (Esseni 2017 eq 11) -----------
        # SAME ordering invariant as the M15/M16 blocks above: after
        # both continuity `=` assignments, before Dirichlet stamping.
        # Only the path GEOMETRY is frozen per solve_bias call; psi along
        # every path, the eq (11) prefactor, eq (12)'s band extrema and
        # the electron deposit point are live (pytcad/nonlocal_path.py,
        # M34-PLAN.md section 2).
        if getattr(self.models, "btbt_nonlocal", False):
            if self._btbt_nl_paths is None:
                self._btbt_nl_paths = self._btbt_nl_build_paths(psi)
            strength = getattr(self, "_ii_strength", 1.0)
            # strength 0 (the ladder's plain-DD stage) contributes exactly
            # nothing; skipping it also keeps an unphysical warm-start
            # path from turning 0 * inf into a NaN residual.
            if self._btbt_nl_paths.n_paths and strength > 0.0:
                ev = self._btbt_nl_eval(psi)
                st = self._btbt_nl_paths.start
                # One tunneling event makes one pair: the electron count
                # spread around the delta = 1 crossing equals the hole
                # count at the start node (Esseni 2017 eq (1), fig. 2).
                fac = strength * 1e-6 / self.R0 * dV[st]   # SI -> scaled box count
                cnt = fac * ev.G
                np.add.at(F, 3 * st + 2, -cnt)
                dep = ev.dep.tocoo()
                np.add.at(F, 3 * dep.col + 1, cnt[dep.row] * dep.data)
                dG = ev.dG.tocoo()
                rows.append(3 * st[dG.row] + 2)
                cols.append(3 * dG.col)
                vals.append(-fac[dG.row] * dG.data)
                # electron rows: w_pn * dG_p/dpsi (a sparse product) ...
                Wm = csr_matrix((fac[dep.row] * dep.data,
                                 (3 * dep.col + 1, dep.row)),
                                shape=(3 * N, st.size))
                dG3 = csr_matrix((dG.data, (dG.row, 3 * dG.col)),
                                 shape=(st.size, 3 * N))
                Je = (Wm @ dG3).tocoo()
                rows.append(Je.row)
                cols.append(Je.col)
                vals.append(Je.data)
                # ... plus G_p * d w_pn/dpsi (the crossing moves)
                rows.append(3 * ev.ddep_node + 1)
                cols.append(3 * ev.ddep_col)
                vals.append(cnt[ev.ddep_p] * ev.ddep_val)

        # --- Dirichlet contacts (Robin on n/p when M14 S_n/S_p != 0) ---
        # psi stays fully Dirichlet -- S_n/S_p model carrier recombination
        # at the contact, not band bending. S=0 (default) keeps the
        # EXACT pre-M14 Dirichlet row (n[node]=n0, diagonal 1.0) --
        # bit-identical, not an algebraic reduction of the Robin formula:
        # a Robin flux-balance row (see below) genuinely means something
        # different at S=0 (zero-current/reflecting) than a Dirichlet
        # density clamp, so this MUST branch, not interpolate. S>0
        # replaces the row with the physical boundary condition
        # Jn.n_hat = q*Sn*(n-n0): the edge-0 (node-N-2) SG current
        # already computed for the interior stencil, balanced against
        # the recombination sink, reusing the exact per-edge Jacobian
        # coefficients (an/Bm/Bp/dJn_dpsiR, ap/Bm_h/Bp_h/dJp_dpsiR)
        # already derived above -- no new physics formula invented here,
        # only the existing edge-current model applied at a boundary
        # instead of between two interior nodes.
        # Boundary condition, derived from steady-state particle
        # conservation in the boundary half-box (not assumed from an
        # external sign convention): electron/hole flux entering the
        # half-box from its one interior edge equals the surface
        # recombination sink Sn*(n-n0)/Sp*(p-p0) there. Because
        # electrons carry charge -q, converting the SG conventional
        # current Jn to a particle flux flips a sign that Jp (holes,
        # charge +q) does not -- hence the electron and hole sink terms
        # end up with OPPOSITE sign between the left and right contact
        # (mirroring how this code's own interior continuity rows
        # already use +Rs for holes and -Rs for electrons). Verified
        # against equilibrium (Jn=Jp=0 forces n=n0/p=p0 regardless of S,
        # as it must) and the FD-Jacobian gate
        # (test_m14_surface_mobility.py).
        S_n_s = self.models.S_n * self.LD / D0_REF
        S_p_s = self.models.S_p * self.LD / D0_REF
        # M46-S2: a SchottkyContact with A_star given reuses this SAME
        # Robin machinery for its majority carrier -- thermionic
        # emission (Sze & Ng) restated as a surface recombination
        # velocity v_R = A* T^2 / (q Nc_or_Nv) toward the barrier-
        # limited n0/p0 `bc` already carries (S1's _contact_values),
        # is EXACTLY the same equation shape M14's S_n/S_p already
        # solve for -- no new physics formula, no new Jacobian
        # derivation, only a different velocity/target density
        # sourced per node. Both mechanisms competing for the same row
        # is refused rather than silently combined (S_n/S_p are GLOBAL
        # to both contacts in this module's own existing design, so
        # there is no way to keep them scoped to only the ohmic side
        # without changing that design, which is out of M46's scope).
        schottky_sides = (self.schottky_left, self.schottky_right)
        _sch_robin = [s is not None and s.A_star is not None
                      for s in schottky_sides]
        if any(_sch_robin) and (S_n_s != 0.0 or S_p_s != 0.0):
            raise NotImplementedError(
                "Models(S_n!=0 or S_p!=0) combined with a Robin-mode "
                "SchottkyContact (A_star given) is refused: both "
                "mechanisms would compete for the same boundary row "
                "(M46-S2 scope; unvalidated composition).")
        # Which rows are GENUINELY Dirichlet -- recorded here rather
        # than re-derived at the solve site, so the S_n/S_p branch below
        # cannot drift out of step with it. A Robin row (S != 0) has
        # real off-diagonal entries and must NOT be eliminated: it is
        # not a constraint, it is an equation.
        dirichlet_rows = []
        for k, node in enumerate((0, N - 1)):
            psi0, n0, p0 = bc[k]
            F[3 * node] = psi[node] - psi0
            add(3 * node, 3 * node, 1.0)
            dirichlet_rows.append(3 * node)
            edge = 0 if node == 0 else N - 2   # the one edge touching this node
            other = node + 1 if node == 0 else node - 1
            left = node == 0                   # is `node` the LEFT end of `edge`?
            bsign_n = -1.0 if left else 1.0
            bsign_p = 1.0 if left else -1.0
            S_n_s_local, S_p_s_local = S_n_s, S_p_s
            if _sch_robin[k]:
                sch = schottky_sides[k]
                Nc_or_Nv = (self.mats[node].Nc(self.T) if C[node] >= 0.0
                           else self.mats[node].Nv(self.T))
                v_R_s = (sch.A_star * self.T * self.T / (Q * Nc_or_Nv)) \
                    * self.LD / D0_REF
                if C[node] >= 0.0:
                    S_n_s_local = v_R_s
                else:
                    S_p_s_local = v_R_s
            S_n_s, S_p_s = S_n_s_local, S_p_s_local
            if S_n_s == 0.0:
                F[3 * node + 1] = n[node] - n0
                add(3 * node + 1, 3 * node + 1, 1.0)
                dirichlet_rows.append(3 * node + 1)
            else:
                F[3 * node + 1] = Jn[edge] + bsign_n * S_n_s * (n[node] - n0)
                dpsi_node = -dJn_dpsiR[edge] if left else dJn_dpsiR[edge]
                dpsi_other = dJn_dpsiR[edge] if left else -dJn_dpsiR[edge]
                dn_node = -an[edge] * Bm[edge] if left else an[edge] * Bp[edge]
                dn_other = an[edge] * Bp[edge] if left else -an[edge] * Bm[edge]
                if fd:
                    # M13 FD correction to the SG delta term (the same
                    # chain-rule extension the interior electron rows
                    # get, see the `if fd:` block above building `Sn`/
                    # `wn`) -- hard-debug finding (2026-08-28): omitting
                    # this here made the boundary Jacobian ~0.1% wrong
                    # whenever fd=True and S_n!=0 were combined (caught
                    # by an FD-Jacobian probe restricted to the boundary
                    # columns specifically, not the whole-matrix check
                    # the other M14 tests already ran with fd=False).
                    Sn_edge = n[edge + 1] * dBp[edge] + n[edge] * dBm[edge]
                    dn_node += (-an[edge] * Sn_edge * wn[node]) if left \
                        else (an[edge] * Sn_edge * wn[node])
                    dn_other += (an[edge] * Sn_edge * wn[other]) if left \
                        else (-an[edge] * Sn_edge * wn[other])
                add(3 * node + 1, 3 * node, dpsi_node)
                add(3 * node + 1, 3 * other, dpsi_other)
                add(3 * node + 1, 3 * node + 1, dn_node + bsign_n * S_n_s)
                add(3 * node + 1, 3 * other + 1, dn_other)
            if S_p_s == 0.0:
                F[3 * node + 2] = p[node] - p0
                add(3 * node + 2, 3 * node + 2, 1.0)
                dirichlet_rows.append(3 * node + 2)
            else:
                F[3 * node + 2] = Jp[edge] + bsign_p * S_p_s * (p[node] - p0)
                dpsi_node = -dJp_dpsiR[edge] if left else dJp_dpsiR[edge]
                dpsi_other = dJp_dpsiR[edge] if left else -dJp_dpsiR[edge]
                dp_node = ap[edge] * Bp_h[edge] if left else -ap[edge] * Bm_h[edge]
                dp_other = -ap[edge] * Bm_h[edge] if left else ap[edge] * Bp_h[edge]
                if fd:
                    # Hole mirror of the electron FD correction above --
                    # OPPOSITE sign, same convention as the interior hole
                    # rows' wp terms (delta_tilde_p carries -dL_p).
                    Sp_edge = p[edge + 1] * dBm_h[edge] + p[edge] * dBp_h[edge]
                    dp_node += (ap[edge] * Sp_edge * wp[node]) if left \
                        else (-ap[edge] * Sp_edge * wp[node])
                    dp_other += (-ap[edge] * Sp_edge * wp[other]) if left \
                        else (ap[edge] * Sp_edge * wp[other])
                add(3 * node + 2, 3 * node, dpsi_node)
                add(3 * node + 2, 3 * other, dpsi_other)
                add(3 * node + 2, 3 * node + 2, dp_node + bsign_p * S_p_s)
                add(3 * node + 2, 3 * other + 2, dp_other)

        # M44: coupled electron energy balance, appended as a 4th block
        # (rows/cols 3*N..4*N-1) -- see Models.energy_balance's own
        # docstring and M44-HYDRODYNAMIC-PLAN.md Slice 1. The psi/n/p
        # block above is COMPLETELY UNCHANGED by this: F/rows/cols/vals
        # for it were already finalized in the lines above, so
        # `theta is None` (the default) returns EXACTLY the pre-M44
        # F/J, bit-identical.
        if theta is not None:
            KAPPA0, ALPHA = self._KAPPA0, self._ALPHA_RELAX
            # M44 Slice 4 finding: n_lag underflows to ~1e-14 in a
            # deep-minority region -- left unfloored, kappa_s vanishes
            # there and decouples that node from every neighbor at
            # once, which measurably rank-deficient a 2D grid's larger
            # Jacobian (Device1D's tridiagonal structure tolerates a
            # single weak link better, which is why this was found in
            # Slice 4, not here -- but the same floor belongs here too,
            # for the same reason `_STIFF_DENSITY_FLOOR` exists: a node
            # with ~0 carriers has no physically meaningful electron
            # temperature to solve for anyway). See hydro_grid.py's own
            # matching fix and M44-HYDRODYNAMIC-PLAN.md Slice 4.
            n_floor = np.maximum(n_lag, 1e-8)
            kappa_s = KAPPA0 * self.mu_n0 * n_floor * theta   # per node
            theta_edge = 0.5 * (theta[:-1] + theta[1:])
            kappa_edge = 0.5 * (kappa_s[:-1] + kappa_s[1:])
            grad_theta = (theta[1:] - theta[:-1]) / h
            w_edge = -2.5 * theta_edge * Jn_lag - kappa_edge * grad_theta
            # d(w_edge)/d(theta[node]) via the two additive pieces:
            # convective (theta_edge's own linear dependence) and
            # conductive (kappa_edge's linear dependence on theta,
            # through kappa_s, AND grad_theta's explicit dependence).
            dkappa_L = 0.5 * KAPPA0 * self.mu_n0[:-1] * n_floor[:-1]  # d kappa_edge/d theta[e]
            dkappa_R = 0.5 * KAPPA0 * self.mu_n0[1:] * n_floor[1:]    # d kappa_edge/d theta[e+1]
            dw_dthetaL = (-2.5 * 0.5 * Jn_lag
                         - dkappa_L * grad_theta - kappa_edge * (-1.0 / h))
            dw_dthetaR = (-2.5 * 0.5 * Jn_lag
                         - dkappa_R * grad_theta - kappa_edge * (1.0 / h))

            Q_src = Qheat_lag - ALPHA * n_floor * (theta - 1.0)
            dQ_dtheta = -ALPHA * n_floor

            F_T = np.empty(N)
            base = 3 * N
            F_T[0] = theta[0] - 1.0
            add(base, base, 1.0)
            dirichlet_rows.append(base)
            F_T[-1] = theta[-1] - 1.0
            add(base + N - 1, base + N - 1, 1.0)
            dirichlet_rows.append(base + N - 1)
            # Interior nodes i=1..N-2, vectorized (Slice 2 measurement
            # found the earlier per-node Python loop dominated wall
            # time and worsened with N -- see M44-HYDRODYNAMIC-PLAN.md
            # Slice 2; no serial dependency exists here, every term is
            # already a precomputed edge-indexed array). L=i-1, Rt=i
            # are the edge indices left/right of node i.
            idx = np.arange(1, N - 1)
            L, Rt = idx - 1, idx
            F_T[1:-1] = (w_edge[Rt] - w_edge[L]) - dV[1:-1] * Q_src[1:-1]
            add(base + idx, base + idx - 1, -dw_dthetaL[L])
            add(base + idx, base + idx,
                dw_dthetaL[Rt] - dw_dthetaR[L] - dV[idx] * dQ_dtheta[idx])
            add(base + idx, base + idx + 1, dw_dthetaR[Rt])
            F = np.concatenate([F, F_T])
            shape = 4 * N
        else:
            shape = 3 * N

        J = csr_matrix((np.concatenate(vals),
                        (np.concatenate(rows), np.concatenate(cols))),
                       shape=(shape, shape))
        self._dirichlet_rows = np.array(sorted(dirichlet_rows), dtype=int)
        return F, J, Jn, Jp

    # ------------------------------------------------------------------
    def solve_bias(self, V, opts: NewtonOptions = None):
        # M20: DG is EQUILIBRIUM-ONLY in this milestone -- the quantum
        # potential must also enter the SG currents for a meaningful
        # biased solve, which is DG transport (out of scope; see
        # M20-DENSITY-GRADIENT-PLAN.md section 5).  Refuse loudly
        # rather than silently ignore the flag (standing rule since
        # the M13 incomplete_ion guard).
        if getattr(self.models, "dg", False):
            raise NotImplementedError(
                "Models(dg=True) is equilibrium-only in M20: solve_bias "
                "would need DG inside the Scharfetter-Gummel currents "
                "(DG transport), which is out of scope.  Use the "
                "MOSCapacitor(dg=True) C-V path for the quantum-corrected "
                "inversion layer.")
        if getattr(self.models, "tat", False):
            self._Pn = None
            self._Pp = None
        """Solve at applied bias V = [V_left, V_right] (volts)."""
        opts = opts or NewtonOptions()
        # M31 P5-1 Phase D: opts.linsolve="auto" resolves ONCE, here.
        # Phase A-2 MEASURED 1D (B2) and it resolves to "direct" -- not
        # for lack of evidence but because six of seven iterative
        # configurations do not converge on a 1D coupled Jacobian at
        # all, and the survivor is ~300x slower than a direct solve.
        # See linsolve.select_auto's own docstring.
        resolved_linsolve, auto_reason = (
            linsolve.select_auto(dim=1, unstructured=False, coupled=True,
                                 dof=3 * self.N)
            if opts.linsolve == "auto" else (opts.linsolve, None))
        if opts.verbose and auto_reason:
            print(f"    solve_bias  auto -> {resolved_linsolve} ({auto_reason})")
        self.last_auto_method = resolved_linsolve if opts.linsolve == "auto" else None
        self.last_auto_reason = auto_reason
        if self.psi is None:
            self.solve_equilibrium(opts)

        psi, n, p = self.psi.copy(), self.n.copy(), self.p.copy()

        last_converged = False

        # M15 R1b: generation is computed LIVE inside _residual_jacobian
        # every Newton iterate (no frozen field snapshot, no cached
        # source) -- see the constants block and _residual_jacobian's
        # "M15 impact-ionization generation" section.  A generation-
        # strength continuation (self._ii_strength, ramped below) is
        # kept purely for Newton robustness at the stiff avalanche
        # onset; it multiplies the live, fully-coupled term and its
        # Jacobian consistently, so it never desyncs residual from
        # Jacobian the way a frozen source could.
        ii_enabled = getattr(self.models, "impact", False)
        # M16: BTBT reuses the SAME strength-ladder + backtracking
        # machinery as II (the ladder ramps a scalar multiplying the
        # live term and its Jacobian consistently).  A Zener source is
        # even stiffer than avalanche onset (G ~ exp(-1e8/F)), so the
        # leading 0.0 relaxation stage matters just as much here.
        btbt_enabled = getattr(self.models, "btbt", False)
        # M34-S1: nonlocal BTBT windows are frozen for the DURATION of
        # this solve_bias call (relocated lazily on the first
        # _residual_jacobian evaluation below, same None-cache pattern
        # `_Pn`/`_Pp` use) -- resetting here, once per call, is what
        # gives that cadence; `_residual_jacobian` itself never resets
        # this cache (unlike `_btbt_gs_cache`, which IS live every
        # iterate and is reset there instead).
        btbt_nl_enabled = getattr(self.models, "btbt_nonlocal", False)
        self._btbt_nl_paths = None
        stiff_gen = ii_enabled or btbt_enabled or btbt_nl_enabled
        # M34: deep-minority densities (p ~ 1e-22 scaled on an n+ side)
        # are undetermined at round-off -- measured: full Newton steps
        # at |F| ~ 1e-13 move them by ~1e-4 relative every iteration --
        # so the raw relative-update test can never close.  With a M34
        # flag on, updates are measured against the M11-S5 density
        # floor Device2D/Device3D already use (1e-10 scaled).
        # M34-S7: every stiff (ladder + line search) path now measures
        # that way, because the test reads the FULL Newton correction
        # (see _newton): on M15's diode the raw metric sits at O(1) on
        # the n+ side's p ~ 1e-19 holes at every step, measured.  The
        # plain path keeps the raw test, bit-identical.
        m34_active = btbt_nl_enabled or getattr(
            self.models, "impact_nonlocal", False)
        floored = stiff_gen or m34_active
        self._ii_strength = 1.0

        bc = self._contact_values(V)
        psi[0], n[0], p[0] = bc[0]
        psi[-1], n[-1], p[-1] = bc[1]

        # M44: theta = Tn/T, warm-started from the previous solve (or
        # TL on the very first bias point -- zero current there means
        # zero Joule heating, so theta==1 is the EXACT solution, not an
        # approximation). Jn_prev starts at 0 for the same reason: the
        # Tn row's Joule-heating source is genuinely zero until the
        # first iterate produces a nonzero current.
        energy_balance = self.models.energy_balance
        if energy_balance:
            theta = (self.Tn / self.T).copy() if self.Tn is not None \
                else np.ones(self.N)
            theta[0], theta[-1] = 1.0, 1.0
            Jn_prev = np.zeros(self.N - 1)

        # One Newton solve at the current frozen gs.  Returns
        # (converged, err).  This is the ONLY Newton implementation --
        # the staged continuation and the outer fixed-point loop below
        # both drive it, rather than carrying their own copies.
        def _newton():
            nonlocal psi, n, p
            if energy_balance:
                nonlocal theta, Jn_prev
            err = float("inf")
            for it in range(opts.max_iter):
                E_node = None
                if self.models.field_mobility:
                    # Edge-valued |E| (length N-1) averaged onto nodes
                    # symmetrically -- E_node[i] = 0.5*(|E_{i-1/2}| +
                    # |E_{i+1/2}|) for interior nodes, the boundary edge
                    # value at the endpoints.  Evaluating mu at a node
                    # using only its RIGHT edge's field (the previous
                    # np.r_[...] padding) shifted the field-dependence by
                    # half a cell and broke the discretization's spatial
                    # symmetry.
                    E_abs = np.abs(-(psi[1:] - psi[:-1]) * self.VT
                                   / (self.h * self.LD))
                    E_node = np.empty(self.N)
                    E_node[0] = E_abs[0]
                    E_node[-1] = E_abs[-1]
                    E_node[1:-1] = 0.5 * (E_abs[:-1] + E_abs[1:])
                if energy_balance:
                    # M44 Finding 3: reuse M29's own already-gated
                    # inverse closure to get the field consistent with
                    # the CURRENT (lagged) Tn iterate, then feed the
                    # SAME already-gated Canali mobility model that
                    # field_mobility uses -- this REPLACES field_mobility
                    # (not composed with it: Models.__post_init__-level
                    # comment documents this precedence).
                    Tn_lag = theta * self.T
                    E_eff = _hydro.effective_field_from_temperature(
                        Tn_lag, self.mu_n0, _hydro.TAU_W_N, self.T)
                    mu_n = mobility_field(self.mu_n0, E_eff, self.mat, "n")
                    mu_p = mobility_field(self.mu_p0, E_eff, self.mat, "p")
                    self._set_edge_diffusivity(mu_n, mu_p)
                elif self.models.field_mobility:
                    mu_n = mobility_field(self.mu_n0, E_node, self.mat, "n")
                    mu_p = mobility_field(self.mu_p0, E_node, self.mat, "p")
                    self._set_edge_diffusivity(mu_n, mu_p)

                if energy_balance:
                    n_lag = n.copy()
                    # M44 Joule-heating source: Jn.E_n, where E_n =
                    # -grad(phi_n) is the ELECTRON QUASI-FERMI-POTENTIAL
                    # gradient, not the raw electrostatic field -- the
                    # SAME Wachutka (1990) fix M19 self-heating already
                    # needed for its own H=Jn*E_n+Jp*E_p term
                    # (thermal.joule_heating_density's docstring: plain
                    # E=-grad(psi) gives thermodynamically-impossible
                    # LOCAL NEGATIVE heat in a diode's diffusion-
                    # dominated depletion region -- confirmed here too,
                    # by direct measurement, before this fix: Tn dropped
                    # BELOW TL near the junction, which is unphysical).
                    # Edge product first, THEN box-averaged to nodes --
                    # matching thermal.py's own convention (averaging
                    # E_n and Jn separately before multiplying is NOT
                    # the same thing and was not what was measured).
                    phi_n_lag = psi - np.log(np.maximum(n_lag, 1e-300)
                                             / self.nie_s)
                    En_edge = -(phi_n_lag[1:] - phi_n_lag[:-1]) / self.h
                    Hn_edge = Jn_prev * En_edge
                    Qheat_lag = np.empty(self.N)
                    Qheat_lag[0], Qheat_lag[-1] = Hn_edge[0], Hn_edge[-1]
                    Qheat_lag[1:-1] = 0.5 * (Hn_edge[:-1] + Hn_edge[1:])
                    F, J, Jn, Jp = self._residual_jacobian(
                        psi, n, p, bc, theta=theta, n_lag=n_lag,
                        Jn_lag=Jn_prev, Qheat_lag=Qheat_lag)
                    Jn_prev = Jn.copy()
                else:
                    F, J, Jn, Jp = self._residual_jacobian(psi, n, p, bc)
                # Symmetric Dirichlet elimination. F itself is left
                # ALONE -- the backtracking merit below and the
                # convergence test both read it, and folding the
                # substitution into it would change damping decisions
                # rather than only the arithmetic. See
                # pytcad/dirichlet.py.
                Jd, rhs = eliminate_csr(J, -F, self._dirichlet_rows)
                if resolved_linsolve == "direct":
                    du = spsolve(Jd.tocsc(), rhs)
                else:
                    # NOT given Phase C's try/except fallback: that
                    # phase's own scope was the four unstructured loops
                    # plus device3d.py's pre-existing coupled fallback,
                    # and adding one here now would be an unrequested
                    # behavior change for any caller already passing an
                    # explicit non-"direct" opts.linsolve (their
                    # LinearSolveError would now be silently swallowed
                    # instead of raised). Moot for "auto" specifically,
                    # since dim=1 is MEASURED to prefer direct (Phase
                    # A-2, B2) and so resolves to "direct" above -- this
                    # branch is unreachable through "auto". If a future
                    # measurement ever moves dim=1 off direct, THIS
                    # missing fallback becomes live and must be added
                    # first.
                    du, _ = linsolve.solve_linear(
                        Jd, rhs, method=resolved_linsolve,
                        rtol=opts.linsolve_rtol, block_size=opts.block_size,
                        precond=opts.precond)
                if energy_balance:
                    N3 = 3 * self.N
                    dpsi, dn, dp = du[0:N3:3], du[1:N3:3], du[2:N3:3]
                    dtheta = du[N3:]
                else:
                    dpsi, dn, dp = du[0::3], du[1::3], du[2::3]

                dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
                n_old, p_old = n, p
                n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
                p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)

                # Convergence is judged on the FULL Newton correction,
                # before any damping.  M34-S7: the stiff paths used to
                # measure the line-search-damped update, which a small lam
                # passes with the correction still large -- measured on
                # M15's diode at -30V, the returned state carried 0.698 of
                # the discrete solution's current.
                if floored:
                    rel_n = (np.abs(n_new - n_old)
                             / np.maximum(n_old, _STIFF_DENSITY_FLOOR)).max()
                    rel_p = (np.abs(p_new - p_old)
                             / np.maximum(p_old, _STIFF_DENSITY_FLOOR)).max()
                else:
                    rel_n = np.abs(n_new / np.maximum(n_old, 1e-300)
                                   - 1.0).max()
                    rel_p = np.abs(p_new / np.maximum(p_old, 1e-300)
                                   - 1.0).max()
                err = max(np.abs(dpsi).max(), rel_n, rel_p)
                if energy_balance:
                    err = max(err, float(np.abs(dtheta).max()))

                # M15 backtracking: 2-norm merit reduction test
                # (M16: also active for BTBT -- stiff_gen above), run only
                # outside Newton's region (_LS_NEWTON_REGION); inside it,
                # and for a converged step, the step is taken whole.
                if stiff_gen and err >= _LS_NEWTON_REGION:
                    base = 0.5 * float(np.dot(F, F))
                    lam = 1.0
                    for _ in range(_LS_MAX_HALVINGS + 1):
                        Ft, *_ = self._residual_jacobian(
                            psi + lam * dpsi,
                            np.clip(n_old + lam * dn, 0.1 * n_old,
                                    10.0 * n_old),
                            np.clip(p_old + lam * dp, 0.1 * p_old,
                                    10.0 * p_old), bc)
                        ft = 0.5 * float(np.dot(Ft, Ft))
                        if np.isfinite(ft) and \
                                ft <= base * (1.0 - 1e-4 * lam):
                            break
                        lam *= 0.5
                    else:
                        # No trial reduced the merit.  lam = 0 would repeat
                        # this identical iterate (state, F, J and step
                        # cannot change) until max_iter -- a certain
                        # failure; take the full step and let the update
                        # test judge (M34-S7; Device2D/3D's rule).
                        lam = 1.0
                    if opts.verbose:
                        print(f"   stage {self._ii_strength}  lam={lam:.3e}"
                              f"  merit {base:.3e} -> {ft:.3e}")
                    n_new = np.clip(n_old + lam * dn, 0.1 * n_old,
                                    10.0 * n_old)
                    p_new = np.clip(p_old + lam * dp, 0.1 * p_old,
                                    10.0 * p_old)
                    psi = psi + lam * dpsi
                    n, p = n_new, p_new
                else:
                    psi = psi + dpsi
                    n, p = n_new, p_new
                    if energy_balance:
                        # Relative clip, same convention as n/p's own
                        # 0.1x-10x bound -- an unclipped/absolute-range
                        # clip let a single early Newton step overshoot
                        # by >30x (Tn 300K -> 10800K in one iterate),
                        # which was harmless in 1D but corrupted y/z-
                        # uniformity once the same code was ported to a
                        # multi-row 2D/3D grid (found while gating M44
                        # Slice 4 -- see M44-HYDRODYNAMIC-PLAN.md).
                        theta = np.clip(theta + dtheta, 0.1 * theta,
                                       10.0 * theta)
                        theta[0], theta[-1] = 1.0, 1.0
                if opts.verbose:
                    print(f"   it {it:2d}  |F|={np.abs(F).max():.3e}  "
                          f"|dpsi|={np.abs(dpsi).max():.3e}  "
                          f"|dn/n|={rel_n:.3e}")
                if err < opts.tol_update:
                    return True, err
            return False, err

        # Generation-strength continuation: ramp the LIVE, fully-coupled
        # source from weak to full.  Each stage runs its own Newton
        # solve to full convergence at that strength; the final state
        # seeds the next stage (warm start).  Every stage is itself a
        # fully self-consistent Newton solve of the coupled system, so
        # there is no separate outer fixed-point loop or closure
        # criterion left to run: Newton's own convergence tolerance IS
        # the closure criterion now.  Getting PAST the avalanche fold
        # itself (where plain voltage-controlled Newton basin-locks
        # onto a weak branch -- see the constants block) is
        # pytcad.continuation.arc_length_sweep's job, not this loop's;
        # solve_bias stays a plain bias-controlled solver.
        stages = _II_STAGES if stiff_gen else (1.0,)
        err = float("inf")

        for stage_factor in stages:
            self._ii_strength = stage_factor
            last_converged, err = _newton()
            if not last_converged:
                break

        # M34-S1: the tunnel paths were located at the WARM START.  Make
        # the converged state consistent with its own paths: re-locate
        # them at the converged psi and, if the start set changed or a
        # path is truncated (its delta = 1 crossing left the frozen
        # span), re-solve at full strength with the new ones.  Bounded,
        # and reported in last_btbt_nl_stable rather than hidden.
        self.last_btbt_nl_refreshes = 0
        self.last_btbt_nl_stable = None
        if btbt_nl_enabled and last_converged:
            self.last_btbt_nl_stable = False
            while True:
                new = self._btbt_nl_build_paths(psi)
                cur = self._btbt_nl_paths
                if (cur is not None and np.array_equal(new.start, cur.start)
                        and self._btbt_nl_eval(psi).reached.all()):
                    self.last_btbt_nl_stable = True
                    break
                if self.last_btbt_nl_refreshes == 4:
                    break
                self._btbt_nl_paths = new
                self.last_btbt_nl_refreshes += 1
                # Plain full-step Newton here, not the stiff_gen
                # backtracking: the re-solve starts from a converged
                # state, and a newly located path can dominate a deep-
                # minority node's balance while its residual sits below
                # the other rows' round-off -- the unscaled merit then
                # rejects the (physical) step and the update test never
                # closes (measured: dp/p = 0.38 at p ~ 3e-22, -5.5V).
                stiff_gen = False
                last_converged, err = _newton()
                if not last_converged:
                    break

        if not last_converged:
            warnings.warn(f"Newton did not converge at V={V}; "
                          f"last update {err:.2e}")

        self.psi, self.n, self.p = psi, n, p
        if energy_balance:
            self.Tn = theta * self.T
        _, _, Jn, Jp = self._residual_jacobian(psi, n, p, bc)
        self.Jn = Jn * self.J0
        self.Jp = Jp * self.J0
        # M22 phase 2: convergence status as an attribute, not just a
        # warning -- a continuation driver needs to detect failure
        # reliably (parsing warning text is not that).
        self.last_converged = last_converged
        self.last_newton_err = err
        return self

    # --- physical-unit accessors -------------------------------------
    @property
    def psi_V(self):
        """Electrostatic potential [V]."""
        return self.psi * self.VT

    @property
    def n_cm3(self):
        """Electron density [cm^-3]."""
        return self.n * self.Ns

    @property
    def p_cm3(self):
        """Hole density [cm^-3]."""
        return self.p * self.Ns

    @property
    def E_field(self):
        """Electric field on the mesh interfaces [V/cm]."""
        return -(self.psi[1:] - self.psi[:-1]) * self.VT / (self.h * self.LD)

    # ------------------------------------------------------------------
    def current_density(self):
        """Total current density [A/cm^2].

        In 1D steady state Jn + Jp is exactly constant; the spread across
        interfaces is a useful convergence diagnostic and is returned too.
        """
        Jt = self.Jn + self.Jp
        return float(np.mean(Jt)), float(np.std(Jt) / (np.abs(np.mean(Jt)) + 1e-30))

    def iv_sweep(self, voltages, terminal=0, opts: NewtonOptions = None,
                 verbose=True):
        """Ramp bias and record J(V).  The previous solution seeds the next
        bias point -- essential for convergence beyond a few hundred mV."""
        opts = opts or NewtonOptions()
        self.solve_equilibrium(opts)
        J = []
        for V in voltages:
            bias = [V, 0.0] if terminal == 0 else [0.0, V]
            self.solve_bias(bias, opts)
            j, spread = self.current_density()
            J.append(j)
            if verbose:
                print(f"  V = {V:+.3f} V   J = {j:+.6e} A/cm^2   "
                      f"(continuity spread {spread:.1e})")
        return np.array(J)

    # ------------------------------------------------------------------
    def band_diagram(self):
        """Conduction/valence band edges and quasi-Fermi levels [eV]."""
        VT = self.VT
        chi_arr = np.array([m.chi for m in self.mats])
        Eg_arr = np.array([m.Eg(self.T) for m in self.mats])
        Ec = -self.psi * VT - chi_arr
        Ev = Ec - Eg_arr
        Nc_arr = np.array([m.Nc(self.T) for m in self.mats])
        Nv_arr = np.array([m.Nv(self.T) for m in self.mats])
        if getattr(self.models, "fd", False):
            # M13: physical-statistics quasi-Fermi levels -- a Boltzmann
            # log would misplace E_F by many kT in degenerate regions.
            en = f_half_inv(np.maximum(self.n_cm3, 1e-300) / Nc_arr)
            ep = f_half_inv(np.maximum(self.p_cm3, 1e-300) / Nv_arr)
            EFn = Ec + KB_EV * self.T * en
            EFp = Ev - KB_EV * self.T * ep
            return Ec, Ev, EFn, EFp
        EFn = Ec + VT * np.log(np.maximum(self.n * self.Ns, 1e-30)
                               / Nc_arr)
        EFp = Ev - VT * np.log(np.maximum(self.p * self.Ns, 1e-30)
                               / Nv_arr)
        return Ec, Ev, EFn, EFp

