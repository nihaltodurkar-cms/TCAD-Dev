"""Compiled-kernel dispatch. The C++ engine (`pytcad._core`) is
REQUIRED as of 2026-09-16 -- there is no pure-Python fallback path.
Every kernel that used to carry a `_<name>_py` oracle body now calls
straight into `_core`; `require_accel()` below is the single place that
raises a clear, actionable error if the extension is not built.

Build it with:
  cmake -S core -B build/dev -G Ninja -DTCAD_INPLACE_OUTPUT=ON \\
        -DPython_EXECUTABLE=<path to this interpreter>
  cmake --build build/dev
See core/CMakeLists.txt's header comment if the machine has no C++
compiler in the SAME env Python runs in (put the compiler in a
separate conda env and point CMAKE_CXX_COMPILER/CMAKE_AR/CMAKE_RANLIB
at it -- installing a compiler directly into the Python env has
broken PySide6 here once, via a transitive dependency channel switch).

This module must never raise at import time -- only inside
`require_accel()`, called lazily by each kernel wrapper.
`pytcad/__init__.py` imports its submodules eagerly, so anything that
can fail at IMPORT time here fails `import pytcad` itself.
"""
import os

__all__ = ["HAVE_ACCEL", "require_accel", "core", "status", "have_petsc",
           "as_csr_index", "as_field"]

try:
    from . import _core as _core_mod
except ImportError:          # not built, or built for another Python
    _core_mod = None

HAVE_ACCEL = _core_mod is not None

core = _core_mod

_BUILD_HELP = (
    "pytcad requires the compiled extension pytcad._core, which is not "
    "importable. Build it with:\n"
    "  cmake -S core -B build/dev -G Ninja -DTCAD_INPLACE_OUTPUT=ON\n"
    "  cmake --build build/dev\n"
    "(point CMAKE_CXX_COMPILER/CMAKE_AR/CMAKE_RANLIB at a separate "
    "conda env's compiler if this one has none -- see "
    "core/CMakeLists.txt).")


def require_accel():
    """Raise ImportError with actionable build instructions if `_core`
    is not importable; no-op otherwise. Every accelerated kernel
    wrapper calls this before `_accel.core.<kernel>(...)`."""
    if not HAVE_ACCEL:
        raise ImportError(_BUILD_HELP)


def have_petsc():
    """True if the COMPILED PETSc solver backend is available AND
    selected. Two independent things have to hold: the extension was
    compiled against PETSc (CMake's TCAD_WITH_PETSC found it -- the
    pip-only CI job builds without), and PYTCAD_ACCEL has not forced
    the petsc4py path. A False here is never a hard error by itself:
    linsolve.solve_linear(method="petsc") then runs the petsc4py
    backend instead -- a real, independent second implementation
    (M43 phase 4 left this selector alone: unlike the kernels that
    used to fall back to a pure-Python reference for lack of a
    compiler, petsc4py is never a stand-in, and stays selectable this
    way on purpose).

    getattr, not a bare attribute: an extension built before P3b has no
    petsc_available, and a stale .so must degrade rather than crash.
    """
    if not HAVE_ACCEL:
        return False
    if os.environ.get("PYTCAD_ACCEL", "").strip() == "0":
        return False
    probe = getattr(_core_mod, "petsc_available", None)
    return bool(probe is not None and probe())


def have_mumps():
    """True if the COMPILED PETSc backend is available and selected (see
    have_petsc) AND its PETSc has MUMPS, i.e. linsolve.solve_linear(
    method="mumps") can run through pytcad._core. getattr for the same
    stale-.so reason as have_petsc."""
    if not have_petsc():
        return False
    probe = getattr(_core_mod, "mumps_available", None)
    return bool(probe is not None and probe())


def status():
    """A one-line human-readable summary, for test output and bug reports."""
    if not HAVE_ACCEL:
        return "pytcad._core: not built (accelerated kernels unavailable)"
    petsc = getattr(_core_mod, "petsc_available", None)
    if petsc is not None and petsc():
        # The index width is worth printing: conda-forge's default PETSc
        # is 32-bit, which is a real ceiling (>2^31 nonzeros) rather than
        # a detail, and it is invisible from Python otherwise.
        where = (f"petsc={_core_mod.petsc_version()}"
                 f"/{_core_mod.petsc_index_bytes() * 8}-bit-int")
    else:
        where = "petsc=no"
    return (f"pytcad._core: {_core_mod.__version__}, "
            f"threads={_core_mod.thread_count()}, {where}")


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


def as_csr_index(a):
    """A c-contiguous 1-D int64 view of a CSR indptr/indices array.

    int64 even though conda-forge's PETSc uses a 32-bit PetscInt: the
    boundary rule above applies here too, and the C++ side converts once
    (range-checked) rather than every caller having to ask how PETSc was
    configured.  scipy hands out int32 CSR indices for small matrices and
    int64 for large ones, so SOME normalization was going to happen
    either way -- doing it here keeps it visible and in one place.
    """
    a = _np.ascontiguousarray(a, dtype=_np.int64)
    if a.ndim != 1:
        raise ValueError(f"CSR index array must be 1-D, got {a.shape}")
    return a


def as_field(a):
    """A c-contiguous 1-D float64 view of a nodal or cell field.

    The P4 kernels (indicators, diffusion) take several of these, and
    they take them ALREADY TRANSFORMED where a transcendental is
    involved -- `np.log(n)` rather than `n`, the nodal Debye lengths
    rather than the doping.  That split is deliberate: numpy's `log`
    and C++'s are two independent implementations, and the parity gate
    compares with `np.array_equal`, so the only defensible thing to do
    is compute such a value ONCE, in numpy, and hand the result down.
    """
    a = _np.ascontiguousarray(a, dtype=_np.float64)
    if a.ndim != 1:
        raise ValueError(f"field must be 1-D, got {a.shape}")
    return a


def match_empty_edges(edges):
    """Reference parity for the empty case.

    `build_unstructured_stencil` returns `np.array(sorted({}), dtype=int)`
    when a mesh has no edges, which is shape **(0,)**, not (0, 2). The
    kernel always produces (n, 2), so collapse it here rather than
    letting a caller see a shape the Python path would never return.
    """
    return edges.reshape(0) if edges.shape[0] == 0 else edges
