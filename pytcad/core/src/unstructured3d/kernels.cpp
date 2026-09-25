// Transcription of pytcad/unstructured_dd3d.py's own COO block
// functions (_poisson_flux_geometry_coo, _poisson_equilibrium_diag_coo,
// _poisson_charge_coupling_coo, _srh_auger_coo, _sg_carrier_coo) plus
// the two orchestrated assembly functions -- same statement order, same
// association, per core/src/thermal/grid.cpp's own precedent (see
// kernels.hpp's header comment for why that matters here).
#include "tcad/unstructured3d/kernels.hpp"

#include <algorithm>
#include <cstddef>

namespace tcad::unstructured3d {

Coo poisson_flux_geometry(const std::vector<std::int64_t>& edge_i,
                          const std::vector<std::int64_t>& edge_j,
                          const std::vector<double>& trans, int comp3) {
    // Python's `np.concatenate([ii,ii,jj,jj])` (rows) / `[ii,jj,jj,ii]`
    // (cols) / `[-trans,trans,-trans,trans]` (vals) is FOUR BLOCKS OF E
    // EACH -- term1 for every edge, then term2 for every edge, etc. --
    // NOT one 4-entry group per edge. This grouping is load-bearing for
    // duplicate-(row,col) accumulation order (see file header); must be
    // reproduced exactly, not merely "the same 4 mathematical terms".
    const std::size_t E = edge_i.size();
    Coo out;
    out.rows.resize(4 * E);
    out.cols.resize(4 * E);
    out.vals.resize(4 * E);
    const std::int64_t scale = (comp3 >= 0) ? 3 : 1;
    const std::int64_t off = (comp3 >= 0) ? static_cast<std::int64_t>(comp3) : 0;
    for (std::size_t e = 0; e < E; ++e) {
        const std::int64_t ii = scale * edge_i[e] + off;
        const std::int64_t jj = scale * edge_j[e] + off;
        const double t = trans[e];
        out.rows[0 * E + e] = ii; out.cols[0 * E + e] = ii; out.vals[0 * E + e] = -t;
        out.rows[1 * E + e] = ii; out.cols[1 * E + e] = jj; out.vals[1 * E + e] = t;
        out.rows[2 * E + e] = jj; out.cols[2 * E + e] = jj; out.vals[2 * E + e] = -t;
        out.rows[3 * E + e] = jj; out.cols[3 * E + e] = ii; out.vals[3 * E + e] = t;
    }
    return out;
}

Coo poisson_equilibrium_diag(const std::vector<double>& node_vols_s,
                             const std::vector<double>& n,
                             const std::vector<double>& p) {
    const std::size_t N = node_vols_s.size();
    Coo out;
    out.rows.resize(N);
    out.cols.resize(N);
    out.vals.resize(N);
    for (std::size_t k = 0; k < N; ++k) {
        const double dnp = n[k] + p[k];
        out.rows[k] = static_cast<std::int64_t>(k);
        out.cols[k] = static_cast<std::int64_t>(k);
        out.vals[k] = -node_vols_s[k] * dnp;
    }
    return out;
}

Coo poisson_charge_coupling(const std::vector<double>& node_vols_s) {
    // Python: rows=concat([3k,3k]), cols=concat([3k+1,3k+2]),
    // vals=concat([-vols,vols]) -- TWO BLOCKS OF N (E then F), not
    // interleaved per node.
    const std::size_t N = node_vols_s.size();
    Coo out;
    out.rows.resize(2 * N);
    out.cols.resize(2 * N);
    out.vals.resize(2 * N);
    for (std::size_t k = 0; k < N; ++k) {
        const std::int64_t k3 = 3 * static_cast<std::int64_t>(k);
        out.rows[0 * N + k] = k3; out.cols[0 * N + k] = k3 + 1; out.vals[0 * N + k] = -node_vols_s[k];
        out.rows[1 * N + k] = k3; out.cols[1 * N + k] = k3 + 2; out.vals[1 * N + k] = node_vols_s[k];
    }
    return out;
}

SrhResult srh_auger(const std::vector<double>& n, const std::vector<double>& p,
                    const std::vector<double>& nie_phys, const std::vector<double>& tau_n,
                    const std::vector<double>& tau_p,
                    const std::vector<double>& node_vols_s, double Ns,
                    double R0, bool srh, bool auger, double auger_cn,
                    double auger_cp) {
    const std::size_t N = n.size();
    SrhResult out;
    out.F1_baseline.assign(N, 0.0);
    out.F2_baseline.assign(N, 0.0);
    std::vector<double> dRs_dn(N, 0.0), dRs_dp(N, 0.0);

    if (srh) {
        for (std::size_t k = 0; k < N; ++k) {
            // Per node (M47 Slice 3). For a homojunction every entry is
            // the same value, so nie*nie is the same product the former
            // scalar hoisted out of this loop -- bit-identical.
            const double nie_k = nie_phys[k];
            const double ni2 = nie_k * nie_k;
            const double n_phys = n[k] * Ns;
            const double p_phys = p[k] * Ns;
            const double excess = n_phys * p_phys - ni2;
            const double den = tau_p[k] * (n_phys + nie_k) + tau_n[k] * (p_phys + nie_k);
            double R = excess / den;
            double dRdn = (p_phys * den - excess * tau_p[k]) / (den * den);
            double dRdp = (n_phys * den - excess * tau_n[k]) / (den * den);
            if (auger) {
                const double C = auger_cn * n_phys + auger_cp * p_phys;
                R = R + C * excess;
                dRdn = dRdn + auger_cn * excess + C * p_phys;
                dRdp = dRdp + auger_cp * excess + C * n_phys;
            }
            const double Rs = R / R0;
            dRs_dn[k] = dRdn * Ns / R0;
            dRs_dp[k] = dRdp * Ns / R0;
            out.F1_baseline[k] = -Rs * node_vols_s[k];
            out.F2_baseline[k] = Rs * node_vols_s[k];
        }
    }
    // Diagonal COO block -- present (zero-valued) even when srh=False,
    // matching the oracle's own unconditional add() calls (dRs_dn/dRs_dp
    // are simply zero arrays there when R=0). Python: rows=concat([3k+1,
    // 3k+1,3k+2,3k+2]) -- FOUR BLOCKS OF N (A,B,C,D), not interleaved.
    Coo diag;
    diag.rows.resize(4 * N);
    diag.cols.resize(4 * N);
    diag.vals.resize(4 * N);
    for (std::size_t k = 0; k < N; ++k) {
        const std::int64_t k3 = 3 * static_cast<std::int64_t>(k);
        diag.rows[0 * N + k] = k3 + 1; diag.cols[0 * N + k] = k3 + 1; diag.vals[0 * N + k] = -dRs_dn[k] * node_vols_s[k];
        diag.rows[1 * N + k] = k3 + 1; diag.cols[1 * N + k] = k3 + 2; diag.vals[1 * N + k] = -dRs_dp[k] * node_vols_s[k];
        diag.rows[2 * N + k] = k3 + 2; diag.cols[2 * N + k] = k3 + 1; diag.vals[2 * N + k] = dRs_dn[k] * node_vols_s[k];
        diag.rows[3 * N + k] = k3 + 2; diag.cols[3 * N + k] = k3 + 2; diag.vals[3 * N + k] = dRs_dp[k] * node_vols_s[k];
    }
    out.diag = std::move(diag);
    return out;
}

Coo sg_carrier_jacobian(const std::vector<std::int64_t>& edge_i,
                        const std::vector<std::int64_t>& edge_j, int comp,
                        const std::vector<double>& dJ_dpsi_j,
                        const std::vector<double>& dJ_dself_i,
                        const std::vector<double>& dJ_dself_j) {
    // Python: rows=concat([ci,ci,ci,ci,cj,cj,cj,cj]) -- EIGHT BLOCKS OF
    // E (K,L,M,N,O,P,Q,R), not interleaved per edge.
    const std::size_t E = edge_i.size();
    Coo out;
    out.rows.resize(8 * E);
    out.cols.resize(8 * E);
    out.vals.resize(8 * E);
    for (std::size_t e = 0; e < E; ++e) {
        const std::int64_t i0 = 3 * edge_i[e];
        const std::int64_t j0 = 3 * edge_j[e];
        const std::int64_t ci = i0 + comp;
        const std::int64_t cj = j0 + comp;
        const double dpj = dJ_dpsi_j[e], dsi = dJ_dself_i[e], dsj = dJ_dself_j[e];
        out.rows[0 * E + e] = ci; out.cols[0 * E + e] = i0; out.vals[0 * E + e] = -dpj;
        out.rows[1 * E + e] = ci; out.cols[1 * E + e] = j0; out.vals[1 * E + e] = dpj;
        out.rows[2 * E + e] = ci; out.cols[2 * E + e] = ci; out.vals[2 * E + e] = dsi;
        out.rows[3 * E + e] = ci; out.cols[3 * E + e] = cj; out.vals[3 * E + e] = dsj;
        out.rows[4 * E + e] = cj; out.cols[4 * E + e] = i0; out.vals[4 * E + e] = dpj;
        out.rows[5 * E + e] = cj; out.cols[5 * E + e] = j0; out.vals[5 * E + e] = -dpj;
        out.rows[6 * E + e] = cj; out.cols[6 * E + e] = ci; out.vals[6 * E + e] = -dsi;
        out.rows[7 * E + e] = cj; out.cols[7 * E + e] = cj; out.vals[7 * E + e] = -dsj;
    }
    return out;
}

SgResult sg_electron(const std::vector<std::int64_t>& edge_i,
                     const std::vector<std::int64_t>& edge_j,
                     const std::vector<double>& trans_bare,
                     const std::vector<double>& D_n_s,
                     const std::vector<double>& n,
                     const std::vector<double>& Bp, const std::vector<double>& Bm,
                     const std::vector<double>& dBp, const std::vector<double>& dBm) {
    const std::size_t E = edge_i.size();
    SgResult out;
    out.J_edge.resize(E);
    std::vector<double> dpsi_j(E), dself_i(E), dself_j(E);
    for (std::size_t e = 0; e < E; ++e) {
        const double n_i = n[edge_i[e]], n_j = n[edge_j[e]];
        const double D = D_n_s[e], t = trans_bare[e];
        out.J_edge[e] = D * t * (n_j * Bp[e] - n_i * Bm[e]);
        dpsi_j[e] = D * t * (n_j * dBp[e] + n_i * dBm[e]);
        dself_i[e] = -D * t * Bm[e];   // dJn_dn_i
        dself_j[e] = D * t * Bp[e];    // dJn_dn_j
    }
    out.jac = sg_carrier_jacobian(edge_i, edge_j, 1, dpsi_j, dself_i, dself_j);
    return out;
}

SgResult sg_hole(const std::vector<std::int64_t>& edge_i,
                 const std::vector<std::int64_t>& edge_j,
                 const std::vector<double>& trans_bare,
                 const std::vector<double>& D_p_s,
                 const std::vector<double>& p,
                 const std::vector<double>& Bp, const std::vector<double>& Bm,
                 const std::vector<double>& dBp, const std::vector<double>& dBm) {
    const std::size_t E = edge_i.size();
    SgResult out;
    out.J_edge.resize(E);
    std::vector<double> dpsi_j(E), dself_i(E), dself_j(E);
    for (std::size_t e = 0; e < E; ++e) {
        const double p_i = p[edge_i[e]], p_j = p[edge_j[e]];
        const double D = D_p_s[e], t = trans_bare[e];
        out.J_edge[e] = -D * t * (p_j * Bm[e] - p_i * Bp[e]);
        dpsi_j[e] = D * t * (p_j * dBm[e] + p_i * dBp[e]);
        dself_i[e] = D * t * Bp[e];     // dJp_dp_i
        dself_j[e] = -D * t * Bm[e];    // dJp_dp_j
    }
    out.jac = sg_carrier_jacobian(edge_i, edge_j, 2, dpsi_j, dself_i, dself_j);
    return out;
}

namespace {
void extend(Coo& dst, const Coo& src) {
    dst.rows.insert(dst.rows.end(), src.rows.begin(), src.rows.end());
    dst.cols.insert(dst.cols.end(), src.cols.begin(), src.cols.end());
    dst.vals.insert(dst.vals.end(), src.vals.begin(), src.vals.end());
}
/// Reserve exact final capacity before any insert() -- without this,
/// std::vector's geometric growth means EACH extend() call below can
/// trigger a full reallocation+copy of everything accumulated so far,
/// turning what should be one memcpy-per-block into repeated partial
/// recopies across the whole concatenation chain. Suspected (per
/// M47-3D-ENGINE-PLAN.md's "Investigating the null speedup result")
/// as a real cause of the null benchmark result -- np.concatenate does
/// not have this problem (it computes the total size and allocates
/// once). Being tested here, not assumed fixed until re-measured.
void reserve_total(Coo& dst, std::size_t total) {
    dst.rows.reserve(total);
    dst.cols.reserve(total);
    dst.vals.reserve(total);
}
}  // namespace

Result residual_jacobian_equilibrium(
    const std::vector<double>& n, const std::vector<double>& p,
    const std::vector<double>& C_s, const std::vector<double>& node_vols_s,
    const std::vector<std::int64_t>& edge_i,
    const std::vector<std::int64_t>& edge_j,
    const std::vector<double>& trans, const std::vector<double>& flux) {
    const std::size_t N = C_s.size();
    Result out;
    out.F.resize(N);
    for (std::size_t k = 0; k < N; ++k)
        out.F[k] = -node_vols_s[k] * (n[k] - p[k] - C_s[k]);
    // TWO SEPARATE passes, i then j -- matches np.add.at(F,i_idx,flux);
    // np.add.at(F,j_idx,-flux) being two distinct calls, not one
    // interleaved loop; a node touched as an i-endpoint by one edge AND
    // a j-endpoint by another accumulates in a different relative order
    // otherwise (a real bit-identity risk, not a style choice).
    for (std::size_t e = 0; e < edge_i.size(); ++e)
        out.F[static_cast<std::size_t>(edge_i[e])] += flux[e];
    for (std::size_t e = 0; e < edge_j.size(); ++e)
        out.F[static_cast<std::size_t>(edge_j[e])] -= flux[e];
    // Equilibrium order: flux geometry FIRST, diagonal charge term LAST.
    Coo geom = poisson_flux_geometry(edge_i, edge_j, trans, -1);
    Coo diag = poisson_equilibrium_diag(node_vols_s, n, p);
    out.J = std::move(geom);
    reserve_total(out.J, out.J.rows.size() + diag.rows.size());
    extend(out.J, diag);
    return out;
}

CoupledResult residual_jacobian_coupled(
    const std::vector<double>& n, const std::vector<double>& p,
    const std::vector<double>& C_s, const std::vector<double>& node_vols_s,
    const std::vector<std::int64_t>& edge_i,
    const std::vector<std::int64_t>& edge_j,
    const std::vector<double>& eps_trans, const std::vector<double>& flux,
    const std::vector<double>& trans_bare,
    const std::vector<double>& D_n_s, const std::vector<double>& D_p_s,
    const std::vector<double>& Bp, const std::vector<double>& Bm,
    const std::vector<double>& dBp, const std::vector<double>& dBm,
    const std::vector<double>& nie_phys, const std::vector<double>& tau_n,
    const std::vector<double>& tau_p, double Ns, double R0, bool srh,
    bool auger, double auger_cn, double auger_cp,
    const std::vector<double>& Bp_h, const std::vector<double>& Bm_h,
    const std::vector<double>& dBp_h, const std::vector<double>& dBm_h) {
    const std::size_t N = C_s.size();

    // Block order: SRH/Auger FIRST, Poisson charge-coupling SECOND,
    // Poisson flux geometry THIRD, electron SG FOURTH, hole SG LAST --
    // the exact traced source order (kernels.hpp's file header).
    SrhResult srh_r = srh_auger(n, p, nie_phys, tau_n, tau_p, node_vols_s,
                                Ns, R0, srh, auger, auger_cn, auger_cp);

    std::vector<double> F0(N);
    for (std::size_t k = 0; k < N; ++k)
        F0[k] = -node_vols_s[k] * (n[k] - p[k] - C_s[k]);
    Coo chg = poisson_charge_coupling(node_vols_s);

    // Two separate i-then-j passes throughout -- see the equilibrium
    // function's own comment for why this is required, not stylistic.
    for (std::size_t e = 0; e < edge_i.size(); ++e)
        F0[static_cast<std::size_t>(edge_i[e])] += flux[e];
    for (std::size_t e = 0; e < edge_j.size(); ++e)
        F0[static_cast<std::size_t>(edge_j[e])] -= flux[e];
    Coo geom = poisson_flux_geometry(edge_i, edge_j, eps_trans, 0);

    SgResult sg_e = sg_electron(edge_i, edge_j, trans_bare, D_n_s, n, Bp, Bm, dBp, dBm);
    std::vector<double> F1 = srh_r.F1_baseline;
    for (std::size_t e = 0; e < edge_i.size(); ++e)
        F1[static_cast<std::size_t>(edge_i[e])] += sg_e.J_edge[e];
    for (std::size_t e = 0; e < edge_j.size(); ++e)
        F1[static_cast<std::size_t>(edge_j[e])] -= sg_e.J_edge[e];

    SgResult sg_h = sg_hole(edge_i, edge_j, trans_bare, D_p_s, p, Bp_h, Bm_h, dBp_h, dBm_h);
    std::vector<double> F2 = srh_r.F2_baseline;
    for (std::size_t e = 0; e < edge_i.size(); ++e)
        F2[static_cast<std::size_t>(edge_i[e])] += sg_h.J_edge[e];
    for (std::size_t e = 0; e < edge_j.size(); ++e)
        F2[static_cast<std::size_t>(edge_j[e])] -= sg_h.J_edge[e];

    CoupledResult out;
    out.base.F.resize(3 * N);
    for (std::size_t k = 0; k < N; ++k) {
        out.base.F[3 * k + 0] = F0[k];
        out.base.F[3 * k + 1] = F1[k];
        out.base.F[3 * k + 2] = F2[k];
    }
    out.base.J = std::move(srh_r.diag);
    reserve_total(out.base.J, out.base.J.rows.size() + chg.rows.size() +
                                  geom.rows.size() + sg_e.jac.rows.size() +
                                  sg_h.jac.rows.size());
    extend(out.base.J, chg);
    extend(out.base.J, geom);
    extend(out.base.J, sg_e.jac);
    extend(out.base.J, sg_h.jac);
    out.Jn_edge = std::move(sg_e.J_edge);
    out.Jp_edge = std::move(sg_h.J_edge);
    return out;
}

}  // namespace tcad::unstructured3d
