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
#include "tcad/nonlocal/segments.hpp"
#include "tcad/nonlocal/evaluate.hpp"
#include "tcad/base/checks.hpp"

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

    m.def("segment_integrals",
          [](F64 da, F64 db, F64 L, double u, double Eg_J, double mr_kg, double hbar) {
              const std::size_t n = da.shape(0);
              if (db.shape(0) != n || L.shape(0) != n)
                  throw tcad::InvalidArgument("da, db, L: expected equal lengths, got " +
                                              std::to_string(n) + ", " +
                                              std::to_string(db.shape(0)) + ", " +
                                              std::to_string(L.shape(0)));
              if (!(u > 1.0))
                  throw tcad::InvalidArgument(
                      "eq (9) needs u = m0/(2 mr) > 1 (mr < m0/2) for kappa to vanish "
                      "at both band edges");
              std::vector<double> Ik(n), Iik(n), dIk_da(n), dIk_db(n), dIik_da(n), dIik_db(n);
              {
                  nb::gil_scoped_release nogil;
                  tcad::nonlocal::segment_integrals(
                      da.data(), db.data(), L.data(), static_cast<std::int64_t>(n), u, Eg_J,
                      mr_kg, hbar, Ik.data(), Iik.data(), dIk_da.data(), dIk_db.data(),
                      dIik_da.data(), dIik_db.data());
              }
              return nb::make_tuple(publish(std::move(Ik)), publish(std::move(Iik)),
                                    publish(std::move(dIk_da)), publish(std::move(dIk_db)),
                                    publish(std::move(dIik_da)), publish(std::move(dIik_db)));
          },
          nb::arg("da"), nb::arg("db"), nb::arg("L"), nb::arg("u"), nb::arg("Eg_J"),
          nb::arg("mr_kg"), nb::arg("hbar"),
          "btbt.segment_integrals, compiled and fused: returns (Ik, Iik, "
          "dIk_da, dIk_db, dIik_da, dIik_db), bit-identical to the Python "
          "reference.");

    m.def("evaluate_paths",
          [](F64 psi, I64 start, I64 offset, F64_2 swts, nb::ndarray<const std::int64_t, nb::ndim<2>, nb::c_contig> sidx,
             F64 seg_len, F64_2 gwts, nb::ndarray<const std::int64_t, nb::ndim<2>, nb::c_contig> gidx,
             double VT, double Eg_J, double mr_kg, double mc_kg, double mv_kg, double u,
             double hbar, double q) {
              const auto N = static_cast<std::int64_t>(psi.shape(0));
              const auto P = static_cast<std::int64_t>(start.shape(0));
              const auto S = static_cast<std::int64_t>(sidx.shape(0));
              const auto K = static_cast<std::int64_t>(sidx.shape(1));
              const auto Kg = static_cast<std::int64_t>(gidx.shape(1));
              if (P < 1) throw tcad::InvalidArgument("evaluate_paths: no paths");
              if (!(u > 1.0))
                  throw tcad::InvalidArgument("eq (9) needs u = m0/(2 mr) > 1 (mr < m0/2)");
              tcad::check_length(static_cast<std::int64_t>(offset.shape(0)), P + 1, "offset");
              tcad::check_length(static_cast<std::int64_t>(swts.shape(0)), S, "swts rows");
              tcad::check_length(static_cast<std::int64_t>(swts.shape(1)), K, "swts cols");
              tcad::check_length(static_cast<std::int64_t>(seg_len.shape(0)), S, "seg_len");
              tcad::check_length(static_cast<std::int64_t>(gidx.shape(0)), P, "gidx rows");
              tcad::check_length(static_cast<std::int64_t>(gwts.shape(0)), P, "gwts rows");
              tcad::check_length(static_cast<std::int64_t>(gwts.shape(1)), Kg, "gwts cols");
              const std::int64_t* off = offset.data();
              if (off[0] != 0 || off[P] != S)
                  throw tcad::InvalidArgument("offset must run from 0 to the sample count");
              for (std::int64_t p = 0; p < P; ++p)
                  if (off[p + 1] - off[p] < 2)
                      throw tcad::InvalidArgument("every path needs at least 2 samples");
              tcad::check_indices(start.data(), P, N, "start");
              tcad::check_indices(sidx.data(), S * K, N, "sidx");
              tcad::check_indices(gidx.data(), P * Kg, N, "gidx");
              tcad::nonlocal::EvalResult r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::nonlocal::evaluate_paths(
                      psi.data(), N, start.data(), off, P, sidx.data(), swts.data(), S, K,
                      seg_len.data(), gidx.data(), gwts.data(), Kg, VT, Eg_J, mr_kg, mc_kg,
                      mv_kg, u, hbar, q);
              }
              return nb::make_tuple(
                  publish(std::move(r.G)), publish(std::move(r.Ik)), publish(std::move(r.Iik)),
                  publish(std::move(r.reached)), publish(std::move(r.length)),
                  publish(std::move(r.fmin)), publish(std::move(r.fmax)),
                  publish(std::move(r.dG_rows)), publish(std::move(r.dG_cols)),
                  publish(std::move(r.dG_vals)), publish(std::move(r.dep_rows)),
                  publish(std::move(r.dep_cols)), publish(std::move(r.dep_vals)),
                  publish(std::move(r.ddep_p)), publish(std::move(r.ddep_node)),
                  publish(std::move(r.ddep_col)), publish(std::move(r.ddep_val)));
          },
          "nonlocal_path._evaluate_py, compiled up to the COO triplets (scipy "
          "builds the CSR matrices). Bit-identical to the Python oracle.");
}
