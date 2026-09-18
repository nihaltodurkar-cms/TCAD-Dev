// pytcad._core -- the single extension module for the C++ engine.
//
// P0 scope: no kernels yet.  What this file establishes is the BOUNDARY
// -- module identity, thread policy, and above all the exception
// translation contract -- so that when kernels land in P2 they plug into
// a boundary that already has tests.
//
// The exception rule is the important one: the PYTHON class is the
// authority.  A C++ kernel that raises tcad::DegenerateMesh surfaces in
// Python as pytcad.errors.DegenerateMeshError -- the very class an
// existing, unmodified `pytest.raises(DegenerateMeshError)` in
// tests/test_m21_phase3.py and tests/test_unstructured_dd3d.py already
// catches.  We never mint a parallel C++-side exception type, because
// then every one of those tests would have to learn a second name.
#include <nanobind/nanobind.h>

#include <exception>

#include "tcad/base/errors.hpp"
#include "tcad/runtime/threads.hpp"

// Defined in mesh_bindings.cpp / solver_bindings.cpp -- one module,
// several translation units.
void register_mesh(nanobind::module_& m);
void register_solver(nanobind::module_& m);
void register_process(nanobind::module_& m);
void register_nonlocal(nanobind::module_& m);
void register_thermal(nanobind::module_& m);
void register_dg(nanobind::module_& m);

namespace nb = nanobind;

namespace {

// Resolved LAZILY, never at module init: pytcad.errors and
// pytcad.linsolve must both be importable in a checkout where this
// extension does not exist at all, so importing them from here at load
// time would invert the dependency the whole fallback design rests on.
PyObject* python_error_class(const char* module, const char* attr) {
    nb::object cls = nb::module_::import_(module).attr(attr);
    return cls.release().ptr();  // module-level classes outlive us
}

PyObject* degenerate_mesh_error() {
    static PyObject* c = python_error_class("pytcad.errors", "DegenerateMeshError");
    return c;
}

PyObject* linear_solve_error() {
    static PyObject* c = python_error_class("pytcad.linsolve", "LinearSolveError");
    return c;
}

}  // namespace

NB_MODULE(_core, m) {
    m.doc() = "Compiled kernels for pytcad. Always optional: pytcad/_accel.py "
              "falls back to the pure-Python reference path when absent.";

    m.attr("__version__") = "0.1.0";

    m.def("thread_count", &tcad::runtime::thread_count,
          "Threads the kernels will use. Defaults to 1 -- see "
          "tcad/runtime/threads.hpp for why (bit-identity under "
          "np.array_equal goldens, and not oversubscribing "
          "workbench/batch.py's pool workers).");

    // Sole purpose: give tests/test_accel_boundary.py something to
    // assert the translation contract against without needing a kernel.
    m.def("_raise_for_test", [](const char* which) {
        const std::string w(which);
        if (w == "degenerate")  throw tcad::DegenerateMesh("tet 0 is degenerate");
        if (w == "linsolve")    throw tcad::LinearSolveFailure("singular matrix");
        if (w == "convergence") throw tcad::ConvergenceFailure("did not converge", 42, 1.5e-3);
        if (w == "argument")    throw tcad::InvalidArgument("bad shape");
        if (w == "index")       throw tcad::IndexOutOfRange("node 7 is out of range");
        throw std::runtime_error("unmapped");
    }, nb::arg("which"),
       "Raise one C++ exception of each mapped kind. Test hook only.");

    register_mesh(m);
    register_solver(m);
    register_process(m);
    register_nonlocal(m);
    register_thermal(m);
    register_dg(m);

    nb::register_exception_translator(
        [](const std::exception_ptr& p, void*) {
            try {
                std::rethrow_exception(p);
            } catch (const tcad::DegenerateMesh& e) {
                PyErr_SetString(degenerate_mesh_error(), e.what());
            } catch (const tcad::LinearSolveFailure& e) {
                PyErr_SetString(linear_solve_error(), e.what());
            } catch (const tcad::ConvergenceFailure& e) {
                // Diagnostics travel on the exception so a caller can LOG
                // what happened without ever being handed the bad iterate.
                nb::object exc = nb::steal(
                    PyObject_CallFunction(linear_solve_error(), "s", e.what()));
                if (exc.is_valid()) {
                    exc.attr("iterations") = e.iterations;
                    exc.attr("residual")   = e.residual;
                    PyErr_SetObject(linear_solve_error(), exc.ptr());
                }
            } catch (const tcad::InvalidArgument& e) {
                PyErr_SetString(PyExc_ValueError, e.what());
            } catch (const tcad::IndexOutOfRange& e) {
                // numpy raises IndexError for an out-of-range fancy index,
                // so the accelerated path must too -- the CLASS is the
                // contract, the message text deliberately is not.
                PyErr_SetString(PyExc_IndexError, e.what());
            }
            // Anything unmapped falls through to nanobind's default.
        });
}
