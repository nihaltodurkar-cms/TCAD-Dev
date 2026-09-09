"""Layer boundaries, enforced by test rather than by convention.

Architecture_Master_Plan.md section 41 asks for automated import checks
so the layering cannot erode silently.  Until now the only such check
was gui/tests/test_m3_store_seam.py's pair of controller/visualization
assertions.  These generalize it to the boundaries the C++ migration
depends on staying intact.

The checks are deliberately source-text greps rather than import-graph
analysis, matching the existing seam test: they run in milliseconds, they
fail with an obvious message, and they cannot be defeated by a deferred
import (which is the thing they are there to catch).
"""
import ast
import inspect
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _imported_top_level_modules(path):
    """Every top-level package name this file imports, including imports
    nested inside functions -- a deferred import is still a dependency."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # relative import: same package
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _python_files(*parts):
    base = ROOT.joinpath(*parts)
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


# ----------------------------------------------------------------------
#  the numerical core is the bottom layer: it depends on nobody above it
# ----------------------------------------------------------------------
def test_core_never_imports_gui_or_workbench():
    """pytcad/ is the engine.  If it reaches up into gui/ or workbench/,
    the C++ port cannot be extracted without dragging Qt along."""
    offenders = {}
    for path in _python_files("pytcad"):
        bad = _imported_top_level_modules(path) & {"gui", "workbench", "PySide6"}
        if bad:
            offenders[path.relative_to(ROOT)] = sorted(bad)
    assert not offenders, f"numerical core must not depend on upper layers: {offenders}"


def test_workbench_core_never_imports_gui_or_qt():
    """workbench/__init__.py promises "No Qt, no solver imports in core"."""
    offenders = {}
    for path in _python_files("workbench", "core"):
        bad = _imported_top_level_modules(path) & {"gui", "PySide6"}
        if bad:
            offenders[path.relative_to(ROOT)] = sorted(bad)
    assert not offenders, f"workbench.core must stay Qt-free: {offenders}"


# ----------------------------------------------------------------------
#  the solver subprocess entry points must stay Qt-free and runnable
#  as plain CLIs -- this is what makes them swappable for a C++ binary
# ----------------------------------------------------------------------
@pytest.mark.parametrize("module", [
    "solver_runner.py", "process_runner.py", "mpi_schwarz_runner.py",
])
def test_solver_entry_points_import_no_qt(module):
    path = ROOT / "gui" / "services" / module
    bad = _imported_top_level_modules(path) & {"PySide6", "shiboken6"}
    assert not bad, (
        f"gui/services/{module} is a subprocess entry point and must run "
        f"without Qt (it is the seam a C++ backend replaces), but imports {bad}")


# ----------------------------------------------------------------------
#  the C++ extension is optional, at the source level too
# ----------------------------------------------------------------------
def test_only_accel_imports_the_extension():
    """Everything else must go through pytcad._accel, so there is exactly
    one place that knows whether compiled kernels exist."""
    offenders = []
    for path in _python_files("pytcad"):
        if path.name == "_accel.py":
            continue
        src = path.read_text()
        if "import _core" in src or "from ._core" in src:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        f"the extension must be reached through pytcad/_accel.py, not "
        f"imported directly: {offenders}")


def test_accel_cannot_raise_at_import_time():
    """pytcad/__init__.py imports eagerly, so anything _accel can raise at
    module scope breaks `import pytcad` for a checkout with no compiler."""
    src = (ROOT / "pytcad" / "_accel.py").read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import,
                             ast.ImportFrom, ast.Assign, ast.Expr, ast.Try)):
            continue
        pytest.fail(f"unexpected module-scope statement in _accel.py: "
                    f"{type(node).__name__} at line {node.lineno}")
    assert "warnings.warn" not in src, "no module-scope warnings in _accel.py"


# ----------------------------------------------------------------------
#  the existing controller seam, restated here so the whole layering
#  story lives in one file as well as in gui/tests/
# ----------------------------------------------------------------------
def test_controllers_never_import_the_numerical_core():
    offenders = {}
    for path in _python_files("gui", "controllers"):
        bad = _imported_top_level_modules(path) & {"pytcad"}
        if bad:
            offenders[path.relative_to(ROOT)] = sorted(bad)
    assert not offenders, (
        f"controllers must reach core math through services, not directly: "
        f"{offenders}")
