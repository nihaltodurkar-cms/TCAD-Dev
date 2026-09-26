// Contour levels exactly as matplotlib chooses them for
// ax.contour(z, levels=n) -- the QML viewport's contour overlay uses
// levels=8 (NATIVE-DESKTOP-PLAN.md 15.17, S5f and review revision 1).
//
// A port of matplotlib 3.11's path, operation for operation:
//   ContourSet._ensure_locator_exists -> MaxNLocator(n + 1, min_n_ticks=1)
//   MaxNLocator.tick_values -> transforms._nonsingular(expander=1e-13, tiny=1e-14)
//                           -> _raw_ticks (scale_range, the extended step
//                              staircase, _Edge_integer; autolimit 'data')
//   ContourSet._autolev -> trim, keeping ONE level below zmin and ONE above zmax
// Python's float floor division and divmod are reproduced as CPython
// computes them (from fmod), not as floor(a / b). The MaxNLocator itself
// lives in max_n_locator.hpp since P2-S2 (the plot axes share it).
//
// gui/tests/test_desktop_contour_levels.py compares this with
// matplotlib's own ContourSet.levels. Qt- and VTK-free.
#pragma once

#include <vector>

namespace tcad::desktop {

// Line-contour levels for data spanning [zmin, zmax] (NaN excluded by the
// caller), as ax.contour(z, levels=n).levels.
std::vector<double> contour_levels(double zmin, double zmax, int n = 8);

}  // namespace tcad::desktop
