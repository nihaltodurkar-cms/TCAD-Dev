// Bindings for M42-S3's density-gradient Lambda-row assembly.
//
// Same D=2-or-3-generic concatenation pattern as nonlocal_bindings.cpp/
// thermal_bindings.cpp: nanobind has no direct binding for a Python
// list of ndarrays, so every per-axis array is CONCATENATED into one
// flat buffer, with `n_edges` (length n_axes) telling this binding
// where each axis's edge-indexed slice starts, and dV_phys concatenated
// in fixed N-sized chunks (one per axis).
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/dg/kernels.hpp"

namespace nb = nanobind;

namespace {

using F64 = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using I64 = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig>;
using U8 = nb::ndarray<const std::uint8_t, nb::ndim<1>, nb::c_contig>;

template <typename T>
nb::ndarray<nb::numpy, T> publish(std::vector<T>&& v) {
    auto* held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
    return nb::ndarray<nb::numpy, T>(held->data(), {held->size()}, owner);
}

}  // namespace

void register_dg(nb::module_& m) {
    m.def("dg_grid_lambda_rows",
          [](std::int64_t N, I64 n_edges,
             I64 kL_concat, I64 kR_concat, F64 h_phys_concat, F64 dV_phys_concat,
             F64 gn, F64 gp, F64 Lam_n, F64 Lam_p, F64 pref_n, F64 pref_p,
             U8 gate_mask, double VT) {
              const int n_axes = static_cast<int>(n_edges.shape(0));
              if (n_axes != 2 && n_axes != 3)
                  throw tcad::InvalidArgument("n_edges: expected 2 or 3 axes, got " +
                                              std::to_string(n_axes));
              if (static_cast<std::int64_t>(gn.shape(0)) != N ||
                  static_cast<std::int64_t>(gp.shape(0)) != N ||
                  static_cast<std::int64_t>(Lam_n.shape(0)) != N ||
                  static_cast<std::int64_t>(Lam_p.shape(0)) != N ||
                  static_cast<std::int64_t>(pref_n.shape(0)) != N ||
                  static_cast<std::int64_t>(pref_p.shape(0)) != N ||
                  static_cast<std::int64_t>(gate_mask.shape(0)) != N)
                  throw tcad::InvalidArgument("gn/gp/Lam_n/Lam_p/pref_n/pref_p/gate_mask: "
                                              "expected N entries each");

              std::vector<tcad::dg::Axis> axes(static_cast<std::size_t>(n_axes));
              std::int64_t edge_off = 0, node_off = 0;
              std::int64_t total_edges = 0;
              for (int a = 0; a < n_axes; ++a) total_edges += n_edges.data()[a];
              if (static_cast<std::int64_t>(kL_concat.shape(0)) != total_edges ||
                  static_cast<std::int64_t>(kR_concat.shape(0)) != total_edges ||
                  static_cast<std::int64_t>(h_phys_concat.shape(0)) != total_edges)
                  throw tcad::InvalidArgument("kL/kR/h_phys: total length must match sum(n_edges)");
              if (static_cast<std::int64_t>(dV_phys_concat.shape(0)) != n_axes * N)
                  throw tcad::InvalidArgument("dV_phys: expected n_axes*N entries");

              for (int a = 0; a < n_axes; ++a) {
                  const std::int64_t ne = n_edges.data()[a];
                  axes[static_cast<std::size_t>(a)] = tcad::dg::Axis{
                      ne,
                      kL_concat.data() + edge_off,
                      kR_concat.data() + edge_off,
                      h_phys_concat.data() + edge_off,
                      dV_phys_concat.data() + node_off,
                  };
                  edge_off += ne;
                  node_off += N;
              }

              tcad::dg::GridResult r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::dg::lambda_rows(
                      N, n_axes, axes.data(), gn.data(), gp.data(),
                      Lam_n.data(), Lam_p.data(), pref_n.data(), pref_p.data(),
                      gate_mask.data(), VT);
              }
              return nb::make_tuple(
                  publish(std::move(r.Fn)),
                  publish(std::move(r.Fp)),
                  publish(std::move(r.rows)),
                  publish(std::move(r.cols)),
                  publish(std::move(r.vals)));
          },
          nb::arg("N"), nb::arg("n_edges"), nb::arg("kL_concat"), nb::arg("kR_concat"),
          nb::arg("h_phys_concat"), nb::arg("dV_phys_concat"),
          nb::arg("gn"), nb::arg("gp"), nb::arg("Lam_n"), nb::arg("Lam_p"),
          nb::arg("pref_n"), nb::arg("pref_p"), nb::arg("gate_mask"), nb::arg("VT"),
          "M42-S3's structured-grid (2 or 3 axes) density-gradient "
          "Lambda_n/Lambda_p residual/Jacobian assembly. Per-axis edge "
          "arrays are concatenated in axis order (n_edges says where "
          "each axis's slice starts); dV_phys is concatenated in fixed "
          "N-sized per-axis chunks. Returns (Fn, Fp, rows, cols, vals) "
          "-- the caller builds the scipy sparse matrix itself.");
}
