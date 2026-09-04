"""Performance pass (2026-09-04): regression gate for pytcad.linsolve's
lazy cupy import.

A real `import cupy` costs ~85-124ms (confirmed via `python3 -X
importtime`) -- CUDA driver detection, extension loading -- the single
largest contributor to this codebase's cold-start import chain, even
though most sessions never touch the opt-in gpu_direct solve method.
pytcad.linsolve used to `import cupy` unconditionally at module load;
it now defers that to solve_linear()'s gpu_direct branch, the one
place that actually needs it, while _HAVE_CUPY stays a plain,
eagerly-computed module-level bool (via importlib.util.find_spec,
which locates the package without executing it) since gui/services/
solver_runner.py imports that name directly and reads it as a flag,
not a function call.

This test is the regression gate: importing pytcad.linsolve alone must
never pull cupy into sys.modules.
"""
import subprocess
import sys


def test_importing_linsolve_does_not_import_cupy():
    # A subprocess, not a direct `import` in this test process: once
    # cupy is in sys.modules for any reason (e.g. an earlier test in
    # the same worker), an in-process check would pass regardless of
    # whether THIS import path is the one that pulled it in.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import pytcad.linsolve; "
         "print('cupy' in sys.modules)"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", (
        "importing pytcad.linsolve pulled cupy into sys.modules -- "
        "the lazy-import regression this test guards against"
    )


def test_have_cupy_flag_is_still_a_plain_eager_bool_matching_availability():
    # gui/services/solver_runner.py imports _HAVE_CUPY directly as a
    # name (`from pytcad.linsolve import ..., _HAVE_CUPY`) and reads it
    # as a plain flag -- it must exist and be correct without cupy ever
    # being imported.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from pytcad.linsolve import _HAVE_CUPY; "
         "import importlib.util; "
         "expected = importlib.util.find_spec('cupy') is not None; "
         "print(_HAVE_CUPY == expected and 'cupy' not in sys.modules)"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
