#include "tcad/mesh/stencil.hpp"

#include <algorithm>
#include <cstdio>
#include <string>

#include "tcad/base/errors.hpp"
#include "tcad/geom/simplex.hpp"
#include "tcad/runtime/threads.hpp"

namespace tcad::mesh {
namespace {

using geom::Vec2;
using geom::Vec3;

inline Vec2 node2(const double* p, int64_t i) { return {p[3 * i], p[3 * i + 1]}; }
inline Vec3 node3(const double* p, int64_t i) { return {p[3 * i], p[3 * i + 1], p[3 * i + 2]}; }

/// One (element, local-entity) incidence. `seq` is the position at which
/// Python's dict would first have seen this key, which is what selects
/// WHICH bad entity gets reported when several are non-manifold: Python
/// takes next(iter(bad)) on an insertion-ordered dict, not the
/// lexicographically smallest.
struct EdgeRec {
    int64_t lo, hi;
    int64_t elem;
    int64_t seq;
};

bool by_key_then_elem(const EdgeRec& a, const EdgeRec& b) {
    if (a.lo != b.lo) return a.lo < b.lo;
    if (a.hi != b.hi) return a.hi < b.hi;
    return a.elem < b.elem;
}

/// Python's f"{x:.3e}" / f"{x:.1e}" -- C's %.3e/%.1e agree with Python's
/// format spec for finite doubles (both round-half-even on the decimal
/// expansion). Pinned by tests/test_accel_parity.py's message checks
/// rather than assumed.
std::string fmt(double v, int prec) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*e", prec, v);
    return buf;
}

/// Faces of a tet, in the reference's FACES order.
constexpr int FACES[4][3] = {{0, 1, 2}, {0, 1, 3}, {0, 2, 3}, {1, 2, 3}};
/// Edges of a tet, in the reference's EDGES order.
constexpr int EDGES[6][2] = {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3}};

/// For each local vertex pair (a<b), the two FACES ordinals containing
/// both -- in FACES order, matching the reference's list comprehension
/// `[f for f in FACES if local_i in f and local_j in f]`.
constexpr int PAIR_FACES[4][4][2] = {
    {{-1, -1}, {0, 1}, {0, 2}, {1, 2}},
    {{-1, -1}, {-1, -1}, {0, 3}, {1, 3}},
    {{-1, -1}, {-1, -1}, {-1, -1}, {2, 3}},
    {{-1, -1}, {-1, -1}, {-1, -1}, {-1, -1}},
};

}  // namespace

Stencil2D build_stencil2d(const double* nodes_xy, size_t n_nodes,
                          const int64_t* tris, size_t n_tris,
                          double min_area) {
    Stencil2D out;
    out.node_areas.assign(n_nodes, 0.0);

    std::vector<EdgeRec> recs;
    recs.reserve(3 * n_tris);

    // Serial and in element order: the reference accumulates node areas
    // triangle by triangle, and float addition is not associative, so
    // this loop must not be reordered. It is also not the bottleneck --
    // the dictionary work this replaces was.
    for (size_t t = 0; t < n_tris; ++t) {
        const int64_t a = tris[3 * t], b = tris[3 * t + 1], c = tris[3 * t + 2];
        const Vec2 p0 = node2(nodes_xy, a), p1 = node2(nodes_xy, b), p2 = node2(nodes_xy, c);
        const double area2 = geom::triangle_area2(p0, p1, p2);
        const double tri_area = 0.5 * std::fabs(area2);
        if (tri_area < min_area) {
            throw DegenerateMesh(
                "triangle " + std::to_string(t) + " (nodes " + std::to_string(a) + "," +
                std::to_string(b) + "," + std::to_string(c) + ") has area " +
                fmt(tri_area, 3) + " < min_area=" + fmt(min_area, 1) +
                " -- degenerate or duplicate/collinear vertices");
        }

        const int64_t tri3[3] = {a, b, c};
        for (int e = 0; e < 3; ++e) {
            const int64_t u = tri3[e], v = tri3[(e + 1) % 3];
            recs.push_back({std::min(u, v), std::max(u, v),
                            static_cast<int64_t>(t),
                            static_cast<int64_t>(3 * t + e)});
        }

        const double La2 = geom::sqnorm2(geom::sub2(p1, p2));
        const double Lb2 = geom::sqnorm2(geom::sub2(p2, p0));
        const double Lc2 = geom::sqnorm2(geom::sub2(p0, p1));
        const bool obtuse_a = La2 > Lb2 + Lc2;
        const bool obtuse_b = Lb2 > La2 + Lc2;
        const bool obtuse_c = Lc2 > La2 + Lb2;

        if (obtuse_a || obtuse_b || obtuse_c) {
            if (obtuse_a) {
                out.node_areas[a] += 0.5 * tri_area;
                out.node_areas[b] += 0.25 * tri_area;
                out.node_areas[c] += 0.25 * tri_area;
            } else if (obtuse_b) {
                out.node_areas[b] += 0.5 * tri_area;
                out.node_areas[a] += 0.25 * tri_area;
                out.node_areas[c] += 0.25 * tri_area;
            } else {
                out.node_areas[c] += 0.5 * tri_area;
                out.node_areas[a] += 0.25 * tri_area;
                out.node_areas[b] += 0.25 * tri_area;
            }
        } else {
            const double cot_a = geom::cot(p0, p1, p2);
            const double cot_b = geom::cot(p1, p2, p0);
            const double cot_c = geom::cot(p2, p0, p1);
            const double term_ab = cot_c * Lc2 / 8.0;
            const double term_bc = cot_a * La2 / 8.0;
            const double term_ca = cot_b * Lb2 / 8.0;
            out.node_areas[a] += term_ab + term_ca;
            out.node_areas[b] += term_ab + term_bc;
            out.node_areas[c] += term_bc + term_ca;
        }
    }

    std::sort(recs.begin(), recs.end(), by_key_then_elem);

    // Non-manifold check. Report the group Python would report: the one
    // whose key was inserted FIRST, i.e. smallest `seq` among bad groups.
    const EdgeRec* worst = nullptr;
    int64_t worst_seq = 0;
    size_t worst_count = 0;
    for (size_t s = 0; s < recs.size();) {
        size_t e = s;
        int64_t first_seq = recs[s].seq;
        while (e < recs.size() && recs[e].lo == recs[s].lo && recs[e].hi == recs[s].hi) {
            first_seq = std::min(first_seq, recs[e].seq);
            ++e;
        }
        if (e - s > 2 && (worst == nullptr || first_seq < worst_seq)) {
            worst = &recs[s];
            worst_seq = first_seq;
            worst_count = e - s;
        }
        s = e;
    }
    if (worst != nullptr) {
        throw DegenerateMesh(
            "edge (" + std::to_string(worst->lo) + ", " + std::to_string(worst->hi) +
            ") is shared by " + std::to_string(worst_count) +
            " triangles (expected 1 or 2) -- the mesh is not a valid 2-manifold "
            "triangulation (likely disconnected/overlapping triangles)");
    }

    // Unique keys, already in lexicographic order == sorted(dict.keys()).
    for (size_t s = 0; s < recs.size();) {
        size_t e = s;
        while (e < recs.size() && recs[e].lo == recs[s].lo && recs[e].hi == recs[s].hi) ++e;
        out.edges.push_back(recs[s].lo);
        out.edges.push_back(recs[s].hi);
        ++out.n_edges;
        s = e;
    }
    return out;
}

Stencil3D build_stencil3d(const double* nodes_xyz, size_t n_nodes,
                          const int64_t* tets, size_t n_tets,
                          double min_volume) {
    Stencil3D out;
    out.node_vol.assign(n_nodes, 0.0);

    std::vector<EdgeRec> erecs;
    erecs.reserve(6 * n_tets);
    struct FaceRec { int64_t a, b, c, elem, seq; };
    std::vector<FaceRec> frecs;
    frecs.reserve(4 * n_tets);

    for (size_t t = 0; t < n_tets; ++t) {
        const int64_t* v = &tets[4 * t];
        const Vec3 p0 = node3(nodes_xyz, v[0]), p1 = node3(nodes_xyz, v[1]);
        const Vec3 p2 = node3(nodes_xyz, v[2]), p3 = node3(nodes_xyz, v[3]);
        const double vol = std::fabs(geom::tet_volume(p0, p1, p2, p3));
        if (vol < min_volume) {
            throw DegenerateMesh(
                "tet " + std::to_string(t) + " (nodes [" + std::to_string(v[0]) + ", " +
                std::to_string(v[1]) + ", " + std::to_string(v[2]) + ", " +
                std::to_string(v[3]) + "]) has volume " + fmt(vol, 3) +
                " < min_volume=" + fmt(min_volume, 1) +
                " -- degenerate or duplicate/coplanar vertices");
        }
        // node_vol[verts] += vol / 4.0 -- four adds, in vertex order
        const double quarter = vol / 4.0;
        for (int k = 0; k < 4; ++k) out.node_vol[v[k]] += quarter;

        for (int e = 0; e < 6; ++e) {
            const int64_t u = v[EDGES[e][0]], w = v[EDGES[e][1]];
            erecs.push_back({std::min(u, w), std::max(u, w),
                             static_cast<int64_t>(t), static_cast<int64_t>(6 * t + e)});
        }
        for (int f = 0; f < 4; ++f) {
            int64_t s[3] = {v[FACES[f][0]], v[FACES[f][1]], v[FACES[f][2]]};
            std::sort(s, s + 3);
            frecs.push_back({s[0], s[1], s[2],
                             static_cast<int64_t>(t), static_cast<int64_t>(4 * t + f)});
        }
    }

    std::sort(frecs.begin(), frecs.end(), [](const FaceRec& x, const FaceRec& y) {
        if (x.a != y.a) return x.a < y.a;
        if (x.b != y.b) return x.b < y.b;
        if (x.c != y.c) return x.c < y.c;
        return x.elem < y.elem;
    });
    const FaceRec* badf = nullptr;
    int64_t badf_seq = 0;
    size_t badf_count = 0;
    for (size_t s = 0; s < frecs.size();) {
        size_t e = s;
        int64_t first_seq = frecs[s].seq;
        while (e < frecs.size() && frecs[e].a == frecs[s].a &&
               frecs[e].b == frecs[s].b && frecs[e].c == frecs[s].c) {
            first_seq = std::min(first_seq, frecs[e].seq);
            ++e;
        }
        if (e - s > 2 && (badf == nullptr || first_seq < badf_seq)) {
            badf = &frecs[s];
            badf_seq = first_seq;
            badf_count = e - s;
        }
        s = e;
    }
    if (badf != nullptr) {
        throw DegenerateMesh(
            "face (" + std::to_string(badf->a) + ", " + std::to_string(badf->b) + ", " +
            std::to_string(badf->c) + ") is shared by " + std::to_string(badf_count) +
            " tets (expected 1 or 2) -- the mesh is not a valid manifold "
            "tetrahedralization");
    }

    std::sort(erecs.begin(), erecs.end(), by_key_then_elem);
    for (size_t s = 0; s < erecs.size();) {
        size_t e = s;
        while (e < erecs.size() && erecs[e].lo == erecs[s].lo && erecs[e].hi == erecs[s].hi) ++e;
        out.edges.push_back(erecs[s].lo);
        out.edges.push_back(erecs[s].hi);
        ++out.n_edges;
        s = e;
    }
    return out;
}

FluxGeometry2D build_flux_geometry2d(const double* nodes_xy, size_t /*n_nodes*/,
                                     const int64_t* tris, size_t n_tris,
                                     const int64_t* edges, size_t n_edges) {
    std::vector<EdgeRec> recs;
    recs.reserve(3 * n_tris);
    std::vector<double> cc(2 * n_tris);
    for (size_t t = 0; t < n_tris; ++t) {
        const int64_t a = tris[3 * t], b = tris[3 * t + 1], c = tris[3 * t + 2];
        const int64_t tri3[3] = {a, b, c};
        for (int e = 0; e < 3; ++e) {
            const int64_t u = tri3[e], v = tri3[(e + 1) % 3];
            recs.push_back({std::min(u, v), std::max(u, v),
                            static_cast<int64_t>(t), static_cast<int64_t>(3 * t + e)});
        }
        const Vec2 p = geom::triangle_circumcenter(node2(nodes_xy, a), node2(nodes_xy, b),
                                                   node2(nodes_xy, c));
        cc[2 * t] = p.x;
        cc[2 * t + 1] = p.y;
    }
    std::sort(recs.begin(), recs.end(), by_key_then_elem);

    FluxGeometry2D out;
    for (size_t r = 0; r < n_edges; ++r) {
        const int64_t i = edges[2 * r], j = edges[2 * r + 1];
        // lower_bound on the sorted incidence array replaces the dict lookup
        const EdgeRec probe{i, j, -1, -1};
        auto lo = std::lower_bound(recs.begin(), recs.end(), probe, by_key_then_elem);
        auto hi = lo;
        while (hi != recs.end() && hi->lo == i && hi->hi == j) ++hi;
        if (lo == recs.end() || lo->lo != i || lo->hi != j) {
            throw InvalidArgument("edge (" + std::to_string(i) + ", " + std::to_string(j) +
                                  ") is not an edge of the given triangulation");
        }
        if (hi - lo != 2) continue;  // boundary edge: no interior flux term
        const int64_t t1 = lo->elem, t2 = (lo + 1)->elem;
        const Vec2 d = {cc[2 * t1] - cc[2 * t2], cc[2 * t1 + 1] - cc[2 * t2 + 1]};
        const double dual_len = geom::norm2(d);
        const double primal_len = geom::norm2(geom::sub2(node2(nodes_xy, j), node2(nodes_xy, i)));
        out.edges.push_back(i);
        out.edges.push_back(j);
        out.trans.push_back(dual_len / primal_len);
        ++out.n;
    }
    return out;
}

void build_flux_geometry3d(const double* nodes_xyz, size_t /*n_nodes*/,
                           const int64_t* tets, size_t n_tets,
                           const int64_t* edges, size_t n_edges,
                           double* out) {
    // Per-tet circumcenters, plus the 4 face circumcenters each tet
    // needs. Precomputed rather than recomputed inside the edge loop
    // (each face is shared by 3 of the tet's 6 edges), and indexed by
    // tet, so this pass is order-independent.
    std::vector<double> tet_cc(3 * n_tets);
    std::vector<double> face_cc(12 * n_tets);
    const int nthreads = runtime::thread_count();
#if defined(TCAD_HAVE_OPENMP)
#pragma omp parallel for schedule(static) num_threads(nthreads) if (nthreads > 1)
#endif
    for (long long t = 0; t < static_cast<long long>(n_tets); ++t) {
        const int64_t* v = &tets[4 * t];
        Vec3 p[4];
        for (int k = 0; k < 4; ++k) p[k] = node3(nodes_xyz, v[k]);
        const Vec3 tc = geom::tetrahedron_circumcenter(p[0], p[1], p[2], p[3]);
        tet_cc[3 * t] = tc.x; tet_cc[3 * t + 1] = tc.y; tet_cc[3 * t + 2] = tc.z;
        for (int f = 0; f < 4; ++f) {
            const Vec3 fc = geom::triangle_circumcenter3d(
                p[FACES[f][0]], p[FACES[f][1]], p[FACES[f][2]]);
            face_cc[12 * t + 3 * f] = fc.x;
            face_cc[12 * t + 3 * f + 1] = fc.y;
            face_cc[12 * t + 3 * f + 2] = fc.z;
        }
    }

    std::vector<EdgeRec> recs;
    recs.reserve(6 * n_tets);
    for (size_t t = 0; t < n_tets; ++t) {
        const int64_t* v = &tets[4 * t];
        for (int e = 0; e < 6; ++e) {
            const int64_t u = v[EDGES[e][0]], w = v[EDGES[e][1]];
            recs.push_back({std::min(u, w), std::max(u, w),
                            static_cast<int64_t>(t), static_cast<int64_t>(6 * t + e)});
        }
    }
    std::sort(recs.begin(), recs.end(), by_key_then_elem);

    // The loop is over OUTPUT edges. `area` is thread-private and visits
    // this edge's owner tets in ascending index, so the result is
    // bit-identical at any thread count (gate G-D).
#if defined(TCAD_HAVE_OPENMP)
#pragma omp parallel for schedule(static) num_threads(nthreads) if (nthreads > 1)
#endif
    for (long long r = 0; r < static_cast<long long>(n_edges); ++r) {
        const int64_t i = edges[2 * r], j = edges[2 * r + 1];
        const Vec3 pi = node3(nodes_xyz, i), pj = node3(nodes_xyz, j);
        const Vec3 mid = {0.5 * (pi.x + pj.x), 0.5 * (pi.y + pj.y), 0.5 * (pi.z + pj.z)};
        const double primal_len = geom::norm3(geom::sub3(pj, pi));

        const EdgeRec probe{i, j, -1, -1};
        auto lo = std::lower_bound(recs.begin(), recs.end(), probe, by_key_then_elem);
        double area = 0.0;
        for (auto it = lo; it != recs.end() && it->lo == i && it->hi == j; ++it) {
            const int64_t t = it->elem;
            const int64_t* v = &tets[4 * t];
            int li = -1, lj = -1;
            for (int k = 0; k < 4; ++k) {           // np.where(verts == i)[0][0]
                if (li < 0 && v[k] == i) li = k;
                if (lj < 0 && v[k] == j) lj = k;
            }
            const int fa = PAIR_FACES[std::min(li, lj)][std::max(li, lj)][0];
            const int fb = PAIR_FACES[std::min(li, lj)][std::max(li, lj)][1];
            const Vec3 fc1 = {face_cc[12 * t + 3 * fa], face_cc[12 * t + 3 * fa + 1],
                              face_cc[12 * t + 3 * fa + 2]};
            const Vec3 fc2 = {face_cc[12 * t + 3 * fb], face_cc[12 * t + 3 * fb + 1],
                              face_cc[12 * t + 3 * fb + 2]};
            const Vec3 tc = {tet_cc[3 * t], tet_cc[3 * t + 1], tet_cc[3 * t + 2]};
            const double a1 = 0.5 * geom::norm3(
                geom::cross3(geom::sub3(fc1, mid), geom::sub3(tc, mid)));
            const double a2 = 0.5 * geom::norm3(
                geom::cross3(geom::sub3(tc, mid), geom::sub3(fc2, mid)));
            area += a1 + a2;
        }
        out[r] = primal_len > 0 ? area / primal_len : 0.0;
    }
}

FaceWeights boundary_face_node_weights3d(const double* nodes_xyz, size_t /*n_nodes*/,
                                         const int64_t* faces, size_t n_faces) {
    FaceWeights out;
    if (n_faces == 0) return out;

    // The reference accumulates into a dict face by face, vertex by
    // vertex, then emits sorted(keys). Reproduce that order exactly:
    // collect (node, contribution) in visit order, sort by node with a
    // STABLE sort so contributions stay in visit order, then sum.
    struct Contrib { int64_t node; double w; size_t seq; };
    std::vector<Contrib> cs;
    cs.reserve(3 * n_faces);
    for (size_t f = 0; f < n_faces; ++f) {
        const int64_t a = faces[3 * f], b = faces[3 * f + 1], c = faces[3 * f + 2];
        const Vec3 p0 = node3(nodes_xyz, a), p1 = node3(nodes_xyz, b), p2 = node3(nodes_xyz, c);
        const double area = 0.5 * geom::norm3(
            geom::cross3(geom::sub3(p1, p0), geom::sub3(p2, p0)));
        const double w = area / 3.0;
        cs.push_back({a, w, 3 * f});
        cs.push_back({b, w, 3 * f + 1});
        cs.push_back({c, w, 3 * f + 2});
    }
    std::sort(cs.begin(), cs.end(), [](const Contrib& x, const Contrib& y) {
        if (x.node != y.node) return x.node < y.node;
        return x.seq < y.seq;
    });
    for (size_t s = 0; s < cs.size();) {
        size_t e = s;
        double acc = 0.0;
        while (e < cs.size() && cs[e].node == cs[s].node) {
            acc += cs[e].w;
            ++e;
        }
        out.node_idx.push_back(cs[s].node);
        out.weights.push_back(acc);
        s = e;
    }
    return out;
}

}  // namespace tcad::mesh
