// Unstructured-mesh geometry precompute: the unique edge list, dual-cell
// measures, and TPFA edge-flux factors.
//
// This is the measured bottleneck the whole C++ effort was sequenced
// around.  The Python reference builds its edge/face maps with
// dictionaries keyed by (i, j) tuples and a Python-level loop over every
// element, which profiles at ~80k triangles/s in 2D and ~3.5k tets/s in
// 3D -- so a 1M-tet mesh spends about five minutes in dict operations
// before any physics runs.
//
// The replacement is the standard one: emit one record per
// (element, local edge), sort, and group.  Sorting by
// (lo, hi, element) leaves each edge's owners in ascending element
// order, which is exactly the order the Python `setdefault(...).append`
// produces -- and that order is load-bearing, because the 3D flux
// kernel accumulates `area += a1 + a2` over owners and float addition
// is not associative.
//
// Bit-identity, not tolerance: see geom/simplex.hpp for the measured
// list of numpy primitives these kernels reproduce exactly.
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::mesh {

/// (edge_list, node_areas) from build_unstructured_stencil.
struct Stencil2D {
    std::vector<int64_t> edges;       ///< 2*n_edges, row-major (i, j), i < j
    std::vector<double> node_areas;   ///< n_nodes
    size_t n_edges = 0;
};

/// (edge_list, node_volumes) from build_unstructured_stencil3d.
struct Stencil3D {
    std::vector<int64_t> edges;       ///< 2*n_edges, row-major (i, j), i < j
    std::vector<double> node_vol;     ///< n_nodes
    size_t n_edges = 0;
};

/// (interior_edges, trans) from build_edge_flux_geometry (2D).
struct FluxGeometry2D {
    std::vector<int64_t> edges;       ///< 2*n, a SUBSET of the input edge list
    std::vector<double> trans;        ///< n
    size_t n = 0;
};

/// (node_idx, weights) from boundary_face_node_weights3d.
struct FaceWeights {
    std::vector<int64_t> node_idx;    ///< sorted unique
    std::vector<double> weights;
};

/// Throws tcad::DegenerateMesh with the reference message on a
/// degenerate triangle or a non-manifold edge.
Stencil2D build_stencil2d(const double* nodes_xy, size_t n_nodes,
                          const int64_t* tris, size_t n_tris,
                          double min_area);

/// Throws tcad::DegenerateMesh on a degenerate tet or non-manifold face.
Stencil3D build_stencil3d(const double* nodes_xyz, size_t n_nodes,
                          const int64_t* tets, size_t n_tets,
                          double min_volume);

FluxGeometry2D build_flux_geometry2d(const double* nodes_xy, size_t n_nodes,
                                     const int64_t* tris, size_t n_tris,
                                     const int64_t* edges, size_t n_edges);

/// Writes n_edges factors into `out`. Parallel-safe and bit-identical
/// across thread counts: the loop is over OUTPUT edges, each with a
/// thread-private accumulator visiting its owner tets in ascending index.
void build_flux_geometry3d(const double* nodes_xyz, size_t n_nodes,
                           const int64_t* tets, size_t n_tets,
                           const int64_t* edges, size_t n_edges,
                           double* out);

FaceWeights boundary_face_node_weights3d(const double* nodes_xyz, size_t n_nodes,
                                         const int64_t* faces, size_t n_faces);

}  // namespace tcad::mesh
