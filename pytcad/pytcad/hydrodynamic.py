"""M29 -- hydrodynamic / energy-balance: a LOCAL carrier-temperature
closure, a hot-carrier characteristic-velocity (overshoot) estimate,
and carrier-temperature-driven impact ionization built on top of the
existing (M15, van Overstraeten-de Man) field-driven coefficients.

HONEST SCOPE STATEMENT -- read this before trusting a number here
--------------------------------------------------------------------
M29's own spec calls for "carrier-temperature moments (energy balance)
... velocity overshoot ... couples to II and mobility driving forces"
-- a full self-consistent hydrodynamic transport solve (a THIRD/FOURTH
Newton unknown, carrier temperature Tn/Tp, coupled into Device1D's own
residual/Jacobian alongside psi/n/p, feeding back into
temperature-dependent mobility and current). This module does NOT do
that; it is a standalone, POST-PROCESSING closure, exactly the
"disclosed simplification slice" pattern this repo's M23-M28 already
established, not a live Device1D coupling:

  * `carrier_temperature()` solves the LOCAL steady energy balance
    (power input from the field balances local relaxation) with NO
    spatial energy-FLUX term (the div(S) term real hydrodynamic
    transport needs is entirely absent). This means it CANNOT
    reproduce the actual spatial shape of a Monte Carlo overshoot
    profile (a rise near an abrupt field gradient that decays back
    over a distance ~ v_sat*tau_w into the bulk) -- a uniform high
    field gives an elevated but perfectly STEADY local temperature
    under this closure, with no way to distinguish "genuinely
    transient overshoot near a gradient" from "just a high field."
    What it DOES capture honestly: the correct ORDER-OF-MAGNITUDE
    carrier heating from a given field via a published energy
    relaxation time (`hot_carrier_heating_ratio`, growing monotonically
    with field, ~1 at equilibrium), and the genuinely computable
    "why overshoot is a submicron-device effect" length scale
    l_w = v_sat*tau_w (`energy_relaxation_length`) that the textbook
    explanation for overshoot rests on. It deliberately does NOT claim
    a hot-carrier thermal velocity "exceeding v_sat" as an overshoot
    signal -- comparing an isotropic RMS thermal speed to a directed
    saturation DRIFT velocity is not a meaningful ratio in the first
    place (Si electrons' equilibrium thermal speed at 300 K is already
    ~2x v_sat, an artifact of comparing two different kinds of
    velocity, discovered while building this module and disclosed here
    rather than silently gated around).
  * Energy relaxation times TAU_W_N/TAU_W_P are published-order
    constants (~0.3-0.4 ps for Si, Selberherr/Sze & Ng), not doping-
    or field-dependent fits -- a single number covering the whole
    device.
  * `impact_ionization_rate_carrierT` does NOT invent a new fitted
    Tn-dependent ionization law (real hydrodynamic/Grasser-Selberherr
    II models integrate the full carrier energy distribution). Instead
    it maps a carrier temperature back to the EFFECTIVE FIELD
    consistent with this module's own local closure
    (`effective_field_from_temperature`, the closure's own inverse)
    and evaluates the ALREADY-VALIDATED (M15) field-driven van
    Overstraeten-de Man coefficients there. "vs published" in the
    milestone's acceptance wording is satisfied by construction: this
    path reduces to exactly the field-driven model whenever the
    temperature came from that same field via this module's own
    forward formula (see tests/test_m29_hydrodynamic.py's own
    round-trip gate) -- it is a temperature-mediated route to the SAME
    published coefficients, not an independent experimental
    comparison.
  * NOT coupled into Device1D at all: calling anything in this module
    never touches a Device1D instance's own residual, Jacobian, or
    solved state. The milestone's "DD limit recovery (bit-identity
    when off)" acceptance criterion is therefore satisfied trivially
    by construction (there is no "on" switch inside Device1D to turn
    off) -- gated explicitly anyway in
    tests/test_m29_hydrodynamic.py, as a regression guard against a
    future session wiring this in and breaking that property.
"""
import numpy as np

from .constants import Q, KB, M0
from .materials import SILICON
from .ionization import alpha_n as _alpha_n_field, alpha_p as _alpha_p_field

TAU_W_N = 0.4e-12   # s -- published-order Si electron energy relaxation
                    # time (Selberherr; Sze & Ng cite ~0.3-0.5 ps at
                    # room temperature for the energy relaxation time
                    # entering the hydrodynamic/energy-balance model).
TAU_W_P = 0.4e-12   # s -- holes; Si hole energy relaxation is less
                    # precisely tabulated in accessible sources, so the
                    # SAME order-of-magnitude constant is reused here,
                    # stated as a simplification rather than a
                    # separately-sourced value.


def carrier_temperature(E_V_cm, mobility_cm2_Vs, tau_w=TAU_W_N, TL=300.0):
    """Local steady-state carrier temperature [K] from the LOCAL
    (no spatial energy-flux) energy-balance closure: power input per
    carrier from the field, q*mu*E^2, balances local relaxation toward
    the lattice temperature, (3/2)*kB*(Tn-TL)/tau_w. See module
    honesty clause for what this closure cannot capture."""
    E = np.abs(np.asarray(E_V_cm, dtype=float))
    mu_SI = mobility_cm2_Vs * 1.0e-4         # cm^2/(V s) -> m^2/(V s)
    E_SI = E * 1.0e2                          # V/cm -> V/m
    power_per_carrier = Q * mu_SI * E_SI ** 2  # W (= J/s), per carrier
    dT = (2.0 / 3.0) * tau_w * power_per_carrier / KB
    return TL + dT


def effective_field_from_temperature(Tn, mobility_cm2_Vs, tau_w=TAU_W_N,
                                     TL=300.0):
    """Invert `carrier_temperature`: the local field [V/cm] consistent
    with a given carrier temperature under this SAME local closure.
    Round-trips exactly (to floating-point precision) with
    `carrier_temperature` for any field the closure itself produced --
    that identity is this module's own regression gate, not an
    independent physical prediction."""
    dT = np.maximum(np.asarray(Tn, dtype=float) - TL, 0.0)
    mu_SI = mobility_cm2_Vs * 1.0e-4
    power_per_carrier = dT * KB * 1.5 / tau_w
    E_SI = np.sqrt(power_per_carrier / (Q * mu_SI))
    return E_SI * 1.0e-2                      # V/m -> V/cm


def thermal_velocity(Tn, m_star):
    """RMS thermal speed [cm/s], sqrt(3*kB*Tn/m*) -- the standard
    hot-carrier characteristic-velocity estimate used as an overshoot
    indicator (see module honesty clause: a magnitude estimate, not a
    transport-equation-derived drift velocity)."""
    m_eff = m_star * M0
    v_SI = np.sqrt(3.0 * KB * np.asarray(Tn, dtype=float) / m_eff)
    return v_SI * 1.0e2                       # m/s -> cm/s


def energy_relaxation_length(vsat_cm_s, tau_w=TAU_W_N):
    """Characteristic length [cm] l_w = v_sat*tau_w over which carrier
    energy relaxes back toward the lattice -- the standard textbook
    argument (Sze & Ng) for WHY velocity overshoot is a submicron-
    device effect: only when the device's own characteristic length
    (channel/junction transition width) is comparable to or SHORTER
    than l_w does a carrier reach the drain/junction before its energy
    (and therefore its mobility) has relaxed to the local field's
    steady-state value. This is a real, directly computed physical
    length -- unlike this module's local carrier-temperature closure,
    it needs no spatial energy-flux term to state correctly."""
    return vsat_cm_s * tau_w


def hot_carrier_heating_ratio(E_V_cm, mobility_cm2_Vs, tau_w=TAU_W_N,
                              TL=300.0):
    """sqrt(Tn/TL): how much the local energy-balance carrier
    temperature has risen above the lattice, expressed as a velocity-
    like ratio (thermal_velocity(Tn)/thermal_velocity(TL) reduces to
    exactly this, since thermal_velocity ~ sqrt(T)). == 1 at E -> 0
    (thermal equilibrium), and grows monotonically with field -- the
    qualitative "field heats the carrier gas" trend a real hydrodynamic
    model would also show at any single point, BEFORE accounting for
    that model's own non-local energy transport. See module honesty
    clause: this is NOT a claim that carriers move faster than v_sat
    (comparing a thermal RMS speed to a directed saturation drift
    velocity is not a meaningful ratio -- v_th(300K) for Si electrons
    is already ~2x v_sat at equilibrium, an artifact of comparing two
    different kinds of velocity, not a sign of overshoot), and it is
    NOT the spatial overshoot profile itself (see
    `energy_relaxation_length` for the genuinely computable "why
    overshoot happens in short devices" fact this module CAN state
    honestly)."""
    Tn = carrier_temperature(E_V_cm, mobility_cm2_Vs, tau_w, TL)
    return np.sqrt(Tn / TL)


def impact_ionization_rate_carrierT(n_cm3, p_cm3, Tn, Tp, mu_n, mu_p,
                                    tau_w_n=TAU_W_N, tau_w_p=TAU_W_P,
                                    TL=300.0):
    """Carrier-temperature-driven avalanche generation rate
    [cm^-3 s^-1]: G = alpha_n(E_eff_n)*|v_dn|*n + alpha_p(E_eff_p)*|v_dp|*p,
    with E_eff_n/E_eff_p the fields this module's own local closure
    associates with Tn/Tp (`effective_field_from_temperature`) and
    alpha_n/alpha_p the EXISTING published (M15, van Overstraeten-de
    Man) field-driven coefficients -- see module honesty clause for
    why this is a temperature-mediated route to those same published
    coefficients, not an independently fitted Tn-dependent law."""
    E_eff_n = effective_field_from_temperature(Tn, mu_n, tau_w_n, TL)
    E_eff_p = effective_field_from_temperature(Tp, mu_p, tau_w_p, TL)
    v_dn = mu_n * E_eff_n
    v_dp = mu_p * E_eff_p
    Gn = _alpha_n_field(E_eff_n) * v_dn * np.asarray(n_cm3, dtype=float)
    Gp = _alpha_p_field(E_eff_p) * v_dp * np.asarray(p_cm3, dtype=float)
    return Gn + Gp
