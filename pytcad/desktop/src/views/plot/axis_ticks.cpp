#include "axis_ticks.hpp"

#include "data/max_n_locator.hpp"
#include "data/pyfloat.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>

namespace tcad::desktop::plot {
namespace {

constexpr double kBase = 10.0;

// Python int arithmetic on the small exponents below.
long long py_mod(long long a, long long b) { return ((a % b) + b) % b; }

std::string printf_str(const char* fmt, double v) {
    char buf[512];
    std::snprintf(buf, sizeof buf, fmt, v);
    return buf;
}

std::string printf_prec(int decimals, double v) {
    char buf[512];
    std::snprintf(buf, sizeof buf, "%1.*f", decimals, v);
    return buf;
}

// Formatter.fix_minus with axes.unicode_minus (the default): "-" -> U+2212.
std::string fix_minus(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '-') out += "\xE2\x88\x92";
        else out += c;
    }
    return out;
}

// numpy's power_of_ten, used by np.round(x, decimals).
double numpy_power_of_ten(int n) {
    static const double p10[] = {1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8};
    if (n < 9) return p10[n];
    double ret = 1e9;
    while (n-- > 9) ret *= 10.;
    return ret;
}

// np.round(x, decimals) for decimals >= 0: rint(x * 10**d) / 10**d.
double numpy_round(double x, int decimals) {
    const double f = numpy_power_of_ten(decimals);
    return std::nearbyint(x * f) / f;
}

// Python's round(x, ndigits): correctly rounded to ndigits decimals, as
// CPython's dtoa does it (the %.Nf conversion is correctly rounded too).
double py_round(double x, int ndigits) { return std::strtod(printf_prec(ndigits, x).c_str(), nullptr); }

// Python int 10**e converted to float (exact decimal, correctly rounded),
// or, for e < 0, the float 10.0**e.
double py_ten_pow(long long e) {
    if (e < 0) return std::pow(10.0, static_cast<double>(e));
    return std::strtod(("1e" + std::to_string(e)).c_str(), nullptr);
}

// math.log(x, 10): CPython computes log(x) / log(10), NOT log10(x).
double math_log10_via_ln(double x) { return std::log(x) / std::log(kBase); }

}  // namespace

std::vector<double> linear_ticks(double vmin, double vmax, int nbins) {
    return max_n_tick_values(vmin, vmax, nbins, kAutoLocatorSteps, 2);
}

namespace {

// LogLocator.tick_values (not classic mode), base 10. `minor`: subs='auto',
// else subs=(1.0,).
std::vector<double> log_tick_values(double vmin, double vmax, int numticks, bool minor) {
    if (!(vmin > 0.0) || !std::isfinite(vmin)) return {};
    long long n_request = numticks;
    if (vmax < vmin) std::swap(vmin, vmax);
    // _log_b: np.log10 for base 10
    const double efmin = std::log10(vmin), efmax = std::log10(vmax);
    const long long emin = static_cast<long long>(std::ceil(efmin));
    const long long emax = static_cast<long long>(std::floor(efmax));
    const long long n_avail = emax - emin + 1;

    std::vector<double> subs;
    if (minor) {
        if (n_avail >= 10) return {};  // no minor ticks
        for (double s = 2.0; s < kBase; s += 1.0) subs.push_back(s);  // np.arange(2.0, 10)
    } else {
        subs = {1.0};
    }

    long long stride = n_avail / (n_request + 1) + 1;
    const long long nr = static_cast<long long>(std::ceil(static_cast<double>(n_avail) / static_cast<double>(stride)));
    if (nr <= n_request) n_request = nr;
    std::vector<long long> decades;
    if (n_request == 0) {  // no tick in bounds; two ticks just outside
        decades = {emin - 1, emax + 1};
        stride = decades[1] - decades[0];
    } else if (n_request == 1) {  // a single tick close to centre
        const long long mid = static_cast<long long>(py::round_half_even((efmin + efmax) / 2));
        stride = std::max(mid - (emin - 1), (emax + 1) - mid);
        decades = {mid - stride, mid, mid + stride};
    } else {
        stride = (n_avail - 1) / (n_request - 1);
        if (static_cast<double>(stride) < static_cast<double>(n_avail) / static_cast<double>(n_request))
            stride = n_avail / n_request;
        const long long olo = std::max(n_avail - stride * n_request, 0LL);
        const long long ohi = std::min(n_avail - stride * (n_request - 1), stride);
        long long offset = py_mod(-emin, stride);
        if (!(olo <= offset && offset < ohi)) offset = olo;
        for (long long d = emin + offset - stride; d < emax + stride + 1; d += stride) decades.push_back(d);
    }

    std::vector<double> ticklocs;
    const bool is_minor = subs.size() > 1 || (subs.size() == 1 && subs[0] != 1.0);
    if (is_minor) {
        if (stride == 1 || n_avail <= 1)  // minors start in the decade before the first major
            for (long long d = emin - 1; d < emax + 1; ++d) {
                const double p = std::pow(kBase, static_cast<double>(d));  // b**decade, float ** int
                for (double s : subs) ticklocs.push_back(s * p);
            }
    } else {
        for (long long d : decades) ticklocs.push_back(std::pow(kBase, static_cast<double>(d)));
    }

    if (subs.size() > 1 && stride == 1) {
        long long in_view = 0;
        for (double t : ticklocs) in_view += (vmin <= t && t <= vmax) ? 1 : 0;
        if (static_cast<long long>(decades.size()) - 2 + in_view <= 1)
            // a minor locator with at most one tick: AutoLocator() with no axis (nbins 9)
            return max_n_tick_values(vmin, vmax, 9, kAutoLocatorSteps, 2);
    }
    return ticklocs;
}

}  // namespace

std::vector<double> log_major_ticks(double vmin, double vmax, int numticks) {
    return log_tick_values(vmin, vmax, numticks, false);
}

std::vector<double> log_minor_ticks(double vmin, double vmax, int numticks) {
    return log_tick_values(vmin, vmax, numticks, true);
}

// -- ScalarFormatter ------------------------------------------------------------------

namespace {

// ScalarFormatter.format_data (the offset's text): no mathtext.
std::string format_data(double value) {
    const long long e = static_cast<long long>(std::floor(std::log10(std::abs(value))));
    const double s = py_round(value / py_ten_pow(e), 10);
    const std::string significand = std::fmod(s, 1.0) == 0.0 ? printf_str("%.0f", s) : printf_str("%1.10g", s);
    if (e == 0) return significand;
    return significand + "e" + std::to_string(e);
}

std::vector<double> in_view(const std::vector<double>& locs, double vmin, double vmax) {
    std::vector<double> out;
    for (double l : locs)
        if (vmin <= l && l <= vmax) out.push_back(l);
    return out;
}

double compute_offset(const std::vector<double>& locs_all, double vmin, double vmax) {
    const std::vector<double> locs = in_view(locs_all, vmin, vmax);
    if (locs.empty()) return 0.0;
    const double lmin = *std::min_element(locs.begin(), locs.end());
    const double lmax = *std::max_element(locs.begin(), locs.end());
    if (lmin == lmax || (lmin <= 0 && 0 <= lmax)) return 0.0;
    double abs_min = std::abs(lmin), abs_max = std::abs(lmax);
    if (abs_min > abs_max) std::swap(abs_min, abs_max);
    const double sign = std::copysign(1.0, lmin);
    const double oom_max = std::ceil(std::log10(abs_max));
    // np.float64 ** : pow; the float // np.float64 : numpy's divmod (as CPython's)
    auto p = [](double oom) { return std::pow(10.0, oom); };
    double oom = oom_max;
    for (int guard = 0; guard < 2200; ++guard, oom -= 1)
        if (py::floordiv(abs_min, p(oom)) != py::floordiv(abs_max, p(oom))) break;
    oom += 1;
    if ((abs_max - abs_min) / p(oom) <= 1e-2) {
        oom = oom_max;
        for (int guard = 0; guard < 2200; ++guard, oom -= 1)
            if (py::floordiv(abs_max, p(oom)) - py::floordiv(abs_min, p(oom)) > 1) break;
        oom += 1;
    }
    const int n = 4 - 1;  // axes.formatter.offset_threshold - 1
    return py::floordiv(abs_max, p(oom)) >= std::pow(10.0, n) ? sign * py::floordiv(abs_max, p(oom)) * p(oom) : 0.0;
}

int order_of_magnitude(const std::vector<double>& locs_all, double vmin, double vmax, double offset) {
    std::vector<double> locs = in_view(locs_all, vmin, vmax);
    if (locs.empty()) return 0;
    for (double& l : locs) l = std::abs(l);
    int oom;
    if (offset != 0.0) {
        oom = static_cast<int>(std::floor(std::log10(vmax - vmin)));
    } else {
        const double val = *std::max_element(locs.begin(), locs.end());
        oom = val == 0 ? 0 : static_cast<int>(std::floor(std::log10(val)));
    }
    if (oom <= -5 || oom >= 6) return oom;  // axes.formatter.limits (-5, 6)
    return 0;
}

int format_decimals(const std::vector<double>& locs_all, double view_a, double view_b, double offset, int oom) {
    std::vector<double> locs = locs_all;
    const bool few = locs_all.size() < 2;
    if (few) {
        locs.push_back(view_a);
        locs.push_back(view_b);
    }
    const double scale = std::pow(10.0, oom);
    for (double& l : locs) l = (l - offset) / scale;
    double loc_range = *std::max_element(locs.begin(), locs.end()) - *std::min_element(locs.begin(), locs.end());
    if (loc_range == 0) {
        loc_range = 0;
        for (double l : locs) loc_range = std::max(loc_range, std::abs(l));
    }
    if (loc_range == 0) loc_range = 1;
    if (few) locs.resize(locs.size() - 2);
    const int loc_range_oom = static_cast<int>(std::floor(std::log10(loc_range)));
    int sigfigs = std::max(0, 3 - loc_range_oom);
    const double thresh = 1e-3 * py_ten_pow(loc_range_oom);
    while (sigfigs >= 0) {
        double worst = 0;  // np.abs(locs - np.round(locs, sigfigs)).max(); an empty max raises in numpy
        for (double l : locs) worst = std::max(worst, std::abs(l - numpy_round(l, sigfigs)));
        if (worst < thresh) --sigfigs;
        else break;
    }
    return sigfigs + 1;
}

}  // namespace

ScalarLabels scalar_labels(const std::vector<double>& locs, double view_min, double view_max) {
    ScalarLabels out;
    if (locs.empty()) return out;
    const double vmin = std::min(view_min, view_max), vmax = std::max(view_min, view_max);
    const double offset = compute_offset(locs, vmin, vmax);
    const int oom = order_of_magnitude(locs, vmin, vmax, offset);
    const int decimals = format_decimals(locs, view_min, view_max, offset, oom);
    const double scale = std::pow(10.0, oom);
    for (double x : locs) {
        double xp = (x - offset) / scale;
        if (std::abs(xp) < 1e-8) xp = 0;
        out.labels.push_back(fix_minus(printf_prec(decimals, xp)));
    }
    if (oom != 0 || offset != 0.0) {
        std::string offset_str, sci;
        if (offset != 0.0) {
            offset_str = format_data(offset);
            if (offset > 0) offset_str = "+" + offset_str;
        }
        if (oom != 0) sci = "1e" + std::to_string(oom);
        out.offset_text = fix_minus(sci + offset_str);
    }
    return out;
}

// -- LogFormatterSciNotation --------------------------------------------------------

std::vector<LogLabel> log_labels(const std::vector<double>& locs, double view_min, double view_max) {
    // set_locs: which multiples of each decade are labelled
    double vmin = std::min(view_min, view_max), vmax = std::max(view_min, view_max);
    std::vector<double> sublabels;  // the set; {1} = decades only
    if (vmin <= 0) {
        sublabels = {1};
    } else {
        const double lmin = math_log10_via_ln(vmin), lmax = math_log10_via_ln(vmax);
        const double numticks = std::floor(lmax) - std::floor(std::nextafter(lmin, -std::numeric_limits<double>::infinity()));
        const double numdec = std::abs(lmax - lmin);
        if (numticks > 1) sublabels = {1};                        // minor_thresholds[0] (subset) = 1
        else if (numdec > 0.4) sublabels = {1, 2, 3, 4, 6, 10};   // set(np.round(np.geomspace(1, 10, 6)))
        else sublabels = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};         // set(np.arange(1, 11))
    }
    std::vector<LogLabel> out;
    for (double x0 : locs) {
        LogLabel lab;
        const double x = std::abs(x0);
        if (x == 0) {
            out.push_back(lab);  // matplotlib's symlog "0": never on a log view
            continue;
        }
        double fx = std::log(x) / std::log(kBase);
        const bool is_decade = py::isclose(fx, py::round_half_even(fx));
        const double exponent = is_decade ? py::round_half_even(fx) : std::floor(fx);
        const double coeff = py::round_half_even(std::pow(kBase, fx - exponent));
        if (std::find(sublabels.begin(), sublabels.end(), coeff) == sublabels.end()) {
            out.push_back(lab);
            continue;
        }
        lab.shown = true;
        if (is_decade) {
            fx = py::round_half_even(fx);
            lab.decade = true;
            lab.exponent = static_cast<int>(fx);
        } else {  // LogFormatterSciNotation._non_decade_format
            const double e = std::floor(fx);
            double c = std::pow(kBase, fx - e);
            if (py::isclose(c, py::round_half_even(c))) c = py::round_half_even(c);
            lab.decade = false;
            lab.coeff = c;
            lab.exponent = static_cast<int>(e);
        }
        out.push_back(lab);
    }
    return out;
}

std::string mathtext(const LogLabel& l) {
    if (!l.shown) return "";
    if (l.decade) return "$\\mathdefault{10^{" + std::to_string(l.exponent) + "}}$";
    return "$\\mathdefault{" + printf_str("%g", l.coeff) + "\\times10^{" + std::to_string(l.exponent) + "}}$";
}

}  // namespace tcad::desktop::plot
