"""Shared vertical-DMOS doping construction, factored out of
sic_vmosfet.py and umos3d.py: both built the identical additive-region
formula (background drift/substrate erf step + body Gaussian/erfc-
rolloff + source Gaussian/erfc-rolloff + body-tie notch) against their
own Params dataclass, which happen to share the exact attribute names
(Lch, Ln, Lbt, Wbt, y_body, sigma_src, sigma_bt, t_drift, Na_body,
Nd_source, Na_bodytie, Nd_drift, Nd_sub) -- a byte-for-byte retyped
copy, not two independently-derived models. This module is the one
implementation both call, so a tuning change to the shared convention
(lat_sigma, the Ntotal formula, ...) can't silently diverge between the
two devices the way the duplicated copies could.
"""

import numpy as np
from scipy.special import erf, erfc


def erfc_rolloff(coord, edge, sigma_lat, high_side):
    """0.5*erfc rolloff, 1D. high_side='left' -> ~1 for coord<<edge, 0
    for coord>>edge (mirrors mosfet.py's `_sd_profile` convention)."""
    s = (edge - coord) if high_side == "left" else (coord - edge)
    return 0.5 * erfc(-s / (np.sqrt(2.0) * sigma_lat))


def vertical_dmos_doping(mesh, p):
    """Net doping and total ionized-impurity concentration [cm^-3],
    both shape (Nz, Ny, Nx) -- Device3D's expected doping array layout.

    Additive-region construction (mosfet.py's own convention,
    generalized to a vertical stack + a genuinely 3D lateral notch):
    each physical region contributes a signed Gaussian/erf-rolloff
    doping blob; net doping is their sum, Ntotal is the sum of their
    magnitudes (the total-ionized-impurity convention every mobility/
    BGN call in this repo already expects -- using |Nnet| instead is a
    known bug class in compensated regions, see materials.py's own
    `mobility_caughey_thomas` docstring).

    `p` is any object exposing Lch/Ln/Lbt/Wbt, y_body/sigma_src/
    sigma_bt/t_drift, and Na_body/Nd_source/Na_bodytie/Nd_drift/Nd_sub
    -- both SiCVMOSFETParams and UMOSParams satisfy this."""
    x, y, z = mesh.x, mesh.y, mesh.z
    X = x[None, None, :]      # (1,1,Nx)
    Y = y[None, :, None]      # (1,Ny,1)
    Z = z[:, None, None]      # (Nz,1,1)

    lat_sigma = 3e-6   # lateral junction grading -- same order as
                       # mosfet.py's own sigma_lat default (Lg/4-ish)

    # --- vertical background: drift everywhere, smoothly boosted to
    # substrate concentration near the bottom (erf step, not a hard
    # cutoff -- avoids an unnecessary sharp Newton-unfriendly interface
    # at a depth with no lateral structure to justify one).
    y_drift_end = p.y_body + p.t_drift
    sigma_sub = 3e-6
    substrate_boost = (p.Nd_sub - p.Nd_drift) * 0.5 * (
        1.0 + erf((Y - y_drift_end) / (np.sqrt(2.0) * sigma_sub)))
    background = p.Nd_drift + substrate_boost              # n-type, >0 everywhere

    # --- P-body: Gaussian-in-depth (peaked at the surface, same shape
    # convention as mosfet.py's `_sd_profile`), present for x < Lch.
    vert_body = np.exp(-(Y ** 2) / (2.0 * (p.y_body / 2.0) ** 2))
    lat_body = erfc_rolloff(X, p.Lch, lat_sigma, "left")
    body = p.Na_body * vert_body * lat_body                 # p-type magnitude

    # --- N+ source: shallow Gaussian, present for x < Ln, EXCEPT the
    # body-tie notch (x < Lbt AND z < Wbt) is carved out below.
    vert_src = np.exp(-(Y ** 2) / (2.0 * p.sigma_src ** 2))
    lat_src = erfc_rolloff(X, p.Ln, lat_sigma, "left")
    notch = (erfc_rolloff(X, p.Lbt, lat_sigma, "left")
             * erfc_rolloff(Z, p.Wbt, lat_sigma, "left"))
    source = p.Nd_source * vert_src * lat_src * (1.0 - notch)

    # --- P+ body-tie: shallow Gaussian, confined to the notch region.
    vert_bt = np.exp(-(Y ** 2) / (2.0 * p.sigma_bt ** 2))
    bodytie = p.Na_bodytie * vert_bt * notch

    doping = background - body + source - bodytie
    Ntotal = np.abs(background) + body + source + bodytie
    return doping, Ntotal
