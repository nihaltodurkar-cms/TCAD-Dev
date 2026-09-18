// M42-S3: the Lambda_n/Lambda_p flux-divergence/Jacobian assembly for
// the density-gradient (Ancona-Stafford) coupled-Newton equilibrium
// solve, generic over D=2 or 3 mesh axes -- pytcad/dg_grid.py's own
// _dg_lambda_rows_py, a TRANSCRIPTION (same discipline as
// core/src/thermal/grid.cpp / core/src/process/diffuse.cpp): every
// numpy statement in the reference becomes code here in the same
// order with the same association.
//
// THE TRANSCENDENTALS, AND WHY THEY NEVER CROSS THIS BOUNDARY
// ----------------------------------------------------------------------
// sqrt(n)/sqrt(p) (the density-gradient "g" variable) are evaluated
// ONCE in Python and handed down as `gn`/`gp` plain arrays -- per the
// house rule (CLAUDE.md's "Where an accelerated function's
// transcendentals live matters"). This kernel is pure arithmetic
// (+, -, *, /) end to end.
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::dg {

struct GridResult {
    std::vector<double> Fn;              // (N,) Lambda_n residual
    std::vector<double> Fp;              // (N,) Lambda_p residual
    std::vector<std::int64_t> rows;      // Jacobian COO, into the 3N system
    std::vector<std::int64_t> cols;
    std::vector<double> vals;
};

/// One mesh axis's edge data.
struct Axis {
    std::int64_t n_edges = 0;
    const std::int64_t* kL = nullptr;   // (n_edges,) "near" node index
    const std::int64_t* kR = nullptr;   // (n_edges,) "far" node index
    const double* h_phys = nullptr;     // (n_edges,) physical edge length
    const double* dV_phys = nullptr;    // (N,) physical control-volume
                                        // width along THIS axis, per node
};

/// Lambda_n/Lambda_p box-integration flux-divergence rows and their
/// Jacobian, generic over `n_axes` mesh axes (2 for Device2D, 3 for
/// Device3D) -- pytcad/dg_grid.py's own dg_lambda_rows.
///
/// N          : total node count.
/// axes       : n_axes entries.
/// gn, gp     : flat (N,) sqrt(n)/sqrt(p) -- see the transcendental
///              note above.
/// Lam_n, Lam_p, pref_n, pref_p : flat (N,).
/// gate_mask  : flat (N,) nonzero => ghost g to 0 at this node (M42-S2's
///              infinite-barrier hard wall).
/// VT         : thermal voltage [V].
///
/// The interleaved-unknown convention is fixed: for node k, psi is at
/// column 3k, Lambda_n at 3k+1, Lambda_p at 3k+2 -- matching every
/// device's own ip()/iln()/ilp() index functions exactly.
GridResult lambda_rows(
    std::int64_t N, int n_axes, const Axis* axes,
    const double* gn, const double* gp,
    const double* Lam_n, const double* Lam_p,
    const double* pref_n, const double* pref_p,
    const std::uint8_t* gate_mask, double VT);

}  // namespace tcad::dg
