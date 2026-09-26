#include "line_cut.hpp"

#include <cmath>
#include <stdexcept>

namespace tcad::desktop {

std::size_t nearest_node(const std::vector<double>& axis, double position) {
    if (axis.empty()) throw std::invalid_argument("line cut: empty axis");
    // numpy's argmin over abs(axis - position): the first minimum, except
    // that NaN propagates -- the first NaN wins (so a NaN position gives 0).
    std::size_t best = 0;
    double best_d = std::abs(axis[0] - position);
    if (std::isnan(best_d)) return 0;
    for (std::size_t i = 1; i < axis.size(); ++i) {
        const double d = std::abs(axis[i] - position);
        if (std::isnan(d)) return i;
        if (d < best_d) {
            best = i;
            best_d = d;
        }
    }
    return best;
}

LineCut line_cut(const std::vector<double>& x, const std::vector<double>& y,
                 const std::vector<double>& values, CutOrientation orientation, double position) {
    if (x.empty() || y.empty()) throw std::invalid_argument("line cut: empty axis");
    const std::size_t nx = x.size(), ny = y.size();
    if (values.size() != nx * ny)
        throw std::invalid_argument("line cut: " + std::to_string(values.size()) + " values for a " +
                                    std::to_string(ny) + " x " + std::to_string(nx) + " grid");
    LineCut c;
    if (orientation == CutOrientation::Horizontal) {
        c.index = nearest_node(y, position);
        c.actual = y[c.index];
        c.coord = x;
        c.values.assign(values.begin() + static_cast<std::ptrdiff_t>(c.index * nx),
                        values.begin() + static_cast<std::ptrdiff_t>((c.index + 1) * nx));
    } else {
        c.index = nearest_node(x, position);
        c.actual = x[c.index];
        c.coord = y;
        c.values.resize(ny);
        for (std::size_t j = 0; j < ny; ++j) c.values[j] = values[j * nx + c.index];
    }
    return c;
}

CutOrientation cut_orientation_from_string(const std::string& s) {
    if (s == "horizontal") return CutOrientation::Horizontal;
    if (s == "vertical") return CutOrientation::Vertical;
    throw std::invalid_argument("orientation must be 'horizontal' or 'vertical', got '" + s + "'");
}

}  // namespace tcad::desktop
