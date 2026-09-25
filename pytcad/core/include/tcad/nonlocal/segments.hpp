// Exact WKB integrals over straight tunnel-path segments (nonlocal BTBT).
//
// Compiled mirror of pytcad/btbt.py::segment_integrals, the hot spot of
// nonlocal_path.evaluate (B10 profile 2026-09-25: 5.2s of 14.6s, with
// _kane_alpha_c evaluated 8 times per segment on the same 3 points).
// Here each segment evaluates eq (9)'s alpha/cos(theta) ONCE at each of
// its 3 points (hi, lo, midpoint) in one pass.
//
// The Python function is the ORACLE: tests/test_accel_segment_integrals.py
// compares all six outputs with np.array_equal, so this reproduces its
// arithmetic operation for operation:
//   * every expression keeps numpy's association order, and scalar
//     prefactors are formed exactly as the Python scalars are;
//   * np.maximum(a, b) keeps a when a >= b or a is NaN; np.clip(x, 0, 1)
//     is MIN(MAX(x, 0), 1) with NaN passing through;
//   * np.where evaluates both branches -- only the selected value is
//     kept, as here;
//   * sqrt is correctly rounded (IEEE 754); atan2 is the one other
//     transcendental and the parity gate is what vouches for it;
//   * compiled with -ffp-contract=off (core/CMakeLists.txt).
#pragma once

#include <cstdint>

namespace tcad::nonlocal {

/// Per segment s in [0, n): delta runs linearly from da[s] to db[s]
/// over length L[s] [m]. u = m0/(2 mr) (> 1), Eg_J [J], mr_kg [kg].
/// Writes Ik, Iik, dIk_da, dIk_db, dIik_da, dIik_db (each length n).
void segment_integrals(const double* da, const double* db, const double* L,
                       std::int64_t n, double u, double Eg_J, double mr_kg,
                       double hbar, double* Ik, double* Iik, double* dIk_da,
                       double* dIk_db, double* dIik_da, double* dIik_db);

}  // namespace tcad::nonlocal
