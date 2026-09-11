#include "tcad/nonlocal/paths.hpp"

#include <algorithm>
#include <cmath>
#include <string>

#include "tcad/base/errors.hpp"

namespace tcad::nonlocal {
namespace {

/// Python's builtin max(a, b): b only if STRICTLY greater.
inline double py_max(double a, double b) { return b > a ? b : a; }
/// Python's builtin min(a, b): b only if STRICTLY smaller.
inline double py_min(double a, double b) { return b < a ? b : a; }

constexpr int kMaxDim = 3;
constexpr std::int64_t kNoProgressSteps = 64;   // nonlocal_path.NO_PROGRESS_STEPS
constexpr int kMaxCorners = 8;

struct Grid {
    int d;
    const double* c[kMaxDim];      // coordinate array per axis
    std::int64_t n[kMaxDim];       // points per axis
    std::int64_t stride[kMaxDim];  // row-major strides
    int K;                         // 2^d corners
};

/// _trace_paths_py.cell: the cell containing P (direction-aware when a
/// coordinate sits exactly on a face), and the local coordinates.
void cell(const Grid& g, const double* P, const double* dirv, std::int64_t* idx,
          double* t) {
    for (int a = 0; a < g.d; ++a) {
        const double* c = g.c[a];
        std::int64_t k = static_cast<std::int64_t>(
                             std::upper_bound(c, c + g.n[a], P[a]) - c) - 1;
        if (dirv != nullptr && k > 0 && P[a] == c[k] && dirv[a] < 0.0) k -= 1;
        // min(max(k, 0), n - 2) on integers
        if (k < 0) k = 0;
        if (k > g.n[a] - 2) k = g.n[a] - 2;
        idx[a] = k;
        const double v = (P[a] - c[k]) / (c[k + 1] - c[k]);
        t[a] = py_min(py_max(v, 0.0), 1.0);
    }
}

/// _trace_paths_py.stencil: corner nodes in itertools-product order
/// (axis 0 slowest) and their multilinear weights, products in axis order.
void stencil(const Grid& g, const std::int64_t* idx, const double* t,
             std::int64_t* nodes, double* w) {
    for (int ci = 0; ci < g.K; ++ci) {
        std::int64_t flat = 0;
        double wi = 1.0;
        for (int a = 0; a < g.d; ++a) {
            const int bit = (ci >> (g.d - 1 - a)) & 1;
            flat += (idx[a] + bit) * g.stride[a];
            wi *= bit ? t[a] : 1.0 - t[a];
        }
        nodes[ci] = flat;
        w[ci] = wi;
    }
}

/// _trace_paths_py.interp: sequential sum from 0.0 in corner order.
double interp(int K, const std::int64_t* nodes, const double* w, const double* vals) {
    double acc = 0.0;
    for (int ci = 0; ci < K; ++ci) acc += w[ci] * vals[nodes[ci]];
    return acc;
}

}  // namespace

TraceResult trace_paths(const double* coords, const std::int64_t* shape, int d,
                        const double* psi, const double* grads,
                        std::int64_t n_nodes, const std::int64_t* cand,
                        std::int64_t n_cand, const bool* contact, double VT,
                        double Eg_eV, double screen_Vcm, double margin,
                        std::int64_t max_steps, double hmin_all) {
    if (d != 2 && d != 3)
        throw InvalidArgument("trace_paths: the grid must be 2D or 3D, got " +
                              std::to_string(d) + " axes");
    Grid g{};
    g.d = d;
    g.K = 1 << d;
    std::int64_t off = 0, total = 1;
    for (int a = 0; a < d; ++a) {
        if (shape[a] < 2)
            throw InvalidArgument("trace_paths: every axis needs >= 2 points");
        g.c[a] = coords + off;
        g.n[a] = shape[a];
        off += shape[a];
        total *= shape[a];
    }
    if (total != n_nodes)
        throw InvalidArgument("trace_paths: shape does not match the node count");
    g.stride[d - 1] = 1;
    for (int a = d - 2; a >= 0; --a) g.stride[a] = g.stride[a + 1] * shape[a + 1];
    for (std::int64_t q = 0; q < n_cand; ++q) {
        if (cand[q] < 0 || cand[q] >= n_nodes)
            throw IndexOutOfRange("trace_paths: candidate " + std::to_string(q) +
                                  " names node " + std::to_string(cand[q]) +
                                  ", out of range for " + std::to_string(n_nodes) +
                                  " nodes");
    }

    const int K = g.K;
    TraceResult r;
    r.offset.push_back(0);
    std::vector<std::int64_t> pn;   // this path's sample stencils, flat
    std::vector<double> pw;
    std::vector<double> pl;
    std::int64_t idx[kMaxDim], nodes[kMaxCorners];
    double t[kMaxDim], w[kMaxCorners];
    double P[kMaxDim], Pn[kMaxDim], gv[kMaxDim], dirv[kMaxDim];

    for (std::int64_t q = 0; q < n_cand; ++q) {
        const std::int64_t s = cand[q];
        std::int64_t rem = s;
        for (int a = 0; a < d; ++a) {
            const std::int64_t m = rem / g.stride[a];
            rem -= m * g.stride[a];
            P[a] = g.c[a][m];
        }
        const double psi_s = psi[s];
        pn.assign(static_cast<std::size_t>(K), s);
        pw.assign(static_cast<std::size_t>(K), 0.0);
        pw[0] = 1.0;
        pl.clear();
        bool reached = false;
        std::int64_t n_samples = 1;
        double best = psi_s;
        std::int64_t stall = 0;
        double length = 0.0;
        const double len_cap = margin * Eg_eV / screen_Vcm;   // cm

        for (std::int64_t step = 0; step < max_steps; ++step) {
            cell(g, P, nullptr, idx, t);
            stencil(g, idx, t, nodes, w);
            for (int a = 0; a < d; ++a) gv[a] = interp(K, nodes, w, grads + a * n_nodes);
            double acc = 0.0;
            for (int a = 0; a < d; ++a) acc += gv[a] * gv[a];
            const double gn = std::sqrt(acc);
            if (gn == 0.0) break;
            for (int a = 0; a < d; ++a) dirv[a] = gv[a] / gn;
            for (int a = 0; a < d; ++a) {
                if ((P[a] <= g.c[a][0] && dirv[a] < 0.0) ||
                    (P[a] >= g.c[a][g.n[a] - 1] && dirv[a] > 0.0))
                    dirv[a] = 0.0;
            }
            acc = 0.0;
            for (int a = 0; a < d; ++a) acc += dirv[a] * dirv[a];
            const double nrm = std::sqrt(acc);
            if (nrm == 0.0) break;
            for (int a = 0; a < d; ++a) dirv[a] = dirv[a] / nrm;
            cell(g, P, dirv, idx, t);
            double ds = g.c[0][idx[0] + 1] - g.c[0][idx[0]];
            for (int a = 1; a < d; ++a)
                ds = py_min(ds, g.c[a][idx[a] + 1] - g.c[a][idx[a]]);
            ds = 0.5 * ds;
            int lim_axis = -1;
            double lim_face = 0.0;
            for (int a = 0; a < d; ++a) {
                double face;
                if (dirv[a] > 0.0) face = g.c[a][idx[a] + 1];
                else if (dirv[a] < 0.0) face = g.c[a][idx[a]];
                else continue;
                const double da = (face - P[a]) / dirv[a];
                if (da < ds) {
                    ds = da;
                    lim_axis = a;
                    lim_face = face;
                }
            }
            if (!(ds > 1e-12 * hmin_all)) break;
            for (int a = 0; a < d; ++a) Pn[a] = P[a] + ds * dirv[a];
            if (lim_axis >= 0) Pn[lim_axis] = lim_face;
            for (int a = 0; a < d; ++a) {
                double face;
                if (dirv[a] > 0.0) face = g.c[a][idx[a] + 1];
                else if (dirv[a] < 0.0) face = g.c[a][idx[a]];
                else continue;
                const double w_cell = g.c[a][idx[a] + 1] - g.c[a][idx[a]];
                if (std::fabs(Pn[a] - face) <= 1e-9 * w_cell) Pn[a] = face;
            }
            bool outside = false;
            for (int a = 0; a < d; ++a)
                if (Pn[a] < g.c[a][0] || Pn[a] > g.c[a][g.n[a] - 1]) outside = true;
            if (outside) break;
            cell(g, Pn, dirv, idx, t);
            stencil(g, idx, t, nodes, w);
            bool hits_contact = false;
            for (int ci = 0; ci < K; ++ci)
                if (w[ci] > 0.0 && contact[nodes[ci]]) hits_contact = true;
            if (hits_contact) break;
            pn.insert(pn.end(), nodes, nodes + K);
            pw.insert(pw.end(), w, w + K);
            pl.push_back(ds * 1e-2);                        // cm -> m
            ++n_samples;
            length += ds;
            const double psi_here = interp(K, nodes, w, psi);
            if (n_samples == 2 && VT * (psi_here - psi_s) / ds < screen_Vcm)
                break;                                      // first-segment screen
            const double raw = VT * (psi_here - psi_s) / Eg_eV;
            if (raw >= 1.0) reached = true;
            if (raw >= margin) break;
            if (psi_here > best) {
                best = psi_here;
                stall = 0;
            } else if (++stall >= kNoProgressSteps) {
                break;
            }
            if (length > len_cap) break;
            for (int a = 0; a < d; ++a) P[a] = Pn[a];
        }
        if (!reached || n_samples < 2) continue;
        const double L0 = pl[0];
        r.starts.push_back(s);
        r.sidx.insert(r.sidx.end(), pn.begin(), pn.end());
        r.swts.insert(r.swts.end(), pw.begin(), pw.end());
        r.seg_len.insert(r.seg_len.end(), pl.begin(), pl.end());
        r.seg_len.push_back(0.0);
        r.offset.push_back(r.offset.back() + n_samples);
        r.gidx.push_back(s);
        r.gidx.insert(r.gidx.end(), pn.begin() + K, pn.begin() + 2 * K);
        r.gwts.push_back(-1.0 / L0);
        for (int ci = 0; ci < K; ++ci) r.gwts.push_back(pw[K + ci] / L0);
    }
    return r;
}

}  // namespace tcad::nonlocal
