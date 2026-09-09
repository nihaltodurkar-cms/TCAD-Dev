#include "tcad/process/kernels.hpp"

#include <cmath>
#include <string>

#include "tcad/base/errors.hpp"
#include "tcad/geom/simplex.hpp"

namespace tcad::process {
namespace {

/// Python's builtin `max(a, b)`: returns b only if it is STRICTLY
/// greater. With a NaN operand every comparison is false, so `a` wins --
/// and the reference's `max(vals)` / `max(x, y)` behave the same way.
/// Reproducing that is the difference between "bit-identical" and
/// "bit-identical on inputs that happen to be finite".
inline double py_max(double a, double b) { return b > a ? b : a; }

/// Python's builtin `min(a, b)`: the mirror image, replacing only on a
/// strictly smaller item.
inline double py_min(double a, double b) { return b < a ? b : a; }

/// np.linalg.norm on a length-2 vector -- measured equal to
/// sqrt(x*x + y*y) in geom/simplex.hpp's preamble, which is why this
/// can be written out rather than deferred to a library.
inline double edge_len(const double* nodes_xyz, std::int64_t i, std::int64_t j) {
    const double dx = nodes_xyz[3 * j]     - nodes_xyz[3 * i];
    const double dy = nodes_xyz[3 * j + 1] - nodes_xyz[3 * i + 1];
    return std::sqrt(dx * dx + dy * dy);
}

/// One O(n) pass, before any dereference, so a malformed connectivity
/// array raises instead of reading out of bounds. The reference gets
/// this from numpy fancy-indexing; see tcad::IndexOutOfRange.
void check_indices(const std::int64_t* tris, std::int64_t n_tris, std::int64_t n_nodes) {
    for (std::int64_t k = 0; k < 3 * n_tris; ++k) {
        const std::int64_t v = tris[k];
        if (v < 0 || v >= n_nodes) {
            throw IndexOutOfRange(
                "triangle " + std::to_string(k / 3) + " names node " +
                std::to_string(v) + ", which is out of range for " +
                std::to_string(n_nodes) + " nodes");
        }
    }
}

}  // namespace

std::vector<double> indicator_curvature_tri(const double* nodes_xyz, std::int64_t n_nodes,
                                           const std::int64_t* tris, std::int64_t n_tris,
                                           const double* psi, double scale) {
    check_indices(tris, n_tris, n_nodes);
    std::vector<double> out(static_cast<std::size_t>(n_tris), 0.0);

    for (std::int64_t k = 0; k < n_tris; ++k) {
        const std::int64_t a = tris[3 * k], b = tris[3 * k + 1], c = tris[3 * k + 2];
        // The reference builds vals in edge order (a,b), (b,c), (c,a)
        // and then takes max(vals), i.e. seeds with the first and
        // replaces on a strictly greater one.
        double best = edge_len(nodes_xyz, a, b) * std::fabs(psi[b] - psi[a]);
        best = py_max(best, edge_len(nodes_xyz, b, c) * std::fabs(psi[c] - psi[b]));
        best = py_max(best, edge_len(nodes_xyz, c, a) * std::fabs(psi[a] - psi[c]));
        out[static_cast<std::size_t>(k)] = best / scale;
    }
    return out;
}

std::vector<double> indicator_log_density_tri(std::int64_t n_nodes,
                                             const std::int64_t* tris, std::int64_t n_tris,
                                             const double* ln_n, const double* ln_p) {
    check_indices(tris, n_tris, n_nodes);
    std::vector<double> out(static_cast<std::size_t>(n_tris), 0.0);

    for (std::int64_t k = 0; k < n_tris; ++k) {
        const std::int64_t v[3] = {tris[3 * k], tris[3 * k + 1], tris[3 * k + 2]};
        double best = 0.0;
        for (int e = 0; e < 3; ++e) {
            const std::int64_t i = v[e], j = v[(e + 1) % 3];
            // Inner max(|dln n|, |dln p|) is a 2-argument builtin max
            // too, so it takes the first on a tie or a NaN.
            const double val = py_max(std::fabs(ln_n[j] - ln_n[i]),
                                      std::fabs(ln_p[j] - ln_p[i]));
            best = (e == 0) ? val : py_max(best, val);
        }
        out[static_cast<std::size_t>(k)] = best;
    }
    return out;
}

std::vector<double> debye_ratio_tri(const double* nodes_xyz, std::int64_t n_nodes,
                                   const std::int64_t* tris, std::int64_t n_tris,
                                   const double* ld_node) {
    check_indices(tris, n_tris, n_nodes);
    std::vector<double> out(static_cast<std::size_t>(n_tris), 0.0);

    for (std::int64_t k = 0; k < n_tris; ++k) {
        const std::int64_t a = tris[3 * k], b = tris[3 * k + 1], c = tris[3 * k + 2];
        double h = edge_len(nodes_xyz, a, b);
        h = py_max(h, edge_len(nodes_xyz, b, c));
        h = py_max(h, edge_len(nodes_xyz, c, a));

        double ld_min = ld_node[a];
        ld_min = py_min(ld_min, ld_node[b]);
        ld_min = py_min(ld_min, ld_node[c]);

        out[static_cast<std::size_t>(k)] = h / py_max(ld_min, 1e-300);
    }
    return out;
}

}  // namespace tcad::process
