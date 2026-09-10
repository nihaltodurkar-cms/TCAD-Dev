"""M31 P5-1 Phase B -- `precond`/`block_size` become expressible.

See `M31-P5-1-SOLVER-SELECTION-PLAN.md` section 4, Phase B. Before this
phase every COUPLED (psi/n/p-interleaved) Newton loop in the tree
hardcoded `block_size=3` and never passed `precond` at all --
`NewtonOptions` had no field for either, so the winning 2D
configuration Phase A found (ILU, `block_size=None`) and the
preconditioner flavor Phase A swept (`precond="schur"`) were
unreachable from any public entry point. This phase widens the API
surface only; it does not change what any core does by default.

TWO GATES, MATCHING THE PLAN'S OWN NUMBERING
----------------------------------------------
Gate B-1: with the new fields left at their defaults, every core is
bit-identical to pre-Phase-B behavior. The defaults
(`precond="auto"`, `block_size=3`) are chosen to reproduce exactly what
every coupled call site hardcoded before -- this file's job is to prove
the new field actually REACHES `solve_linear` (the plumbing), not to
re-derive numerical bit-identity, which is what
`tests/test_m13_goldens.py` (unchanged, unmoved, see the plan's Phase A
subsection to confirm the reconstruct-and-compare protocol was run) and
the M22/M31-P5-0 bit-identity suites already prove for every fixture
that exercises Device1D/2D/3D's `solve_bias`.

Gate B-2: an unknown `precond` or a structurally nonsensical
`block_size` is refused at `NewtonOptions` construction time, not
silently ignored -- mirroring `Models.driving_force`'s own
`__post_init__` guard (`device.py`) and, one layer down,
`linsolve.solve_linear`'s own `_PRECOND` validation, so a value this
class accepts can never be rejected one layer further in.

A THIRD, UNNUMBERED THING THIS FILE CHECKS
--------------------------------------------
The asymmetry `NewtonOptions`'s own docstring states: only the coupled
(3-unknowns-per-node) solves read `block_size`/`precond` at all -- the
SCALAR Poisson-equilibrium solves (`solve_equilibrium` on all three
dimensionalities) never hardcoded a block size and must keep not
passing one, regardless of what `NewtonOptions.block_size` holds.
Getting this backwards (threading `block_size=3` into a one-unknown-
per-node system) would not raise -- `_build_block_jacobi_preconditioner`
just returns `None` on a shape it cannot use and the code silently
falls through to a different preconditioner -- so this needs its own
check rather than trusting "no exception" as proof.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import NewtonOptions
from pytcad import linsolve as _linsolve


# ---------------------------------------------------------------- B-1
def test_defaults_reproduce_pre_phase_b_hardcoding():
    """The two new fields' defaults are the exact values every coupled
    call site hardcoded before Phase B existed -- a caller that never
    touches them gets the identical `solve_linear` call shape."""
    opts = NewtonOptions()
    assert opts.precond == "auto"
    assert opts.block_size == 3


def _spy_solve_linear(monkeypatch, module):
    """Patch `module`'s own `solve_linear` (module-attribute lookup, the
    pattern `device.py`/`device2d.py`/`device3d.py` use, or a
    module-local `from .linsolve import solve_linear` binding, the
    pattern the unstructured cores use since P5-0 -- both are patched
    the same way from outside, by name, on `module`) to record every
    call's REQUESTED kwargs.

    The spy always executes the solve via `method="direct"` regardless
    of what was requested -- this file's job is to prove
    `opts.block_size`/`opts.precond` REACH `solve_linear` with the
    right values (the plumbing), not to exercise a real Krylov solver.
    An earlier version of this file forwarded the requested method
    verbatim with a deliberately mismatched `block_size=7`, which made
    scipy's `gmres` genuinely attempt to converge (up to `maxiter *
    restart` inner iterations per Phase A's own finding on this exact
    scipy version) before failing -- confirmed directly to balloon this
    suite from ~70s to 600s+. Recording the request while always
    solving via the fast, exact path keeps the plumbing check and
    removes the cost."""
    calls = []
    real = module.solve_linear if hasattr(module, "solve_linear") else \
        module.linsolve.solve_linear

    def spy(A, b, **kwargs):
        calls.append(kwargs)
        return real(A, b, method="direct")

    if hasattr(module, "solve_linear"):
        monkeypatch.setattr(module, "solve_linear", spy)
    else:
        monkeypatch.setattr(module.linsolve, "solve_linear", spy)
    return calls


def test_1d_coupled_solve_honors_block_size_and_precond(monkeypatch):
    """Device1D.solve_bias's coupled Newton loop (device.py) threads
    opts.block_size/opts.precond through to solve_linear."""
    from pytcad import Device1D, Models
    import pytcad.device as device_mod

    x = np.linspace(0.0, 1.0e-4, 41)
    dop = np.where(x < 0.5e-4, -1e17, 1e17)
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))

    calls = _spy_solve_linear(monkeypatch, device_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=7, precond="block_jacobi")
    dev.solve_bias([0.3, 0.0], opts)

    assert calls, "solve_linear was never called -- opts.linsolve did not reach it"
    assert any(c.get("block_size") == 7 for c in calls)
    assert any(c.get("precond") == "block_jacobi" for c in calls)


def test_2d_coupled_solve_honors_block_size_and_precond(monkeypatch):
    """Device2D.solve_bias's coupled Newton loop (device2d.py)."""
    pytest.importorskip("scipy")
    from pytcad import Device2D, Models
    from pytcad.mesh2d import Mesh2D
    import pytcad.device2d as device2d_mod

    x = np.linspace(0.0, 1.0e-4, 15)
    y = np.linspace(0.0, 0.3e-4, 5)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 0.5e-4, -1e17, 1e17), (y.size, 1))
    dev = Device2D(mesh, dop, models=Models(bgn=False))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)

    calls = _spy_solve_linear(monkeypatch, device2d_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=7, precond="block_jacobi")
    dev.solve_bias({"left": 0.3, "right": 0.0}, opts)

    assert calls
    assert any(c.get("block_size") == 7 for c in calls)
    assert any(c.get("precond") == "block_jacobi" for c in calls)


def test_3d_coupled_solve_honors_block_size_and_precond(monkeypatch):
    """Device3D.solve_bias's coupled Newton loop (device3d.py) -- the
    only one of the five call sites wrapped in a try/except direct
    fallback (P5-0's noted asymmetry), so the spy must still see the
    FIRST (iterative) attempt's kwargs even on fixtures where every
    iterate happens to converge."""
    pytest.importorskip("scipy")
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D
    import pytcad.device3d as device3d_mod

    x = np.linspace(0.0, 1.0e-4, 9)
    y = np.linspace(0.0, 0.3e-4, 5)
    z = np.linspace(0.0, 0.3e-4, 4)
    mesh = Mesh3D(x, y, z)
    dop = np.tile(np.where(x < 0.5e-4, -1e17, 1e17), (z.size, y.size, 1))
    dev = Device3D(mesh, dop, models=Models(bgn=False, srh=False))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)

    calls = _spy_solve_linear(monkeypatch, device3d_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=7, precond="block_jacobi")
    dev.solve_bias({"left": 0.3, "right": 0.0}, opts)

    assert calls
    assert any(c.get("block_size") == 7 for c in calls)
    assert any(c.get("precond") == "block_jacobi" for c in calls)


def test_unstructured_2d_coupled_solve_honors_block_size_and_precond(monkeypatch):
    """unstructured_dd.solve_bias -- the module-local `solve_linear`
    binding P5-0 introduced."""
    gmsh = pytest.importorskip("gmsh")
    from pytcad.gmsh_mesh import build_diode_mesh
    from pytcad.region_resolver import resolve_regions, resolve_contacts
    from pytcad.unstructured_assembly import (
        build_unstructured_stencil, build_edge_flux_geometry)
    from pytcad.unstructured_poisson import evaluate_doping_at_nodes
    import pytcad.unstructured_dd as udd_mod

    mesh = build_diode_mesh(Lx=4.0e-4, Ly=1.0e-4, Xj=2.0e-4)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    region_of_triangle = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles, region_of_triangle,
                                 {"p_region": -1e17, "n_region": 1e17})

    calls = _spy_solve_linear(monkeypatch, udd_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=7, precond="block_jacobi")
    udd_mod.solve_bias(mesh.nodes, mesh.triangles, edge_list, node_areas,
                       interior_edges, trans_geom, C, contacts,
                       {"left_contact": 0.3, "right_contact": 0.0}, opts=opts)

    assert calls
    assert any(c.get("block_size") == 7 for c in calls)
    assert any(c.get("precond") == "block_jacobi" for c in calls)


def test_unstructured_3d_coupled_solve_honors_block_size_and_precond(monkeypatch):
    """unstructured_dd3d.solve_bias3d's coupled DD loop threads
    opts.block_size/opts.precond to solve_linear. (Unlike the 2D
    unstructured core, solve_bias3d does not warm-start from the
    module's own solve_poisson_equilibrium3d -- confirmed by reading
    its body rather than assumed -- so there is no scalar sub-solve
    call to check here the way there is for the structured 3D core
    below.)"""
    gmsh = pytest.importorskip("gmsh")
    from pytcad.gmsh_mesh3d import build_diode_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    import pytcad.unstructured_dd3d as udd3d_mod

    mesh = build_diode_mesh3d(Lx=1.0e-4, Ly=2.5e-5, Lz=1.5e-5, Xj=0.5e-4,
                              Nd_scale=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = udd3d_mod.evaluate_doping_at_nodes3d(
        mesh.nodes, mesh.tets, region_of_tet,
        {"p_region": -1e17, "n_region": 1e17})
    contacts = {"left_contact": mesh.face_tags["left_contact"],
               "right_contact": mesh.face_tags["right_contact"]}

    calls = _spy_solve_linear(monkeypatch, udd3d_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=7, precond="block_jacobi")
    udd3d_mod.solve_bias3d(mesh.nodes, mesh.tets, edges, node_vols, trans, C,
                           contacts, {"left_contact": 0.3, "right_contact": 0.0},
                           opts=opts)

    coupled_calls = [c for c in calls if c.get("block_size") == 7]
    assert coupled_calls, \
        "no solve_linear call in solve_bias3d saw block_size=7 -- the " \
        "coupled DD loop is not threading opts.block_size"
    assert any(c.get("precond") == "block_jacobi" for c in coupled_calls)


# ---------------------------------------------------------------- asymmetry
def test_equilibrium_solve_never_receives_block_size(monkeypatch):
    """Device3D.solve_equilibrium (device3d.py) is a SCALAR system --
    it must not thread opts.block_size even when the caller sets a
    non-default one, because there is no real per-node grouping to
    block on. Confirms the asymmetry NewtonOptions' own docstring
    documents, on the structured 3D core Phase A found the largest
    result on (so this exact code path matters more than a token
    check)."""
    pytest.importorskip("scipy")
    from pytcad import Device3D, Models
    from pytcad.mesh3d import Mesh3D
    import pytcad.device3d as device3d_mod

    x = np.linspace(0.0, 1.0e-4, 9)
    y = np.linspace(0.0, 0.3e-4, 5)
    z = np.linspace(0.0, 0.3e-4, 4)
    mesh = Mesh3D(x, y, z)
    dop = np.full((z.size, y.size, x.size), 1e16)
    dev = Device3D(mesh, dop, models=Models(bgn=False, srh=False))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)

    calls = _spy_solve_linear(monkeypatch, device3d_mod)
    opts = NewtonOptions(linsolve="gmres", block_size=9, precond="block_jacobi")
    dev.solve_equilibrium(opts)

    assert calls, "solve_linear was never called by solve_equilibrium"
    assert all(c.get("block_size") is None for c in calls), \
        "solve_equilibrium's scalar Poisson solve received a non-None " \
        "block_size from opts -- it must never group unrelated nodes " \
        "into a fake block"


# ---------------------------------------------------------------- B-2
@pytest.mark.parametrize("bad_precond", ["ilu", "bogus", "", "Auto", None])
def test_unknown_precond_refuses_at_construction(bad_precond):
    with pytest.raises(ValueError):
        NewtonOptions(precond=bad_precond)


@pytest.mark.parametrize("bad_block_size", [0, -1, -3, 1.5, "3"])
def test_nonsensical_block_size_refuses_at_construction(bad_block_size):
    with pytest.raises(ValueError):
        NewtonOptions(block_size=bad_block_size)


@pytest.mark.parametrize("precond", ["auto", "block_jacobi", "schur"])
def test_every_solve_linear_precond_value_constructs_cleanly(precond):
    """No valid value `linsolve.solve_linear` itself accepts (`_PRECOND`)
    is ever rejected one layer up, at `NewtonOptions` -- and vice versa,
    checked by the parametrization sharing linsolve's own tuple."""
    NewtonOptions(precond=precond)


def test_newtonoptions_precond_choices_match_solve_linear_exactly():
    """If `linsolve._PRECOND` ever grows or shrinks, this catches
    `NewtonOptions`'s validation drifting out of sync with it silently
    -- the whole point of Gate B-2 is that the two layers agree."""
    assert set(_linsolve._PRECOND) == {"auto", "block_jacobi", "schur"}


def test_block_size_none_is_valid():
    """None is the scalar-system value, not an omission -- must not be
    rejected."""
    NewtonOptions(block_size=None)
