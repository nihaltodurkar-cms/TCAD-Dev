"""Elementwise numerical primitives shared by every solver in the core.

These four functions plus `D0_REF` were defined in `device.py` and then
imported OUT of it -- as private-by-convention internals -- by
`device2d.py`, `device3d.py`, `unstructured_dd.py`, `unstructured_dd3d.py`
and `moscap.py`.  That made a 1900-line module fusing 1D mesh setup,
physics, discretization and the Newton driver into a load-bearing
dependency of code that wanted none of it.

They live here instead because they are what they look like: pure,
stateless, vectorized float64 kernels with no notion of a mesh, a device
or a solve.  That is also exactly the property that makes them the first
candidates for a compiled implementation -- `bernoulli`/`dbernoulli` are
evaluated on every edge of every Jacobian assembly, in every dimension.

`device.py` re-exports all five names, so every existing import site
keeps working unchanged.

Depends only on numpy and `fermi`; imports nothing from `device*`, so
there is no cycle.
"""
import numpy as np

from .fermi import FERMI_ETA_MAX, FERMI_ETA_MIN, f_half, f_mhalf

__all__ = ["D0_REF", "fd_density", "fd_ddensity_deta",
           "bernoulli", "dbernoulli"]

D0_REF = 1.0  # reference diffusivity for scaling [cm^2/s]


# ----------------------------------------------------------------------
#  M13 Fermi-Dirac helpers (asymmetric eta policy -- see docstrings)
# ----------------------------------------------------------------------
def fd_density(nc, eta):
    """n = nc * F_{1/2}(eta) with the M13 asymmetric eta policy.

    Below eta = -35 the integral switches to its EXACT Boltzmann tail
    exp(eta): the FD deviation there is exp(eta)/2^{3/2} <= 2.5e-16
    RELATIVE -- below double precision and MORE accurate than evaluating
    the quadrature on a 1e-12-scale value (minority carriers reach
    eta ~ -170 at cryogenic temperature).  Above FERMI_ETA_MAX we refuse
    loudly -- beyond +40 the parabolic-band model itself is invalid (G7
    applicability); no silent extrapolation.  The branches agree to
    ~2e-16 at the crossover."""
    eta = np.asarray(eta, dtype=float)
    if np.any(eta > FERMI_ETA_MAX):
        raise ValueError(
            f"FD density argument eta={eta.max():.1f} exceeds "
            f"+{FERMI_ETA_MAX:.0f}: outside the validated Fermi-integral "
            f"range (M13 G7 applicability).  Refusing to extrapolate.")
    shp = np.broadcast_shapes(np.shape(nc), eta.shape)
    e1 = np.broadcast_to(np.asarray(eta, dtype=float), shp).ravel()
    c1 = np.broadcast_to(np.asarray(nc, dtype=float), shp).ravel()
    lo = e1 < -35.0
    # f_half's fixed-node quadrature is vectorized over 1-D inputs
    # only -- flatten, evaluate, restore (any-shape grids supported).
    out = np.where(lo,
                   c1 * np.exp(np.minimum(e1, 700.0)),
                   c1 * f_half(np.clip(e1, FERMI_ETA_MIN,
                                       FERMI_ETA_MAX)))
    return out.reshape(shp)


def fd_ddensity_deta(nc, eta):
    """d(nc F(eta))/d(eta) matching fd_density piecewise: f_mhalf
    inside the validated range, the exact tail derivative nc*exp(eta)
    below FERMI_ETA_MIN, loud refusal above."""
    eta = np.asarray(eta, dtype=float)
    if np.any(eta > FERMI_ETA_MAX):
        raise ValueError(
            f"FD density argument eta={eta.max():.1f} exceeds "
            f"+{FERMI_ETA_MAX:.0f} (M13 G7 applicability).")
    shp = np.broadcast_shapes(np.shape(nc), eta.shape)
    e1 = np.broadcast_to(np.asarray(eta, dtype=float), shp).ravel()
    c1 = np.broadcast_to(np.asarray(nc, dtype=float), shp).ravel()
    lo = e1 < -35.0
    tail = np.exp(np.minimum(e1, 700.0))
    out = np.where(lo, c1 * tail,
                   c1 * f_mhalf(np.clip(e1, FERMI_ETA_MIN,
                                        FERMI_ETA_MAX)))
    return out.reshape(shp)


# ----------------------------------------------------------------------
#  Bernoulli function and its derivative (numerically stable)
# ----------------------------------------------------------------------
def bernoulli(x):
    """B(x) = x / (exp(x) - 1), with B(0) = 1."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)          # dummy to avoid 0/0
    out = np.where(small,
                   1.0 - x / 2.0 + x * x / 12.0,
                   xs / np.expm1(xs))
    return out


def dbernoulli(x):
    """dB/dx, computed as B(x) [1/x - 1/(1 - e^-x)] for stability."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)
    B = np.where(small, 1.0, xs / np.expm1(xs))
    em = -np.expm1(-xs)                   # 1 - exp(-x)
    em = np.where(np.abs(em) < 1e-300, 1e-300, em)
    full = B * (1.0 / xs - 1.0 / em)
    series = -0.5 + x / 6.0 - x**3 / 180.0
    return np.where(small, series, full)
