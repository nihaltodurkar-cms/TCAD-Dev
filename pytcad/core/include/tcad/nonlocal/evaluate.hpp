// Live evaluation of frozen nonlocal-BTBT tunnel paths at one psi.
//
// Compiled mirror of pytcad/nonlocal_path.py::_evaluate_py, which stays
// as the ORACLE (tests/test_accel_nonlocal_evaluate.py: np.array_equal
// on every PathEval field, and on the COO arrays the CSR matrices are
// built from). Everything up to the COO triplets is here; scipy still
// builds the two CSR matrices, because its duplicate summation follows
// an unstable per-row sort that C++ cannot reproduce bit for bit.
//
// numpy semantics mirrored exactly:
//   * np.sum(x, axis=1) over a row of n terms: sequential from -0.0 when
//     n < 8, else numpy's 8-accumulator pairwise block then the rest
//     sequentially (measured on this build, 2026-09-25);
//   * np.bincount / np.cumsum / ufunc.at: sequential, in index order,
//     starting from 0.0 (add.at into zeros turns -0.0 into +0.0);
//   * np.minimum / np.maximum propagate NaN; np.clip passes NaN;
//     np.sign(+-0) is +0.0; np.argmin/argmax return the first NaN if any;
//   * exp is the UCRT exp numpy itself calls on this build (checked
//     bit-identical on 8e5 samples); sqrt/atan2 as in segments.hpp;
//   * compiled with -ffp-contract=off.
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::nonlocal {

struct EvalResult {
    std::vector<double> G, Ik, Iik, length, fmin, fmax;   // (P,)
    std::vector<std::uint8_t> reached;                   // (P,)
    std::vector<std::int64_t> dG_rows, dG_cols;          // COO, reference order
    std::vector<double> dG_vals;
    std::vector<std::int64_t> dep_rows, dep_cols;
    std::vector<double> dep_vals;
    std::vector<std::int64_t> ddep_p, ddep_node, ddep_col; // after keep = val != 0
    std::vector<double> ddep_val;
};

EvalResult evaluate_paths(const double* psi, std::int64_t N,
                          const std::int64_t* start, const std::int64_t* offset,
                          std::int64_t P, const std::int64_t* sidx,
                          const double* swts, std::int64_t S, std::int64_t K,
                          const double* seg_len, const std::int64_t* gidx,
                          const double* gwts, std::int64_t Kg, double VT,
                          double Eg_J, double mr_kg, double mc_kg, double mv_kg,
                          double u, double hbar, double q);

}  // namespace tcad::nonlocal
