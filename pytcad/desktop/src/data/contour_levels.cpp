#include "contour_levels.hpp"

#include "max_n_locator.hpp"

#include <cstddef>

namespace tcad::desktop {

std::vector<double> contour_levels(double zmin, double zmax, int n) {
    // ContourSet._ensure_locator_exists: MaxNLocator(n + 1, min_n_ticks=1),
    // default steps; its tick_values (not symmetric, no prune)
    const std::vector<double> lev = max_n_tick_values(zmin, zmax, n + 1, kDefaultSteps, 1);
    // ContourSet._autolev (extend 'neither'): keep one level beyond each end
    std::size_t i0 = 0, i1 = lev.size();
    for (std::size_t i = 0; i < lev.size(); ++i)
        if (lev[i] < zmin) i0 = i;  // the last level under zmin
    for (std::size_t i = 0; i < lev.size(); ++i)
        if (lev[i] > zmax) {
            i1 = i + 1;  // up to and including the first level over zmax
            break;
        }
    if (static_cast<long long>(i1) - static_cast<long long>(i0) < 3) {
        i0 = 0;
        i1 = lev.size();
    }
    return std::vector<double>(lev.begin() + static_cast<std::ptrdiff_t>(i0), lev.begin() + static_cast<std::ptrdiff_t>(i1));
}

}  // namespace tcad::desktop
