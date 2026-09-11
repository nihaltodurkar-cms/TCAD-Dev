"""M34-S6: M15's coupled impact ionization on structured 2D/3D grids.

One kernel for Device2D and Device3D (M34-S6-PLAN.md section 1).  Per
node and carrier c, with every grid axis a:

    S_a,c   = mean over the node's incident a-edges of J0 * s(J_c,e)
    E_a     = mean over the node's incident a-edges of |E_e|
    M_c     = sqrt(sum_a S_a,c^2)                  current magnitude
    E_par,c = sum_a E_a * (S_a,c / M_c)            field along the current
    G       = (1/(q R0)) * (alpha_n(E_par,n) M_n + alpha_p(E_par,p) M_p)

s(J) = sqrt(J^2 + eps^2) is M15's own smoothed |J|, with M15's eps
(1e-6 x the largest edge current).  E_par is the per-axis field
magnitude projected on the direction of the per-axis current magnitude:
a field ACROSS the current does not ionize (up to the eps floor: an axis
carrying no current still weighs in with eps/M).  Sign-free per axis, as
M15 is; equal to |E . J_hat| wherever field and current are aligned
(drift-dominated transport, the only place alpha is not zero).

In a transversely uniform device the transverse currents vanish, s gives
eps there, and M = sqrt(S_x^2 + eps^2) differs from M15's S_x by
eps^2/(2 S_x) -- round-off-close to Device1D where ionization happens.

The Jacobian is exact, including G's dependence on eps, i.e. on the
unknowns of the largest-|J| edge.  M15 neglects that term in 1D, where it
is second order in eps; here a current-free transverse axis enters E_par
with weight eps/M, which makes it first order (measured: 1e-4 of a
column, fixed at every FD step).

`eff`, if given, replaces E_par by a per-carrier effective field and its
Jacobian (the nonlocal model, M34-S6 section 2).
"""
import numpy as np

from .device import _II_J_EPS_REL, _ii_smooth_abs, _ii_smooth_sign
from .ionization import alpha_n, alpha_p, dalpha_dE, Q_E


def _ratio(S, M):
    return np.divide(S, M, out=np.zeros_like(S), where=M > 0.0)


def grid_impact(N, axes, psi, VT, LD, J0, R0, eff=None):
    """Impact-ionization generation on a structured grid.

    N    : node count; node indices are the devices' flat (row-major) ones.
    axes : one dict per grid axis, each array flat over that axis's edges:
           kL, kR     end nodes (lower / upper index along the axis)
           h          scaled edge length (x/LD units)
           Jn, Jp     scaled SG edge currents
           dJn_dpsiR, dJn_dnL, dJn_dnR, dJp_dpsiR, dJp_dpL, dJp_dpR
                      the SG edge derivatives the device already built
                      (d/dpsi_L is minus d/dpsi_R).
    psi  : flat potential (units of VT).
    eff  : None, or (E_n, D_n, E_p, D_p): per-carrier effective fields
           [V/cm] and their d/dpsi as (N, N) scipy sparse matrices.

    Returns (G, rows, cols, vals, (E_n, E_p)): G (N,) scaled generation;
    the Jacobian dG_i/du as COO triples -- rows are NODE indices i, cols
    are unknown indices 3*u + comp; and the fields alpha was evaluated at.
    """
    K = 1.0 / (Q_E * R0)
    # the edge that sets eps: (|J|, axis index, carrier, edge index)
    top = (0.0, None, None, None)
    for ai, ax in enumerate(axes):
        for car in ("n", "p"):
            J = ax["J" + car]
            if J.size:
                k = int(np.argmax(np.abs(J)))
                if abs(J[k]) > top[0]:
                    top = (float(abs(J[k])), ai, car, k)
    j_eps = _II_J_EPS_REL * max(top[0], 1e-300)
    per = []
    for ax in axes:
        kL, kR = ax["kL"], ax["kR"]
        cnt = (np.bincount(kL, minlength=N)
               + np.bincount(kR, minlength=N)).astype(float)
        inv = _ratio(np.ones(N), cnt)
        rn = _ii_smooth_abs(ax["Jn"], j_eps)
        rp = _ii_smooth_abs(ax["Jp"], j_eps)
        sn, sp = rn * J0, rp * J0
        dpsi = psi[kR] - psi[kL]
        cE = VT / (LD * ax["h"])                      # V/cm per unit psi
        Ee = np.abs(dpsi) * cE
        per.append(dict(
            ax=ax, inv=inv, rn=rn, rp=rp,
            Sn=(np.bincount(kL, sn, N) + np.bincount(kR, sn, N)) * inv,
            Sp=(np.bincount(kL, sp, N) + np.bincount(kR, sp, N)) * inv,
            Ea=(np.bincount(kL, Ee, N) + np.bincount(kR, Ee, N)) * inv,
            sgn_n=_ii_smooth_sign(ax["Jn"], j_eps),
            sgn_p=_ii_smooth_sign(ax["Jp"], j_eps),
            cEs=np.sign(dpsi) * cE))
    Mn = np.sqrt(sum(a["Sn"] * a["Sn"] for a in per))
    Mp = np.sqrt(sum(a["Sp"] * a["Sp"] for a in per))
    for a in per:
        a["un"] = _ratio(a["Sn"], Mn)                 # dM_n/dS_a,n
        a["up"] = _ratio(a["Sp"], Mp)
    if eff is None:
        En = sum(a["Ea"] * a["un"] for a in per)
        Ep = sum(a["Ea"] * a["up"] for a in per)
    else:
        En, Dn, Ep, Dp = eff
    an, ap = alpha_n(En), alpha_p(Ep)
    dan, dap = dalpha_dE(En, "n"), dalpha_dE(Ep, "p")
    G = K * (an * Mn + ap * Mp)

    rows, cols, vals = [], [], []
    dG_deps = np.zeros(N)
    for a in per:
        ax, inv = a["ax"], a["inv"]
        if eff is None:
            gSn = K * (dan * (a["Ea"] - En * a["un"]) + an * a["un"])
            gSp = K * (dap * (a["Ea"] - Ep * a["up"]) + ap * a["up"])
            gE = K * (dan * a["Sn"] + dap * a["Sp"])
        else:
            gSn = K * an * a["un"]
            gSp = K * ap * a["up"]
            gE = np.zeros(N)
        kL, kR = ax["kL"], ax["kR"]
        for i in (kL, kR):              # the edge enters both end nodes
            cJn = gSn[i] * inv[i] * J0 * a["sgn_n"]
            cJp = gSp[i] * inv[i] * J0 * a["sgn_p"]
            cEd = gE[i] * inv[i] * a["cEs"]
            rows += [i] * 6
            cols += [3 * kL, 3 * kR, 3 * kL + 1, 3 * kR + 1,
                     3 * kL + 2, 3 * kR + 2]
            vals += [-cJn * ax["dJn_dpsiR"] - cJp * ax["dJp_dpsiR"] - cEd,
                     cJn * ax["dJn_dpsiR"] + cJp * ax["dJp_dpsiR"] + cEd,
                     cJn * ax["dJn_dnL"], cJn * ax["dJn_dnR"],
                     cJp * ax["dJp_dpL"], cJp * ax["dJp_dpR"]]
        # d(J0 s)/d eps = J0 eps / s, per edge, into both end nodes
        for g, r in ((gSn, a["rn"]), (gSp, a["rp"])):
            ds = J0 * j_eps / r
            dG_deps += g * (np.bincount(kL, ds, N)
                            + np.bincount(kR, ds, N)) * inv
    if top[1] is not None:
        ax = axes[top[1]]
        car, k = top[2], top[3]
        comp = 1 if car == "n" else 2
        dcL, dcR = ("dJn_dnL", "dJn_dnR") if car == "n" else ("dJp_dpL",
                                                               "dJp_dpR")
        # eps = rel * |J_k|: d eps/du = rel * sign(J_k) * dJ_k/du
        c = _II_J_EPS_REL * np.sign(ax["J" + car][k])
        dJ = {3 * ax["kL"][k]: -ax["dJ" + car + "_dpsiR"][k],
              3 * ax["kR"][k]: ax["dJ" + car + "_dpsiR"][k],
              3 * ax["kL"][k] + comp: ax[dcL][k],
              3 * ax["kR"][k] + comp: ax[dcR][k]}
        nz = np.nonzero(dG_deps)[0]
        for col, d in dJ.items():
            rows.append(nz)
            cols.append(np.full(nz.size, col))
            vals.append(dG_deps[nz] * c * d)
    if eff is not None:
        for Dc, dac, Mc in ((Dn, dan, Mn), (Dp, dap, Mp)):
            Dc = Dc.tocoo()
            rows.append(Dc.row)
            cols.append(3 * Dc.col)
            vals.append(K * dac[Dc.row] * Mc[Dc.row] * Dc.data)
    return (G, np.concatenate(rows), np.concatenate(cols),
            np.concatenate(vals), (En, Ep))
