"""3D (tetrahedral-mesh) sibling of unstructured_dd.py/unstructured_
poisson.py, fused into one module (Poisson equilibrium + coupled
Scharfetter-Gummel drift-diffusion bias) rather than split across two
files -- the 3D geometry setup (unstructured_assembly3d.py) is
expensive enough per call that both solves sharing one module keeps
the call sites (and this module's own tests) from re-deriving it
twice.

Physics: box-integration finite-volume, EXACTLY unstructured_dd.py's
own residual/Jacobian, with the 2D "dual_facet_length/primal_edge_
length" TPFA factor replaced by 3D's "dual_facet_area/primal_edge_
length" one from unstructured_assembly3d.build_edge_flux_geometry3d,
and node_areas (2D, [cm^2]) replaced by node_volumes (3D, [cm^3]) from
unstructured_assembly3d.build_unstructured_stencil3d. No new physics
term versus unstructured_dd.py -- same Scharfetter-Gummel current, same
SRH recombination, same Newton scheme.

Scope, stated honestly (matching this repo's own convention for a
first tetrahedral-mesh pass):

  - Caughey-Thomas doping-dependent mobility IS supported here
    (doping_mobility=True, Ntot_phys) -- ported directly from
    unstructured_dd.py's harmonic-edge-mean approach, since it needed
    no new 3D geometry.
  - HETEROJUNCTIONS ARE NOT SUPPORTED in this module (no
    materials_per_node parameter, no ln(nie) edge term) -- explicit
    scope-down from unstructured_dd.py's 2D heterojunction support,
    per this task's own instructions ("homojunction-only is fine to
    START with for 3D"). A future session wanting this should port
    unstructured_dd.py's dlnnie mechanism the same way Caughey-Thomas
    was ported here -- it needs no new 3D geometry either.
  - SRH lifetimes are the material's own tau_n0/tau_p0 constants (no
    Scharfetter doping-dependent lifetime); Auger is off by default;
    no Fermi-Dirac statistics, bandgap narrowing, incomplete
    ionization, or field/surface mobility -- same refusal list as
    unstructured_dd.py's own.

Validated (tests/test_unstructured_dd3d.py) against the ALREADY-
VALIDATED structured Device3D/Mesh3D solver, in THREE separate
regimes:

  - Poisson EQUILIBRIUM on the z-invariant p-n slab geometry
    test_validation_3d.py's own test_bias_3d_reduces_to_2d fixture
    uses: bulk built-in potential matches the analytic arcsinh(C/2nie)
    value (and the structured solver) to float-precision -- this
    confirms the tet dual-volume/TPFA-area geometry and residual/
    Jacobian assembly are correct.
  - An OHMIC (uniform-doping) resistor bar under small bias: measured
    current agrees with the structured solver (and the analytic
    I=q*mu*n*A*V/L Ohmic limit) to ~15-25%, the same order of FVM
    discretization tolerance test_m21_phase3.py's own 2D G4 gate
    already established for an independent-discretization comparison.
  - A forward-biased p-n JUNCTION under SRH recombination (the case a
    prior pass of this module flagged as an unresolved 1-2-orders-of-
    magnitude gap, attributed -- WITHOUT having actually diagnosed it
    -- to per-node doping smoothing near the junction): that gap was
    a genuine bug, since fixed, NOT a doping/mesh-resolution
    limitation. Root cause, confirmed by direct instrumentation
    against the structured Device3D reference on matched geometry:
    R0 (the physical-to-scaled recombination-rate normalization in
    solve_bias3d) was `D0_REF * Ns / LD**2`, copied verbatim from
    unstructured_dd.py's 2D module -- correct THERE because 2D's
    node_areas_s divides by LD**2, but wrong here because this
    module's node_vols_s divides by LD**3 (one more power of LD, a 3D
    dual-cell VOLUME vs. a 2D dual-cell AREA). The missing power of
    LD (~1.29e-6 cm for the Nd=1e17 test fixture, so R0 too small by
    ~7.7e5x) inflated the SCALED SRH sink Rs=R/R0 by the same factor,
    corrupting the coupled solve wherever SRH mattered while leaving
    equilibrium (bulk charge-neutrality only, no flux/recombination
    balance) and the srh=False Ohmic path untouched -- exactly the
    "equilibrium fine, forward bias badly wrong" signature originally
    observed. Fixed by changing R0 to `D0_REF * Ns / LD**3`. Measured
    (test_unstructured_dd3d.py's test_forward_junction_matches_
    structured, direct instrumentation against Device3D on the SAME
    Nd_scale=1e17/Xj=1e-4 geometry, srh=True, doping_mobility=False
    on both sides so only the discretization differs): ratio
    unstructured/structured = 1.19 (0.3V), 1.22 (0.5V), 1.23 (0.6V) --
    the SAME ~20-25% band the Ohmic/srh=False case already showed, not
    the exponentially-blown-up 30-60x this bug produced before the
    fix. A mesh-grading refinement (finer SizeMin/wider DistMax near
    the junction) was tried FIRST as the suspected fix and made
    essentially no difference (33x -> 36x, still wrong) -- ruling out
    "doping smoothing"/mesh coarseness as the actual cause before the
    R0 bug was found by direct dimensional derivation, not left as an
    unconfirmed hypothesis this time.
"""
import warnings

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .constants import Q, EPS0
from .device import NewtonOptions, thermal_voltage, bernoulli, dbernoulli, D0_REF
from .device2d import _ohmic_values
from .materials import SILICON, recombination, mobility_caughey_thomas


def evaluate_doping_at_nodes3d(nodes, tets, region_of_tet, doping_by_region):
    """Per-node net doping [cm^-3], tet-volume-weighted over each
    node's touching tets -- the 3D analogue of unstructured_poisson.
    evaluate_doping_at_nodes (barycentric weight: vol/4 per vertex,
    matching this module's own dual-volume convention). A node on a
    region boundary gets a volume-weighted AVERAGE, the same honest
    "one row of smoothing at the step junction" simplification the 2D
    function's docstring already states.
    """
    nodes_xyz = np.asarray(nodes, dtype=float)[:, :3]
    tet = np.asarray(tets, dtype=int)
    N = nodes_xyz.shape[0]
    weighted = np.zeros(N)
    weight = np.zeros(N)
    for t_idx, verts in enumerate(tet):
        pts = nodes_xyz[verts]
        vol = abs(np.dot(pts[1] - pts[0],
                         np.cross(pts[2] - pts[0], pts[3] - pts[0]))) / 6.0
        dop = doping_by_region[region_of_tet[t_idx]]
        for v in verts:
            weighted[v] += dop * vol / 4.0
            weight[v] += vol / 4.0
    return weighted / weight


def _residual_jacobian_poisson3d(psi, C_s, nie_s, node_vols_s, edges, trans):
    """Scaled Poisson-equilibrium residual/Jacobian (Boltzmann carriers
    slaved to psi) -- 3D analogue of unstructured_poisson._residual_
    jacobian, node_areas -> node_vols_s, otherwise identical."""
    N = psi.shape[0]
    n = nie_s * np.exp(np.clip(psi, -700, 700))
    p = nie_s * np.exp(np.clip(-psi, -700, 700))
    dnp = n + p

    F = -node_vols_s * (n - p - C_s)
    i_idx, j_idx = edges[:, 0], edges[:, 1]
    flux = trans * (psi[j_idx] - psi[i_idx])
    np.add.at(F, i_idx, flux)
    np.add.at(F, j_idx, -flux)

    rows = np.concatenate([i_idx, i_idx, j_idx, j_idx, np.arange(N)])
    cols = np.concatenate([i_idx, j_idx, j_idx, i_idx, np.arange(N)])
    vals = np.concatenate([-trans, trans, -trans, trans, -node_vols_s * dnp])
    J = sp.csr_matrix((vals, (rows, cols)), shape=(N, N))
    return F, J


def solve_poisson_equilibrium3d(nodes, tets, edges, node_vols, trans_geom,
                                C_phys, contacts, material=SILICON,
                                T=300.0, opts=None):
    """Newton-solve the 3D tet-mesh Poisson equilibrium. 3D analogue
    of unstructured_poisson.solve_poisson_equilibrium; contacts here
    are {name: (K, 3) boundary-face node-index array} (triangular
    faces, not edges)."""
    opts = opts or NewtonOptions()
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    nie = material.ni(T)
    Ns = max(float(np.abs(C_phys).max()), nie)
    LD = np.sqrt(eps * VT / (Q * Ns))

    C_s = C_phys / Ns
    nie_s = nie / Ns
    vols_s = node_vols / LD ** 3
    trans_s = trans_geom * eps

    contact_node = {}
    for faces in contacts.values():
        for tri in faces:
            for node in map(int, tri):
                if node not in contact_node:
                    psi0, _, _ = _ohmic_values(C_s[node], nie_s, 0.0, VT)
                    contact_node[node] = float(psi0)
    contact_idx = np.array(sorted(contact_node), dtype=int)
    contact_psi0 = np.array([contact_node[k] for k in contact_idx])

    psi = np.arcsinh(C_s / (2.0 * nie_s))
    psi[contact_idx] = contact_psi0

    N = psi.shape[0]
    for it in range(opts.max_iter):
        F, J = _residual_jacobian_poisson3d(psi, C_s, nie_s, vols_s, edges, trans_s)
        F[contact_idx] = psi[contact_idx] - contact_psi0
        J = J.tolil()
        J[contact_idx, :] = 0.0
        J[contact_idx, contact_idx] = 1.0
        J = J.tocsc()

        d = spsolve(J, -F)
        d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
        psi = psi + d
        if opts.verbose:
            print(f"    unstructured3d-eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
        if np.abs(d).max() < opts.tol_update:
            break
    else:
        warnings.warn("unstructured3d Poisson equilibrium solve did not converge.")

    return psi, dict(Ns=Ns, LD=LD, VT=VT, nie=nie, eps=eps)


def _residual_jacobian_dd3d(psi, n, p, C_s, nie_s, node_vols_s, edges,
                            eps_trans, D_n_s, D_p_s, R0, tau_n, tau_p,
                            material, Ns, srh=True, auger=False):
    """Scaled coupled residual/Jacobian, interior physics only -- exact
    3D analogue of unstructured_dd._residual_jacobian (node_areas ->
    node_vols_s; no dlnnie term, this module is homojunction-only)."""
    N = psi.shape[0]
    n_phys, p_phys = n * Ns, p * Ns
    trans = eps_trans / material.eps_r / EPS0

    if srh:
        R, dRdn, dRdp = recombination(n_phys, p_phys, nie_s * Ns,
                                      tau_n, tau_p, material, auger=auger)
    else:
        R = np.zeros(N); dRdn = np.zeros(N); dRdp = np.zeros(N)
    Rs = R / R0
    dRs_dn = dRdn * Ns / R0
    dRs_dp = dRdp * Ns / R0

    F = np.zeros(3 * N)
    F[1::3] = -Rs * node_vols_s
    F[2::3] = Rs * node_vols_s

    rows, cols, vals = [], [], []
    diag_k = np.arange(N)

    def add(r, c, v):
        r = np.atleast_1d(np.asarray(r))
        c = np.atleast_1d(np.asarray(c))
        v = np.broadcast_to(np.asarray(v, dtype=float), r.shape)
        rows.append(r); cols.append(c); vals.append(np.array(v))

    add(3 * diag_k + 1, 3 * diag_k + 1, -dRs_dn * node_vols_s)
    add(3 * diag_k + 1, 3 * diag_k + 2, -dRs_dp * node_vols_s)
    add(3 * diag_k + 2, 3 * diag_k + 1, dRs_dn * node_vols_s)
    add(3 * diag_k + 2, 3 * diag_k + 2, dRs_dp * node_vols_s)

    F[0::3] = -node_vols_s * (n - p - C_s)
    add(3 * diag_k, 3 * diag_k + 1, -node_vols_s)
    add(3 * diag_k, 3 * diag_k + 2, node_vols_s)

    i_idx, j_idx = edges[:, 0], edges[:, 1]
    dpsi_flux = eps_trans * (psi[j_idx] - psi[i_idx])
    np.add.at(F[0::3], i_idx, dpsi_flux)
    np.add.at(F[0::3], j_idx, -dpsi_flux)

    add(3 * i_idx, 3 * i_idx, -eps_trans)
    add(3 * i_idx, 3 * j_idx, eps_trans)
    add(3 * j_idx, 3 * j_idx, -eps_trans)
    add(3 * j_idx, 3 * i_idx, eps_trans)

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


def solve_bias3d(nodes, tets, edges, node_vols, trans_geom, C_phys, contacts,
                 bias, material=SILICON, T=300.0, opts=None, srh=True,
                 auger=False, doping_mobility=False, Ntot_phys=None,
                 init=None, return_diagnostics=False):
    """Newton-solve the coupled 3D tet-mesh drift-diffusion system at
    an applied bias. 3D analogue of unstructured_dd.solve_bias.

    contacts: {name: (K, 3) boundary-face node-index array}.
    doping_mobility/Ntot_phys: same Caughey-Thomas mobility support as
    unstructured_dd.solve_bias (harmonic edge mean); NO heterojunction
    support here (see module docstring).

    init / return_diagnostics: same M21 adaptive-refinement warm-start /
    per-node Newton-residual-history opt-ins as unstructured_dd.
    solve_bias -- see that function's docstring. Default behavior
    (init=None, return_diagnostics=False) is unchanged.

    Returns (psi, n, p) [scaled] plus the scaling dict and a per-
    contact terminal current dict [A, NOT A/cm -- this is a genuine 3D
    mesh with no translational-invariance axis to divide out, unlike
    the 2D module's A/cm convention]. With return_diagnostics=True, a
    7th element {"n_iter", "residual_node_history"} is appended.
    """
    opts = opts or NewtonOptions()
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    nie = material.ni(T)
    Ns = max(float(np.abs(C_phys).max()), nie)
    LD = np.sqrt(eps * VT / (Q * Ns))
    R0 = D0_REF * Ns / LD ** 3

    C_s = C_phys / Ns
    nie_s = nie / Ns
    vols_s = node_vols / LD ** 3
    eps_trans = trans_geom * eps
    tau_n = np.full_like(C_phys, material.tau_n0)
    tau_p = np.full_like(C_phys, material.tau_p0)

    N = C_phys.shape[0]
    i_e, j_e = edges[:, 0], edges[:, 1]
    if doping_mobility:
        if Ntot_phys is None:
            raise ValueError(
                "doping_mobility=True requires Ntot_phys (total ionized "
                "impurity concentration per node).")
        mu_n_node = mobility_caughey_thomas(Ntot_phys, material, T, "n")
        mu_p_node = mobility_caughey_thomas(Ntot_phys, material, T, "p")
    else:
        mu_n_node = np.full(N, material.mu_n_max)
        mu_p_node = np.full(N, material.mu_p_max)

    def hmean(lo, hi):
        return 2.0 * lo * hi / (lo + hi)

    D_n_s = hmean(mu_n_node[i_e], mu_n_node[j_e]) * VT / D0_REF
    D_p_s = hmean(mu_p_node[i_e], mu_p_node[j_e]) * VT / D0_REF

    contact_node_bias = {}
    for name, faces in contacts.items():
        V = bias.get(name, 0.0)
        for tri in faces:
            for node in map(int, tri):
                contact_node_bias[node] = V
    contact_idx = np.array(sorted(contact_node_bias), dtype=int)
    contact_V = np.array([contact_node_bias[k] for k in contact_idx])
    psi0, n0, p0 = _ohmic_values(C_s[contact_idx], nie_s, contact_V, VT)

    if init is None:
        psi = np.arcsinh(C_s / (2.0 * nie_s))
        n = np.where(C_s >= 0, 0.5 * (C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)),
                    nie_s ** 2 / np.maximum(
                        0.5 * (-C_s + np.sqrt(C_s ** 2 + 4 * nie_s ** 2)), 1e-300))
        p = nie_s ** 2 / np.maximum(n, 1e-300)
    else:
        psi = np.array(init["psi"], dtype=float, copy=True)
        n = np.array(init["n"], dtype=float, copy=True)
        p = np.array(init["p"], dtype=float, copy=True)
        if psi.shape != C_s.shape:
            raise ValueError(
                f"init arrays have shape {psi.shape}, expected {C_s.shape} "
                "(one value per node of THIS mesh)")
    psi[contact_idx], n[contact_idx], p[contact_idx] = psi0, n0, p0

    last_converged = False
    n_iter_used = 0
    residual_node_history = [] if return_diagnostics else None
    for it in range(opts.max_iter):
        F, J, Jn, Jp = _residual_jacobian_dd3d(
            psi, n, p, C_s, nie_s, vols_s, edges, eps_trans, D_n_s, D_p_s,
            R0, tau_n, tau_p, material, Ns, srh=srh, auger=auger)
        F3 = F.reshape(N, 3)
        F3[contact_idx, 0] = psi[contact_idx] - psi0
        F3[contact_idx, 1] = n[contact_idx] - n0
        F3[contact_idx, 2] = p[contact_idx] - p0

        if return_diagnostics:
            residual_node_history.append(
                np.linalg.norm(F3, axis=1).astype(float))

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
        n_iter_used = it + 1
        if opts.verbose:
            print(f"    unstructured3d-dd it {it:2d}  |dpsi|={np.abs(dpsi).max():.3e}"
                 f"  |dn/n|={rel_n:.3e}")
        if err < opts.tol_update:
            last_converged = True
            break
    else:
        warnings.warn("unstructured3d coupled bias solve did not converge.")

    _, _, Jn, Jp = _residual_jacobian_dd3d(
        psi, n, p, C_s, nie_s, vols_s, edges, eps_trans, D_n_s, D_p_s,
        R0, tau_n, tau_p, material, Ns, srh=srh, auger=auger)

    # terminal current: for each contact FACE, sum its net (electron+
    # hole) edge flux over the contact's nodes -- the box-integration
    # analogue of unstructured_dd.solve_bias's node-flux extraction,
    # generalized from "contact edges" to "contact faces". Jn/Jp here
    # already carry trans_geom's [cm] AREA/length units (unlike the 2D
    # module's dimensionless facet_length/edge_length ratio), so the
    # physical-current conversion needs only ONE factor of LD (not
    # LD**2): physical_I[A] = q*D0_REF*Ns * (D_s*trans_geom_phys*(...))
    # = (J0*LD) * Jn_code, since J0*LD = q*D0_REF*Ns already carries
    # the area-with-length-canceled dimensional bookkeeping -- verified
    # against the structured Device3D solver in
    # tests/test_unstructured_dd3d.py (see that file for the measured
    # cross-check).
    terminal_current = {}
    for name, faces in contacts.items():
        nodes_here = np.unique(faces)
        mask_i = np.isin(i_e, nodes_here)
        mask_j = np.isin(j_e, nodes_here)
        I = float((Jn[mask_i] + Jp[mask_i]).sum())
        I -= float((Jn[mask_j] + Jp[mask_j]).sum())
        J0 = Q * D0_REF * Ns / LD
        terminal_current[name] = I * J0 * LD   # [A]

    scale = dict(Ns=Ns, LD=LD, VT=VT, nie=nie, eps=eps, R0=R0,
                last_converged=last_converged)
    if return_diagnostics:
        diagnostics = dict(
            n_iter=n_iter_used,
            residual_node_history=(np.array(residual_node_history)
                                   if residual_node_history else
                                   np.zeros((0, N))))
        return psi, n, p, scale, terminal_current, diagnostics
    return psi, n, p, scale, terminal_current
