"""3D drift-diffusion device simulator: box-integration finite volumes on
a structured tensor-product grid (Mesh3D), generalizing device2d.py's
edge-scatter architecture with a third axis.  Same equations, same
scaling convention, same physics models as 1D/2D -- validated by
z-invariant reduction to Device2D (see tests), the primary correctness
gate for this module.

ASSEMBLY STRATEGY
------------------
Same edge-scatter pattern as device2d.py: each x/y/z-edge contributes a
flux to its two endpoint nodes, weighted by the AREA of the control-
volume face it crosses (the product of the OTHER two axes' widths --
dVy*dVz for x-edges, dVx*dVz for y-edges, dVx*dVy for z-edges).  A
boundary node simply has fewer edges touching it, giving implicit
zero-flux Neumann for free -- unchanged from 2D, just one more axis.

GATE BOUNDARY CONDITION
------------------------
Unlike 2D (where the gate was always on a y=const surface), a 3D gate
can sit on a face normal to any of the three axes.  GateBC carries an
explicit normal_axis ('x', 'y', or 'z'); the residual/Jacobian assembly
picks the matching face-AREA weight.  This module only exercises
normal_axis='z' in its own tests, but the mechanism supports the other
two orientations from the start -- a future wrapped-gate device (FinFET,
GAA) needs this, not a redesigned BC class.

The gate's flux term also includes a LOCAL bulk reference potential
(psi_b_local = arcsinh(C/(2*nie_s)), computed per node), matching
moscap.py's validated 1D formula exactly.  Device2D's gate BC originally
shipped without this term -- a real bug only caught once a full MOSFET
existed to expose it.  Built in correctly here from the start.
"""

import warnings

import numpy as np
from scipy.sparse import csr_matrix

# M31 P4b: symmetric Dirichlet elimination -- see pytcad/dirichlet.py.
from .btbt import M0_SI as _NL_M0, Q_SI as _NL_Q
from .nonlocal_path import build_structured as _nl_build_structured
from .nonlocal_path import evaluate as _nl_evaluate
from .dirichlet import eliminate_csr
from .ii_grid import grid_impact as _ii_grid
from .btbt_grid import grid_btbt as _btbt_grid
from .ii_nonlocal_grid import effective_field_grid as _ii_eff_grid
from .device import (_II_STAGES, _LS_MAX_HALVINGS, _LS_NEWTON_REGION,
                     _STIFF_DENSITY_FLOOR)

from . import linsolve

from .constants import KB_EV, Q, EPS0, thermal_voltage
from .schottky import schottky_barrier_height_n as _schottky_barrier_height_n
from .materials import (
    SILICON, SIC_4H, Semiconductor, mobility_caughey_thomas, mobility_field,
    nie_effective, lifetime_scharfetter, recombination,
)
from .device import (D0_REF, bernoulli, dbernoulli, fd_density,
                     fd_ddensity_deta, fd_node_factors, fd_ohmic_values,
                     ionized_dE_kt, ionized_doping, ionized_eta_doping,
                     Models, NewtonOptions)
from .fermi import FERMI_ETA_MAX
from .mesh3d import Mesh3D
from .mesh2d import control_volume_widths
from .moscap import EPS_OX_R
from .constants import KB
from . import hydrodynamic as _hydro
from .hydro_grid import grid_hydro as _grid_hydro


# ----------------------------------------------------------------------
#  Boundary conditions
# ----------------------------------------------------------------------
class DirichletBC:
    """Ohmic contact: fixed voltage at a set of (i,j,k) grid nodes."""

    def __init__(self, i, j, k, V=0.0):
        self.i = np.atleast_1d(np.asarray(i, dtype=int))
        self.j = np.atleast_1d(np.asarray(j, dtype=int))
        self.k = np.atleast_1d(np.asarray(k, dtype=int))
        self.V = float(V)


class PinnedBC:
    """An interior interface pinned directly to given per-node state
    values (psi0, and for the bias/DD system also n0/p0) -- NOT derived
    from a contact voltage via the equilibrium ohmic relations
    (_bc_contact_values), unlike DirichletBC.

    Used by MPI Schwarz domain decomposition (gui/services/
    mpi_schwarz.py): splitting a device into subdomains creates
    artificial internal boundaries that must track whatever the
    NEIGHBORING subdomain's current iterate says there -- an arbitrary
    field value exchanged over MPI each Schwarz sweep, not a physical
    ohmic contact. Structurally handled identically to DirichletBC in
    both _residual_jacobian_poisson and _residual_jacobian (same row-
    replacement treatment), just sourcing its target values directly
    instead of computing them from a voltage.
    """

    def __init__(self, i, j, k, psi0, n0=None, p0=None):
        self.i = np.atleast_1d(np.asarray(i, dtype=int))
        self.j = np.atleast_1d(np.asarray(j, dtype=int))
        self.k = np.atleast_1d(np.asarray(k, dtype=int))
        self.psi0 = np.atleast_1d(np.asarray(psi0, dtype=float))
        self.n0 = None if n0 is None else np.atleast_1d(np.asarray(n0, dtype=float))
        self.p0 = None if p0 is None else np.atleast_1d(np.asarray(p0, dtype=float))


class GateBC:
    """Gate/oxide coupling (Robin condition on psi only) at a set of
    silicon-surface (i,j,k) grid nodes, on a face normal to normal_axis."""

    def __init__(self, i, j, k, kappa, Vfb, Vg=0.0, normal_axis='z'):
        self.i = np.atleast_1d(np.asarray(i, dtype=int))
        self.j = np.atleast_1d(np.asarray(j, dtype=int))
        self.k = np.atleast_1d(np.asarray(k, dtype=int))
        self.kappa = float(kappa)
        self.Vfb = float(Vfb)
        self.Vg = float(Vg)
        if normal_axis not in ('x', 'y', 'z'):
            raise ValueError(
                f"normal_axis must be 'x', 'y', or 'z', got {normal_axis!r}")
        self.normal_axis = normal_axis


class SchottkyBC(DirichletBC):
    """M46-S3: a metal-semiconductor (Schottky) contact -- the Device3D
    lift of Device1D's SchottkyContact / Device2D's SchottkyBC. A
    DirichletBC SUBCLASS (not a new dispatch branch), for the same
    reason as Device2D's own SchottkyBC: every existing
    `isinstance(bc, DirichletBC)` site treats it correctly already,
    since a Schottky contact's psi row is a Dirichlet row (barrier-
    referenced) here too.

    ONLY the S1 Dirichlet approximation is implemented in Device3D
    (see add_schottky_contact's own docstring for why the S2 Robin
    mode is refused): the majority-carrier density is pinned at its
    barrier-limited equilibrium value through the SAME psi0 formula
    an ohmic DirichletBC already uses."""

    def __init__(self, i, j, k, phi_metal_eV, A_star=None, V=0.0):
        super().__init__(i, j, k, V)
        self.phi_metal_eV = float(phi_metal_eV)
        self.A_star = None if A_star is None else float(A_star)


def _ohmic_values(C, nie, V, VT):
    """Ohmic contact: local charge neutrality + thermal equilibrium.
    Dimension-agnostic -- always evaluate the MAJORITY carrier from the
    quadratic and get the minority one from the mass-action law, to
    avoid cancellation (same as device.py/device2d.py)."""
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


def _edge_pairs_x(Nx, Ny, Nz):
    """Flat node index pairs for x-direction edges: (Nz,Ny,Nx-1) edges."""
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny, 0:Nx - 1]
    kL = (kk * Nx * Ny + jj * Nx + ii).ravel()
    kR = kL + 1
    return kL, kR


def _edge_pairs_y(Nx, Ny, Nz):
    """Flat node index pairs for y-direction edges: (Nz,Ny-1,Nx) edges."""
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny - 1, 0:Nx]
    kS = (kk * Nx * Ny + jj * Nx + ii).ravel()
    kN = kS + Nx
    return kS, kN


def _edge_pairs_z(Nx, Ny, Nz):
    """Flat node index pairs for z-direction edges: (Nz-1,Ny,Nx) edges."""
    kk, jj, ii = np.mgrid[0:Nz - 1, 0:Ny, 0:Nx]
    kD = (kk * Nx * Ny + jj * Nx + ii).ravel()    # "down" (smaller z)
    kU = kD + Nx * Ny                              # "up" (larger z)
    return kD, kU


# ----------------------------------------------------------------------
#  M47 Slice 2a groundwork: the base-assembly COO stamps (Poisson flux,
#  electron/hole continuity, local diagonal terms) factored into named,
#  PURE (no closure-captured mutable state) block functions -- the
#  structured-grid analogue of unstructured_dd3d.py's own M47 Slice 1
#  block functions (_poisson_flux_geometry_coo etc.), same reasoning:
#  isolation for a future C++ port's raw-COO parity test, and each
#  block independently testable.
#
#  CONCATENATION IS ASSOCIATIVE, UNLIKE ADDITION -- this refactor is
#  lower-risk than Slice 1's own was for exactly this reason. The
#  original `_residual_jacobian` builds `rows`/`cols`/`vals` as plain
#  Python LISTS, `.extend()`/`.append()`-ed by call order, concatenated
#  EXACTLY ONCE at the end (`rows = np.concatenate(rows)`). Grouping
#  those same sub-arrays into named functions that each return their
#  OWN already-concatenated (rows,cols,vals) does not change the FINAL
#  flat element order at all -- `np.concatenate([a,b,c,d])` is bit-
#  identical to `np.concatenate([np.concatenate([a,b]), np.concatenate(
#  [c,d])])` (concatenation preserves element order regardless of how
#  the pieces are grouped, exactly unlike floating-point summation).
#  So this split is safe by construction, verified by direct digest
#  comparison below rather than re-derived from first principles the
#  way Slice 1's COO/F ordering had to be.
# ----------------------------------------------------------------------
def _scatter3_coo(kL, kR, weight, row_comp, comp_L, dL, comp_R, dR):
    """One axis's edge-Jacobian stamp -- the SAME formula
    `Device3D._residual_jacobian`'s own (now-removed) nested `scatter()`
    closure used, made pure (returns arrays instead of mutating a
    captured list) so it can be called from a block function instead of
    only from inside `_residual_jacobian` itself."""
    w = weight.ravel(); dL = dL.ravel(); dR = dR.ravel()
    rows = np.concatenate([3 * kL + row_comp, 3 * kL + row_comp,
                           3 * kR + row_comp, 3 * kR + row_comp])
    cols = np.concatenate([3 * kL + comp_L, 3 * kR + comp_R,
                           3 * kL + comp_L, 3 * kR + comp_R])
    vals = np.concatenate([w * dL, w * dR, -w * dL, -w * dR])
    return rows, cols, vals


def _poisson_flux_row_coo(kLx, kRx, wx_h, kSy, kNy, wy_h, kDz, kUz, wz_h):
    """Poisson row (comp 0), x THEN y THEN z -- exact call order of the
    original 3 `scatter()` calls."""
    rx, cx, vx = _scatter3_coo(kLx, kRx, wx_h, 0, 0, -np.ones_like(wx_h),
                               0, np.ones_like(wx_h))
    ry, cy, vy = _scatter3_coo(kSy, kNy, wy_h, 0, 0, -np.ones_like(wy_h),
                               0, np.ones_like(wy_h))
    rz, cz, vz = _scatter3_coo(kDz, kUz, wz_h, 0, 0, -np.ones_like(wz_h),
                               0, np.ones_like(wz_h))
    return (np.concatenate([rx, ry, rz]), np.concatenate([cx, cy, cz]),
           np.concatenate([vx, vy, vz]))


def _electron_continuity_coo(kLx, kRx, wx_area, dJn_dpsiR_x, dJn_dn_L_x, dJn_dn_R_x,
                             kSy, kNy, wy_area, dJn_dpsiR_y, dJn_dn_L_y, dJn_dn_R_y,
                             kDz, kUz, wz_area, dJn_dpsiR_z, dJn_dn_L_z, dJn_dn_R_z):
    """Electron continuity row (comp 1) -- x-psi, x-n, y-psi, y-n,
    z-psi, z-n, exact call order of the original 6 `scatter()` calls."""
    parts = [
        _scatter3_coo(kLx, kRx, wx_area, 1, 0, -dJn_dpsiR_x, 0, dJn_dpsiR_x),
        _scatter3_coo(kLx, kRx, wx_area, 1, 1, dJn_dn_L_x, 1, dJn_dn_R_x),
        _scatter3_coo(kSy, kNy, wy_area, 1, 0, -dJn_dpsiR_y, 0, dJn_dpsiR_y),
        _scatter3_coo(kSy, kNy, wy_area, 1, 1, dJn_dn_L_y, 1, dJn_dn_R_y),
        _scatter3_coo(kDz, kUz, wz_area, 1, 0, -dJn_dpsiR_z, 0, dJn_dpsiR_z),
        _scatter3_coo(kDz, kUz, wz_area, 1, 1, dJn_dn_L_z, 1, dJn_dn_R_z),
    ]
    return (np.concatenate([x[0] for x in parts]),
           np.concatenate([x[1] for x in parts]),
           np.concatenate([x[2] for x in parts]))


def _hole_continuity_coo(kLx, kRx, wx_area, dJp_dpsiR_x, dJp_dp_L_x, dJp_dp_R_x,
                         kSy, kNy, wy_area, dJp_dpsiR_y, dJp_dp_L_y, dJp_dp_R_y,
                         kDz, kUz, wz_area, dJp_dpsiR_z, dJp_dp_L_z, dJp_dp_R_z):
    """Hole continuity row (comp 2) -- x-psi, x-p, y-psi, y-p, z-psi,
    z-p, exact call order of the original 6 `scatter()` calls."""
    parts = [
        _scatter3_coo(kLx, kRx, wx_area, 2, 0, -dJp_dpsiR_x, 0, dJp_dpsiR_x),
        _scatter3_coo(kLx, kRx, wx_area, 2, 2, dJp_dp_L_x, 2, dJp_dp_R_x),
        _scatter3_coo(kSy, kNy, wy_area, 2, 0, -dJp_dpsiR_y, 0, dJp_dpsiR_y),
        _scatter3_coo(kSy, kNy, wy_area, 2, 2, dJp_dp_L_y, 2, dJp_dp_R_y),
        _scatter3_coo(kDz, kUz, wz_area, 2, 0, -dJp_dpsiR_z, 0, dJp_dpsiR_z),
        _scatter3_coo(kDz, kUz, wz_area, 2, 2, dJp_dp_L_z, 2, dJp_dp_R_z),
    ]
    return (np.concatenate([x[0] for x in parts]),
           np.concatenate([x[1] for x in parts]),
           np.concatenate([x[2] for x in parts]))


def _base_diagonal_coo(diag_k, dV, dcden, dcdp, dRs_dn, dRs_dp):
    """Local (same-node) diagonal terms: Poisson's charge term (two
    forms depending on incomplete_ion), then SRH n-row, then SRH
    p-row -- exact order/branch of the original 6 `append()` calls."""
    dVf = dV.ravel()
    rows, cols, vals = [], [], []
    if dcden is None:
        rows.append(3 * diag_k); cols.append(3 * diag_k + 1); vals.append(-dVf)
        rows.append(3 * diag_k); cols.append(3 * diag_k + 2); vals.append(dVf)
    else:
        rows.append(3 * diag_k); cols.append(3 * diag_k + 1)
        vals.append(-dVf * (1.0 - dcden.ravel()))
        rows.append(3 * diag_k); cols.append(3 * diag_k + 2)
        vals.append(dVf * (1.0 + dcdp.ravel()))

    rows.append(3 * diag_k + 1); cols.append(3 * diag_k + 1)
    vals.append(-dRs_dn.ravel() * dVf)
    rows.append(3 * diag_k + 1); cols.append(3 * diag_k + 2)
    vals.append(-dRs_dp.ravel() * dVf)

    rows.append(3 * diag_k + 2); cols.append(3 * diag_k + 2)
    vals.append(dRs_dp.ravel() * dVf)
    rows.append(3 * diag_k + 2); cols.append(3 * diag_k + 1)
    vals.append(dRs_dn.ravel() * dVf)
    return (np.concatenate(rows), np.concatenate(cols), np.concatenate(vals))


# ----------------------------------------------------------------------
#  Device
# ----------------------------------------------------------------------
class Device3D:
    """A 3D semiconductor device on a structured Mesh3D.

    Parameters
    ----------
    mesh     : Mesh3D
    doping   : net doping N_D - N_A [cm^-3], shape (Nz, Ny, Nx) or flat (N,)
    Ntotal   : total ionised impurity concentration for mobility/lifetime
               models [cm^-3]; defaults to |doping|
    Ns_override : force the reference concentration (normally
               max(|doping|, ni)) to a given value instead of deriving
               it from THIS device's own doping array. Every downstream
               dimensionless quantity is scaled from Ns -- not just
               psi/n/p but LD, J0, and even the mesh coordinates
               themselves (xs = mesh.x / LD) -- so two Device3D
               instances covering DIFFERENT spatial slices of the SAME
               physical device (gui/services/mpi_schwarz_runner.py's
               domain-decomposed subdomains) would otherwise silently
               disagree on units unless both are pinned to the same
               reference derived from the FULL device's doping range.
               None (default) is the original, bit-identical behavior.
    """

    def __init__(self, mesh: Mesh3D, doping, Ntotal=None, T=300.0,
                 material: Semiconductor = SILICON, models: Models = None,
                 Ns_override=None):
        self.mesh = mesh
        self.Nx, self.Ny, self.Nz, self.N = mesh.Nx, mesh.Ny, mesh.Nz, mesh.N
        self.doping = np.asarray(doping, dtype=float).reshape(
            self.Nz, self.Ny, self.Nx)
        self.Ntot = (np.abs(self.doping) if Ntotal is None
                     else np.asarray(Ntotal, dtype=float).reshape(
                         self.Nz, self.Ny, self.Nx))
        self.T = T
        # M11-S4: a single Semiconductor keeps the classic behavior; a
        # flat per-node sequence (row-major, length Nx*Ny*Nz) defines a
        # 3D heterostructure -- same conventions as Device1D/Device2D.
        if isinstance(material, Semiconductor):
            self.mats = [material] * self.N
        else:
            mats_flat = list(material)
            if len(mats_flat) != self.N:
                raise ValueError(
                    "material list length must equal Nx*Ny*Nz "
                    f"({self.N}); got {len(mats_flat)}")
            if not all(isinstance(m, Semiconductor) for m in mats_flat):
                raise TypeError("material entries must be Semiconductor")
            self.mats = mats_flat
        self.mat = material if isinstance(material, Semiconductor) \
            else self.mats[0]
        self.models = models or Models()
        if self.models.field_mobility:
            raise NotImplementedError(
                "Canali field-dependent mobility is not implemented in "
                "Device3D (see design spec, deferred items)."
            )
        if self.models.S_n != 0.0 or self.models.S_p != 0.0:
            raise NotImplementedError(
                "Models.S_n/S_p (M14 surface recombination velocity) is "
                "implemented in Device1D and Device2D only -- never in "
                "the M14 plan's scope for Device3D. Refusing rather than "
                "silently ignoring the flag.")
        # Models(impact=True): M15's coupled model, ported by M34-S6
        # (pytcad/ii_grid.py; see _residual_jacobian and solve_bias).
        # Models(impact_nonlocal=True): S6c, the same effective field on
        # the grid (pytcad/ii_nonlocal_grid.py) -- same precondition as
        # Device1D (M34-S2): needs impact=True, needs a positive lambda.
        if getattr(self.models, "impact_nonlocal", False):
            if not getattr(self.models, "impact", False):
                raise ValueError(
                    "Models(impact_nonlocal=True) modifies the impact-"
                    "ionization coefficients and needs Models(impact=True) "
                    "as well.")
            for lam in (self.models.impact_lambda_n,
                        self.models.impact_lambda_p):
                if not lam > 0.0:
                    raise ValueError(
                        f"impact_lambda_n/p must be > 0 cm, got {lam}")
        # M34-S3: nonlocal path BTBT (field-line paths, pytcad/
        # nonlocal_path.py).  Homojunction only, as in Device1D/Device2D.
        if getattr(self.models, "btbt_nonlocal", False) and any(
                mm is not self.mats[0] for mm in self.mats):
            raise NotImplementedError(
                "Models(btbt_nonlocal=True) is homojunction-only (M34 "
                "scope) -- this device has more than one material. "
                "Refusing rather than applying a single-material formula "
                "across a hetero boundary.")
        self._btbt_nl_paths = None
        self.last_btbt_nl_refreshes = 0
        self.last_btbt_nl_stable = None
        self.last_converged = None
        # M34-S6: M15's generation-strength multiplier (see _II_STAGES),
        # the last stamped generation (scaled, zero at contacts), its
        # Jacobian, and the fields alpha was evaluated at.
        self._ii_strength = 1.0
        self._ii_gs_cache = None
        self._ii_jac_cache = None
        self._ii_fields = None
        # M16-S2: local BTBT's last stamped generation (scaled, zero at
        # contacts) and the node field it was evaluated at.
        self._btbt_gs_cache = None
        self._btbt_fields = None
        # Models(btbt=True): M16-S2, local Kane BTBT on the structured
        # grid (pytcad/btbt_grid.py) -- a dimensional lift of the
        # already-gated Device1D model, no new constant.  No lambda-style
        # precondition and no heterojunction restriction.
        # M42-S3: density-gradient quantum correction, ported to Device3D
        # from Device2D's S1/S2 coupled-Newton (psi, Lambda_n, Lambda_p)
        # equilibrium solve (M42-DENSITY-GRADIENT-2D3D-PLAN.md section
        # 10.8). Same refusal shape as Device1D/Device2D: dg+fd,
        # dg+incomplete_ion, dg+band_offset="affinity", and dg+SIC_4H
        # are all unvalidated compositions there and stay refused here.
        if getattr(self.models, "dg", False):
            if getattr(self.models, "fd", False):
                raise NotImplementedError(
                    "Models(dg=True, fd=True) is refused: the DG "
                    "correction was derived and gated against Boltzmann "
                    "statistics only (M20 scope, unchanged by the 3D "
                    "port).")
            if getattr(self.models, "incomplete_ion", False):
                raise NotImplementedError(
                    "Models(dg=True, incomplete_ion=True) is refused "
                    "(unvalidated composition, matching Device1D/2D).")
            if self.models.band_offset == "affinity":
                raise NotImplementedError(
                    "Models(band_offset='affinity', dg=True) is refused "
                    "(unvalidated composition, matching Device1D/2D).")
            if any(m is SIC_4H for m in self.mats):
                raise NotImplementedError(
                    "Models(dg=True) with SIC_4H is refused: "
                    "SIC_4H.m_n_star/m_p_star are documented placeholders "
                    "(materials.py's 4H-SiC block), not a validated "
                    "effective-mass fit, and the DG quantum correction "
                    "uses that mass directly -- refusing rather than "
                    "silently reporting a confinement number built on an "
                    "unvalidated input (M42-DENSITY-GRADIENT-2D3D-PLAN.md "
                    "section 10.3(d), same judgment as Device2D's S2).")
        # M41: Models(incomplete_ion=True) is implemented here as well
        # now -- the M13 shallow-dopant model on the same grid
        # (device.py's ionized_doping, shared with Device1D/Device2D),
        # entering Poisson's charge term as rho = n - p - C_ion.
        # Independent of the fd flag, exactly as in 1D.  See
        # M41-INCOMPLETE-ION-2D3D-PLAN.md.
        if getattr(self.models, "thermionic", False):
            raise NotImplementedError(
                "Thermionic-emission interface flux (Models(thermionic="
                "True)) is implemented in Device1D only (M33-S2 scope; "
                "2D/3D ports are a follow-up slice).  Refusing rather "
                "than silently ignoring the flag."
            )

        self.fd = bool(getattr(self.models, "fd", False))
        self.dg = bool(getattr(self.models, "dg", False))
        self._dg_Lam_n = None
        self._dg_Lam_p = None
        if self.Ntot.max() > 1e19 and not self.fd:
            warnings.warn(
                "Doping exceeds ~1e19 cm^-3: Boltzmann statistics used here "
                "overestimate the carrier density. Treat results in the "
                "degenerate regions as qualitative."
            )

        self.VT = thermal_voltage(T)
        self.eps_arr = np.array([m.eps_r * EPS0 for m in self.mats])
        self.eps0 = float(self.eps_arr[0])   # reference (legacy scalar)
        self.eps = self.eps0                 # legacy attribute name
        self.ni = self.mats[0].ni(T)

        self.Ns = (max(float(np.abs(self.doping).max()), self.ni)
                  if Ns_override is None else float(Ns_override))
        self.LD = np.sqrt(self.eps * self.VT / (Q * self.Ns))
        self.J0 = Q * D0_REF * self.Ns / self.LD
        self.R0 = D0_REF * self.Ns / self.LD ** 2

        # M44 Slice 4: same scaling constants as Device1D/Device2D's
        # own (identical derivation) -- see M44-HYDRODYNAMIC-PLAN.md.
        self._ALPHA_RELAX = (1.5 * KB * self.T * self.Ns * self.LD
                             / (_hydro.TAU_W_N * self.J0 * self.VT))
        self._KAPPA0 = (2.5 * (KB * KB / Q) * self.Ns * self.T * self.T
                        / (self.LD * self.J0 * self.VT))
        self.Tn = None

        self.xs = mesh.x / self.LD
        self.ys = mesh.y / self.LD
        self.zs = mesh.z / self.LD
        self.hx = np.diff(self.xs)
        self.hy = np.diff(self.ys)
        self.hz = np.diff(self.zs)
        self.dVx = control_volume_widths(self.hx)
        self.dVy = control_volume_widths(self.hy)
        self.dVz = control_volume_widths(self.hz)
        self.dV = (self.dVz[:, None, None] * self.dVy[None, :, None]
                   * self.dVx[None, None, :])    # (Nz,Ny,Nx), scaled volume

        self.C = self.doping / self.Ns
        # M41 (incomplete ionization): single-species per node -- the
        # majority side carries all dopants, because a net-doping
        # profile cannot say otherwise.  Device1D/Device2D's convention.
        self.nd_arr = np.maximum(self.doping, 0.0) / self.Ns   # scaled N_D
        self.na_arr = np.maximum(-self.doping, 0.0) / self.Ns  # scaled N_A

        # M11-S4: per-material grouping (mirrors Device1D/Device2D).
        shp = (self.Nz, self.Ny, self.Nx)
        nie_f = np.empty(self.N); mu_n_f = np.empty(self.N)
        mu_p_f = np.empty(self.N); taun_f = np.empty(self.N)
        taup_f = np.empty(self.N); nc_f = np.empty(self.N)
        nv_f = np.empty(self.N); egkt_f = np.empty(self.N)
        seen_mats = []
        for mm in self.mats:
            if not any(mm is m2 for m2 in seen_mats):
                seen_mats.append(mm)
        nt_flat = self.Ntot.ravel()
        for m in seen_mats:
            nodes = np.array([mm is m for mm in self.mats])
            nt = nt_flat[nodes]
            nie_f[nodes] = nie_effective(nt, m, T, self.models.bgn)
            mu_n_f[nodes] = (
                mobility_caughey_thomas(nt, m, T, "n")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_n_max))
            mu_p_f[nodes] = (
                mobility_caughey_thomas(nt, m, T, "p")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_p_max))
            taun_f[nodes] = lifetime_scharfetter(nt, m.tau_n0,
                                                 m.tau_Nref)
            taup_f[nodes] = lifetime_scharfetter(nt, m.tau_p0,
                                                 m.tau_Nref)
            nc_f[nodes] = m.Nc(T)
            nv_f[nodes] = m.Nv(T)
            egkt_f[nodes] = m.Eg(T) / KB_EV / T
        self.nie = nie_f.reshape(shp)
        self.nie_s = self.nie / self.Ns

        # M13 fd DOS: per-node grids (composes with heterojunctions)
        self.nc_s = nc_f.reshape(shp) / self.Ns
        self.nv_s = nv_f.reshape(shp) / self.Ns
        self.ln_gn = np.log(self.nc_s / self.nie_s)
        self.ln_gp = np.log(self.nv_s / self.nie_s)
        self.eg_kt = egkt_f.reshape(shp)

        # --- M33-S5: band-alignment shift, ported from Device2D's S4
        # (device2d.py's own band_shift construction; see
        # M33-S5-PLAN.md section 0 for the full derivation). ONE
        # per-node offset referenced to node (0, 0, 0), identically
        # zero for a homojunction, so the default "nie" gauge stays
        # bit-identical BY CONSTRUCTION (every new term below is an
        # exact +0.0), not by tolerance. ---
        self.chi_arr = np.array([m.chi for m in self.mats]).reshape(shp)
        if self.models.band_offset == "affinity":
            if self.fd or getattr(self.models, "incomplete_ion", False):
                raise NotImplementedError(
                    "Models(band_offset='affinity') with fd/"
                    "incomplete_ion is refused: "
                    "the FD eta-space contact solver and neutral-guess "
                    "bisection both carry their own ln(Nc/nie) offset, "
                    "and composing them with the affinity shift has not "
                    "been derived or gated here (Device1D's S1/Device2D's "
                    "S4 give the same refusal for the same reason).")
            s = self.ln_gn + self.chi_arr / self.VT
            self.band_shift = s - s.flat[0]
        else:
            self.band_shift = np.zeros(shp)

        self.mu_n0 = mu_n_f.reshape(shp)
        self.mu_p0 = mu_p_f.reshape(shp)

        self.tau_n = taun_f.reshape(shp)
        self.tau_p = taup_f.reshape(shp)

        # M11-S4: harmonic-mean scaled permittivity on edges,
        # normalized by the FIRST node's eps (uniform => exactly 1.0,
        # so every residual reduces ALGEBRAICALLY to the legacy form).
        et = (self.eps_arr / self.eps0).reshape(shp)

        def hmean3d(lo, hi):
            return 2.0 * lo * hi / (lo + hi)

        self.et_x = hmean3d(et[:, :, :-1], et[:, :, 1:])
        self.et_y = hmean3d(et[:, :-1, :], et[:, 1:, :])
        self.et_z = hmean3d(et[:-1, :, :], et[1:, :, :])

        def hmean(lo, hi):
            return 2.0 * lo * hi / (lo + hi)

        self.dn_edge_x = hmean(self.mu_n0[:, :, :-1], self.mu_n0[:, :, 1:]) * self.VT / D0_REF
        self.dp_edge_x = hmean(self.mu_p0[:, :, :-1], self.mu_p0[:, :, 1:]) * self.VT / D0_REF
        self.dn_edge_y = hmean(self.mu_n0[:, :-1, :], self.mu_n0[:, 1:, :]) * self.VT / D0_REF
        self.dp_edge_y = hmean(self.mu_p0[:, :-1, :], self.mu_p0[:, 1:, :]) * self.VT / D0_REF
        self.dn_edge_z = hmean(self.mu_n0[:-1, :, :], self.mu_n0[1:, :, :]) * self.VT / D0_REF
        self.dp_edge_z = hmean(self.mu_p0[:-1, :, :], self.mu_p0[1:, :, :]) * self.VT / D0_REF

        self.bcs = {}   # name -> DirichletBC | GateBC
        self.psi = self.n = self.p = None
        # (id(bc), V) -> (psi0, n0, p0): _bc_contact_values solves a
        # per-node charge-neutrality root (FD: ~60-iteration vectorized
        # bisection over tabulated Fermi-Dirac integrals) that depends
        # only on the contact's fixed node set/doping/material and the
        # requested V -- all invariant across an entire Newton solve
        # (V is fixed for the whole solve_equilibrium/solve_bias call).
        # Every caller (_residual_jacobian_poisson/_residual_jacobian,
        # every Newton iteration; ac.py/continuation.py/transient.py
        # calling _residual_jacobian repeatedly at the same voltages)
        # was redoing that root-find from scratch each time -- profiled
        # at 66% of a 25-iteration solve_equilibrium's wall time on a
        # 5040-node mesh. Safe to cache for the object's lifetime: T,
        # VT, C, nc_s, nv_s, ln_gn, eg_kt are all set once in __init__
        # and never mutated afterward, and add_contact/add_gate always
        # install a brand-new BC object (new id()) rather than mutating
        # node indices in place.
        self._bc_value_cache = {}

    # ------------------------------------------------------------------
    def _update_energy_mobility(self, theta):
        """M44: recompute EVERY edge diffusivity from the Tn-consistent
        Canali mobility -- Device2D's own `_update_energy_mobility`
        twin (see device2d.py and M44-HYDRODYNAMIC-PLAN.md Slice 4)."""
        Tn = theta * self.T
        E_eff = _hydro.effective_field_from_temperature(
            Tn, self.mu_n0, _hydro.TAU_W_N, self.T)
        mu_n = mobility_field(self.mu_n0, E_eff, self.mat, "n")
        mu_p = mobility_field(self.mu_p0, E_eff, self.mat, "p")

        def hmean(lo, hi):
            return 2.0 * lo * hi / (lo + hi)

        self.dn_edge_x = hmean(mu_n[:, :, :-1], mu_n[:, :, 1:]) * self.VT / D0_REF
        self.dp_edge_x = hmean(mu_p[:, :, :-1], mu_p[:, :, 1:]) * self.VT / D0_REF
        self.dn_edge_y = hmean(mu_n[:, :-1, :], mu_n[:, 1:, :]) * self.VT / D0_REF
        self.dp_edge_y = hmean(mu_p[:, :-1, :], mu_p[:, 1:, :]) * self.VT / D0_REF
        self.dn_edge_z = hmean(mu_n[:-1, :, :], mu_n[1:, :, :]) * self.VT / D0_REF
        self.dp_edge_z = hmean(mu_p[:-1, :, :], mu_p[1:, :, :]) * self.VT / D0_REF

    # ------------------------------------------------------------------
    def add_contact(self, name, i, j, k, V=0.0):
        self.bcs[name] = DirichletBC(i, j, k, V)
        return self.bcs[name]

    def add_gate(self, name, i, j, k, tox_cm, Vfb, Vg=0.0, normal_axis='z'):
        eps_ox = EPS_OX_R * EPS0
        kappa = eps_ox * self.LD / (self.eps * tox_cm)
        self.bcs[name] = GateBC(i, j, k, kappa, Vfb, Vg, normal_axis)
        return self.bcs[name]

    def add_schottky_contact(self, name, i, j, k, phi_metal_eV, A_star=None, V=0.0):
        """M46-S3: add a Schottky contact -- the Device3D lift of
        Device1D/Device2D's SchottkyContact/SchottkyBC. ONLY the S1
        Dirichlet approximation is implemented here (A_star must be
        None): Device3D has no M14 S_n/S_p Robin-BC machinery to reuse
        (see the constructor's own S_n/S_p refusal a few lines above
        this method) -- the S2 Robin thermionic-flux BC would need
        that machinery built from scratch first, which is out of this
        slice's scope. See SchottkyBC's own docstring."""
        if A_star is not None:
            raise NotImplementedError(
                "SchottkyBC(A_star=...) (M46-S2's Robin thermionic-flux "
                "BC) is refused in Device3D: it reuses Device1D/"
                "Device2D's own M14 S_n/S_p Robin-BC machinery, which "
                "Device3D does not have (see this class's own S_n/S_p "
                "refusal). Only the Dirichlet approximation (A_star="
                "None) is implemented here -- M46-S3's own scope.")
        self.bcs[name] = SchottkyBC(i, j, k, phi_metal_eV, A_star, V)
        return self.bcs[name]

    def _bulk_psi_guess(self):
        """Neutral-bulk potential per node (FD eta-space root or the
        classic arcsinh)."""
        ion = self._ion_root_args()
        # M41: freeze-out moves the neutral potential, so the Boltzmann
        # arcsinh guess is wrong under incomplete ionization for the
        # same reason it is wrong under FD -- Device1D's equilibrium
        # takes the eta-space branch on `fd or ion` too.
        if not self.fd and ion is None:
            # M33-S5: the neutral guess is a statement about the
            # CARRIER law, so it is derived in the shifted variable;
            # -band_shift brings it back to the electrostatic
            # potential the Poisson flux is written in (identical
            # reasoning to Device1D/2D's own equilibrium guess).
            return np.arcsinh(self.C / (2.0 * self.nie_s)) - self.band_shift
        lo0 = -self.eg_kt - 80.0
        hi = np.full(self.C.shape, float(FERMI_ETA_MAX))

        def g(e):
            n_ = fd_density(self.nc_s, np.minimum(e, FERMI_ETA_MAX))
            p_ = fd_density(self.nv_s,
                            np.minimum(-e - self.eg_kt, FERMI_ETA_MAX))
            if ion is None:
                return n_ - p_ - self.C
            c_, _, _ = ionized_eta_doping(
                self.nd_arr, self.na_arr, np.minimum(e, FERMI_ETA_MAX),
                np.minimum(-e - self.eg_kt, FERMI_ETA_MAX),
                ionized_dE_kt(self.T))
            return n_ - p_ - c_

        flo, fhi = g(lo0), g(hi)
        if np.any(flo > 0) or np.any(fhi < 0):
            raise ValueError("3D FD bulk guess: root not bracketed")
        lo = np.full(self.C.shape, lo0)
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            left = g(mid) < 0
            lo = np.where(left, mid, lo)
            hi = np.where(left, hi, mid)
            if np.all(hi - lo < 1e-13 * (1.0 + np.abs(lo))):
                break
        e0 = 0.5 * (lo + hi)
        if np.any(e0 > FERMI_ETA_MAX - 2.0):
            raise ValueError(
                "FD substrate eta beyond the validated range (G7).")
        return e0 + self.ln_gn

    def _ionized_C(self, n, p):
        """M41: net ionized doping (scaled) and d/dn, d/dp, from the
        shared M13 kernel -- see device.py's `ionized_doping`, which
        Device1D and Device2D call identically."""
        return ionized_doping(self.nd_arr, self.na_arr, n, p,
                              self.nc_s, self.nv_s, self.T)

    def _ion_root_args(self):
        """`ion=` payload for fd_ohmic_values' neutrality root, or None
        under full ionization."""
        if getattr(self.models, "incomplete_ion", False):
            return (self.nd_arr, self.na_arr, self.T)
        return None

    def _poisson_charge(self, psi, n, p, dnp):
        """M41: Poisson's charge term and its d/dpsi under the
        equilibrium slaving, for either statistics.

        rho = n - p - C_ion, so the slaved-density chain picks up
        d(rho)/dpsi = (1-dcden) dn/dpsi + (1+dcdp) |dp/dpsi| -- eta_p
        FALLS as psi rises, which cancels the carrier sign.  Returns
        (c_eff, dnp); identical to Device1D's own equilibrium block."""
        if not getattr(self.models, "incomplete_ion", False):
            return self.C, dnp
        cion, dcden, dcdp = self._ionized_C(n, p)
        if self.fd:
            dn_dpsi = fd_ddensity_deta(
                self.nc_s, np.minimum(psi - self.ln_gn, FERMI_ETA_MAX))
            dp_dpsi = fd_ddensity_deta(
                self.nv_s, np.minimum(-psi - self.ln_gp, FERMI_ETA_MAX))
        else:
            dn_dpsi, dp_dpsi = n, p
        return cion, dnp - dcden * dn_dpsi + dcdp * dp_dpsi

    def _fd_slaved_densities(self, psi):
        """Equilibrium slaving under FD + d(n+p)/d(psi).

        eta is clamped to FERMI_ETA_MAX before evaluating (matching the
        np.minimum(..., FERMI_ETA_MAX) guard used for the bulk-guess
        bisection above) so a transient Newton overshoot cannot abort
        the whole solve when the converged answer would be valid."""
        en = np.minimum(psi - self.ln_gn, FERMI_ETA_MAX)
        ep = np.minimum(-psi - self.ln_gp, FERMI_ETA_MAX)
        n = fd_density(self.nc_s, en)
        p = fd_density(self.nv_s, ep)
        dnp = fd_ddensity_deta(self.nc_s, en) \
            + fd_ddensity_deta(self.nv_s, ep)
        return n, p, dnp

    def _bc_contact_values(self, bc, V):
        """Ohmic values at a contact's nodes (M11-S4 per-node materials;
        M13 FD-aware).  Memoized per (bc, V): pure function of fixed
        per-node data and the requested V (see the cache comment in
        __init__) -- callers hit this every Newton iteration with the
        SAME V, so recomputation here would be pure waste.  M33-S5:
        n0/p0 are gauge-free, only psi0's reference moves, by
        -band_shift[k,j,i] (identical reasoning to Device1D/2D's own
        contact-value fix)."""
        key = (id(bc), float(V))
        cached = self._bc_value_cache.get(key)
        if cached is not None:
            return cached
        k, j, i = bc.k, bc.j, bc.i
        ion = self._ion_root_args()
        # M46-S3: a SchottkyBC replaces the local-neutrality majority
        # density with the barrier-limited one (reusing schottky.py's
        # own schottky_barrier_height_n, not re-derived) -- a direct
        # lift of Device1D/Device2D's own Schottky branch. Refused
        # under fd/incomplete_ion (unvalidated composition, matching
        # both lower dimensions' own refusal).
        if isinstance(bc, SchottkyBC):
            if self.fd or ion is not None:
                raise NotImplementedError(
                    "SchottkyBC combined with Models(fd=True) or "
                    "incomplete_ion=True is refused: the barrier-"
                    "referenced majority density was only derived "
                    "against Boltzmann statistics (M46-S3 scope, "
                    "matching Device1D/Device2D's own refusal).")
            C, nie = self.C[k, j, i], self.nie_s[k, j, i]
            phi_m, chi_eV = bc.phi_metal_eV, self.chi_arr[k, j, i]
            is_n = C >= 0.0
            phi_Bn = _schottky_barrier_height_n(phi_m, chi_eV)
            Eg_eV = np.array([self.mats[kk_ * self.Nx * self.Ny + jj_ * self.Nx + ii_].Eg(self.T)
                              for kk_, jj_, ii_ in zip(np.atleast_1d(k), np.atleast_1d(j), np.atleast_1d(i))])
            phi_B = np.where(is_n, phi_Bn, Eg_eV - phi_Bn)
            n0 = np.where(is_n, self.nc_s[k, j, i] * np.exp(-phi_B / (KB_EV * self.T)),
                         nie * nie / np.maximum(
                             self.nv_s[k, j, i] * np.exp(-phi_B / (KB_EV * self.T)),
                             1e-300))
            p0 = np.where(is_n, nie * nie / np.maximum(n0, 1e-300),
                         self.nv_s[k, j, i] * np.exp(-phi_B / (KB_EV * self.T)))
            psi0 = V / self.VT + np.log(n0 / nie)
            out = (psi0 - self.band_shift[k, j, i], n0, p0)
            self._bc_value_cache[key] = out
            return out
        # M41: incomplete ionization routes through the SAME eta-space
        # root even under Boltzmann statistics (it reduces exactly to
        # the closed form as F -> exp), so the flag stays independent
        # of `fd` -- Device1D's _contact_values does the same.
        if self.fd or ion is not None:
            psi0, n0, p0 = fd_ohmic_values(self.C[k, j, i], self.nc_s[k, j, i],
                                  self.nv_s[k, j, i],
                                  self.ln_gn[k, j, i],
                                  self.eg_kt[k, j, i], V, self.VT,
                                  ion=None if ion is None
                                  else (self.nd_arr[k, j, i],
                                        self.na_arr[k, j, i], self.T))
        else:
            psi0, n0, p0 = _ohmic_values(self.C[k, j, i], self.nie_s[k, j, i],
                                V, self.VT)
        out = (psi0 - self.band_shift[k, j, i], n0, p0)
        self._bc_value_cache[key] = out
        return out

    def _gate_face_weight(self, bc: GateBC):
        """Control-volume face AREA the gate's flux crosses, per node,
        depending on which axis the gate's face is normal to."""
        if bc.normal_axis == 'z':
            return self.dVx[bc.i] * self.dVy[bc.j]
        elif bc.normal_axis == 'y':
            return self.dVx[bc.i] * self.dVz[bc.k]
        else:  # 'x'
            return self.dVy[bc.j] * self.dVz[bc.k]

    # ------------------------------------------------------------------
    #  Poisson-only residual/Jacobian (used by solve_equilibrium)
    # ------------------------------------------------------------------
    def _residual_jacobian_poisson(self, psi):
        Nx, Ny, Nz, N = self.Nx, self.Ny, self.Nz, self.N
        hx, hy, hz = self.hx, self.hy, self.hz
        dVx, dVy, dVz, dV = self.dVx, self.dVy, self.dVz, self.dV
        C, nie = self.C, self.nie_s

        if self.fd:
            n, p, dnp = self._fd_slaved_densities(psi)
        else:
            # M33-S5: carriers are slaved to psi + band_shift, not psi
            # alone (identical to Device1D/2D's own psi_c). Identically
            # psi on the default "nie" gauge.
            psi_c = psi + self.band_shift
            n = nie * np.exp(np.clip(psi_c, -700, 700))
            p = nie * np.exp(np.clip(-psi_c, -700, 700))
            dnp = n + p
        # M41: rho = n - p - C_ion under EITHER statistics; C is
        # returned unchanged when the flag is off, so this path stays
        # bit-identical.
        C, dnp = self._poisson_charge(psi, n, p, dnp)

        # M11-S4: position-dependent eps in flux form (uniform => 1.0)
        Fx = self.et_x * (psi[:, :, 1:] - psi[:, :, :-1]) / hx[None, None, :]
        Fy = self.et_y * (psi[:, 1:, :] - psi[:, :-1, :]) / hy[None, :, None]
        Fz = self.et_z * (psi[1:, :, :] - psi[:-1, :, :]) / hz[:, None, None]

        div_x = np.zeros((Nz, Ny, Nx)); div_x[:, :, :-1] += Fx; div_x[:, :, 1:] -= Fx
        div_y = np.zeros((Nz, Ny, Nx)); div_y[:, :-1, :] += Fy; div_y[:, 1:, :] -= Fy
        div_z = np.zeros((Nz, Ny, Nx)); div_z[:-1, :, :] += Fz; div_z[1:, :, :] -= Fz

        F = (dVy[None, :, None] * dVz[:, None, None] * div_x
           + dVx[None, None, :] * dVz[:, None, None] * div_y
           + dVx[None, None, :] * dVy[None, :, None] * div_z
           - dV * (n - p - C))

        kLx, kRx = _edge_pairs_x(Nx, Ny, Nz)
        wx = np.broadcast_to(dVy[None, :, None] * dVz[:, None, None] / hx[None, None, :],
                              (Nz, Ny, Nx - 1)).ravel()
        kSy, kNy = _edge_pairs_y(Nx, Ny, Nz)
        wy = np.broadcast_to(dVx[None, None, :] * dVz[:, None, None] / hy[None, :, None],
                              (Nz, Ny - 1, Nx)).ravel()
        kDz, kUz = _edge_pairs_z(Nx, Ny, Nz)
        wz = np.broadcast_to(dVx[None, None, :] * dVy[None, :, None] / hz[:, None, None],
                              (Nz - 1, Ny, Nx)).ravel()

        rows = np.concatenate([kLx, kRx, kLx, kRx, kSy, kNy, kSy, kNy,
                                kDz, kUz, kDz, kUz])
        cols = np.concatenate([kLx, kRx, kRx, kLx, kSy, kNy, kNy, kSy,
                                kDz, kUz, kUz, kDz])
        vals = np.concatenate([-wx, -wx, wx, wx, -wy, -wy, wy, wy,
                                -wz, -wz, wz, wz])

        diag_k = np.arange(N)
        diag_v = (-dV * dnp).ravel()
        rows = np.concatenate([rows, diag_k])
        cols = np.concatenate([cols, diag_k])
        vals = np.concatenate([vals, diag_v])

        # --- Robin (gate) BC: add Gauss's-law flux, weighted by the
        # face area and referenced to the local bulk potential ---
        F_flat = F.ravel()
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                w = self._gate_face_weight(bc)
                Vg_s, Vfb_s = 0.0, bc.Vfb / self.VT   # equilibrium: gate at zero bias too
                # M33-S5: same -band_shift reference as _bulk_psi_guess;
                # identically 0 on the default "nie" gauge.
                psi_b_local = (np.arcsinh(
                    self.C[bc.k, bc.j, bc.i] / (2.0 * self.nie_s[bc.k, bc.j, bc.i]))
                    - self.band_shift[bc.k, bc.j, bc.i])
                F_flat[kk] += bc.kappa * w * (
                    Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows = np.concatenate([rows, kk])
                cols = np.concatenate([cols, kk])
                vals = np.concatenate([vals, -bc.kappa * w])

        # --- Dirichlet (contact) BC: replace the row entirely, always
        # at V = 0 -- equilibrium is by definition the zero-bias solve ---
        contact_k = []
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                psi0 = self._bc_contact_values(bc, 0.0)[0]
                F_flat[kk] = psi.ravel()[kk] - psi0
                contact_k.append(kk)
            elif isinstance(bc, PinnedBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                F_flat[kk] = psi.ravel()[kk] - bc.psi0
                contact_k.append(kk)
        if contact_k:
            contact_k = np.unique(np.concatenate(contact_k))
            keep = ~np.isin(rows, contact_k)
            rows, cols, vals = rows[keep], cols[keep], vals[keep]
            rows = np.concatenate([rows, contact_k])
            cols = np.concatenate([cols, contact_k])
            vals = np.concatenate([vals, np.ones_like(contact_k, dtype=float)])

        J = csr_matrix((vals, (rows, cols)), shape=(N, N))
        self._dirichlet_rows_poisson = (
            np.asarray(contact_k, dtype=int) if len(contact_k)
            else np.zeros(0, dtype=int))
        return F, J

    # ------------------------------------------------------------------
    def _dg_residual_jacobian_eq(self, psi, Lam_n, Lam_p, gamma=None):
        """M42-S3 coupled-Newton DG residual/Jacobian for Device3D
        equilibrium: interleaved unknowns [psi_k, Lambda_n_k, Lambda_p_k]
        per flat node k = kk*Nx*Ny+jj*Nx+ii, a direct lift of Device2D's
        own _dg_residual_jacobian_eq (device2d.py) one axis further --
        see that method's docstring for the full physics/BC rationale
        (M42-S1/S2), unchanged here except for the extra z axis.

        Poisson row: identical box-integration flux-divergence assembly
        as _residual_jacobian_poisson, DG-corrected densities, two new
        Jacobian columns per node. The gate (Robin) BC is a direct copy
        of _residual_jacobian_poisson's own gate block (this device's
        GateBC carries a normal_axis, but the Lambda hard wall below
        does not care which face a gate sits on -- the infinite-barrier
        limit applies to the whole node).

        Lambda_n/Lambda_p rows: pytcad/dg_grid.py's dg_lambda_rows, the
        SAME dimension-generic kernel Device2D now calls (M42-S3's own
        extraction) -- here with 3 axes instead of 2. Reduces EXACTLY
        to Device2D's own answer for a z-uniform device (this port's
        S3-G-REDUCTION gate), which itself already reduces to
        Device1D's non-uniform three-point second derivative.

        Boundary treatment: DirichletBC and PinnedBC nodes both pin
        Lambda_n=Lambda_p=0 (both are "the potential here is fixed"
        contacts in the classical Poisson row already -- see
        _residual_jacobian_poisson's own contact_k construction, which
        groups them identically). GateBC nodes not also a contact pin
        Lambda to LAMBDA_MAX_VT*VT (M42-S2's hard wall).

        Returns (F [3N], J [3N x 3N] csr_matrix); sets
        self._dg_dirichlet_rows_eq.
        """
        from .dg import LAMBDA_MAX_VT
        from .dg_grid import dg_lambda_rows
        Nx, Ny, Nz, N = self.Nx, self.Ny, self.Nz, self.N
        VT = self.VT
        gamma = getattr(self.models, "dg_gamma", 1.0) if gamma is None else gamma
        hx, hy, hz = self.hx, self.hy, self.hz
        dVx, dVy, dVz, dV = self.dVx, self.dVy, self.dVz, self.dV
        nie = self.nie_s

        psi_c = psi + self.band_shift
        e = np.clip(psi_c, -700, 700)
        n = nie * np.exp(e) * np.exp(-Lam_n / VT)
        p = nie * np.exp(-e) * np.exp(-Lam_p / VT)
        dnp = n + p
        rho = n - p - self.C

        # ---- Poisson row (identical structure to
        # _residual_jacobian_poisson, DG-corrected densities) ----------
        Fx = self.et_x * (psi[:, :, 1:] - psi[:, :, :-1]) / hx[None, None, :]
        Fy = self.et_y * (psi[:, 1:, :] - psi[:, :-1, :]) / hy[None, :, None]
        Fz = self.et_z * (psi[1:, :, :] - psi[:-1, :, :]) / hz[:, None, None]
        div_x = np.zeros((Nz, Ny, Nx)); div_x[:, :, :-1] += Fx; div_x[:, :, 1:] -= Fx
        div_y = np.zeros((Nz, Ny, Nx)); div_y[:, :-1, :] += Fy; div_y[:, 1:, :] -= Fy
        div_z = np.zeros((Nz, Ny, Nx)); div_z[:-1, :, :] += Fz; div_z[1:, :, :] -= Fz
        F_psi = (dVy[None, :, None] * dVz[:, None, None] * div_x
                + dVx[None, None, :] * dVz[:, None, None] * div_y
                + dVx[None, None, :] * dVy[None, :, None] * div_z
                - dV * rho)

        kLx, kRx = _edge_pairs_x(Nx, Ny, Nz)
        wx = np.broadcast_to(dVy[None, :, None] * dVz[:, None, None] / hx[None, None, :],
                              (Nz, Ny, Nx - 1)).ravel()
        kSy, kNy = _edge_pairs_y(Nx, Ny, Nz)
        wy = np.broadcast_to(dVx[None, None, :] * dVz[:, None, None] / hy[None, :, None],
                              (Nz, Ny - 1, Nx)).ravel()
        kDz, kUz = _edge_pairs_z(Nx, Ny, Nz)
        wz = np.broadcast_to(dVx[None, None, :] * dVy[None, :, None] / hz[:, None, None],
                              (Nz - 1, Ny, Nx)).ravel()

        def ip(k): return 3 * k
        def iln(k): return 3 * k + 1
        def ilp(k): return 3 * k + 2

        rows = [ip(kLx), ip(kRx), ip(kLx), ip(kRx),
                ip(kSy), ip(kNy), ip(kSy), ip(kNy),
                ip(kDz), ip(kUz), ip(kDz), ip(kUz)]
        cols = [ip(kLx), ip(kRx), ip(kRx), ip(kLx),
                ip(kSy), ip(kNy), ip(kNy), ip(kSy),
                ip(kDz), ip(kUz), ip(kUz), ip(kDz)]
        vals = [-wx, -wx, wx, wx, -wy, -wy, wy, wy, -wz, -wz, wz, wz]

        kdiag = np.arange(N)
        rows.append(ip(kdiag)); cols.append(ip(kdiag)); vals.append((-dV * dnp).ravel())
        rows.append(ip(kdiag)); cols.append(iln(kdiag)); vals.append((dV * n / VT).ravel())
        rows.append(ip(kdiag)); cols.append(ilp(kdiag)); vals.append((-dV * p / VT).ravel())

        # ---- gate (Robin) BC on the Poisson row -- a direct port of
        # _residual_jacobian_poisson's own gate block, generalized to
        # the interleaved 3N layout. Equilibrium is always solved at
        # the device's own Vg_s=0.0 (never bc.Vg -- see Device2D's own
        # docstring for why: DG is equilibrium-only, biased through Vfb
        # only). Gate nodes also carry the Lambda hard wall below; a
        # node with BOTH a contact BC and a GateBC takes the contact's
        # Lambda=0 rule (ohmic/pinned wins -- enforced by the pin logic
        # below, which runs after and overwrites unconditionally).
        gate_k_list = [bc.k * Nx * Ny + bc.j * Nx + bc.i
                       for bc in self.bcs.values() if isinstance(bc, GateBC)]
        gate_k = (np.unique(np.concatenate(gate_k_list)) if gate_k_list
                  else np.zeros(0, dtype=int))
        gate_mask = np.zeros(N, dtype=bool)
        gate_mask[gate_k] = True
        F_flat = F_psi.ravel()
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                w = self._gate_face_weight(bc)
                Vg_s, Vfb_s = 0.0, bc.Vfb / VT
                psi_b_local = (np.arcsinh(
                    self.C[bc.k, bc.j, bc.i] / (2.0 * self.nie_s[bc.k, bc.j, bc.i]))
                    - self.band_shift[bc.k, bc.j, bc.i])
                F_flat[kk] += bc.kappa * w * (
                    Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows.append(ip(kk)); cols.append(ip(kk))
                vals.append(-bc.kappa * w * np.ones_like(kk, dtype=float))

        # ---- Lambda_n / Lambda_p rows: pytcad/dg_grid.py's dimension-
        # generic kernel, shared with Device2D (M42-S3 extraction) -----
        h_phys_x = np.diff(self.mesh.x)
        h_phys_y = np.diff(self.mesh.y)
        h_phys_z = np.diff(self.mesh.z)
        dVx_phys = control_volume_widths(h_phys_x)
        dVy_phys = control_volume_widths(h_phys_y)
        dVz_phys = control_volume_widths(h_phys_z)

        m_n = np.array([m.m_n_star for m in self.mats]).reshape(Nz, Ny, Nx)
        m_p = np.array([m.m_p_star for m in self.mats]).reshape(Nz, Ny, Nx)

        axes = [
            dict(kL=kLx, kR=kRx,
                 h_phys=np.broadcast_to(h_phys_x[None, None, :], (Nz, Ny, Nx - 1)).ravel(),
                 dV_phys=np.broadcast_to(dVx_phys[None, None, :], (Nz, Ny, Nx)).ravel()),
            dict(kL=kSy, kR=kNy,
                 h_phys=np.broadcast_to(h_phys_y[None, :, None], (Nz, Ny - 1, Nx)).ravel(),
                 dV_phys=np.broadcast_to(dVy_phys[None, :, None], (Nz, Ny, Nx)).ravel()),
            dict(kL=kDz, kR=kUz,
                 h_phys=np.broadcast_to(h_phys_z[:, None, None], (Nz - 1, Ny, Nx)).ravel(),
                 dV_phys=np.broadcast_to(dVz_phys[:, None, None], (Nz, Ny, Nx)).ravel()),
        ]
        Flam_n, Flam_p, lam_rows, lam_cols, lam_vals = dg_lambda_rows(
            N, axes, n.ravel(), p.ravel(), Lam_n.ravel(), Lam_p.ravel(),
            m_n.ravel(), m_p.ravel(), gamma, gate_mask, ip, iln, ilp, VT)
        rows += lam_rows; cols += lam_cols; vals += lam_vals

        F = np.zeros(3 * N)
        F[ip(kdiag)] = F_flat
        F[iln(kdiag)] = Flam_n
        F[ilp(kdiag)] = Flam_p

        # ---- Dirichlet/Pinned rows: psi + Lambda_n + Lambda_p at every
        # contact node, equilibrium => V = 0 (or the pinned value) ------
        contact_k = []
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                psi0 = self._bc_contact_values(bc, 0.0)[0]
                F[ip(kk)] = psi.ravel()[kk] - psi0
                F[iln(kk)] = Lam_n.ravel()[kk]
                F[ilp(kk)] = Lam_p.ravel()[kk]
                contact_k.append(kk)
            elif isinstance(bc, PinnedBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                F[ip(kk)] = psi.ravel()[kk] - bc.psi0
                F[iln(kk)] = Lam_n.ravel()[kk]
                F[ilp(kk)] = Lam_p.ravel()[kk]
                contact_k.append(kk)
        contact_k = (np.unique(np.concatenate(contact_k)) if contact_k
                     else np.zeros(0, dtype=int))

        # ---- GateBC hard wall: pin Lambda_n/Lambda_p to LAMBDA_MAX_VT*VT
        # at every gate node that is not also a contact ------------------
        gate_k_only = (gate_k[~np.isin(gate_k, contact_k)]
                       if gate_k.size else gate_k)
        if gate_k_only.size:
            pin_val = LAMBDA_MAX_VT * VT
            F[iln(gate_k_only)] = Lam_n.ravel()[gate_k_only] - pin_val
            F[ilp(gate_k_only)] = Lam_p.ravel()[gate_k_only] - pin_val

        rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)
        pin_rows = []
        pin_list = []
        if contact_k.size:
            pin_list.append(np.concatenate(
                [ip(contact_k), iln(contact_k), ilp(contact_k)]))
        if gate_k_only.size:
            pin_list.append(np.concatenate(
                [iln(gate_k_only), ilp(gate_k_only)]))
        if pin_list:
            pin_rows = np.unique(np.concatenate(pin_list))
            keep = ~np.isin(rows, pin_rows)
            rows, cols, vals = rows[keep], cols[keep], vals[keep]
            rows = np.concatenate([rows, pin_rows])
            cols = np.concatenate([cols, pin_rows])
            vals = np.concatenate([vals, np.ones_like(pin_rows, dtype=float)])

        J = csr_matrix((vals, (rows, cols)), shape=(3 * N, 3 * N))
        self._dg_dirichlet_rows_eq = (
            np.asarray(pin_rows, dtype=int) if len(pin_rows)
            else np.zeros(0, dtype=int))
        return F, J

    def _dg_newton_solve_eq(self, psi, Lam_n, Lam_p, gamma, max_iter, tol,
                            tol_residual=1e-7):
        """One coupled-Newton solve at FIXED gamma from a warm start.
        A direct lift of Device2D's own _dg_newton_solve_eq (device2d.py)
        -- same residual-based convergence check and backtracking-line-
        search-on-the-residual-merit addition found necessary there
        under a GateBC's inversion regime; see that method's docstring
        for the full rationale. Never raises on non-convergence/a
        singular step, reports via `converged`."""
        for _ in range(max_iter):
            F, J = self._dg_residual_jacobian_eq(psi, Lam_n, Lam_p, gamma=gamma)
            Jd, rhs = eliminate_csr(J, -F, self._dg_dirichlet_rows_eq)
            try:
                d, _ = linsolve.solve_linear(Jd.tocsc(), rhs, method="direct")
            except linsolve.LinearSolveError:
                return psi, Lam_n, Lam_p, False
            if not np.all(np.isfinite(d)):
                return psi, Lam_n, Lam_p, False
            d_psi = np.clip(d[0::3], -5.0, 5.0).reshape(self.Nz, self.Ny, self.Nx)
            d_ln = np.clip(d[1::3], -10.0 * self.VT, 10.0 * self.VT).reshape(self.Nz, self.Ny, self.Nx)
            d_lp = np.clip(d[2::3], -10.0 * self.VT, 10.0 * self.VT).reshape(self.Nz, self.Ny, self.Nx)
            err = max(np.abs(d_psi).max(), np.abs(d_ln).max(), np.abs(d_lp).max())
            residual_ok = np.abs(F).max() < tol_residual
            lam = 1.0
            if err >= _LS_NEWTON_REGION and not residual_ok:
                base = 0.5 * float(np.dot(F, F))
                for _ in range(_LS_MAX_HALVINGS + 1):
                    Ft, _ = self._dg_residual_jacobian_eq(
                        psi + lam * d_psi, Lam_n + lam * d_ln,
                        Lam_p + lam * d_lp, gamma=gamma)
                    ft = 0.5 * float(np.dot(Ft, Ft))
                    if np.isfinite(ft) and ft <= base * (1.0 - 1e-4 * lam):
                        break
                    lam *= 0.5
                else:
                    lam = 1.0
            psi = psi + lam * d_psi
            Lam_n = Lam_n + lam * d_ln
            Lam_p = Lam_p + lam * d_lp
            if err < tol or residual_ok:
                return psi, Lam_n, Lam_p, True
        return psi, Lam_n, Lam_p, False

    def _solve_equilibrium_dg_coupled(self, opts: NewtonOptions):
        """M42-S3: gamma-continuation coupled-Newton DG equilibrium, a
        direct lift of Device2D's own _solve_equilibrium_dg_coupled --
        same stage list, same warm-restart/retry-with-bisection logic.
        A gated DG device is biased through Vfb only (equilibrium's own
        Vg_s=0.0), so there is no DG C-V curve here."""
        psi = self._bulk_psi_guess()
        Lam_n = np.zeros((self.Nz, self.Ny, self.Nx))
        Lam_p = np.zeros((self.Nz, self.Ny, self.Nx))

        target_gamma = getattr(self.models, "dg_gamma", 1.0)
        stages = [0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0]
        k = 0
        retries_at_stage = 0
        converged_final = True
        while k < len(stages):
            gamma_k = target_gamma * stages[k]
            psi_new, Ln_new, Lp_new, ok = self._dg_newton_solve_eq(
                psi, Lam_n, Lam_p, gamma_k, opts.max_iter, opts.tol_update)
            if ok:
                psi, Lam_n, Lam_p = psi_new, Ln_new, Lp_new
                k += 1
                retries_at_stage = 0
                continue
            retries_at_stage += 1
            if retries_at_stage > 20:
                converged_final = False
                break
            stages.insert(k, 0.5 * (stages[k - 1] if k > 0 else 0.0) + 0.5 * stages[k])
        if not converged_final:
            warnings.warn("M42 DG (3D) equilibrium coupled-Newton solve "
                          "did not converge (gamma continuation stalled).")

        self.psi = psi
        self._dg_Lam_n = Lam_n
        self._dg_Lam_p = Lam_p
        psi_c = psi + self.band_shift
        self.n = self.nie_s * np.exp(np.clip(psi_c, -700, 700)) * np.exp(-Lam_n / self.VT)
        self.p = self.nie_s * np.exp(np.clip(-psi_c, -700, 700)) * np.exp(-Lam_p / self.VT)
        return self

    # ------------------------------------------------------------------
    def solve_equilibrium(self, opts: NewtonOptions = None, psi_guess=None):
        """psi_guess: optional warm-start initial iterate, shape
        (Nz,Ny,Nx).  When given, skips _bulk_psi_guess()'s bisection
        root-find (itself a real cost -- see M22-LINSOLVE-PLAN's
        profiling note) and starts Newton directly from psi_guess
        instead.  Correctness never depends on the initial guess (same
        contract as solve_bias's own psi/n/p warm start); only how
        many iterations it takes to reconverge.  Default None keeps
        the original cold bulk-neutral guess -- every existing caller
        omits this and is unaffected.  Added for
        mpi_schwarz_runner.py's Schwarz outer loop, whose interface
        pins change only slightly between iterations, so re-deriving
        the flat bulk guess from scratch every iteration was pure
        waste."""
        opts = opts or NewtonOptions()
        if self.dg:
            # M42-S3: coupled-Newton DG equilibrium, mirroring Device2D's
            # S1/S2 one dimension up (see _solve_equilibrium_dg_coupled's
            # own docstring). psi_guess is not threaded through here --
            # the DG path always starts from its own bulk-neutral guess,
            # same as Device2D's S1/S2 path (no existing caller passes
            # psi_guess together with dg=True).
            return self._solve_equilibrium_dg_coupled(opts)
        Nz, Ny, Nx = self.Nz, self.Ny, self.Nx

        # M31 P5-1 Phase D: opts.linsolve="auto" resolves ONCE, here --
        # this is B4, the case Phase A found the largest measured win
        # on (3D structured Poisson-equilibrium). See
        # linsolve.select_auto's own docstring for the evidence and the
        # refusal path (Gate D-3): every other opts.linsolve value
        # (including the default "direct") passes through unaffected.
        resolved_linsolve, auto_reason = (
            linsolve.select_auto(dim=3, unstructured=False, coupled=False,
                                 dof=Nz * Ny * Nx)
            if opts.linsolve == "auto" else (opts.linsolve, None))
        if opts.verbose and auto_reason:
            print(f"    eq  auto -> {resolved_linsolve} ({auto_reason})")
        # Gate D-2: the choice and its reason are always inspectable
        # after the call, not just when opts.verbose prints them.
        self.last_auto_method = resolved_linsolve if opts.linsolve == "auto" else None
        self.last_auto_reason = auto_reason

        psi = self._bulk_psi_guess() if psi_guess is None else np.array(psi_guess, dtype=float)
        for it in range(opts.max_iter):
            F, J = self._residual_jacobian_poisson(psi)
            # linsolve.solve_linear(method="direct") no longer
            # reformats A before calling spsolve, so passing the same
            # J.tocsc() this always used keeps this bit-identical while
            # adding the finiteness/singularity checks every other
            # Newton loop in this file already goes through.
            #
            # opts.linsolve now reaches equilibrium too, not just
            # solve_bias: M22-LINSOLVE-PLAN.md's own note that
            # equilibrium's tridiagonal solve was "never the measured
            # bottleneck" was measured on Device1D/2D and on a
            # 19683-node 3D resistor -- direct sparse LU's fill-in on a
            # genuinely large 3D structured grid (7-point stencil, no
            # tridiagonal structure to exploit) is a different story,
            # confirmed directly: bicgstab solved the FIRST iteration's
            # equilibrium Jacobian for a real ~40k-node device over
            # 100x faster than spsolve (5.07s -> 0.047s), agreeing to a
            # relative error of 2.5e-9. But a later iteration's
            # Jacobian on the SAME device -- confirmed directly, not
            # assumed -- failed to converge in 500 bicgstab iterations
            # (scipy code -11): the matrix's conditioning shifts as psi
            # moves away from the bulk guess, and an iterative method's
            # convergence is not guaranteed the way direct LU's is. So
            # a requested non-default method is tried FIRST for speed,
            # but a LinearSolveError falls back to "direct" for that
            # ONE iteration only, rather than aborting the whole solve
            # or (worse) silently accepting a wrong/unconverged update
            # -- the Newton loop always sees a real solution, just
            # sometimes the slow one. No block_size is passed: this is
            # a single scalar (psi-only) system, one unknown per node,
            # not the psi/n/p-interleaved triple solve_bias solves --
            # block_size=None correctly skips straight to the ILU
            # preconditioner (see solve_linear's docstring). Default
            # opts.linsolve="direct" never enters the except branch at
            # all, so this is bit-identical unless the caller opts in,
            # exactly as solve_bias below already does.
            # Symmetric Dirichlet elimination -- see pytcad/dirichlet.py.
            Jd, rhs = eliminate_csr(J, -F.ravel(),
                                    self._dirichlet_rows_poisson)
            try:
                d, _ = linsolve.solve_linear(Jd.tocsc(), rhs,
                                             method=resolved_linsolve,
                                             rtol=opts.linsolve_rtol)
            except linsolve.LinearSolveError:
                if resolved_linsolve == "direct":
                    raise
                if opts.verbose:
                    print(f"    eq it {it:2d}  {resolved_linsolve} did not "
                          "converge -- falling back to direct for this "
                          "iteration")
                d, _ = linsolve.solve_linear(Jd.tocsc(), rhs,
                                             method="direct")
            d = d.reshape(Nz, Ny, Nx)
            d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
            psi = psi + d
            if opts.verbose:
                print(f"    eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
            if np.abs(d).max() < opts.tol_update:
                break
        else:
            warnings.warn("3D equilibrium Poisson solve did not converge.")

        self.psi = psi
        if self.fd:
            # _fd_slaved_densities clamps eta to FERMI_ETA_MAX to survive
            # a TRANSIENT overshoot during iteration; it must not also
            # silently accept a CONVERGED eta genuinely outside the
            # validated range here -- check the raw, unclamped eta so a
            # genuinely-invalid converged state still refuses loudly
            # (M13 G7), matching fd_density's own contract.
            en_raw = psi - self.ln_gn
            ep_raw = -psi - self.ln_gp
            if np.any(en_raw > FERMI_ETA_MAX) or np.any(ep_raw > FERMI_ETA_MAX):
                raise ValueError(
                    f"FD equilibrium converged to eta_n={en_raw.max():.1f} / "
                    f"eta_p={ep_raw.max():.1f}, beyond +{FERMI_ETA_MAX:.0f}: "
                    "outside the validated Fermi-integral range (M13 G7 "
                    "applicability).  Refusing to extrapolate.")
            self.n, self.p, _ = self._fd_slaved_densities(psi)
        else:
            # M33-S5: matches _residual_jacobian_poisson's own psi_c
            # slaving (see M33-S4-PLAN.md section 4 for why Device1D's
            # own equivalent final assignment does NOT do this -- a
            # known, deliberately-unfixed asymmetry not replicated
            # into new code here).
            psi_c = psi + self.band_shift
            self.n = self.nie_s * np.exp(np.clip(psi_c, -700, 700))
            self.p = self.nie_s * np.exp(np.clip(-psi_c, -700, 700))
        if getattr(self.models, "energy_balance", False):
            self.Tn = np.full((self.Nz, self.Ny, self.Nx), self.T)
        return self

    # ------------------------------------------------------------------
    #  Full drift-diffusion residual/Jacobian
    # ------------------------------------------------------------------
    def _btbt_nl_params(self):
        """M34-S3: (Eg [J], mr, mc, mv [kg]) of the homojunction material."""
        mat = self.mats[0]
        mc = mat.m_n_star * _NL_M0
        mv = mat.m_p_star * _NL_M0
        return mat.Eg(self.T) * _NL_Q, 1.0 / (1.0 / mc + 1.0 / mv), mc, mv

    def _btbt_nl_build_paths(self, psi):
        """M34-S3: trace the field-line tunnel paths at `psi` (grid).
        Only this geometry is frozen for the Newton solve that follows;
        solve_bias re-locates it after convergence.  Dirichlet AND pinned
        nodes (both have their rows replaced) are off limits."""
        mask = np.zeros((self.Nz, self.Ny, self.Nx), dtype=bool)
        for bc in self.bcs.values():
            if isinstance(bc, (DirichletBC, PinnedBC)):
                mask[bc.k, bc.j, bc.i] = True
        return _nl_build_structured((self.mesh.z, self.mesh.y, self.mesh.x),
                                    psi, self.VT, self.mats[0].Eg(self.T),
                                    mask)

    def _btbt_nl_eval(self, psi_flat):
        """M34-S3: evaluate the frozen paths at a live (flat) psi."""
        Eg_J, mr, mc, mv = self._btbt_nl_params()
        return _nl_evaluate(self._btbt_nl_paths, psi_flat, self.VT, Eg_J,
                            mr, mc, mv)

    def _residual_jacobian(self, psi, n, p, voltages, theta=None,
                           n_lag=None, Jn_lag_x=None, Jn_lag_y=None,
                           Jn_lag_z=None, Qheat_lag=None):
        Nx, Ny, Nz, N = self.Nx, self.Ny, self.Nz, self.N
        hx, hy, hz = self.hx, self.hy, self.hz
        dVx, dVy, dVz, dV = self.dVx, self.dVy, self.dVz, self.dV
        C = self.C
        # M41 incomplete ionization: Poisson's charge term becomes
        # rho = n - p - C_ion(n, p).  Here n and p are INDEPENDENT
        # unknowns (unlike the slaved equilibrium block), so the two
        # density columns of the Poisson row pick up d(C_ion)/dn and
        # d(C_ion)/dp directly.  None when the flag is off.
        dcden = dcdp = None
        if getattr(self.models, "incomplete_ion", False):
            C, dcden, dcdp = self._ionized_C(n, p)

        # --- M13: nu-factor SG (plan section 3.2bis; shared with the
        # 1D/2D cores): electron deltas gain +dL_n, hole deltas -dL_p;
        # psi-columns of the Jacobian unchanged, density columns gain
        # the verified w-chain. ---
        fd = self.fd
        if fd:
            Ln, Lp, wn, wp = fd_node_factors(self.nc_s, self.nv_s,
                                             n, p)
            nu_n = np.exp(Ln)
            nu_p = np.exp(Lp)

        # --- M11-S4: Anderson band offsets via CARRIER-SPECIFIC
        # ln(nie) edge deltas (electron +dln(nie), hole -dln(nie));
        # composes additively with the fd nu-factors. ---
        dlnnie_x = np.log(self.nie_s[:, :, 1:] / self.nie_s[:, :, :-1])
        dlnnie_y = np.log(self.nie_s[:, 1:, :] / self.nie_s[:, :-1, :])
        dlnnie_z = np.log(self.nie_s[1:, :, :] / self.nie_s[:-1, :, :])

        # M33-S5: the affinity gauge adds ONE edge term, the SAME sign
        # for both carriers (unlike dlnnie's opposite carrier signs --
        # a rigid band shift moves both carriers' reference together;
        # see device2d.py's own ds_x/ds_y for the identical 2D
        # argument). Constant under the Newton update exactly like
        # dlnnie, so no Jacobian column changes. Identically zero on
        # the default "nie" gauge and for a homojunction.
        ds_x = self.band_shift[:, :, 1:] - self.band_shift[:, :, :-1]
        ds_y = self.band_shift[:, 1:, :] - self.band_shift[:, :-1, :]
        ds_z = self.band_shift[1:, :, :] - self.band_shift[:-1, :, :]

        # --- Scharfetter-Gummel currents, per axis ---
        dx = psi[:, :, 1:] - psi[:, :, :-1] + dlnnie_x + ds_x
        if fd:
            dx = dx + (Ln[:, :, 1:] - Ln[:, :, :-1])
        Bp_x, Bm_x = bernoulli(dx), bernoulli(-dx)
        dBp_x, dBm_x = dbernoulli(dx), dbernoulli(-dx)
        an_x = self.dn_edge_x / hx[None, None, :]
        ap_x = self.dp_edge_x / hx[None, None, :]
        dxp = psi[:, :, 1:] - psi[:, :, :-1] - dlnnie_x + ds_x
        if fd:
            dxp = dxp - (Lp[:, :, 1:] - Lp[:, :, :-1])
        Bpx_h, Bmx_h = bernoulli(dxp), bernoulli(-dxp)
        dBpx_h, dBmx_h = dbernoulli(dxp), dbernoulli(-dxp)
        an_x = self.dn_edge_x / hx[None, None, :]
        ap_x = self.dp_edge_x / hx[None, None, :]
        Jn_x = an_x * (n[:, :, 1:] * Bp_x - n[:, :, :-1] * Bm_x)
        Jp_x = -ap_x * (p[:, :, 1:] * Bmx_h - p[:, :, :-1] * Bpx_h)

        dy = psi[:, 1:, :] - psi[:, :-1, :] + dlnnie_y + ds_y
        if fd:
            dy = dy + (Ln[:, 1:, :] - Ln[:, :-1, :])
        Bp_y, Bm_y = bernoulli(dy), bernoulli(-dy)
        dBp_y, dBm_y = dbernoulli(dy), dbernoulli(-dy)
        dyp = psi[:, 1:, :] - psi[:, :-1, :] - dlnnie_y + ds_y
        if fd:
            dyp = dyp - (Lp[:, 1:, :] - Lp[:, :-1, :])
        Bpy_h, Bmy_h = bernoulli(dyp), bernoulli(-dyp)
        dBpy_h, dBmy_h = dbernoulli(dyp), dbernoulli(-dyp)
        an_y = self.dn_edge_y / hy[None, :, None]
        ap_y = self.dp_edge_y / hy[None, :, None]
        Jn_y = an_y * (n[:, 1:, :] * Bp_y - n[:, :-1, :] * Bm_y)
        Jp_y = -ap_y * (p[:, 1:, :] * Bmy_h - p[:, :-1, :] * Bpy_h)

        dz = psi[1:, :, :] - psi[:-1, :, :] + dlnnie_z + ds_z
        if fd:
            dz = dz + (Ln[1:, :, :] - Ln[:-1, :, :])
        Bp_z, Bm_z = bernoulli(dz), bernoulli(-dz)
        dBp_z, dBm_z = dbernoulli(dz), dbernoulli(-dz)
        dzp = psi[1:, :, :] - psi[:-1, :, :] - dlnnie_z + ds_z
        if fd:
            dzp = dzp - (Lp[1:, :, :] - Lp[:-1, :, :])
        Bpz_h, Bmz_h = bernoulli(dzp), bernoulli(-dzp)
        dBpz_h, dBmz_h = dbernoulli(dzp), dbernoulli(-dzp)
        an_z = self.dn_edge_z / hz[:, None, None]
        ap_z = self.dp_edge_z / hz[:, None, None]
        Jn_z = an_z * (n[1:, :, :] * Bp_z - n[:-1, :, :] * Bm_z)
        Jp_z = -ap_z * (p[1:, :, :] * Bmz_h - p[:-1, :, :] * Bpz_h)

        # --- recombination (unscaled physical densities) ---
        n_phys, p_phys = n * self.Ns, p * self.Ns
        npq_args = {}
        if fd:
            npq = self.nie ** 2 * nu_n * nu_p          # physical
            dnpq_dns = self.nie ** 2 * nu_p * nu_n * wn
            dnpq_dps = self.nie ** 2 * nu_n * nu_p * wp
            npq_args = dict(np_eq=npq,
                            dnpq_dn=dnpq_dns / self.Ns,
                            dnpq_dp=dnpq_dps / self.Ns)
        # M11-S4: per-material recombination parameter sets
        R = np.empty_like(n_phys); dRdn = np.empty_like(n_phys)
        dRdp = np.empty_like(n_phys)
        nflat, pflat = n_phys.ravel(), p_phys.ravel()
        nief, taunf, taupf = (self.nie.ravel(), self.tau_n.ravel(),
                              self.tau_p.ravel())
        for m in {id(mm): mm for mm in self.mats}.values():
            nodes = np.array([mm is m for mm in self.mats])
            (R.ravel()[nodes], dRdn.ravel()[nodes],
             dRdp.ravel()[nodes]) = recombination(
                nflat[nodes], pflat[nodes], nief[nodes], taunf[nodes],
                taupf[nodes], m, auger=self.models.auger, **{
                    k: v.ravel()[nodes] for k, v in npq_args.items()})
        if not self.models.srh:
            R = np.zeros_like(R); dRdn = np.zeros_like(R); dRdp = np.zeros_like(R)
        Rs = R / self.R0
        dRs_dn = dRdn * self.Ns / self.R0
        dRs_dp = dRdp * self.Ns / self.R0

        # --- Poisson residual: pure potential differences (NOT the
        # fd-modified deltas; M13 fix) times the M11-S4 edge eps ---
        Fx_psi = self.et_x * (psi[:, :, 1:] - psi[:, :, :-1]) / hx[None, None, :]
        Fy_psi = self.et_y * (psi[:, 1:, :] - psi[:, :-1, :]) / hy[None, :, None]
        Fz_psi = self.et_z * (psi[1:, :, :] - psi[:-1, :, :]) / hz[:, None, None]
        div_x = np.zeros((Nz, Ny, Nx)); div_x[:, :, :-1] += Fx_psi; div_x[:, :, 1:] -= Fx_psi
        div_y = np.zeros((Nz, Ny, Nx)); div_y[:, :-1, :] += Fy_psi; div_y[:, 1:, :] -= Fy_psi
        div_z = np.zeros((Nz, Ny, Nx)); div_z[:-1, :, :] += Fz_psi; div_z[1:, :, :] -= Fz_psi
        F_psi = (dVy[None, :, None] * dVz[:, None, None] * div_x
               + dVx[None, None, :] * dVz[:, None, None] * div_y
               + dVx[None, None, :] * dVy[None, :, None] * div_z
               - dV * (n - p - C))

        # --- continuity residuals ---
        div_Jn_x = np.zeros((Nz, Ny, Nx)); div_Jn_x[:, :, :-1] += Jn_x; div_Jn_x[:, :, 1:] -= Jn_x
        div_Jn_y = np.zeros((Nz, Ny, Nx)); div_Jn_y[:, :-1, :] += Jn_y; div_Jn_y[:, 1:, :] -= Jn_y
        div_Jn_z = np.zeros((Nz, Ny, Nx)); div_Jn_z[:-1, :, :] += Jn_z; div_Jn_z[1:, :, :] -= Jn_z
        F_n = (dVy[None, :, None] * dVz[:, None, None] * div_Jn_x
             + dVx[None, None, :] * dVz[:, None, None] * div_Jn_y
             + dVx[None, None, :] * dVy[None, :, None] * div_Jn_z
             - Rs * dV)

        div_Jp_x = np.zeros((Nz, Ny, Nx)); div_Jp_x[:, :, :-1] += Jp_x; div_Jp_x[:, :, 1:] -= Jp_x
        div_Jp_y = np.zeros((Nz, Ny, Nx)); div_Jp_y[:, :-1, :] += Jp_y; div_Jp_y[:, 1:, :] -= Jp_y
        div_Jp_z = np.zeros((Nz, Ny, Nx)); div_Jp_z[:-1, :, :] += Jp_z; div_Jp_z[1:, :, :] -= Jp_z
        F_p = (dVy[None, :, None] * dVz[:, None, None] * div_Jp_x
             + dVx[None, None, :] * dVz[:, None, None] * div_Jp_y
             + dVx[None, None, :] * dVy[None, :, None] * div_Jp_z
             + Rs * dV)

        F = np.empty((N, 3))
        F[:, 0] = F_psi.ravel(); F[:, 1] = F_n.ravel(); F[:, 2] = F_p.ravel()
        F = F.ravel()   # interleaved 3k, 3k+1, 3k+2

        # --- Jacobian: M47 Slice 2a groundwork -- the base COO stamps
        # now live in module-level block functions (_poisson_flux_row_coo
        # etc., see their own docstrings for why the split is safe by
        # construction). `rows`/`cols`/`vals` stay plain lists here so
        # the GateBC/impact/btbt/nonlocal-btbt code below (UNCHANGED)
        # can keep appending to them exactly as before. ---
        kLx, kRx = _edge_pairs_x(Nx, Ny, Nz)
        kSy, kNy = _edge_pairs_y(Nx, Ny, Nz)
        kDz, kUz = _edge_pairs_z(Nx, Ny, Nz)

        wx_area = np.broadcast_to(dVy[None, :, None] * dVz[:, None, None], (Nz, Ny, Nx - 1))
        wy_area = np.broadcast_to(dVx[None, None, :] * dVz[:, None, None], (Nz, Ny - 1, Nx))
        wz_area = np.broadcast_to(dVx[None, None, :] * dVy[None, :, None], (Nz - 1, Ny, Nx))

        # Poisson row (comp 0), depends on psi at both edge endpoints
        wx_h = wx_area * self.et_x / hx[None, None, :]
        wy_h = wy_area * self.et_y / hy[None, :, None]
        wz_h = wz_area * self.et_z / hz[:, None, None]
        rows, cols, vals = [], [], []
        p_r, p_c, p_v = _poisson_flux_row_coo(kLx, kRx, wx_h, kSy, kNy, wy_h,
                                              kDz, kUz, wz_h)
        rows.append(p_r); cols.append(p_c); vals.append(p_v)

        # electron continuity row (comp 1). M13 fd density-chain:
        #   d(Jn)/d(n_{k+1}) = an(Bp + Sn w_{k+1}),
        #   d(Jn)/d(n_k)     = an(-Bm - Sn w_k);  psi-cols unchanged.
        Snx = n[:, :, 1:] * dBp_x + n[:, :, :-1] * dBm_x
        Sny = n[:, 1:, :] * dBp_y + n[:, :-1, :] * dBm_y
        Snz = n[1:, :, :] * dBp_z + n[:-1, :, :] * dBm_z
        dJn_dpsiR_x = an_x * Snx
        dJn_dn_L_x, dJn_dn_R_x = -an_x * Bm_x, an_x * Bp_x
        if fd:
            dJn_dn_L_x = dJn_dn_L_x - an_x * Snx * wn[:, :, :-1]
            dJn_dn_R_x = dJn_dn_R_x + an_x * Snx * wn[:, :, 1:]

        dJn_dpsiR_y = an_y * Sny
        dJn_dn_L_y, dJn_dn_R_y = -an_y * Bm_y, an_y * Bp_y
        if fd:
            dJn_dn_L_y = dJn_dn_L_y - an_y * Sny * wn[:, :-1, :]
            dJn_dn_R_y = dJn_dn_R_y + an_y * Sny * wn[:, 1:, :]

        dJn_dpsiR_z = an_z * Snz
        dJn_dn_L_z, dJn_dn_R_z = -an_z * Bm_z, an_z * Bp_z
        if fd:
            dJn_dn_L_z = dJn_dn_L_z - an_z * Snz * wn[:-1, :, :]
            dJn_dn_R_z = dJn_dn_R_z + an_z * Snz * wn[1:, :, :]

        e_r, e_c, e_v = _electron_continuity_coo(
            kLx, kRx, wx_area, dJn_dpsiR_x, dJn_dn_L_x, dJn_dn_R_x,
            kSy, kNy, wy_area, dJn_dpsiR_y, dJn_dn_L_y, dJn_dn_R_y,
            kDz, kUz, wz_area, dJn_dpsiR_z, dJn_dn_L_z, dJn_dn_R_z)
        rows.append(e_r); cols.append(e_c); vals.append(e_v)

        # hole continuity row (comp 2). M13 fd density-chain:
        #   d(Jp)/d(p_{k+1}) = -ap(Bm_h + Sp w_{k+1}),
        #   d(Jp)/d(p_k)     = +ap(Bp_h + Sp w_k).
        Spx = p[:, :, 1:] * dBmx_h + p[:, :, :-1] * dBpx_h
        Spy = p[:, 1:, :] * dBmy_h + p[:, :-1, :] * dBpy_h
        Spz = p[1:, :, :] * dBmz_h + p[:-1, :, :] * dBpz_h
        dJp_dpsiR_x = ap_x * Spx
        dJp_dp_L_x, dJp_dp_R_x = ap_x * Bpx_h, -ap_x * Bmx_h
        if fd:
            dJp_dp_L_x = dJp_dp_L_x + ap_x * Spx * wp[:, :, :-1]
            dJp_dp_R_x = dJp_dp_R_x - ap_x * Spx * wp[:, :, 1:]

        dJp_dpsiR_y = ap_y * Spy
        dJp_dp_L_y, dJp_dp_R_y = ap_y * Bpy_h, -ap_y * Bmy_h
        if fd:
            dJp_dp_L_y = dJp_dp_L_y + ap_y * Spy * wp[:, :-1, :]
            dJp_dp_R_y = dJp_dp_R_y - ap_y * Spy * wp[:, 1:, :]

        dJp_dpsiR_z = ap_z * Spz
        dJp_dp_L_z, dJp_dp_R_z = ap_z * Bpz_h, -ap_z * Bmz_h
        if fd:
            dJp_dp_L_z = dJp_dp_L_z + ap_z * Spz * wp[:-1, :, :]
            dJp_dp_R_z = dJp_dp_R_z - ap_z * Spz * wp[1:, :, :]

        h_r, h_c, h_v = _hole_continuity_coo(
            kLx, kRx, wx_area, dJp_dpsiR_x, dJp_dp_L_x, dJp_dp_R_x,
            kSy, kNy, wy_area, dJp_dpsiR_y, dJp_dp_L_y, dJp_dp_R_y,
            kDz, kUz, wz_area, dJp_dpsiR_z, dJp_dp_L_z, dJp_dp_R_z)
        rows.append(h_r); cols.append(h_c); vals.append(h_v)

        # local (same-node) diagonal terms: Poisson's charge term,
        # continuity's recombination cross terms
        diag_k = np.arange(N)
        d_r, d_c, d_v = _base_diagonal_coo(diag_k, dV, dcden, dcdp, dRs_dn, dRs_dp)
        rows.append(d_r); cols.append(d_c); vals.append(d_v)

        # --- Robin (gate) BC on psi only, area-weighted per normal_axis,
        # referenced to the local bulk potential ---
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                w = self._gate_face_weight(bc)
                Vg_s, Vfb_s = bc.Vg / self.VT, bc.Vfb / self.VT
                # M33-S5: same -band_shift reference as the
                # equilibrium Robin term above.
                psi_b_local = (np.arcsinh(
                    self.C[bc.k, bc.j, bc.i] / (2.0 * self.nie_s[bc.k, bc.j, bc.i]))
                    - self.band_shift[bc.k, bc.j, bc.i])
                F.reshape(N, 3)[kk, 0] += bc.kappa * w * (
                    Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows.append(3 * kk); cols.append(3 * kk); vals.append(-bc.kappa * w)

        # --- M34-S6: M15's coupled impact ionization on the grid
        # (pytcad/ii_grid.py; Device2D's block with a third axis).  After
        # the continuity rows, before the Dirichlet stamping, not at
        # contact or pinned nodes; the ladder's strength scales the live
        # term and its Jacobian together. ---
        impact_on = getattr(self.models, "impact", False)
        btbt_on = getattr(self.models, "btbt", False)
        if impact_on or btbt_on:
            axes = [
                dict(kL=kLx, kR=kRx,
                     h=np.broadcast_to(hx[None, None, :],
                                       (Nz, Ny, Nx - 1)).ravel(),
                     Jn=Jn_x.ravel(), Jp=Jp_x.ravel(),
                     dJn_dpsiR=dJn_dpsiR_x.ravel(),
                     dJn_dnL=dJn_dn_L_x.ravel(), dJn_dnR=dJn_dn_R_x.ravel(),
                     dJp_dpsiR=dJp_dpsiR_x.ravel(),
                     dJp_dpL=dJp_dp_L_x.ravel(), dJp_dpR=dJp_dp_R_x.ravel()),
                dict(kL=kSy, kR=kNy,
                     h=np.broadcast_to(hy[None, :, None],
                                       (Nz, Ny - 1, Nx)).ravel(),
                     Jn=Jn_y.ravel(), Jp=Jp_y.ravel(),
                     dJn_dpsiR=dJn_dpsiR_y.ravel(),
                     dJn_dnL=dJn_dn_L_y.ravel(), dJn_dnR=dJn_dn_R_y.ravel(),
                     dJp_dpsiR=dJp_dpsiR_y.ravel(),
                     dJp_dpL=dJp_dp_L_y.ravel(), dJp_dpR=dJp_dp_R_y.ravel()),
                dict(kL=kDz, kR=kUz,
                     h=np.broadcast_to(hz[:, None, None],
                                       (Nz - 1, Ny, Nx)).ravel(),
                     Jn=Jn_z.ravel(), Jp=Jp_z.ravel(),
                     dJn_dpsiR=dJn_dpsiR_z.ravel(),
                     dJn_dnL=dJn_dn_L_z.ravel(), dJn_dnR=dJn_dn_R_z.ravel(),
                     dJp_dpsiR=dJp_dpsiR_z.ravel(),
                     dJp_dpL=dJp_dp_L_z.ravel(), dJp_dpR=dJp_dp_R_z.ravel()),
            ]
            live = np.ones(N, dtype=bool)
            for bc in self.bcs.values():
                if isinstance(bc, (DirichletBC, PinnedBC)):
                    live[bc.k * Nx * Ny + bc.j * Nx + bc.i] = False
            dVf = dV.ravel()
        if impact_on:
            if getattr(self.models, "impact_nonlocal", False):
                En_ii, Dn_ii = _ii_eff_grid(
                    (Nz, Ny, Nx), axes, psi.ravel(), self.VT, self.LD, "n",
                    self.models.impact_lambda_n)
                Ep_ii, Dp_ii = _ii_eff_grid(
                    (Nz, Ny, Nx), axes, psi.ravel(), self.VT, self.LD, "p",
                    self.models.impact_lambda_p)
                eff = (En_ii, Dn_ii, Ep_ii, Dp_ii)
            else:
                eff = None
            G, g_r, g_c, g_v, self._ii_fields = _ii_grid(
                N, axes, psi.ravel(), self.VT, self.LD, self.J0, self.R0,
                eff=eff)
            strength = self._ii_strength
            Gs = np.where(live, strength * G, 0.0)
            self._ii_gs_cache = Gs.copy()
            F[1::3] += Gs * dVf
            F[2::3] -= Gs * dVf
            keep = live[g_r]
            self._ii_jac_cache = (g_r[keep], g_c[keep],
                                  strength * g_v[keep])
            w = strength * dVf[g_r[keep]] * g_v[keep]
            rows.append(3 * g_r[keep] + 1); cols.append(g_c[keep]); vals.append(w)
            rows.append(3 * g_r[keep] + 2); cols.append(g_c[keep]); vals.append(-w)

        # --- M16-S2: local Kane BTBT on the structured grid (Device2D's
        # block; same ordering invariant, interior/live nodes only). ---
        if btbt_on:
            Gb, b_r, b_c, b_v, self._btbt_fields = _btbt_grid(
                N, axes, psi.ravel(), self.VT, self.LD, self.R0)
            strength = self._ii_strength
            Gbs = np.where(live, strength * Gb, 0.0)
            self._btbt_gs_cache = Gbs.copy()
            F[1::3] += Gbs * dVf
            F[2::3] -= Gbs * dVf
            keep_b = live[b_r]
            w_b = strength * dVf[b_r[keep_b]] * b_v[keep_b]
            rows.append(3 * b_r[keep_b] + 1); cols.append(b_c[keep_b]); vals.append(w_b)
            rows.append(3 * b_r[keep_b] + 2); cols.append(b_c[keep_b]); vals.append(-w_b)

        # --- M34-S3: nonlocal path BTBT along field lines (Device2D's
        # block; same invariant: after the continuity rows, before the
        # Dirichlet stamping). ---
        if getattr(self.models, "btbt_nonlocal", False):
            if self._btbt_nl_paths is None:
                self._btbt_nl_paths = self._btbt_nl_build_paths(psi)
            if self._btbt_nl_paths.n_paths:
                ev = self._btbt_nl_eval(psi.ravel())
                st = self._btbt_nl_paths.start
                fac = 1e-6 / self.R0 * dV.ravel()[st]      # SI -> scaled count
                cnt = fac * ev.G
                np.add.at(F, 3 * st + 2, -cnt)
                dep = ev.dep.tocoo()
                np.add.at(F, 3 * dep.col + 1, cnt[dep.row] * dep.data)
                dG = ev.dG.tocoo()
                rows.append(3 * st[dG.row] + 2)
                cols.append(3 * dG.col)
                vals.append(-fac[dG.row] * dG.data)
                Wm = csr_matrix((fac[dep.row] * dep.data,
                                 (3 * dep.col + 1, dep.row)),
                                shape=(3 * N, st.size))
                dG3 = csr_matrix((dG.data, (dG.row, 3 * dG.col)),
                                 shape=(st.size, 3 * N))
                Je = (Wm @ dG3).tocoo()
                rows.append(Je.row)
                cols.append(Je.col)
                vals.append(Je.data)
                rows.append(3 * ev.ddep_node + 1)
                cols.append(3 * ev.ddep_col)
                vals.append(cnt[ev.ddep_p] * ev.ddep_val)

        rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)

        # --- Dirichlet (contact) BC on psi, n, p: replace all 3 rows ---
        contact_k = []
        F3 = F.reshape(N, 3)
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                V = voltages.get(name, bc.V)
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                psi0, n0, p0 = self._bc_contact_values(bc, V)
                F3[kk, 0] = psi.ravel()[kk] - psi0
                F3[kk, 1] = n.ravel()[kk] - n0
                F3[kk, 2] = p.ravel()[kk] - p0
                contact_k.append(kk)
            elif isinstance(bc, PinnedBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                F3[kk, 0] = psi.ravel()[kk] - bc.psi0
                F3[kk, 1] = n.ravel()[kk] - bc.n0
                F3[kk, 2] = p.ravel()[kk] - bc.p0
                contact_k.append(kk)
        if contact_k:
            contact_k = np.unique(np.concatenate(contact_k))
            all_contact_rows = np.concatenate(
                [3 * contact_k, 3 * contact_k + 1, 3 * contact_k + 2])
            keep = ~np.isin(rows, all_contact_rows)
            rows, cols, vals = rows[keep], cols[keep], vals[keep]
            for comp in range(3):
                r = 3 * contact_k + comp
                rows = np.concatenate([rows, r]); cols = np.concatenate([cols, r])
                vals = np.concatenate([vals, np.ones_like(r, dtype=float)])

        base_dirichlet = (
            all_contact_rows if len(contact_k) else np.zeros(0, dtype=int))

        # M44 Slice 4: coupled electron energy balance, appended as a
        # 4th block (rows/cols 3*N..4*N-1) -- SAME design as Device1D/
        # Device2D (see M44-HYDRODYNAMIC-PLAN.md). The 3*N block above
        # is COMPLETELY UNCHANGED by this: `theta is None` (default)
        # returns exactly the pre-M44 F/J, bit-identical.
        # contact_k is ALREADY the deduped ndarray by this point (the
        # `if contact_k:` block above reassigns it from the raw list).
        contact_nodes = contact_k if len(contact_k) else np.zeros(0, dtype=int)
        if theta is not None:
            # w = transverse control-volume width -- the PRODUCT of
            # the other two axes' local widths (e.g. an x-edge's flux
            # has a "depth" in BOTH y and z). Mandatory: omitting this
            # was a real bug found while gating Device2D (see
            # hydro_grid.py's own docstring) -- breaks exact
            # y/z-uniformity between a boundary "half-width" transverse
            # CV and an interior "full-width" one.
            axes = [
                dict(kL=kLx, kR=kRx,
                     h=np.broadcast_to(hx[None, None, :], (Nz, Ny, Nx - 1)).ravel(),
                     w=np.broadcast_to((dVy[None, :, None] * dVz[:, None, None]),
                                       (Nz, Ny, Nx - 1)).ravel(),
                     Jn=Jn_lag_x.ravel()),
                dict(kL=kSy, kR=kNy,
                     h=np.broadcast_to(hy[None, :, None], (Nz, Ny - 1, Nx)).ravel(),
                     w=np.broadcast_to((dVx[None, None, :] * dVz[:, None, None]),
                                       (Nz, Ny - 1, Nx)).ravel(),
                     Jn=Jn_lag_y.ravel()),
                dict(kL=kDz, kR=kUz,
                     h=np.broadcast_to(hz[:, None, None], (Nz - 1, Ny, Nx)).ravel(),
                     w=np.broadcast_to((dVx[None, None, :] * dVy[None, :, None]),
                                       (Nz - 1, Ny, Nx)).ravel(),
                     Jn=Jn_lag_z.ravel()),
            ]
            F_T, t_r, t_c, t_v = _grid_hydro(
                N, axes, dV.ravel(), n_lag.ravel(), theta.ravel(),
                Qheat_lag.ravel(), self.mu_n0.ravel(), self._KAPPA0,
                self._ALPHA_RELAX, contact_nodes)
            base = 3 * N
            rows = np.concatenate([rows, t_r + base])
            cols = np.concatenate([cols, t_c + base])
            vals = np.concatenate([vals, t_v])
            F3 = np.concatenate([F3.ravel(), F_T])
            self._dirichlet_rows = np.concatenate(
                [base_dirichlet, contact_nodes + base])
            shape = 4 * N
        else:
            F3 = F3.ravel()
            self._dirichlet_rows = base_dirichlet
            shape = 3 * N

        J = csr_matrix((vals, (rows, cols)), shape=(shape, shape))
        # Every component of every contact node is Dirichlet here (3D has
        # no S_n/S_p Robin variant), so the eliminated set is the full
        # all_contact_rows. See pytcad/dirichlet.py.
        return F3, J, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, F_n, F_p

    # ------------------------------------------------------------------
    def solve_bias(self, voltages=None, opts: NewtonOptions = None):
        """Solve at applied bias.  voltages: {contact_name: V}; contacts
        not mentioned keep their previously set voltage.  Gate voltage is
        set the same way, using the gate's registered name."""
        opts = opts or NewtonOptions()
        if self.dg:
            # M42-S3: DG stays EQUILIBRIUM-ONLY, matching Device1D/
            # Device2D (M20/M42 scope; DG transport is out of scope for
            # this dimensional lift too -- a lift is not a scope
            # extension).
            raise NotImplementedError(
                "Models(dg=True) is equilibrium-only (M20/M42 scope): "
                "solve_bias would need DG inside the Scharfetter-Gummel "
                "currents (DG transport), which is out of scope.")
        if self.psi is None:
            self.solve_equilibrium(opts)

        voltages = voltages or {}
        for name, V in voltages.items():
            bc = self.bcs[name]
            if isinstance(bc, DirichletBC):
                bc.V = V
            elif isinstance(bc, GateBC):
                bc.Vg = V

        psi, n, p = self.psi.copy(), self.n.copy(), self.p.copy()
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                psi0, n0, p0 = self._bc_contact_values(bc, bc.V)
                psi[bc.k, bc.j, bc.i] = psi0
                n[bc.k, bc.j, bc.i] = n0
                p[bc.k, bc.j, bc.i] = p0
            elif isinstance(bc, PinnedBC):
                psi[bc.k, bc.j, bc.i] = bc.psi0
                n[bc.k, bc.j, bc.i] = bc.n0
                p[bc.k, bc.j, bc.i] = bc.p0

        cur_voltages = {name: bc.V for name, bc in self.bcs.items()
                        if isinstance(bc, DirichletBC)}

        # M44 Slice 4: theta = Tn/T -- see Device1D/Device2D's own
        # identical warm-start reasoning (zero current at the very
        # first bias point makes theta==1 the EXACT solution there).
        energy_balance = getattr(self.models, "energy_balance", False)
        if energy_balance:
            theta = ((self.Tn / self.T).copy() if self.Tn is not None
                     else np.ones((self.Nz, self.Ny, self.Nx)))
            contact_idx = [(bc.k, bc.j, bc.i) for bc in self.bcs.values()
                          if isinstance(bc, (DirichletBC, PinnedBC))]
            for kk, jj, ii in contact_idx:
                theta[kk, jj, ii] = 1.0
            Jn_prev_x = np.zeros((self.Nz, self.Ny, self.Nx - 1))
            Jn_prev_y = np.zeros((self.Nz, self.Ny - 1, self.Nx))
            Jn_prev_z = np.zeros((self.Nz - 1, self.Ny, self.Nx))

        # M31 P5-1 Phase D: opts.linsolve="auto" resolves ONCE, here.
        # This is the COUPLED 3D structured solve -- Phase A never
        # measured it (only B4's equilibrium-only path), so
        # select_auto's own evidence table has no entry for
        # (dim=3, unstructured=False, coupled=True). Phase A-2 MEASURED
        # this cell (S3D) and it is the largest coupled win in the
        # study: 44.56s direct -> 1.60s at 27,783 DOF (27.9x), so "auto"
        # resolves to "gmres" here at or above 6,591 DOF and refuses to
        # direct below. The iterative branch below therefore IS
        # reachable through "auto" now -- which is why its existing
        # per-iterate fallback matters. See linsolve.select_auto's
        # docstring.
        resolved_linsolve, auto_reason = (
            linsolve.select_auto(dim=3, unstructured=False, coupled=True,
                                 dof=3 * self.Nz * self.Ny * self.Nx)
            if opts.linsolve == "auto" else (opts.linsolve, None))
        if opts.verbose and auto_reason:
            print(f"    solve_bias  auto -> {resolved_linsolve} ({auto_reason})")
        self.last_auto_method = resolved_linsolve if opts.linsolve == "auto" else None
        self.last_auto_reason = auto_reason

        # M34-S3: nonlocal BTBT paths are frozen for a Newton solve and
        # re-located at the converged state; the loop below runs exactly
        # once otherwise.
        btbt_nl = getattr(self.models, "btbt_nonlocal", False)
        self._btbt_nl_paths = None
        self.last_btbt_nl_refreshes = 0
        self.last_btbt_nl_stable = None
        # M34-S6: impact ionization runs Device2D's M15 machinery -- the
        # _II_STAGES ladder, backtracking on the 2-norm merit with
        # convergence judged on the FULL Newton correction, and the full
        # step when a search fails (see Device2D.solve_bias for both
        # measured reasons).  impact=False keeps the single full-step
        # pass, arithmetic unchanged.
        ii_on = getattr(self.models, "impact", False)
        # M16-S2: local BTBT is a Zener-stiff generation source exactly
        # like impact ionization; drives the same ladder/backtrack/floor
        # gating (Device1D's own stiff_gen includes btbt_enabled).
        btbt_on = getattr(self.models, "btbt", False)
        stiff_on = ii_on or btbt_on
        stages = _II_STAGES if stiff_on else (1.0,)
        backtrack = stiff_on
        # the stiff path's update-test floor (device._STIFF_DENSITY_FLOOR);
        # the plain path keeps M11-S5's 1e-10, bit-identical
        dens_floor = _STIFF_DENSITY_FLOOR if stiff_on else 1e-10
        self._ii_strength = 1.0
        while True:
            for stage in stages:
                self._ii_strength = stage
                converged = False
                for it in range(opts.max_iter):
                    if energy_balance:
                        self._update_energy_mobility(theta)
                        n_lag = n.copy()
                        # Wachutka quasi-Fermi field, per axis -- same
                        # fix Device1D/Device2D's own Slice 1/4 needed.
                        phi_n_lag = psi - np.log(
                            np.maximum(n_lag, 1e-300) / self.nie_s)
                        En_x = -(phi_n_lag[:, :, 1:] - phi_n_lag[:, :, :-1]) / self.hx[None, None, :]
                        En_y = -(phi_n_lag[:, 1:, :] - phi_n_lag[:, :-1, :]) / self.hy[None, :, None]
                        En_z = -(phi_n_lag[1:, :, :] - phi_n_lag[:-1, :, :]) / self.hz[:, None, None]
                        Hx_edge = Jn_prev_x * En_x
                        Hy_edge = Jn_prev_y * En_y
                        Hz_edge = Jn_prev_z * En_z
                        Qheat_lag = np.zeros((self.Nz, self.Ny, self.Nx))
                        Qheat_lag[:, :, 1:-1] += 0.5 * (Hx_edge[:, :, :-1] + Hx_edge[:, :, 1:])
                        Qheat_lag[:, :, 0] += Hx_edge[:, :, 0]
                        Qheat_lag[:, :, -1] += Hx_edge[:, :, -1]
                        Qheat_lag[:, 1:-1, :] += 0.5 * (Hy_edge[:, :-1, :] + Hy_edge[:, 1:, :])
                        Qheat_lag[:, 0, :] += Hy_edge[:, 0, :]
                        Qheat_lag[:, -1, :] += Hy_edge[:, -1, :]
                        Qheat_lag[1:-1, :, :] += 0.5 * (Hz_edge[:-1, :, :] + Hz_edge[1:, :, :])
                        Qheat_lag[0, :, :] += Hz_edge[0, :, :]
                        Qheat_lag[-1, :, :] += Hz_edge[-1, :, :]
                        F, J, *rest = self._residual_jacobian(
                            psi, n, p, cur_voltages, theta=theta, n_lag=n_lag,
                            Jn_lag_x=Jn_prev_x, Jn_lag_y=Jn_prev_y,
                            Jn_lag_z=Jn_prev_z, Qheat_lag=Qheat_lag)
                        Jn_prev_x, Jn_prev_y, Jn_prev_z = (
                            rest[0].copy(), rest[1].copy(), rest[2].copy())
                    else:
                        F, J, *_ = self._residual_jacobian(psi, n, p, cur_voltages)
                    # Symmetric Dirichlet elimination -- see pytcad/dirichlet.py.
                    Jd, rhs = eliminate_csr(J, -F, self._dirichlet_rows)
                    if resolved_linsolve == "direct":
                        # linsolve.solve_linear(method="direct") is documented
                        # bit-identical to a raw spsolve call (see its own
                        # docstring) -- routing through it here, rather than
                        # calling spsolve directly, buys the MatrixRankWarning-
                        # as-error guard for free with no behavior change,
                        # matching solve_equilibrium's primary direct branch.
                        du, _ = linsolve.solve_linear(Jd, rhs, method="direct")
                    else:
                        # Same fallback contract as solve_equilibrium above: a
                        # requested iterative method is tried first for speed,
                        # but a LinearSolveError (confirmed directly: the node
                        # block-Jacobi preconditioner does not always converge
                        # on this equation's coupled psi/n/p Jacobian, even
                        # with pyamg installed -- a non-None block_size (M31
                        # P5-1 Phase B: opts.block_size, default 3) routes to
                        # block-Jacobi before AMG is ever tried, see
                        # linsolve._build_preconditioner) falls back to a
                        # direct solve for that one iteration only, rather than
                        # raising out of the whole solve. Routed through
                        # linsolve.solve_linear (not a raw spsolve call) so an
                        # exactly-singular Jacobian raises LinearSolveError
                        # instead of silently propagating a NaN/Inf update into
                        # the next Newton iteration.
                        try:
                            du, _ = linsolve.solve_linear(
                                Jd, rhs, method=resolved_linsolve,
                                rtol=opts.linsolve_rtol, block_size=opts.block_size,
                                precond=opts.precond)
                        except linsolve.LinearSolveError:
                            # resolved_linsolve != "direct" is guaranteed here
                            # (the outer if/else already routed "direct" to the
                            # plain branch above), so there is no re-raise guard
                            # needed the way the try-always shape below has one.
                            if opts.verbose:
                                print(f"    solve_bias it {it:2d}  {resolved_linsolve} "
                                      "did not converge -- falling back to direct "
                                      "for this iteration")
                            du, _ = linsolve.solve_linear(Jd, rhs, method="direct")
                    if energy_balance:
                        N3 = 3 * self.N
                        dpsi = du[0:N3:3].reshape(self.Nz, self.Ny, self.Nx)
                        dn = du[1:N3:3].reshape(self.Nz, self.Ny, self.Nx)
                        dp = du[2:N3:3].reshape(self.Nz, self.Ny, self.Nx)
                        dtheta = du[N3:].reshape(self.Nz, self.Ny, self.Nx)
                    else:
                        dpsi = du[0::3].reshape(self.Nz, self.Ny, self.Nx)
                        dn = du[1::3].reshape(self.Nz, self.Ny, self.Nx)
                        dp = du[2::3].reshape(self.Nz, self.Ny, self.Nx)

                    dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
                    n_old, p_old = n, p
                    n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
                    p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)

                    # M11-S5: relative updates are measured against a
                    # density floor -- deep-minority nodes (e.g. inside an
                    # AlGaAs barrier, p ~ 1e-13 scaled) otherwise pin the
                    # criterion to roundoff and stall the solve at a
                    # harmless limit cycle.  Densities below 1e-10 scaled
                    # carry <= 1e-10 of the local Poisson charge; their
                    # exact value is numerically meaningless.  Equilibrium
                    # (slaved-carrier) solves are unaffected.
                    rel_n = (np.abs(n_new - n_old)
                             / np.maximum(n_old, dens_floor)).max()
                    rel_p = (np.abs(p_new - p_old)
                             / np.maximum(p_old, dens_floor)).max()
                    err = max(np.abs(dpsi).max(), rel_n, rel_p)
                    if energy_balance:
                        err = max(err, float(np.abs(dtheta).max()))
                    # (search only outside Newton's region -- see
                    # device._LS_NEWTON_REGION)
                    if backtrack and err >= _LS_NEWTON_REGION:
                        base = 0.5 * float(np.dot(F, F))
                        lam = 1.0
                        for _ in range(_LS_MAX_HALVINGS + 1):
                            Ft, *_ = self._residual_jacobian(
                                psi + lam * dpsi,
                                np.clip(n_old + lam * dn, 0.1 * n_old,
                                        10.0 * n_old),
                                np.clip(p_old + lam * dp, 0.1 * p_old,
                                        10.0 * p_old), cur_voltages)
                            ft = 0.5 * float(np.dot(Ft, Ft))
                            if np.isfinite(ft) and \
                                    ft <= base * (1.0 - 1e-4 * lam):
                                break
                            lam *= 0.5
                        else:
                            lam = 1.0      # see Device2D.solve_bias
                        if opts.verbose:
                            print(f"    stage {self._ii_strength}  lam={lam:.3e}"
                                  f"  merit {base:.3e} -> {ft:.3e}")
                        n_new = np.clip(n_old + lam * dn, 0.1 * n_old,
                                        10.0 * n_old)
                        p_new = np.clip(p_old + lam * dp, 0.1 * p_old,
                                        10.0 * p_old)
                        psi = psi + lam * dpsi
                    else:
                        psi = psi + dpsi
                        if energy_balance:
                            theta = np.clip(theta + dtheta, 0.1 * theta,
                                           10.0 * theta)
                            for kk, jj, ii in contact_idx:
                                theta[kk, jj, ii] = 1.0
                    n, p = n_new, p_new
                    if opts.verbose:
                        print(f"    it {it:2d}  |dpsi|={np.abs(dpsi).max():.3e}  |dn/n|={rel_n:.3e}")
                    if err < opts.tol_update:
                        converged = True
                        break
                else:
                    warnings.warn(f"3D Newton did not converge; last update {err:.2e}")
                if not converged:
                    break

            if not (btbt_nl and converged):
                break
            new = self._btbt_nl_build_paths(psi)
            if (self._btbt_nl_paths is not None
                    and np.array_equal(new.start, self._btbt_nl_paths.start)
                    and self._btbt_nl_eval(psi.ravel()).reached.all()):
                self.last_btbt_nl_stable = True
                break
            if self.last_btbt_nl_refreshes == 4:
                self.last_btbt_nl_stable = False
                break
            self._btbt_nl_paths = new
            self.last_btbt_nl_refreshes += 1
            # the re-solve starts converged: full strength, plain Newton
            stages = (1.0,)
            backtrack = False
        self.last_converged = converged

        self.psi, self.n, self.p = psi, n, p
        if energy_balance:
            self.Tn = theta * self.T
        _, _, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, _, _ = self._residual_jacobian(
            psi, n, p, cur_voltages)
        self.Jn_x, self.Jp_x = Jn_x * self.J0, Jp_x * self.J0
        self.Jn_y, self.Jp_y = Jn_y * self.J0, Jp_y * self.J0
        self.Jn_z, self.Jp_z = Jn_z * self.J0, Jp_z * self.J0
        return self

    # ------------------------------------------------------------------
    def terminal_current(self, name):
        """Total (Jn+Jp) current [A] into a named Dirichlet contact.

        Extracted from the box-integration continuity residual (F_n, F_p)
        evaluated at the contact's nodes BEFORE the Dirichlet row-
        overwrite replaces them with the fixed-value equations.  At those
        raw values, F_n/F_p is the true net divergence of (Jn, Jp) out of
        that node's control volume (charge conservation), which the
        contact must supply -- this includes every edge touching the
        contact (all six directions) with the correct sign, automatically,
        with no separate edge-walking or restriction to a single boundary
        face.  Same technique Device2D's terminal_current uses (adopted
        after a conservation bug in an earlier edge-walking version) --
        built in correctly here from the start.

        Units: real Amps [A] -- unlike Device2D's A/cm (current per unit
        depth), 3D explicitly meshes every physical dimension of the
        device, so there is no remaining implicit unit-width/depth
        assumption; the conversion factor is J0*LD**2 (an AREA, not a
        length) since F_n/F_p here carry a scaled-area weight rather
        than 2D's scaled-length weight.
        """
        bc = self.bcs[name]
        if not isinstance(bc, DirichletBC):
            raise ValueError(f"terminal_current: '{name}' is not a Dirichlet contact")
        if self.psi is None:
            raise RuntimeError("terminal_current: solve the device first")

        cur_voltages = {nm: b.V for nm, b in self.bcs.items() if isinstance(b, DirichletBC)}
        *_, F_n, F_p = self._residual_jacobian(self.psi, self.n, self.p, cur_voltages)

        I = float((F_n[bc.k, bc.j, bc.i] + F_p[bc.k, bc.j, bc.i]).sum()) * self.J0 * self.LD ** 2
        return I

    # --- physical-unit accessors -------------------------------------
    @property
    def psi_V(self):
        return self.psi * self.VT

    @property
    def n_cm3(self):
        return self.n * self.Ns

    @property
    def p_cm3(self):
        return self.p * self.Ns
