// Bindings for M47 Slice 1's unstructured 3D drift-diffusion
// interior-physics assembly (core/src/unstructured3d/kernels.cpp).
//
// Only the two ORCHESTRATED entry points are bound -- see
// tcad/unstructured3d/kernels.hpp's file header for the binding-shape
// decision (a throwaway micro-benchmark found no measurable difference
// between 4 separate bound calls and 1, so the simpler 1-call-per-mode
// shape was kept).
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <optional>
#include <vector>

#include <nanobind/stl/optional.h>

#include "tcad/base/checks.hpp"
#include "tcad/base/errors.hpp"
#include "tcad/unstructured3d/kernels.hpp"

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

/// The kernels scatter into F[edge_i[e]] / F[edge_j[e]] unchecked.
void check_edge_nodes(const I64& edge_i, const I64& edge_j, std::int64_t N) {
    const auto E = static_cast<std::int64_t>(edge_i.shape(0));
    tcad::check_indices(edge_i.data(), E, N, "edge_i");
    tcad::check_indices(edge_j.data(), E, N, "edge_j");
}

}  // namespace

void register_unstructured3d(nb::module_& m) {
    m.def("unstructured3d_residual_jacobian_equilibrium",
          [](F64 n, F64 p, F64 C_s, F64 node_vols_s, I64 edge_i, I64 edge_j,
             F64 trans, F64 flux) {
              const std::int64_t N = static_cast<std::int64_t>(C_s.shape(0));
              if (static_cast<std::int64_t>(n.shape(0)) != N ||
                  static_cast<std::int64_t>(p.shape(0)) != N ||
                  static_cast<std::int64_t>(node_vols_s.shape(0)) != N)
                  throw tcad::InvalidArgument(
                      "n/p/node_vols_s: expected " + std::to_string(N) + " nodes");
              const std::int64_t E = static_cast<std::int64_t>(edge_i.shape(0));
              if (static_cast<std::int64_t>(edge_j.shape(0)) != E ||
                  static_cast<std::int64_t>(trans.shape(0)) != E ||
                  static_cast<std::int64_t>(flux.shape(0)) != E)
                  throw tcad::InvalidArgument(
                      "edge_j/trans/flux: expected " + std::to_string(E) + " edges");
              check_edge_nodes(edge_i, edge_j, N);

              auto out = tcad::unstructured3d::residual_jacobian_equilibrium(
                  to_vec<double>(n), to_vec<double>(p), to_vec<double>(C_s),
                  to_vec<double>(node_vols_s), to_vec<std::int64_t>(edge_i),
                  to_vec<std::int64_t>(edge_j), to_vec<double>(trans),
                  to_vec<double>(flux));

              return nb::make_tuple(publish(std::move(out.F)),
                                    publish(std::move(out.J.rows)),
                                    publish(std::move(out.J.cols)),
                                    publish(std::move(out.J.vals)));
          },
          nb::arg("n"), nb::arg("p"), nb::arg("C_s"), nb::arg("node_vols_s"), nb::arg("edge_i"), nb::arg("edge_j"),
          nb::arg("trans"), nb::arg("flux"));

    m.def("unstructured3d_residual_jacobian_coupled",
          [](F64 n, F64 p, F64 C_s, F64 node_vols_s, I64 edge_i, I64 edge_j,
             F64 eps_trans, F64 flux, F64 trans_bare, F64 D_n_s, F64 D_p_s,
             F64 Bp, F64 Bm, F64 dBp, F64 dBm, double nie_phys, F64 tau_n,
             F64 tau_p, double Ns, double R0, bool srh, bool auger,
             double auger_cn, double auger_cp,
             std::optional<F64> nie_node, std::optional<F64> Bp_h,
             std::optional<F64> Bm_h, std::optional<F64> dBp_h,
             std::optional<F64> dBm_h) {
              const std::int64_t N = static_cast<std::int64_t>(C_s.shape(0));
              if (static_cast<std::int64_t>(n.shape(0)) != N ||
                  static_cast<std::int64_t>(p.shape(0)) != N ||
                  static_cast<std::int64_t>(node_vols_s.shape(0)) != N ||
                  static_cast<std::int64_t>(tau_n.shape(0)) != N ||
                  static_cast<std::int64_t>(tau_p.shape(0)) != N)
                  throw tcad::InvalidArgument(
                      "n/p/node_vols_s/tau_n/tau_p: expected " + std::to_string(N) +
                      " nodes");
              const std::int64_t E = static_cast<std::int64_t>(edge_i.shape(0));
              if (static_cast<std::int64_t>(edge_j.shape(0)) != E ||
                  static_cast<std::int64_t>(eps_trans.shape(0)) != E ||
                  static_cast<std::int64_t>(flux.shape(0)) != E ||
                  static_cast<std::int64_t>(trans_bare.shape(0)) != E ||
                  static_cast<std::int64_t>(D_n_s.shape(0)) != E ||
                  static_cast<std::int64_t>(D_p_s.shape(0)) != E ||
                  static_cast<std::int64_t>(Bp.shape(0)) != E ||
                  static_cast<std::int64_t>(Bm.shape(0)) != E ||
                  static_cast<std::int64_t>(dBp.shape(0)) != E ||
                  static_cast<std::int64_t>(dBm.shape(0)) != E)
                  throw tcad::InvalidArgument(
                      "edge_j/eps_trans/flux/trans_bare/D_n_s/D_p_s/Bp/Bm/dBp/dBm: "
                      "expected " + std::to_string(E) + " edges");
              check_edge_nodes(edge_i, edge_j, N);

              // M47 Slice 3 heterojunction inputs, all optional: a
              // per-node nie overrides the scalar, and the hole's own
              // Bernoulli arrays override the electron ones. Omitted, the
              // scalar is broadcast and the electron arrays reused --
              // exactly the former homojunction call.
              std::vector<double> nie_v;
              if (nie_node) {
                  if (static_cast<std::int64_t>(nie_node->shape(0)) != N)
                      throw tcad::InvalidArgument("nie_node: expected " +
                                                  std::to_string(N) + " nodes");
                  nie_v = to_vec<double>(*nie_node);
              } else {
                  nie_v.assign(static_cast<std::size_t>(N), nie_phys);
              }
              const bool any_h = Bp_h || Bm_h || dBp_h || dBm_h;
              if (any_h && !(Bp_h && Bm_h && dBp_h && dBm_h))
                  throw tcad::InvalidArgument(
                      "Bp_h/Bm_h/dBp_h/dBm_h: pass all four or none");
              if (any_h &&
                  (static_cast<std::int64_t>(Bp_h->shape(0)) != E ||
                   static_cast<std::int64_t>(Bm_h->shape(0)) != E ||
                   static_cast<std::int64_t>(dBp_h->shape(0)) != E ||
                   static_cast<std::int64_t>(dBm_h->shape(0)) != E))
                  throw tcad::InvalidArgument(
                      "Bp_h/Bm_h/dBp_h/dBm_h: expected " + std::to_string(E) + " edges");
              const auto bph = to_vec<double>(any_h ? *Bp_h : Bp);
              const auto bmh = to_vec<double>(any_h ? *Bm_h : Bm);
              const auto dbph = to_vec<double>(any_h ? *dBp_h : dBp);
              const auto dbmh = to_vec<double>(any_h ? *dBm_h : dBm);

              auto out = tcad::unstructured3d::residual_jacobian_coupled(
                  to_vec<double>(n), to_vec<double>(p), to_vec<double>(C_s),
                  to_vec<double>(node_vols_s), to_vec<std::int64_t>(edge_i),
                  to_vec<std::int64_t>(edge_j), to_vec<double>(eps_trans),
                  to_vec<double>(flux), to_vec<double>(trans_bare),
                  to_vec<double>(D_n_s), to_vec<double>(D_p_s),
                  to_vec<double>(Bp), to_vec<double>(Bm), to_vec<double>(dBp),
                  to_vec<double>(dBm), nie_v, to_vec<double>(tau_n),
                  to_vec<double>(tau_p), Ns, R0, srh, auger, auger_cn,
                  auger_cp, bph, bmh, dbph, dbmh);

              return nb::make_tuple(publish(std::move(out.base.F)),
                                    publish(std::move(out.base.J.rows)),
                                    publish(std::move(out.base.J.cols)),
                                    publish(std::move(out.base.J.vals)),
                                    publish(std::move(out.Jn_edge)),
                                    publish(std::move(out.Jp_edge)));
          },
          nb::arg("n"), nb::arg("p"), nb::arg("C_s"), nb::arg("node_vols_s"), nb::arg("edge_i"), nb::arg("edge_j"),
          nb::arg("eps_trans"), nb::arg("flux"), nb::arg("trans_bare"), nb::arg("D_n_s"), nb::arg("D_p_s"),
          nb::arg("Bp"), nb::arg("Bm"), nb::arg("dBp"),
          nb::arg("dBm"), nb::arg("nie_phys"), nb::arg("tau_n"), nb::arg("tau_p"), nb::arg("Ns"), nb::arg("R0"),
          nb::arg("srh"), nb::arg("auger"), nb::arg("auger_cn"), nb::arg("auger_cp"),
          nb::arg("nie_node").none() = nb::none(), nb::arg("Bp_h").none() = nb::none(),
          nb::arg("Bm_h").none() = nb::none(), nb::arg("dBp_h").none() = nb::none(),
          nb::arg("dBm_h").none() = nb::none());
}
