"""M21 phase 3c -- coupled drift-diffusion BIAS solve on an unstructured
triangle mesh (psi, n, p -- 3 unknowns per node, up from phase 3b's
Poisson-only 1). Scharfetter-Gummel current on triangle edges, SRH
recombination, Newton-solved.

Scope (M21-PHASE3-MESHING-PLAN.md section 1, steps 6-10 of the
implementation order): the same per-edge `trans` geometry factor phase
3b's Poisson solve already uses (dual_facet_length/primal_edge_length,
from unstructured_assembly.build_edge_flux_geometry) serves the SG
current term too, with NO new geometric quantity -- re-derived directly
from the structured formulas (device2d.py's own edge-scatter pattern:
current is scattered into the continuity residual weighted by the
transverse dual width, exactly the same weighting Poisson's flux
already uses), not assumed from the plan's handoff notes.

Homojunction-only simplifications (stated, not hidden, mirroring
phase 3b's uniform-eps_r one): mobility is `material.mu_n_max`/
`mu_p_max` UNIFORMLY (no Caughey-Thomas doping dependence); no
heterojunction ln(nie) edge term (delta = psi_j - psi_i for both
carriers); SRH lifetimes are the material's own tau_n0/tau_p0
constants (no Scharfetter doping-dependent lifetime); Auger is off by
default. `Device2D(unstructured=True)` class-level integration is
explicitly NOT built -- this module is a standalone, directly-tested
physics core, the same relationship `unstructured_poisson.py` has to
`Device2D._residual_jacobian_poisson`.
"""
import warnings

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .constants import Q, EPS0
from .device import (
    NewtonOptions, thermal_voltage, bernoulli, dbernoulli, D0_REF,
)
from .device2d import _ohmic_values
from .materials import SILICON, recombination
from .unstructured_poisson import evaluate_doping_at_nodes  # re-exported


def _residual_jacobian(psi, n, p, C_s, nie_s, node_areas_s, interior_edges,
                       eps_trans, D_n_s, D_p_s, R0, tau_n, tau_p, material,
                       Ns, srh=True, auger=False):
    """Scaled coupled residual/Jacobian for the INTERIOR physics only
    (no Dirichlet contact rows -- solve_bias overwrites those after
    calling this, the same split phase 3b's Poisson solver uses).
    Interleaved [psi_i, n_i, p_i] per node, continuation.py's own
    convention for this kind of externally-driven assembly.

    eps_trans: eps * (dual_facet_length/primal_edge_length) per
    interior edge -- Poisson's own prefactor.
    D_n_s, D_p_s: scaled diffusivities (mu*VT/D0_REF), UNIFORM scalars
    this slice (homojunction). The continuity prefactor per edge is
    D_n_s/D0_REF-normalized trans, i.e. (eps_trans/eps)*D_n_s -- reusing
    the SAME geometric ratio, just swapping the physical constant.
    """
    N = psi.shape[0]
    n_phys, p_phys = n * Ns, p * Ns
    trans = eps_trans / material.eps_r / EPS0   # recover the bare geometry ratio

    if srh:
        R, dRdn, dRdp = recombination(n_phys, p_phys, nie_s * Ns,
                                      tau_n, tau_p, material, auger=auger)
    else:
        R = np.zeros(N); dRdn = np.zeros(N); dRdp = np.zeros(N)
    Rs = R / R0
    dRs_dn = dRdn * Ns / R0
    dRs_dp = dRdp * Ns / R0

    F = np.zeros(3 * N)
    F[1::3] = -Rs * node_areas_s
    F[2::3] = Rs * node_areas_s

    rows, cols, vals = [], [], []
    diag_k = np.arange(N)

    def add(r, c, v):
        r = np.atleast_1d(np.asarray(r))
        c = np.atleast_1d(np.asarray(c))
        v = np.broadcast_to(np.asarray(v, dtype=float), r.shape)
        rows.append(r); cols.append(c); vals.append(np.array(v))

    add(3 * diag_k + 1, 3 * diag_k + 1, -dRs_dn * node_areas_s)
    add(3 * diag_k + 1, 3 * diag_k + 2, -dRs_dp * node_areas_s)
    add(3 * diag_k + 2, 3 * diag_k + 1, dRs_dn * node_areas_s)
    add(3 * diag_k + 2, 3 * diag_k + 2, dRs_dp * node_areas_s)

    # --- Poisson: F_psi[k] = -area*(n-p-C) + sum_edges eps_trans*(psi_j-psi_i) ---
    F[0::3] = -node_areas_s * (n - p - C_s)
    add(3 * diag_k, 3 * diag_k + 1, -node_areas_s)
    add(3 * diag_k, 3 * diag_k + 2, node_areas_s)

    i_idx = interior_edges[:, 0]
    j_idx = interior_edges[:, 1]
    dpsi_flux = eps_trans * (psi[j_idx] - psi[i_idx])
    np.add.at(F[0::3], i_idx, dpsi_flux)
    np.add.at(F[0::3], j_idx, -dpsi_flux)

    add(3 * i_idx, 3 * i_idx, -eps_trans)
    add(3 * i_idx, 3 * j_idx, eps_trans)
    add(3 * j_idx, 3 * j_idx, -eps_trans)
    add(3 * j_idx, 3 * i_idx, eps_trans)

    # --- continuity: Scharfetter-Gummel current on each edge ---
    delta = psi[j_idx] - psi[i_idx]
    Bp, Bm = bernoulli(delta), bernoulli(-delta)
    dBp, dBm = dbernoulli(delta), dbernoulli(-delta)
    n_i, n_j = n[i_idx], n[j_idx]
    p_i, p_j = p[i_idx], p[j_idx]

    Jn = D_n_s * trans * (n_j * Bp - n_i * Bm)
    Jp = -D_p_s * trans * (p_j * Bm - p_i * Bp)
    np.add.at(F[1::3], i_idx, Jn)
    np.add.at(F[1::3], j_idx, -Jn)
    np.add.at(F[2::3], i_idx, Jp)
    np.add.at(F[2::3], j_idx, -Jp)

    dJn_dpsi_j = D_n_s * trans * (n_j * dBp + n_i * dBm)
    dJn_dn_j = D_n_s * trans * Bp
    dJn_dn_i = -D_n_s * trans * Bm
    add(3 * i_idx + 1, 3 * i_idx, -dJn_dpsi_j)
    add(3 * i_idx + 1, 3 * j_idx, dJn_dpsi_j)
    add(3 * i_idx + 1, 3 * i_idx + 1, dJn_dn_i)
    add(3 * i_idx + 1, 3 * j_idx + 1, dJn_dn_j)
    add(3 * j_idx + 1, 3 * i_idx, dJn_dpsi_j)
    add(3 * j_idx + 1, 3 * j_idx, -dJn_dpsi_j)
    add(3 * j_idx + 1, 3 * i_idx + 1, -dJn_dn_i)
    add(3 * j_idx + 1, 3 * j_idx + 1, -dJn_dn_j)

    dJp_dpsi_j = D_p_s * trans * (p_j * dBm + p_i * dBp)
    dJp_dp_j = -D_p_s * trans * Bm
    dJp_dp_i = D_p_s * trans * Bp
    add(3 * i_idx + 2, 3 * i_idx, -dJp_dpsi_j)
    add(3 * i_idx + 2, 3 * j_idx, dJp_dpsi_j)
    add(3 * i_idx + 2, 3 * i_idx + 2, dJp_dp_i)
    add(3 * i_idx + 2, 3 * j_idx + 2, dJp_dp_j)
    add(3 * j_idx + 2, 3 * i_idx, dJp_dpsi_j)
    add(3 * j_idx + 2, 3 * j_idx, -dJp_dpsi_j)
    add(3 * j_idx + 2, 3 * i_idx + 2, -dJp_dp_i)
    add(3 * j_idx + 2, 3 * j_idx + 2, -dJp_dp_j)

    J = sp.csr_matrix((np.concatenate(vals),
                       (np.concatenate(rows), np.concatenate(cols))),
                      shape=(3 * N, 3 * N))
    return F, J, Jn, Jp


def solve_bias(nodes, triangles, edge_list, node_areas, interior_edges,
              trans_geom, C_phys, contacts, bias, material=SILICON,
              T=300.0, opts=None, srh=True, auger=False):
    """Newton-solve the coupled unstructured drift-diffusion system at
    an applied bias.

    bias: {contact_name: V [volts]}. Any contact not mentioned keeps
    V=0.
    contacts: {name: (K, 2) boundary-edge node-index array} from
    region_resolver.resolve_contacts().

    Returns (psi, n, p) [all scaled, dimensionless] plus the scaling
    dict (Ns, LD, VT, nie, eps, R0) and a per-contact terminal current
    dict [A/cm, matching Device2D.terminal_current's 2D convention --
    this is a 2D unstructured mesh, same physical units].
    """
    opts = opts or NewtonOptions()
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    nie = material.ni(T)
    Ns = max(float(np.abs(C_phys).max()), nie)
    LD = np.sqrt(eps * VT / (Q * Ns))
    R0 = D0_REF * Ns / LD ** 2

    C_s = C_phys / Ns
    nie_s = nie / Ns
    areas_s = node_areas / LD ** 2
    eps_trans = trans_geom * eps
    D_n_s = material.mu_n_max * VT / D0_REF
    D_p_s = material.mu_p_max * VT / D0_REF
    tau_n = np.full_like(C_phys, material.tau_n0)
    tau_p = np.full_like(C_phys, material.tau_p0)

    contact_node_bias = {}
    for name, edges in contacts.items():
        V = bias.get(name, 0.0)
        for i, j in edges:
            for node in (int(i), int(j)):
                contact_node_bias[node] = V
    contact_idx = np.array(sorted(contact_node_bias), dtype=int)
    contact_V = np.array([contact_node_bias[k] for k in contact_idx])
    psi0, n0, p0 = _ohmic_values(C_s[contact_idx], nie_s, contact_V, VT)

    # warm start: equilibrium first (V=0 everywhere), matching
    # Device1D/Device2D.solve_bias's own convention
    psi = np.arcsinh(C_s / (2.0 * nie_s))
    n = np.where(C_s >= 0, 0.5 * (C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)),
                nie_s ** 2 / np.maximum(
                    0.5 * (-C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)), 1e-300))
    p = nie_s ** 2 / np.maximum(n, 1e-300)
    psi[contact_idx], n[contact_idx], p[contact_idx] = psi0, n0, p0

    N = psi.shape[0]
    last_converged = False
    for it in range(opts.max_iter):
        F, J, Jn, Jp = _residual_jacobian(
            psi, n, p, C_s, nie_s, areas_s, interior_edges, eps_trans,
            D_n_s, D_p_s, R0, tau_n, tau_p, material, Ns, srh=srh,
            auger=auger)
        F3 = F.reshape(N, 3)
        F3[contact_idx, 0] = psi[contact_idx] - psi0
        F3[contact_idx, 1] = n[contact_idx] - n0
        F3[contact_idx, 2] = p[contact_idx] - p0

        Jl = J.tolil()
        for comp in range(3):
            rows = 3 * contact_idx + comp
            Jl[rows, :] = 0.0
            Jl[rows, rows] = 1.0
        Jc = Jl.tocsc()

        du = spsolve(Jc, -F3.ravel())
        dpsi, dn, dp = du[0::3], du[1::3], du[2::3]
        dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
        n_old, p_old = n, p
        n = np.clip(n + dn, 0.1 * n, 10.0 * n)
        p = np.clip(p + dp, 0.1 * p, 10.0 * p)
        psi = psi + dpsi

        rel_n = np.abs(n / np.maximum(n_old, 1e-300) - 1.0).max()
        rel_p = np.abs(p / np.maximum(p_old, 1e-300) - 1.0).max()
        err = max(float(np.abs(dpsi).max()), float(rel_n), float(rel_p))
        if opts.verbose:
            print(f"    unstructured-dd it {it:2d}  |dpsi|={np.abs(dpsi).max():.3e}"
                 f"  |dn/n|={rel_n:.3e}")
        if err < opts.tol_update:
            last_converged = True
            break
    else:
        warnings.warn("unstructured coupled bias solve did not converge.")

    _, _, Jn, Jp = _residual_jacobian(
        psi, n, p, C_s, nie_s, areas_s, interior_edges, eps_trans,
        D_n_s, D_p_s, R0, tau_n, tau_p, material, Ns, srh=srh, auger=auger)

    terminal_current = {}
    for name, edges in contacts.items():
        nodes_here = np.unique(edges)
        i_idx, j_idx = interior_edges[:, 0], interior_edges[:, 1]
        I = 0.0
        # terminal current = net (electron+hole) flux leaving this
        # contact's nodes through their INTERIOR edges (the same
        # box-residual-based extraction Device2D.terminal_current uses,
        # here computed directly from the per-edge Jn/Jp arrays since
        # contact rows were overwritten in F but Jn/Jp above were
        # computed from the CONVERGED (psi, n, p), which already
        # satisfies the contact Dirichlet values exactly).
        mask_i = np.isin(i_idx, nodes_here)
        mask_j = np.isin(j_idx, nodes_here)
        I += float((Jn[mask_i] + Jp[mask_i]).sum())
        I -= float((Jn[mask_j] + Jp[mask_j]).sum())
        J0 = Q * D0_REF * Ns / LD
        terminal_current[name] = I * J0 * LD

    scale = dict(Ns=Ns, LD=LD, VT=VT, nie=nie, eps=eps, R0=R0,
                last_converged=last_converged)
    return psi, n, p, scale, terminal_current
