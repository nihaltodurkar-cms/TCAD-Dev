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
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/device3d/kernels.hpp"

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

template <typename T, typename Nd>
std::vector<T> to_vec(const Nd& a) {
    return std::vector<T>(a.data(), a.data() + a.shape(0));
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

}  // namespace

void register_device3d(nb::module_& m) {
    m.def("device3d_poisson_flux_row",
          [](I64 kLx, I64 kRx, F64 wx_h, I64 kSy, I64 kNy, F64 wy_h,
             I64 kDz, I64 kUz, F64 wz_h) {
              check_edges(kLx.shape(0), kRx, wx_h, "x");
              check_edges(kSy.shape(0), kNy, wy_h, "y");
              check_edges(kDz.shape(0), kUz, wz_h, "z");
              return publish_coo(tcad::device3d::poisson_flux_row(
                  to_vec<std::int64_t>(kLx), to_vec<std::int64_t>(kRx), to_vec<double>(wx_h),
                  to_vec<std::int64_t>(kSy), to_vec<std::int64_t>(kNy), to_vec<double>(wy_h),
                  to_vec<std::int64_t>(kDz), to_vec<std::int64_t>(kUz), to_vec<double>(wz_h)));
          },
          nb::arg("kLx"), nb::arg("kRx"), nb::arg("wx_h"), nb::arg("kSy"),
          nb::arg("kNy"), nb::arg("wy_h"), nb::arg("kDz"), nb::arg("kUz"),
          nb::arg("wz_h"));

    m.def("device3d_electron_continuity",
          [](I64 kLx, I64 kRx, F64 wx_area, F64 dpsiRx, F64 dnLx, F64 dnRx,
             I64 kSy, I64 kNy, F64 wy_area, F64 dpsiRy, F64 dnLy, F64 dnRy,
             I64 kDz, I64 kUz, F64 wz_area, F64 dpsiRz, F64 dnLz, F64 dnRz) {
              return publish_coo(tcad::device3d::electron_continuity(
                  to_vec<std::int64_t>(kLx), to_vec<std::int64_t>(kRx), to_vec<double>(wx_area),
                  to_vec<double>(dpsiRx), to_vec<double>(dnLx), to_vec<double>(dnRx),
                  to_vec<std::int64_t>(kSy), to_vec<std::int64_t>(kNy), to_vec<double>(wy_area),
                  to_vec<double>(dpsiRy), to_vec<double>(dnLy), to_vec<double>(dnRy),
                  to_vec<std::int64_t>(kDz), to_vec<std::int64_t>(kUz), to_vec<double>(wz_area),
                  to_vec<double>(dpsiRz), to_vec<double>(dnLz), to_vec<double>(dnRz)));
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
              return publish_coo(tcad::device3d::hole_continuity(
                  to_vec<std::int64_t>(kLx), to_vec<std::int64_t>(kRx), to_vec<double>(wx_area),
                  to_vec<double>(dpsiRx), to_vec<double>(dpLx), to_vec<double>(dpRx),
                  to_vec<std::int64_t>(kSy), to_vec<std::int64_t>(kNy), to_vec<double>(wy_area),
                  to_vec<double>(dpsiRy), to_vec<double>(dpLy), to_vec<double>(dpRy),
                  to_vec<std::int64_t>(kDz), to_vec<std::int64_t>(kUz), to_vec<double>(wz_area),
                  to_vec<double>(dpsiRz), to_vec<double>(dpLz), to_vec<double>(dpRz)));
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
              return publish_coo(tcad::device3d::base_diagonal(
                  N, to_vec<double>(dV), has_incomplete_ion, to_vec<double>(dcden),
                  to_vec<double>(dcdp), to_vec<double>(dRs_dn), to_vec<double>(dRs_dp)));
          },
          nb::arg("N"), nb::arg("dV"), nb::arg("has_incomplete_ion"),
          nb::arg("dcden"), nb::arg("dcdp"), nb::arg("dRs_dn"), nb::arg("dRs_dp"));
}
