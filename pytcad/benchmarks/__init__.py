"""pyTCAD benchmark suite (M32).

Permanent, reproducible performance cases B1-B7 plus the section-35
dashboard. See README.md in this directory for what each number means
and how to run it.

Nothing here imports at package-import time beyond the stdlib: the
cases import pytcad lazily inside their builders, so `import benchmarks`
stays cheap and cannot fail on an optional dependency.
"""
from .cases import CASES, Case, get           # noqa: F401
from .harness import Row, environment, run_all, run_case, to_dict  # noqa: F401
from .dashboard import render_markdown        # noqa: F401

__all__ = ["CASES", "Case", "get", "Row", "environment", "run_all",
           "run_case", "to_dict", "render_markdown"]
