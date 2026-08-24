"""GUI-side derived quantities for the Process Workbench's Derived
Quantities panel (design section 19).  Only functions here are exposed
in that panel -- each one is either a direct pass-through of a
backend-tested pytcad.process function, or (like sheet_resistance) a
small GUI-service computation built from already-tested backend pieces,
with its own dedicated test.  Nothing here is new physics.
"""
import numpy as np

from pytcad.materials import mobility_caughey_thomas, SILICON
from pytcad.constants import Q
from pytcad.process import junction_depth


def sheet_resistance(x, net_doping, ntotal, T=300.0):
    """Ohm/sq of the doped-above-background region, integrating
    conductivity over depth and inverting.

    Masks to `x <= junction_depth(x, net_doping)[0]` before integrating --
    matching examples/02_process_flow.py's own formula exactly (its
    section 5: `mask = x <= xj[0]`). Without this mask, the integral
    included the substrate/background tail beyond the junction too,
    which is not "sheet resistance of the n-layer" (or p-layer) the
    docstring/design spec/label all claim this computes -- it was instead
    a resistance of the WHOLE stack, off by up to several times at
    realistic substrate lengths where the background tail is much longer
    than the shallow implanted layer. Falls back to the full array when
    `junction_depth` finds no sign change at all (e.g. a uniformly-doped
    substrate with no implant, or same-type reinforcement) -- there is no
    junction to mask to in that case, and the doped region legitimately
    *is* the whole array.

    Uses the majority-carrier mobility PER NODE, selected from the sign
    of `net_doping`: n-type (net_doping >= 0) nodes use electron
    (Caughey-Thomas "n") mobility, p-type (net_doping < 0) nodes use hole
    ("p") mobility. A profile with both n-type and p-type regions (e.g.
    a substrate of one type with an implanted-and-annealed dopant of the
    opposite type forming a junction) is common in real process flows, so
    always using electron mobility would silently overestimate the
    conductivity -- and understate the sheet resistance -- of any p-type
    region. Note that within the masked region (x <= first junction, by
    construction the region BEFORE the first sign change) net_doping is a
    single, constant polarity, so this per-node selection is mostly a
    defensive/general-case safeguard here rather than something a normal
    single-junction masked profile exercises both branches of; it is
    still exercised for real by the "no junction found" fallback path
    (e.g. a uniformly p-type profile correctly uses hole mobility
    throughout, not electron mobility by default).

    `net_doping`/`ntotal` are cm^-3 arrays on `x` [cm].
    """
    x = np.asarray(x, dtype=float)
    net_doping = np.asarray(net_doping, dtype=float)
    ntotal = np.asarray(ntotal, dtype=float)

    xj = junction_depth(x, net_doping)
    mask = (x <= xj[0]) if xj.size else np.ones_like(x, dtype=bool)
    xm, netm, ntotalm = x[mask], net_doping[mask], ntotal[mask]

    mu_n = mobility_caughey_thomas(ntotalm, SILICON, T, "n")
    mu_p = mobility_caughey_thomas(ntotalm, SILICON, T, "p")
    mu = np.where(netm >= 0, mu_n, mu_p)
    sigma = Q * mu * np.maximum(np.abs(netm), 1.0)
    return 1.0 / np.trapezoid(sigma, xm)
