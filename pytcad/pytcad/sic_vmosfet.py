"""Vertical (DMOS-style) 4H-SiC power MOSFET: a real 3D structure with
genuine variation along all three axes, built from ordinary numpy on a
Mesh3D grid using the same box-integration Device3D core every other
device in this repo uses -- no new solver machinery, only geometry.

No vertical/DMOS doping-profile builder existed anywhere in this repo
before this module (checked: pytcad/mosfet.py is a LATERAL structure --
source|gate|drain side by side at one depth; pytcad/moscap.py is a 1D
gate/oxide/substrate stack with no source/drain/channel at all). This
follows mosfet.py's own additive-Gaussian/erfc-rolloff convention
(mosfet_doping/`_sd_profile`), generalized to (a) a VERTICAL stack
(source/body over drift over substrate, not side-by-side) and (b) a
genuinely 3D lateral layout: a finite body-tie contact "notch" occupies
only part of the stripe length in z, so the structure does not reduce
to a z-invariant 2D extrusion the way examples/06_3d_mosfet.py's does
-- it exercises real x-y-z coupling, not just a width multiplier.

GEOMETRY (a symmetric HALF-CELL of a striped planar DMOS layout --
mirror symmetry assumed at all four lateral boundaries x=0, x=Lcell,
z=0, z=W; Device3D's box-integration assembly gives this for free with
no explicit boundary condition, same zero-flux-Neumann-by-omission
convention every other fixture in this repo relies on):

    x (lateral, half-cell):
        [0, Ln]     N+ source (at the surface); for z < Wbt, the
                    sub-range [0, Lbt] is instead P+ body-tie (shorts
                    P-body to the source metal -- a real periodic
                    design feature, not a simplification for this
                    example: without SOME body tie a real device's
                    parasitic BJT can trigger under transient stress).
        [0, Lch]    P-body (vertically, beneath the surface features
                    above -- extends further in x than the source does)
        [Lch, Lcell] JFET/drift region exposed at the surface (no body,
                    no source) -- gate oxide sits directly over N-
                    drift here, the accumulation/JFET-spreading region
                    real planar power MOSFETs have between cells.
        Gate: covers (Ln, Lcell] at the surface -- channel AND JFET
        region under one gate electrode, standard planar layout.

    y (depth, 0 = top surface):
        N+ source / P+ body-tie: shallow (Gaussian-in-depth, same
        functional form as mosfet.py's `_sd_profile`).
        P-body: a deeper Gaussian-in-depth region, x < Lch only.
        N- drift: the bulk of the device depth -- this is what sets
        the blocking voltage (thicker/lighter-doped = higher BV, at
        the cost of on-resistance -- the fundamental SiC/Si power
        MOSFET tradeoff curve, same physics, different material).
        N+ substrate/drain: a thin heavily-doped layer at the bottom,
        contacted by a full-area drain electrode -- the standard TCAD
        simplification of a much-thicker real wafer handle, same
        approach examples/06_3d_mosfet.py and this repo's other
        MOSFET/MOSCap fixtures already use for their own contacts.

    z (stripe length): uniform EXCEPT the body-tie notch above -- the
        one deliberately 3D-only feature of this structure.
"""

import numpy as np
from scipy.special import erf, erfc

from .mesh3d import Mesh3D
from .device3d import Device3D
from .materials import SIC_4H, Semiconductor
from .moscap import flatband_voltage


class SiCVMOSFETParams:
    """All dimensions [cm], concentrations [cm^-3]. Defaults describe a
    representative (not literally datasheet-matched) planar 4H-SiC
    power MOSFET half-cell: ~0.5 um channel, ~4.2 um / 1e16 drift
    (a few-hundred-volt-class drift design, per Baliga's own parallel-
    plane unipolar-limit scaling -- see the README for the actual
    simulated peak-field-vs-critical-field estimate, not a claimed
    target rating)."""

    def __init__(self,
                 Ln=4e-5, Lbt=2e-5, Lch=1e-4, Lcell=2e-4,      # x [cm]
                 W=2e-4, Wbt=1e-4,                              # z [cm]
                 y_body=5e-5, sigma_src=8e-6, sigma_bt=1e-5,    # y [cm]
                 t_drift=4.2e-4, t_sub=3e-5,                    # y [cm]
                 Na_body=2e17, Nd_source=2e19, Na_bodytie=2e19,
                 Nd_drift=1e16, Nd_sub=1e19,
                 tox_cm=5e-7, gate="n+poly", T=300.0,
                 material: Semiconductor = SIC_4H):
        self.Ln, self.Lbt, self.Lch, self.Lcell = Ln, Lbt, Lch, Lcell
        self.W, self.Wbt = W, Wbt
        self.y_body, self.sigma_src, self.sigma_bt = y_body, sigma_src, sigma_bt
        self.t_drift, self.t_sub = t_drift, t_sub
        self.Na_body, self.Nd_source, self.Na_bodytie = Na_body, Nd_source, Na_bodytie
        self.Nd_drift, self.Nd_sub = Nd_drift, Nd_sub
        self.tox_cm, self.gate, self.T, self.material = tox_cm, gate, T, material
        if Lbt >= Ln or Ln >= Lch or Lch >= Lcell:
            raise ValueError("require Lbt < Ln < Lch < Lcell")
        if Wbt >= W:
            raise ValueError("require Wbt < W")
        # Depth axis derived from the vertical stack, not a free knob --
        # keeps the doping builder and the mesh's y-extent self-consistent.
        self.depth = y_body + self.t_drift + t_sub


DEFAULT_PARAMS = SiCVMOSFETParams()


def _erfc_rolloff(coord, edge, sigma_lat, high_side):
    """0.5*erfc rolloff, 1D. high_side='left' -> ~1 for coord<<edge, 0
    for coord>>edge (mirrors mosfet.py's `_sd_profile` convention)."""
    s = (edge - coord) if high_side == "left" else (coord - edge)
    return 0.5 * erfc(-s / (np.sqrt(2.0) * sigma_lat))


def sic_vmosfet_doping(mesh: Mesh3D, p: SiCVMOSFETParams = DEFAULT_PARAMS):
    """Net doping and total ionized-impurity concentration [cm^-3],
    both shape (Nz, Ny, Nx) -- Device3D's expected doping array layout.

    Additive-region construction (mosfet.py's own convention,
    generalized to a vertical stack + a genuinely 3D lateral notch):
    each physical region contributes a signed Gaussian/erf-rolloff
    doping blob; net doping is their sum, Ntotal is the sum of their
    magnitudes (the total-ionized-impurity convention every mobility/
    BGN call in this repo already expects -- using |Nnet| instead is a
    known bug class in compensated regions, see materials.py's own
    `mobility_caughey_thomas` docstring)."""
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
    lat_body = _erfc_rolloff(X, p.Lch, lat_sigma, "left")
    body = p.Na_body * vert_body * lat_body                 # p-type magnitude

    # --- N+ source: shallow Gaussian, present for x < Ln, EXCEPT the
    # body-tie notch (x < Lbt AND z < Wbt) is carved out below.
    vert_src = np.exp(-(Y ** 2) / (2.0 * p.sigma_src ** 2))
    lat_src = _erfc_rolloff(X, p.Ln, lat_sigma, "left")
    notch = (_erfc_rolloff(X, p.Lbt, lat_sigma, "left")
             * _erfc_rolloff(Z, p.Wbt, lat_sigma, "left"))
    source = p.Nd_source * vert_src * lat_src * (1.0 - notch)

    # --- P+ body-tie: shallow Gaussian, confined to the notch region.
    vert_bt = np.exp(-(Y ** 2) / (2.0 * p.sigma_bt ** 2))
    bodytie = p.Na_bodytie * vert_bt * notch

    doping = background - body + source - bodytie
    Ntotal = np.abs(background) + body + source + bodytie
    return doping, Ntotal


def build_sic_vmosfet(mesh: Mesh3D, p: SiCVMOSFETParams = DEFAULT_PARAMS,
                      models=None):
    """Build a ready-to-solve 4H-SiC vertical power MOSFET Device3D on
    `mesh`. Contacts: 'source' (N+ source + P+ body-tie, shorted -- a
    single ohmic contact, matching how they're physically wired), 'gate'
    (GateBC, normal_axis='y', over the channel+JFET region), 'drain'
    (full-area ohmic, bottom face). No explicit BC at x=0/x=Lcell or
    z=0/z=W -- Device3D's box-integration assembly gives the intended
    mirror-symmetry zero-flux Neumann condition there for free."""
    doping, Ntotal = sic_vmosfet_doping(mesh, p)
    dev = Device3D(mesh, doping, Ntotal=Ntotal, T=p.T, material=p.material,
                   models=models)

    i_src = np.where(mesh.x <= p.Ln)[0]
    i_gate = np.where(mesh.x > p.Ln)[0]
    kk_all = np.arange(mesh.Nz)

    ii, kk = np.meshgrid(i_src, kk_all, indexing="ij")
    dev.add_contact("source", i=ii.ravel(), j=np.zeros(ii.size, dtype=int),
                    k=kk.ravel(), V=0.0)

    Vfb = flatband_voltage(-p.Na_body, p.tox_cm, p.gate, 0.0, p.T, p.material)
    ii, kk = np.meshgrid(i_gate, kk_all, indexing="ij")
    dev.add_gate("gate", i=ii.ravel(), j=np.zeros(ii.size, dtype=int),
                k=kk.ravel(), tox_cm=p.tox_cm, Vfb=Vfb, Vg=0.0, normal_axis="y")

    ii, kk = np.meshgrid(np.arange(mesh.Nx), kk_all, indexing="ij")
    dev.add_contact("drain", i=ii.ravel(),
                    j=np.full(ii.size, mesh.Ny - 1, dtype=int),
                    k=kk.ravel(), V=0.0)
    return dev
