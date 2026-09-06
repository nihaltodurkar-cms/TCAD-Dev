"""M28 -- Schottky / tunnel contacts + gate stacks.

Scope (ARCHITECTURE.md M28): Schottky boundary condition (thermionic
emission + image-force barrier lowering, Richardson-constant benchmark),
a disclosed-approximation tunnel-contact boundary condition for
degenerately-doped "ohmic" contacts (Padovani-Stratton field-emission
limit), and barrier-height / work-function bookkeeping for metal-
semiconductor and gate-stack junctions.

Fixed charge / work-function engineering *in MOS gate stacks* already
has a home: ``pytcad.moscap.flatband_voltage`` (V_FB = phi_ms - Q_f/C_ox)
was built for M-earlier work and is not duplicated here -- this module
adds the metal-semiconductor (Schottky) contact physics that was
actually missing, plus a shared ``schottky_barrier_height_n/p`` helper
that both a bare Schottky diode and a MOS gate stack can use to get
phi_m.

HONESTY CLAUSE -- what this module does and does not model:

  * Thermionic emission (``thermionic_current_density``) is the
    standard ideal-diode Richardson-Dushman/Bethe form
    J = A* T^2 exp(-phi_B/kT) [exp(qV/(n kT)) - 1]. The Richardson
    constant A* is NOT derived from the material's conductivity
    effective mass (that would be wrong for Si's multi-valley band
    structure -- the DOS-effective mass relevant to A* differs from the
    conductivity mass already stored on ``Semiconductor``); instead
    published effective values are used directly
    (``RICHARDSON_A_STAR_TABLE``, Sze & Ng). ``richardson_constant_A0``
    is the free-electron constant, derived here from fundamental
    constants and used only as the textbook benchmark number, not as a
    per-material A*.
  * Image-force barrier lowering uses the classical
    Delta_phi = sqrt(q E_max / (4 pi eps_s)) result with E_max taken
    from a one-sided abrupt-junction depletion approximation (same
    level of approximation as the depletion-approximation formulas used
    throughout the rest of pytcad). It ignores the (small, well known)
    correction from the image-force potential's own distortion of the
    field profile near the interface.
  * The tunnel-contact / field-emission current
    (``field_emission_current_density``) is the Padovani-Stratton pure
    field-emission LIMIT formula, valid when E00 >> kT (heavily doped
    contacts, the regime it is meant for -- degenerate "ohmic" tunnel
    contacts). It is NOT the full thermionic-field-emission (TFE)
    integral that covers the crossover regime; ``contact_regime``
    reports which of the three qualitative regimes (TE / TFE / FE)
    a given E00, T falls into, and callers should only trust the FE
    formula's numbers deep in the FE regime (E00/kT >~ 2-3).
  * There is no self-consistent coupling into Device1D/Device2D's
    Newton solve here -- this module computes contact I-V and barrier
    physics standalone, the same "gated standalone module" pattern used
    for M23/M24/M25, not a live Jacobian stamp. Wiring a Schottky BC
    into the transport Jacobian is future work if/when a device needs
    it self-consistently.

References: Sze & Ng, "Physics of Semiconductor Devices", 3rd ed.,
ch. 3 (thermionic emission, image-force lowering, Richardson constants
Table 3.4-ish, Padovani-Stratton field emission); Padovani & Stratton,
Solid-State Electronics 9, 695 (1966) (E00, FE/TFE/TE regimes).
"""

import numpy as np

from .constants import Q, KB, KB_EV, EPS0

# ----------------------------------------------------------------------
# Richardson constant
# ----------------------------------------------------------------------

def richardson_constant_A0() -> float:
    """Free-electron Richardson constant [A/(cm^2 K^2)], derived from
    fundamental constants: A0 = 4 pi q m0 kB^2 / h^3. Published value is
    120.173 A/(cm^2 K^2) (Sze & Ng); this is a self-check, not a fit."""
    from .constants import M0
    h = 2.0 * np.pi * 1.054571817e-34  # Planck constant [J s]
    A0_SI = 4.0 * np.pi * Q * M0 * KB**2 / h**3   # A/(m^2 K^2)
    return A0_SI * 1e-4                            # -> A/(cm^2 K^2)


# Published effective Richardson constants [A/(cm^2 K^2)] -- these are
# NOT A0 * (conductivity effective mass), they are measured/tabulated
# per Sze & Ng because A* depends on the DOS effective mass along the
# transport direction for each conduction-band valley, which is not the
# same parameter as the conductivity mass already on Semiconductor.
RICHARDSON_A_STAR_TABLE = {
    ("Si", "n"): 252.0,
    ("Si", "p"): 32.0,
    ("Ge", "n"): 143.0,
    ("Ge", "p"): 41.0,
    ("GaAs", "n"): 8.0,
    ("GaAs", "p"): 74.0,
}


def richardson_a_star(material_name: str, carrier: str) -> float:
    """Published effective Richardson constant [A/(cm^2 K^2)] for
    (material_name, carrier in {'n','p'}). Raises KeyError if unknown --
    callers must supply A_star explicitly for materials not tabulated."""
    return RICHARDSON_A_STAR_TABLE[(material_name, carrier)]


# ----------------------------------------------------------------------
# Barrier height (Schottky-Mott rule)
# ----------------------------------------------------------------------

def schottky_barrier_height_n(phi_metal_eV: float, chi_semi_eV: float) -> float:
    """Ideal (Schottky-Mott) n-type barrier height [eV]: phi_Bn = phi_m - chi.
    Real interfaces show Fermi-level pinning that this ignores -- see the
    module honesty clause; this is the textbook zero-pinning limit."""
    return phi_metal_eV - chi_semi_eV


def schottky_barrier_height_p(phi_metal_eV: float, chi_semi_eV: float, Eg_eV: float) -> float:
    """Ideal p-type barrier height [eV]: phi_Bp = Eg - (phi_m - chi), the
    complementary barrier such that phi_Bn + phi_Bp = Eg on the same
    junction (Sze & Ng eq. 3.2)."""
    return Eg_eV - schottky_barrier_height_n(phi_metal_eV, chi_semi_eV)


# ----------------------------------------------------------------------
# One-sided abrupt-junction depletion approximation (for E_max, W)
# ----------------------------------------------------------------------

def schottky_max_field(Nd_cm3: float, Vbi_eV: float, V: float, eps_r: float) -> float:
    """Maximum (interface) field [V/cm] in the semiconductor depletion
    region of a Schottky contact under bias V [V] (forward positive),
    one-sided abrupt-junction depletion approximation:
        E_max = sqrt(2 q Nd (Vbi - V) / eps_s),   eps_s = eps_r * eps0.
    Clipped at V = Vbi (flat-band) so the field never goes imaginary
    right at/above the ideal built-in voltage."""
    eps_s = eps_r * EPS0
    Vd = max(Vbi_eV - V, 1e-6)
    return np.sqrt(2.0 * Q * Nd_cm3 * Vd / eps_s)


def image_force_lowering_eV(E_max_V_per_cm: float, eps_r: float) -> float:
    """Image-force barrier lowering [eV]: Delta_phi = sqrt(q E_max /
    (4 pi eps_s)), the classical Schottky-effect result (Sze & Ng eq.
    3.5-3.6)."""
    eps_s = eps_r * EPS0
    return np.sqrt(Q * np.abs(E_max_V_per_cm) / (4.0 * np.pi * eps_s))


# ----------------------------------------------------------------------
# Thermionic emission I-V
# ----------------------------------------------------------------------

def thermionic_current_density(phi_B_eV: float, T: float, V, A_star: float,
                                n_ideality: float = 1.0):
    """Ideal thermionic-emission current density [A/cm^2] at bias V [V]
    (forward positive), Richardson-Dushman/Bethe diode equation:
        J = A* T^2 exp(-phi_B/kT) [exp(qV/(n kT)) - 1].
    V may be a scalar or ndarray."""
    Vt = KB * T / Q
    J0 = A_star * T**2 * np.exp(-phi_B_eV / (KB_EV * T))
    return J0 * (np.exp(np.asarray(V, dtype=float) / (n_ideality * Vt)) - 1.0)


def schottky_iv(phi_B0_eV: float, T: float, V, A_star: float,
                 Nd_cm3: float = None, eps_r: float = None,
                 image_force: bool = True, n_ideality: float = 1.0):
    """Schottky-diode I-V [A/cm^2] including bias-dependent image-force
    barrier lowering when Nd_cm3/eps_r are given (each bias point uses
    its own depletion-approximation E_max -- a common quasi-static
    treatment, not a fully self-consistent Poisson solve). Falls back to
    the fixed-barrier thermionic-emission curve when Nd_cm3 or eps_r is
    None, or when image_force=False."""
    V = np.atleast_1d(np.asarray(V, dtype=float))
    if image_force and Nd_cm3 is not None and eps_r is not None:
        Vbi_eV = phi_B0_eV  # ideal Schottky-Mott limit: Vbi ~= phi_Bn (n-type, non-degenerate)
        phi_B_eff = np.empty_like(V)
        for i, v in enumerate(V):
            Emax = schottky_max_field(Nd_cm3, Vbi_eV, v, eps_r)
            phi_B_eff[i] = phi_B0_eV - image_force_lowering_eV(Emax, eps_r)
        J0 = A_star * T**2 * np.exp(-phi_B_eff / (KB_EV * T))
        Vt = KB * T / Q
        J = J0 * (np.exp(V / (n_ideality * Vt)) - 1.0)
    else:
        J = thermionic_current_density(phi_B0_eV, T, V, A_star, n_ideality)
    return J if J.shape != (1,) else float(J[0])


# ----------------------------------------------------------------------
# Tunnel ("ohmic") contact -- Padovani-Stratton field-emission limit
# ----------------------------------------------------------------------

def characteristic_tunneling_energy_E00_eV(Nd_cm3: float, m_eff_ratio: float,
                                            eps_r: float) -> float:
    """E00 [eV] (Padovani & Stratton, 1966):
        E00 = (q hbar / 2) sqrt(Nd / (m* eps_s))
    with Nd converted to m^-3, m* to kg, eps_s to F/m for the SI
    evaluation. E00 sets the qualitative TE/TFE/FE boundary: E00 << kT
    is thermionic emission, E00 >> kT is field emission (degenerate
    tunnel contact), comparable is thermionic-field emission."""
    from .constants import HBAR, M0
    Nd_m3 = Nd_cm3 * 1e6
    m_eff = m_eff_ratio * M0
    eps_s = eps_r * EPS0 * 1e2  # F/cm -> F/m
    E00_J = (Q * HBAR / 2.0) * np.sqrt(Nd_m3 / (m_eff * eps_s))
    return E00_J / Q  # J -> eV


def contact_regime(E00_eV: float, T: float) -> str:
    """Qualitative Padovani-Stratton regime classification from E00/kT:
    'TE' (thermionic emission dominates, E00 << kT), 'FE' (field
    emission / tunnel contact dominates, E00 >> kT), else 'TFE'
    (thermionic-field emission, the mixed crossover regime -- this
    module does not evaluate the TFE integral, see honesty clause)."""
    ratio = E00_eV / (KB_EV * T)
    if ratio < 0.5:
        return "TE"
    if ratio > 3.0:
        return "FE"
    return "TFE"


def field_emission_current_density(phi_B_eV: float, T: float, E00_eV: float,
                                    A_star: float) -> float:
    """Zero-bias-limit field-emission (tunnel-contact) saturation
    current density [A/cm^2], Padovani-Stratton pure-FE-limit formula:
    (phi_B, E00 both in eV so no extra charge factor is needed in the
    square root):
        J_FE = (A* T / kB) * sqrt(pi E00 phi_B) * exp(-phi_B / E00)
    Only meaningful deep in the FE regime (see contact_regime) -- this
    is the characteristic tunnel-contact current used to justify why
    heavily-doped contacts behave "ohmic" (near-zero effective
    resistance) despite a nonzero barrier, not a bias-swept I-V curve."""
    return (A_star * T / KB_EV) * np.sqrt(np.pi * E00_eV * phi_B_eV) * \
        np.exp(-phi_B_eV / E00_eV)
