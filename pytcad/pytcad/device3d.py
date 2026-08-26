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
from scipy.sparse.linalg import spsolve

from .constants import KB_EV, Q, EPS0, thermal_voltage
from .materials import (
    SILICON, Semiconductor, mobility_caughey_thomas, nie_effective,
    lifetime_scharfetter, recombination,
)
from .device import (D0_REF, bernoulli, dbernoulli, fd_density,
                     fd_ddensity_deta, fd_node_factors, fd_ohmic_values,
                     Models, NewtonOptions)
from .fermi import FERMI_ETA_MAX
from .mesh3d import Mesh3D
from .mesh2d import control_volume_widths
from .moscap import EPS_OX_R


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
    """

    def __init__(self, mesh: Mesh3D, doping, Ntotal=None, T=300.0,
                 material: Semiconductor = SILICON, models: Models = None):
        self.mesh = mesh
        self.Nx, self.Ny, self.Nz, self.N = mesh.Nx, mesh.Ny, mesh.Nz, mesh.N
        self.doping = np.asarray(doping, dtype=float).reshape(
            self.Nz, self.Ny, self.Nx)
        self.Ntot = (np.abs(self.doping) if Ntotal is None
                     else np.asarray(Ntotal, dtype=float).reshape(
                         self.Nz, self.Ny, self.Nx))
        self.T = T
        self.mat = material
        self.models = models or Models()
        if self.models.field_mobility:
            raise NotImplementedError(
                "Canali field-dependent mobility is not implemented in "
                "Device3D (see design spec, deferred items)."
            )

        self.fd = bool(getattr(self.models, "fd", False))
        if self.Ntot.max() > 1e19 and not self.fd:
            warnings.warn(
                "Doping exceeds ~1e19 cm^-3: Boltzmann statistics used here "
                "overestimate the carrier density. Treat results in the "
                "degenerate regions as qualitative."
            )

        self.VT = thermal_voltage(T)
        self.eps = material.eps_r * EPS0
        self.ni = material.ni(T)

        self.Ns = max(float(np.abs(self.doping).max()), self.ni)
        self.LD = np.sqrt(self.eps * self.VT / (Q * self.Ns))
        self.J0 = Q * D0_REF * self.Ns / self.LD
        self.R0 = D0_REF * self.Ns / self.LD ** 2

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
        self.nie = nie_effective(self.Ntot, material, T, self.models.bgn)
        self.nie_s = self.nie / self.Ns

        # M13: physical band-DOS scalars for FD statistics (single-
        # material core; same construction as Device1D/Device2D)
        self.nc_s = float(material.Nc(T)) / self.Ns
        self.nv_s = float(material.Nv(T)) / self.Ns
        nie0 = float(np.asarray(self.nie_s).reshape(-1)[0])  # uniform
        self.ln_gn = float(np.log(self.nc_s / nie0))
        self.ln_gp = float(np.log(self.nv_s / nie0))
        self.eg_kt = float(material.Eg(T)) / KB_EV / T

        self.mu_n0 = (mobility_caughey_thomas(self.Ntot, material, T, "n")
                      if self.models.doping_mobility
                      else np.full((self.Nz, self.Ny, self.Nx), material.mu_n_max))
        self.mu_p0 = (mobility_caughey_thomas(self.Ntot, material, T, "p")
                      if self.models.doping_mobility
                      else np.full((self.Nz, self.Ny, self.Nx), material.mu_p_max))

        self.tau_n = lifetime_scharfetter(self.Ntot, material.tau_n0, material.tau_Nref)
        self.tau_p = lifetime_scharfetter(self.Ntot, material.tau_p0, material.tau_Nref)

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

    # ------------------------------------------------------------------
    def add_contact(self, name, i, j, k, V=0.0):
        self.bcs[name] = DirichletBC(i, j, k, V)
        return self.bcs[name]

    def add_gate(self, name, i, j, k, tox_cm, Vfb, Vg=0.0, normal_axis='z'):
        eps_ox = EPS_OX_R * EPS0
        kappa = eps_ox * self.LD / (self.eps * tox_cm)
        self.bcs[name] = GateBC(i, j, k, kappa, Vfb, Vg, normal_axis)
        return self.bcs[name]

    def _contact_values(self, C_nodes, V, nie_nodes=None):
        """Ohmic values at a contact's nodes (M13: FD-aware; the FD
        bisection reduces exactly to the Boltzmann closed form)."""
        if self.fd:
            return fd_ohmic_values(C_nodes, self.nc_s, self.nv_s,
                                   self.ln_gn, self.eg_kt, V, self.VT)
        return _ohmic_values(C_nodes, nie_nodes, V, self.VT)

    def _bulk_psi_guess(self):
        """Neutral-bulk potential per node (FD eta-space root or the
        classic arcsinh)."""
        if not self.fd:
            return np.arcsinh(self.C / (2.0 * self.nie_s))
        lo0 = -self.eg_kt - 80.0
        hi = np.full(self.C.shape, float(FERMI_ETA_MAX))

        def g(e):
            n_ = fd_density(self.nc_s, np.minimum(e, FERMI_ETA_MAX))
            p_ = fd_density(self.nv_s,
                            np.minimum(-e - self.eg_kt, FERMI_ETA_MAX))
            return n_ - p_ - self.C

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

    def _fd_slaved_densities(self, psi):
        """Equilibrium slaving under FD + d(n+p)/d(psi)."""
        en = psi - self.ln_gn
        ep = -psi - self.ln_gp
        n = fd_density(self.nc_s, en)
        p = fd_density(self.nv_s, ep)
        dnp = fd_ddensity_deta(self.nc_s, en) \
            + fd_ddensity_deta(self.nv_s, ep)
        return n, p, dnp

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
            n = nie * np.exp(np.clip(psi, -700, 700))
            p = nie * np.exp(np.clip(-psi, -700, 700))
            dnp = n + p

        Fx = (psi[:, :, 1:] - psi[:, :, :-1]) / hx[None, None, :]
        Fy = (psi[:, 1:, :] - psi[:, :-1, :]) / hy[None, :, None]
        Fz = (psi[1:, :, :] - psi[:-1, :, :]) / hz[:, None, None]

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
                psi_b_local = np.arcsinh(
                    self.C[bc.k, bc.j, bc.i] / (2.0 * self.nie_s[bc.k, bc.j, bc.i]))
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
                psi0 = self._contact_values(self.C[bc.k, bc.j, bc.i],
                                            0.0,
                                            self.nie_s[bc.k, bc.j, bc.i])[0]
                F_flat[kk] = psi.ravel()[kk] - psi0
                contact_k.append(kk)
        if contact_k:
            contact_k = np.unique(np.concatenate(contact_k))
            keep = ~np.isin(rows, contact_k)
            rows, cols, vals = rows[keep], cols[keep], vals[keep]
            rows = np.concatenate([rows, contact_k])
            cols = np.concatenate([cols, contact_k])
            vals = np.concatenate([vals, np.ones_like(contact_k, dtype=float)])

        J = csr_matrix((vals, (rows, cols)), shape=(N, N))
        return F, J

    # ------------------------------------------------------------------
    def solve_equilibrium(self, opts: NewtonOptions = None):
        opts = opts or NewtonOptions()
        Nz, Ny, Nx = self.Nz, self.Ny, self.Nx

        psi = self._bulk_psi_guess()
        for it in range(opts.max_iter):
            F, J = self._residual_jacobian_poisson(psi)
            d = spsolve(J.tocsc(), -F.ravel()).reshape(Nz, Ny, Nx)
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
            self.n, self.p, _ = self._fd_slaved_densities(psi)
        else:
            self.n = self.nie_s * np.exp(np.clip(psi, -700, 700))
            self.p = self.nie_s * np.exp(np.clip(-psi, -700, 700))
        return self

    # ------------------------------------------------------------------
    #  Full drift-diffusion residual/Jacobian
    # ------------------------------------------------------------------
    def _residual_jacobian(self, psi, n, p, voltages):
        Nx, Ny, Nz, N = self.Nx, self.Ny, self.Nz, self.N
        hx, hy, hz = self.hx, self.hy, self.hz
        dVx, dVy, dVz, dV = self.dVx, self.dVy, self.dVz, self.dV
        C = self.C

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

        # --- Scharfetter-Gummel currents, per axis ---
        dx = psi[:, :, 1:] - psi[:, :, :-1]
        if fd:
            dx = dx + (Ln[:, :, 1:] - Ln[:, :, :-1])
        Bp_x, Bm_x = bernoulli(dx), bernoulli(-dx)
        dBp_x, dBm_x = dbernoulli(dx), dbernoulli(-dx)
        an_x = self.dn_edge_x / hx[None, None, :]
        ap_x = self.dp_edge_x / hx[None, None, :]
        dxp = psi[:, :, 1:] - psi[:, :, :-1]
        if fd:
            dxp = dxp - (Lp[:, :, 1:] - Lp[:, :, :-1])
        Bpx_h, Bmx_h = bernoulli(dxp), bernoulli(-dxp)
        dBpx_h, dBmx_h = dbernoulli(dxp), dbernoulli(-dxp)
        an_x = self.dn_edge_x / hx[None, None, :]
        ap_x = self.dp_edge_x / hx[None, None, :]
        Jn_x = an_x * (n[:, :, 1:] * Bp_x - n[:, :, :-1] * Bm_x)
        Jp_x = -ap_x * (p[:, :, 1:] * Bmx_h - p[:, :, :-1] * Bpx_h)

        dy = psi[:, 1:, :] - psi[:, :-1, :]
        if fd:
            dy = dy + (Ln[:, 1:, :] - Ln[:, :-1, :])
        Bp_y, Bm_y = bernoulli(dy), bernoulli(-dy)
        dBp_y, dBm_y = dbernoulli(dy), dbernoulli(-dy)
        dyp = psi[:, 1:, :] - psi[:, :-1, :]
        if fd:
            dyp = dyp - (Lp[:, 1:, :] - Lp[:, :-1, :])
        Bpy_h, Bmy_h = bernoulli(dyp), bernoulli(-dyp)
        dBpy_h, dBmy_h = dbernoulli(dyp), dbernoulli(-dyp)
        an_y = self.dn_edge_y / hy[None, :, None]
        ap_y = self.dp_edge_y / hy[None, :, None]
        Jn_y = an_y * (n[:, 1:, :] * Bp_y - n[:, :-1, :] * Bm_y)
        Jp_y = -ap_y * (p[:, 1:, :] * Bmy_h - p[:, :-1, :] * Bpy_h)

        dz = psi[1:, :, :] - psi[:-1, :, :]
        if fd:
            dz = dz + (Ln[1:, :, :] - Ln[:-1, :, :])
        Bp_z, Bm_z = bernoulli(dz), bernoulli(-dz)
        dBp_z, dBm_z = dbernoulli(dz), dbernoulli(-dz)
        dzp = psi[1:, :, :] - psi[:-1, :, :]
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
        R, dRdn, dRdp = recombination(
            n_phys, p_phys, self.nie, self.tau_n, self.tau_p, self.mat,
            auger=self.models.auger, **npq_args)
        if not self.models.srh:
            R = np.zeros_like(R); dRdn = np.zeros_like(R); dRdp = np.zeros_like(R)
        Rs = R / self.R0
        dRs_dn = dRdn * self.Ns / self.R0
        dRs_dp = dRdp * self.Ns / self.R0

        # --- Poisson residual (pure potential differences -- NOT the
        # fd-modified SG deltas above; M13 fix, mirrors device2d.py) ---
        Fx_psi = (psi[:, :, 1:] - psi[:, :, :-1]) / hx[None, None, :]
        Fy_psi = (psi[:, 1:, :] - psi[:, :-1, :]) / hy[None, :, None]
        Fz_psi = (psi[1:, :, :] - psi[:-1, :, :]) / hz[:, None, None]
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

        # --- Jacobian: edge-scatter helper (same pattern as device2d.py,
        # one more axis) ---
        rows, cols, vals = [], [], []

        def scatter(kL, kR, weight, row_comp, comp_L, dL, comp_R, dR):
            w = weight.ravel(); dL = dL.ravel(); dR = dR.ravel()
            rows.extend([3 * kL + row_comp, 3 * kL + row_comp,
                         3 * kR + row_comp, 3 * kR + row_comp])
            cols.extend([3 * kL + comp_L, 3 * kR + comp_R,
                         3 * kL + comp_L, 3 * kR + comp_R])
            vals.extend([w * dL, w * dR, -w * dL, -w * dR])

        kLx, kRx = _edge_pairs_x(Nx, Ny, Nz)
        kSy, kNy = _edge_pairs_y(Nx, Ny, Nz)
        kDz, kUz = _edge_pairs_z(Nx, Ny, Nz)

        wx_area = np.broadcast_to(dVy[None, :, None] * dVz[:, None, None], (Nz, Ny, Nx - 1))
        wy_area = np.broadcast_to(dVx[None, None, :] * dVz[:, None, None], (Nz, Ny - 1, Nx))
        wz_area = np.broadcast_to(dVx[None, None, :] * dVy[None, :, None], (Nz - 1, Ny, Nx))

        # Poisson row (comp 0), depends on psi at both edge endpoints
        wx_h = wx_area / hx[None, None, :]
        wy_h = wy_area / hy[None, :, None]
        wz_h = wz_area / hz[:, None, None]
        scatter(kLx, kRx, wx_h, 0, 0, -np.ones_like(wx_h), 0, np.ones_like(wx_h))
        scatter(kSy, kNy, wy_h, 0, 0, -np.ones_like(wy_h), 0, np.ones_like(wy_h))
        scatter(kDz, kUz, wz_h, 0, 0, -np.ones_like(wz_h), 0, np.ones_like(wz_h))

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
        scatter(kLx, kRx, wx_area, 1, 0, -dJn_dpsiR_x, 0, dJn_dpsiR_x)
        scatter(kLx, kRx, wx_area, 1, 1, dJn_dn_L_x, 1, dJn_dn_R_x)

        dJn_dpsiR_y = an_y * Sny
        dJn_dn_L_y, dJn_dn_R_y = -an_y * Bm_y, an_y * Bp_y
        if fd:
            dJn_dn_L_y = dJn_dn_L_y - an_y * Sny * wn[:, :-1, :]
            dJn_dn_R_y = dJn_dn_R_y + an_y * Sny * wn[:, 1:, :]
        scatter(kSy, kNy, wy_area, 1, 0, -dJn_dpsiR_y, 0, dJn_dpsiR_y)
        scatter(kSy, kNy, wy_area, 1, 1, dJn_dn_L_y, 1, dJn_dn_R_y)

        dJn_dpsiR_z = an_z * Snz
        dJn_dn_L_z, dJn_dn_R_z = -an_z * Bm_z, an_z * Bp_z
        if fd:
            dJn_dn_L_z = dJn_dn_L_z - an_z * Snz * wn[:-1, :, :]
            dJn_dn_R_z = dJn_dn_R_z + an_z * Snz * wn[1:, :, :]
        scatter(kDz, kUz, wz_area, 1, 0, -dJn_dpsiR_z, 0, dJn_dpsiR_z)
        scatter(kDz, kUz, wz_area, 1, 1, dJn_dn_L_z, 1, dJn_dn_R_z)

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
        scatter(kLx, kRx, wx_area, 2, 0, -dJp_dpsiR_x, 0, dJp_dpsiR_x)
        scatter(kLx, kRx, wx_area, 2, 2, dJp_dp_L_x, 2, dJp_dp_R_x)

        dJp_dpsiR_y = ap_y * Spy
        dJp_dp_L_y, dJp_dp_R_y = ap_y * Bpy_h, -ap_y * Bmy_h
        if fd:
            dJp_dp_L_y = dJp_dp_L_y + ap_y * Spy * wp[:, :-1, :]
            dJp_dp_R_y = dJp_dp_R_y - ap_y * Spy * wp[:, 1:, :]
        scatter(kSy, kNy, wy_area, 2, 0, -dJp_dpsiR_y, 0, dJp_dpsiR_y)
        scatter(kSy, kNy, wy_area, 2, 2, dJp_dp_L_y, 2, dJp_dp_R_y)

        dJp_dpsiR_z = ap_z * Spz
        dJp_dp_L_z, dJp_dp_R_z = ap_z * Bpz_h, -ap_z * Bmz_h
        if fd:
            dJp_dp_L_z = dJp_dp_L_z + ap_z * Spz * wp[:-1, :, :]
            dJp_dp_R_z = dJp_dp_R_z - ap_z * Spz * wp[1:, :, :]
        scatter(kDz, kUz, wz_area, 2, 0, -dJp_dpsiR_z, 0, dJp_dpsiR_z)
        scatter(kDz, kUz, wz_area, 2, 2, dJp_dp_L_z, 2, dJp_dp_R_z)

        # local (same-node) diagonal terms: Poisson's charge term,
        # continuity's recombination cross terms
        diag_k = np.arange(N)
        rows.append(3 * diag_k); cols.append(3 * diag_k + 1); vals.append(-dV.ravel())
        rows.append(3 * diag_k); cols.append(3 * diag_k + 2); vals.append(dV.ravel())

        rows.append(3 * diag_k + 1); cols.append(3 * diag_k + 1)
        vals.append(-dRs_dn.ravel() * dV.ravel())
        rows.append(3 * diag_k + 1); cols.append(3 * diag_k + 2)
        vals.append(-dRs_dp.ravel() * dV.ravel())

        rows.append(3 * diag_k + 2); cols.append(3 * diag_k + 2)
        vals.append(dRs_dp.ravel() * dV.ravel())
        rows.append(3 * diag_k + 2); cols.append(3 * diag_k + 1)
        vals.append(dRs_dn.ravel() * dV.ravel())

        # --- Robin (gate) BC on psi only, area-weighted per normal_axis,
        # referenced to the local bulk potential ---
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                w = self._gate_face_weight(bc)
                Vg_s, Vfb_s = bc.Vg / self.VT, bc.Vfb / self.VT
                psi_b_local = np.arcsinh(
                    self.C[bc.k, bc.j, bc.i] / (2.0 * self.nie_s[bc.k, bc.j, bc.i]))
                F.reshape(N, 3)[kk, 0] += bc.kappa * w * (
                    Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows.append(3 * kk); cols.append(3 * kk); vals.append(-bc.kappa * w)

        rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)

        # --- Dirichlet (contact) BC on psi, n, p: replace all 3 rows ---
        contact_k = []
        F3 = F.reshape(N, 3)
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                V = voltages.get(name, bc.V)
                kk = bc.k * Nx * Ny + bc.j * Nx + bc.i
                psi0, n0, p0 = self._contact_values(
                    self.C[bc.k, bc.j, bc.i], V,
                    self.nie_s[bc.k, bc.j, bc.i])
                F3[kk, 0] = psi.ravel()[kk] - psi0
                F3[kk, 1] = n.ravel()[kk] - n0
                F3[kk, 2] = p.ravel()[kk] - p0
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

        J = csr_matrix((vals, (rows, cols)), shape=(3 * N, 3 * N))
        return F3.ravel(), J, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, F_n, F_p

    # ------------------------------------------------------------------
    def solve_bias(self, voltages=None, opts: NewtonOptions = None):
        """Solve at applied bias.  voltages: {contact_name: V}; contacts
        not mentioned keep their previously set voltage.  Gate voltage is
        set the same way, using the gate's registered name."""
        opts = opts or NewtonOptions()
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
                psi0, n0, p0 = self._contact_values(
                    self.C[bc.k, bc.j, bc.i], bc.V,
                    self.nie_s[bc.k, bc.j, bc.i])
                psi[bc.k, bc.j, bc.i] = psi0
                n[bc.k, bc.j, bc.i] = n0
                p[bc.k, bc.j, bc.i] = p0

        cur_voltages = {name: bc.V for name, bc in self.bcs.items()
                        if isinstance(bc, DirichletBC)}

        for it in range(opts.max_iter):
            F, J, *_ = self._residual_jacobian(psi, n, p, cur_voltages)
            du = spsolve(J.tocsc(), -F)
            dpsi = du[0::3].reshape(self.Nz, self.Ny, self.Nx)
            dn = du[1::3].reshape(self.Nz, self.Ny, self.Nx)
            dp = du[2::3].reshape(self.Nz, self.Ny, self.Nx)

            dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
            n_old, p_old = n, p
            n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
            p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)
            psi = psi + dpsi
            n, p = n_new, p_new

            rel_n = np.abs(n_new / np.maximum(n_old, 1e-300) - 1.0).max()
            rel_p = np.abs(p_new / np.maximum(p_old, 1e-300) - 1.0).max()
            err = max(np.abs(dpsi).max(), rel_n, rel_p)
            if opts.verbose:
                print(f"    it {it:2d}  |dpsi|={np.abs(dpsi).max():.3e}  |dn/n|={rel_n:.3e}")
            if err < opts.tol_update:
                break
        else:
            warnings.warn(f"3D Newton did not converge; last update {err:.2e}")

        self.psi, self.n, self.p = psi, n, p
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
