// Scalar simplex geometry, written to be BIT-IDENTICAL to the numpy
// reference in pytcad/unstructured_assembly{,3d}.py.
//
// Every operation below reproduces its numpy counterpart's exact
// association order.  That is not a stylistic choice: the parity gate
// (tests/test_accel_parity.py) compares the compiled path against the
// Python oracle with np.array_equal, not a tolerance.
//
// The reproducibility was MEASURED, not assumed, before this file was
// written (numpy 2.4 / OpenBLAS, 20k-40k random device-scale inputs
// each, all exact):
//
//   np.linalg.norm(v3)              == sqrt(x*x + y*y + z*z)
//   np.linalg.norm(v2)              == sqrt(x*x + y*y)
//   np.sum(d**2)   (2 elts)         == a*a + b*b
//   np.sum(d)      (3 elts)         == (a + b) + c        left to right
//   np.dot(u3, v3)                  == (ux*vx + uy*vy) + uz*vz
//   np.cross(u3, v3)                == the scalar formula below
//
// i.e. numpy does NOT dispatch these to a BLAS kernel at these sizes,
// so plain scalar C++ matches it exactly.  If a future numpy starts
// vectorizing them differently, the parity gate fails loudly rather
// than drifting silently -- which is the point of gating on equality.
#pragma once

#include <cmath>

namespace tcad::geom {

struct Vec2 { double x, y; };
struct Vec3 { double x, y, z; };

inline Vec2 sub2(const Vec2& a, const Vec2& b) { return {a.x - b.x, a.y - b.y}; }
inline Vec3 sub3(const Vec3& a, const Vec3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }

/// np.linalg.norm on a length-2 vector.
inline double norm2(const Vec2& v) { return std::sqrt(v.x * v.x + v.y * v.y); }

/// np.linalg.norm on a length-3 vector.
inline double norm3(const Vec3& v) { return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z); }

/// np.sum(v ** 2) for a length-2 vector.
inline double sqnorm2(const Vec2& v) { return v.x * v.x + v.y * v.y; }

/// np.cross for two length-3 vectors.
inline Vec3 cross3(const Vec3& a, const Vec3& b) {
    return {a.y * b.z - a.z * b.y,
            a.z * b.x - a.x * b.z,
            a.x * b.y - a.y * b.x};
}

/// np.dot for two length-3 vectors: numpy sums left to right.
inline double dot3(const Vec3& a, const Vec3& b) {
    return (a.x * b.x + a.y * b.y) + a.z * b.z;
}

/// _triangle_area2: twice the SIGNED area, xy only.
inline double triangle_area2(const Vec2& p0, const Vec2& p1, const Vec2& p2) {
    return (p1.x - p0.x) * (p2.y - p0.y) - (p2.x - p0.x) * (p1.y - p0.y);
}

/// _cot: cot of the angle at p_apex subtended by rays to p_a and p_b.
///
/// |cross|, not cross: the undirected angle between two rays is in
/// (0, pi), so its sine is positive and the sign of the cotangent comes
/// from the dot product alone. The signed form made the dual areas in
/// stencil.cpp winding-sensitive (M31 P2b). fabs() on a positive value
/// is exact, so counter-clockwise input -- which is everything gmsh
/// emits, and everything the goldens contain -- is bit-identical.
inline double cot(const Vec2& apex, const Vec2& a, const Vec2& b) {
    const Vec2 v1 = sub2(a, apex);
    const Vec2 v2 = sub2(b, apex);
    const double cross = v1.x * v2.y - v1.y * v2.x;
    const double dot = v1.x * v2.x + v1.y * v2.y;
    return dot / std::fabs(cross);
}

/// _tet_volume: SIGNED volume (the caller takes abs, as Python does).
inline double tet_volume(const Vec3& p0, const Vec3& p1, const Vec3& p2, const Vec3& p3) {
    return dot3(sub3(p1, p0), cross3(sub3(p2, p0), sub3(p3, p0))) / 6.0;
}

/// triangle_circumcenter (2D determinant form).
inline Vec2 triangle_circumcenter(const Vec2& A, const Vec2& B, const Vec2& C) {
    const double D = 2.0 * (A.x * (B.y - C.y) + B.x * (C.y - A.y) + C.x * (A.y - B.y));
    const double a2 = A.x * A.x + A.y * A.y;
    const double b2 = B.x * B.x + B.y * B.y;
    const double c2 = C.x * C.x + C.y * C.y;
    return {(a2 * (B.y - C.y) + b2 * (C.y - A.y) + c2 * (A.y - B.y)) / D,
            (a2 * (C.x - B.x) + b2 * (A.x - C.x) + c2 * (B.x - A.x)) / D};
}

/// triangle_circumcenter3d (barycentric form, valid off the xy-plane).
inline Vec3 triangle_circumcenter3d(const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 ac = sub3(c, a);
    const Vec3 ab = sub3(b, a);
    const Vec3 abXac = cross3(ab, ac);
    const double denom = 2.0 * dot3(abXac, abXac);
    if (std::fabs(denom) < 1e-300) {
        // degenerate fallback: centroid, matching (a + b + c) / 3.0
        return {(a.x + b.x + c.x) / 3.0,
                (a.y + b.y + c.y) / 3.0,
                (a.z + b.z + c.z) / 3.0};
    }
    // np.cross(abXac, ab) * np.dot(ac, ac) + np.cross(ac, abXac) * np.dot(ab, ab)
    const Vec3 t1 = cross3(abXac, ab);
    const Vec3 t2 = cross3(ac, abXac);
    const double d_ac = dot3(ac, ac);
    const double d_ab = dot3(ab, ab);
    const Vec3 to_c = {(t1.x * d_ac + t2.x * d_ab) / denom,
                       (t1.y * d_ac + t2.y * d_ab) / denom,
                       (t1.z * d_ac + t2.z * d_ab) / denom};
    return {a.x + to_c.x, a.y + to_c.y, a.z + to_c.z};
}

/// _solve3: 3x3 Cramer in the SAME fixed order as the Python reference.
/// Returns false on an exactly singular system (caller falls back to the
/// centroid, as Python does on LinAlgError).
///
/// Deliberately not an LU: the Python side stopped using np.linalg.solve
/// for exactly this reason -- LAPACK dgesv's result depends on the BLAS
/// build, and a measured attempt to replicate an unblocked dgetf2
/// matched numpy on only 72.6% of random 3x3 systems.
inline bool solve3(const double a[3][3], const double b[3], double out[3]) {
    const double c00 = a[1][1] * a[2][2] - a[1][2] * a[2][1];
    const double c01 = a[1][2] * a[2][0] - a[1][0] * a[2][2];
    const double c02 = a[1][0] * a[2][1] - a[1][1] * a[2][0];
    const double det = a[0][0] * c00 + a[0][1] * c01 + a[0][2] * c02;
    if (det == 0.0) return false;
    const double c10 = a[0][2] * a[2][1] - a[0][1] * a[2][2];
    const double c11 = a[0][0] * a[2][2] - a[0][2] * a[2][0];
    const double c12 = a[0][1] * a[2][0] - a[0][0] * a[2][1];
    const double c20 = a[0][1] * a[1][2] - a[0][2] * a[1][1];
    const double c21 = a[0][2] * a[1][0] - a[0][0] * a[1][2];
    const double c22 = a[0][0] * a[1][1] - a[0][1] * a[1][0];
    const double r = 1.0 / det;
    out[0] = (c00 * b[0] + c10 * b[1] + c20 * b[2]) * r;
    out[1] = (c01 * b[0] + c11 * b[1] + c21 * b[2]) * r;
    out[2] = (c02 * b[0] + c12 * b[1] + c22 * b[2]) * r;
    return true;
}

/// tetrahedron_circumcenter: the point equidistant from all 4 vertices.
inline Vec3 tetrahedron_circumcenter(const Vec3& p0, const Vec3& p1,
                                     const Vec3& p2, const Vec3& p3) {
    const double a[3][3] = {{p1.x - p0.x, p1.y - p0.y, p1.z - p0.z},
                            {p2.x - p0.x, p2.y - p0.y, p2.z - p0.z},
                            {p3.x - p0.x, p3.y - p0.y, p3.z - p0.z}};
    // 0.5 * np.sum(pts[1:]**2 - pts[0]**2, axis=1), summed left to right
    const double b[3] = {
        0.5 * (((p1.x * p1.x - p0.x * p0.x) + (p1.y * p1.y - p0.y * p0.y))
               + (p1.z * p1.z - p0.z * p0.z)),
        0.5 * (((p2.x * p2.x - p0.x * p0.x) + (p2.y * p2.y - p0.y * p0.y))
               + (p2.z * p2.z - p0.z * p0.z)),
        0.5 * (((p3.x * p3.x - p0.x * p0.x) + (p3.y * p3.y - p0.y * p0.y))
               + (p3.z * p3.z - p0.z * p0.z))};
    double sol[3];
    if (!solve3(a, b, sol)) {
        // degenerate fallback: pts.mean(axis=0), i.e. numpy's pairwise
        // sum over 4 elements, which for n=4 is ((a+b)+(c+d)).
        return {((p0.x + p1.x) + (p2.x + p3.x)) / 4.0,
                ((p0.y + p1.y) + (p2.y + p3.y)) / 4.0,
                ((p0.z + p1.z) + (p2.z + p3.z)) / 4.0};
    }
    return {sol[0], sol[1], sol[2]};
}

}  // namespace tcad::geom
