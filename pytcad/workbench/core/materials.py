"""MaterialLibrary: named lookup over pytcad's Semiconductor parameter
sets, with an educational summary per material.

M1 scope: silicon only -- that is not a limitation of this class but of
the numerical core (SILICON is the only Semiconductor instance pytcad
defines; Device2D takes one material for the whole domain).  The library
is the seam where GaAs / InGaAs / SiGe etc. will appear once a backend
supports heterostructures.
"""
from pytcad.materials import SILICON, Semiconductor


class MaterialLibrary:
    def __init__(self):
        # name -> Semiconductor instance.  Keys are the domain-level
        # identifiers used by Region.material / DomainDevice.material.
        self._materials = {"SILICON": SILICON}

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
