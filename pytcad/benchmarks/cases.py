"""The permanent benchmark cases B1-B9 (M32, extended for M31 P5).

`Architecture_Master_Plan.md` section 34 names seven cases and what each
is supposed to test.  This module builds them, plus two the section does
not name: B8 and B9 cover the UNSTRUCTURED path, which section 34 never
had a row for and which M31 P5 is scoped to port.  They are marked as
additions rather than folded in silently, so a reader comparing this
list against section 34 finds the difference explained instead of
apparent.

TWO SIZES, AND WHY
------------------
Every case takes a `size`: "quick" or "full".  This is not a convenience
knob.  A benchmark that only runs in its expensive configuration gets run
once, quoted forever, and never re-measured -- which is exactly the state
section 36's performance rule exists to prevent.  "quick" is sized to run
the whole suite in well under a minute so it can live in CI and be run
casually; "full" is the configuration a published number should come
from.  Both are recorded in the report, so a table can never be mistaken
for the other size.

DEPENDENCIES ARE DECLARED, NOT ASSUMED
--------------------------------------
Cases that need an optional dependency (pyamg, mpi4py, CuPy) declare it
in `requires`.  The harness SKIPS such a case and prints the reason in
the table rather than omitting the row -- an absent row reads as "not
measured yet", a skipped row reads as "cannot be measured here", and
those are different facts.

WHAT THESE CASES DO NOT CLAIM
-----------------------------
They are performance and reproducibility probes, not physics gates.  The
physics is gated by `tests/`, which is where a wrong answer must fail.
A benchmark case asserts only that the solve CONVERGED -- a diverged
solve's timings are meaningless, and reporting them as if they were
comparable would be worse than reporting nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass
class Case:
    """One benchmark case.

    `build` returns `(device, run)`: `device` is the object to
    instrument (or None), `run` is a zero-argument callable performing
    the measured work.  Splitting them this way keeps mesh/doping
    construction OUT of the measured region -- section 35 asks for solver
    timings, and folding setup into them would flatter or penalise a case
    depending on how elaborate its geometry happens to be.
    """

    name: str
    title: str
    tests: str
    build: Callable
    requires: tuple = ()
    dim: int = 1
    notes: str = ""


def _skip_reason(requires):
    """None if every declared dependency imports, else why not."""
    import importlib
    for mod in requires:
        try:
            importlib.import_module(mod)
        except ImportError:
            return f"needs {mod}"
    return None


# ----------------------------------------------------------------------
#  B1 -- 1D Poisson
# ----------------------------------------------------------------------
def _b1(size):
    from pytcad import Device1D
    from pytcad.mesh import uniform_mesh

    n = 2001 if size == "quick" else 200001
    x = uniform_mesh(6.0e-4, n)
    doping = np.where(x < 3.0e-4, -1e16, 1e17)
    dev = Device1D(x, doping)
    return dev, dev.solve_equilibrium


# ----------------------------------------------------------------------
#  B2 -- 1D diode
# ----------------------------------------------------------------------
def _b2(size):
    from pytcad import Device1D, Models
    from pytcad.mesh import uniform_mesh

    n = 401 if size == "quick" else 20001
    x = uniform_mesh(6.0e-4, n)
    doping = np.where(x < 3.0e-4, -1e16, 1e17)
    dev = Device1D(x, doping, models=Models(srh=True))
    dev.solve_equilibrium()          # setup, deliberately outside the timing

    def run():
        dev.solve_bias([0.5, 0.0])
    return dev, run


# ----------------------------------------------------------------------
#  B3 -- 2D MOSFET
# ----------------------------------------------------------------------
def _b3(size):
    from pytcad.mosfet import build_mosfet

    if size == "quick":
        dev = build_mosfet(Lg=0.5e-4, Lsd=0.5e-4, depth=0.6e-4, Na=1e17,
                           Nsd_peak=1e20, tox_cm=3e-7, nx=41, ny=25)
    else:
        dev = build_mosfet(Lg=0.5e-4, Lsd=0.5e-4, depth=0.6e-4, Na=1e17,
                           Nsd_peak=1e20, tox_cm=3e-7, nx=161, ny=97)
    dev.solve_equilibrium()

    def run():
        dev.solve_bias({"gate": 1.0, "drain": 0.1, "source": 0.0, "body": 0.0})
    return dev, run


# ----------------------------------------------------------------------
#  B4 -- 3D MOSFET
# ----------------------------------------------------------------------
def _b4(size, opts=None):
    """`opts`: OPTIONAL NewtonOptions, default None reproduces the
    original behavior exactly (dev.solve_equilibrium's own default).
    Added for M31 P5's re-decision (M31-P5-ASSEMBLY-NEWTON-PLAN.md) to
    measure `linsolve="auto"` (M31 P5-1 Phase D) through the real
    harness rather than by hand -- not used by the dashboard's own
    default-config row, which still calls `case.build(size)` with one
    argument."""
    from pytcad import Device3D, Mesh3D
    from pytcad.mesh import uniform_mesh

    n = 16 if size == "quick" else 40
    xs = uniform_mesh(1.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, n))
    # Device3D reshapes its doping to (Nz, Ny, Nx), so build it in that
    # order directly rather than meshgrid-ing in 'ij' and transposing --
    # the transpose is the exact step history.md records as a silent
    # data-corruption bug when it is forgotten.
    Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    doping = np.where(Z < 0.2e-4, 1e19, -1e17)
    dev = Device3D(mesh, doping.ravel())
    if opts is None:
        return dev, dev.solve_equilibrium
    return dev, lambda: dev.solve_equilibrium(opts)


# ----------------------------------------------------------------------
#  B5 -- 3D SiC MOSFET
# ----------------------------------------------------------------------
def _b5(size):
    from pytcad.sic_vmosfet import build_sic_vmosfet, DEFAULT_PARAMS
    from pytcad import Mesh3D
    from pytcad.mesh import uniform_mesh

    # The cell's own dimensions: x spans one half-cell (Lcell), y the
    # full body+drift+substrate stack, z the cell width (W).
    p = DEFAULT_PARAMS
    n = 12 if size == "quick" else 32
    depth = p.y_body + p.t_drift + p.t_sub
    mesh = Mesh3D(uniform_mesh(p.Lcell, n), uniform_mesh(depth, n),
                  uniform_mesh(p.W, n))
    dev = build_sic_vmosfet(mesh, p)
    return dev, dev.solve_equilibrium


# ----------------------------------------------------------------------
#  B6 -- 3D GaN HEMT  (2D today; see `notes`)
# ----------------------------------------------------------------------
def _b6(size):
    """The heterojunction case.

    Built on the AlGaAs/GaAs HEMT template that `workbench/core/
    templates.py` already ships and `gui/tests/test_m11s5_templates.py`
    already gates, at 2D, rather than on a 3D GaN stack that does not
    exist anywhere in the tree.  What section 34 asks this case to test
    -- heterojunctions, interface charge, high-field transport -- is
    exercised by the material discontinuity, which is the part that
    stresses the solver.  Recorded honestly in the report as 2D AlGaAs/
    GaAs; when a real 3D GaN HEMT exists this case should be repointed
    at it rather than the label quietly widened.
    """
    from pytcad import Device2D, Mesh2D, Models
    from pytcad.materials import GAAS, algaas
    from pytcad.mesh import uniform_mesh

    n = 41 if size == "quick" else 121
    mesh = Mesh2D(uniform_mesh(1.0e-4, n), uniform_mesh(0.4e-4, n))
    ny, nx = mesh.y.size, mesh.x.size

    # The wide-gap barrier over a narrow-gap channel IS the benchmark:
    # the band offset is what makes this a heterojunction case rather
    # than a second 2D MOSFET. x=0.3 is the standard HEMT-barrier mole
    # fraction workbench/core/materials.py already uses.
    barrier = algaas(0.3)
    mats = [barrier if mesh.y[j] < 0.1e-4 else GAAS
            for j in range(ny) for i in range(nx)]

    doping = np.where(mesh.y[:, None] < 0.1e-4, 1e18, -1e15) * np.ones((ny, nx))
    dev = Device2D(mesh, doping.ravel(), material=mats, models=Models())
    return dev, dev.solve_equilibrium


# ----------------------------------------------------------------------
#  B7 -- large synthetic 3D
# ----------------------------------------------------------------------
def _b7(size):
    """DOF scaling. The only case whose point is to be big.

    Uses the iterative path deliberately: section 34 lists AMG/MPI/GPU
    under this case, and the direct solve is exactly what M31's own
    measurement showed hits a wall here (3.0 s @ 8k nodes -> 51.8 s @
    27k -> 64k never completing). Running it "direct" at scale would
    measure the wall, not the solver.
    """
    from pytcad import Device3D, Mesh3D, NewtonOptions
    from pytcad.mesh import uniform_mesh

    # uniform_mesh(L, n) returns n+1 nodes, so size the doping off the
    # mesh rather than off n -- getting this wrong is a reshape error at
    # best and a silently transposed field at worst (see history.md's
    # meshgrid gotcha).
    n = 20 if size == "quick" else 44
    xs = uniform_mesh(2.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), xs.copy())
    # A real 3D junction, not a uniform block: a uniformly-doped device
    # converges in ONE Newton iteration, so it would measure assembly and
    # a single solve rather than the solver doing work at scale -- which
    # is the whole point of this case.
    Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    doping = np.where(Z < 1.0e-4, 1e17, -1e16)
    dev = Device3D(mesh, doping.ravel())
    opts = NewtonOptions(linsolve="bicgstab", linsolve_rtol=1e-10)

    def run():
        dev.solve_equilibrium(opts)
    return dev, run


# ----------------------------------------------------------------------
#  B8 -- 2D unstructured drift-diffusion  (gmsh triangles)
# ----------------------------------------------------------------------
def _b8(size, opts=None):
    """The unstructured 2D path: gmsh triangles, box-integration dual
    cells, coupled [psi, n, p] Newton.

    `opts`: OPTIONAL NewtonOptions, default None reproduces the
    original behavior exactly (solve_bias's own default). Added for
    M31 P5's re-decision to measure `linsolve="auto"` (M31 P5-1 Phase
    D) through the real harness.

    Added ahead of M31 P5, whose scope is exactly this assembler
    (`pytcad/unstructured_dd.py:_residual_jacobian`). Before this case
    existed the code P5 targets had NO row in the dashboard, so the
    phase could not have made a performance claim without violating
    `Architecture_Master_Plan.md` section 36 -- and M32's own plan
    records what happens when the benchmark trails the work it is meant
    to police.

    Sized by GEOMETRY, not by the mesh size field. `build_diode_mesh`
    grades toward the junction off `debye_length(Nd_scale)` but clamps
    the bulk at SizeMax = 2e-5 cm, so Nd_scale barely moves the node
    count (measured: 1e16 -> 2102 nodes, 1e17 -> 3350). Enlarging the
    domain at a fixed cell size is the honest knob, and it keeps the
    physics -- the same p-n junction, the same doping -- identical
    between the two sizes.
    """
    import numpy as np
    from pytcad.gmsh_mesh import build_diode_mesh
    from pytcad.region_resolver import resolve_regions, resolve_contacts
    from pytcad.unstructured_assembly import (
        build_unstructured_stencil, build_edge_flux_geometry)
    from pytcad.unstructured_poisson import evaluate_doping_at_nodes
    from pytcad.unstructured_dd import solve_bias

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
        solve_bias(mesh.nodes, mesh.triangles, edge_list, node_areas,
                   interior_edges, trans_geom, C, contacts,
                   {"left_contact": 0.5, "right_contact": 0.0}, opts=opts)
    # No device object: this core assembles through a module-level
    # function, which instrument.py patches by name.
    return None, run


# ----------------------------------------------------------------------
#  B9 -- 3D unstructured drift-diffusion  (gmsh tets)
# ----------------------------------------------------------------------
def _b9(size, opts=None):
    """The 3D counterpart of B8, on a tet mesh.

    This is the case the whole C++/DMPlex argument is about: an
    unstructured 3D coupled solve is the only path in the tree that a
    distributed `Mat` would ever be built for. It is deliberately small
    even at "full" -- 2,488 nodes solves in ~7.5 s here, against B4's
    68,921-node structured 3D at ~179 s -- because the direct solve on
    a tet mesh's wider stencil hits the wall M31's section 1 measured,
    and a benchmark that never completes measures nothing.

    `opts`: OPTIONAL NewtonOptions, default None reproduces the
    original behavior exactly (solve_bias3d's own default). Added for
    M31 P5's re-decision to measure `linsolve="auto"` (M31 P5-1 Phase
    D) through the real harness.
    """
    import numpy as np
    from pytcad.gmsh_mesh3d import build_diode_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    from pytcad.unstructured_dd3d import (evaluate_doping_at_nodes3d,
                                          solve_bias3d)

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
        solve_bias3d(mesh.nodes, mesh.tets, edges, node_vols, trans, C,
                     contacts,
                     {"left_contact": 0.5, "right_contact": 0.0}, opts=opts)
    return None, run


CASES = [
    Case("B1", "1D Poisson", "PDE IR, BCs, Jacobian", _b1, dim=1),
    Case("B2", "1D diode", "DD, convergence, conservation", _b2, dim=1),
    Case("B3", "2D MOSFET", "device physics, Newton, current continuity",
         _b3, dim=2),
    Case("B4", "3D MOSFET", "3D mesh, memory, solver scaling", _b4, dim=3),
    Case("B5", "3D SiC MOSFET", "traps, high field, avalanche, thermal",
         _b5, dim=3,
         notes="equilibrium only; the avalanche/thermal columns of "
               "section 34 are not exercised by this run"),
    Case("B6", "GaN HEMT (2D AlGaAs/GaAs stand-in)",
         "heterojunctions, interface charge", _b6, dim=2,
         notes="2D AlGaAs/GaAs, not 3D GaN -- see the case docstring"),
    Case("B7", "Large synthetic 3D", "DOF scaling, AMG, MPI, GPU", _b7,
         dim=3,
         notes="iterative (bicgstab) by design; AMG/MPI/GPU columns need "
               "pyamg/mpi4py/CuPy and are reported separately"),
    Case("B8", "2D unstructured DD",
         "gmsh triangles, box integration, coupled Newton", _b8,
         requires=("gmsh",), dim=2,
         notes="the M31 P5 assembler's own case; sized by geometry, not "
               "by the mesh size field -- see the case docstring. One "
               "assembly call is the post-convergence current "
               "extraction, not a Newton iteration"),
    Case("B9", "3D unstructured DD",
         "gmsh tets, dual volumes, coupled Newton", _b9,
         requires=("gmsh",), dim=3,
         notes="the case the DMPlex/distributed-Mat argument is about; "
               "deliberately small even at full size -- see the case "
               "docstring. One assembly call is the post-convergence "
               "current extraction, not a Newton iteration"),
]


def get(name):
    for c in CASES:
        if c.name.lower() == name.lower():
            return c
    raise KeyError(f"no benchmark case {name!r}; have "
                   f"{[c.name for c in CASES]}")
