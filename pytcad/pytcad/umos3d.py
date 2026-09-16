"""Vertical trench-gate power MOSFET (UMOS): a real 3D structure built
the same way sic_vmosfet.py's planar DMOS device is -- ordinary numpy
doping on a Mesh3D grid, the same box-integration Device3D core every
other device in this repo uses. No new solver machinery, only geometry
and boundary-condition placement.

Nothing named "UMOS"/"trench" existed anywhere in this repo before this
module (checked). sic_vmosfet.py's planar device puts its gate on the
TOP SURFACE (normal_axis='y') beyond the source edge -- the channel
runs horizontally under the oxide. A UMOS device instead cuts a trench
down from the surface and gates the VERTICAL sidewall -- the channel
runs vertically along that wall, between the source above and the
drift region below.

Device3D solves on a single rectangular box (no internal cavities), so
the trench cavity itself is not meshed as removed volume -- exactly the
same structural convention sic_vmosfet.py already relies on for its
own surface gate (the oxide/poly above the surface isn't meshed
either; only its Robin coupling to the silicon surface is). Here, the
silicon domain's OWN x=0 face becomes the trench sidewall: a GateBC is
applied there (normal_axis='x') for depths shallower than the trench
bottom (y < Dtrench); at y > Dtrench the same x=0 face reverts to the
default zero-flux Neumann mirror-symmetry boundary every other lateral
edge in this device already uses. That single geometric fact --
one face, split into a gated shallow part and a natural-BC deep part
-- is what makes this a genuine trench device rather than a relabeled
planar one, and it is exactly what produces the two physically real
field-crowding corners a trench MOSFET is known for:
    (x=0, y=0)        -- trench top corner (sidewall meets surface)
    (x=0, y=Dtrench)  -- trench bottom corner (sidewall meets the
                          body/drift junction curving underneath it)

GEOMETRY (a symmetric HALF-CELL: mirror symmetry at x=Lcell, z=0,
z=W; the x=0 face carries the trench gate for y<Dtrench and mirror
symmetry for y>Dtrench):

    x (lateral, half-cell, 0 = trench sidewall):
        [0, Lbt]    P+ body-tie (for z < Wbt only -- a real periodic
                    design feature that shorts P-body to source metal,
                    same convention as sic_vmosfet.py's own notch)
        [0, Ln]     N+ source (elsewhere in z)
        [0, Lch]    P-body (extends further in x than the source)
        [Lch, Lcell] N- drift, exposed to nothing but drift for the
                    rest of the half-cell -- no JFET region is needed
                    here (unlike the planar device) because the trench
                    itself, not a surface gate, does the inversion.

    y (depth, 0 = top surface):
        Trench: [0, Dtrench] at x=0 -- gated sidewall (GateBC).
        N+ source / P+ body-tie: shallow Gaussian-in-depth.
        P-body: a deeper Gaussian-in-depth region, x < Lch only.
                Dtrench is chosen deeper than the body's own
                characteristic depth so the gated sidewall genuinely
                spans the whole channel and reaches into the drift
                below it (the real UMOS design requirement -- an
                under-depth trench leaves an ungated JFET neck).
        N- drift: the bulk of the device depth -- sets the blocking
                voltage.
        N+ substrate/drain: a thin heavily-doped layer at the bottom.

    z (stripe length): uniform except the body-tie notch above -- the
        one deliberately 3D-only feature, same as sic_vmosfet.py.
"""

import numpy as np
from scipy.special import erf, erfc

from .mesh3d import Mesh3D
from .device3d import Device3D
from .materials import SILICON, Semiconductor
from .moscap import flatband_voltage


class UMOSParams:
    """All dimensions [cm], concentrations [cm^-3]. Defaults describe a
    representative (not datasheet-matched) silicon trench power MOSFET
    half-cell: ~0.6 um channel, ~3.5 um / 2e16 drift."""

    def __init__(self,
                 Lbt=1.5e-5, Ln=3.5e-5, Lch=6.5e-5, Lcell=1.4e-4,  # x [cm]
                 W=1.4e-4, Wbt=7e-5,                                # z [cm]
                 y_body=5e-5, Dtrench=7e-5,                         # y [cm]
                 sigma_src=1.5e-5, sigma_bt=2e-5,                   # y [cm]
                 t_drift=3.5e-4, t_sub=3e-5,                        # y [cm]
                 Na_body=3e17, Nd_source=5e19, Na_bodytie=5e19,
                 Nd_drift=2e16, Nd_sub=1e19,
                 tox_cm=5e-6, gate="n+poly", T=300.0,
                 material: Semiconductor = SILICON):
        self.Lbt, self.Ln, self.Lch, self.Lcell = Lbt, Ln, Lch, Lcell
        self.W, self.Wbt = W, Wbt
        self.y_body, self.Dtrench = y_body, Dtrench
        self.sigma_src, self.sigma_bt = sigma_src, sigma_bt
        self.t_drift, self.t_sub = t_drift, t_sub
        self.Na_body, self.Nd_source, self.Na_bodytie = Na_body, Nd_source, Na_bodytie
        self.Nd_drift, self.Nd_sub = Nd_drift, Nd_sub
        self.tox_cm, self.gate, self.T, self.material = tox_cm, gate, T, material
        if Lbt >= Ln or Ln >= Lch or Lch >= Lcell:
            raise ValueError("require Lbt < Ln < Lch < Lcell")
        if Wbt >= W:
            raise ValueError("require Wbt < W")
        if Dtrench <= y_body:
            raise ValueError(
                "require Dtrench > y_body -- an under-depth trench "
                "leaves an ungated JFET neck, not a valid UMOS design")
        self.depth = y_body + self.t_drift + t_sub


DEFAULT_PARAMS = UMOSParams()


def _erfc_rolloff(coord, edge, sigma_lat, high_side):
    """0.5*erfc rolloff, 1D (same convention as sic_vmosfet.py's own
    helper). high_side='left' -> ~1 for coord<<edge, 0 for coord>>edge."""
    s = (edge - coord) if high_side == "left" else (coord - edge)
    return 0.5 * erfc(-s / (np.sqrt(2.0) * sigma_lat))


def umos_doping(mesh: Mesh3D, p: UMOSParams = DEFAULT_PARAMS):
    """Net doping and total ionized-impurity concentration [cm^-3],
    both shape (Nz, Ny, Nx). Identical additive-region construction to
    sic_vmosfet.sic_vmosfet_doping (the doping profile does not care
    where the gate BC is placed) -- only the caller's geometry
    parameters and the gate placement in build_umos differ."""
    x, y, z = mesh.x, mesh.y, mesh.z
    X = x[None, None, :]
    Y = y[None, :, None]
    Z = z[:, None, None]

    lat_sigma = 3e-6

    y_drift_end = p.y_body + p.t_drift
    sigma_sub = 3e-6
    substrate_boost = (p.Nd_sub - p.Nd_drift) * 0.5 * (
        1.0 + erf((Y - y_drift_end) / (np.sqrt(2.0) * sigma_sub)))
    background = p.Nd_drift + substrate_boost

    vert_body = np.exp(-(Y ** 2) / (2.0 * (p.y_body / 2.0) ** 2))
    lat_body = _erfc_rolloff(X, p.Lch, lat_sigma, "left")
    body = p.Na_body * vert_body * lat_body

    vert_src = np.exp(-(Y ** 2) / (2.0 * p.sigma_src ** 2))
    lat_src = _erfc_rolloff(X, p.Ln, lat_sigma, "left")
    notch = (_erfc_rolloff(X, p.Lbt, lat_sigma, "left")
             * _erfc_rolloff(Z, p.Wbt, lat_sigma, "left"))
    source = p.Nd_source * vert_src * lat_src * (1.0 - notch)

    vert_bt = np.exp(-(Y ** 2) / (2.0 * p.sigma_bt ** 2))
    bodytie = p.Na_bodytie * vert_bt * notch

    doping = background - body + source - bodytie
    Ntotal = np.abs(background) + body + source + bodytie
    return doping, Ntotal


def build_umos(mesh: Mesh3D, p: UMOSParams = DEFAULT_PARAMS, models=None):
    """Build a ready-to-solve trench-gate (UMOS) power MOSFET Device3D
    on `mesh`. Contacts: 'source' (N+ source + P+ body-tie, shorted),
    'gate' (GateBC on the x=0 face, normal_axis='x', restricted to
    y <= Dtrench -- the trench sidewall), 'drain' (full-area ohmic,
    bottom face). No explicit BC at x=Lcell / z=0 / z=W, and none at
    x=0 for y>Dtrench -- Device3D's box-integration assembly gives the
    intended zero-flux Neumann condition there for free."""
    doping, Ntotal = umos_doping(mesh, p)
    dev = Device3D(mesh, doping, Ntotal=Ntotal, T=p.T, material=p.material,
                   models=models)

    kk_all = np.arange(mesh.Nz)

    # Source: the entire x=0..Ln surface strip (source + body-tie,
    # shorted -- physically the same metal).
    i_src = np.where(mesh.x <= p.Ln)[0]
    ii, kk = np.meshgrid(i_src, kk_all, indexing="ij")
    dev.add_contact("source", i=ii.ravel(), j=np.zeros(ii.size, dtype=int),
                    k=kk.ravel(), V=0.0)

    # Gate: the trench sidewall -- x=0 face, restricted to y <= Dtrench.
    j_trench = np.where(mesh.y <= p.Dtrench)[0]
    Vfb = flatband_voltage(-p.Na_body, p.tox_cm, p.gate, 0.0, p.T, p.material)
    jj, kk = np.meshgrid(j_trench, kk_all, indexing="ij")
    dev.add_gate("gate", i=np.zeros(jj.size, dtype=int), j=jj.ravel(),
                k=kk.ravel(), tox_cm=p.tox_cm, Vfb=Vfb, Vg=0.0,
                normal_axis="x")

    # Drain: full-area ohmic, bottom face.
    ii, kk = np.meshgrid(np.arange(mesh.Nx), kk_all, indexing="ij")
    dev.add_contact("drain", i=ii.ravel(),
                    j=np.full(ii.size, mesh.Ny - 1, dtype=int),
                    k=kk.ravel(), V=0.0)
    return dev
