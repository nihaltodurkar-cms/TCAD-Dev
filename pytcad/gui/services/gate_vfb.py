"""Gate flatband voltage: computed (via the existing, unmodified
moscap.flatband_voltage(), the same path build_mosfet() already uses)
or a manual override.

Reuses a pure, non-solving pytcad utility function -- this is the
intended integration point per the design spec, not a numerical-backend
change.
"""
from pytcad.moscap import flatband_voltage

from .structure_model import rasterize_doping, resolve_boundary_indices


class NonUniformGateSubstrateDopingError(Exception):
    def __init__(self, gate_name, min_doping, max_doping):
        self.gate_name = gate_name
        self.min_doping = min_doping
        self.max_doping = max_doping
        super().__init__(
            f"Gate '{gate_name}' spans doping regions with different "
            f"concentrations ({min_doping:.3g} to {max_doping:.3g} cm^-3) -- "
            f"narrow its boundary to one doping region, or set Vfb mode to manual.")


def get_gate_substrate_doping(gate, structure, mesh_spec):
    """The net doping at the EXACT silicon-surface nodes this gate's
    Robin BC will be applied to.  Flatband voltage is only physically
    defined for one substrate doping, so this requires exact uniformity
    across those nodes rather than averaging or sampling one of them."""
    doping = rasterize_doping(structure, mesh_spec)
    i, j = resolve_boundary_indices(gate.boundary, mesh_spec)
    if i.size == 0:
        raise ValueError(f"gate '{gate.name}' boundary resolves to zero nodes")
    values = doping[j, i]
    lo, hi = float(values.min()), float(values.max())
    if lo != hi:
        raise NonUniformGateSubstrateDopingError(gate.name, lo, hi)
    return lo


def resolve_gate_vfb(gate, structure, mesh_spec, T=300.0):
    """The Vfb [V] to use for this gate, per its vfb_mode."""
    if gate.vfb_mode == "manual":
        if gate.vfb_manual is None:
            raise ValueError(
                f"gate '{gate.name}' is in manual Vfb mode but vfb_manual is not set")
        return gate.vfb_manual
    if gate.vfb_mode == "computed":
        nsub = get_gate_substrate_doping(gate, structure, mesh_spec)
        return flatband_voltage(nsub, gate.tox_cm, gate.gate_type, 0.0, T)
    raise ValueError(f"unknown vfb_mode '{gate.vfb_mode}'")
