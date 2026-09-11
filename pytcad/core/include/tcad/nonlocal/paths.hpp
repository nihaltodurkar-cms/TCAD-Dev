// Nonlocal band-to-band tunneling path tracer (M34-S4).
//
// Compiled mirror of pytcad/nonlocal_path.py::_trace_paths_py -- the
// per-path stepping loop of build_structured, which follows field lines
// of a structured 2D/3D potential grid.  The Python function is the
// ORACLE: tests/test_m34_s4_trace_parity.py compares every output array
// with np.array_equal, so this file reproduces its arithmetic operation
// for operation rather than "the same algorithm":
//
//   * every sum is sequential, in the reference's order, starting from
//     0.0 (the reference replaces np.dot by an explicit loop for exactly
//     this reason: BLAS may reassociate);
//   * the multilinear weights are products in axis order, starting 1.0;
//   * bisect.bisect_right is std::upper_bound;
//   * Python's builtin min/max keep the FIRST argument unless the second
//     is strictly smaller/greater -- mirrored by py_min/py_max, so a NaN
//     propagates the same way;
//   * sqrt is correctly rounded in both libraries (IEEE 754), and this
//     translation unit is compiled with -ffp-contract=off so no multiply-
//     add is fused (see core/CMakeLists.txt).
//
// No transcendental other than sqrt appears, and the array work (the
// nodal gradient, the edge-field pre-screen, the candidate list) stays
// in numpy -- its RESULTS are passed down, the M31 P4 convention.
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::nonlocal {

struct TraceResult {
    std::vector<std::int64_t> starts;   // (P,)
    std::vector<std::int64_t> offset;   // (P+1,)
    std::vector<std::int64_t> sidx;     // (S*K,)  K = 2^d
    std::vector<double> swts;           // (S*K,)
    std::vector<double> seg_len;        // (S,)    [m]
    std::vector<std::int64_t> gidx;     // (P*(K+1),)
    std::vector<double> gwts;           // (P*(K+1),)
};

/// Trace the tunnel paths from every candidate start node.
///
/// coords : the d coordinate arrays [cm] concatenated in array-axis
///          order (C order: 2D (y, x), 3D (z, y, x)); shape[a] entries
///          each.
/// psi    : (n_nodes,) potential in units of VT, row-major.
/// grads  : (d, n_nodes) nodal gradient [1/cm], row-major.
/// cand   : candidate start nodes, in the order they are traced.
/// contact: (n_nodes,) true at Dirichlet contact nodes.
TraceResult trace_paths(const double* coords, const std::int64_t* shape, int d,
                        const double* psi, const double* grads,
                        std::int64_t n_nodes, const std::int64_t* cand,
                        std::int64_t n_cand, const bool* contact, double VT,
                        double Eg_eV, double screen_Vcm, double margin,
                        std::int64_t max_steps, double hmin_all);

}  // namespace tcad::nonlocal
