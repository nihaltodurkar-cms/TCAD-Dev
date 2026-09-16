#include "tcad/thermal/kernels.hpp"

#include <array>
#include <cstring>

namespace tcad::thermal {
namespace {

/// Row-major strides for a D-dimensional shape (D <= 3, this project's
/// own convention -- see mesh2d.py/mesh3d.py, never a generic N-D
/// mesh). Axis 0 is the SLOWEST-varying, matching numpy's default
/// C-order and every device2d.py/device3d.py (Ny,Nx)/(Nz,Ny,Nx) array.
struct Shape {
    std::array<std::int64_t, 3> dims{1, 1, 1};
    std::array<std::int64_t, 3> strides{1, 1, 1};
    int D = 0;
    std::int64_t total = 1;
};

Shape make_shape(int D, const std::int64_t* dims) {
    Shape s;
    s.D = D;
    for (int a = 0; a < D; ++a) s.dims[static_cast<std::size_t>(a)] = dims[a];
    std::int64_t acc = 1;
    for (int a = D - 1; a >= 0; --a) {
        s.strides[static_cast<std::size_t>(a)] = acc;
        acc *= s.dims[static_cast<std::size_t>(a)];
    }
    s.total = acc;
    return s;
}

inline void decode(std::int64_t i, const Shape& s, std::int64_t* out) {
    for (int a = 0; a < s.D; ++a) {
        out[a] = i / s.strides[static_cast<std::size_t>(a)];
        i -= out[a] * s.strides[static_cast<std::size_t>(a)];
    }
}

inline std::int64_t encode(const std::int64_t* idx, const Shape& s) {
    std::int64_t f = 0;
    for (int a = 0; a < s.D; ++a) f += idx[a] * s.strides[static_cast<std::size_t>(a)];
    return f;
}

/// COO append helper -- mirrors the Python reference's `add()`: values
/// that are EXACTLY zero are dropped (never appended), matching
/// `m = v != 0.0` there precisely (not a tolerance).
inline void add(GridResult& out, std::int64_t r, std::int64_t c, double v) {
    if (v != 0.0) {
        out.rows.push_back(r);
        out.cols.push_back(c);
        out.vals.push_back(v);
    }
}

/// `_clear_row`: drop every existing (row,col,val) triple whose row is
/// in `row_ids`, preserving the relative order of what remains --
/// exactly the Python reference's list-comprehension `keep` filter,
/// needed so an isothermal boundary always overrides whatever the
/// interior stencil (or an earlier-processed resistance boundary at a
/// shared corner) already appended for that row.
void clear_rows(GridResult& out, const std::int64_t* row_ids, std::int64_t n) {
    std::size_t w = 0;
    const std::size_t n_entries = out.rows.size();
    for (std::size_t i = 0; i < n_entries; ++i) {
        bool drop = false;
        for (std::int64_t k = 0; k < n; ++k) {
            if (out.rows[i] == row_ids[k]) { drop = true; break; }
        }
        if (!drop) {
            out.rows[w] = out.rows[i];
            out.cols[w] = out.cols[i];
            out.vals[w] = out.vals[i];
            ++w;
        }
    }
    out.rows.resize(w);
    out.cols.resize(w);
    out.vals.resize(w);
}

}  // namespace

GridResult residual_jacobian_grid(
    int D, const std::int64_t* shape_in,
    const double* T, const double* H, double T_ambient,
    const double* const* dV, const double* const* h,
    const double* const* ke, const double* const* dke,
    const BC* bcs) {
    const Shape shape = make_shape(D, shape_in);
    const std::int64_t total = shape.total;

    GridResult out;
    out.F.assign(static_cast<std::size_t>(total), 0.0);

    // dV_full[i] = product over ALL axes a of dV[a][midx[a]]
    // (axis_weight(None, include_axis=True)); F = H*dV, matching the
    // reference's initial `F = H * dV` before any axis loop runs.
    for (std::int64_t i = 0; i < total; ++i) {
        std::array<std::int64_t, 3> midx{};
        decode(i, shape, midx.data());
        double w = 1.0;
        for (int a = 0; a < D; ++a) w = w * dV[a][midx[static_cast<std::size_t>(a)]];
        out.F[static_cast<std::size_t>(i)] = H[i] * w;
    }

    // ---- interior flux contributions, one axis at a time ----
    for (int axis = 0; axis < D; ++axis) {
        std::array<std::int64_t, 3> edge_dims{shape.dims};
        edge_dims[static_cast<std::size_t>(axis)] -= 1;
        const Shape edge_shape = make_shape(D, edge_dims.data());
        const std::int64_t n_edges = edge_shape.total;

        std::vector<std::int64_t> kL(static_cast<std::size_t>(n_edges));
        std::vector<std::int64_t> kR(static_cast<std::size_t>(n_edges));
        std::vector<double> Fedge(static_cast<std::size_t>(n_edges));
        std::vector<double> dF_lo(static_cast<std::size_t>(n_edges));
        std::vector<double> dF_hi(static_cast<std::size_t>(n_edges));

        for (std::int64_t e = 0; e < n_edges; ++e) {
            std::array<std::int64_t, 3> midx{};
            decode(e, edge_shape, midx.data());
            std::array<std::int64_t, 3> lo_idx = midx;
            std::array<std::int64_t, 3> hi_idx = midx;
            hi_idx[static_cast<std::size_t>(axis)] += 1;
            const std::int64_t l = encode(lo_idx.data(), shape);
            const std::int64_t r = encode(hi_idx.data(), shape);
            kL[static_cast<std::size_t>(e)] = l;
            kR[static_cast<std::size_t>(e)] = r;

            // w = axis_weight(axis, include_axis=False): product over
            // every OTHER axis of dV[a][midx[a]], in axis order 0..D-1
            // (matching the reference's `for a in range(D)` loop).
            double w = 1.0;
            for (int a = 0; a < D; ++a) {
                if (a == axis) continue;
                w = w * dV[a][midx[static_cast<std::size_t>(a)]];
            }

            const double h_a = h[axis][midx[static_cast<std::size_t>(axis)]];
            const double ke_v = ke[axis][static_cast<std::size_t>(e)];
            const double dke_v = dke[axis][static_cast<std::size_t>(e)];
            const double dT = T[r] - T[l];

            // Fedge = w*ke*dT/h_a  ==  ((w*ke)*dT)/h_a
            const double wke = w * ke_v;
            Fedge[static_cast<std::size_t>(e)] = (wke * dT) / h_a;

            // dF_lo = w*(dke*dT/h_a - ke/h_a); dF_hi = w*(... + ...)
            const double term1 = (dke_v * dT) / h_a;
            const double term2 = ke_v / h_a;
            dF_lo[static_cast<std::size_t>(e)] = w * (term1 - term2);
            dF_hi[static_cast<std::size_t>(e)] = w * (term1 + term2);
        }

        // div[lo] += Fedge (pass 1, all edges), div[hi] -= Fedge (pass
        // 2, all edges), THEN F = F + div once -- reproducing the
        // reference's own two-pass-then-add structure exactly, rather
        // than folding straight into F, because scipy/numpy's
        // elementwise `F = F + div` happens AFTER both scatter passes
        // complete, not interleaved with them.
        std::vector<double> div(static_cast<std::size_t>(total), 0.0);
        for (std::int64_t e = 0; e < n_edges; ++e)
            div[static_cast<std::size_t>(kL[static_cast<std::size_t>(e)])] +=
                Fedge[static_cast<std::size_t>(e)];
        for (std::int64_t e = 0; e < n_edges; ++e)
            div[static_cast<std::size_t>(kR[static_cast<std::size_t>(e)])] -=
                Fedge[static_cast<std::size_t>(e)];
        for (std::int64_t i = 0; i < total; ++i)
            out.F[static_cast<std::size_t>(i)] += div[static_cast<std::size_t>(i)];

        // Jacobian: FOUR separate passes over all edges, in the same
        // order as the reference's four separate add() calls --
        // add(kL,kL,dF_lo); add(kL,kR,dF_hi); add(kR,kL,-dF_lo);
        // add(kR,kR,-dF_hi) -- because a node touched by two DIFFERENT
        // edges of the SAME axis (an interior diagonal) is a genuine
        // duplicate (row,col) pair, and scipy.sparse.csr_matrix sums
        // duplicates in insertion order.
        for (std::int64_t e = 0; e < n_edges; ++e)
            add(out, kL[static_cast<std::size_t>(e)], kL[static_cast<std::size_t>(e)],
                dF_lo[static_cast<std::size_t>(e)]);
        for (std::int64_t e = 0; e < n_edges; ++e)
            add(out, kL[static_cast<std::size_t>(e)], kR[static_cast<std::size_t>(e)],
                dF_hi[static_cast<std::size_t>(e)]);
        for (std::int64_t e = 0; e < n_edges; ++e)
            add(out, kR[static_cast<std::size_t>(e)], kL[static_cast<std::size_t>(e)],
                -dF_lo[static_cast<std::size_t>(e)]);
        for (std::int64_t e = 0; e < n_edges; ++e)
            add(out, kR[static_cast<std::size_t>(e)], kR[static_cast<std::size_t>(e)],
                -dF_hi[static_cast<std::size_t>(e)]);
    }

    // ---- boundaries: resistance first (all axes), isothermal last
    // (all axes) -- matches thermal_grid.py's own `boundaries` list
    // (built axis-then-lo/hi) and its two separate filtering loops, so
    // isothermal always wins at a corner/edge shared with a Robin
    // boundary regardless of which axis each came from.
    struct Boundary {
        int axis;
        std::int64_t fixed;   // 0 or shape[axis]-1
        BC bc;
    };
    std::vector<Boundary> boundaries;
    boundaries.reserve(static_cast<std::size_t>(2 * D));
    for (int axis = 0; axis < D; ++axis) {
        boundaries.push_back({axis, 0, bcs[2 * axis + 0]});
        boundaries.push_back(
            {axis, shape.dims[static_cast<std::size_t>(axis)] - 1, bcs[2 * axis + 1]});
    }

    auto strip_total = [&](int axis) {
        return total / shape.dims[static_cast<std::size_t>(axis)];
    };

    // decode a flat index over the (D-1)-axis boundary strip into the
    // FULL D-dim multi-index, with `axis` fixed at `fixed` -- matches
    // numpy's T[..., fixed, ...] scalar-indexing ravel order (every
    // OTHER axis keeps its original relative order).
    auto decode_strip = [&](std::int64_t e, int axis, std::int64_t fixed,
                            std::int64_t* out_idx) {
        Shape reduced;
        reduced.D = D - 1;
        int j = 0;
        for (int a = 0; a < D; ++a) {
            if (a == axis) continue;
            reduced.dims[static_cast<std::size_t>(j)] = shape.dims[static_cast<std::size_t>(a)];
            ++j;
        }
        std::int64_t acc = 1;
        for (int a = D - 2; a >= 0; --a) {
            reduced.strides[static_cast<std::size_t>(a)] = acc;
            acc *= reduced.dims[static_cast<std::size_t>(a)];
        }
        std::array<std::int64_t, 3> reduced_idx{};
        decode(e, reduced, reduced_idx.data());
        j = 0;
        for (int a = 0; a < D; ++a) {
            if (a == axis) { out_idx[a] = fixed; continue; }
            out_idx[a] = reduced_idx[static_cast<std::size_t>(j)];
            ++j;
        }
    };

    for (const auto& b : boundaries) {
        if (b.bc.kind != 1) continue;  // resistance only
        const std::int64_t n = strip_total(b.axis);
        const double inv_Rth = 1.0 / b.bc.R_th_area;
        // cross = axis_weight(axis, include_axis=False), squeezed --
        // for a boundary node, the SAME product-over-other-axes as an
        // interior edge along this axis would use.
        for (std::int64_t e = 0; e < n; ++e) {
            std::array<std::int64_t, 3> midx{};
            decode_strip(e, b.axis, b.fixed, midx.data());
            const std::int64_t node = encode(midx.data(), shape);
            double cross = 1.0;
            for (int a = 0; a < D; ++a) {
                if (a == b.axis) continue;
                cross = cross * dV[a][midx[static_cast<std::size_t>(a)]];
            }
            const double Tb = T[node];
            // F[bslice] = F[bslice] - (Tb-T_ambient)*inv_Rth*cross_b
            const double correction = ((Tb - T_ambient) * inv_Rth) * cross;
            out.F[static_cast<std::size_t>(node)] -= correction;
            // add(bnode, bnode, -inv_Rth*cross_b)
            add(out, node, node, -(inv_Rth * cross));
        }
    }

    for (const auto& b : boundaries) {
        if (b.bc.kind != 0) continue;  // isothermal only
        const std::int64_t n = strip_total(b.axis);
        std::vector<std::int64_t> nodes(static_cast<std::size_t>(n));
        for (std::int64_t e = 0; e < n; ++e) {
            std::array<std::int64_t, 3> midx{};
            decode_strip(e, b.axis, b.fixed, midx.data());
            const std::int64_t node = encode(midx.data(), shape);
            nodes[static_cast<std::size_t>(e)] = node;
            out.F[static_cast<std::size_t>(node)] = T[node] - T_ambient;
        }
        clear_rows(out, nodes.data(), n);
        for (std::int64_t e = 0; e < n; ++e)
            add(out, nodes[static_cast<std::size_t>(e)], nodes[static_cast<std::size_t>(e)], 1.0);
    }

    return out;
}

}  // namespace tcad::thermal
