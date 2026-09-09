// Bindings for the unstructured-mesh geometry kernels.
//
// Ownership discipline, applied uniformly below:
//   * inputs are borrowed, read-only, and never retained past the call;
//   * every output is a FRESH allocation handed to numpy through an
//     nb::capsule, so nothing returned aliases an input and no
//     keep_alive relationship is needed anywhere;
//   * the result vectors are only published AFTER the kernel returns
//     normally -- on a throw the std::vector dies and no Python object
//     was ever created. That is the "a failed call never returns
//     half-state" rule made structural rather than disciplinary.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <utility>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/mesh/stencil.hpp"

namespace nb = nanobind;

namespace {

// Exact dtype + contiguity + shape in the signature means nanobind
// BINDS the caller's buffer or raises. There is no silent-conversion
// path (pybind11's forcecast would memcpy ~100 MB on a 1M-tet mesh --
// precisely the copy this work exists to remove).
using NodesF = nb::ndarray<const double, nb::c_contig>;
using IdxF = nb::ndarray<const int64_t, nb::c_contig>;

/// Move a std::vector onto the heap and hand numpy a view of it that
/// owns it. One allocation, one capsule, one deleter.
template <typename T>
nb::ndarray<nb::numpy, T> publish(std::vector<T>&& v, std::initializer_list<size_t> shape) {
    auto* held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
    return nb::ndarray<nb::numpy, T>(held->data(), shape, owner);
}

void check_2d(const NodesF& a, size_t cols, const char* what) {
    if (a.ndim() != 2 || a.shape(1) != cols)
        throw tcad::InvalidArgument(std::string(what) + ": expected an (n, " +
                                    std::to_string(cols) + ") array");
}
void check_2d_i(const IdxF& a, size_t cols, const char* what) {
    if (a.ndim() != 2 || a.shape(1) != cols)
        throw tcad::InvalidArgument(std::string(what) + ": expected an (n, " +
                                    std::to_string(cols) + ") int64 array");
}

}  // namespace

void register_mesh(nb::module_& m) {
    m.def("build_stencil2d",
          [](NodesF nodes, IdxF tris, double min_area) {
              check_2d(nodes, 3, "nodes");
              check_2d_i(tris, 3, "triangles");
              tcad::mesh::Stencil2D r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::mesh::build_stencil2d(nodes.data(), nodes.shape(0),
                                                  tris.data(), tris.shape(0), min_area);
              }
              const size_t ne = r.n_edges, nn = r.node_areas.size();
              return nb::make_tuple(publish(std::move(r.edges), {ne, size_t(2)}),
                                    publish(std::move(r.node_areas), {nn}));
          },
          nb::arg("nodes"), nb::arg("triangles"), nb::arg("min_area"));

    m.def("build_stencil3d",
          [](NodesF nodes, IdxF tets, double min_volume) {
              check_2d(nodes, 3, "nodes");
              check_2d_i(tets, 4, "tets");
              tcad::mesh::Stencil3D r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::mesh::build_stencil3d(nodes.data(), nodes.shape(0),
                                                  tets.data(), tets.shape(0), min_volume);
              }
              const size_t ne = r.n_edges, nn = r.node_vol.size();
              return nb::make_tuple(publish(std::move(r.edges), {ne, size_t(2)}),
                                    publish(std::move(r.node_vol), {nn}));
          },
          nb::arg("nodes"), nb::arg("tets"), nb::arg("min_volume"));

    m.def("build_flux_geometry2d",
          [](NodesF nodes, IdxF tris, IdxF edges) {
              check_2d(nodes, 3, "nodes");
              check_2d_i(tris, 3, "triangles");
              check_2d_i(edges, 2, "edge_list");
              tcad::mesh::FluxGeometry2D r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::mesh::build_flux_geometry2d(nodes.data(), nodes.shape(0),
                                                        tris.data(), tris.shape(0),
                                                        edges.data(), edges.shape(0));
              }
              const size_t n = r.n;
              return nb::make_tuple(publish(std::move(r.edges), {n, size_t(2)}),
                                    publish(std::move(r.trans), {n}));
          },
          nb::arg("nodes"), nb::arg("triangles"), nb::arg("edge_list"));

    m.def("build_flux_geometry3d",
          [](NodesF nodes, IdxF tets, IdxF edges) {
              check_2d(nodes, 3, "nodes");
              check_2d_i(tets, 4, "tets");
              check_2d_i(edges, 2, "edge_list");
              const size_t ne = edges.shape(0);
              std::vector<double> trans(ne);
              {
                  nb::gil_scoped_release nogil;
                  tcad::mesh::build_flux_geometry3d(nodes.data(), nodes.shape(0),
                                                    tets.data(), tets.shape(0),
                                                    edges.data(), ne, trans.data());
              }
              return publish(std::move(trans), {ne});
          },
          nb::arg("nodes"), nb::arg("tets"), nb::arg("edge_list"));

    m.def("boundary_face_node_weights3d",
          [](NodesF nodes, IdxF faces) {
              check_2d(nodes, 3, "nodes");
              check_2d_i(faces, 3, "faces");
              tcad::mesh::FaceWeights r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::mesh::boundary_face_node_weights3d(
                      nodes.data(), nodes.shape(0), faces.data(), faces.shape(0));
              }
              const size_t n = r.node_idx.size();
              return nb::make_tuple(publish(std::move(r.node_idx), {n}),
                                    publish(std::move(r.weights), {n}));
          },
          nb::arg("nodes"), nb::arg("faces"));
}
