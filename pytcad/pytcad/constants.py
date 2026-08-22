"""Physical constants in CGS-practical units used throughout PyTCAD.

Unit convention (the standard TCAD convention):
    length          cm
    concentration   cm^-3
    potential       V
    current density A/cm^2
    time            s
"""

Q = 1.602176634e-19        # elementary charge [C]
KB = 1.380649e-23          # Boltzmann constant [J/K]
KB_EV = 8.617333262e-5     # Boltzmann constant [eV/K]
EPS0 = 8.8541878128e-14    # vacuum permittivity [F/cm]
HBAR = 1.054571817e-34     # reduced Planck constant [J s]
M0 = 9.1093837015e-31      # free electron mass [kg]


def thermal_voltage(T: float) -> float:
    """V_T = kT/q [V].  25.852 mV at T = 300 K."""
    return KB * T / Q
