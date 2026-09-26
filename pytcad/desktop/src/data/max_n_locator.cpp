#include "max_n_locator.hpp"

#include "pyfloat.hpp"

#include <algorithm>
#include <cfloat>
#include <cmath>

namespace tcad::desktop {
namespace {

// matplotlib.ticker.scale_range (threshold 100). `x // 1` on a float is
// Python floor division by 1.
std::pair<double, double> scale_range(double vmin, double vmax, int n) {
    const double dv = std::abs(vmax - vmin);
    const double meanv = (vmax + vmin) / 2;
    double offset = 0.0;
    if (!(std::abs(meanv) / dv < 100))
        offset = std::copysign(std::pow(10.0, py::floordiv(std::log10(std::abs(meanv)), 1.0)), meanv);
    const double scale = std::pow(10.0, py::floordiv(std::log10(dv / n), 1.0));
    return {scale, offset};
}

// matplotlib.ticker._Edge_integer (it stores abs(offset)).
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
        const auto [d, m] = py::divmod(x, step);
        return closeto(m / step, 1) ? d + 1 : d;
    }
    double ge(double x) const {
        const auto [d, m] = py::divmod(x, step);
        return closeto(m / step, 0) ? d : d + 1;
    }
};

// MaxNLocator._raw_ticks with the given nbins, steps and min_n_ticks.
std::vector<double> raw_ticks(double vmin, double vmax, int nbins, const std::vector<double>& steps_in,
                              int min_n_ticks) {
    // _staircase: 0.1 * steps[:-1], steps, [10 * steps[1]]
    std::vector<double> extended;
    for (std::size_t i = 0; i + 1 < steps_in.size(); ++i) extended.push_back(0.1 * steps_in[i]);
    for (double s : steps_in) extended.push_back(s);
    extended.push_back(10 * steps_in[1]);

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
        const double best_vmin = py::floordiv(v0, step) * step;
        const EdgeInteger edge{step, std::abs(offset)};
        const double low = edge.le(v0 - best_vmin);
        const double high = edge.ge(v1 - best_vmin);
        // np.arange(low, high + 1): ceil(stop - start) values start + i
        ticks.clear();
        const auto count = static_cast<long long>(std::ceil((high + 1) - low));
        for (long long i = 0; i < count; ++i) ticks.push_back((low + static_cast<double>(i)) * step + best_vmin);
        long long nticks = 0;
        for (double t : ticks) nticks += (t <= v1 && t >= v0) ? 1 : 0;
        if (nticks >= min_n_ticks) break;
    }
    for (double& t : ticks) t += offset;
    return ticks;
}

}  // namespace

std::pair<double, double> mpl_nonsingular(double vmin, double vmax, double expander, double tiny) {
    if (!std::isfinite(vmin) || !std::isfinite(vmax)) return {-expander, expander};
    if (vmax < vmin) std::swap(vmin, vmax);  // increasing=True: stays swapped
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

std::vector<double> max_n_tick_values(double vmin, double vmax, int nbins, std::span<const double> steps,
                                      int min_n_ticks) {
    std::vector<double> s(steps.begin(), steps.end());
    if (s.empty() || s.front() != 1) s.insert(s.begin(), 1.0);  // _validate_steps
    if (s.back() != 10) s.push_back(10.0);
    const auto [a, b] = mpl_nonsingular(vmin, vmax, 1e-13, 1e-14);
    return raw_ticks(a, b, std::max(1, nbins), s, std::max(1, min_n_ticks));
}

}  // namespace tcad::desktop
