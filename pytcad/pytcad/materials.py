"""Material and physical models for PyTCAD.

Every model below is an EMPIRICAL FIT to experiment unless stated otherwise.
Where a parameter comes from a fit, the source class is noted in the docstring
so you always know what is theory and what is curve-fitting.
"""

from dataclasses import dataclass, field
import numpy as np

from .constants import KB_EV


# ----------------------------------------------------------------------
#  Material definition
# ----------------------------------------------------------------------
@dataclass
class Semiconductor:
    """Bulk semiconductor parameter set.

    Defaults are silicon.  Parameter provenance:
      eps_r, Eg, Nc300, Nv300   : measured / band-structure
      mobility parameters       : Caughey-Thomas empirical fit
      lifetime parameters       : Scharfetter empirical fit
      Auger coefficients        : measured (Dziewior & Schmid)
    """

    name: str = "Silicon"
    eps_r: float = 11.7                # relative permittivity
    chi: float = 4.05                  # electron affinity [eV]

    # --- band structure (Varshni) ---
    Eg0: float = 1.1700                # Eg(0 K) [eV]
    varshni_alpha: float = 4.730e-4    # [eV/K]
    varshni_beta: float = 636.0        # [K]
    Nc300: float = 2.86e19             # conduction band DOS at 300 K [cm^-3]
    Nv300: float = 3.10e19             # valence band DOS at 300 K [cm^-3]

    # --- Caughey-Thomas mobility (300 K, silicon) ---
    mu_n_min: float = 92.0             # [cm^2/V/s]
    mu_n_max: float = 1360.0
    mu_n_Nref: float = 1.3e17          # [cm^-3]
    mu_n_alpha: float = 0.91
    mu_n_Texp: float = -2.33           # temperature exponent on mu_max

    mu_p_min: float = 47.7
    mu_p_max: float = 495.0
    mu_p_Nref: float = 6.3e16
    mu_p_alpha: float = 0.76
    mu_p_Texp: float = -2.23

    # --- velocity saturation (Canali) ---
    vsat_n: float = 1.07e7             # [cm/s]
    vsat_p: float = 8.37e6
    beta_n: float = 2.0
    beta_p: float = 1.0

    # --- SRH lifetimes (Scharfetter fit) ---
    tau_n0: float = 1.0e-5             # [s]
    tau_p0: float = 3.0e-6
    tau_Nref: float = 5.0e16           # [cm^-3]

    # --- Auger ---
    Cn_auger: float = 2.8e-31          # [cm^6/s]
    Cp_auger: float = 9.9e-32

    # --- Slotboom bandgap narrowing ---
    bgn_E0: float = 6.92e-3            # [eV]
    bgn_N0: float = 1.3e17             # [cm^-3]

    # --- carrier effective masses (M12-S3 density-gradient prereq) ---
    # conductivity effective masses, in units of m0.  Unused by any
    # solver yet -- prerequisites for the density-gradient quantum
    # correction and tunneling kappa evaluations.
    m_n_star: float = 0.26             # electrons (Si)
    m_p_star: float = 0.386            # holes (Si)

    def Eg(self, T: float) -> float:
        """Varshni temperature dependence of the bandgap [eV].

        Eg(T) = Eg(0) - alpha T^2 / (T + beta)
        Empirical, but reproduces Si to within ~1 meV over 0-500 K.
        """
        return self.Eg0 - self.varshni_alpha * T**2 / (T + self.varshni_beta)

    def Nc(self, T: float) -> float:
        return self.Nc300 * (T / 300.0) ** 1.5

    def Nv(self, T: float) -> float:
        return self.Nv300 * (T / 300.0) ** 1.5

    def ni(self, T: float) -> float:
        """Intrinsic carrier concentration [cm^-3], non-degenerate limit.

            n_i = sqrt(Nc Nv) exp(-Eg / 2kT)

        This is exact within Boltzmann statistics; it fails for degenerate
        doping (> ~1e19 cm^-3) where Fermi-Dirac statistics are required.
        """
        return np.sqrt(self.Nc(T) * self.Nv(T)) * np.exp(
            -self.Eg(T) / (2.0 * KB_EV * T)
        )


SILICON = Semiconductor()


# ---------------------------------------------------------------------------
# Additional bulk parameter sets (M11-S1).  These make materials KNOWN to
# validation and the catalog; they do NOT make them solvable -- Device1D/2D/3D
# assemblies are silicon-only until the M11-S3 heterojunction core lands.
# Provenance per set: handbook band parameters (Adachi, "Properties of
# Semiconductor Alloys"); mobility/Auger/lifetime numbers are empirical fits
# with typical +-10..30% literature spread, stated rather than hidden.
# ---------------------------------------------------------------------------
GE = Semiconductor(
    name="Germanium",
    eps_r=16.2,
    chi=4.13,
    Eg0=0.744, varshni_alpha=4.774e-4, varshni_beta=235.0,
    Nc300=1.04e19, Nv300=6.0e18,
    mu_n_min=0.0, mu_n_max=3900.0, mu_n_Nref=1.3e17, mu_n_alpha=0.91,
    mu_n_Texp=-2.33,
    mu_p_min=0.0, mu_p_max=1900.0, mu_p_Nref=6.3e16, mu_p_alpha=0.76,
    mu_p_Texp=-2.23,
    vsat_n=7.0e6, vsat_p=6.3e6,
    Cn_auger=2.8e-31, Cp_auger=9.9e-32,
)

GAAS = Semiconductor(
    name="Gallium arsenide",
    eps_r=12.9,
    chi=4.07,
    Eg0=1.519, varshni_alpha=5.405e-4, varshni_beta=204.0,   # Gamma valley
    Nc300=4.7e17, Nv300=7.0e18,
    mu_n_min=0.0, mu_n_max=8500.0, mu_n_Nref=1.3e17, mu_n_alpha=0.91,
    mu_n_Texp=-2.33,
    mu_p_min=0.0, mu_p_max=400.0, mu_p_Nref=6.3e16, mu_p_alpha=0.76,
    mu_p_Texp=-2.23,
    vsat_n=1.2e7, vsat_p=9.0e6,
    Cn_auger=1.0e-30, Cp_auger=1.0e-31,
)

INGAAS = Semiconductor(
    # In0.53Ga0.47As lattice-matched to InP
    name="In0.53Ga0.47As",
    eps_r=13.9,
    chi=4.55,
    Eg0=0.817, varshni_alpha=5.78e-4, varshni_beta=296.0,
    Nc300=2.1e17, Nv300=7.7e18,
    mu_n_min=0.0, mu_n_max=12000.0, mu_n_Nref=1.3e17, mu_n_alpha=0.91,
    mu_n_Texp=-2.33,
    mu_p_min=0.0, mu_p_max=300.0, mu_p_Nref=6.3e16, mu_p_alpha=0.76,
    mu_p_Texp=-2.23,
    vsat_n=1.0e7, vsat_p=8.0e6,
    Cn_auger=1.0e-30, Cp_auger=1.0e-31,
)


def algaas(x):
    """Al_x Ga_{1-x} As parameter family (direct-gap regime, x <= 0.45).

    Linear interpolation of eps_r / chi between GaAs and AlAs; direct-gap
    Varshni Eg0(x) = 1.519 + 1.247*x [eV] below the X-crossing.  Above
    x=0.45 the gap becomes indirect -- raise instead of silently solving
    the wrong band structure."""
    if not 0.0 <= x <= 0.45:
        raise ValueError(
            f"AlGaAs mole fraction x={x} outside the direct-gap regime "
            "(x <= 0.45); indirect-gap sets are not provided")
    return Semiconductor(
        name=f"Al{x:.2f}Ga{1 - x:.2f}As",
        eps_r=12.9 - 2.6 * x,          # linear: GaAs 12.9 -> AlAs 10.3
        chi=4.07 - 0.85 * x,           # conduction-band offset ~85% of dEg
        Eg0=1.519 + 1.247 * x,
        varshni_alpha=5.405e-4, varshni_beta=204.0,
        Nc300=4.7e17 * (1.0 + 0.5 * x),   # crude DOS scaling, stated honestly
        Nv300=7.0e18 * (1.0 - 0.3 * x),
        mu_n_max=8500.0 - 5500.0 * x,
        mu_p_max=400.0 - 150.0 * x,
    )


# ----------------------------------------------------------------------
#  Mobility
# ----------------------------------------------------------------------
def mobility_caughey_thomas(N, mat: Semiconductor, T: float, carrier: str):
    """Doping-dependent low-field mobility [cm^2/V/s].

        mu(N) = mu_min + (mu_max - mu_min) / (1 + (N/N_ref)^alpha)

    N is the TOTAL ionised impurity concentration N_A + N_D (not the net
    doping) -- this is a common bug: using |N_D - N_A| overestimates the
    mobility badly in compensated regions.

    Purely empirical (Caughey & Thomas, Proc. IEEE 55, 2192 (1967)).
    Typical Si values at 300 K: mu_n ~ 1360 (intrinsic) -> ~270 at 1e18.
    """
    N = np.maximum(np.asarray(N, dtype=float), 1.0)
    if carrier == "n":
        mu_max = mat.mu_n_max * (T / 300.0) ** mat.mu_n_Texp
        mu_min, Nref, a = mat.mu_n_min, mat.mu_n_Nref, mat.mu_n_alpha
    else:
        mu_max = mat.mu_p_max * (T / 300.0) ** mat.mu_p_Texp
        mu_min, Nref, a = mat.mu_p_min, mat.mu_p_Nref, mat.mu_p_alpha
    return mu_min + (mu_max - mu_min) / (1.0 + (N / Nref) ** a)


def mobility_field(mu0, E, mat: Semiconductor, carrier: str):
    """Canali velocity-saturation model.

        mu(E) = mu0 / [1 + (mu0 |E| / v_sat)^beta]^(1/beta)

    E is the driving field parallel to the current [V/cm].  Reduces to mu0
    for mu0|E| << v_sat.  This is applied LAGGED in the Newton loop (mu is
    frozen at the previous iterate), which costs some quadratic convergence
    but keeps the Jacobian sparse and simple.
    """
    vsat = mat.vsat_n if carrier == "n" else mat.vsat_p
    beta = mat.beta_n if carrier == "n" else mat.beta_p
    x = mu0 * np.abs(E) / vsat
    return mu0 / (1.0 + x**beta) ** (1.0 / beta)


# ----------------------------------------------------------------------
#  Bandgap narrowing
# ----------------------------------------------------------------------
def bandgap_narrowing_slotboom(N, mat: Semiconductor):
    """Slotboom / de Graaff heavy-doping bandgap narrowing, dEg [eV].

        dEg = E0 [ ln(N/N0) + sqrt( ln^2(N/N0) + 1/2 ) ]

    Empirical fit to bipolar transistor data.  Set to zero below N0.
    Effect: n_ie^2 = n_i^2 exp(dEg / kT), which enhances minority-carrier
    injection from heavily doped emitters -- the dominant reason real BJT
    gains fall short of the ideal-diode prediction.
    """
    N = np.maximum(np.asarray(N, dtype=float), 1.0)
    x = np.log(N / mat.bgn_N0)
    dEg = mat.bgn_E0 * (x + np.sqrt(x * x + 0.5))
    return np.where(N > mat.bgn_N0, dEg, 0.0)


def nie_effective(N, mat: Semiconductor, T: float, use_bgn: bool = True):
    """Effective intrinsic concentration including bandgap narrowing."""
    ni = mat.ni(T)
    if not use_bgn:
        return np.full_like(np.asarray(N, dtype=float), ni)
    dEg = bandgap_narrowing_slotboom(N, mat)
    return ni * np.exp(dEg / (2.0 * KB_EV * T))


# ----------------------------------------------------------------------
#  Lifetimes and recombination
# ----------------------------------------------------------------------
def lifetime_scharfetter(N, tau0, Nref):
    """Doping-dependent SRH lifetime [s]:  tau = tau0 / (1 + N/N_ref)."""
    N = np.maximum(np.asarray(N, dtype=float), 1.0)
    return tau0 / (1.0 + N / Nref)


def recombination(n, p, nie, tau_n, tau_p, mat: Semiconductor,
                  auger: bool = True):
    """Net recombination rate R [cm^-3 s^-1] and its derivatives dR/dn, dR/dp.

    SRH with mid-gap traps (n1 = p1 = n_ie):

        R_SRH = (np - n_ie^2) / [ tau_p (n + n_ie) + tau_n (p + n_ie) ]

    Auger:

        R_Aug = (C_n n + C_p p) (np - n_ie^2)

    Both vanish at equilibrium (np = n_ie^2) as they must.  Returned
    derivatives are exact and feed the Newton Jacobian.
    """
    ni2 = nie * nie
    excess = n * p - ni2

    den = tau_p * (n + nie) + tau_n * (p + nie)
    R = excess / den
    dRdn = (p * den - excess * tau_p) / den**2
    dRdp = (n * den - excess * tau_n) / den**2

    if auger:
        C = mat.Cn_auger * n + mat.Cp_auger * p
        R = R + C * excess
        dRdn = dRdn + mat.Cn_auger * excess + C * p
        dRdp = dRdp + mat.Cp_auger * excess + C * n

    return R, dRdn, dRdp
