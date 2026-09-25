// Bindings for the PETSc KSP configuration (M31 P3b).
//
// Same ownership discipline as mesh_bindings.cpp: inputs are borrowed,
// read-only and never retained past the call; the solution is a FRESH
// allocation published to numpy through an nb::capsule, and only after
// the solve returns normally -- on a throw the vector dies and no Python
// object was ever created.
//
// The signature is deliberately LOW-LEVEL (raw CSR triple, no matrix
// object).  linsolve.py already holds a canonical scipy CSR and its own
// residual/acceptance logic; handing that across as three arrays keeps
// the C++ side free of any opinion about what a matrix is, which is what
// lets both backends be driven from one code path in Python and compared
// with np.array_equal.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"
#include "tcad/solver/petsc_ksp.hpp"

namespace nb = nanobind;

namespace {

using I64 = nb::ndarray<const std::int64_t, nb::c_contig, nb::ndim<1>>;
using F64 = nb::ndarray<const double, nb::c_contig, nb::ndim<1>>;

nb::ndarray<nb::numpy, double> publish(std::vector<double>&& v) {
    auto* held = new std::vector<double>(std::move(v));
    nb::capsule owner(held, [](void* p) noexcept {
        delete static_cast<std::vector<double>*>(p);
    });
    return nb::ndarray<nb::numpy, double>(held->data(), {held->size()}, owner);
}

}  // namespace

void register_solver(nb::module_& m) {
    m.def("petsc_available", &tcad::solver::have_petsc,
          "True when this extension was compiled against PETSc. False is a "
          "SUPPORTED configuration -- linsolve.solve_linear(method='petsc') "
          "then uses the petsc4py backend instead.");

    m.def("petsc_version", []() { return std::string(tcad::solver::petsc_version()); },
          "PETSc version this was compiled against, or '' without PETSc.");

    m.def("mumps_available", &tcad::solver::have_mumps,
          "True when the PETSc this extension was compiled against has "
          "MUMPS, i.e. petsc_solve_csr(direct_lu=True) can run.");

    m.def("petsc_index_bytes", &tcad::solver::petsc_index_bytes,
          "sizeof(PetscInt) in the PETSc this was compiled against, or 0. "
          "Informational: the array boundary is int64 either way. A 4 here "
          "means matrices with more than 2^31 nonzeros are out of reach.");

    m.def("petsc_solve_csr",
          [](I64 indptr, I64 indices, F64 values, F64 b,
             std::optional<F64> x0, double rtol, double atol, int maxiter,
             int restart, int block_size, bool direct_lu) {
              const std::int64_t n = static_cast<std::int64_t>(indptr.shape(0)) - 1;
              const std::int64_t nnz = static_cast<std::int64_t>(indices.shape(0));
              if (n < 0)
                  throw tcad::InvalidArgument("indptr must have at least one entry");
              if (static_cast<std::int64_t>(values.shape(0)) != nnz)
                  throw tcad::InvalidArgument(
                      "CSR data and indices must have the same length");
              if (static_cast<std::int64_t>(b.shape(0)) != n)
                  throw tcad::InvalidArgument("b must have length n");
              if (x0 && static_cast<std::int64_t>(x0->shape(0)) != n)
                  throw tcad::InvalidArgument("x0 must have length n");

              tcad::solver::KspConfig cfg;
              cfg.rtol = rtol;
              cfg.atol = atol;
              cfg.maxiter = maxiter;
              cfg.restart = restart;
              cfg.block_size = block_size;
              cfg.nonzero_guess = x0.has_value();
              cfg.direct_lu = direct_lu;

              std::vector<double> x(static_cast<std::size_t>(n), 0.0);
              if (x0) std::copy(x0->data(), x0->data() + n, x.begin());

              tcad::solver::KspResult r;
              {
                  // The solve is the whole point of releasing the GIL:
                  // it is the longest-running call in the engine.
                  nb::gil_scoped_release nogil;
                  r = tcad::solver::solve_csr(n, nnz, indptr.data(), indices.data(),
                                              values.data(), b.data(), x.data(), cfg);
              }
              return nb::make_tuple(publish(std::move(x)), r.iterations,
                                    r.converged_reason);
          },
          nb::arg("indptr"), nb::arg("indices"), nb::arg("values"), nb::arg("b"),
          nb::arg("x0").none(), nb::arg("rtol"), nb::arg("atol"),
          nb::arg("maxiter"), nb::arg("restart"), nb::arg("block_size"),
          nb::arg("direct_lu") = false,
          "GMRES via PETSc's KSP on a sequential CSR matrix.\n\n"
          "Returns (x, iterations, converged_reason). A converged_reason <= 0 "
          "is NOT raised here: the caller recomputes the true residual and "
          "applies the same acceptance test to both backends, so that the "
          "compiled and petsc4py paths can never disagree about whether a "
          "solve succeeded.");
}
