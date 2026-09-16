"""The C++/Python boundary contract (M31 P0).

These tests do not exercise any kernel -- there are none yet.  They lock
down the properties every future kernel depends on, so that when kernels
land the boundary they plug into is already gated:

  * `import pytcad` itself never fails when the extension is absent
    (gate G-F, now scoped to IMPORT only -- as of M43 phase 4,
    2026-09-16, individual accelerated kernels REQUIRE the extension
    and raise a clear ImportError via `_accel.require_accel()` if it
    is missing, rather than falling back to a pure-Python path);
  * a C++ exception surfaces as the EXISTING Python class, so existing
    `pytest.raises(...)` sites keep working unmodified;
  * the default thread count is 1, because parallel FP reductions would
    break the repo's np.array_equal goldens and because
    workbench/batch.py pins its pool workers single-threaded.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

from pytcad import _accel
from pytcad.errors import DegenerateMeshError
from pytcad.linsolve import LinearSolveError

# NOT a module-level importorskip.  The two tests below that check the
# ABSENCE path are exactly the ones that matter when the extension is
# missing -- skipping the whole module there would silence them in the
# only run that exercises what they cover (found by actually deleting
# the .so and reading the skip count).
needs_core = pytest.mark.skipif(
    not _accel.HAVE_ACCEL, reason="compiled extension not built")


@pytest.fixture
def core():
    return _accel.core


def test_accel_absence_is_never_an_error():
    """_accel must import and answer cleanly whether or not _core exists."""
    assert isinstance(_accel.HAVE_ACCEL, bool)
    assert isinstance(_accel.status(), str)


def test_pytcad_imports_without_touching_the_extension():
    """`import pytcad` must not require _core.

    Run in a subprocess with the extension hidden, since it is already
    loaded in this one.  This is gate G-F in miniature: a checkout with
    no compiler still works.
    """
    code = (
        "import sys;"
        "sys.modules['pytcad._core'] = None;"   # force the ImportError path
        "import importlib;"
        "import pytcad;"
        "from pytcad import _accel;"
        "print(_accel.HAVE_ACCEL)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr


@needs_core
@pytest.mark.parametrize("kind,expected", [
    ("degenerate", DegenerateMeshError),
    ("linsolve", LinearSolveError),
    ("argument", ValueError),
])
def test_cpp_exceptions_become_the_existing_python_classes(core, kind, expected):
    """The Python class is the authority.

    A C++ kernel must raise the very class the existing tests already
    catch -- tests/test_m21_phase3.py's DegenerateMeshError, not a
    parallel C++-side type that every call site would have to learn.
    """
    with pytest.raises(expected):
        core._raise_for_test(kind)


def test_degenerate_mesh_error_is_one_class_everywhere():
    """Regression: it used to be declared TWICE, as unrelated classes.

    `unstructured_assembly.py` and `unstructured_assembly3d.py` each had
    their own `class DegenerateMeshError(ValueError)`, so an `except` on
    one silently failed to catch the other.
    """
    from pytcad.unstructured_assembly import DegenerateMeshError as E2
    from pytcad.unstructured_assembly3d import DegenerateMeshError as E3
    assert E2 is E3 is DegenerateMeshError


@needs_core
def test_convergence_failure_carries_diagnostics_not_state(core):
    """A failed solve must never hand back the bad iterate.

    It raises, and the diagnostics ride on the exception so a caller can
    still log what happened -- mirroring linsolve.py's existing rule.
    """
    with pytest.raises(LinearSolveError) as exc:
        core._raise_for_test("convergence")
    assert exc.value.iterations == 42
    assert exc.value.residual == pytest.approx(1.5e-3)


def test_petsc_capability_is_answerable_without_the_extension():
    """M31 P3b added a second optional layer on top of the extension
    itself -- built against PETSc, or not -- and both combinations have
    to answer cleanly rather than raise.  A checkout with no compiler
    must still be able to ask."""
    assert isinstance(_accel.have_petsc(), bool)
    assert isinstance(_accel.status(), str)
    if not _accel.HAVE_ACCEL:
        assert _accel.have_petsc() is False


@needs_core
def test_petsc_capability_reporting_is_self_consistent(core):
    """petsc_available() and the index width must agree: a build with
    PETSc reports a real version and a real sizeof(PetscInt); a build
    without reports neither, and that is a supported configuration."""
    available = core.petsc_available()
    assert isinstance(available, bool)
    if available:
        assert core.petsc_version().count(".") == 2, core.petsc_version()
        # 4 on conda-forge's default build, 8 with --with-64-bit-indices.
        # Anything else means the probe is reading the wrong thing.
        assert core.petsc_index_bytes() in (4, 8)
        assert "petsc=" in _accel.status()
    else:
        assert core.petsc_version() == ""
        assert core.petsc_index_bytes() == 0


@needs_core
def test_petsc_solve_without_petsc_names_both_recovery_routes(core):
    """A _core built without PETSc must not merely fail -- it has to say
    which of the two things to install, since the method has two
    independent backends now."""
    if core.petsc_available():
        pytest.skip("this extension was built with PETSc")
    with pytest.raises(LinearSolveError) as exc:
        core.petsc_solve_csr(np.array([0], dtype=np.int64),
                             np.zeros(0, dtype=np.int64), np.zeros(0),
                             np.zeros(0), None, 1e-10, 1e-50, 10, 10, 0)
    assert "petsc4py" in str(exc.value)


@needs_core
def test_default_thread_count_is_one():
    """Not a style preference -- see tcad/runtime/threads.hpp.

    Threads here would both oversubscribe workbench/batch.py's pool
    workers and make scatter-add reductions non-reproducible.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTCAD_NUM_THREADS", "OMP_NUM_THREADS")}
    out = subprocess.run(
        [sys.executable, "-c",
         "from pytcad import _core; print(_core.thread_count())"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1"


@needs_core
@pytest.mark.parametrize("var", ["PYTCAD_NUM_THREADS", "OMP_NUM_THREADS"])
def test_thread_count_honors_the_environment(var):
    env = dict(os.environ)
    env.pop("PYTCAD_NUM_THREADS", None)
    env.pop("OMP_NUM_THREADS", None)
    env[var] = "4"
    out = subprocess.run(
        [sys.executable, "-c",
         "from pytcad import _core; print(_core.thread_count())"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip() == "4", out.stderr


@needs_core
def test_index_errors_stay_index_errors(core):
    """M31 P4 added a fourth mapped exception.

    The reference gets IndexError for free from numpy fancy-indexing; a
    kernel dereferencing a raw pointer would read out of bounds instead,
    so the process kernels validate the index range and raise this. It
    has to arrive as IndexError, not ValueError -- a caller distinguishes
    "you passed a broken mesh" from "you passed the wrong shape".
    """
    with pytest.raises(IndexError):
        core._raise_for_test("index")


def test_process_kernels_raise_a_clear_error_without_the_extension():
    """M43 phase 4 (2026-09-16): process.diffuse_numeric and
    ted.diffuse_with_defects no longer have a pure-Python fallback --
    calling them with the extension absent must raise a clear,
    actionable ImportError (via _accel.require_accel()), not an
    AttributeError on `_accel.core` being None. Run in a subprocess
    with the extension hidden, since it is already loaded in this one
    (same technique test_pytcad_imports_without_touching_the_extension
    uses above)."""
    code = (
        "import sys, numpy as np\n"
        "sys.modules['pytcad._core'] = None\n"
        "from pytcad import process\n"
        "x = np.linspace(0.0, 2.0e-4, 40)\n"
        "C = process.implant(x, 'B', 50.0, 1e15)\n"
        "try:\n"
        "    process.diffuse_numeric(x, C, 'B', 1000.0, 1.0)\n"
        "    print('NO_RAISE')\n"
        "except ImportError as exc:\n"
        "    print('RAISED:' + str(exc)[:30])\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().startswith("RAISED:"), out.stdout
