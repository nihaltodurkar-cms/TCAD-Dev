// matplotlib's MaxNLocator.tick_values, operation for operation
// (matplotlib 3.11, ticker.py), for a GIVEN number of bins: the contour
// levels (S5f) and the plot axes' AutoLocator (P2-S2) both call it.
//
//   tick_values -> transforms._nonsingular(expander=1e-13, tiny=1e-14)
//               -> _raw_ticks: scale_range, the extended step staircase,
//                  _Edge_integer; autolimit 'data' (no round_numbers),
//                  integer=False, not a 3D axis, no prune, not symmetric.
//
// `nbins="auto"` is NOT here: matplotlib derives it from the axis length
// in points and its font size, which the native app does not share
// (NATIVE-DESKTOP-PLAN.md 16.2); the caller chooses nbins. Qt-free.
#pragma once

#include <span>
#include <utility>
#include <vector>

namespace tcad::desktop {

// MaxNLocator's default steps, and AutoLocator's.
inline constexpr double kDefaultSteps[] = {1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10};
inline constexpr double kAutoLocatorSteps[] = {1, 2, 2.5, 5, 10};

// MaxNLocator(nbins, steps=steps, min_n_ticks=min_n_ticks).tick_values(vmin, vmax).
// `steps` must be increasing within [1, 10]; 1 and 10 are added when
// missing, as _validate_steps does.
std::vector<double> max_n_tick_values(double vmin, double vmax, int nbins, std::span<const double> steps,
                                      int min_n_ticks);

// matplotlib.transforms._nonsingular.
std::pair<double, double> mpl_nonsingular(double vmin, double vmax, double expander, double tiny);

}  // namespace tcad::desktop
