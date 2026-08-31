"""2D drift-diffusion device simulator: box-integration finite volumes on
a structured tensor-product grid (Mesh2D), Scharfetter-Gummel currents,
full Newton with an analytic sparse Jacobian.  Direct 2D generalization
of device.py -- same equations, same scaling convention, same physics
models, now assembled on a 5-point stencil instead of a tridiagonal one.

ASSEMBLY STRATEGY
-----------------
Every residual is built as a per-edge "scatter": each x-edge or y-edge
contributes a flux to the two nodes it connects, weighted by the length
of the control-volume face crossing it (dVy[j] for x-edges, dVx[i] for
y-edges -- see Mesh2D).  Writing div_x[:, :-1] += flux; div_x[:, 1:] -=
flux (and the y-direction equivalent) gives the divergence at EVERY node,
interior or boundary, uniformly -- a boundary node simply has one fewer
edge touching it, which is exactly the natural (zero-flux) Neumann
condition.  Dirichlet contacts and the Robin gate condition are then
applied as a small correction on top of this uniform assembly.

The Jacobian uses the same per-edge scatter: an edge's derivative
contributions go into both endpoint rows (+weight at the "near" node,
-weight at the "far" node -- see the row/col/val construction below), so
the interior 5-point stencil and the boundary's reduced stencil come out
of the same code path.
"""

import warnings

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from . import linsolve

from .constants import KB_EV, Q, EPS0, thermal_voltage
from .materials import (
    SILICON, Semiconductor, mobility_caughey_thomas, mobility_cvt,
    nie_effective, lifetime_scharfetter, recombination,
)
from .device import (D0_REF, bernoulli, dbernoulli, fd_density,
                     fd_ddensity_deta, fd_node_factors, fd_ohmic_values,
                     Models, NewtonOptions)
from .fermi import FERMI_ETA_MAX
from .mesh2d import Mesh2D, control_volume_widths
from .moscap import EPS_OX_R


# ----------------------------------------------------------------------
#  Boundary conditions
# ----------------------------------------------------------------------
class DirichletBC:
    """Ohmic contact: fixed voltage at a set of (i,j) grid nodes."""

    def __init__(self, i, j, V=0.0):
        self.i = np.atleast_1d(np.asarray(i, dtype=int))
        self.j = np.atleast_1d(np.asarray(j, dtype=int))
        self.V = float(V)


class GateBC:
    """Gate/oxide coupling (Robin condition on psi only) at a set of
    silicon-surface (i,j) grid nodes."""

    def __init__(self, i, j, kappa, Vfb, Vg=0.0):
        self.i = np.atleast_1d(np.asarray(i, dtype=int))
        self.j = np.atleast_1d(np.asarray(j, dtype=int))
        self.kappa = float(kappa)
        self.Vfb = float(Vfb)
        self.Vg = float(Vg)


def _ohmic_values(C, nie, V, VT):
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


def _edge_pairs_x(Nx, Ny):
    """Flat node index pairs for x-direction edges: (Ny, Nx-1) edges."""
    jj, ii = np.mgrid[0:Ny, 0:Nx - 1]
    kL = (jj * Nx + ii).ravel()
    kR = kL + 1
    return kL, kR


def _edge_pairs_y(Nx, Ny):
    """Flat node index pairs for y-direction edges: (Ny-1, Nx) edges."""
    jj, ii = np.mgrid[0:Ny - 1, 0:Nx]
    kS = (jj * Nx + ii).ravel()
    kN = kS + Nx
    return kS, kN


# ----------------------------------------------------------------------
#  Device
# ----------------------------------------------------------------------
class Device2D:
    """A 2D semiconductor device on a structured Mesh2D.

    Parameters
    ----------
    mesh     : Mesh2D, or a gmsh_mesh.GmshMesh when unstructured=True
    doping   : net doping N_D - N_A [cm^-3], shape (Ny, Nx) or flat (N,);
               when unstructured=True, a {region_name: doping_value}
               dict instead (there is no (Ny,Nx) grid to reshape a
               per-node array into -- mirrors unstructured_poisson.
               evaluate_doping_at_nodes's own doping_by_region param)
    Ntotal   : total ionised impurity concentration for mobility/lifetime
               models [cm^-3]; defaults to |doping|. Not used when
               unstructured=True (see the M21 phase 3d refusal list).
    unstructured : M21 phase 3d -- wire the standalone, already-gated
               unstructured_poisson.py/unstructured_dd.py physics core
               (region_resolver.py, unstructured_assembly.py) into this
               class's normal solve_equilibrium/solve_bias/terminal_
               current API. A THIN WRAPPER, not new physics: refuses
               loudly (NotImplementedError) for any Models() flag or
               material config that core doesn't implement
               (doping_mobility, bgn, fd, incomplete_ion,
               surface_mobility, field_mobility, heterostructure
               material lists) rather than silently ignoring it -- see
               M21-PHASE3-MESHING-PLAN.md section "PHASE 3d
               IMPLEMENTATION RECORD". self.psi/n/p are flat (N,)
               arrays on this path, NOT reshaped to (Ny,Nx) -- there is
               no grid.
    """

    def __init__(self, mesh, doping, Ntotal=None, T=300.0,
                 material: Semiconductor = SILICON, models: Models = None,
                 unstructured=False):
        self.unstructured = bool(unstructured)
        if self.unstructured:
            self._init_unstructured(mesh, doping, T, material, models)
            return
        self.mesh = mesh
        self.Nx, self.Ny, self.N = mesh.Nx, mesh.Ny, mesh.N
        self.doping = np.asarray(doping, dtype=float).reshape(self.Ny, self.Nx)
        self.Ntot = (np.abs(self.doping) if Ntotal is None
                     else np.asarray(Ntotal, dtype=float).reshape(self.Ny, self.Nx))
        self.T = T
        # M11-S4: a single Semiconductor keeps the classic behavior; a
        # flat per-node sequence (row-major, length Ny*Nx) defines a 2D
        # heterostructure -- same conventions as Device1D's M11-S3 core.
        if isinstance(material, Semiconductor):
            self.mats = [material] * self.N
        else:
            mats_flat = list(material)
            if len(mats_flat) != self.N:
                raise ValueError(
                    "material list length must equal Ny*Nx "
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
                "Device2D (see design spec, deferred items)."
            )
        if getattr(self.models, "impact", False):
            raise NotImplementedError(
                "Impact ionization (Models(impact=True)) is implemented "
                "in Device1D only (M15 scope; 2D/3D ports are a follow-"
                "up slice).  Refusing rather than silently ignoring the "
                "flag -- a silently dropped physics model is a hidden "
                "failure."
            )
        if getattr(self.models, "btbt", False):
            raise NotImplementedError(
                "Band-to-band tunneling (Models(btbt=True)) is implemented "
                "in Device1D only (M16 scope; 2D port is a follow-up "
                "slice).  Refusing rather than silently ignoring the "
                "flag -- a silently dropped physics model is a hidden "
                "failure."
            )
        if getattr(self.models, "dg", False):
            raise NotImplementedError(
                "Density-gradient quantum correction (Models(dg=True)) is "
                "implemented in Device1D equilibrium and MOSCapacitor only "
                "(M20 scope; DG transport/2D is a follow-up slice).  "
                "Refusing rather than silently ignoring the flag -- a "
                "silently dropped physics model is a hidden failure."
            )
        if getattr(self.models, "incomplete_ion", False):
            raise NotImplementedError(
                "Incomplete dopant ionization "
                "(Models(incomplete_ion=True)) is implemented in "
                "Device1D only (M13 plan section 3.3).  Refusing rather "
                "than silently ignoring the flag."
            )

        self.fd = bool(getattr(self.models, "fd", False))
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

        self.Ns = max(float(np.abs(self.doping).max()), self.ni)
        self.LD = np.sqrt(self.eps * self.VT / (Q * self.Ns))
        self.J0 = Q * D0_REF * self.Ns / self.LD
        self.R0 = D0_REF * self.Ns / self.LD ** 2

        self.xs = mesh.x / self.LD
        self.ys = mesh.y / self.LD
        self.hx = np.diff(self.xs)
        self.hy = np.diff(self.ys)
        self.dVx = control_volume_widths(self.hx)
        self.dVy = control_volume_widths(self.hy)
        self.dV = np.outer(self.dVy, self.dVx)     # (Ny, Nx), scaled area

        self.C = self.doping / self.Ns

        # M11-S4: per-material grouping (identity-unique, ordered) so
        # each Semiconductor's parameter set applies only on its own
        # nodes (mirrors the Device1D M11-S3 assembly).
        nie_f = np.empty(self.N)
        mu_n_f = np.empty(self.N)
        mu_p_f = np.empty(self.N)
        taun_f = np.empty(self.N)
        taup_f = np.empty(self.N)
        nc_f = np.empty(self.N)
        nv_f = np.empty(self.N)
        egkt_f = np.empty(self.N)
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
        shp = (self.Ny, self.Nx)
        self.nie = nie_f.reshape(shp)
        self.nie_s = self.nie / self.Ns
        self.mu_n0 = mu_n_f.reshape(shp)
        self.mu_p0 = mu_p_f.reshape(shp)
        self.tau_n = taun_f.reshape(shp)
        self.tau_p = taup_f.reshape(shp)

        # M11-S4: harmonic-mean scaled permittivity on edges,
        # normalized by the FIRST node's eps so a uniform device gives
        # exactly 1.0 everywhere and every residual reduces ALGEBRAICALLY
        # to its original form (structural bit-identity, as Device1D).
        et = (self.eps_arr / self.eps0).reshape(shp)

        def hmean2d(lo, hi):
            return 2.0 * lo * hi / (lo + hi)

        self.et_x = hmean2d(et[:, :-1], et[:, 1:])
        self.et_y = hmean2d(et[:-1, :], et[1:, :])

        # M13 fd DOS (per-node so fd composes with heterojunctions):
        self.nc_s = nc_f.reshape(shp) / self.Ns
        self.nv_s = nv_f.reshape(shp) / self.Ns
        self.ln_gn = np.log(self.nc_s / (self.nie / self.Ns))
        self.ln_gp = np.log(self.nv_s / (self.nie / self.Ns))
        self.eg_kt = egkt_f.reshape(shp)

        def hmean(lo, hi):
            return 2.0 * lo * hi / (lo + hi)

        self.dn_edge_x = hmean(self.mu_n0[:, :-1], self.mu_n0[:, 1:]) * self.VT / D0_REF
        self.dp_edge_x = hmean(self.mu_p0[:, :-1], self.mu_p0[:, 1:]) * self.VT / D0_REF
        self.dn_edge_y = hmean(self.mu_n0[:-1, :], self.mu_n0[1:, :]) * self.VT / D0_REF
        self.dp_edge_y = hmean(self.mu_p0[:-1, :], self.mu_p0[1:, :]) * self.VT / D0_REF
        # M14: surface_mobility overwrites ONLY dn_edge_y[0,:]/dp_edge_y[0,:]
        # (the edge between the surface row and the row beneath it) from
        # solve_bias, per Newton iteration.  Constructed here, at the
        # bulk value, so the array this method mutates in place already
        # exists with the right shape/dtype before any bias solve runs.

        self.bcs = {}   # name -> DirichletBC | GateBC
        self.psi = self.n = self.p = None

    # ------------------------------------------------------------------
    #  M21 phase 3d -- unstructured (gmsh triangle mesh) path
    # ------------------------------------------------------------------
    def _init_unstructured(self, mesh, doping, T, material, models):
        """Thin-wrapper setup: run the exact pipeline tests/test_m21_
        phase3.py's own diode_bias_solve fixture already exercises
        end-to-end (the golden, already-gated reference sequence),
        store the results, and refuse any Models()/material config the
        standalone unstructured_poisson.py/unstructured_dd.py physics
        core does not implement. See M21-PHASE3-MESHING-PLAN.md
        "PHASE 3d IMPLEMENTATION RECORD" for the full rationale.
        """
        # Local imports: unstructured_poisson.py/unstructured_dd.py both
        # import _ohmic_values FROM this module, so a top-level import
        # here would be circular.
        from .gmsh_mesh import GmshMesh
        from .region_resolver import resolve_regions, resolve_contacts
        from .unstructured_assembly import (
            build_unstructured_stencil, build_edge_flux_geometry,
        )
        from .unstructured_poisson import evaluate_doping_at_nodes

        if not isinstance(mesh, GmshMesh):
            raise TypeError(
                "Device2D(unstructured=True) requires a gmsh_mesh.GmshMesh, "
                f"got {type(mesh).__name__}")
        if not isinstance(doping, dict):
            raise TypeError(
                "Device2D(unstructured=True) requires doping as a "
                "{region_name: doping_value} dict (no (Ny,Nx) grid exists "
                f"to reshape a per-node array into), got {type(doping).__name__}")
        if not isinstance(material, Semiconductor):
            raise NotImplementedError(
                "Device2D(unstructured=True) does not support a "
                "heterostructure material list -- unstructured_dd.py is "
                "explicitly homojunction-only (see its module docstring). "
                "Pass a single Semiconductor.")

        models = models or Models()
        self.models = models
        unsupported = {
            "doping_mobility": getattr(models, "doping_mobility", False),
            "bgn": getattr(models, "bgn", False),
            "fd": getattr(models, "fd", False),
            "incomplete_ion": getattr(models, "incomplete_ion", False),
            "surface_mobility": getattr(models, "surface_mobility", False),
            "field_mobility": getattr(models, "field_mobility", False),
        }
        bad = [name for name, on in unsupported.items() if on]
        if bad:
            raise NotImplementedError(
                f"Device2D(unstructured=True) does not implement {bad} -- "
                "unstructured_poisson.py/unstructured_dd.py are homojunction-"
                "only (uniform mu_n_max/mu_p_max, no Caughey-Thomas doping "
                "dependence, no FD statistics, no incomplete ionization, no "
                "surface/field mobility). Refusing rather than silently "
                "ignoring the flag(s) -- same convention as the impact/btbt/"
                "dg/incomplete_ion refusals above for the structured path. "
                "NOTE: Models()'s own default has doping_mobility=True, so "
                "unstructured=True callers must pass "
                "Models(doping_mobility=False, ...) explicitly.")

        self.mesh = mesh
        self.mat = material
        self.mats = None          # no per-node material list on this path
        self.T = T
        self.doping = doping      # {region_name: value}, unlike structured

        regions = resolve_regions(mesh)
        self._u_contacts = resolve_contacts(mesh)
        edge_list, node_areas = build_unstructured_stencil(
            mesh.nodes, mesh.triangles)
        interior_edges, trans_geom = build_edge_flux_geometry(
            mesh.nodes, mesh.triangles, edge_list)
        region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
        for name, idx in regions.items():
            region_of_triangle[idx] = name
        C_phys = evaluate_doping_at_nodes(
            mesh.nodes, mesh.triangles, region_of_triangle, doping)

        self._u_edge_list = edge_list
        self._u_node_areas = node_areas
        self._u_interior_edges = interior_edges
        self._u_trans_geom = trans_geom
        self._u_C = C_phys
        self._u_terminal_current = {}
        self.N = mesh.n_nodes()
        self.bcs = {}
        self.psi = self.n = self.p = None

    def _unstructured_solve_equilibrium(self, opts):
        from .unstructured_poisson import solve_poisson_equilibrium
        psi, scale = solve_poisson_equilibrium(
            self.mesh.nodes, self.mesh.triangles, self._u_edge_list,
            self._u_node_areas, self._u_interior_edges, self._u_trans_geom,
            self._u_C, self._u_contacts, material=self.mat, T=self.T,
            opts=opts)
        Ns, nie_s = scale["Ns"], scale["nie"] / scale["Ns"]
        C_s = self._u_C / Ns
        e = np.clip(psi, -700, 700)
        n = np.where(C_s >= 0,
                    0.5 * (C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)),
                    nie_s ** 2 / np.maximum(
                        0.5 * (-C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)),
                        1e-300))
        p = nie_s ** 2 / np.maximum(n, 1e-300)
        self.psi, self.n, self.p = psi, n, p
        self._u_scale = scale
        self.Ns, self.LD, self.VT = scale["Ns"], scale["LD"], scale["VT"]
        self.J0 = Q * D0_REF * self.Ns / self.LD
        return self

    def _unstructured_solve_bias(self, voltages, opts):
        from .unstructured_dd import solve_bias as _u_solve_bias
        if self.psi is None:
            self._unstructured_solve_equilibrium(opts)
        voltages = voltages or {}
        psi, n, p, scale, terminal_current = _u_solve_bias(
            self.mesh.nodes, self.mesh.triangles, self._u_edge_list,
            self._u_node_areas, self._u_interior_edges, self._u_trans_geom,
            self._u_C, self._u_contacts, bias=voltages, material=self.mat,
            T=self.T, opts=opts, srh=self.models.srh,
            auger=getattr(self.models, "auger", False))
        self.psi, self.n, self.p = psi, n, p
        self._u_terminal_current = terminal_current
        self._u_scale = scale
        self.Ns, self.LD, self.VT = scale["Ns"], scale["LD"], scale["VT"]
        self.J0 = Q * D0_REF * self.Ns / self.LD
        return self

    def _unstructured_terminal_current(self, name):
        if self.psi is None:
            raise RuntimeError("terminal_current: solve the device first")
        if name not in self._u_terminal_current:
            raise ValueError(
                f"terminal_current: '{name}' is not a known contact "
                f"(known: {sorted(self._u_terminal_current)})")
        return self._u_terminal_current[name]

    # ------------------------------------------------------------------
    def _update_surface_mobility(self, psi):
        """M14: recompute the row-0/row-1 edge diffusivities from the
        Lombardi CVT surface mobility (materials.mobility_cvt), using
        the CURRENT psi.  LAGGED, same convention as Device1D's
        field_mobility: recomputed every Newton iteration, no Jacobian
        contribution (the edge value is treated as fixed within the
        iteration it is used in).

        SCOPE LIMITATION (recorded here, not silently assumed away):
        this identifies "the surface" as mesh row 0 -- the row every
        add_gate call in this codebase actually uses (see
        pytcad/mosfet.py's build_mosfet: `j=np.zeros_like(i_gate)`,
        the only place a 2D gate is placed in this tree).  A gate on
        any other row, or a side-wall gate, is NOT handled; nothing
        currently exercises that case, and this method does not detect
        or guard against it -- it always treats row 0 as the channel
        surface regardless of where (or whether) a GateBC actually is.
        """
        E_eff = (np.abs(psi[0, :] - psi[1, :]) * self.VT
                / (self.hy[0] * self.LD))
        mu_n_surf = mobility_cvt(E_eff, self.mu_n0[0, :], "n", self.T)
        mu_p_surf = mobility_cvt(E_eff, self.mu_p0[0, :], "p", self.T)
        # Same harmonic-mean-edge convention as every other edge in this
        # class: combine the (now surface-scattering-limited) row-0
        # mobility with the untouched bulk row-1 mobility.
        self.dn_edge_y[0, :] = (2.0 * mu_n_surf * self.mu_n0[1, :]
                               / (mu_n_surf + self.mu_n0[1, :])
                               * self.VT / D0_REF)
        self.dp_edge_y[0, :] = (2.0 * mu_p_surf * self.mu_p0[1, :]
                               / (mu_p_surf + self.mu_p0[1, :])
                               * self.VT / D0_REF)

    # ------------------------------------------------------------------
    def add_contact(self, name, i, j, V=0.0):
        self.bcs[name] = DirichletBC(i, j, V)
        return self.bcs[name]

    def add_gate(self, name, i, j, tox_cm, Vfb, Vg=0.0):
        eps_ox = EPS_OX_R * EPS0
        kappa = eps_ox * self.LD / (self.eps * tox_cm)
        self.bcs[name] = GateBC(i, j, kappa, Vfb, Vg)
        return self.bcs[name]

    def _bc_contact_values(self, bc, V):
        """Ohmic values at a contact's nodes (M11-S4 per-node materials;
        M13: FD-aware -- the FD bisection reduces exactly to the
        Boltzmann closed form)."""
        j, i = bc.j, bc.i
        if self.fd:
            return fd_ohmic_values(self.C[j, i], self.nc_s[j, i],
                                   self.nv_s[j, i], self.ln_gn[j, i],
                                   self.eg_kt[j, i], V, self.VT)
        return _ohmic_values(self.C[j, i], self.nie_s[j, i], V, self.VT)

    def _bulk_psi_guess(self):
        """Neutral-bulk potential per node: eta-space root under FD
        (the Boltzmann arcsinh guess overshoots the FD gauge), the
        classic arcsinh otherwise."""
        if not self.fd:
            return np.arcsinh(self.C / (2.0 * self.nie_s))
        lo = -self.eg_kt - 80.0
        hi = float(FERMI_ETA_MAX)

        def g(e):
            n_ = fd_density(self.nc_s, np.minimum(e, FERMI_ETA_MAX))
            p_ = fd_density(self.nv_s,
                            np.minimum(-e - self.eg_kt, FERMI_ETA_MAX))
            return n_ - p_ - self.C

        flo, fhi = g(lo), g(hi)
        if np.any(flo > 0) or np.any(fhi < 0):
            raise ValueError("2D FD bulk guess: root not bracketed")
        lo = np.full(self.C.shape, lo)
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
        """Equilibrium slaving under FD: n = Nc F(psi-ln(Nc/nie)),
        p = Nv F(-psi-ln(Nv/nie)); returns n, p and d(n+p)/d(psi).

        eta is clamped to FERMI_ETA_MAX before evaluating (matching the
        np.minimum(..., FERMI_ETA_MAX) guard used for the bulk-guess
        bisection above) so a transient Newton overshoot cannot abort
        the whole solve when the converged answer would be valid."""
        en = np.minimum(psi - self.ln_gn, FERMI_ETA_MAX)
        ep = np.minimum(-psi - self.ln_gp, FERMI_ETA_MAX)
        n = fd_density(self.nc_s, en)
        p = fd_density(self.nv_s, ep)
        dnp = fd_ddensity_deta(self.nc_s, en)             + fd_ddensity_deta(self.nv_s, ep)
        return n, p, dnp

    # ------------------------------------------------------------------
    #  Poisson-only residual/Jacobian (used by solve_equilibrium)
    # ------------------------------------------------------------------
    def _residual_jacobian_poisson(self, psi):
        """Equilibrium is always solved at zero bias on every contact,
        regardless of what a contact's stored DirichletBC.V happens to be
        (a later biased solve uses a separate residual/Jacobian method)."""
        Ny, Nx, N = self.Ny, self.Nx, self.N
        hx, hy, dVx, dVy, dV = self.hx, self.hy, self.dVx, self.dVy, self.dV
        C, nie = self.C, self.nie_s

        if self.fd:
            n, p, dnp = self._fd_slaved_densities(psi)
        else:
            n = nie * np.exp(np.clip(psi, -700, 700))
            p = nie * np.exp(np.clip(-psi, -700, 700))
            dnp = n + p

        # M11-S4: position-dependent eps enters Poisson in FLUX form
        # (harmonic-mean edge factors; exactly 1.0 for uniform devices)
        Fx = self.et_x * (psi[:, 1:] - psi[:, :-1]) / hx[None, :]
        Fy = self.et_y * (psi[1:, :] - psi[:-1, :]) / hy[:, None]

        div_x = np.zeros((Ny, Nx)); div_x[:, :-1] += Fx; div_x[:, 1:] -= Fx
        div_y = np.zeros((Ny, Nx)); div_y[:-1, :] += Fy; div_y[1:, :] -= Fy

        F = dVy[:, None] * div_x + dVx[None, :] * div_y - dV * (n - p - C)

        kL, kR = _edge_pairs_x(Nx, Ny)
        wx = np.broadcast_to(dVy[:, None] / hx[None, :], (Ny, Nx - 1)).ravel()
        kS, kN = _edge_pairs_y(Nx, Ny)
        wy = np.broadcast_to(dVx[None, :] / hy[:, None], (Ny - 1, Nx)).ravel()

        rows = np.concatenate([kL, kR, kL, kR, kS, kN, kS, kN])
        cols = np.concatenate([kL, kR, kR, kL, kS, kN, kN, kS])
        vals = np.concatenate([-wx, -wx, wx, wx, -wy, -wy, wy, wy])

        diag_k = np.arange(N)
        diag_v = (-dV * dnp).ravel()
        rows = np.concatenate([rows, diag_k])
        cols = np.concatenate([cols, diag_k])
        vals = np.concatenate([vals, diag_v])

        # --- Robin (gate) BC: add Gauss's-law flux, on top of the
        # implicit zero-flux the uniform assembly already gives there ---
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.j * Nx + bc.i
                # Equilibrium is always solved at zero bias on every contact
                # (see the docstring above) -- hardcode Vg_s to 0.0 rather
                # than reading bc.Vg, which can be stale/nonzero if
                # solve_equilibrium is ever called again after a bias point.
                # Mirrors the Dirichlet contact case a few lines below,
                # which hardcodes V = 0.0 for exactly the same reason.
                Vg_s, Vfb_s = 0.0, bc.Vfb / self.VT
                w = dVx[bc.i]     # face length the gate flux crosses, per node
                # psi is intrinsic-referenced (see _ohmic_values), so the
                # neutral-bulk potential under the gate is psi_b, not 0 --
                # matches moscap.py's validated arcsinh(C/(2*nie_s)) term,
                # generalized to per-node doping (see moscap.py:135 and the
                # code review that flagged this omission).
                psi_b_local = np.arcsinh(self.C[bc.j, bc.i] / (2.0 * self.nie_s[bc.j, bc.i]))
                F.ravel()[kk] += bc.kappa * w * (Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows = np.concatenate([rows, kk])
                cols = np.concatenate([cols, kk])
                vals = np.concatenate([vals, -bc.kappa * w])

        # --- Dirichlet (contact) BC: replace the row entirely, always
        # at V = 0 -- equilibrium is by definition the zero-bias solve ---
        contact_k = []
        F_flat = F.ravel()
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                kk = bc.j * Nx + bc.i
                psi0 = self._bc_contact_values(bc, 0.0)[0]
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
        if self.unstructured:
            return self._unstructured_solve_equilibrium(opts)
        Ny, Nx = self.Ny, self.Nx

        psi = self._bulk_psi_guess()
        for it in range(opts.max_iter):
            F, J = self._residual_jacobian_poisson(psi)
            # linsolve.solve_linear(method="direct") no longer
            # reformats A before calling spsolve, so passing the same
            # J.tocsc() this always used keeps this bit-identical while
            # adding the finiteness/singularity checks every other
            # Newton loop in this file already goes through.
            d, _ = linsolve.solve_linear(J.tocsc(), -F.ravel(), method="direct")
            d = d.reshape(Ny, Nx)
            d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
            psi = psi + d
            if opts.verbose:
                print(f"    eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
            if np.abs(d).max() < opts.tol_update:
                break
        else:
            warnings.warn("2D equilibrium Poisson solve did not converge.")

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
            self.n = self.nie_s * np.exp(np.clip(psi, -700, 700))
            self.p = self.nie_s * np.exp(np.clip(-psi, -700, 700))
        return self

    # ------------------------------------------------------------------
    #  Full drift-diffusion residual/Jacobian
    # ------------------------------------------------------------------
    def _residual_jacobian(self, psi, n, p, voltages):
        Ny, Nx, N = self.Ny, self.Nx, self.N
        hx, hy, dVx, dVy, dV = self.hx, self.hy, self.dVx, self.dVy, self.dV
        C = self.C

        # --- M13: nu-factor SG (plan section 3.2bis; shared with the
        # 1D core).  Electron deltas gain +dL_n, hole deltas -dL_p
        # (carrier-specific opposite signs); psi-columns of the
        # Jacobian are UNCHANGED because delta_tilde keeps its +-1
        # psi-dependence, density columns gain the w-chain below. ---
        fd = self.fd
        if fd:
            Ln, Lp, wn, wp = fd_node_factors(self.nc_s, self.nv_s,
                                             n, p)
            nu_n = np.exp(Ln)
            nu_p = np.exp(Lp)

        # --- M11-S4: Anderson band offsets via CARRIER-SPECIFIC
        # ln(nie) edge deltas (electron +dln(nie), hole -dln(nie) --
        # opposite signs; the shared-delta bug breaks hole detailed
        # balance).  Composes additively with the fd nu-factors. ---
        dlnnie_x = np.log(self.nie_s[:, 1:] / self.nie_s[:, :-1])
        dlnnie_y = np.log(self.nie_s[1:, :] / self.nie_s[:-1, :])

        # --- Scharfetter-Gummel currents, per axis ---
        dx = psi[:, 1:] - psi[:, :-1] + dlnnie_x
        if fd:
            dx = dx + (Ln[:, 1:] - Ln[:, :-1])
        Bp_x, Bm_x = bernoulli(dx), bernoulli(-dx)
        dBp_x, dBm_x = dbernoulli(dx), dbernoulli(-dx)
        dxp = psi[:, 1:] - psi[:, :-1] - dlnnie_x
        if fd:
            dxp = dxp - (Lp[:, 1:] - Lp[:, :-1])
        Bpx_h, Bmx_h = bernoulli(dxp), bernoulli(-dxp)
        dBpx_h, dBmx_h = dbernoulli(dxp), dbernoulli(-dxp)
        an_x = self.dn_edge_x / hx[None, :]
        ap_x = self.dp_edge_x / hx[None, :]
        Jn_x = an_x * (n[:, 1:] * Bp_x - n[:, :-1] * Bm_x)
        Jp_x = -ap_x * (p[:, 1:] * Bmx_h - p[:, :-1] * Bpx_h)

        dy = psi[1:, :] - psi[:-1, :] + dlnnie_y
        if fd:
            dy = dy + (Ln[1:, :] - Ln[:-1, :])
        Bp_y, Bm_y = bernoulli(dy), bernoulli(-dy)
        dBp_y, dBm_y = dbernoulli(dy), dbernoulli(-dy)
        dyp = psi[1:, :] - psi[:-1, :] - dlnnie_y
        if fd:
            dyp = dyp - (Lp[1:, :] - Lp[:-1, :])
        Bpy_h, Bmy_h = bernoulli(dyp), bernoulli(-dyp)
        dBpy_h, dBmy_h = dbernoulli(dyp), dbernoulli(-dyp)
        an_y = self.dn_edge_y / hy[:, None]
        ap_y = self.dp_edge_y / hy[:, None]
        Jn_y = an_y * (n[1:, :] * Bp_y - n[:-1, :] * Bm_y)
        Jp_y = -ap_y * (p[1:, :] * Bmy_h - p[:-1, :] * Bpy_h)

        # --- recombination (unscaled physical densities) ---
        n_phys, p_phys = n * self.Ns, p * self.Ns
        npq_args = {}
        if fd:
            npq = self.nie ** 2 * nu_n * nu_p          # physical
            dnpq_dns = self.nie ** 2 * nu_p * nu_n * wn    # per scaled n
            dnpq_dps = self.nie ** 2 * nu_n * nu_p * wp    # per scaled p
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
        # fd-modified deltas) times the M11-S4 harmonic-mean edge eps ---
        Fx_psi = self.et_x * (psi[:, 1:] - psi[:, :-1]) / hx[None, :]
        Fy_psi = self.et_y * (psi[1:, :] - psi[:-1, :]) / hy[:, None]
        div_x = np.zeros((Ny, Nx)); div_x[:, :-1] += Fx_psi; div_x[:, 1:] -= Fx_psi
        div_y = np.zeros((Ny, Nx)); div_y[:-1, :] += Fy_psi; div_y[1:, :] -= Fy_psi
        F_psi = dVy[:, None] * div_x + dVx[None, :] * div_y - dV * (n - p - C)

        # --- continuity residuals ---
        div_Jn_x = np.zeros((Ny, Nx)); div_Jn_x[:, :-1] += Jn_x; div_Jn_x[:, 1:] -= Jn_x
        div_Jn_y = np.zeros((Ny, Nx)); div_Jn_y[:-1, :] += Jn_y; div_Jn_y[1:, :] -= Jn_y
        F_n = dVy[:, None] * div_Jn_x + dVx[None, :] * div_Jn_y - Rs * dV

        div_Jp_x = np.zeros((Ny, Nx)); div_Jp_x[:, :-1] += Jp_x; div_Jp_x[:, 1:] -= Jp_x
        div_Jp_y = np.zeros((Ny, Nx)); div_Jp_y[:-1, :] += Jp_y; div_Jp_y[1:, :] -= Jp_y
        F_p = dVy[:, None] * div_Jp_x + dVx[None, :] * div_Jp_y + Rs * dV

        F = np.empty((N, 3))
        F[:, 0] = F_psi.ravel(); F[:, 1] = F_n.ravel(); F[:, 2] = F_p.ravel()
        F = F.ravel()   # interleaved 3k, 3k+1, 3k+2

        # --- Jacobian: edge-scatter helper ---
        rows, cols, vals = [], [], []

        def scatter(kL, kR, weight, row_comp, comp_L, dL, comp_R, dR):
            w = weight.ravel(); dL = dL.ravel(); dR = dR.ravel()
            rows.extend([3 * kL + row_comp, 3 * kL + row_comp,
                         3 * kR + row_comp, 3 * kR + row_comp])
            cols.extend([3 * kL + comp_L, 3 * kR + comp_R,
                         3 * kL + comp_L, 3 * kR + comp_R])
            vals.extend([w * dL, w * dR, -w * dL, -w * dR])

        kLx, kRx = _edge_pairs_x(Nx, Ny)
        kSy, kNy = _edge_pairs_y(Nx, Ny)
        wx_psi = (np.broadcast_to(dVy[:, None], (Ny, Nx - 1))
                  * self.et_x) / hx[None, :]
        wy_psi = (np.broadcast_to(dVx[None, :], (Ny - 1, Nx))
                  * self.et_y) / hy[:, None]

        # Poisson row (comp 0), depends on psi at both edge endpoints
        scatter(kLx, kRx, wx_psi, 0, 0, -np.ones_like(wx_psi), 0, np.ones_like(wx_psi))
        scatter(kSy, kNy, wy_psi, 0, 0, -np.ones_like(wy_psi), 0, np.ones_like(wy_psi))

        # electron continuity row (comp 1), from Jn_x / Jn_y.
        # M13 fd: psi-columns unchanged; density columns gain the
        # verified per-edge chain (device.py derivation):
        #   d(Jn)/d(n_{k+1}) = an(Bp + Sn w_{k+1})
        #   d(Jn)/d(n_k)     = an(-Bm - Sn w_k)
        Snx = n[:, 1:] * dBp_x + n[:, :-1] * dBm_x
        Sny = n[1:, :] * dBp_y + n[:-1, :] * dBm_y
        dJn_dpsiR_x = an_x * Snx
        dJn_dn_L_x, dJn_dn_R_x = -an_x * Bm_x, an_x * Bp_x
        if fd:
            dJn_dn_L_x = dJn_dn_L_x - an_x * Snx * wn[:, :-1]
            dJn_dn_R_x = dJn_dn_R_x + an_x * Snx * wn[:, 1:]
        wx_dVy = np.broadcast_to(dVy[:, None], (Ny, Nx - 1))
        scatter(kLx, kRx, wx_dVy, 1, 0, -dJn_dpsiR_x, 0, dJn_dpsiR_x)
        scatter(kLx, kRx, wx_dVy, 1, 1, dJn_dn_L_x, 1, dJn_dn_R_x)

        dJn_dpsiR_y = an_y * Sny
        dJn_dn_L_y, dJn_dn_R_y = -an_y * Bm_y, an_y * Bp_y
        if fd:
            dJn_dn_L_y = dJn_dn_L_y - an_y * Sny * wn[:-1, :]
            dJn_dn_R_y = dJn_dn_R_y + an_y * Sny * wn[1:, :]
        wy_dVx = np.broadcast_to(dVx[None, :], (Ny - 1, Nx))
        scatter(kSy, kNy, wy_dVx, 1, 0, -dJn_dpsiR_y, 0, dJn_dpsiR_y)
        scatter(kSy, kNy, wy_dVx, 1, 1, dJn_dn_L_y, 1, dJn_dn_R_y)

        # hole continuity row (comp 2), from Jp_x / Jp_y.
        # M13 fd (verified per-edge):
        #   d(Jp)/d(p_{k+1}) = -ap(Bm_h + Sp w_{k+1})
        #   d(Jp)/d(p_k)     = +ap(Bp_h + Sp w_k)
        Spx = p[:, 1:] * dBmx_h + p[:, :-1] * dBpx_h
        Spy = p[1:, :] * dBmy_h + p[:-1, :] * dBpy_h
        dJp_dpsiR_x = ap_x * Spx
        dJp_dp_L_x, dJp_dp_R_x = ap_x * Bpx_h, -ap_x * Bmx_h
        if fd:
            dJp_dp_L_x = dJp_dp_L_x + ap_x * Spx * wp[:, :-1]
            dJp_dp_R_x = dJp_dp_R_x - ap_x * Spx * wp[:, 1:]
        scatter(kLx, kRx, wx_dVy, 2, 0, -dJp_dpsiR_x, 0, dJp_dpsiR_x)
        scatter(kLx, kRx, wx_dVy, 2, 2, dJp_dp_L_x, 2, dJp_dp_R_x)

        dJp_dpsiR_y = ap_y * Spy
        dJp_dp_L_y, dJp_dp_R_y = ap_y * Bpy_h, -ap_y * Bmy_h
        if fd:
            dJp_dp_L_y = dJp_dp_L_y + ap_y * Spy * wp[:-1, :]
            dJp_dp_R_y = dJp_dp_R_y - ap_y * Spy * wp[1:, :]
        scatter(kSy, kNy, wy_dVx, 2, 0, -dJp_dpsiR_y, 0, dJp_dpsiR_y)
        scatter(kSy, kNy, wy_dVx, 2, 2, dJp_dp_L_y, 2, dJp_dp_R_y)

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

        # --- Robin (gate) BC on psi only ---
        for bc in self.bcs.values():
            if isinstance(bc, GateBC):
                kk = bc.j * Nx + bc.i
                Vg_s, Vfb_s = bc.Vg / self.VT, bc.Vfb / self.VT
                w = dVx[bc.i]     # face length the gate flux crosses, per node
                # see the matching comment in _residual_jacobian_poisson --
                # psi is intrinsic-referenced, so the neutral-bulk potential
                # under the gate is psi_b, not 0.
                psi_b_local = np.arcsinh(self.C[bc.j, bc.i] / (2.0 * self.nie_s[bc.j, bc.i]))
                F.reshape(N, 3)[kk, 0] += bc.kappa * w * (Vg_s - Vfb_s - (psi.ravel()[kk] - psi_b_local))
                rows.append(3 * kk); cols.append(3 * kk); vals.append(-bc.kappa * w)

        rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)

        # --- Dirichlet (contact) BC on psi, always; n/p when S=0 ----------
        # M14 G-C (2D): for S_n/S_p != 0, a Robin flux-balance BC
        # (Jn.n_hat = q*Sn*(n-n0), mirrored for holes) replaces the
        # Dirichlet density row.  Rather than deriving, per contact node,
        # "which single edge is into the bulk" (hard for an arbitrary 2D
        # contact shape -- a node can touch 1-4 edges), this reuses the
        # box-integration continuity residual F_n/F_p ALREADY computed
        # above for every node uniformly, contact or not, before this
        # block ever runs -- exactly what terminal_current() itself reads
        # as "the net current the contact must supply" (see its own
        # docstring). That residual already sums over however many edges
        # touch the node, so ADDING the recombination sink to it (instead
        # of overwriting it and stripping every other Jacobian entry in
        # the row) generalizes to any contact shape with no special-casing.
        # S=0 keeps the EXACT pre-existing Dirichlet row (bit-identical),
        # not an algebraic reduction of the Robin formula -- S=0 means a
        # fixed density, S>0 a flux condition, genuinely different physics
        # (same branching principle Device1D's own S_n/S_p implementation
        # uses, and for the same reason).
        S_n_s = self.models.S_n * self.LD / D0_REF
        S_p_s = self.models.S_p * self.LD / D0_REF
        strip_rows_list = []
        extra_rows, extra_cols, extra_vals = [], [], []
        F3 = F.reshape(N, 3)
        for name, bc in self.bcs.items():
            if isinstance(bc, DirichletBC):
                V = voltages.get(name, bc.V)
                kk = bc.j * Nx + bc.i
                psi0, n0, p0 = self._bc_contact_values(bc, V)
                F3[kk, 0] = psi.ravel()[kk] - psi0
                strip_rows_list.append(3 * kk)
                if S_n_s == 0.0:
                    F3[kk, 1] = n.ravel()[kk] - n0
                    strip_rows_list.append(3 * kk + 1)
                else:
                    F3[kk, 1] += S_n_s * (n.ravel()[kk] - n0)
                    extra_rows.append(3 * kk + 1)
                    extra_cols.append(3 * kk + 1)
                    extra_vals.append(np.full(kk.shape, S_n_s))
                if S_p_s == 0.0:
                    F3[kk, 2] = p.ravel()[kk] - p0
                    strip_rows_list.append(3 * kk + 2)
                else:
                    F3[kk, 2] += S_p_s * (p.ravel()[kk] - p0)
                    extra_rows.append(3 * kk + 2)
                    extra_cols.append(3 * kk + 2)
                    extra_vals.append(np.full(kk.shape, S_p_s))
        if strip_rows_list:
            strip_rows = np.unique(np.concatenate(strip_rows_list))
            keep = ~np.isin(rows, strip_rows)
            rows, cols, vals = rows[keep], cols[keep], vals[keep]
            rows = np.concatenate([rows, strip_rows])
            cols = np.concatenate([cols, strip_rows])
            vals = np.concatenate([vals, np.ones_like(strip_rows, dtype=float)])
        if extra_rows:
            rows = np.concatenate([rows] + extra_rows)
            cols = np.concatenate([cols] + extra_cols)
            vals = np.concatenate([vals] + extra_vals)

        J = csr_matrix((vals, (rows, cols)), shape=(3 * N, 3 * N))
        # F_n, F_p (returned raw, pre-Dirichlet-overwrite, shape (Ny,Nx),
        # scaled units) are the box-integration continuity residuals.  At an
        # interior node they are ~0 by construction of the Newton solve; AT
        # a Dirichlet contact node they equal the net current (electron +
        # hole) the contact must supply to keep that control volume in
        # steady state -- used by terminal_current for an exactly
        # current-conserving extraction (see terminal_current docstring).
        return F3.ravel(), J, Jn_x, Jn_y, Jp_x, Jp_y, F_n, F_p

    # ------------------------------------------------------------------
    def solve_bias(self, voltages=None, opts: NewtonOptions = None):
        """Solve at applied bias.  voltages: {contact_name: V}; contacts
        not mentioned keep their previously set voltage.  Gate voltage is
        set the same way, using the gate's registered name."""
        opts = opts or NewtonOptions()
        if self.unstructured:
            return self._unstructured_solve_bias(voltages, opts)
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
                psi[bc.j, bc.i], n[bc.j, bc.i], p[bc.j, bc.i] = psi0, n0, p0

        cur_voltages = {name: bc.V for name, bc in self.bcs.items() if isinstance(bc, DirichletBC)}

        for it in range(opts.max_iter):
            if self.models.surface_mobility:
                self._update_surface_mobility(psi)
            F, J, Jn_x, Jn_y, Jp_x, Jp_y, _, _ = self._residual_jacobian(psi, n, p, cur_voltages)
            if opts.linsolve == "direct":
                du = spsolve(J.tocsc(), -F)
            else:
                du, _ = linsolve.solve_linear(
                    J, -F, method=opts.linsolve, rtol=opts.linsolve_rtol,
                    block_size=3)
            dpsi = du[0::3].reshape(self.Ny, self.Nx)
            dn = du[1::3].reshape(self.Ny, self.Nx)
            dp = du[2::3].reshape(self.Ny, self.Nx)

            dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
            n_old, p_old = n, p
            n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
            p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)
            psi = psi + dpsi
            n, p = n_new, p_new

            # M11-S5: relative updates are measured against a density
            # floor -- deep-minority nodes (e.g. inside an AlGaAs
            # barrier, p ~ 1e-13 scaled) otherwise pin the criterion to
            # roundoff and stall the solve at a harmless limit cycle.
            # Densities below 1e-10 scaled carry <= 1e-10 of the local
            # Poisson charge; their exact value is numerically
            # meaningless.  Equilibrium (slaved-carrier) solves are
            # unaffected.
            rel_n = (np.abs(n_new - n_old)
                     / np.maximum(n_old, 1e-10)).max()
            rel_p = (np.abs(p_new - p_old)
                     / np.maximum(p_old, 1e-10)).max()
            err = max(np.abs(dpsi).max(), rel_n, rel_p)
            if opts.verbose:
                print(f"    it {it:2d}  |dpsi|={np.abs(dpsi).max():.3e}  |dn/n|={rel_n:.3e}")
            if err < opts.tol_update:
                break
        else:
            warnings.warn(f"2D Newton did not converge; last update {err:.2e}")

        self.psi, self.n, self.p = psi, n, p
        _, _, Jn_x, Jn_y, Jp_x, Jp_y, _, _ = self._residual_jacobian(psi, n, p, cur_voltages)
        self.Jn_x, self.Jp_x = Jn_x * self.J0, Jp_x * self.J0
        self.Jn_y, self.Jp_y = Jn_y * self.J0, Jp_y * self.J0
        return self

    # ------------------------------------------------------------------
    def terminal_current(self, name):
        """Total (Jn+Jp) current [A/cm] flowing INTO the device through a
        named Dirichlet contact.

        Extracted from the box-integration continuity residual (F_n, F_p)
        evaluated at the contact's nodes BEFORE the Dirichlet row-overwrite
        replaces them with the fixed-value equations.  At those raw values,
        F_n/F_p is the true net divergence of (Jn, Jp) out of that node's
        control volume (charge conservation), which the contact must supply
        -- this includes every edge touching the contact (top, bottom, and
        any lateral seam into a non-contact neighbor) with the correct
        sign, automatically, with no separate edge-walking or restriction
        to a single boundary row.
        """
        if self.unstructured:
            return self._unstructured_terminal_current(name)
        bc = self.bcs[name]
        if not isinstance(bc, DirichletBC):
            raise ValueError(f"terminal_current: '{name}' is not a Dirichlet contact")
        if self.psi is None:
            raise RuntimeError("terminal_current: solve the device first")

        cur_voltages = {nm: b.V for nm, b in self.bcs.items() if isinstance(b, DirichletBC)}
        *_, F_n, F_p = self._residual_jacobian(self.psi, self.n, self.p, cur_voltages)

        kk = bc.j * self.Nx + bc.i
        # F_n/F_p at a (pre-overwrite) contact node is exactly the current
        # the contact must supply to satisfy charge conservation in that
        # control volume -- verified empirically against the known-good
        # forward-diode current (test_bias_2d_reduces_to_1d's Jtot_2d):
        # this sign convention makes the higher-potential ("anode")
        # contact's current come out positive, matching Jtot_2d.mean().
        I = float((F_n.ravel()[kk] + F_p.ravel()[kk]).sum()) * self.J0 * self.LD
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
