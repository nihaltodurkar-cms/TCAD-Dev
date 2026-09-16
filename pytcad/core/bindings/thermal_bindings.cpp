// Bindings for the M43 structured-grid self-heating assembly.
//
// Same D=2-or-3-generic pattern as nonlocal_bindings.cpp's trace_paths:
// rather than a Python list of per-axis arrays (which nanobind has no
// direct ndarray-of-ndarrays support for), every per-axis array is
// CONCATENATED into one flat buffer, with `shape` (length D) telling
// this binding where each axis's slice starts and ends.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/thermal/kernels.hpp"

namespace nb = nanobind;

namespace {

using F64 = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using I64 = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig>;

template <typename T>
nb::ndarray<nb::numpy, T> publish(std::vector<T>&& v) {
    auto* held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
    return nb::ndarray<nb::numpy, T>(held->data(), {held->size()}, owner);
}

/// Slice a concatenated per-axis buffer into D raw pointers, given each
/// axis's length. `lens[a]` is the length of axis a's own slice.
std::array<const double*, 3> split_axes(const double* concat, const std::int64_t* lens, int D) {
    std::array<const double*, 3> out{nullptr, nullptr, nullptr};
    std::int64_t offset = 0;
    for (int a = 0; a < D; ++a) {
        out[static_cast<std::size_t>(a)] = concat + offset;
        offset += lens[a];
    }
    return out;
}

}  // namespace

void register_thermal(nb::module_& m) {
    m.def("thermal_grid_residual_jacobian",
          [](I64 shape, F64 T, F64 H, double T_ambient,
             F64 dV_concat, F64 h_concat, F64 ke_concat, F64 dke_concat,
             I64 bc_kind, F64 bc_rth) {
              const int D = static_cast<int>(shape.shape(0));
              if (D != 2 && D != 3)
                  throw tcad::InvalidArgument("shape: expected 2 or 3 axes, got " +
                                              std::to_string(D));
              std::int64_t total = 1;
              std::array<std::int64_t, 3> dims{};
              std::array<std::int64_t, 3> node_lens{};   // shape[a]
              std::array<std::int64_t, 3> edge_lens{};   // shape[a]-1
              std::array<std::int64_t, 3> edge_totals{}; // total/shape[a]*(shape[a]-1)
              for (int a = 0; a < D; ++a) {
                  dims[static_cast<std::size_t>(a)] = shape.data()[a];
                  total *= shape.data()[a];
              }
              for (int a = 0; a < D; ++a) {
                  node_lens[static_cast<std::size_t>(a)] = dims[static_cast<std::size_t>(a)];
                  edge_lens[static_cast<std::size_t>(a)] = dims[static_cast<std::size_t>(a)] - 1;
                  edge_totals[static_cast<std::size_t>(a)] =
                      total / dims[static_cast<std::size_t>(a)] *
                      (dims[static_cast<std::size_t>(a)] - 1);
              }
              if (static_cast<std::int64_t>(T.shape(0)) != total)
                  throw tcad::InvalidArgument("T: expected " + std::to_string(total) +
                                              " nodes, got " + std::to_string(T.shape(0)));
              if (static_cast<std::int64_t>(H.shape(0)) != total)
                  throw tcad::InvalidArgument("H: expected " + std::to_string(total) + " nodes");
              if (static_cast<std::int64_t>(bc_kind.shape(0)) != 2 * D ||
                  static_cast<std::int64_t>(bc_rth.shape(0)) != 2 * D)
                  throw tcad::InvalidArgument("bc_kind/bc_rth: expected 2*D entries");

              auto dV_ptrs = split_axes(dV_concat.data(), node_lens.data(), D);
              auto h_ptrs = split_axes(h_concat.data(), edge_lens.data(), D);
              auto ke_ptrs = split_axes(ke_concat.data(), edge_totals.data(), D);
              auto dke_ptrs = split_axes(dke_concat.data(), edge_totals.data(), D);

              std::array<tcad::thermal::BC, 6> bcs{};
              for (int i = 0; i < 2 * D; ++i)
                  bcs[static_cast<std::size_t>(i)] = {
                      static_cast<int>(bc_kind.data()[i]), bc_rth.data()[i]};

              tcad::thermal::GridResult r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::thermal::residual_jacobian_grid(
                      D, dims.data(), T.data(), H.data(), T_ambient,
                      dV_ptrs.data(), h_ptrs.data(), ke_ptrs.data(), dke_ptrs.data(),
                      bcs.data());
              }
              const size_t nnz = r.vals.size();
              return nb::make_tuple(
                  publish(std::move(r.F)),
                  publish(std::move(r.rows)),
                  publish(std::move(r.cols)),
                  publish(std::move(r.vals)));
          },
          nb::arg("shape"), nb::arg("T"), nb::arg("H"), nb::arg("T_ambient"),
          nb::arg("dV_concat"), nb::arg("h_concat"), nb::arg("ke_concat"),
          nb::arg("dke_concat"), nb::arg("bc_kind"), nb::arg("bc_rth"),
          "M43's structured-grid (D=2 or 3) thermal residual/Jacobian "
          "assembly. Per-axis arrays are concatenated in axis order; "
          "`shape` says where each axis's slice starts. Returns "
          "(F, rows, cols, vals) -- the caller builds the scipy sparse "
          "matrix from the COO triples itself, exactly as the pure-Python "
          "oracle does, so duplicate-summing is scipy's own code either way.");
}
