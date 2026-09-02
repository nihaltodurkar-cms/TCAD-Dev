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
phase 3b's uniform-eps_r one): SRH lifetimes are the material's own
tau_n0/tau_p0 constants (no Scharfetter doping-dependent lifetime);
Auger is off by default. `Device2D(unstructured=True)` class-level
integration is explicitly NOT built -- this module is a standalone,
directly-tested physics core, the same relationship
`unstructured_poisson.py` has to `Device2D._residual_jacobian_poisson`.

M21-follow-up (doping-dependent mobility + heterojunctions): `solve_bias`
now accepts `doping_mobility` and `materials_per_node`, mirroring
device2d.py's own per-node material grouping:

  - `doping_mobility=False` (default) reproduces the ORIGINAL uniform
    `material.mu_n_max`/`mu_p_max` behavior bit-for-bit -- this is the
    regression safety net (see test_unstructured_dd.py
    test_homojunction_unchanged).
  - `doping_mobility=True` evaluates `materials.mobility_caughey_thomas`
    per node from `Ntot_phys` (total ionized impurity N_A+N_D, NOT net
    doping -- same caveat as materials.py's own docstring), then takes
    the SAME harmonic mean across each edge's two endpoint mobilities
    that device2d.py's `dn_edge_x`/`dn_edge_y` use at structured cell
    faces (Meyer et al.-style TPFA: harmonic mean is the right average
    for a diffusive/conductive flux in series across the two half-edges).
  - `materials_per_node` (array of `Semiconductor`, one per node;
    default: all `material`, i.e. homojunction) enables the Anderson
    band-offset heterojunction term device2d.py adds at structured cell
    faces: a per-edge `ln(nie_s[j]/nie_s[i])` shift added to the
    electron SG argument and SUBTRACTED from the hole one (opposite
    signs -- device2d.py's own comment on why a shared-sign delta
    breaks hole detailed balance applies identically here). With a
    uniform `materials_per_node`, `dlnnie == 0` everywhere and this
    reduces algebraically to the homojunction SG current.

NOT implemented (explicit, matching device2d.py's own unstructured
refusal list): Fermi-Dirac statistics, bandgap narrowing, incomplete
ionization, surface/field-dependent mobility, doping-dependent (vs.
constant) SRH lifetime. A future session wanting these should extend
`materials_per_node`-style per-node grouping the same way, not bolt
them on ad hoc.
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
from .materials import SILICON, recombination, mobility_caughey_thomas
from .unstructured_poisson import evaluate_doping_at_nodes  # re-exported


def _residual_jacobian(psi, n, p, C_s, nie_s, node_areas_s, interior_edges,
                       eps_trans, D_n_s, D_p_s, R0, tau_n, tau_p, material,
                       Ns, srh=True, auger=False, dlnnie=None):
    """Scaled coupled residual/Jacobian for the INTERIOR physics only
    (no Dirichlet contact rows -- solve_bias overwrites those after
    calling this, the same split phase 3b's Poisson solver uses).
    Interleaved [psi_i, n_i, p_i] per node, continuation.py's own
    convention for this kind of externally-driven assembly.

    eps_trans: eps * (dual_facet_length/primal_edge_length) per
    interior edge -- Poisson's own prefactor.
    D_n_s, D_p_s: scaled diffusivities (mu*VT/D0_REF) PER INTERIOR EDGE
    (harmonic mean of the two endpoint mobilities when doping_mobility
    is on; a uniform scalar broadcasts unchanged for the homojunction,
    uniform-mobility case). The continuity prefactor per edge is
    D_n_s/D0_REF-normalized trans, i.e. (eps_trans/eps)*D_n_s -- reusing
    the SAME geometric ratio, just swapping the physical constant.
    nie_s: per-NODE scaled intrinsic concentration (array); a uniform
    array reduces this to the old homojunction scalar broadcast.
    dlnnie: per-INTERIOR-EDGE ln(nie_s[j]/nie_s[i]) heterojunction band-
    offset shift (device2d.py's own Anderson-offset SG term); None or
    all-zero reproduces the homojunction current exactly.
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
    # Anderson band-offset shift (device2d.py section "M11-S4"):
    # electron argument gains +dlnnie, hole argument gains -dlnnie
    # (opposite signs -- a shared-sign delta breaks hole detailed
    # balance). dlnnie is exactly zero for a homojunction.
    dz = 0.0 if dlnnie is None else dlnnie
    delta_n = psi[j_idx] - psi[i_idx] + dz
    delta_p = psi[j_idx] - psi[i_idx] - dz
    Bp, Bm = bernoulli(delta_n), bernoulli(-delta_n)
    dBp, dBm = dbernoulli(delta_n), dbernoulli(-delta_n)
    Bp_h, Bm_h = bernoulli(delta_p), bernoulli(-delta_p)
    dBp_h, dBm_h = dbernoulli(delta_p), dbernoulli(-delta_p)
    n_i, n_j = n[i_idx], n[j_idx]
    p_i, p_j = p[i_idx], p[j_idx]

    Jn = D_n_s * trans * (n_j * Bp - n_i * Bm)
    Jp = -D_p_s * trans * (p_j * Bm_h - p_i * Bp_h)
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

    dJp_dpsi_j = D_p_s * trans * (p_j * dBm_h + p_i * dBp_h)
    dJp_dp_j = -D_p_s * trans * Bm_h
    dJp_dp_i = D_p_s * trans * Bp_h
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
              T=300.0, opts=None, srh=True, auger=False,
              doping_mobility=False, Ntot_phys=None, materials_per_node=None):
    """Newton-solve the coupled unstructured drift-diffusion system at
    an applied bias.

    bias: {contact_name: V [volts]}. Any contact not mentioned keeps
    V=0.
    contacts: {name: (K, 2) boundary-edge node-index array} from
    region_resolver.resolve_contacts().

    doping_mobility: if True, per-node mobility is
    materials.mobility_caughey_thomas(Ntot_phys, node's material, T,
    carrier), harmonic-averaged across each edge (device2d.py's own
    edge-mobility convention). Default False keeps the ORIGINAL uniform
    material.mu_n_max/mu_p_max behavior exactly.
    Ntot_phys: (N,) physical TOTAL ionized impurity concentration
    [cm^-3] per node (N_A+N_D, not net doping -- required, and used
    only, when doping_mobility=True).
    materials_per_node: (N,) array of Semiconductor, one per node, for
    heterojunction band offsets (default: all `material`, homojunction).
    `material` itself is still used for the overall scaling
    constants (Ns/LD/VT normalization reference), matching device2d.py's
    "first material is the scaling reference" convention.

    Returns (psi, n, p) [all scaled, dimensionless] plus the scaling
    dict (Ns, LD, VT, nie, eps, R0) and a per-contact terminal current
    dict [A/cm, matching Device2D.terminal_current's 2D convention --
    this is a 2D unstructured mesh, same physical units].
    """
    opts = opts or NewtonOptions()
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    N = C_phys.shape[0]
    mats = (np.array([material] * N, dtype=object) if materials_per_node is None
           else np.asarray(materials_per_node, dtype=object))
    nie_node = np.array([m.ni(T) for m in mats])
    nie = material.ni(T)   # reference material's nie for the scale dict
    Ns = max(float(np.abs(C_phys).max()), float(nie_node.max()))
    LD = np.sqrt(eps * VT / (Q * Ns))
    R0 = D0_REF * Ns / LD ** 2

    C_s = C_phys / Ns
    nie_s = nie_node / Ns          # per-NODE (array; uniform => old scalar)
    areas_s = node_areas / LD ** 2
    eps_trans = trans_geom * eps
    tau_n = np.full_like(C_phys, material.tau_n0)
    tau_p = np.full_like(C_phys, material.tau_p0)

    # --- per-node mobility (uniform mu_n_max/mu_p_max, or Caughey-
    # Thomas doping-dependent), then harmonic-mean onto interior edges
    # -- the same averaging device2d.py's dn_edge_x/dn_edge_y apply at
    # structured cell faces. ---
    if doping_mobility:
        if Ntot_phys is None:
            raise ValueError(
                "doping_mobility=True requires Ntot_phys (total ionized "
                "impurity concentration per node) -- net doping alone "
                "cannot recover it in compensated regions.")
        mu_n_node = np.empty(N); mu_p_node = np.empty(N)
        for m in {id(mm): mm for mm in mats}.values():
            sel = np.array([mm is m for mm in mats])
            mu_n_node[sel] = mobility_caughey_thomas(Ntot_phys[sel], m, T, "n")
            mu_p_node[sel] = mobility_caughey_thomas(Ntot_phys[sel], m, T, "p")
    else:
        mu_n_node = np.array([m.mu_n_max for m in mats])
        mu_p_node = np.array([m.mu_p_max for m in mats])

    def hmean(lo, hi):
        return 2.0 * lo * hi / (lo + hi)

    i_e, j_e = interior_edges[:, 0], interior_edges[:, 1]
    D_n_s = hmean(mu_n_node[i_e], mu_n_node[j_e]) * VT / D0_REF
    D_p_s = hmean(mu_p_node[i_e], mu_p_node[j_e]) * VT / D0_REF
    dlnnie = np.log(nie_s[j_e] / nie_s[i_e])

    contact_node_bias = {}
    for name, edges in contacts.items():
        V = bias.get(name, 0.0)
        for i, j in edges:
            for node in (int(i), int(j)):
                contact_node_bias[node] = V
    contact_idx = np.array(sorted(contact_node_bias), dtype=int)
    contact_V = np.array([contact_node_bias[k] for k in contact_idx])
    psi0, n0, p0 = _ohmic_values(C_s[contact_idx], nie_s[contact_idx],
                                 contact_V, VT)

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
            auger=auger, dlnnie=dlnnie)
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
        D_n_s, D_p_s, R0, tau_n, tau_p, material, Ns, srh=srh, auger=auger,
        dlnnie=dlnnie)

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
