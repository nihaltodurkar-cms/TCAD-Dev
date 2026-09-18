#include "tcad/dg/kernels.hpp"

#include <algorithm>
#include <cmath>

namespace tcad::dg {
namespace {

// Harmonic mean, guarded against the 0/0 that gamma=0 (the first
// continuation stage, where pref is exactly zero everywhere) would
// otherwise hit -- mirrors dg_grid.py's own _hmean exactly.
inline double hmean(double lo, double hi) {
    const double s = lo + hi;
    return s > 0.0 ? 2.0 * lo * hi / s : 0.0;
}

inline void append(GridResult& out, std::int64_t r, std::int64_t c, double v) {
    out.rows.push_back(r);
    out.cols.push_back(c);
    out.vals.push_back(v);
}

}  // namespace

GridResult lambda_rows(
    std::int64_t N, int n_axes, const Axis* axes,
    const double* gn, const double* gp,
    const double* Lam_n, const double* Lam_p,
    const double* pref_n, const double* pref_p,
    const std::uint8_t* gate_mask, double VT) {
    GridResult out;
    out.Fn.assign(static_cast<std::size_t>(N), 0.0);
    out.Fp.assign(static_cast<std::size_t>(N), 0.0);

    struct Tag {
        const double* g;
        const double* Lam;
        const double* pref;
        double sign;
        int comp;   // 1 = Lambda_n column, 2 = Lambda_p column
        std::vector<double>* F;
    };
    const Tag tags[2] = {
        {gn, Lam_n, pref_n, +1.0, 1, &out.Fn},
        {gp, Lam_p, pref_p, -1.0, 2, &out.Fp},
    };

    for (const Tag& t : tags) {
        // M42-S2's ghosting: a gate node's g is forced to 0 in the
        // curvature stencil (both flux and Jacobian) -- see
        // dg_grid.py's own docstring for the physics rationale.
        std::vector<double> g_eff(static_cast<std::size_t>(N));
        for (std::int64_t k = 0; k < N; ++k)
            g_eff[static_cast<std::size_t>(k)] =
                gate_mask[k] ? 0.0 : t.g[k];

        auto dg_dpsi = [&](double gv) { return t.sign * gv / 2.0; };
        auto dg_dlam = [&](double gv) { return -gv / (2.0 * VT); };

        // Per-axis floating-point association order matters here (see
        // core/src/thermal/grid.cpp's own note on the same class of
        // issue): the Python/numpy reference vectorizes each of the 8
        // Jacobian terms as ONE array op across ALL edges of an axis,
        // so a (row,col) pair touched by two different edges (an
        // interior node's own diagonal, from being kR of its left edge
        // AND kL of its right edge) accumulates in "all edges' term k"
        // order, not edge-by-edge. Mirrored exactly here with 8
        // separate passes per axis rather than one interleaved pass,
        // so scipy's duplicate-summing order (stable-sorted by row,
        // otherwise insertion order) matches bit-for-bit.
        std::vector<double> lap(static_cast<std::size_t>(N), 0.0);
        std::vector<double> pref_e_buf, wL_buf, wR_buf;
        for (int a = 0; a < n_axes; ++a) {
            const Axis& ax = axes[a];
            const std::int64_t ne = ax.n_edges;
            pref_e_buf.assign(static_cast<std::size_t>(ne), 0.0);
            wL_buf.assign(static_cast<std::size_t>(ne), 0.0);
            wR_buf.assign(static_cast<std::size_t>(ne), 0.0);
            for (std::int64_t e = 0; e < ne; ++e) {
                const std::int64_t kL = ax.kL[e], kR = ax.kR[e];
                pref_e_buf[static_cast<std::size_t>(e)] = hmean(t.pref[kL], t.pref[kR]);
                wL_buf[static_cast<std::size_t>(e)] =
                    pref_e_buf[static_cast<std::size_t>(e)] / (ax.h_phys[e] * ax.dV_phys[kL]);
                wR_buf[static_cast<std::size_t>(e)] =
                    pref_e_buf[static_cast<std::size_t>(e)] / (ax.h_phys[e] * ax.dV_phys[kR]);
            }
            // divx[:, :-1] += Gx; divx[:, 1:] -= Gx (two full passes)
            for (std::int64_t e = 0; e < ne; ++e) {
                const std::int64_t kL = ax.kL[e], kR = ax.kR[e];
                const double G = pref_e_buf[static_cast<std::size_t>(e)]
                                * (g_eff[static_cast<std::size_t>(kR)]
                                 - g_eff[static_cast<std::size_t>(kL)])
                                / ax.h_phys[e];
                lap[static_cast<std::size_t>(kL)] += G / ax.dV_phys[kL];
            }
            for (std::int64_t e = 0; e < ne; ++e) {
                const std::int64_t kL = ax.kL[e], kR = ax.kR[e];
                const double G = pref_e_buf[static_cast<std::size_t>(e)]
                                * (g_eff[static_cast<std::size_t>(kR)]
                                 - g_eff[static_cast<std::size_t>(kL)])
                                / ax.h_phys[e];
                lap[static_cast<std::size_t>(kR)] -= G / ax.dV_phys[kR];
            }
            // 8 separate passes, one per Jacobian term, each covering
            // ALL edges of this axis before moving to the next term --
            // matches the 8 `rows.append(...)` calls in dg_grid.py's
            // per-axis loop exactly, each a single vectorized op there.
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kL[e] + t.comp, 3 * ax.kR[e],
                       wL_buf[static_cast<std::size_t>(e)]
                       * dg_dpsi(g_eff[static_cast<std::size_t>(ax.kR[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kL[e] + t.comp, 3 * ax.kR[e] + t.comp,
                       wL_buf[static_cast<std::size_t>(e)]
                       * dg_dlam(g_eff[static_cast<std::size_t>(ax.kR[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kL[e] + t.comp, 3 * ax.kL[e],
                       -wL_buf[static_cast<std::size_t>(e)]
                       * dg_dpsi(g_eff[static_cast<std::size_t>(ax.kL[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kL[e] + t.comp, 3 * ax.kL[e] + t.comp,
                       -wL_buf[static_cast<std::size_t>(e)]
                       * dg_dlam(g_eff[static_cast<std::size_t>(ax.kL[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kR[e] + t.comp, 3 * ax.kL[e],
                       wR_buf[static_cast<std::size_t>(e)]
                       * dg_dpsi(g_eff[static_cast<std::size_t>(ax.kL[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kR[e] + t.comp, 3 * ax.kL[e] + t.comp,
                       wR_buf[static_cast<std::size_t>(e)]
                       * dg_dlam(g_eff[static_cast<std::size_t>(ax.kL[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kR[e] + t.comp, 3 * ax.kR[e],
                       -wR_buf[static_cast<std::size_t>(e)]
                       * dg_dpsi(g_eff[static_cast<std::size_t>(ax.kR[e])]));
            for (std::int64_t e = 0; e < ne; ++e)
                append(out, 3 * ax.kR[e] + t.comp, 3 * ax.kR[e] + t.comp,
                       -wR_buf[static_cast<std::size_t>(e)]
                       * dg_dlam(g_eff[static_cast<std::size_t>(ax.kR[e])]));
        }

        for (std::int64_t k = 0; k < N; ++k)
            (*t.F)[static_cast<std::size_t>(k)] =
                t.Lam[k] * t.g[k] + lap[static_cast<std::size_t>(k)];

        // Diagonal "Lam*g" Jacobian term -- uses the GHOSTED g_eff, not
        // the real g the residual above used, a direct port of
        // dg_grid.py's own documented asymmetry (that row is entirely
        // overwritten by the Lambda pin at gate nodes, so it is
        // discarded, not wrong).
        for (std::int64_t k = 0; k < N; ++k) {
            const std::int64_t row_k = 3 * k + t.comp;
            const double ge = g_eff[static_cast<std::size_t>(k)];
            append(out, row_k, 3 * k, t.Lam[k] * dg_dpsi(ge));
            append(out, row_k, 3 * k + t.comp, ge + t.Lam[k] * dg_dlam(ge));
        }
    }

    return out;
}

}  // namespace tcad::dg
