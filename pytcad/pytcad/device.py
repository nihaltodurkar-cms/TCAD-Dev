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

from . import linsolve

from .constants import KB_EV, Q, EPS0, thermal_voltage
from .fermi import (
    FERMI_ETA_MAX, FERMI_ETA_MIN, f_half, f_half_inv, f_mhalf,
)
from .ionization import alpha_n as _ii_alpha_n
from .ionization import alpha_p as _ii_alpha_p
from .ionization import dalpha_dE as _ii_dalpha_dE
from .ionization import Q_E as _II_Q
from .btbt import btbt_generation as _btbt_G
from .btbt import dbtbt_dF as _btbt_dG

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

D0_REF = 1.0  # reference diffusivity for scaling [cm^2/s]


# ----------------------------------------------------------------------
#  M13 Fermi-Dirac helpers (asymmetric eta policy -- see docstrings)
# ----------------------------------------------------------------------
def fd_density(nc, eta):
    """n = nc * F_{1/2}(eta) with the M13 asymmetric eta policy.

    Below eta = -35 the integral switches to its EXACT Boltzmann tail
    exp(eta): the FD deviation there is exp(eta)/2^{3/2} <= 2.5e-16
    RELATIVE -- below double precision and MORE accurate than evaluating
    the quadrature on a 1e-12-scale value (minority carriers reach
    eta ~ -170 at cryogenic temperature).  Above FERMI_ETA_MAX we refuse
    loudly -- beyond +40 the parabolic-band model itself is invalid (G7
    applicability); no silent extrapolation.  The branches agree to
    ~2e-16 at the crossover."""
    eta = np.asarray(eta, dtype=float)
    if np.any(eta > FERMI_ETA_MAX):
        raise ValueError(
            f"FD density argument eta={eta.max():.1f} exceeds "
            f"+{FERMI_ETA_MAX:.0f}: outside the validated Fermi-integral "
            f"range (M13 G7 applicability).  Refusing to extrapolate.")
    shp = np.broadcast_shapes(np.shape(nc), eta.shape)
    e1 = np.broadcast_to(np.asarray(eta, dtype=float), shp).ravel()
    c1 = np.broadcast_to(np.asarray(nc, dtype=float), shp).ravel()
    lo = e1 < -35.0
    # f_half's fixed-node quadrature is vectorized over 1-D inputs
    # only -- flatten, evaluate, restore (any-shape grids supported).
    out = np.where(lo,
                   c1 * np.exp(np.minimum(e1, 700.0)),
                   c1 * f_half(np.clip(e1, FERMI_ETA_MIN,
                                       FERMI_ETA_MAX)))
    return out.reshape(shp)


def fd_ddensity_deta(nc, eta):
    """d(nc F(eta))/d(eta) matching fd_density piecewise: f_mhalf
    inside the validated range, the exact tail derivative nc*exp(eta)
    below FERMI_ETA_MIN, loud refusal above."""
    eta = np.asarray(eta, dtype=float)
    if np.any(eta > FERMI_ETA_MAX):
        raise ValueError(
            f"FD density argument eta={eta.max():.1f} exceeds "
            f"+{FERMI_ETA_MAX:.0f} (M13 G7 applicability).")
    shp = np.broadcast_shapes(np.shape(nc), eta.shape)
    e1 = np.broadcast_to(np.asarray(eta, dtype=float), shp).ravel()
    c1 = np.broadcast_to(np.asarray(nc, dtype=float), shp).ravel()
    lo = e1 < -35.0
    tail = np.exp(np.minimum(e1, 700.0))
    out = np.where(lo, c1 * tail,
                   c1 * f_mhalf(np.clip(e1, FERMI_ETA_MIN,
                                        FERMI_ETA_MAX)))
    return out.reshape(shp)


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


def fd_ohmic_values(C, nc_s, nv_s, ln_gn, eg_kt, V, VT):
    """FD ohmic-contact values for ARBITRARY node sets (vectorized
    bisection; the exact Boltzmann closed form is recovered as
    F -> exp).  All inputs broadcast against each other; C is the SCALED
    net doping at the contact nodes.  Returns (psi0, n0, p0) scaled."""
    C = np.asarray(C, dtype=float)

    def dens(e):
        return fd_density(nc_s, np.minimum(e, FERMI_ETA_MAX)), \
            fd_density(nv_s, np.minimum(-e - eg_kt, FERMI_ETA_MAX))

    lo = -eg_kt - (FERMI_ETA_MAX - FERMI_ETA_MIN) - 1.0
    hi = np.full(np.shape(C), float(FERMI_ETA_MAX))

    def g(e):
        n_, p_ = dens(e)
        return n_ - p_ - C

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
#  Bernoulli function and its derivative (numerically stable)
# ----------------------------------------------------------------------
def bernoulli(x):
    """B(x) = x / (exp(x) - 1), with B(0) = 1."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)          # dummy to avoid 0/0
    out = np.where(small,
                   1.0 - x / 2.0 + x * x / 12.0,
                   xs / np.expm1(xs))
    return out


def dbernoulli(x):
    """dB/dx, computed as B(x) [1/x - 1/(1 - e^-x)] for stability."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)
    B = np.where(small, 1.0, xs / np.expm1(xs))
    em = -np.expm1(-xs)                   # 1 - exp(-x)
    em = np.where(np.abs(em) < 1e-300, 1e-300, em)
    full = B * (1.0 / xs - 1.0 / em)
    series = -0.5 + x / 6.0 - x**3 / 180.0
    return np.where(small, series, full)


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
    # M16: local Kane band-to-band tunneling (Hurkx 1992 Si
    # coefficients, G = A F^2 exp(-B/F)).  Default OFF => bit-identical
    # to the plain solver (goldens).  1D only; Device2D/3D raise.
    btbt: bool = False
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
    # M14: surface recombination velocity at contacts [cm/s], Robin BC
    # Jn.n_hat = q*S_n*(n-n0), Jp.n_hat = q*S_p*(p-p0). S_n = S_p = 0
    # (default) => no surface recombination, bit-identical to the plain
    # Dirichlet contact (verified: (1.0 + 0.0) == 1.0 exactly, no
    # branching needed in the residual/Jacobian). Wired in Device1D and
    # Device2D; Device3D raises (never in the M14 plan's scope for this
    # feature -- see device3d.py's own guard, not this shared one).
    S_n: float = 0.0
    S_p: float = 0.0

    def __post_init__(self):
        # driving_force is declared and documented as controlling real
        # physics but has no consumer: Canali/mobility_field() (the only
        # place a "driving force" argument exists) is unconditionally
        # NotImplementedError in Device2D/Device3D, and Device1D's plain
        # "field" convention is the only one implemented anywhere.
        # Refuse loudly rather than silently no-op, same as
        # impact/incomplete_ion do for a dimensionality that can't honor
        # them.
        if self.driving_force != "field":
            raise NotImplementedError(
                f"Models.driving_force={self.driving_force!r} is not "
                "implemented -- only the default 'field' driving force "
                "is wired into the mobility model.")


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
    linsolve: str = "direct"
    linsolve_rtol: float = 1e-10


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
                 models: Models = None):
        self.x = np.asarray(x, dtype=float)
        self.N = self.x.size
        self.doping = np.asarray(doping, dtype=float)
        self.Ntot = np.abs(self.doping) if Ntotal is None else np.asarray(Ntotal, float)
        self.T = T
        # M11-S3: a single Semiconductor keeps the classic behavior; a
        # per-node sequence defines a heterostructure.  All material
        # fields below become node arrays in that case, and eps(x)
        # enters the Poisson flux form while chi/Eg enter the currents
        # through position-dependent nie (band offsets ride ln(nie)
        # edge factors -- see _residual_jacobian).
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
        # M13 incomplete ionization: dopant split from the net doping.
        # Single-species assumption (majority side carries all dopants);
        # documented in Models.incomplete_ion.
        self.nd_arr = np.maximum(self.doping, 0.0) / self.Ns   # scaled N_D
        self.na_arr = np.maximum(-self.doping, 0.0) / self.Ns  # scaled N_A

        # interface (harmonic-mean) diffusivities, scaled
        self._set_edge_diffusivity(self.mu_n0, self.mu_p0)

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
        # M12-S2 frozen-field WKB escape probabilities (None until the
        # first TAT-enabled residual evaluation freezes them)
        self._Pn = None
        self._Pp = None
        # M22 phase 2: convergence status of the last solve_bias call.
        self.last_converged = None
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
        (majority side carries all dopants)."""
        en, ep = self._fd_eta(n, p)
        ded_kt = 0.045 / (KB_EV * self.T)
        ed_n = np.exp(np.minimum(en + ded_kt, 700.0))    # e^{eta_n+dE/kT}
        ea_p = np.exp(np.minimum(ep + ded_kt, 700.0))
        ndp = self.nd_arr / (1.0 + 2.0 * ed_n)
        nam = self.na_arr / (1.0 + 4.0 * ea_p)
        # chain: d(eta)/d(density) = 1/(Nc_s F'(eta)) with the exact
        # tail derivative exp(eta) below the validated range
        # (consistent with fd_density's piecewise policy)
        tail_n = np.exp(np.minimum(en, 700.0))
        tail_p = np.exp(np.minimum(ep, 700.0))
        den_n = np.where(en >= FERMI_ETA_MIN,
                         f_mhalf(np.clip(en, FERMI_ETA_MIN,
                                         FERMI_ETA_MAX)), tail_n)
        den_p = np.where(ep >= FERMI_ETA_MIN,
                         f_mhalf(np.clip(ep, FERMI_ETA_MIN,
                                         FERMI_ETA_MAX)), tail_p)
        detn = 1.0 / np.maximum(self.nc_s * den_n, 1e-300)
        detp = 1.0 / np.maximum(self.nv_s * den_p, 1e-300)
        dndp_dn = -2.0 * ed_n / (1.0 + 2.0 * ed_n) ** 2 \
            * self.nd_arr * detn
        dnam_dp = -4.0 * ea_p / (1.0 + 4.0 * ea_p) ** 2 \
            * self.na_arr * detp
        cion = ndp - nam                 # scaled (ND+ - NA-)/Ns
        return cion, dndp_dn, -dnam_dp   # d cion/dn, d cion/dp

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
                ded_kt = 0.045 / (KB_EV * self.T)
                ndp = self.nd_arr / (1.0 + 2.0 * np.exp(
                    np.minimum(np.minimum(e, FERMI_ETA_MAX) + ded_kt,
                               700.0)))
                nam = self.na_arr / (1.0 + 4.0 * np.exp(
                    np.minimum(np.minimum(-e - self.eg_kt,
                                          FERMI_ETA_MAX) + ded_kt,
                               700.0)))
                cion = ndp - nam
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
        for i in (0, self.N - 1):
            C, nie = self.C[i], self.nie_s[i]
            root = np.sqrt(C * C + 4.0 * nie * nie)
            if C >= 0.0:                     # n-type: electrons are majority
                n0 = 0.5 * (C + root)
                p0 = nie * nie / n0
            else:                            # p-type: holes are majority
                p0 = 0.5 * (-C + root)
                n0 = nie * nie / p0
            psi0 = V[0 if i == 0 else 1] / self.VT + np.log(n0 / nie)
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
        # see Models.dg).  LAGGED quantum potential inside the Newton
        # loop (frozen-Lambda => dn/dpsi == n exactly, classical
        # Jacobian form) with an outer fixed-point rerun until Lambda
        # closes -- the same Gummel-style architecture the MOSCapacitor
        # DG branch uses.  dg+fd is REFUSED (joint density law not
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
            from .dg import quantum_potential
            gamma = getattr(self.models, "dg_gamma", 1.0)
            m_n = np.array([m.m_n_star for m in self.mats])
            m_p = np.array([m.m_p_star for m in self.mats])
            Lam_n = np.zeros(self.N)
            Lam_p = np.zeros(self.N)
        n_outer = 60 if dg else 1
        psi_prev = None

        for _outer in range(n_outer):
            if fd or ion:
                # M13: eta-space neutral guess (the Boltzmann arcsinh form
                # overshoots badly when ln(Nc/nie) is large -- e.g. GaAs,
                # cryogenic T); psi = eta + ln(Nc/nie) per node.
                psi = self._fd_neutral_eta(C) + self.ln_gn
            else:
                psi = np.arcsinh(C / (2.0 * nie))      # neutral-bulk guess
            if dg and psi_prev is not None:
                psi = psi_prev.copy()                  # warm restart
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
                    n = nie * np.exp(np.clip(psi, -700, 700))
                    p = nie * np.exp(np.clip(-psi, -700, 700))
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

                # M20 DG correction (Boltzmann path only -- dg+fd and
                # dg+incomplete_ion are refused above; with Lambda
                # LAGGED, dn/dpsi == n exactly, so dnp keeps the
                # classical form in terms of corrected n, p).
                if dg:
                    n = n * np.exp(-Lam_n / self.VT)
                    p = p * np.exp(-Lam_p / self.VT)
                    dnp = n + p

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

                # linsolve.solve_linear(method="direct") no longer
                # reformats A before calling spsolve (that reformatting was
                # itself the bug -- see linsolve.py), so this is now
                # actually bit-identical to the raw spsolve(A, -F) call
                # while adding the finiteness/singularity checks every
                # other Newton loop in this file already goes through.
                d, _ = linsolve.solve_linear(A, -F, method="direct")
                d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
                psi = psi + d
                if opts.verbose:
                    print(f"    eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
                if np.abs(d).max() < opts.tol_update:
                    break
            else:
                warnings.warn("Equilibrium Poisson solve did not converge.")

            if dg:
                # M20 outer fixed point: refresh the lagged quantum
                # potentials from the CLASSICAL density of the psi that
                # just converged -- NOT the DG-corrected density (see
                # moscap.py's solve_psi for the full explanation: sourcing
                # this from the DG-corrected density closes a 1-node
                # self-reference at the node next to the Lambda=0
                # boundary and produces a rigid, non-damping period-2
                # oscillation rather than convergence).
                n_c = nie * np.exp(np.clip(psi, -700, 700))
                p_c = nie * np.exp(np.clip(-psi, -700, 700))
                Lam_n_new = quantum_potential(self.x, n_c, m_n,
                                              gamma=gamma, T=self.T)
                Lam_p_new = quantum_potential(self.x, p_c, m_p,
                                              gamma=gamma, T=self.T)
                delta = max(np.abs(Lam_n_new - Lam_n).max(),
                            np.abs(Lam_p_new - Lam_p).max())
                Lam_n, Lam_p = Lam_n_new, Lam_p_new
                psi_prev = psi.copy()
                if delta < 1e-8:
                    break                     # Lambda closed: done
                if _outer == n_outer - 1:
                    warnings.warn("M20 DG equilibrium outer fixed point "
                                  "did not converge (Lambda still moving "
                                  "at the iteration cap).")

        self._ii_gs = None               # no II source at equilibrium
        self._ii_gs_cache = None         # clear frozen generation cache
        self._btbt_gs_cache = None       # M16: no BTBT source at V=0 gauge
        self._dg_Lam_n = Lam_n if dg else None
        self._dg_Lam_p = Lam_p if dg else None
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
        elif dg:
            # M20: the returned densities must be the DG-CORRECTED ones
            # (the same law the residual converged with), not the bare
            # Boltzmann values.
            self.n = nie * np.exp(np.clip(psi, -700, 700)) \
                * np.exp(-Lam_n / self.VT)
            self.p = nie * np.exp(np.clip(-psi, -700, 700)) \
                * np.exp(-Lam_p / self.VT)
        else:
            self.n = nie * np.exp(np.clip(psi, -700, 700))
            self.p = nie * np.exp(np.clip(-psi, -700, 700))
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
        delta = (psi[1:] - psi[:-1]) + dlnnie
        delta_p = (psi[1:] - psi[:-1]) - dlnnie
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

    def _residual_jacobian(self, psi, n, p, bc):
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
        delta = (psi[1:] - psi[:-1]) + dlnnie          # electrons
        delta_p = (psi[1:] - psi[:-1]) - dlnnie        # holes
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
            E_node = self._ii_compute_E_from_state(psi)
            alpha_n_E = _ii_alpha_n(E_node)
            alpha_p_E = _ii_alpha_p(E_node)
            gs_full = self._ii_compute_gs_frozen(
                psi, n, p, alpha_n_E, alpha_p_E)
            strength = getattr(self, "_ii_strength", 1.0)
            self._ii_gs_cache = (gs_full * strength).copy()

            F[3 * i + 1] += strength * gs_full[1:-1] * dV[1:-1]
            F[3 * i + 2] -= strength * gs_full[1:-1] * dV[1:-1]

            dalpha_n_E = _ii_dalpha_dE(E_node, "n")
            dalpha_p_E = _ii_dalpha_dE(E_node, "p")
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
        for k, node in enumerate((0, N - 1)):
            psi0, n0, p0 = bc[k]
            F[3 * node] = psi[node] - psi0
            add(3 * node, 3 * node, 1.0)
            edge = 0 if node == 0 else N - 2   # the one edge touching this node
            other = node + 1 if node == 0 else node - 1
            left = node == 0                   # is `node` the LEFT end of `edge`?
            bsign_n = -1.0 if left else 1.0
            bsign_p = 1.0 if left else -1.0
            if S_n_s == 0.0:
                F[3 * node + 1] = n[node] - n0
                add(3 * node + 1, 3 * node + 1, 1.0)
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

        J = csr_matrix((np.concatenate(vals),
                        (np.concatenate(rows), np.concatenate(cols))),
                       shape=(3 * N, 3 * N))
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
        stiff_gen = ii_enabled or btbt_enabled
        self._ii_strength = 1.0

        bc = self._contact_values(V)
        psi[0], n[0], p[0] = bc[0]
        psi[-1], n[-1], p[-1] = bc[1]

        # One Newton solve at the current frozen gs.  Returns
        # (converged, err).  This is the ONLY Newton implementation --
        # the staged continuation and the outer fixed-point loop below
        # both drive it, rather than carrying their own copies.
        def _newton():
            nonlocal psi, n, p
            err = float("inf")
            for it in range(opts.max_iter):
                if self.models.field_mobility:
                    E = -(psi[1:] - psi[:-1]) * self.VT / (self.h * self.LD)
                    mu_n = mobility_field(
                        self.mu_n0, np.r_[np.abs(E), np.abs(E[-1])],
                        self.mat, "n")
                    mu_p = mobility_field(
                        self.mu_p0, np.r_[np.abs(E), np.abs(E[-1])],
                        self.mat, "p")
                    self._set_edge_diffusivity(mu_n, mu_p)

                F, J, Jn, Jp = self._residual_jacobian(psi, n, p, bc)
                if opts.linsolve == "direct":
                    du = spsolve(J.tocsc(), -F)
                else:
                    du, _ = linsolve.solve_linear(
                        J, -F, method=opts.linsolve, rtol=opts.linsolve_rtol,
                        block_size=3)
                dpsi, dn, dp = du[0::3], du[1::3], du[2::3]

                dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
                n_old, p_old = n, p
                n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
                p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)

                # M15 backtracking: 2-norm merit reduction test
                # (M16: also active for BTBT -- stiff_gen above)
                if stiff_gen:
                    base = 0.5 * float(np.dot(F, F))
                    lam = 1.0
                    for _ in range(40):
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
                        lam = 0.0
                    n_new = np.clip(n_old + lam * dn, 0.1 * n_old,
                                    10.0 * n_old)
                    p_new = np.clip(p_old + lam * dp, 0.1 * p_old,
                                    10.0 * p_old)
                    psi = psi + lam * dpsi
                    n, p = n_new, p_new
                else:
                    psi = psi + dpsi
                    n, p = n_new, p_new

                rel_n = np.abs(n_new / np.maximum(n_old, 1e-300)
                               - 1.0).max()
                rel_p = np.abs(p_new / np.maximum(p_old, 1e-300)
                               - 1.0).max()
                err = max(np.abs(dpsi).max(), rel_n, rel_p)
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

        if not last_converged:
            warnings.warn(f"Newton did not converge at V={V}; "
                          f"last update {err:.2e}")

        self.psi, self.n, self.p = psi, n, p
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

