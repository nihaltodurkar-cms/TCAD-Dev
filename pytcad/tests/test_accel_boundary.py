"""The C++/Python boundary contract (M31 P0).

These tests do not exercise any kernel -- there are none yet.  They lock
down the properties every future kernel depends on, so that when kernels
land the boundary they plug into is already gated:

  * the extension is OPTIONAL and its absence is not an error (gate G-F);
  * a C++ exception surfaces as the EXISTING Python class, so existing
    `pytest.raises(...)` sites keep working unmodified;
  * the default thread count is 1, because parallel FP reductions would
    break the repo's np.array_equal goldens and because
    workbench/batch.py pins its pool workers single-threaded.
"""
import os
import subprocess
import sys

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
