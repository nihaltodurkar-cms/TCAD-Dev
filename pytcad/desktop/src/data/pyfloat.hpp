// Python float arithmetic that matplotlib's tick code relies on,
// reproduced as CPython computes it -- not as the obvious C++ spelling
// (1.0 // 0.1 == 9.0 in Python, floor(1.0 / 0.1) == 10). Shared by the
// contour levels (S5f) and the plot axes (P2-S2). Qt-free.
#pragma once

#include <cmath>
#include <utility>

namespace tcad::desktop::py {

// CPython's float_divmod (Objects/floatobject.c): (floor quotient, modulo
// with the divisor's sign), exactly as Python's divmod() and // compute it.
inline std::pair<double, double> divmod(double vx, double wx) {
    double mod = std::fmod(vx, wx);
    double div = (vx - mod) / wx;
    if (mod != 0.0) {
        if ((wx < 0) != (mod < 0)) {
            mod += wx;
            div -= 1.0;
        }
    } else {
        mod = std::copysign(0.0, wx);
    }
    double floordiv;
    if (div != 0.0) {
        floordiv = std::floor(div);
        if (div - floordiv > 0.5) floordiv += 1.0;
    } else {
        floordiv = std::copysign(0.0, vx / wx);
    }
    return {floordiv, mod};
}

inline double floordiv(double a, double b) { return divmod(a, b).first; }

// math.isclose(a, b) with its defaults (rel_tol=1e-9, abs_tol=0).
inline bool isclose(double a, double b) {
    if (a == b) return true;
    if (std::isinf(a) || std::isinf(b)) return false;
    const double diff = std::abs(b - a);
    return diff <= std::abs(1e-9 * b) || diff <= std::abs(1e-9 * a);
}

// Python's round(x) for a float: to the nearest integer, halves to even.
inline double round_half_even(double x) { return std::nearbyint(x); }

}  // namespace tcad::desktop::py
