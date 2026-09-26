// Patch edges for "nearest" shading, as matplotlib's
// pcolormesh(x, y, z, shading="nearest") computes them (Axes._interp_grid,
// matplotlib 3.11): each node owns [midpoint to the previous node, midpoint
// to the next], and the first and last patches extend half the
// neighbouring spacing outward. Operation for operation, so the edges are
// bit-identical to matplotlib's (gui/tests/test_desktop_nearest_edges.py).
// A single node gets a zero-width patch [x0, x0], as matplotlib's does.
// NATIVE-DESKTOP-PLAN.md 15.17, S5c. Qt- and VTK-free.
#pragma once

#include <cstddef>
#include <vector>

namespace tcad::desktop {

inline std::vector<double> nearest_edges(const std::vector<double>& x) {
    const std::size_t n = x.size();
    if (n == 0) return {};
    if (n == 1) return {x[0], x[0]};
    std::vector<double> e(n + 1);
    // dX = diff(X) * 0.5; X = [X[0] - dX[0], X[:-1] + dX, X[-1] + dX[-1]]
    e[0] = x[0] - (x[1] - x[0]) * 0.5;
    for (std::size_t i = 0; i + 1 < n; ++i) e[i + 1] = x[i] + (x[i + 1] - x[i]) * 0.5;
    e[n] = x[n - 1] + (x[n - 1] - x[n - 2]) * 0.5;
    return e;
}

}  // namespace tcad::desktop
