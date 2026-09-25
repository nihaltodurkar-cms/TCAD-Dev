// Bindings for M47 Slice 2a's structured-grid (Device3D) base Jacobian
// assembly (core/src/device3d/kernels.cpp). 4 separate bound functions,
// one per block -- these are called from 4 distinct points inside
// device3d.py's `_residual_jacobian` (with unrelated Python code, the
// derivative-array computation, in between each), unlike M47 Slice 1's
// coupled kernel which had one natural single-call orchestration point.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <string>
#include <span>
#include <vector>

#include "tcad/base/checks.hpp"
#include "tcad/base/errors.hpp"
#include "tcad/device3d/kernels.hpp"
#include "tcad/device3d/poisson_eq.hpp"

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

/// Zero-copy read-only view of a bound 1-D array. Replaces the former
/// `to_vec`, which copied every input into a fresh std::vector per call.
/// The nanobind ndarray argument owns the buffer for the whole call; a
/// kernel must not keep the span past its own return.
template <typename T, typename Nd>
std::span<const T> as_span(const Nd& a) {
    return std::span<const T>(a.data(), static_cast<std::size_t>(a.shape(0)));
}

nb::tuple publish_coo(tcad::device3d::Coo&& c) {
    return nb::make_tuple(publish(std::move(c.rows)), publish(std::move(c.cols)),
                          publish(std::move(c.vals)));
}

void check_edges(std::int64_t E, I64 kR, F64 w, const char* axis) {
    if (static_cast<std::int64_t>(kR.shape(0)) != E ||
        static_cast<std::int64_t>(w.shape(0)) != E)
        throw tcad::InvalidArgument(std::string("device3d ") + axis +
                                    "-axis arrays disagree in length");
}

/// The continuity kernels read every per-edge array at [0, E) where
/// E = kL.size(); a short one was an out-of-bounds read.
void check_edges6(I64 kL, I64 kR, F64 w, F64 d0, F64 d1, F64 d2, const char* axis) {
    const auto E = static_cast<std::int64_t>(kL.shape(0));
    check_edges(E, kR, w, axis);
    if (static_cast<std::int64_t>(d0.shape(0)) != E ||
        static_cast<std::int64_t>(d1.shape(0)) != E ||
        static_cast<std::int64_t>(d2.shape(0)) != E)
        throw tcad::InvalidArgument(std::string("device3d ") + axis +
                                    "-axis derivative arrays disagree in length");
}

}  // namespace

void register_device3d(nb::module_& m) {
    m.def("device3d_poisson_eq_stencil",
          [](std::int64_t Nz, std::int64_t Ny, std::int64_t Nx, F64 psi, F64 n, F64 p,
             F64 C, F64 dnp, F64 dV, F64 et_x, F64 et_y, F64 et_z, F64 hx, F64 hy,
             F64 hz, F64 dVx, F64 dVy, F64 dVz, I64 gate_rows, F64 gate_vals, I64 contact) {
              if (Nz < 1 || Ny < 1 || Nx < 1)
                  throw tcad::InvalidArgument("device3d_poisson_eq_stencil: empty grid");
              const std::int64_t N = Nz * Ny * Nx;
              auto need = [](const F64& a, std::int64_t len, const char* what) {
                  if (static_cast<std::int64_t>(a.shape(0)) != len)
                      throw tcad::InvalidArgument(
                          std::string("device3d_poisson_eq_stencil: ") + what +
                          " has " + std::to_string(a.shape(0)) + " entries, expected " +
                          std::to_string(len));
              };
              need(psi, N, "psi"); need(n, N, "n"); need(p, N, "p"); need(C, N, "C");
              need(dnp, N, "dnp"); need(dV, N, "dV");
              need(et_x, Nz * Ny * (Nx - 1), "et_x");
              need(et_y, Nz * (Ny - 1) * Nx, "et_y");
              need(et_z, (Nz - 1) * Ny * Nx, "et_z");
              need(hx, Nx - 1, "hx"); need(hy, Ny - 1, "hy"); need(hz, Nz - 1, "hz");
              need(dVx, Nx, "dVx"); need(dVy, Ny, "dVy"); need(dVz, Nz, "dVz");
              const auto G = static_cast<std::int64_t>(gate_rows.shape(0));
              const auto K = static_cast<std::int64_t>(contact.shape(0));
              need(gate_vals, G, "gate_vals");
              tcad::check_indices(gate_rows.data(), G, N, "gate_rows");
              tcad::check_indices(contact.data(), K, N, "contact");
              tcad::device3d::PoissonEq r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::device3d::poisson_eq_stencil(
                      Nz, Ny, Nx, psi.data(), n.data(), p.data(), C.data(), dnp.data(),
                      dV.data(), et_x.data(), et_y.data(), et_z.data(), hx.data(),
                      hy.data(), hz.data(), dVx.data(), dVy.data(), dVz.data(),
                      gate_rows.data(), gate_vals.data(), G, contact.data(), K);
              }
              return nb::make_tuple(publish(std::move(r.F)), publish(std::move(r.rows)),
                                    publish(std::move(r.cols)), publish(std::move(r.vals)));
          },
          "device3d._poisson_eq_stencil_py, compiled: (F flat, rows, cols, vals), "
          "bit-identical to the Python oracle.");

    m.def("device3d_poisson_flux_row",
          [](I64 kLx, I64 kRx, F64 wx_h, I64 kSy, I64 kNy, F64 wy_h,
             I64 kDz, I64 kUz, F64 wz_h) {
              check_edges(kLx.shape(0), kRx, wx_h, "x");
              check_edges(kSy.shape(0), kNy, wy_h, "y");
              check_edges(kDz.shape(0), kUz, wz_h, "z");
              return publish_coo(tcad::device3d::poisson_flux_row(
                  as_span<std::int64_t>(kLx), as_span<std::int64_t>(kRx), as_span<double>(wx_h),
                  as_span<std::int64_t>(kSy), as_span<std::int64_t>(kNy), as_span<double>(wy_h),
                  as_span<std::int64_t>(kDz), as_span<std::int64_t>(kUz), as_span<double>(wz_h)));
          },
          nb::arg("kLx"), nb::arg("kRx"), nb::arg("wx_h"), nb::arg("kSy"),
          nb::arg("kNy"), nb::arg("wy_h"), nb::arg("kDz"), nb::arg("kUz"),
          nb::arg("wz_h"));

    m.def("device3d_electron_continuity",
          [](I64 kLx, I64 kRx, F64 wx_area, F64 dpsiRx, F64 dnLx, F64 dnRx,
             I64 kSy, I64 kNy, F64 wy_area, F64 dpsiRy, F64 dnLy, F64 dnRy,
             I64 kDz, I64 kUz, F64 wz_area, F64 dpsiRz, F64 dnLz, F64 dnRz) {
              check_edges6(kLx, kRx, wx_area, dpsiRx, dnLx, dnRx, "x");
              check_edges6(kSy, kNy, wy_area, dpsiRy, dnLy, dnRy, "y");
              check_edges6(kDz, kUz, wz_area, dpsiRz, dnLz, dnRz, "z");
              return publish_coo(tcad::device3d::electron_continuity(
                  as_span<std::int64_t>(kLx), as_span<std::int64_t>(kRx), as_span<double>(wx_area),
                  as_span<double>(dpsiRx), as_span<double>(dnLx), as_span<double>(dnRx),
                  as_span<std::int64_t>(kSy), as_span<std::int64_t>(kNy), as_span<double>(wy_area),
                  as_span<double>(dpsiRy), as_span<double>(dnLy), as_span<double>(dnRy),
                  as_span<std::int64_t>(kDz), as_span<std::int64_t>(kUz), as_span<double>(wz_area),
                  as_span<double>(dpsiRz), as_span<double>(dnLz), as_span<double>(dnRz)));
          },
          nb::arg("kLx"), nb::arg("kRx"), nb::arg("wx_area"), nb::arg("dpsiRx"),
          nb::arg("dnLx"), nb::arg("dnRx"), nb::arg("kSy"), nb::arg("kNy"),
          nb::arg("wy_area"), nb::arg("dpsiRy"), nb::arg("dnLy"), nb::arg("dnRy"),
          nb::arg("kDz"), nb::arg("kUz"), nb::arg("wz_area"), nb::arg("dpsiRz"),
          nb::arg("dnLz"), nb::arg("dnRz"));

    m.def("device3d_hole_continuity",
          [](I64 kLx, I64 kRx, F64 wx_area, F64 dpsiRx, F64 dpLx, F64 dpRx,
             I64 kSy, I64 kNy, F64 wy_area, F64 dpsiRy, F64 dpLy, F64 dpRy,
             I64 kDz, I64 kUz, F64 wz_area, F64 dpsiRz, F64 dpLz, F64 dpRz) {
              check_edges6(kLx, kRx, wx_area, dpsiRx, dpLx, dpRx, "x");
              check_edges6(kSy, kNy, wy_area, dpsiRy, dpLy, dpRy, "y");
              check_edges6(kDz, kUz, wz_area, dpsiRz, dpLz, dpRz, "z");
              return publish_coo(tcad::device3d::hole_continuity(
                  as_span<std::int64_t>(kLx), as_span<std::int64_t>(kRx), as_span<double>(wx_area),
                  as_span<double>(dpsiRx), as_span<double>(dpLx), as_span<double>(dpRx),
                  as_span<std::int64_t>(kSy), as_span<std::int64_t>(kNy), as_span<double>(wy_area),
                  as_span<double>(dpsiRy), as_span<double>(dpLy), as_span<double>(dpRy),
                  as_span<std::int64_t>(kDz), as_span<std::int64_t>(kUz), as_span<double>(wz_area),
                  as_span<double>(dpsiRz), as_span<double>(dpLz), as_span<double>(dpRz)));
          },
          nb::arg("kLx"), nb::arg("kRx"), nb::arg("wx_area"), nb::arg("dpsiRx"),
          nb::arg("dpLx"), nb::arg("dpRx"), nb::arg("kSy"), nb::arg("kNy"),
          nb::arg("wy_area"), nb::arg("dpsiRy"), nb::arg("dpLy"), nb::arg("dpRy"),
          nb::arg("kDz"), nb::arg("kUz"), nb::arg("wz_area"), nb::arg("dpsiRz"),
          nb::arg("dpLz"), nb::arg("dpRz"));

    m.def("device3d_base_diagonal",
          [](std::int64_t N, F64 dV, bool has_incomplete_ion, F64 dcden,
             F64 dcdp, F64 dRs_dn, F64 dRs_dp) {
              if (static_cast<std::int64_t>(dV.shape(0)) != N ||
                  static_cast<std::int64_t>(dRs_dn.shape(0)) != N ||
                  static_cast<std::int64_t>(dRs_dp.shape(0)) != N)
                  throw tcad::InvalidArgument("device3d_base_diagonal: "
                                              "dV/dRs_dn/dRs_dp must have N entries");
              // dcden/dcdp are read only on the incomplete-ionization path
              // (the caller passes empty arrays otherwise).
              if (has_incomplete_ion &&
                  (static_cast<std::int64_t>(dcden.shape(0)) != N ||
                   static_cast<std::int64_t>(dcdp.shape(0)) != N))
                  throw tcad::InvalidArgument("device3d_base_diagonal: "
                                              "dcden/dcdp must have N entries "
                                              "when has_incomplete_ion");
              return publish_coo(tcad::device3d::base_diagonal(
                  N, as_span<double>(dV), has_incomplete_ion, as_span<double>(dcden),
                  as_span<double>(dcdp), as_span<double>(dRs_dn), as_span<double>(dRs_dp)));
          },
          nb::arg("N"), nb::arg("dV"), nb::arg("has_incomplete_ion"),
          nb::arg("dcden"), nb::arg("dcdp"), nb::arg("dRs_dn"), nb::arg("dRs_dp"));
}
