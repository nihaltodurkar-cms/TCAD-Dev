"""M31-P5-1-SOLVER-SELECTION-PLAN.md Phase A: per-Newton-iterate
method/preconditioner sweep on the unstructured cores (B8, B9).

WHY THIS IS A SEPARATE MODULE FROM harness.py
----------------------------------------------
`harness.py`/`instrument.py` answer "how fast is the case today" -- one
number (or a few, best-of-`repeats`) per case, meant to be a per-commit
dashboard row. This module answers a different question: "which of
scipy/PETSc x {block_jacobi, ILU, schur} converges, and how does that
change ACROSS a single Newton solve's iterates" -- section 2 of the plan
found the ranking of a fixed preconditioner set INVERTS between B8 (2D)
and B9 (3D), and found the one Jacobian it swept there is not
representative of the whole solve (a 1.99s single-matrix gmres/
block_jacobi solve does not multiply out to B8's measured 117.8s
whole-solve time). That is a study, run occasionally, not a per-commit
row -- Architecture_Master_Plan.md section 36 still applies (no
performance number belongs in a plan or commit message unless it came
from a real run), it just does not belong in the dashboard table.

HOW THE PER-ITERATE MEASUREMENT WORKS
--------------------------------------
The unstructured cores (`unstructured_dd.py`, `unstructured_dd3d.py`)
hold their own `from .linsolve import solve_linear` module-local name
(P5-0), which this module patches per case, exactly like
`instrument.py` does for timing -- nothing in the frozen core is
touched. Unlike `instrument.py`, this patch also OVERRIDES the
`method`/`block_size`/`precond` the call site passes, so a sweep can
force e.g. "gmres + ILU" through code that hardcodes `block_size=3` --
that override is the only way section 3's gap (no core can currently
choose ILU for a coupled solve) can be measured before Phase B closes
it.

THE EMULATED FALLBACK IS A MEASUREMENT DEVICE, NOT A CODE CHANGE
------------------------------------------------------------------
Neither unstructured core has Phase C's per-iterate fallback yet (P5-1
plan section 3, item 3): today a non-converged iterative solve raises
out of the whole Newton loop, which means a config that fails on
iterate 3 of 12 produces NO data for iterates 4-12. This module's patch
catches that failure, records it, and falls back to `method="direct"`
FOR THAT ONE CALL ONLY so the Newton loop can keep going and later
iterates are still measured -- exactly the behavior Phase C is planned
to add for real. This is scaffolding inside the sweep harness, invoked
only from this file; it does not change `unstructured_dd.py` or
`unstructured_dd3d.py`, and every fallback is recorded (`fell_back`),
never silent.

WHAT IS BOUNDED, AND WHY
--------------------------
Section 2 already measured one schur config taking 357s to FAIL a
single linear solve at `maxiter=500`. A 12-iterate Newton loop with
that failure mode at every iterate would cost approaching an hour for
one (case, size, config) cell. Two independent caps exist so a sweep
finishes in bounded time and says so rather than hanging:

  * `maxiter` (default 200, not solve_linear's default 500) bounds a
    single failing iterative solve.
  * `budget_s` (default 180) is a wall-clock cap per (case, config):
    once exceeded, the remaining Newton iterates of that config are
    not run and the result says `aborted="budget exceeded"` -- an
    honest "not measured" rather than a truncated number presented as
    complete.

Neither cap changes what a config that DOES converge reports; they only
bound how long this module spends confirming that one does not.

`maxiter` DOES NOT MEAN THE SAME THING FOR EVERY METHOD
----------------------------------------------------------
Confirmed directly (M31-P5-1-SOLVER-SELECTION-PLAN.md Phase A, first
full-size run): `linsolve.solve_linear`'s `gmres` branch passes
`maxiter` straight to `scipy.sparse.linalg.gmres`, which in the scipy
on this machine (1.17.1) treats it as a count of RESTART CYCLES, not
total iterations -- with `restart=100` (this module's default), a
`maxiter=200` request let one config run to 2025 actual iterations
before converging, an ~10x-100x larger effective budget than the same
`maxiter` gives `bicgstab` (no restart concept, so `maxiter` there is a
literal total-iteration cap) or `method="petsc"` (PETSc's
`KSP.setTolerances(max_it=maxiter)` is also literal). A sweep that uses
one `maxiter` value across all four methods is therefore NOT
apples-to-apples unless it is generous enough that none of
bicgstab/petsc is starved by it -- which is why this module's default
is 2000, not the smaller value an earlier run used and had to correct
afterward (see the plan's "Phase A -- FULL-SIZE RESULTS" section for
the specific numbers that turned out to be a starvation artifact, not a
finding about the method). `budget_s` is the fair, method-independent
constraint; `maxiter` is not, and should be set generously with
`budget_s` doing the real bounding.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import scipy

from pytcad import linsolve as _linsolve
from pytcad.linsolve import LinearSolveError

from .cases import Case, get as _dashboard_get

# label, method, block_size, precond -- see module docstring.
CONFIGS = [
    ("direct", "direct", None, "auto"),
    ("gmres/block_jacobi", "gmres", 3, "block_jacobi"),
    ("gmres/ilu", "gmres", None, "auto"),
    ("gmres/schur", "gmres", 3, "schur"),
    ("bicgstab/block_jacobi", "bicgstab", 3, "block_jacobi"),
    ("bicgstab/ilu", "bicgstab", None, "auto"),
    ("bicgstab/schur", "bicgstab", 3, "schur"),
    ("petsc", "petsc", 3, "auto"),
    # 2026-09-24: exact sparse LU through PETSc/MUMPS -- see F3D below.
    ("mumps", "mumps", None, "auto"),
]

# Which module(s) hold the `solve_linear` name this case's Newton loop
# actually calls -- see the P5-0 module-local-import note in the
# docstring above.
#
# CORRECTION (Phase A-2, 2026-09-10): this comment used to claim
# "B9's exercises unstructured_dd3d, whose solve_bias3d calls its own
# equilibrium sub-solve first". IT DOES NOT. `solve_poisson_equilibrium3d`
# is a separate PUBLIC entry point that `solve_bias3d` never calls --
# `solve_bias3d` cold-starts from an analytic Boltzmann guess, exactly
# like its 2D counterpart. Disproved by measurement, not by re-reading:
# once `IterRecord` recorded `dof`, B9's whole sweep came back with
# dof=[2889] and no 963-row scalar solve anywhere in it. So B9 covers
# (3, True, True) ONLY, and the scalar 3D unstructured cell needs its
# own fixture (U3DP below), just as the 2D one needs U2DP.
CASE_MODULES = {
    "B8": ("unstructured_dd",),
    "B9": ("unstructured_dd3d",),
    # Phase A-2: the scalar unstructured cells, which B8/B9 never
    # reach -- see _u2d_poisson's and _u3d_poisson's docstrings.
    "U2DP": ("unstructured_poisson",),
    "U3DP": ("unstructured_dd3d",),
}


# ----------------------------------------------------------------------
#  Study-only fixtures (NOT dashboard cases)
# ----------------------------------------------------------------------
# Phase A-2 needs one shape the dashboard does not have: a STRUCTURED 3D
# COUPLED bias solve, i.e. `device3d.py:1015`'s `select_auto` site. B4,
# B5 and B7 are all equilibrium-only (B4 by construction -- its `build`
# returns `dev.solve_equilibrium` as the runner), so nothing in
# `cases.py` reaches that call site at all.
#
# It lives HERE, not in `cases.py`, deliberately. Adding a dashboard row
# changes `BASELINE.md`/`FULL.md` and is gated by
# `tests/test_m32_benchmarks.py`; this is a study fixture that exists to
# answer one question about solver selection, and M32's own plan is
# explicit that the dashboard is for per-commit rows rather than
# occasional studies. If a 3D structured coupled solve ever deserves a
# permanent row, that is its own proposal with its own gates.
#
# Sizes are NOT B4's. B4 full is 41^3 = 68,921 nodes, which as a COUPLED
# system is 206,763 unknowns -- M31 section 1's own measurement says a
# direct solve at that scale never completes, so a "full" that large
# would measure only the budget cap. The sizes here bracket the region
# where direct is still finishable, so the comparison is real on both
# sides.
def _s3d_coupled(size, opts=None):
    """B4-SHAPED structured 3D device, driven through a COUPLED
    `solve_bias` rather than `solve_equilibrium`."""
    from pytcad import Device3D, Mesh3D
    from pytcad.mesh import uniform_mesh

    n = 12 if size == "quick" else 20
    xs = uniform_mesh(1.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, n))
    # Same (Nz, Ny, Nx) build order as _b4, for the same reason -- see
    # its comment and history.md's meshgrid gotcha.
    Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    doping = np.where(Z < 0.2e-4, 1e19, -1e17)
    dev = Device3D(mesh, doping.ravel())
    # Device3D has no implicit terminals (unlike Device1D's 2-terminal
    # convention) -- contacts are explicit, one on each side of the
    # z-junction the doping above defines. Same (i, j, k) broadcasting
    # shape tests/test_validation_3d.py uses.
    jj, ii = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nx),
                         indexing="ij")
    jj, ii = jj.ravel(), ii.ravel()
    dev.add_contact("cathode", i=ii, j=jj, k=np.zeros_like(ii), V=0.0)
    dev.add_contact("anode", i=ii, j=jj,
                    k=np.full_like(ii, mesh.Nz - 1), V=0.0)
    dev.solve_equilibrium()      # setup, deliberately outside the sweep

    def run():
        if opts is not None:
            dev.solve_bias({"anode": 0.3, "cathode": 0.0}, opts)
        else:
            dev.solve_bias({"anode": 0.3, "cathode": 0.0})
    return dev, run



def _f3d_coupled(size, opts=None):
    """The tri-gate FinFET of tests/test_model_benchmarks.py's M26 gate
    (pytcad.finfet3d, Lg=0.4 um, 21,888 coupled DOF), driven through a
    gate-voltage sweep of COUPLED `solve_bias` calls -- the same
    `device3d.py` select_auto cell (3, False, True) as S3D, but a thin,
    gated mesh instead of a cube.

    Added 2026-09-24 because S3D alone had decided that cell, and on this
    device the ranking inverts: GMRES slows as the channel inverts while
    SuperLU's fill-in stays small. Equilibrium runs in setup, outside the
    sweep, so only coupled solves are measured (the sweep forces one
    method onto every solve_linear call, and the scalar equilibrium solve
    must not be handed block_size=3 configurations).

    `size` sets the number of gate-voltage points, not the mesh: quick =
    4 points, full = the M26 gate's own 12. The mesh is the gate's."""
    from pytcad.finfet3d import build_finfet3d

    dev = build_finfet3d(Lg=0.4e-6, Lsd=0.3e-6, Hfin=0.3e-6, Wfin=0.2e-6,
                         tox_cm=2e-7, Na=5e17, Nsd_peak=1e19,
                         sigma_y=0.05e-6, sigma_lat=0.05e-6,
                         NX=6, NY=4, NZ=4, mesh_ratio=1.3)
    dev.solve_equilibrium()
    Vg_list = np.linspace(-0.4, 1.2, 4 if size == "quick" else 12)

    def run():
        for Vg in Vg_list:
            bias = {"drain": 0.05, "gate_top": Vg, "gate_left": Vg,
                    "gate_right": Vg}
            if opts is not None:
                dev.solve_bias(bias, opts)
            else:
                dev.solve_bias(bias)
    return dev, run


def _u2d_poisson(size, opts=None):
    """B8's mesh and doping, but driving `unstructured_poisson.
    solve_poisson_equilibrium` -- the `(2, True, False)` cell, i.e.
    `unstructured_poisson.py:141`'s `select_auto` site.

    B8 itself does NOT reach that code: `unstructured_dd.solve_bias`
    cold-starts from an analytic Boltzmann guess rather than running a
    Poisson equilibrium first (confirmed by reading its `init`
    documentation, not assumed from the module name). So the scalar 2D
    unstructured path has never been swept, by B8 or anything else.
    """
    from pytcad.gmsh_mesh import build_diode_mesh
    from pytcad.region_resolver import resolve_regions, resolve_contacts
    from pytcad.unstructured_assembly import (
        build_unstructured_stencil, build_edge_flux_geometry)
    from pytcad.unstructured_poisson import (evaluate_doping_at_nodes,
                                             solve_poisson_equilibrium)

    # Same geometry knob as _b8 -- sized by domain, not by the mesh size
    # field; see that case's docstring for why.
    if size == "quick":
        Lx, Ly, Xj = 4.0e-4, 1.0e-4, 2.0e-4
    else:
        Lx, Ly, Xj = 20.0e-4, 7.0e-4, 10.0e-4
    mesh = build_diode_mesh(Lx=Lx, Ly=Ly, Xj=Xj)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes,
                                                      mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles,
                                 region_of_triangle,
                                 {"p_region": -1e17, "n_region": 1e17})

    def run():
        solve_poisson_equilibrium(mesh.nodes, mesh.triangles, edge_list,
                                  node_areas, interior_edges, trans_geom,
                                  C, contacts, opts=opts)
    return None, run



def _u3d_poisson(size, opts=None):
    """B9's mesh and doping, driving `unstructured_dd3d.
    solve_poisson_equilibrium3d` -- the `(3, True, False)` cell
    (`unstructured_dd3d.py:286`).

    B9 does NOT reach this code, despite living in the same module:
    `solve_bias3d` cold-starts from an analytic Boltzmann guess and
    never calls the Poisson entry point. See the CASE_MODULES
    correction above for how that was established.
    """
    from pytcad.gmsh_mesh3d import build_diode_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    from pytcad.unstructured_dd3d import (evaluate_doping_at_nodes3d,
                                          solve_poisson_equilibrium3d)

    # Same geometry knob as _b9.
    if size == "quick":
        Lx, Ly, Lz, Xj = 1.0e-4, 2.5e-5, 1.5e-5, 0.5e-4
    else:
        Lx, Ly, Lz, Xj = 2.0e-4, 5.0e-5, 3.0e-5, 1.0e-4
    mesh = build_diode_mesh3d(Lx=Lx, Ly=Ly, Lz=Lz, Xj=Xj, Nd_scale=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = evaluate_doping_at_nodes3d(mesh.nodes, mesh.tets, region_of_tet,
                                   {"p_region": -1e17, "n_region": 1e17})
    contacts = {"left_contact": mesh.face_tags["left_contact"],
                "right_contact": mesh.face_tags["right_contact"]}

    def run():
        solve_poisson_equilibrium3d(mesh.nodes, mesh.tets, edges, node_vols,
                                    trans, C, contacts, opts=opts)
    return None, run


_EXTRA_CASES = {
    "S3D": Case("S3D", "3D structured coupled bias",
                "device3d.py:1015 select_auto cell (3, False, True)",
                _s3d_coupled, dim=3,
                notes="study-only fixture, not a dashboard row -- see "
                      "the comment above _s3d_coupled"),
    "F3D": Case("F3D", "3D structured coupled bias, tri-gate FinFET",
                "device3d.py select_auto cell (3, False, True), thin "
                "gated mesh",
                _f3d_coupled, dim=3,
                notes="study-only fixture, not a dashboard row -- see "
                      "_f3d_coupled's docstring"),
    "U2DP": Case("U2DP", "2D unstructured Poisson equilibrium",
                 "unstructured_poisson.py:141 select_auto cell "
                 "(2, True, False)",
                 _u2d_poisson, requires=("gmsh",), dim=2,
                 notes="study-only fixture; B8 does not reach this code "
                       "-- see the comment in _u2d_poisson"),
    "U3DP": Case("U3DP", "3D unstructured Poisson equilibrium",
                 "unstructured_dd3d.py:286 select_auto cell "
                 "(3, True, False)",
                 _u3d_poisson, requires=("gmsh",), dim=3,
                 notes="study-only fixture; B9 does not reach this code "
                       "-- see the CASE_MODULES correction"),
}


def get(name):
    """Dashboard cases first, then this module's study-only fixtures."""
    if name.upper() in _EXTRA_CASES:
        return _EXTRA_CASES[name.upper()]
    return _dashboard_get(name)


@dataclass
class IterRecord:
    call_index: int
    seconds: float
    converged: bool
    iterations: int
    residual: float
    fell_back: bool
    error: str = ""
    # Rows of the system actually handed to solve_linear.  Load-bearing,
    # not decoration: a core that runs a SCALAR equilibrium sub-solve
    # before its COUPLED bias solve (unstructured_dd3d.solve_bias3d does
    # exactly this) reaches TWO different `select_auto` cells through
    # ONE module-local `solve_linear` name, and the only thing that
    # separates them per call is the system size -- N for the scalar
    # Poisson rows, 3N for the coupled rows.  Without this, a B9 sweep
    # silently averages two different questions together.
    dof: int = 0


@dataclass
class ConfigResult:
    label: str
    method: str
    block_size: object
    precond: str
    records: list = field(default_factory=list)
    total_s: float = 0.0
    aborted: str = ""

    def as_dict(self):
        d = asdict(self)
        return d


def _sweep_one(case_name, size, label, method, block_size, precond,
               maxiter, budget_s):
    """Run one (case, size, config) cell, patching every module this
    case's Newton loop reaches `solve_linear` through."""
    case = get(case_name)
    _, run = case.build(size)

    result = ConfigResult(label=label, method=method, block_size=block_size,
                          precond=precond)
    call_index = [0]
    t_start = time.perf_counter()

    def swept_solve_linear(A, b, **kwargs):
        # Ignore the caller's own method/block_size/precond/rtol=default
        # choice for everything the sweep controls; keep whatever else
        # it passed (x0, restart, maxiter override) except maxiter,
        # which this sweep bounds itself.
        idx = call_index[0]
        call_index[0] += 1
        if time.perf_counter() - t_start > budget_s:
            result.aborted = result.aborted or "budget exceeded"
            raise LinearSolveError("preconditioners.py: budget exceeded")
        rtol = kwargs.get("rtol", 1e-10)
        t0 = time.perf_counter()
        try:
            x, info = _linsolve.solve_linear(
                A, b, method=method, rtol=rtol, maxiter=maxiter,
                block_size=block_size, precond=precond)
            dt = time.perf_counter() - t0
            result.records.append(IterRecord(
                call_index=idx, seconds=dt, converged=True,
                iterations=info.get("iterations", 1),
                residual=info.get("residual", float("nan")),
                fell_back=False, dof=int(A.shape[0])))
            return x, info
        except LinearSolveError as exc:
            dt = time.perf_counter() - t0
            if method == "direct":
                # direct has no fallback to fall back TO; record and
                # re-raise so the Newton loop fails honestly, exactly
                # as it does today.
                result.records.append(IterRecord(
                    call_index=idx, seconds=dt, converged=False,
                    iterations=0, residual=float("nan"), fell_back=False,
                    error=str(exc), dof=int(A.shape[0])))
                raise
            # Emulated Phase-C fallback -- see module docstring. Falls
            # back to direct so later iterates are still measured; the
            # failure and its cost are both recorded, never hidden.
            t1 = time.perf_counter()
            xd, infod = _linsolve.solve_linear(A, b, method="direct")
            dt_fb = time.perf_counter() - t1
            result.records.append(IterRecord(
                call_index=idx, seconds=dt + dt_fb, converged=True,
                iterations=infod.get("iterations", 1),
                residual=infod.get("residual", float("nan")),
                fell_back=True, error=str(exc), dof=int(A.shape[0])))
            return xd, infod

    modules = []
    for modname in CASE_MODULES[case_name]:
        mod = __import__(f"pytcad.{modname}", fromlist=["_"])
        modules.append(mod)
    undo = []
    for mod in modules:
        old = getattr(mod, "solve_linear", None)
        if old is None:
            continue
        setattr(mod, "solve_linear", swept_solve_linear)
        undo.append((mod, old))
    try:
        run()
    except LinearSolveError as exc:
        result.aborted = result.aborted or f"Newton loop raised: {exc}"
    except Exception as exc:  # noqa: BLE001 -- a study script must not
        # let one config's unexpected failure kill the whole sweep; the
        # failure itself is the data point.
        result.aborted = result.aborted or f"{type(exc).__name__}: {exc}"
    finally:
        for mod, old in undo:
            setattr(mod, "solve_linear", old)

    result.total_s = time.perf_counter() - t_start
    return result


def run_sweep(cases, sizes, configs=CONFIGS, maxiter=200, budget_s=180.0):
    out = []
    for case_name in cases:
        for size in sizes:
            for label, method, block_size, precond in configs:
                sys.stderr.write(
                    f"[preconditioners] {case_name} {size} {label} ...\n")
                sys.stderr.flush()
                res = _sweep_one(case_name, size, label, method, block_size,
                                 precond, maxiter, budget_s)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                n_fb = sum(1 for r in res.records if r.fell_back)
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, {n_fb} fell back"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
    return out


# ----------------------------------------------------------------------
#  Structured cores (B4 etc.) -- a SEPARATE, smaller sweep
# ----------------------------------------------------------------------
# device3d.py/device2d.py look up `linsolve.solve_linear` through the
# MODULE OBJECT (`from . import linsolve`, then `linsolve.solve_linear`
# at call time), unlike the unstructured cores' `from .linsolve import
# solve_linear` module-local binding -- see CLAUDE.md's CRLF-adjacent
# "read the actual import" discipline. That means the override here has
# to patch the ATTRIBUTE on `pytcad.linsolve` itself, not a name inside
# device3d's own namespace, and the two sweeps are kept as separate
# functions rather than one that guesses which pattern a case uses.
#
# B4's own `solve_equilibrium` is scalar (one unknown -- psi -- per
# node), so `block_size` is always None there and block_jacobi/schur
# cannot apply structurally; only the METHOD varies. That is not a
# limitation of this sweep, it is a structural fact about the equation
# being solved, already reflected in the call site
# (device3d.py:619 passes no block_size).
STRUCTURED_METHODS = ["direct", "gmres", "bicgstab", "petsc"]


def _sweep_structured(case_name, size, method, maxiter, budget_s,
                     block_size=None, precond="auto", label=None,
                     coupled=False):
    """Sweep a STRUCTURED core (device.py / device2d.py / device3d.py).

    `coupled=False` (the default) drives `dev.solve_equilibrium` and
    reproduces the Phase A B4 sweep exactly -- that path is SCALAR (one
    psi per node), so `block_size`/`precond` cannot apply structurally
    and stay at their None/"auto" defaults.

    `coupled=True` drives the case's OWN `run()` instead, which for
    B2/B3 and the 3D coupled fixture below is a `solve_bias` -- three
    interleaved unknowns per node. There `block_size` and `precond` are
    the whole question, not a detail: M22 phase 1 measured scalar ILU
    making NO visible progress in 500 iterations on exactly this
    coupled Jacobian, which is why node-block-Jacobi exists. A coupled
    sweep that varied only the METHOD would therefore be measuring the
    known-bad configuration and calling it "iterative".
    """
    from pytcad.device import NewtonOptions
    from pytcad import linsolve as _mod

    case = get(case_name)
    dev, case_run = case.build(size)

    result = ConfigResult(label=label or method, method=method,
                          block_size=block_size, precond=precond)
    call_index = [0]
    t_start = time.perf_counter()
    real_solve_linear = _mod.solve_linear

    def swept(A, b, **kwargs):
        idx = call_index[0]
        call_index[0] += 1
        if time.perf_counter() - t_start > budget_s:
            result.aborted = result.aborted or "budget exceeded"
            raise LinearSolveError("preconditioners.py: budget exceeded")
        rtol = kwargs.get("rtol", 1e-10)
        t0 = time.perf_counter()
        try:
            x, info = real_solve_linear(A, b, method=method, rtol=rtol,
                                        maxiter=maxiter,
                                        block_size=block_size,
                                        precond=precond)
            dt = time.perf_counter() - t0
            result.records.append(IterRecord(
                call_index=idx, seconds=dt, converged=True,
                iterations=info.get("iterations", 1),
                residual=info.get("residual", float("nan")),
                fell_back=False, dof=int(A.shape[0])))
            return x, info
        except LinearSolveError as exc:
            dt = time.perf_counter() - t0
            if method == "direct":
                result.records.append(IterRecord(
                    call_index=idx, seconds=dt, converged=False,
                    iterations=0, residual=float("nan"), fell_back=False,
                    error=str(exc), dof=int(A.shape[0])))
                raise
            t1 = time.perf_counter()
            xd, infod = real_solve_linear(A, b, method="direct")
            dt_fb = time.perf_counter() - t1
            result.records.append(IterRecord(
                call_index=idx, seconds=dt + dt_fb, converged=True,
                iterations=infod.get("iterations", 1),
                residual=infod.get("residual", float("nan")),
                fell_back=True, error=str(exc), dof=int(A.shape[0])))
            return xd, infod

    _mod.solve_linear = swept
    try:
        if coupled:
            # The case's own run() -- the patch above overrides whatever
            # method it asked for, exactly as _sweep_one does for the
            # unstructured cores, so the case does not need to know it
            # is being swept.
            case_run()
        else:
            opts = NewtonOptions(
                linsolve=method if method != "direct" else "direct")
            dev.solve_equilibrium(opts=opts)
    except LinearSolveError as exc:
        result.aborted = result.aborted or f"Newton loop raised: {exc}"
    except Exception as exc:  # noqa: BLE001 -- see _sweep_one's rationale
        result.aborted = result.aborted or f"{type(exc).__name__}: {exc}"
    finally:
        _mod.solve_linear = real_solve_linear

    result.total_s = time.perf_counter() - t_start
    return result


def run_structured_sweep(cases, sizes, methods=STRUCTURED_METHODS,
                         maxiter=200, budget_s=180.0):
    out = []
    for case_name in cases:
        for size in sizes:
            for method in methods:
                sys.stderr.write(
                    f"[preconditioners] (structured) {case_name} {size} "
                    f"{method} ...\n")
                sys.stderr.flush()
                res = _sweep_structured(case_name, size, method, maxiter,
                                        budget_s)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                n_fb = sum(1 for r in res.records if r.fell_back)
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, {n_fb} fell back"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
    return out


def run_structured_coupled_sweep(cases, sizes, configs=CONFIGS,
                                 maxiter=2000, budget_s=180.0):
    """Phase A-2: the STRUCTURED COUPLED cells Phase A never measured.

    Phase A covered three `(dim, unstructured, coupled)` cells and
    `linsolve.select_auto` refuses every other one by name. Of the five
    it refuses that a caller can actually reach through `auto`, three
    are structured coupled-bias solves -- `device.py:1739`,
    `device2d.py:1000` and `device3d.py:1015` -- and the P5-1 plan's own
    Phase E writeup names them as where more evidence has to come from
    before the default can move.

    Unlike `run_structured_sweep`, this varies the full method x
    block_size x preconditioner grid, because the systems here are
    coupled (see `_sweep_structured`'s docstring).
    """
    out = []
    for case_name in cases:
        for size in sizes:
            for label, method, block_size, precond in configs:
                sys.stderr.write(
                    f"[preconditioners] (structured/coupled) {case_name} "
                    f"{size} {label} ...\n")
                sys.stderr.flush()
                res = _sweep_structured(case_name, size, method, maxiter,
                                        budget_s, block_size=block_size,
                                        precond=precond, label=label,
                                        coupled=True)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                n_fb = sum(1 for r in res.records if r.fell_back)
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, {n_fb} fell back"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
    return out


# ----------------------------------------------------------------------
#  Phase A-2: the FAITHFUL sweep
# ----------------------------------------------------------------------
# Phase A's `_sweep_one`/`_sweep_structured` FORCE a (method,
# block_size, precond) triple onto every solve_linear call, ignoring
# what the call site asked for. That was necessary then: before Phase B
# landed, no core could express "ILU for a coupled solve" at all, so
# forcing was the only way to measure the option that did not exist yet.
#
# It is the WRONG methodology for Phase A-2, and not by a little:
#
#   * Two of Phase A-2's five cells are SCALAR (one unknown per node) --
#     `unstructured_poisson` and `unstructured_dd3d`'s equilibrium
#     sub-solve. Their real call sites pass NO block_size, deliberately.
#     `_build_block_jacobi_preconditioner` only refuses a block_size
#     when `n % block_size != 0`, so forcing block_size=3 onto a scalar
#     system whose node count happens to divide by 3 would silently
#     carve 3x3 "node blocks" out of three UNRELATED rows and measure a
#     preconditioner no caller can ever construct. device.py's own
#     NewtonOptions.block_size comment says exactly this.
#   * Driving a structured core's real `run()` while forcing the method
#     from outside also desynchronises the core from the sweep: the core
#     branches on ITS OWN resolved method, so it would take the
#     `method="direct"` branch (passing no block_size) while the patch
#     quietly ran gmres.
#
# So Phase A-2 builds each case with REAL `NewtonOptions` and lets the
# core decide what to hand `solve_linear`; the patch only RECORDS. Two
# consequences worth stating:
#
#   * No emulated fallback. Phase C landed since Phase A, so every core
#     now HAS a real per-iterate fallback -- this sweep re-raises and
#     lets it run, then records the direct retry as its own call. That
#     is strictly more faithful than Phase A's scaffolding.
#   * `maxiter` is still injected, because no core passes one and
#     `solve_linear`'s default (500) starves bicgstab/petsc relative to
#     gmres+restart -- the exact artifact Phase A had to correct for.
#     This is the one deliberate deviation from "whatever the core does".
def _patch_targets(case_name):
    """(object, attribute) pairs holding the `solve_linear` this case's
    Newton loop actually calls.

    Two import styles exist in the tree and the difference is load-
    bearing: the unstructured cores bind `from .linsolve import
    solve_linear` into their own namespace (so the patch must go on the
    MODULE), while device*.py do `from . import linsolve` and look up
    `linsolve.solve_linear` at call time (so the patch must go on
    `pytcad.linsolve` itself).
    """
    if case_name.upper() in CASE_MODULES:
        return [(__import__(f"pytcad.{m}", fromlist=["_"]), "solve_linear")
                for m in CASE_MODULES[case_name.upper()]]
    return [(_linsolve, "solve_linear")]


# Modules holding a bare `spsolve` in their OWN namespace. Patching
# solve_linear alone is not enough, and this is measured rather than
# defensive: `Device1D.solve_bias`'s direct branch calls
# `spsolve(Jd.tocsc(), rhs)` outright, and so does device2d.py's, so a
# B2/B3 "direct" sweep patched only at solve_linear records ZERO calls
# and reports the baseline as free -- which is exactly what the first
# Phase A-2 run did before this list existed. `instrument.py` carries
# the same list for the same reason. device3d.py by contrast DOES route
# its direct branch through solve_linear, so the cores genuinely differ
# and neither patch point alone covers all of them.
_SPSOLVE_MODULES = ("device", "device2d", "device3d", "unstructured_dd",
                    "unstructured_dd3d", "unstructured_poisson")


def _sweep_faithful(case_name, size, label, method, block_size, precond,
                    maxiter, budget_s):
    from pytcad.device import NewtonOptions

    case = get(case_name)
    opts = NewtonOptions(linsolve=method, block_size=block_size,
                         precond=precond, linsolve_rtol=1e-10)
    _, run = case.build(size, opts=opts)

    result = ConfigResult(label=label, method=method, block_size=block_size,
                          precond=precond)
    call_index = [0]
    t_start = time.perf_counter()
    targets = _patch_targets(case_name)
    reals = [getattr(obj, attr) for obj, attr in targets]
    real_solve = reals[0]

    def _record(idx, t0, A, converged, iterations, residual, err="",
                fell_back=False):
        result.records.append(IterRecord(
            call_index=idx, seconds=time.perf_counter() - t0,
            converged=converged, iterations=iterations, residual=residual,
            fell_back=fell_back, error=err, dof=int(A.shape[0])))

    def recorder(A, b, **kwargs):
        idx = call_index[0]
        call_index[0] += 1
        if time.perf_counter() - t_start > budget_s:
            result.aborted = result.aborted or "budget exceeded"
            raise LinearSolveError("preconditioners.py: budget exceeded")
        kwargs.setdefault("maxiter", maxiter)
        t0 = time.perf_counter()
        try:
            x, info = real_solve(A, b, **kwargs)
        except LinearSolveError as exc:
            # Re-raise: the CORE's own Phase C fallback handles this and
            # its direct retry arrives here as the next recorded call.
            result.records.append(IterRecord(
                call_index=idx, seconds=time.perf_counter() - t0,
                converged=False, iterations=0, residual=float("nan"),
                fell_back=False, error=str(exc), dof=int(A.shape[0])))
            raise
        result.records.append(IterRecord(
            call_index=idx, seconds=time.perf_counter() - t0,
            converged=True, iterations=info.get("iterations", 1),
            residual=info.get("residual", float("nan")),
            fell_back=bool(kwargs.get("method") == "direct"
                           and method != "direct"),
            dof=int(A.shape[0])))
        return x, info

    def make_spsolve_recorder(raw):
        def spsolve_recorder(A, b, *a, **kw):
            idx = call_index[0]
            call_index[0] += 1
            if time.perf_counter() - t_start > budget_s:
                result.aborted = result.aborted or "budget exceeded"
                raise LinearSolveError(
                    "preconditioners.py: budget exceeded")
            t0 = time.perf_counter()
            x = raw(A, b, *a, **kw)
            # spsolve returns a bare x. A direct factorization, so
            # "1 iteration" and no residual -- the same way
            # solve_linear(method="direct") reports itself.
            _record(idx, t0, A, True, 1, float("nan"))
            return x
        return spsolve_recorder

    sp_undo = []
    for _modname in _SPSOLVE_MODULES:
        try:
            _mod = __import__(f"pytcad.{_modname}", fromlist=["_"])
        except ImportError:
            continue
        _raw = getattr(_mod, "spsolve", None)
        if _raw is not None:
            sp_undo.append((_mod, _raw))
            setattr(_mod, "spsolve", make_spsolve_recorder(_raw))

    for obj, attr in targets:
        setattr(obj, attr, recorder)
    try:
        run()
    except Exception as exc:  # noqa: BLE001 -- one config's failure is
        # the data point, not a reason to lose the whole sweep.
        result.aborted = result.aborted or f"{type(exc).__name__}: {exc}"
    finally:
        for (obj, attr), real in zip(targets, reals):
            setattr(obj, attr, real)
        for _mod, _raw in sp_undo:
            setattr(_mod, "spsolve", _raw)

    result.total_s = time.perf_counter() - t_start
    return result


def run_faithful_sweep(cases, sizes, configs=CONFIGS, maxiter=2000,
                       budget_s=180.0):
    out = []
    for case_name in cases:
        for size in sizes:
            for label, method, block_size, precond in configs:
                sys.stderr.write(
                    f"[preconditioners] (faithful) {case_name} {size} "
                    f"{label} ...\n")
                sys.stderr.flush()
                res = _sweep_faithful(case_name, size, label, method,
                                      block_size, precond, maxiter,
                                      budget_s)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                dofs = sorted({r.dof for r in res.records})
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, dofs={dofs}"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
                sys.stderr.flush()
    return out


def _environment():
    from . import harness
    try:
        return harness.environment()
    except AttributeError:
        return {"python": platform.python_version(),
               "numpy": np.__version__, "scipy": scipy.__version__,
               "platform": platform.platform()}


def render_markdown(rows):
    lines = ["# M31 P5-1 Phase A -- preconditioner sweep (per Newton iterate)",
             "",
             "Generated by `python -m benchmarks.preconditioners`. See "
             "`M31-P5-1-SOLVER-SELECTION-PLAN.md` section 4 for what this "
             "measures and why.",
             ""]
    by_case_size = {}
    for r in rows:
        by_case_size.setdefault((r["case"], r["size"]), []).append(r)
    for (case_name, size), group in by_case_size.items():
        lines.append(f"## {case_name} ({size})")
        lines.append("")
        lines.append("| config | calls | total_s | mean_s/call | "
                     "min iters | max iters | fell back | aborted |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in group:
            recs = r["records"]
            n = len(recs)
            mean_s = (r["total_s"] / n) if n else float("nan")
            iters = [rec["iterations"] for rec in recs if rec["converged"]]
            min_i = min(iters) if iters else "-"
            max_i = max(iters) if iters else "-"
            n_fb = sum(1 for rec in recs if rec["fell_back"])
            lines.append(
                f"| {r['label']} | {n} | {r['total_s']:.3g} | {mean_s:.3g} | "
                f"{min_i} | {max_i} | {n_fb} | {r['aborted'] or '-'} |")
        lines.append("")
        lines.append("Per-iterate detail:")
        lines.append("")
        for r in group:
            lines.append(f"**{r['label']}**")
            lines.append("")
            lines.append("| call | seconds | converged | iterations | "
                         "residual | fell_back |")
            lines.append("|---|---|---|---|---|---|")
            for rec in r["records"]:
                lines.append(
                    f"| {rec['call_index']} | {rec['seconds']:.4g} | "
                    f"{rec['converged']} | {rec['iterations']} | "
                    f"{rec['residual']:.3g} | {rec['fell_back']} |")
            lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", default="B8,B9")
    ap.add_argument("--size", default="quick", choices=("quick", "full", "both"))
    ap.add_argument("--maxiter", type=int, default=2000)
    ap.add_argument("--budget", type=float, default=180.0)
    ap.add_argument("--structured", default=None,
                    help="comma-separated structured-core case names "
                         "(e.g. B4) to sweep by METHOD ONLY, via "
                         "dev.solve_equilibrium -- see "
                         "run_structured_sweep's docstring for why this "
                         "is a separate, smaller sweep than --cases")
    ap.add_argument("--structured-coupled", default=None,
                    help="comma-separated STRUCTURED cases whose own "
                         "run() is a coupled solve_bias (B2, B3, S3D) "
                         "to sweep over the full method x block_size x "
                         "preconditioner grid -- Phase A-2, the cells "
                         "linsolve.select_auto currently refuses")
    ap.add_argument("--faithful", default=None,
                    help="comma-separated cases to sweep with Phase "
                         "A-2's FAITHFUL methodology (real NewtonOptions, "
                         "core decides what solve_linear gets, patch only "
                         "records) -- see _sweep_faithful's comment")
    ap.add_argument("--out", default=None,
                    help="write JSON to this path (also prints markdown "
                         "to stdout)")
    args = ap.parse_args(argv)

    cases = args.cases.split(",") if args.cases else []
    sizes = ["quick", "full"] if args.size == "both" else [args.size]

    rows = run_sweep(cases, sizes, maxiter=args.maxiter,
                     budget_s=args.budget) if cases else []
    if args.structured:
        rows += run_structured_sweep(args.structured.split(","), sizes,
                                     maxiter=args.maxiter,
                                     budget_s=args.budget)
    if args.faithful:
        rows += run_faithful_sweep(args.faithful.split(","), sizes,
                                   maxiter=args.maxiter,
                                   budget_s=args.budget)
    if args.structured_coupled:
        rows += run_structured_coupled_sweep(
            args.structured_coupled.split(","), sizes,
            maxiter=args.maxiter, budget_s=args.budget)

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"environment": _environment(), "rows": rows}, f,
                     indent=2)
        sys.stderr.write(f"[preconditioners] wrote {args.out}\n")

    print(render_markdown(rows))


if __name__ == "__main__":
    main()
