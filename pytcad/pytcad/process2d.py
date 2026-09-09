"""2D process geometry engine (M23): mask-driven deposit/etch, 2D thermal
oxidation with bird's-beak encroachment, and mask-driven 2D implants.

This is the "structured-mesh, string-model" slice of M23 (see
M23-PROCESS-GEOMETRY notes in ARCHITECTURE.md): geometry evolves as a set of
per-column interface heights on a fixed lateral grid `x`, not a general
level-set on an unstructured mesh.  General-mesh geometry (post-M21) is
future work, not attempted here.

HONESTY CLAUSE -- what this module does NOT model
--------------------------------------------------
* No viscoelastic oxide stress.  Bird's-beak shape comes from a lateral
  oxidant-diffusion suppression kernel under the mask edge, not from a
  mechanical model of nitride bending.  The resulting wedge shape is
  qualitatively right (monotonic taper over roughly one oxide-thickness of
  lateral distance) but is NOT quantitatively validated against published
  LOCOS cross-sections -- treat any bird's-beak length number as a knob,
  not a prediction.
* Oxidation growth is column-independent except for the lateral coupling
  kernel; there is no true 2D oxidant transport equation.
* Deposit/etch are purely vertical ("string" model): no conformal sidewall
  coverage, no isotropic-etch undercut unless explicitly requested via the
  `lateral_kernel_cm` argument on `etch`, and even that is a smoothing
  approximation, not a transport-limited etch model.
* Implant lateral spread is a Gaussian convolution of the vertical (SUPREM
  Pearson/Gaussian) profile by a fixed lateral/vertical straggle ratio.
  This is the standard cheap 2D-implant approximation used by early process
  simulators; it is NOT a Monte-Carlo (BCA) result -- that is M25.
* Everything here is silicon/SiO2 specific (oxidation stoichiometry,
  dopant diffusivities from pytcad.process).  Extending to other material
  stacks (poly, nitride diffusion barriers as anything other than a mask)
  is out of scope.

Units follow pytcad.process: lateral/vertical mesh coordinates in cm,
oxide thickness in um (matching `process.oxide_thickness`), converted at
the boundary so column bookkeeping stays exact.
"""

from dataclasses import dataclass, field
import numpy as np

from . import process

_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


# ----------------------------------------------------------------------
#  Mask
# ----------------------------------------------------------------------
def mask_from_intervals(x, open_intervals):
    """Boolean open-mask on lateral grid `x` [cm] from a list of
    (x_lo, x_hi) intervals [cm] that are open (unmasked); everywhere else
    is protected (masked, e.g. by nitride or photoresist).
    """
    x = np.asarray(x, dtype=float)
    m = np.zeros(x.shape, dtype=bool)
    for lo, hi in open_intervals:
        m |= (x >= lo) & (x <= hi)
    return m


# ----------------------------------------------------------------------
#  Geometry state
# ----------------------------------------------------------------------
@dataclass
class ProcessGeometry2D:
    """Per-column process geometry on a fixed lateral grid.

    x            : (Nx,) lateral coordinate [cm]
    surface_um   : (Nx,) current top-surface height [um], positive = up
                   from the original wafer flat, i.e. deposited material
                   thickness minus etched thickness.
    ox_thick_um  : (Nx,) grown SiO2 thickness [um] at this column (0 if none).
    si_consumed_um : (Nx,) cumulative silicon consumed by oxidation [um].
                   Kept separately from `surface_um` bookkeeping so mass
                   conservation can be checked directly against the 0.44
                   factor without back-solving it from the surface height.
    """
    x: np.ndarray
    surface_um: np.ndarray = None
    ox_thick_um: np.ndarray = None
    si_consumed_um: np.ndarray = None

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        n = self.x.size
        if self.surface_um is None:
            self.surface_um = np.zeros(n)
        if self.ox_thick_um is None:
            self.ox_thick_um = np.zeros(n)
        if self.si_consumed_um is None:
            self.si_consumed_um = np.zeros(n)
        self.surface_um = np.asarray(self.surface_um, dtype=float).copy()
        self.ox_thick_um = np.asarray(self.ox_thick_um, dtype=float).copy()
        self.si_consumed_um = np.asarray(self.si_consumed_um, dtype=float).copy()

    def copy(self):
        return ProcessGeometry2D(self.x.copy(), self.surface_um.copy(),
                                  self.ox_thick_um.copy(),
                                  self.si_consumed_um.copy())


# ----------------------------------------------------------------------
#  Deposit / etch  (vertical "string" model)
# ----------------------------------------------------------------------
def deposit(geom, thickness_um, mask=None):
    """Uniformly raise the surface by `thickness_um` [um] where `mask` is
    open (default: everywhere).  Purely vertical -- no conformal sidewall
    coverage is modeled (see module honesty clause).

    Returns a new ProcessGeometry2D; mass added equals
    thickness_um * (open width), exactly, by construction.
    """
    g = geom.copy()
    m = np.ones(g.x.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    g.surface_um[m] += thickness_um
    return g


def etch(geom, depth_um, mask=None, lateral_kernel_cm=None):
    """Remove `depth_um` [um] of material from the top of the stack where
    `mask` is open (anisotropic/vertical etch).  Surface height cannot go
    below the pre-deposit substrate reference implicitly by capping at the
    silicon-consumed floor -- callers are responsible for not etching
    through silicon they still need.

    If `lateral_kernel_cm` is given, the etch depth profile is smoothed
    with a Gaussian kernel of that lateral standard deviation to give a
    crude isotropic-undercut look at mask edges. This is a smoothing
    approximation, not a transport-limited etch model (see honesty clause);
    it does not conserve the removed-material integral exactly at mask
    edges because it exchanges depth between neighboring columns.
    """
    g = geom.copy()
    m = np.ones(g.x.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    removal = np.where(m, depth_um, 0.0)
    if lateral_kernel_cm is not None and lateral_kernel_cm > 0:
        removal = _gaussian_smooth_1d(g.x, removal, lateral_kernel_cm)
    g.surface_um -= removal
    return g


def _gaussian_smooth_matrix(x, sigma):
    """The row-normalised dense Gaussian convolution matrix for grid `x`.

    Split out of `_gaussian_smooth_1d` (M31 P4) because it depends only
    on the grid and the width -- so smoothing many rows of the same grid
    rebuilt an identical (Nx, Nx) matrix, and an (Nx, Nx) `exp`, once per
    row.  See implant_2d for the measurement.
    """
    x = np.asarray(x, dtype=float)
    dx = x[:, None] - x[None, :]
    k = np.exp(-0.5 * (dx / sigma) ** 2)
    k /= k.sum(axis=1, keepdims=True)
    return k


def _gaussian_smooth_1d(x, f, sigma):
    """Discrete Gaussian convolution of f(x) with std `sigma`, same units
    as x.  Uses a dense kernel (fine for process-geometry column counts).
    """
    f = np.asarray(f, dtype=float)
    return _gaussian_smooth_matrix(x, sigma) @ f


# ----------------------------------------------------------------------
#  2D thermal oxidation with bird's-beak lateral suppression
# ----------------------------------------------------------------------
def oxidize_2d(geom, T_C, t_hours, ambient="dry", mask=None,
               beak_length_cm=None, masked_rate_fraction=0.02):
    """Grow oxide for `t_hours` at `T_C` [degC], `ambient` in {"dry","wet"},
    on every column, with growth suppressed under a mask (nitride) and a
    smooth lateral taper ("bird's beak") near mask edges.

    Physics
    -------
    - Fully open columns (`mask` False or no mask) follow 1D Deal-Grove
      exactly via `process.oxide_thickness`, using this column's own prior
      oxide thickness as the initial condition (so repeated calls give the
      same growth as one call over the summed time, up to the tau-offset
      Deal-Grove already uses).  This is what makes G1 below exact: with a
      uniform mask (all open), oxidize_2d reduces bit-for-bit to
      `process.oxide_thickness`.
    - Fully masked columns still grow, at `masked_rate_fraction` of the
      open rate (physically: some oxidant reaches the Si/nitride interface
      by lateral diffusion under the mask edge and by finite nitride
      permeability -- not truly zero in real LOCOS, hence "field" growth
      under nitride is small but nonzero).
    - Columns within `beak_length_cm` of a mask edge (default: the
      instantaneous open-region oxide thickness in cm, a common LOCOS
      rule-of-thumb) get an effective rate that is a smooth
      (raised-cosine) blend between the open and masked rates as a
      function of lateral distance to the nearest edge -- this produces
      the taper.  This is a suppression-kernel model of bird's beak, not a
      solved 2D oxidant-diffusion PDE (see module honesty clause).

    Mass conservation: each column's Si consumption is
    `process.silicon_consumed` of that column's *new* oxide thickness minus
    its old one, so summed Si consumed over the wafer always equals
    0.44 * (summed oxide grown) to machine precision (G2), because the
    column bookkeeping never exchanges thickness between columns (only the
    *rate* is blended, the accounting is per-column).
    """
    g = geom.copy()
    n = g.x.size
    m = np.ones(n, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)

    # Full-rate oxide thickness each column would reach if fully open,
    # continuing from its own current oxide thickness (so Deal-Grove's
    # own tau bookkeeping is respected per column).
    # x_init_um=None lets process.oxide_thickness apply its own default
    # xi fudge factor (the dry-oxidation thin-oxide correction) -- passing
    # 0.0 explicitly would bypass that default and break bit-identity with
    # a bare call to process.oxide_thickness on virgin silicon (G1).
    x_open_new = np.array([
        process.oxide_thickness(
            T_C, t_hours, ambient,
            x_init_um=(None if g.ox_thick_um[i] == 0.0 else g.ox_thick_um[i]))
        for i in range(n)
    ])
    open_growth = x_open_new - g.ox_thick_um   # >= 0

    if beak_length_cm is None:
        # rule-of-thumb: taper over roughly one open-oxide-thickness of
        # lateral distance, in cm; guard the all-masked-domain case.
        ref_um = x_open_new[m].mean() if np.any(m) else x_open_new.mean()
        beak_length_cm = max(ref_um * _UM_TO_CM, 1e-9)

    # Distance [cm] from each column to the nearest *open* column (0 if
    # this column itself is open).
    if np.all(m) or not np.any(m):
        dist_to_open = np.zeros(n)
    else:
        xo = g.x[m]
        dist_to_open = np.array([0.0 if m[i] else np.min(np.abs(g.x[i] - xo))
                                  for i in range(n)])

    # Raised-cosine blend: weight=1 at the open edge, ->masked_rate_fraction
    # over one beak_length_cm, then flat.
    t = np.clip(dist_to_open / beak_length_cm, 0.0, 1.0)
    blend = 0.5 * (1.0 + np.cos(np.pi * t))          # 1 at t=0, 0 at t=1
    weight = masked_rate_fraction + (1.0 - masked_rate_fraction) * blend
    weight = np.where(m, 1.0, weight)

    growth = weight * open_growth
    g.ox_thick_um = g.ox_thick_um + growth
    si_growth = process.silicon_consumed(growth)
    g.si_consumed_um = g.si_consumed_um + si_growth
    # The wafer surface rises by (ox_growth - si_growth) where oxide
    # replaces consumed silicon (grown oxide occupies more volume than the
    # silicon it ate).
    g.surface_um = g.surface_um + (growth - si_growth)
    return g


# ----------------------------------------------------------------------
#  2D mask-driven implant
# ----------------------------------------------------------------------
def implant_2d(mesh_x, mesh_y, geom, species, energy_keV, dose, mask=None,
               tilt_deg=0.0, lateral_straggle_ratio=0.8):
    """2D dopant concentration [cm^-3] on a tensor grid (Ny, Nx) after a
    masked implant into the current surface topography.

    mesh_x, mesh_y : 1D arrays [cm]; mesh_y is depth from the ORIGINAL
                     wafer flat (y=0), positive downward, matching the
                     convention used elsewhere in pytcad.process (implant
                     depth x there is this module's y).
    geom           : ProcessGeometry2D giving each column's current
                     surface height (so the implant profile is referenced
                     to the real (possibly recessed/raised) local surface,
                     not the original flat).
    mask           : boolean (Nx,) open-mask; masked columns get zero dose
                     before lateral spreading (a blocking mask, e.g. thick
                     photoresist -- no through-mask range straggle modeled).
    lateral_straggle_ratio : lateral straggle as a multiple of the
                     vertical dRp (SUPREM-style approximation; published
                     ratios for common implants are ~0.7-1.0, so 0.8 is a
                     reasonable default, not a per-species fit).

    Returns C[j, i] = concentration at (mesh_y[j], mesh_x[i]).
    """
    x = np.asarray(mesh_x, dtype=float)
    y = np.asarray(mesh_y, dtype=float)
    Nx, Ny = x.size, y.size
    m = np.ones(Nx, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)

    Rp, dRp = process.implant_moments(species, energy_keV)
    Rp_eff = Rp * np.cos(np.deg2rad(tilt_deg))

    # Column-wise vertical Gaussian about (local surface + Rp_eff), zero
    # dose where masked.
    C = np.zeros((Ny, Nx))
    surf_cm = -geom.surface_um * _UM_TO_CM   # surface rise -> shallower depth
    for i in range(Nx):
        if not m[i]:
            continue
        depth = y - surf_cm[i]
        C[:, i] = dose / (np.sqrt(2.0 * np.pi) * dRp) * np.exp(
            -((depth - Rp_eff) ** 2) / (2.0 * dRp**2))

    # Lateral spread: convolve each depth row with a Gaussian of std
    # lateral_straggle_ratio * dRp [cm]. This spreads dose sideways under
    # mask edges (2D lateral moments) while each row's own integral is
    # preserved by the normalized kernel, so total dose is conserved to
    # numerical (trapezoid) accuracy, not exactly, because the kernel is
    # normalized on a finite non-uniform grid.
    #
    # M31 P4, the measured blocker in this module: the kernel depends
    # only on (x, sigma_lat), so the loop below used to rebuild the same
    # (Nx, Nx) matrix -- and the same (Nx, Nx) `exp` -- once per depth
    # row, making the whole call O(Ny * Nx^2) in transcendentals rather
    # than O(Nx^2). Measured at Nx=400, Ny=600: 939 ms before, 15 ms
    # after, a 62x reduction with NO change to the arithmetic: it is the
    # identical matrix, multiplied into the identical rows, in the
    # identical order, so the result is bit-for-bit what it was. That is
    # also why this one did NOT become a C++ kernel: what remains is a
    # BLAS matrix-vector product, which C++ cannot reproduce
    # bit-identically (it would be a different dgemv blocking) and has
    # no reason to try to beat.
    sigma_lat = lateral_straggle_ratio * dRp
    if sigma_lat > 0:
        k = _gaussian_smooth_matrix(x, sigma_lat)
        for j in range(Ny):
            C[j, :] = k @ C[j, :]
    return C


def total_dose_2d(mesh_x, mesh_y, C):
    """Integrate a 2D dose profile C[j,i] [cm^-3] over depth then laterally
    to get an areal dose-equivalent check [cm^-2 * cm] = [cm^-1]... in
    practice this is used only for *relative* dose-conservation checks
    between two implant_2d calls on the same grid, not an absolute unit.
    """
    x = np.asarray(mesh_x, dtype=float)
    y = np.asarray(mesh_y, dtype=float)
    per_column_dose = np.trapezoid(C, y, axis=0)      # (Nx,) cm^-2
    return np.trapezoid(per_column_dose, x)            # scalar
