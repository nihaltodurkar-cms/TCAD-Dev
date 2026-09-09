"""Optional compiled-kernel dispatch.

The C++ engine (`pytcad._core`) is ALWAYS optional.  Every accelerated
function keeps its pure-Python body -- renamed `_<name>_py` -- and this
module decides which one runs.  Two things depend on that being true:

  * A checkout with no compiler, no CMake and no `_core.so` must pass the
    full test suite.  That is the migration's undo button: at every
    commit, deleting the extension returns the project to a state whose
    behavior is already gated by ~30k lines of existing tests.

  * The Python body is the ORACLE.  `tests/test_accel_parity.py` runs
    both paths over the same fixtures and asserts `np.array_equal`, so
    the reference has to still be there, and still be reachable, to
    compare against.  A "port" that deletes what it replaced cannot be
    checked.

Control with the PYTCAD_ACCEL environment variable:

    auto  (default)  use _core when importable, else Python
    0                force the Python path even if _core is present
    1                require _core; raise at first use if unavailable

This module must never raise at import time.  `pytcad/__init__.py`
imports its submodules eagerly, so anything that can fail here fails
`import pytcad` itself -- which is precisely the failure mode the
soft-import exists to prevent.  No library probing, no version checks,
no module-scope warnings.
"""
import os

__all__ = ["HAVE_ACCEL", "use_accel", "core", "status"]

try:
    from . import _core as _core_mod
except ImportError:          # not built, or built for another Python
    _core_mod = None

HAVE_ACCEL = _core_mod is not None

core = _core_mod


def _mode():
    raw = os.environ.get("PYTCAD_ACCEL", "auto").strip().lower()
    return raw if raw in ("auto", "0", "1") else "auto"


def use_accel():
    """True if compiled kernels should be used for this call.

    Read per call, not cached, so a test can flip PYTCAD_ACCEL with
    monkeypatch.setenv and exercise both paths in one process -- which is
    what makes the parity tests cheap enough to run every time.
    """
    mode = _mode()
    if mode == "0":
        return False
    if mode == "1":
        if not HAVE_ACCEL:
            raise ImportError(
                "PYTCAD_ACCEL=1 requires the compiled extension "
                "pytcad._core, which is not importable.  Build it with:\n"
                "  cmake -S core -B build/dev -G Ninja "
                "-DTCAD_INPLACE_OUTPUT=ON\n"
                "  cmake --build build/dev\n"
                "or unset PYTCAD_ACCEL to fall back to the Python path.")
        return True
    return HAVE_ACCEL


def status():
    """A one-line human-readable summary, for test output and bug reports."""
    if not HAVE_ACCEL:
        return "pytcad._core: not built (pure-Python reference path)"
    return (f"pytcad._core: {_core_mod.__version__}, "
            f"threads={_core_mod.thread_count()}, PYTCAD_ACCEL={_mode()}")


# ----------------------------------------------------------------------
#  Array normalization at the boundary
# ----------------------------------------------------------------------
# The compiled kernels take exactly c-contiguous (n, 3) float64 nodes and
# c-contiguous int64 connectivity -- the nanobind signatures REJECT
# anything else rather than silently converting, which is the point: a
# hidden conversion is a hidden ~100 MB copy on a large mesh. So the
# conversion happens here, once, visibly.
#
# The int64 rule matters beyond tidiness. The reference does
# `np.asarray(tets, dtype=int)`, and numpy's `int` is C `long` -- int64
# on Linux but **int32 on Windows**. Pinning the boundary to int64 keeps
# the extension's ABI identical on both, at the cost of one no-op cast
# on Linux.
import numpy as _np


def as_nodes3(a):
    """A c-contiguous (n, 3) float64 view of a node-coordinate array.

    Accepts (n, 2) as well -- several 2D callers pass xy only, and the
    2D kernels read just the first two columns, so zero-padding the
    third is exact rather than merely harmless.
    """
    a = _np.asarray(a, dtype=_np.float64)
    if a.ndim != 2 or a.shape[1] < 2:
        raise ValueError(f"nodes must be (n, >=2), got {a.shape}")
    if a.shape[1] == 3:
        return _np.ascontiguousarray(a)
    out = _np.zeros((a.shape[0], 3), dtype=_np.float64)
    out[:, :min(a.shape[1], 3)] = a[:, :3]
    return out


def as_idx(a, cols):
    """A c-contiguous (n, cols) int64 view of a connectivity array."""
    a = _np.ascontiguousarray(a, dtype=_np.int64)
    if a.ndim != 2 or a.shape[1] != cols:
        raise ValueError(f"connectivity must be (n, {cols}), got {a.shape}")
    return a


def as_edge_list(a):
    """A c-contiguous (n, 2) int64 edge list.

    Tolerates the shape-(0,) empty array the reference returns for an
    empty mesh (`np.array(sorted({}), dtype=int)` has no second axis).
    """
    a = _np.ascontiguousarray(a, dtype=_np.int64)
    if a.size == 0:
        return _np.zeros((0, 2), dtype=_np.int64)
    return as_idx(a, 2)


def match_empty_edges(edges):
    """Reference parity for the empty case.

    `build_unstructured_stencil` returns `np.array(sorted({}), dtype=int)`
    when a mesh has no edges, which is shape **(0,)**, not (0, 2). The
    kernel always produces (n, 2), so collapse it here rather than
    letting a caller see a shape the Python path would never return.
    """
    return edges.reshape(0) if edges.shape[0] == 0 else edges
