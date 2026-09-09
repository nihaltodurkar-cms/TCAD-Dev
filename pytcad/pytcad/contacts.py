"""Contact boundary-condition value kernels.

`_ohmic_values` lived in `device2d.py` and was imported out of it, by
its private name, from `unstructured_dd.py`, `unstructured_dd3d.py` and
`unstructured_poisson.py` -- three modules whose docstrings describe
them as standalone and independently testable, but which could not run
without reaching into the structured 2D solver's internals.

It is a pure vectorized kernel over doping and intrinsic concentration:
no mesh, no device, no dimensionality.  It belongs here, where the
unstructured solvers can use it without importing a structured one.

`device2d.py` re-exports it under the same private name, so every
existing import site keeps working unchanged.
"""
import numpy as np

__all__ = ["ohmic_values"]


def ohmic_values(C, nie, V, VT):
    """Ohmic contact: local charge neutrality + thermal equilibrium.
    Vectorized version of device.py's _contact_values body -- always
    evaluate the MAJORITY carrier from the quadratic and get the minority
    one from the mass-action law, to avoid cancellation.
    """
    C = np.asarray(C, dtype=float)
    nie = np.asarray(nie, dtype=float)
    root = np.sqrt(C * C + 4.0 * nie * nie)
    n0_if_n = 0.5 * (C + root)
    p0_if_p = 0.5 * (-C + root)
    is_n = C >= 0.0
    n0 = np.where(is_n, n0_if_n, nie * nie / np.maximum(p0_if_p, 1e-300))
    p0 = np.where(is_n, nie * nie / np.maximum(n0_if_n, 1e-300), p0_if_p)
    psi0 = V / VT + np.log(n0 / nie)
    return psi0, n0, p0


# The name three modules already import.  Kept as an alias rather
# than renaming call sites, so this move stays behavior-only.
_ohmic_values = ohmic_values
