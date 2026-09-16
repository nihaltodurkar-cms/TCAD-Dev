// M43 phase 3: the structured-grid (D=2 or 3) self-heating
// residual/Jacobian assembly, pytcad/thermal_grid.py's own
// _residual_jacobian_grid_py -- a TRANSCRIPTION, not a reimplementation
// (same discipline as core/src/process/diffuse.cpp): every numpy
// statement in the reference becomes code here in the SAME ORDER with
// the SAME ASSOCIATION, including places that look avoidable (the
// two-pass-per-axis "lo scatter, then hi scatter, then add to F once"
// structure mirrors the reference's `div[lo]+=Fedge; div[hi]-=Fedge;
// F=F+div` exactly rather than accumulating directly into F, and the
// Jacobian COO triples are appended in FOUR SEPARATE PASSES per axis
// -- kL/kL, then kL/kR, then kR/kL, then kR/kR across ALL edges --
// mirroring the reference's four separate vectorized add() calls,
// because scipy.sparse.csr_matrix sums DUPLICATE (row,col) entries in
// insertion order, and a diagonal node touched by two different edges
// of the same axis is exactly such a duplicate).
//
// THE ONE TRANSCENDENTAL, AND WHY IT NEVER CROSSES THIS BOUNDARY
// ----------------------------------------------------------------------
// material.kappa_th(Tavg) is a power law (kappa_th300 * (T/300)^-1.33)
// -- the ONLY non-arithmetic operation in the whole assembly. Per the
// house rule (see kernels.hpp in core/include/tcad/process/, and
// CLAUDE.md's "Where an accelerated function's transcendentals live
// matters"), it is evaluated ONCE in Python and its RESULT -- the
// per-axis edge kappa `ke[axis]` and its T-derivative `dke[axis]` --
// crosses the boundary as a plain array. This kernel is pure
// arithmetic (+, -, *, /) end to end, which is what makes exact
// bit-identity against the Python oracle a tractable claim rather than
// a hope about two libm implementations agreeing.
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::thermal {

/// One boundary condition, mirroring pytcad.thermal.ThermalBC: kind 0 =
/// isothermal, 1 = resistance, 2 = adiabatic. R_th_area only matters
/// for kind 1 (unread otherwise, matching the Python reference's own
/// "adiabatic never reads R_th_area" behavior).
struct BC {
    int kind = 0;
    double R_th_area = 0.0;
};

struct GridResult {
    std::vector<double> F;               // (total,) residual, row-major
    std::vector<std::int64_t> rows;      // Jacobian COO
    std::vector<std::int64_t> cols;
    std::vector<double> vals;
};

/// Residual/Jacobian of the steady ND (D=2 or 3) heat equation
/// -div(kappa_th(T) grad T) = H on a tensor-product mesh.
///
/// shape[D]     : node counts per axis, row-major (matches T's own
///                np.ndarray.shape -- axis 0 is the SLOWEST-varying).
/// T, H         : flat, row-major, size = product(shape).
/// dV[axis]     : control-volume widths along `axis` (length shape[axis]).
/// h[axis]      : edge spacings along `axis` (length shape[axis]-1).
/// ke[axis]     : edge-averaged kappa_th along `axis`, flat row-major
///                over the EDGE shape (shape with axis's length reduced
///                by 1) -- already evaluated in Python.
/// dke[axis]    : d(kappa_th)/dT at each edge's own endpoint (both
///                endpoints share the same value -- see the Python
///                reference's `dke_dT_each`), same shape as ke[axis].
/// bcs          : 2*D entries, ordered [axis0_lo, axis0_hi, axis1_lo,
///                axis1_hi, ...] -- matches thermal_grid.py's own
///                `boundaries` list construction order.
GridResult residual_jacobian_grid(
    int D, const std::int64_t* shape,
    const double* T, const double* H, double T_ambient,
    const double* const* dV, const double* const* h,
    const double* const* ke, const double* const* dke,
    const BC* bcs);

}  // namespace tcad::thermal
