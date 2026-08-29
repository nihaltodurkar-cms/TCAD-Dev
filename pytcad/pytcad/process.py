"""Process simulation: implantation, diffusion, oxidation.

This is the "process TCAD" half -- it produces the doping profile that the
device solver then consumes, exactly as Sentaurus Process feeds Sentaurus
Device.

IMPORTANT ACCURACY NOTE
-----------------------
The implant range tables below are approximate LSS/Pearson moments for
amorphous silicon.  They are good to roughly 5-10% for the listed
species/energies and are fine for building a device structure or for
teaching, but they do NOT capture ion channelling, which in crystalline
silicon can put a tail one to two orders of magnitude deeper than the
Gaussian predicts.  For anything going into a real process flow, get the
moments from SRIM/TRIM or from a calibrated Monte-Carlo implanter.
"""

import numpy as np
from scipy.special import erfc

from .constants import KB_EV

# ----------------------------------------------------------------------
#  Implantation
# ----------------------------------------------------------------------
# Approximate moments in amorphous Si: energy [keV] -> (Rp [cm], dRp [cm])
_IMPLANT_TABLE = {
    "B":  {10: (33.3e-7, 17.1e-7), 20: (66.0e-7, 28.0e-7),
           30: (100.0e-7, 38.0e-7), 50: (160.0e-7, 54.0e-7),
           70: (220.0e-7, 68.0e-7), 100: (300.0e-7, 85.0e-7),
           150: (430.0e-7, 110.0e-7), 200: (530.0e-7, 130.0e-7)},
    "P":  {10: (13.5e-7, 6.5e-7), 20: (25.5e-7, 11.0e-7),
           30: (38.0e-7, 15.0e-7), 50: (62.0e-7, 22.0e-7),
           70: (86.0e-7, 29.0e-7), 100: (123.0e-7, 38.0e-7),
           150: (180.0e-7, 50.0e-7), 200: (240.0e-7, 62.0e-7)},
    "As": {10: (9.0e-7, 3.5e-7), 20: (15.5e-7, 5.6e-7),
           30: (22.0e-7, 7.5e-7), 50: (33.0e-7, 11.0e-7),
           70: (44.0e-7, 14.0e-7), 100: (60.0e-7, 18.0e-7),
           150: (85.0e-7, 24.0e-7), 200: (110.0e-7, 30.0e-7)},
}

DOPANT_TYPE = {"B": -1, "In": -1, "P": +1, "As": +1, "Sb": +1}


def implant_moments(species, energy_keV):
    """Log-log interpolated projected range Rp and straggle dRp [cm]."""
    if species not in _IMPLANT_TABLE:
        raise KeyError(f"No implant data for '{species}'. "
                       f"Available: {list(_IMPLANT_TABLE)}")
    tab = _IMPLANT_TABLE[species]
    E = np.array(sorted(tab))
    Rp = np.array([tab[e][0] for e in E])
    dRp = np.array([tab[e][1] for e in E])
    lo, hi = E.min(), E.max()
    if not (lo <= energy_keV <= hi):
        raise ValueError(f"Energy {energy_keV} keV outside tabulated range "
                         f"{lo}-{hi} keV for {species}.")
    lE = np.log(energy_keV)
    return (float(np.exp(np.interp(lE, np.log(E), np.log(Rp)))),
            float(np.exp(np.interp(lE, np.log(E), np.log(dRp)))))


def implant(x, species, energy_keV, dose, tilt_deg=0.0, Rp=None, dRp=None):
    """Gaussian implant profile [cm^-3] on the mesh x [cm].

        C(x) = Q / (sqrt(2 pi) dRp) exp[ -(x - Rp)^2 / (2 dRp^2) ]

    Q is the dose [cm^-2].  The prefactor is fixed by requiring the integral
    of C over all depth to equal Q -- ignoring backscattered loss, which is
    < 1% for light ions in Si but not for heavy ions at low energy.

    Tilt scales the projected range by cos(tilt), a first-order correction
    only.  Pass Rp/dRp explicitly to override the table with SRIM values.
    """
    if Rp is None or dRp is None:
        Rp, dRp = implant_moments(species, energy_keV)
    Rp = Rp * np.cos(np.deg2rad(tilt_deg))
    x = np.asarray(x, dtype=float)
    C = dose / (np.sqrt(2.0 * np.pi) * dRp) * np.exp(
        -((x - Rp) ** 2) / (2.0 * dRp**2))
    return C


def implant_pearson4_skewed(x, dose, Rp, dRp, gamma):
    """Skewed profile via a two-sided Gaussian (a cheap Pearson-IV stand-in).

    gamma > 0 stretches the deep side (channelling-like tail).  A genuine
    Pearson-IV needs the kurtosis too; this is a pragmatic approximation for
    reproducing an asymmetric SIMS profile when you only have the skewness.
    """
    x = np.asarray(x, dtype=float)
    s_deep = dRp * (1.0 + max(gamma, 0.0))
    s_shal = dRp * (1.0 + max(-gamma, 0.0))
    sig = np.where(x >= Rp, s_deep, s_shal)
    C = np.exp(-((x - Rp) ** 2) / (2.0 * sig**2))
    norm = np.trapezoid(C, x)
    return C * dose / max(norm, 1e-300)


# ----------------------------------------------------------------------
#  Diffusion
# ----------------------------------------------------------------------
# Intrinsic diffusivity: D = D0 exp(-Ea/kT).  D0 [cm^2/s], Ea [eV].
DIFFUSIVITY = {
    "B":  (0.76, 3.46),
    "P":  (3.85, 3.66),
    "As": (0.066, 3.44),
    "Sb": (0.214, 3.65),
}


def diffusivity(species, T_C):
    """Intrinsic dopant diffusivity in Si [cm^2/s] at temperature T [degC].

    Arrhenius fit to tracer-diffusion data.  It ignores the extrinsic
    enhancement that occurs when the doping exceeds n_i(T) (charged-defect
    assisted diffusion), and it ignores transient enhanced diffusion after
    implant damage -- the two effects that dominate real junction formation
    below 1000 degC.
    """
    D0, Ea = DIFFUSIVITY[species]
    T = T_C + 273.15
    return D0 * np.exp(-Ea / (KB_EV * T))


def diffuse_predep_erfc(x, species, T_C, t_s, Csurf):
    """Constant-source (pre-deposition) diffusion, analytic:

        C(x,t) = C_s erfc( x / (2 sqrt(D t)) )

    Exact solution of Fick's second law with a fixed surface concentration
    and a semi-infinite substrate.  Dose delivered = 2 C_s sqrt(Dt/pi).
    """
    D = diffusivity(species, T_C)
    return Csurf * erfc(np.asarray(x, float) / (2.0 * np.sqrt(D * t_s)))


def diffuse_drivein_gaussian(x, species, T_C, t_s, dose):
    """Limited-source (drive-in) diffusion from a delta function at x = 0:

        C(x,t) = Q / sqrt(pi D t) exp( -x^2 / (4 D t) )

    Valid once sqrt(4Dt) greatly exceeds the initial profile width.
    """
    D = diffusivity(species, T_C)
    return dose / np.sqrt(np.pi * D * t_s) * np.exp(
        -np.asarray(x, float) ** 2 / (4.0 * D * t_s))


def diffuse_numeric(x, C, species, T_C, t_s, n_steps=2000,
                    reflecting=True):
    """Numerically diffuse an arbitrary starting profile.

    Solves dC/dt = d/dx (D dC/dx) with a Crank-Nicolson-free explicit scheme
    guarded by the stability condition dt <= h^2 / (2D).  Constant D.
    Boundary: reflecting at x=0 (dopant does not leave the wafer) or
    absorbing (segregation into a growing oxide, crudely).

    This is the routine to use after an implant, since the starting profile
    is Gaussian rather than a delta function and the analytic solutions do
    not apply.
    """
    x = np.asarray(x, float)
    C = np.asarray(C, float).copy()
    D = diffusivity(species, T_C)
    h = np.diff(x)
    dt_max = 0.4 * h.min() ** 2 / D
    n_steps = max(n_steps, int(np.ceil(t_s / dt_max)))
    dt = t_s / n_steps

    xm = 0.5 * (x[:-1] + x[1:])
    dV = np.empty_like(x)
    dV[1:-1] = xm[1:] - xm[:-1]
    dV[0] = xm[0] - x[0]
    dV[-1] = x[-1] - xm[-1]

    for _ in range(n_steps):
        flux = -D * np.diff(C) / h          # flux on interfaces
        dC = np.zeros_like(C)
        dC[1:-1] = -(flux[1:] - flux[:-1]) / dV[1:-1]
        dC[0] = -flux[0] / dV[0] if reflecting else 0.0
        dC[-1] = flux[-1] / dV[-1]
        C = C + dt * dC
        if not reflecting:
            C[0] = 0.0
    return C


def junction_depth(x, net_doping):
    """Depth [cm] where the net doping changes sign (linear interpolation)."""
    s = np.sign(net_doping)
    idx = np.where(np.diff(s) != 0)[0]
    out = []
    for i in idx:
        f = net_doping[i] / (net_doping[i] - net_doping[i + 1])
        out.append(x[i] + f * (x[i + 1] - x[i]))
    return np.array(out)


# ----------------------------------------------------------------------
#  Thermal oxidation (Deal-Grove)
# ----------------------------------------------------------------------
# (B [um^2/h] prefactor, Ea [eV]) and (B/A [um/h] prefactor, Ea [eV]), Si <100>
_DEAL_GROVE = {
    "dry": {"B": (7.72e2, 1.23), "BA": (6.23e6, 2.00), "xi": 0.0025},
    "wet": {"B": (3.86e2, 0.78), "BA": (1.63e8, 2.05), "xi": 0.0},
}


def deal_grove_coefficients(T_C, ambient="dry"):
    """Linear and parabolic rate constants (B/A [um/h], B [um^2/h])."""
    p = _DEAL_GROVE[ambient]
    T = T_C + 273.15
    B = p["B"][0] * np.exp(-p["B"][1] / (KB_EV * T))
    BA = p["BA"][0] * np.exp(-p["BA"][1] / (KB_EV * T))
    return BA, B


def oxide_thickness(T_C, t_hours, ambient="dry", x_init_um=None):
    """Deal-Grove oxide thickness [um].

        x^2 + A x = B (t + tau),   tau = (x_i^2 + A x_i)/B

    solved as   x = (A/2) [ sqrt(1 + 4B(t+tau)/A^2) - 1 ].

    Physics: A/B is set by interface-reaction-limited growth (thin oxides),
    B by oxidant diffusion through the grown oxide (thick oxides).  The
    model famously under-predicts DRY oxide growth below ~30 nm, which is
    why x_i ~ 25 nm is used as a fitting fudge for the dry case -- that is a
    fit, not physics.
    """
    p = _DEAL_GROVE[ambient]
    BA, B = deal_grove_coefficients(T_C, ambient)
    A = B / BA
    xi = p["xi"] if x_init_um is None else x_init_um
    tau = (xi**2 + A * xi) / B
    return 0.5 * A * (np.sqrt(1.0 + 4.0 * B * (t_hours + tau) / A**2) - 1.0)


def silicon_consumed(x_ox_um):
    """Silicon thickness consumed by oxidation [um]: 0.44 x_ox.

    From the molar volumes: growing 1 um of SiO2 eats 0.44 um of Si, so the
    original surface ends up 0.44 x_ox below the new one.  This matters for
    implant depth bookkeeping after a LOCOS or sacrificial oxide step.
    """
    return 0.44 * np.asarray(x_ox_um, dtype=float)
