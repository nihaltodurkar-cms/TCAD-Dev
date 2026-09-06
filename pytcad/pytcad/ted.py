"""M24: extrinsic diffusion enhancement, oxidation/transient-enhanced
diffusion (OED/TED), segregation, and solubility-limited clustering for
1D process simulation, layered on top of pytcad.process.

This is an engineering-level model, not a coupled point-defect PDE solve
(that would be a much larger undertaking than "nothing hard" milestones
warrant -- see the honesty clause below for exactly what is skipped).

HONESTY CLAUSE -- what this module does NOT model
--------------------------------------------------
* No coupled interstitial/vacancy transport-and-recombination PDE system.
  TED is modeled as a single decaying scalar supersaturation
  `S_I(t) = S0 exp(-t/tau)` (the standard "lumped +1" engineering
  approximation), not a spatially resolved point-defect field. It captures
  the qualitative signature of TED (a transient diffusivity boost that
  saturates rather than growing junction depth like sqrt(Dt) forever) but
  does NOT reproduce a specific published SIMS profile.
* Extrinsic enhancement uses Fair's classic f_I*(n/ni) + f_V*(ni/n) form
  with literature-typical fixed (f_I, f_V) per species; it does not solve
  for local charge-state-dependent diffusivity (B-, B0, etc. contributions
  are lumped into a single effective D).
* OED is modeled as a constant multiplicative boost while oxidation is
  active, proportional to the oxide growth rate to the 1/2 power (the
  common empirical form), not a solved interstitial-injection flux
  boundary condition.
* Segregation is an equilibrium partition at a *fixed* interface slab
  (`segregation_partition`), not a moving-boundary flux condition tracked
  through an evolving Deal-Grove interface -- composing it with
  `process2d.oxidize_2d`'s moving Si/SiO2 boundary is future work.
* Clustering is solubility-clipping (anything above the solid-solubility
  table is instantaneously "clustered"/inactive), not a clustering
  reaction-rate ODE. This is the same simplification most process
  simulators use for a first-order dose-loss estimate.

References for the numbers used: Fair, "Concentration Profiles of
Diffused Dopants in Silicon" (in Impurity Doping Processes in Silicon,
1981) for f_I/f_V; Sze & Ng, Physics of Semiconductor Devices, 3rd ed.,
for the silicon n_i(T) fit; Trumbore (1960) and standard SUPREM tables for
solid-solubility orders of magnitude (used here only to the nearest
half-decade -- see solid_solubility()'s own docstring).
"""

import numpy as np

from .constants import KB_EV
from . import process


# ----------------------------------------------------------------------
#  Intrinsic carrier concentration (Sze & Ng fit for silicon)
# ----------------------------------------------------------------------
def ni_silicon(T_C):
    """Intrinsic carrier concentration in silicon [cm^-3].

        n_i(T) = 5.29e19 (T/300)^2.54 exp(-6726/T)

    Sze & Ng's fit, valid roughly 300-1400 K -- i.e. it covers both device
    operating temperatures and process anneal temperatures.
    """
    T = np.asarray(T_C, dtype=float) + 273.15
    return 5.29e19 * (T / 300.0) ** 2.54 * np.exp(-6726.0 / T)


# ----------------------------------------------------------------------
#  Extrinsic diffusion enhancement (Fair's pair-diffusion model)
# ----------------------------------------------------------------------
# Interstitial-mediated fraction f_I (vacancy fraction f_V = 1 - f_I).
# B and P diffuse overwhelmingly via interstitials; As and Sb lean
# vacancy-mediated -- literature-typical values (Fair 1981; Ural et al.
# 1999 for As/Sb splits), not per-lot calibrated constants.
INTERSTITIAL_FRACTION = {"B": 1.00, "P": 0.90, "As": 0.45, "Sb": 0.02}


def extrinsic_enhancement(species, n_total, T_C):
    """D/D_intrinsic enhancement factor under extrinsic doping:

        D/Di = f_I (n/ni) + f_V (ni/n)

    which is exactly 1 at n = ni (intrinsic) by construction -- the
    algebraic property gate G1 relies on.  n_total is the local total
    (electron, for n-type-dominant regions) carrier concentration
    [cm^-3]; for a first-order estimate this is usually taken as the
    local net active doping magnitude.
    """
    if species not in INTERSTITIAL_FRACTION:
        raise KeyError(f"No extrinsic-diffusion data for '{species}'. "
                        f"Available: {list(INTERSTITIAL_FRACTION)}")
    fI = INTERSTITIAL_FRACTION[species]
    fV = 1.0 - fI
    ni = ni_silicon(T_C)
    r = np.asarray(n_total, dtype=float) / ni
    r = np.maximum(r, 1e-30)
    return fI * r + fV / r


# ----------------------------------------------------------------------
#  TED ("+1" lumped interstitial supersaturation)
# ----------------------------------------------------------------------
def ted_plus_one_S0(dose_cm2, damage_depth_cm, C_I_eq_cm3):
    """Initial interstitial supersaturation S0 = (excess I)/(C_I,eq) from
    the "+1" model: one excess silicon interstitial survives Frenkel-pair
    recombination per implanted ion, spread uniformly over the as-damaged
    depth. This is the standard cheap TED initial condition (Giles 1991),
    not a Monte-Carlo damage cascade result.
    """
    excess_I = dose_cm2 / damage_depth_cm
    return excess_I / C_I_eq_cm3


def ted_supersaturation(t_s, S0, tau_s):
    """Decaying lumped interstitial supersaturation S_I(t) = S0 exp(-t/tau).

    tau_s is a fit/engineering time constant (interstitial recombination
    + diffusion-to-sink time), typically seconds to a few minutes at
    900-1050 C -- pass a literature or calibrated value, there is no
    universal default here.
    """
    return S0 * np.exp(-np.asarray(t_s, dtype=float) / tau_s)


# ----------------------------------------------------------------------
#  OED (oxidation-enhanced diffusion)
# ----------------------------------------------------------------------
def oed_enhancement(dxox_dt_um_per_h, C_ref=1.0, power=0.5):
    """Extra multiplicative diffusivity boost while oxide is actively
    growing:  boost = C_ref * (dXox/dt)^power, dXox/dt in um/h.

    The square-root-of-growth-rate form is the common empirical OED
    scaling; C_ref folds in species/orientation dependence and is a knob,
    not a fitted universal constant -- pass 0 (default C_ref path gives a
    nonzero boost unless dxox_dt is 0) to disable OED for a given call by
    passing dxox_dt_um_per_h=0.
    """
    rate = max(float(dxox_dt_um_per_h), 0.0)
    return C_ref * rate ** power


# ----------------------------------------------------------------------
#  Diffusion with extrinsic/TED/OED enhancement
# ----------------------------------------------------------------------
def diffuse_with_defects(x, C, species, T_C, t_s, n_total=None,
                          ted_S0=0.0, ted_tau_s=None,
                          oed_boost=0.0, n_steps=2000, reflecting=True):
    """Extends process.diffuse_numeric with extrinsic-doping, TED, and OED
    diffusivity enhancement.

    Falls back to process.diffuse_numeric EXACTLY (same code path, same
    arithmetic) when no enhancement is requested (n_total is None,
    ted_S0 == 0, oed_boost == 0) -- this is what makes the "intrinsic
    limit reduces to the current constant-D model" gate a structural
    guarantee rather than a numerical coincidence.

    n_total     : None, or (len(x),) local total carrier concentration
                  [cm^-3] used for the extrinsic-enhancement factor.
    ted_S0      : initial TED supersaturation (see ted_plus_one_S0);
                  0 disables TED.
    ted_tau_s   : TED decay time constant [s]; required if ted_S0 != 0.
    oed_boost   : constant OED multiplicative boost (see oed_enhancement);
                  0 disables OED.
    """
    if n_total is None and ted_S0 == 0.0 and oed_boost == 0.0:
        return process.diffuse_numeric(x, C, species, T_C, t_s, n_steps, reflecting)

    x = np.asarray(x, dtype=float)
    C = np.asarray(C, dtype=float).copy()
    Di = process.diffusivity(species, T_C)

    extrinsic = (extrinsic_enhancement(species, n_total, T_C)
                 if n_total is not None else np.ones_like(x))

    h = np.diff(x)
    # Conservative dt bound using the worst-case (t=0) enhancement, since
    # the extrinsic factor is time-independent and TED/OED only decay/
    # stay constant -- so this bound is stable for the whole run.
    D_worst = Di * extrinsic.max() * (1.0 + ted_S0 + oed_boost)
    dt_max = 0.4 * h.min() ** 2 / max(D_worst, 1e-300)
    n_steps = max(n_steps, int(np.ceil(t_s / dt_max)))
    dt = t_s / n_steps

    xm = 0.5 * (x[:-1] + x[1:])
    dV = np.empty_like(x)
    dV[1:-1] = xm[1:] - xm[:-1]
    dV[0] = xm[0] - x[0]
    dV[-1] = x[-1] - xm[-1]

    t = 0.0
    for _ in range(n_steps):
        S_ted = ted_supersaturation(t, ted_S0, ted_tau_s) if ted_S0 != 0.0 else 0.0
        D_node = Di * extrinsic * (1.0 + S_ted + oed_boost)
        D_face = 0.5 * (D_node[:-1] + D_node[1:])   # arithmetic mean at interfaces
        flux = -D_face * np.diff(C) / h
        dC = np.zeros_like(C)
        dC[1:-1] = -(flux[1:] - flux[:-1]) / dV[1:-1]
        dC[0] = -flux[0] / dV[0] if reflecting else 0.0
        dC[-1] = flux[-1] / dV[-1]
        C = C + dt * dC
        if not reflecting:
            C[0] = 0.0
        t += dt
    return C


# ----------------------------------------------------------------------
#  Solid solubility and clustering
# ----------------------------------------------------------------------
# Approximate solid solubility in silicon [cm^-3] at representative anneal
# temperatures, to the nearest half-decade from Trumbore-style solubility
# curves. This is deliberately coarse -- see docstring below.
_SOLUBILITY_1000C = {"B": 4e20, "P": 1e21, "As": 2e21, "Sb": 4e20}


def solid_solubility(species, T_C, T_ref_C=1000.0):
    """Approximate solid solubility [cm^-3] in silicon.

    Uses the ~1000 C literature value and a fixed exp(-Ea/kT)-shaped
    temperature roll-off with Ea = 0.5 eV (a generic activation energy
    for solubility retrograde behavior, not species-fitted) to give a
    monotonic, physically-reasonable trend with temperature. This is
    accurate to at best a factor of 2-3 versus a real Trumbore-style
    curve -- good enough to gate "is clustering active at all" in a
    process flow, not for a solubility-limited-anneal design.
    """
    if species not in _SOLUBILITY_1000C:
        raise KeyError(f"No solubility data for '{species}'. "
                        f"Available: {list(_SOLUBILITY_1000C)}")
    Cs_ref = _SOLUBILITY_1000C[species]
    Ea = 0.5
    Tref = T_ref_C + 273.15
    T = np.asarray(T_C, dtype=float) + 273.15
    return Cs_ref * np.exp(-Ea / KB_EV * (1.0 / T - 1.0 / Tref))


def apply_clustering(C_total, species, T_C):
    """Split a total dopant concentration into (active, clustered),
    active = min(total, solid_solubility), clustered = total - active.

    Conserves active + clustered == C_total exactly (to floating-point
    subtraction precision) by construction -- there is no separate
    clustering-reaction integration to introduce drift.
    """
    C_total = np.asarray(C_total, dtype=float)
    Cs = solid_solubility(species, T_C)
    active = np.minimum(C_total, Cs)
    clustered = C_total - active
    return active, clustered


# ----------------------------------------------------------------------
#  Segregation (equilibrium partition at a fixed interface slab)
# ----------------------------------------------------------------------
def segregation_partition(Q_areal_cm2, m, thickness_si_cm, thickness_ox_cm):
    """Equilibrium segregation split of an areal dose Q [cm^-2] held in a
    thin slab straddling a Si/SiO2 interface, with segregation
    coefficient m = C_si / C_ox (m < 1: dopant prefers oxide, e.g. boron;
    m >> 1: dopant prefers silicon, e.g. phosphorus/arsenic pileup).

    Solves the two equations
        C_si * thickness_si + C_ox * thickness_ox = Q_areal   (conservation)
        C_si = m * C_ox                                       (segregation)
    for (C_si, C_ox) in cm^-3.
    """
    denom = m * thickness_si_cm + thickness_ox_cm
    C_ox = Q_areal_cm2 / denom
    C_si = m * C_ox
    return C_si, C_ox
