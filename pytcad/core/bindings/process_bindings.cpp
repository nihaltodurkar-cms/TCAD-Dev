// Bindings for the process/adaptivity kernels (M31 P4).
//
// Same ownership discipline as mesh_bindings.cpp: inputs are borrowed
// read-only and never retained; outputs are fresh allocations published
// through an nb::capsule only after the kernel returns normally.
//
// The diffusion entry points differ from every other kernel in one way
// worth stating: they mutate a buffer. They do it on a COPY this binding
// makes, never on the caller's array -- the reference does
// `C = np.asarray(C, float).copy()` for exactly the same reason, and a
// kernel that quietly wrote through would be a difference between the
// two paths that no value comparison could detect.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/process/kernels.hpp"

namespace nb = nanobind;

namespace {

using F64 = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using NodesF = nb::ndarray<const double, nb::c_contig>;
using TriF = nb::ndarray<const std::int64_t, nb::c_contig>;

template <typename T>
nb::ndarray<nb::numpy, T> publish(std::vector<T>&& v, std::initializer_list<size_t> shape) {
    auto* held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
    return nb::ndarray<nb::numpy, T>(held->data(), shape, owner);
}

void check_nodes(const NodesF& a) {
    if (a.ndim() != 2 || a.shape(1) != 3)
        throw tcad::InvalidArgument("nodes: expected an (n, 3) float64 array");
}
void check_tris(const TriF& a) {
    if (a.ndim() != 2 || a.shape(1) != 3)
        throw tcad::InvalidArgument("triangles: expected an (n, 3) int64 array");
}
void check_len(const F64& a, std::int64_t want, const char* what) {
    if (static_cast<std::int64_t>(a.shape(0)) != want)
        throw tcad::InvalidArgument(std::string(what) + ": expected length " +
                                    std::to_string(want) + ", got " +
                                    std::to_string(a.shape(0)));
}

/// Shared shape contract for both diffusion entry points. n >= 2 is not
/// a C++ convenience: the reference indexes flux[0] and flux[-1]
/// unconditionally, so a 1-node grid raises there too -- just with
/// numpy's IndexError wording rather than this one's.
std::int64_t check_diffusion_shapes(const F64& C, const F64& h, const F64& dV,
                                    std::int64_t n_steps) {
    const auto n = static_cast<std::int64_t>(C.shape(0));
    if (n < 2)
        throw tcad::InvalidArgument("C: the diffusion grid needs at least 2 nodes, got " +
                                    std::to_string(n));
    check_len(h, n - 1, "h");
    check_len(dV, n, "dV");
    if (n_steps < 0)
        throw tcad::InvalidArgument("n_steps must be non-negative, got " +
                                    std::to_string(n_steps));
    return n;
}

}  // namespace

void register_process(nb::module_& m) {
    // ------------------------------------------------------------------
    //  AMR indicators
    // ------------------------------------------------------------------
    m.def("indicator_curvature_tri",
          [](NodesF nodes, TriF tris, F64 psi, double scale) {
              check_nodes(nodes);
              check_tris(tris);
              check_len(psi, static_cast<std::int64_t>(nodes.shape(0)), "psi");
              std::vector<double> r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::process::indicator_curvature_tri(
                      nodes.data(), static_cast<std::int64_t>(nodes.shape(0)),
                      tris.data(), static_cast<std::int64_t>(tris.shape(0)),
                      psi.data(), scale);
              }
              const size_t nt = r.size();
              return publish(std::move(r), {nt});
          },
          nb::arg("nodes"), nb::arg("triangles"), nb::arg("psi"), nb::arg("scale"),
          "Per-triangle curvature indicator. `scale` is the caller's peak "
          "normalisation, computed in numpy.");

    m.def("indicator_log_density_tri",
          [](TriF tris, F64 ln_n, F64 ln_p) {
              check_tris(tris);
              const auto nn = static_cast<std::int64_t>(ln_n.shape(0));
              check_len(ln_p, nn, "ln_p");
              std::vector<double> r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::process::indicator_log_density_tri(
                      nn, tris.data(), static_cast<std::int64_t>(tris.shape(0)),
                      ln_n.data(), ln_p.data());
              }
              const size_t nt = r.size();
              return publish(std::move(r), {nt});
          },
          nb::arg("triangles"), nb::arg("ln_n"), nb::arg("ln_p"),
          "Per-triangle log-density indicator. Takes the LOGS: np.log stays "
          "on the numpy side so the two paths cannot disagree about it.");

    m.def("debye_ratio_tri",
          [](NodesF nodes, TriF tris, F64 ld_node) {
              check_nodes(nodes);
              check_tris(tris);
              check_len(ld_node, static_cast<std::int64_t>(nodes.shape(0)), "ld_node");
              std::vector<double> r;
              {
                  nb::gil_scoped_release nogil;
                  r = tcad::process::debye_ratio_tri(
                      nodes.data(), static_cast<std::int64_t>(nodes.shape(0)),
                      tris.data(), static_cast<std::int64_t>(tris.shape(0)),
                      ld_node.data());
              }
              const size_t nt = r.size();
              return publish(std::move(r), {nt});
          },
          nb::arg("nodes"), nb::arg("triangles"), nb::arg("ld_node"),
          "Per-triangle longest-edge / min-nodal-Debye-length ratio. Takes "
          "the nodal Debye lengths, already computed by numpy.");

    // ------------------------------------------------------------------
    //  1D explicit diffusion
    // ------------------------------------------------------------------
    m.def("diffuse1d_const",
          [](F64 C, F64 h, F64 dV, double D, double dt,
             std::int64_t n_steps, bool reflecting) {
              const std::int64_t n = check_diffusion_shapes(C, h, dV, n_steps);
              std::vector<double> buf(C.data(), C.data() + n);
              {
                  nb::gil_scoped_release nogil;
                  tcad::process::diffuse1d_const(buf.data(), n, h.data(), dV.data(),
                                                 D, dt, n_steps, reflecting);
              }
              return publish(std::move(buf), {static_cast<size_t>(n)});
          },
          nb::arg("C"), nb::arg("h"), nb::arg("dV"), nb::arg("D"), nb::arg("dt"),
          nb::arg("n_steps"), nb::arg("reflecting"),
          "process.diffuse_numeric's time loop, constant D. Returns a NEW "
          "array; the caller's C is not modified.");

    m.def("diffuse1d_enhanced",
          [](F64 C, F64 h, F64 dV, double Di, F64 extrinsic,
             double ted_S0, double ted_tau_s, double oed_boost, double dt,
             std::int64_t n_steps, bool reflecting) {
              const std::int64_t n = check_diffusion_shapes(C, h, dV, n_steps);
              check_len(extrinsic, n, "extrinsic");
              std::vector<double> buf(C.data(), C.data() + n);
              {
                  nb::gil_scoped_release nogil;
                  tcad::process::diffuse1d_enhanced(
                      buf.data(), n, h.data(), dV.data(), Di, extrinsic.data(),
                      ted_S0, ted_tau_s, oed_boost, dt, n_steps, reflecting);
              }
              return publish(std::move(buf), {static_cast<size_t>(n)});
          },
          nb::arg("C"), nb::arg("h"), nb::arg("dV"), nb::arg("Di"),
          nb::arg("extrinsic"), nb::arg("ted_S0"), nb::arg("ted_tau_s"),
          nb::arg("oed_boost"), nb::arg("dt"), nb::arg("n_steps"),
          nb::arg("reflecting"),
          "ted.diffuse_with_defects' time loop. ted_tau_s is ignored when "
          "ted_S0 == 0.0, matching the reference's short circuit.");
}
