// Up-front argument validation shared by the bindings.
//
// errors.hpp's IndexOutOfRange contract -- "every kernel taking
// connectivity validates the index range ONCE up front" -- was, until
// 2026-09-23, honoured only by process/indicators.cpp and
// nonlocal/paths.cpp.  Every other kernel dereferenced whatever index it
// was handed, so a malformed array SEGV'd or overflowed the heap instead
// of raising (found under ASan/UBSan; gated by
// tests/test_core_input_validation.py).  These helpers are that one O(n)
// pass, called in the bindings BEFORE the GIL is released, so the kernels
// themselves can keep assuming valid input.
//
// Validation only: nothing here changes any value a kernel computes.
#pragma once

#include <cstdint>
#include <string>

#include "tcad/base/errors.hpp"

namespace tcad {

/// Every entry of idx[0..count) must lie in [0, n_nodes).
/// -> IndexError, the class numpy raises for the same mistake.
inline void check_indices(const std::int64_t* idx, std::int64_t count,
                          std::int64_t n_nodes, const char* what) {
    for (std::int64_t k = 0; k < count; ++k) {
        const std::int64_t v = idx[k];
        if (v < 0 || v >= n_nodes)
            throw IndexOutOfRange(std::string(what) + "[" + std::to_string(k) +
                                  "] = " + std::to_string(v) +
                                  " is out of range for " +
                                  std::to_string(n_nodes) + " nodes");
    }
}

/// An array's length must equal `want`.  -> ValueError
inline void check_length(std::int64_t got, std::int64_t want, const char* what) {
    if (got != want)
        throw InvalidArgument(std::string(what) + ": expected length " +
                              std::to_string(want) + ", got " + std::to_string(got));
}

}  // namespace tcad
