// Transcription of device3d.py's own _poisson_flux_row_coo /
// _electron_continuity_coo / _hole_continuity_coo / _base_diagonal_coo
// -- see kernels.hpp's file header for scope and the reserve-from-
// the-start design note.
#include "tcad/device3d/kernels.hpp"

namespace tcad::device3d {

namespace {

/// One axis's 4-entry-per-edge scatter stamp, written DIRECTLY into
/// `out` at `offset` (4*E slots, term-blocks-of-E layout: term1 for
/// every edge, then term2, etc. -- matches
/// device3d.py's own `_scatter3_coo`'s `np.concatenate([...])` term
/// order exactly). No intermediate allocation.
void write_scatter4(Coo& out, std::size_t offset,
                    const std::vector<std::int64_t>& kL,
                    const std::vector<std::int64_t>& kR,
                    const std::vector<double>& weight, int row_comp,
                    int comp_L, const std::vector<double>& dL, int comp_R,
                    const std::vector<double>& dR) {
    const std::size_t E = kL.size();
    for (std::size_t e = 0; e < E; ++e) {
        const double w = weight[e], vL = dL[e], vR = dR[e];
        const std::int64_t rL = 3 * kL[e] + row_comp, rR = 3 * kR[e] + row_comp;
        const std::int64_t cL = 3 * kL[e] + comp_L, cR = 3 * kR[e] + comp_R;
        out.rows[offset + 0 * E + e] = rL; out.cols[offset + 0 * E + e] = cL;
        out.vals[offset + 0 * E + e] = w * vL;
        out.rows[offset + 1 * E + e] = rL; out.cols[offset + 1 * E + e] = cR;
        out.vals[offset + 1 * E + e] = w * vR;
        out.rows[offset + 2 * E + e] = rR; out.cols[offset + 2 * E + e] = cL;
        out.vals[offset + 2 * E + e] = -w * vL;
        out.rows[offset + 3 * E + e] = rR; out.cols[offset + 3 * E + e] = cR;
        out.vals[offset + 3 * E + e] = -w * vR;
    }
}

}  // namespace

Coo poisson_flux_row(
    const std::vector<std::int64_t>& kLx, const std::vector<std::int64_t>& kRx,
    const std::vector<double>& wx_h,
    const std::vector<std::int64_t>& kSy, const std::vector<std::int64_t>& kNy,
    const std::vector<double>& wy_h,
    const std::vector<std::int64_t>& kDz, const std::vector<std::int64_t>& kUz,
    const std::vector<double>& wz_h) {
    const std::size_t Ex = kLx.size(), Ey = kSy.size(), Ez = kDz.size();
    Coo out;
    const std::size_t total = 4 * (Ex + Ey + Ez);
    out.rows.resize(total); out.cols.resize(total); out.vals.resize(total);

    std::vector<double> onesx(Ex, 1.0), onesy(Ey, 1.0), onesz(Ez, 1.0);
    std::vector<double> monesx(Ex, -1.0), monesy(Ey, -1.0), monesz(Ez, -1.0);

    std::size_t off = 0;
    write_scatter4(out, off, kLx, kRx, wx_h, 0, 0, monesx, 0, onesx);
    off += 4 * Ex;
    write_scatter4(out, off, kSy, kNy, wy_h, 0, 0, monesy, 0, onesy);
    off += 4 * Ey;
    write_scatter4(out, off, kDz, kUz, wz_h, 0, 0, monesz, 0, onesz);
    return out;
}

Coo electron_continuity(
    const std::vector<std::int64_t>& kLx, const std::vector<std::int64_t>& kRx,
    const std::vector<double>& wx_area, const std::vector<double>& dJn_dpsiR_x,
    const std::vector<double>& dJn_dn_L_x, const std::vector<double>& dJn_dn_R_x,
    const std::vector<std::int64_t>& kSy, const std::vector<std::int64_t>& kNy,
    const std::vector<double>& wy_area, const std::vector<double>& dJn_dpsiR_y,
    const std::vector<double>& dJn_dn_L_y, const std::vector<double>& dJn_dn_R_y,
    const std::vector<std::int64_t>& kDz, const std::vector<std::int64_t>& kUz,
    const std::vector<double>& wz_area, const std::vector<double>& dJn_dpsiR_z,
    const std::vector<double>& dJn_dn_L_z, const std::vector<double>& dJn_dn_R_z) {
    const std::size_t Ex = kLx.size(), Ey = kSy.size(), Ez = kDz.size();
    Coo out;
    const std::size_t total = 8 * (Ex + Ey + Ez);
    out.rows.resize(total); out.cols.resize(total); out.vals.resize(total);

    std::vector<double> ndpx(Ex), ndpy(Ey), ndpz(Ez);
    for (std::size_t e = 0; e < Ex; ++e) ndpx[e] = -dJn_dpsiR_x[e];
    for (std::size_t e = 0; e < Ey; ++e) ndpy[e] = -dJn_dpsiR_y[e];
    for (std::size_t e = 0; e < Ez; ++e) ndpz[e] = -dJn_dpsiR_z[e];

    std::size_t off = 0;
    write_scatter4(out, off, kLx, kRx, wx_area, 1, 0, ndpx, 0, dJn_dpsiR_x);
    off += 4 * Ex;
    write_scatter4(out, off, kLx, kRx, wx_area, 1, 1, dJn_dn_L_x, 1, dJn_dn_R_x);
    off += 4 * Ex;
    write_scatter4(out, off, kSy, kNy, wy_area, 1, 0, ndpy, 0, dJn_dpsiR_y);
    off += 4 * Ey;
    write_scatter4(out, off, kSy, kNy, wy_area, 1, 1, dJn_dn_L_y, 1, dJn_dn_R_y);
    off += 4 * Ey;
    write_scatter4(out, off, kDz, kUz, wz_area, 1, 0, ndpz, 0, dJn_dpsiR_z);
    off += 4 * Ez;
    write_scatter4(out, off, kDz, kUz, wz_area, 1, 1, dJn_dn_L_z, 1, dJn_dn_R_z);
    return out;
}

Coo hole_continuity(
    const std::vector<std::int64_t>& kLx, const std::vector<std::int64_t>& kRx,
    const std::vector<double>& wx_area, const std::vector<double>& dJp_dpsiR_x,
    const std::vector<double>& dJp_dp_L_x, const std::vector<double>& dJp_dp_R_x,
    const std::vector<std::int64_t>& kSy, const std::vector<std::int64_t>& kNy,
    const std::vector<double>& wy_area, const std::vector<double>& dJp_dpsiR_y,
    const std::vector<double>& dJp_dp_L_y, const std::vector<double>& dJp_dp_R_y,
    const std::vector<std::int64_t>& kDz, const std::vector<std::int64_t>& kUz,
    const std::vector<double>& wz_area, const std::vector<double>& dJp_dpsiR_z,
    const std::vector<double>& dJp_dp_L_z, const std::vector<double>& dJp_dp_R_z) {
    const std::size_t Ex = kLx.size(), Ey = kSy.size(), Ez = kDz.size();
    Coo out;
    const std::size_t total = 8 * (Ex + Ey + Ez);
    out.rows.resize(total); out.cols.resize(total); out.vals.resize(total);

    std::vector<double> ndpx(Ex), ndpy(Ey), ndpz(Ez);
    for (std::size_t e = 0; e < Ex; ++e) ndpx[e] = -dJp_dpsiR_x[e];
    for (std::size_t e = 0; e < Ey; ++e) ndpy[e] = -dJp_dpsiR_y[e];
    for (std::size_t e = 0; e < Ez; ++e) ndpz[e] = -dJp_dpsiR_z[e];

    std::size_t off = 0;
    write_scatter4(out, off, kLx, kRx, wx_area, 2, 0, ndpx, 0, dJp_dpsiR_x);
    off += 4 * Ex;
    write_scatter4(out, off, kLx, kRx, wx_area, 2, 2, dJp_dp_L_x, 2, dJp_dp_R_x);
    off += 4 * Ex;
    write_scatter4(out, off, kSy, kNy, wy_area, 2, 0, ndpy, 0, dJp_dpsiR_y);
    off += 4 * Ey;
    write_scatter4(out, off, kSy, kNy, wy_area, 2, 2, dJp_dp_L_y, 2, dJp_dp_R_y);
    off += 4 * Ey;
    write_scatter4(out, off, kDz, kUz, wz_area, 2, 0, ndpz, 0, dJp_dpsiR_z);
    off += 4 * Ez;
    write_scatter4(out, off, kDz, kUz, wz_area, 2, 2, dJp_dp_L_z, 2, dJp_dp_R_z);
    return out;
}

Coo base_diagonal(std::int64_t N, const std::vector<double>& dV,
                  bool has_incomplete_ion, const std::vector<double>& dcden,
                  const std::vector<double>& dcdp,
                  const std::vector<double>& dRs_dn,
                  const std::vector<double>& dRs_dp) {
    const std::size_t Nu = static_cast<std::size_t>(N);
    Coo out;
    const std::size_t total = 6 * Nu;
    out.rows.resize(total); out.cols.resize(total); out.vals.resize(total);

    for (std::size_t k = 0; k < Nu; ++k) {
        const std::int64_t k3 = 3 * static_cast<std::int64_t>(k);
        // term1, term2: Poisson charge (dcden-None vs incomplete_ion form)
        out.rows[0 * Nu + k] = k3; out.cols[0 * Nu + k] = k3 + 1;
        out.rows[1 * Nu + k] = k3; out.cols[1 * Nu + k] = k3 + 2;
        if (!has_incomplete_ion) {
            out.vals[0 * Nu + k] = -dV[k];
            out.vals[1 * Nu + k] = dV[k];
        } else {
            out.vals[0 * Nu + k] = -dV[k] * (1.0 - dcden[k]);
            out.vals[1 * Nu + k] = dV[k] * (1.0 + dcdp[k]);
        }
        // term3, term4: electron SRH row
        out.rows[2 * Nu + k] = k3 + 1; out.cols[2 * Nu + k] = k3 + 1;
        out.vals[2 * Nu + k] = -dRs_dn[k] * dV[k];
        out.rows[3 * Nu + k] = k3 + 1; out.cols[3 * Nu + k] = k3 + 2;
        out.vals[3 * Nu + k] = -dRs_dp[k] * dV[k];
        // term5, term6: hole SRH row
        out.rows[4 * Nu + k] = k3 + 2; out.cols[4 * Nu + k] = k3 + 2;
        out.vals[4 * Nu + k] = dRs_dp[k] * dV[k];
        out.rows[5 * Nu + k] = k3 + 2; out.cols[5 * Nu + k] = k3 + 1;
        out.vals[5 * Nu + k] = dRs_dn[k] * dV[k];
    }
    return out;
}

}  // namespace tcad::device3d
