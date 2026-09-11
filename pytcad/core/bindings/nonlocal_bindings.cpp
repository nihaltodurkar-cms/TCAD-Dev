// Bindings for the nonlocal-BTBT path tracer (M34-S4).
//
// Same ownership discipline as process_bindings.cpp: inputs are borrowed
// read-only and never retained; outputs are fresh allocations published
// through an nb::capsule only after the kernel returns normally.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/nonlocal/paths.hpp"

namespace nb = nanobind;

namespace {

using F64 = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using F64_2 = nb::ndarray<const double, nb::ndim<2>, nb::c_contig>;
using I64 = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig>;
using B1 = nb::ndarray<const bool, nb::ndim<1>, nb::c_contig>;

template <typename T>
nb::ndarray<nb::numpy, T> publish(std::vector<T>&& v) {
    auto* held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
    return nb::ndarray<nb::numpy, T>(held->data(), {held->size()}, owner);
}

}  // namespace

void register_nonlocal(nb::module_& m) {
    m.def("trace_paths",
          [](F64 coords, I64 shape, F64 psi, F64_2 grads, I64 cand, B1 contact,
             double VT, double Eg_eV, double screen_Vcm, double margin,
             std::int64_t max_steps, double hmin_all) {
              const int d = static_cast<int>(shape.shape(0));
              if (d != 2 && d != 3)
                  throw tcad::InvalidArgument("shape: expected 2 or 3 axes, got " +
                                              std::to_string(d));
              std::int64_t n = 1, ncoord = 0;
              for (int a = 0; a < d; ++a) {
                  n *= shape.data()[a];
                  ncoord += shape.data()[a];
              }
              if (static_cast<std::int64_t>(coords.shape(0)) != ncoord)
                  throw tcad::InvalidArgument("coords: expected the concatenated axes (" +
                                              std::to_string(ncoord) + " values)");
              if (static_cast<std::int64_t>(psi.shape(0)) != n)
                  throw tcad::InvalidArgument("psi: expected " + std::to_string(n) + " nodes");
              if (static_cast<int>(grads.shape(0)) != d ||
                  static_cast<std::int64_t>(grads.shape(1)) != n)
                  throw tcad::InvalidArgument("grads: expected a (d, n_nodes) array");
              if (static_cast<std::int64_t>(contact.shape(0)) != n)
                  throw tcad::InvalidArgument("contact: expected " + std::to_string(n) +
                                              " nodes");
              tcad::nonlocal::TraceResult r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::nonlocal::trace_paths(
                      coords.data(), shape.data(), d, psi.data(), grads.data(), n,
                      cand.data(), static_cast<std::int64_t>(cand.shape(0)),
                      contact.data(), VT, Eg_eV, screen_Vcm, margin, max_steps,
                      hmin_all);
              }
              return nb::make_tuple(publish(std::move(r.starts)),
                                    publish(std::move(r.offset)),
                                    publish(std::move(r.sidx)),
                                    publish(std::move(r.swts)),
                                    publish(std::move(r.seg_len)),
                                    publish(std::move(r.gidx)),
                                    publish(std::move(r.gwts)));
          },
          nb::arg("coords"), nb::arg("shape"), nb::arg("psi"), nb::arg("grads"),
          nb::arg("cand"), nb::arg("contact"), nb::arg("VT"), nb::arg("Eg_eV"),
          nb::arg("screen_Vcm"), nb::arg("margin"), nb::arg("max_steps"),
          nb::arg("hmin_all"),
          "nonlocal_path._trace_paths_py, compiled: the per-path stepping loop "
          "of build_structured. Returns (starts, offset, sidx, swts, seg_len, "
          "gidx, gwts) as flat arrays; the gradient and candidate list come "
          "from numpy.");
}
