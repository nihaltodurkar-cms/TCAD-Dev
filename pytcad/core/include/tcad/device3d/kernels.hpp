// M47 Slice 2a: structured-grid (Device3D) BASE Jacobian assembly --
// the 4 block functions device3d.py's own `_residual_jacobian` factored
// out (_poisson_flux_row_coo, _electron_continuity_coo,
// _hole_continuity_coo, _base_diagonal_coo). Mirrors these EXACTLY,
// same call order per block (see each Python function's own docstring
// for the traced source order -- np.concatenate is associative, so the
// grouping into named blocks was already proven safe by construction;
// this port keeps every block's OWN internal sub-order unchanged too).
//
// SCOPE: this is genuinely flag-independent. `fd`/`incomplete_ion`
// affect what VALUES Python computes upstream (e.g. whether dJn_dn_L_x
// carries the fd correction) -- these kernels only STAMP whatever
// derivative arrays they are handed, so they run unconditionally,
// covering every Models() combination that reaches this code path.
// Optional-physics composition (impact/btbt/nonlocal-btbt/hydrodynamic/
// GateBC) stays entirely in Python, appended AFTER these 4 blocks,
// completely unchanged by this port.
//
// TRANSCENDENTALS: none of these 4 blocks contain one (no exp/
// bernoulli/log) -- all inputs are already-computed derivative/weight
// arrays. Nothing to keep out of C++ here that wasn't already computed
// in Python upstream, unlike M47 Slice 1's Poisson/SG kernels.
//
// RESERVE-FROM-THE-START (M47 Slice 1's own lesson, M47-3D-ENGINE-
// PLAN.md "Investigating the null speedup result"): every function
// below writes DIRECTLY into a single pre-sized output buffer at a
// known offset -- no intermediate per-term vectors, no insert()/
// extend() concatenation chain. This is the fix Slice 1 needed
// applied retroactively; here it is the design from line one.
#pragma once

#include <cstdint>
#include <span>
#include <vector>

namespace tcad::device3d {

struct Coo {
    std::vector<std::int64_t> rows;
    std::vector<std::int64_t> cols;
    std::vector<double> vals;
};

/// Poisson row (comp 0), x THEN y THEN z -- exact call order of the
/// original 3 `scatter()` calls. wx_h/wy_h/wz_h are the SG-independent
/// psi-flux weights (`wx_area*self.et_x/hx` etc., already computed in
/// Python).
Coo poisson_flux_row(
    std::span<const std::int64_t> kLx, std::span<const std::int64_t> kRx,
    std::span<const double> wx_h,
    std::span<const std::int64_t> kSy, std::span<const std::int64_t> kNy,
    std::span<const double> wy_h,
    std::span<const std::int64_t> kDz, std::span<const std::int64_t> kUz,
    std::span<const double> wz_h);

/// Electron continuity row (comp 1) -- x-psi, x-n, y-psi, y-n, z-psi,
/// z-n, exact call order of the original 6 `scatter()` calls. The
/// dJn_* arrays already carry the `fd` correction if that flag was on
/// (computed in Python, unchanged by this port).
Coo electron_continuity(
    std::span<const std::int64_t> kLx, std::span<const std::int64_t> kRx,
    std::span<const double> wx_area, std::span<const double> dJn_dpsiR_x,
    std::span<const double> dJn_dn_L_x, std::span<const double> dJn_dn_R_x,
    std::span<const std::int64_t> kSy, std::span<const std::int64_t> kNy,
    std::span<const double> wy_area, std::span<const double> dJn_dpsiR_y,
    std::span<const double> dJn_dn_L_y, std::span<const double> dJn_dn_R_y,
    std::span<const std::int64_t> kDz, std::span<const std::int64_t> kUz,
    std::span<const double> wz_area, std::span<const double> dJn_dpsiR_z,
    std::span<const double> dJn_dn_L_z, std::span<const double> dJn_dn_R_z);

/// Hole continuity row (comp 2) -- same shape as electron_continuity,
/// mirrors `_hole_continuity_coo` exactly (comp=2, p-derivative arrays).
Coo hole_continuity(
    std::span<const std::int64_t> kLx, std::span<const std::int64_t> kRx,
    std::span<const double> wx_area, std::span<const double> dJp_dpsiR_x,
    std::span<const double> dJp_dp_L_x, std::span<const double> dJp_dp_R_x,
    std::span<const std::int64_t> kSy, std::span<const std::int64_t> kNy,
    std::span<const double> wy_area, std::span<const double> dJp_dpsiR_y,
    std::span<const double> dJp_dp_L_y, std::span<const double> dJp_dp_R_y,
    std::span<const std::int64_t> kDz, std::span<const std::int64_t> kUz,
    std::span<const double> wz_area, std::span<const double> dJp_dpsiR_z,
    std::span<const double> dJp_dp_L_z, std::span<const double> dJp_dp_R_z);

/// Local (same-node) diagonal terms: Poisson's charge term (two forms
/// depending on incomplete_ion), then SRH n-row, then SRH p-row --
/// exact order/branch of the original 6 `append()` calls, 6 blocks of
/// N each. `has_incomplete_ion=false` ignores dcden/dcdp (pass
/// zero-length or any placeholder arrays; not read in that branch).
Coo base_diagonal(
    std::int64_t N, std::span<const double> dV, bool has_incomplete_ion,
    std::span<const double> dcden, std::span<const double> dcdp,
    std::span<const double> dRs_dn, std::span<const double> dRs_dp);

}  // namespace tcad::device3d
