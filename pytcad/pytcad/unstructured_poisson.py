"""M21 phase 3b -- Poisson-ONLY equilibrium solve on an unstructured
triangle mesh. Carriers slaved to psi (Boltzmann: n=nie*exp(psi),
p=nie*exp(-psi)), exactly Device2D._residual_jacobian_poisson's own
equilibrium physics and scaling convention, generalized from the
structured x/y edge-pair assembly to an arbitrary edge list.

Scope (M21-PHASE3-MESHING-PLAN.md section 1, step 5 of the
implementation order): Poisson only. No Scharfetter-Gummel current, no
continuity equations, no bias, no Device2D integration -- those are
the harder, still-deferred remainder (steps 6-11, gates G4-G5).

Homojunction only this slice: a single material's eps_r is assumed
uniform over the whole mesh (no per-region permittivity harmonic-mean
edge factor the way device2d.py's et_x/et_y carry for heterojunctions)
-- an honest simplification, not silently generalized past what is
actually tested.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

# M31 P4b: symmetric Dirichlet elimination (row AND column), so the
# assembled Jacobian is transposable -- see pytcad/dirichlet.py.
from .dirichlet import eliminate_csr, stamp_dirichlet_rows
from .linsolve import solve_linear, LinearSolveError, select_auto

from .constants import Q, EPS0
from .device import NewtonOptions, thermal_voltage
from .device2d import _ohmic_values
from .materials import SILICON


def evaluate_doping_at_nodes(nodes, triangles, region_of_triangle,
                             doping_by_region):
    """Per-node net doping [cm^-3], barycentric-area-weighted over each
    node's touching triangles. A node sitting exactly on a region
    boundary (e.g. this module's diode fixture's shared junction nodes)
    gets a physically sensible AVERAGE of the adjacent regions' doping,
    not an arbitrary "pick one side" choice -- the doping profile's
    true discontinuity is represented only up to this one row of
    shared-node smoothing, an honest simplification of the ideal
    (node-duplicated) step junction.
    """
    nodes_xy = np.asarray(nodes, dtype=float)[:, :2]
    tri = np.asarray(triangles, dtype=int)
    N = nodes_xy.shape[0]
    weighted = np.zeros(N)
    weight = np.zeros(N)
    for t_idx, (a, b, c) in enumerate(tri):
        pts = nodes_xy[[a, b, c]]
        area = 0.5 * abs((pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
                         - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1]))
        dop = doping_by_region[region_of_triangle[t_idx]]
        for v in (a, b, c):
            weighted[v] += dop * area / 3.0
            weight[v] += area / 3.0
    return weighted / weight


def _residual_jacobian(psi, C_s, nie_s, node_areas, interior_edges, trans):
    """Scaled Poisson-equilibrium residual/Jacobian (Boltzmann carriers
    slaved to psi), matching Device2D._residual_jacobian_poisson's
    physics/scaling exactly, assembled per-edge instead of per x/y
    edge-pair array. `trans` here already has eps_r folded in (this
    module's caller does that once, since it's uniform -- see
    solve_poisson_equilibrium)."""
    N = psi.shape[0]
    n = nie_s * np.exp(np.clip(psi, -700, 700))
    p = nie_s * np.exp(np.clip(-psi, -700, 700))
    dnp = n + p

    F = -node_areas * (n - p - C_s)
    i_idx = interior_edges[:, 0]
    j_idx = interior_edges[:, 1]
    flux = trans * (psi[j_idx] - psi[i_idx])
    np.add.at(F, i_idx, flux)
    np.add.at(F, j_idx, -flux)

    rows = np.concatenate([i_idx, i_idx, j_idx, j_idx, np.arange(N)])
    cols = np.concatenate([i_idx, j_idx, j_idx, i_idx, np.arange(N)])
    vals = np.concatenate([-trans, trans, -trans, trans, -node_areas * dnp])
    J = sp.csr_matrix((vals, (rows, cols)), shape=(N, N))
    return F, J


def solve_poisson_equilibrium(nodes, triangles, edge_list, node_areas,
                              interior_edges, trans_geom, C_phys,
                              contacts, material=SILICON, T=300.0,
                              opts=None):
    """Newton-solve the unstructured-mesh Poisson equilibrium.

    C_phys: (N,) physical net doping [cm^-3] per node (e.g. from
        evaluate_doping_at_nodes).
    contacts: {name: (K, 2) boundary-edge node-index array} from
        region_resolver.resolve_contacts() -- every node referenced is
        pinned Dirichlet at V=0 (equilibrium is always the zero-bias
        solve, same convention Device1D/Device2D's own solve_equilibrium
        already uses).
    trans_geom: the dimensionless (eps-free) TPFA factors from
        unstructured_assembly.build_edge_flux_geometry -- this function
        multiplies in the physical eps once, since a homojunction's
        eps_r is uniform.

    Returns psi [scaled, dimensionless] (V_phys = psi * VT), plus the
    scaling constants (Ns, LD, VT, nie) a caller needs to convert other
    quantities.
    """
    opts = opts or NewtonOptions()
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    nie = material.ni(T)
    Ns = max(float(np.abs(C_phys).max()), nie)
    LD = np.sqrt(eps * VT / (Q * Ns))

    C_s = C_phys / Ns
    nie_s = nie / Ns
    areas_s = node_areas / LD ** 2       # dual-cell areas -> scaled
    trans_s = trans_geom * eps           # physical eps folded in once

    contact_node = {}   # node index -> psi0 (scaled)
    for edges in contacts.values():
        for i, j in edges:
            for node in (int(i), int(j)):
                if node not in contact_node:
                    psi0, _, _ = _ohmic_values(C_s[node], nie_s, 0.0, VT)
                    contact_node[node] = float(psi0)
    contact_idx = np.array(sorted(contact_node), dtype=int)
    contact_psi0 = np.array([contact_node[k] for k in contact_idx])

    psi = np.arcsinh(C_s / (2.0 * nie_s))
    psi[contact_idx] = contact_psi0

    N = psi.shape[0]
    linsolve_fallbacks = 0
    # M31 P5-1 Phase D: opts.linsolve="auto" resolves ONCE, here. This
    # is the SCALAR 2D unstructured equilibrium path -- Phase A never
    # measured it (only unstructured_dd.solve_bias's coupled path, B8),
    # so this always resolves to "direct" today (Gate D-3's refusal
    # path). See linsolve.select_auto's own docstring for the evidence.
    resolved_linsolve, auto_reason = (
        select_auto(dim=2, unstructured=True, coupled=False, dof=N)
        if opts.linsolve == "auto" else (opts.linsolve, None))
    if opts.verbose and auto_reason:
        print(f"    unstructured-eq  auto -> {resolved_linsolve} "
              f"({auto_reason})")
    for it in range(opts.max_iter):
        F, J = _residual_jacobian(psi, C_s, nie_s, areas_s,
                                  interior_edges, trans_s)
        F[contact_idx] = psi[contact_idx] - contact_psi0
        # Symmetric elimination: drop the constrained COLUMNS too,
        # substituting their known contribution into the rhs. Same
        # system, same solution -- but J^T now imposes the same
        # constraint, which row-only elimination does not. See
        # pytcad/dirichlet.py.  M31 P5-0 replaced a J.tolil() round trip
        # with stamp_dirichlet_rows (byte-identical) and routed the
        # update through linsolve so opts.linsolve reaches this core.
        J, rhs = eliminate_csr(stamp_dirichlet_rows(J, contact_idx),
                               -F, contact_idx)

        # M31 P5-1 Phase C: same try/except degrade the structured cores
        # already use (device.py/device2d.py/device3d.py's own
        # solve_equilibrium) -- a requested iterative method is tried
        # first, but a LinearSolveError falls back to a direct solve for
        # THAT iteration only rather than raising out of the whole
        # solve, UNLESS the failing method was already "direct" (then
        # there is nothing to fall back to, and re-raising is correct).
        # opts.linsolve="direct" (the default) never enters the except
        # branch, so this is bit-identical unless the caller opts in.
        try:
            d, _ = solve_linear(J.tocsc(), rhs, method=resolved_linsolve,
                                rtol=opts.linsolve_rtol)
        except LinearSolveError:
            if resolved_linsolve == "direct":
                raise
            if opts.verbose:
                print(f"    unstructured-eq it {it:2d}  {resolved_linsolve} "
                      "did not converge -- falling back to direct for "
                      "this iteration")
            linsolve_fallbacks += 1
            d, _ = solve_linear(J.tocsc(), rhs, method="direct")
        d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
        psi = psi + d
        if opts.verbose:
            print(f"    unstructured-eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
        if np.abs(d).max() < opts.tol_update:
            break
    else:
        import warnings
        warnings.warn("unstructured Poisson equilibrium solve did not converge.")

    return psi, dict(Ns=Ns, LD=LD, VT=VT, nie=nie, eps=eps,
                     linsolve_fallbacks=linsolve_fallbacks,
                     auto_method=(resolved_linsolve
                                 if opts.linsolve == "auto" else None),
                     auto_reason=auto_reason)
