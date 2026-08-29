"""MaterialLibrary: named lookup over pytcad's Semiconductor parameter
sets, with an educational summary per material.

Known materials are registry entries; SOLVABLE materials are a subset
the numerical core actually implements.  Since M11-S1 the library knows
Ge / GaAs / InGaAs / AlGaAS, and DomainDevice.validate() accepts them in
authored regions -- but adapters and solver backends still refuse to
SOLVE them until the heterojunction core (M11-S3) exists.  Keep that
distinction honest everywhere.
"""
from pytcad.materials import (
    SILICON, GE, GAAS, INGAAS, algaas, Semiconductor,
)


class MaterialLibrary:
    def __init__(self):
        # name -> Semiconductor instance.  Keys are the domain-level
        # identifiers used by Region.material / DomainDevice.material.
        self._materials = {
            "SILICON": SILICON,
            "GE": GE,
            "GAAS": GAAS,
            "INGAAS": INGAAS,
            "AL0.3GA0.7AS": algaas(0.3),   # standard HEMT-barrier fraction
        }

    def names(self):
        return sorted(self._materials)

    def register(self, name, material: Semiconductor):
        """Register a parameter set under a domain-level key.  Registering
        makes the material KNOWN to validation -- it does NOT make it
        solvable: the numerical core currently implements silicon only,
        and DomainDevice.validate()/adapters enforce that distinction."""
        if not isinstance(material, Semiconductor):
            raise TypeError("material must be a pytcad Semiconductor")
        self._materials[name] = material

    def get(self, name) -> Semiconductor:
        """Case-INSENSITIVE lookup.  Legacy data carries labels like
        StructureModel's default 'Silicon' while canonical keys are
        uppercase; both must resolve to the same entry, so the lookup
        contract is defined here at the library boundary rather than
        hoping every producer normalizes first."""
        key = str(name).upper()
        for known, material in self._materials.items():
            if known.upper() == key:
                return material
        raise KeyError(
            f"unknown material '{name}' (available: "
            f"{', '.join(self.names())})") from None

    def summary(self, name):
        """Headline properties for UI display / teaching."""
        m = self.get(name)
        return {
            "name": name,
            "label": m.name,
            "eps_r": m.eps_r,
            "chi_eV": m.chi,
            "Eg0_eV": m.Eg0,
            "Eg300": m.Eg(300.0),
            "ni300": m.ni(300.0),
            "Nc300": m.Nc300,
            "Nv300": m.Nv300,
            "mu_n_max": m.mu_n_max,
            "mu_p_max": m.mu_p_max,
        }


LIBRARY = MaterialLibrary()
