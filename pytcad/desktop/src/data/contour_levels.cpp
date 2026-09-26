#include "contour_levels.hpp"

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <utility>

namespace tcad::desktop {
namespace {

// CPython's float_divmod (Objects/floatobject.c): (floor quotient, modulo
// with the divisor's sign), exactly as Python's divmod() and // compute it.
std::pair<double, double> py_divmod(double vx, double wx) {
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

double py_floordiv(double a, double b) { return py_divmod(a, b).first; }

// matplotlib.transforms._nonsingular
std::pair<double, double> nonsingular(double vmin, double vmax, double expander, double tiny) {
    if (!std::isfinite(vmin) || !std::isfinite(vmax)) return {-expander, expander};
    if (vmax < vmin) std::swap(vmin, vmax);
    const double maxabs = std::max(std::abs(vmin), std::abs(vmax));
    if (maxabs < (1e6 / tiny) * DBL_MIN) {
        vmin = -expander;
        vmax = expander;
    } else if (vmax - vmin <= maxabs * tiny) {
        if (vmax == 0 && vmin == 0) {
            vmin = -expander;
            vmax = expander;
        } else {
            vmin -= expander * std::abs(vmin);
            vmax += expander * std::abs(vmax);
        }
    }
    return {vmin, vmax};
}

// matplotlib.ticker.scale_range (threshold 100). `x // 1` on a float is
// Python floor division by 1.
std::pair<double, double> scale_range(double vmin, double vmax, int n) {
    const double dv = std::abs(vmax - vmin);
    const double meanv = (vmax + vmin) / 2;
    double offset = 0.0;
    if (!(std::abs(meanv) / dv < 100)) offset = std::copysign(std::pow(10.0, py_floordiv(std::log10(std::abs(meanv)), 1.0)), meanv);
    const double scale = std::pow(10.0, py_floordiv(std::log10(dv / n), 1.0));
    return {scale, offset};
}

// matplotlib.ticker._Edge_integer
struct EdgeInteger {
    double step, offset;
    bool closeto(double ms, double edge) const {
        double tol;
        if (offset > 0) {
            const double digits = std::log10(offset / step);
            tol = std::max(1e-10, std::pow(10.0, digits - 12));
            tol = std::min(0.4999, tol);
        } else {
            tol = 1e-10;
        }
        return std::abs(ms - edge) < tol;
    }
    double le(double x) const {
        const auto [d, m] = py_divmod(x, step);
        return closeto(m / step, 1) ? d + 1 : d;
    }
    double ge(double x) const {
        const auto [d, m] = py_divmod(x, step);
        return closeto(m / step, 0) ? d : d + 1;
    }
};

// MaxNLocator(nbins, min_n_ticks=1)._raw_ticks, default steps, integer=False,
// axes.autolimit_mode 'data' (no round_numbers adjustment), not a 3D axis.
std::vector<double> raw_ticks(double vmin, double vmax, int nbins) {
    static const double kSteps[] = {1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10};
    std::vector<double> extended;  // _staircase: 0.1*steps[:-1], steps, [10*steps[1]]
    for (int i = 0; i < 9; ++i) extended.push_back(0.1 * kSteps[i]);
    for (double s : kSteps) extended.push_back(s);
    extended.push_back(10 * kSteps[1]);

    const auto [scale, offset] = scale_range(vmin, vmax, nbins);
    const double v0 = vmin - offset, v1 = vmax - offset;
    std::vector<double> steps;
    for (double s : extended) steps.push_back(s * scale);
    const double raw_step = (v1 - v0) / nbins;
    std::size_t istep = steps.size() - 1;
    for (std::size_t i = 0; i < steps.size(); ++i)
        if (steps[i] >= raw_step) {
            istep = i;
            break;
        }
    std::vector<double> ticks;
    for (std::size_t k = istep + 1; k-- > 0;) {
        const double step = steps[k];
        const double best_vmin = py_floordiv(v0, step) * step;
        const EdgeInteger edge{step, std::abs(offset)};
        const double low = edge.le(v0 - best_vmin);
        const double high = edge.ge(v1 - best_vmin);
        // np.arange(low, high + 1): ceil(stop - start) values start + i
        ticks.clear();
        const auto count = static_cast<long long>(std::ceil((high + 1) - low));
        for (long long i = 0; i < count; ++i) ticks.push_back((low + static_cast<double>(i)) * step + best_vmin);
        long long nticks = 0;
        for (double t : ticks) nticks += (t <= v1 && t >= v0) ? 1 : 0;
        if (nticks >= 1) break;  // min_n_ticks = 1
    }
    for (double& t : ticks) t += offset;
    return ticks;
}

}  // namespace

std::vector<double> contour_levels(double zmin, double zmax, int n) {
    // MaxNLocator.tick_values (not symmetric, no prune)
    const auto [vmin, vmax] = nonsingular(zmin, zmax, 1e-13, 1e-14);
    const std::vector<double> lev = raw_ticks(vmin, vmax, n + 1);
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
