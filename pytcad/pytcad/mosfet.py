"""Analytic 2D MOSFET doping and structure builder.

Doping is built directly from closed-form functions rather than a 2D
process simulation (see design spec section on deferred work): a uniform
p-type channel background, plus Gaussian-in-depth x erfc-lateral-rolloff
source/drain profiles -- the standard closed-form stand-in for lateral
straggle under a mask edge, used the same way teaching-scale 2D TCAD
tools build a first structure.

Domain convention: x in [0, 2*Lsd + Lg], source region x <= Lsd, gate
region Lsd < x < Lsd+Lg, drain region x >= Lsd+Lg; y=0 is the silicon
surface, y increasing into the substrate.
"""

import numpy as np
from scipy.special import erfc

from .mesh2d import Mesh2D
from .mesh import graded_mesh
from .device2d import Device2D
from .device import NewtonOptions
from .materials import SILICON
from .moscap import flatband_voltage


def _sd_profile(x, y, x_edge, sigma_y, sigma_lat, Npeak, high_side):
    """Gaussian-in-depth x erfc-lateral-rolloff doping [cm^-3].

    high_side='left'  -> full strength for x < x_edge (source)
    high_side='right' -> full strength for x > x_edge (drain)
    """
    vertical = np.exp(-(y[:, None]) ** 2 / (2.0 * sigma_y ** 2))       # (Ny,1)
    s = (x_edge - x) if high_side == "left" else (x - x_edge)          # (Nx,)
    lateral = 0.5 * erfc(-s[None, :] / (np.sqrt(2.0) * sigma_lat))     # (1,Nx)
    return Npeak * vertical * lateral                                  # (Ny,Nx)


def mosfet_doping(mesh: Mesh2D, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat):
    """Net doping and total ionised impurity concentration [cm^-3] for a
    MOSFET on the given mesh, both shape (Ny, Nx).

    Na        : channel/substrate acceptor concentration [cm^-3], p-type
    Nsd_peak  : source/drain peak donor concentration [cm^-3], n-type
    sigma_y   : source/drain vertical (depth) straggle [cm]
    sigma_lat : source/drain lateral straggle under the gate edge [cm]
    """
    x, y = mesh.x, mesh.y
    channel = -Na * np.ones((mesh.Ny, mesh.Nx))
    source = _sd_profile(x, y, Lsd, sigma_y, sigma_lat, Nsd_peak, "left")
    drain = _sd_profile(x, y, Lsd + Lg, sigma_y, sigma_lat, Nsd_peak, "right")

    doping = channel + source + drain
    Ntotal = np.abs(channel) + source + drain     # source/drain already >= 0
    return doping, Ntotal


def build_mosfet(Lg, Lsd, depth, Na, Nsd_peak, tox_cm, gate="n+poly",
                 Qf=0.0, sigma_y=None, sigma_lat=None, T=300.0,
                 material=SILICON, nx=120, ny=60):
    """Build a ready-to-solve n-channel MOSFET Device2D.

    Domain: x in [0, 2*Lsd+Lg] (source | gate | drain), y in [0, depth]
    (surface at y=0).  sigma_y/sigma_lat default to Lg/4 if not given --
    reasonable for a first structure, tune for sharper/softer junctions.
    """
    sigma_y = sigma_y if sigma_y is not None else Lg / 4.0
    sigma_lat = sigma_lat if sigma_lat is not None else Lg / 4.0

    L = 2 * Lsd + Lg
    x = graded_mesh(L, [Lsd, Lsd + Lg], h_min=L / (nx * 20), h_max=L / nx, ratio=1.15)
    y = graded_mesh(depth, [0.0], h_min=depth / (ny * 20), h_max=depth / ny, ratio=1.15)
    mesh = Mesh2D(x, y)

    doping, Ntotal = mosfet_doping(mesh, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat)
    dev = Device2D(mesh, doping, Ntotal=Ntotal, T=T, material=material)

    i_source = np.where(mesh.x <= Lsd)[0]
    i_gate = np.where((mesh.x > Lsd) & (mesh.x < Lsd + Lg))[0]
    i_drain = np.where(mesh.x >= Lsd + Lg)[0]

    dev.add_contact("source", i=i_source, j=np.zeros_like(i_source), V=0.0)
    dev.add_contact("drain", i=i_drain, j=np.zeros_like(i_drain), V=0.0)
    dev.add_contact("body", i=np.arange(mesh.Nx), j=np.full(mesh.Nx, mesh.Ny - 1), V=0.0)

    Vfb = flatband_voltage(-Na, tox_cm, gate, Qf, T, material)
    dev.add_gate("gate", i=i_gate, j=np.zeros_like(i_gate), tox_cm=tox_cm, Vfb=Vfb, Vg=0.0)
    return dev


def id_vg_sweep(dev, Vg_list, Vds, opts: NewtonOptions = None, verbose=True):
    """Ramp gate voltage at fixed Vds, source and body held at 0 V.
    Returns Id [A/cm] at each Vg.  Reseeds each solve from the previous
    converged point, same pattern as Device1D.iv_sweep."""
    opts = opts or NewtonOptions()
    dev.solve_equilibrium(opts)
    Id = []
    for Vg in Vg_list:
        dev.solve_bias({"drain": Vds, "gate": Vg}, opts)
        I = dev.terminal_current("drain")
        Id.append(I)
        if verbose:
            print(f"  Vg = {Vg:+.3f} V   Id = {I:+.6e} A/cm")
    return np.array(Id)
