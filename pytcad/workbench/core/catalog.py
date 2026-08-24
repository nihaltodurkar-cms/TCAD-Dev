"""The Model Catalog: physics as documented, selectable components.

This is the educational heart of M1.  Every physics model the solver
actually implements is registered here with its equations, the material
parameters it consumes, references, and an HONEST applicability note --
including limitations like field_mobility's 1D-only status.

M1 scope: the catalog is METADATA + configuration validation.  The
solver's Models flags remain the execution truth; default_config()
returns exactly the wire-format defaults (DeviceSpec._default_models),
so adopting the catalog changes no solver behavior.  Later milestones
build the Physics Lab UI and provenance records on top of this registry.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    key: str                      # matches a DeviceSpec.models flag name
    title: str
    equations: tuple              # human-readable equation strings
    parameters: tuple             # Semiconductor field names consumed
    references: tuple             # literature citations
    applicability: str            # where it applies (dimensions, devices)
    enabled_by_default: bool
    limitations: str = ""         # honest statement of what it canNOT do


_MODELS = {
    "doping_mobility": ModelInfo(
        key="doping_mobility",
        title="Doping-dependent mobility (Caughey-Thomas)",
        equations=(
            "mu(N) = mu_min + (mu_max - mu_min) / (1 + (N/Nref)^alpha)",
        ),
        parameters=("mu_n_min", "mu_n_max", "mu_n_Nref", "mu_n_alpha",
                    "mu_n_Texp", "mu_p_min", "mu_p_max", "mu_p_Nref",
                    "mu_p_alpha", "mu_p_Texp"),
        references=(
            "Caughey & Thomas, Proc. IEEE 55, 2192-2193 (1967)",
            "temperature exponent per Scharfetter-Gummel convention",
        ),
        applicability="1D, 2D, 3D; all doped silicon",
        enabled_by_default=True,
    ),
    "field_mobility": ModelInfo(
        key="field_mobility",
        title="High-field mobility / velocity saturation (Canali)",
        equations=(
            "v_sat via mu(E): carriers stop accelerating above ~1e4 V/cm",
        ),
        parameters=("vsat_n", "vsat_p", "beta_n", "beta_p"),
        references=("Canali et al., IEEE Trans. Electron Devices 22, "
                    "1045 (1975)",),
        applicability="1D only",
        enabled_by_default=False,
        limitations="Not implemented above 1D: raises NotImplementedError "
                    "in 2D/3D solvers because there is no single field "
                    "direction on an unstructured current flow.",
    ),
    "srh": ModelInfo(
        key="srh",
        title="Shockley-Read-Hall trap recombination",
        equations=(
            "R_SRH = (n*p - ni^2) / (tau_p*(n + nie) + tau_n*(p + nie))",
            "tau(N) via Scharfetter's empirical lifetime fit",
        ),
        parameters=("tau_n0", "tau_p0", "tau_Nref"),
        references=(
            "Shockley & Read, Phys. Rev. 87, 835 (1952)",
            "Hall, Phys. Rev. 87, 387 (1952)",
            "Scharfetter, Solid-State Electronics 8, 1299 (1965)",
        ),
        applicability="1D, 2D, 3D; dominant in depleted/quasi-neutral regions",
        enabled_by_default=True,
    ),
    "auger": ModelInfo(
        key="auger",
        title="Auger recombination (three-particle)",
        equations=("R_Auger = (n*p - ni^2) * (Cn*n + Cp*p)",),
        parameters=("Cn_auger", "Cp_auger"),
        references=("Dziewior & Schmid, Appl. Phys. Lett. 31, 346 (1977)",),
        applicability="1D, 2D, 3D; dominant at high carrier/doping density",
        enabled_by_default=True,
    ),
    "bgn": ModelInfo(
        key="bgn",
        title="Bandgap narrowing (Slotboom, heavy doping)",
        equations=("nie_eff = ni^2 * exp(dEg(N)/kT) with Slotboom's "
                   "apparent-BGN fit",),
        parameters=("bgn_E0", "bgn_N0"),
        references=(
            "Slotboom & de Graaff, Solid-State Electron. 19, 857 (1976)",
            "del Alamo, integrated BGN fit (course notes)",
        ),
        applicability="1D, 2D, 3D; significant above N ~ 1e17 cm^-3",
        enabled_by_default=True,
    ),
}


class ModelCatalog:
    """Registry API: list()/describe()/validate()/default_config()."""

    @classmethod
    def list(cls):
        return sorted(_MODELS)

    @classmethod
    def describe(cls, key):
        try:
            return _MODELS[key]
        except KeyError:
            raise KeyError(
                f"unknown physics model '{key}' (known models: "
                f"{', '.join(cls.list())})") from None

    @classmethod
    def default_config(cls):
        """The wire-format default: EXACTLY DeviceSpec._default_models().
        field_mobility defaults off because of its honest 1D-only limit."""
        return {key: info.enabled_by_default
                for key, info in _MODELS.items()}

    @classmethod
    def validate(cls, config):
        """Validate a ModelConfig dict against the registry.  Raises
        ValueError with an actionable message; returns None."""
        if not isinstance(config, dict):
            raise ValueError(
                f"model config must be a dict of {{model_key: bool}}, got "
                f"{type(config).__name__}")
        unknown = sorted(set(config) - set(_MODELS))
        if unknown:
            raise ValueError(
                f"unknown physics model(s) {unknown}; known models: "
                f"{', '.join(cls.list())}")
        for key, value in config.items():
            if not isinstance(value, bool):
                raise ValueError(
                    f"model '{key}' must be true or false, got "
                    f"{value!r}")
