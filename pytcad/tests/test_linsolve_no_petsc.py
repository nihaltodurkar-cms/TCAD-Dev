"""`linsolve="auto"` on a machine with NO PETSc backend.

Every `_AUTO_EVIDENCE` cell whose measured winner is method="petsc" used
to resolve to "petsc" regardless of whether PETSc could run. Without it,
each Newton iterate raised LinearSolveError and fell back to a sparse
DIRECT solve -- on this project's 3D cases that is the slow path the
cell exists to avoid (Windows, 2026-09-25: B4 full 187.3s, B5 full
128.5s, B9 full 7.4s). Those cells now carry a measured `no_petsc`
alternative (scipy gmres -- the same Krylov method the petsc path runs),
used ONLY when no PETSc backend exists. With PETSc present nothing moves.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import _accel, linsolve

PETSC_CELLS = sorted(c for c, e in linsolve._AUTO_EVIDENCE.items()
                     if e["method"] == "petsc")


@pytest.fixture
def no_petsc(monkeypatch):
    monkeypatch.setattr(linsolve, "petsc_available", lambda: False)


@pytest.fixture
def with_petsc(monkeypatch):
    monkeypatch.setattr(linsolve, "petsc_available", lambda: True)


def test_np1_petsc_available_reflects_both_backends(monkeypatch):
    monkeypatch.setattr(_accel, "have_petsc", lambda: False)
    monkeypatch.setattr(linsolve, "_HAVE_PETSC4PY", False)
    assert linsolve.petsc_available() is False
    monkeypatch.setattr(linsolve, "_HAVE_PETSC4PY", True)
    assert linsolve.petsc_available() is True
    monkeypatch.setattr(linsolve, "_HAVE_PETSC4PY", False)
    monkeypatch.setattr(_accel, "have_petsc", lambda: True)
    assert linsolve.petsc_available() is True


def test_np2_every_petsc_cell_has_measured_no_petsc_alternative():
    assert PETSC_CELLS, "expected at least one petsc cell"
    for cell in PETSC_CELLS:
        alt = linsolve._AUTO_EVIDENCE[cell].get("no_petsc")
        assert alt is not None, f"{cell} has no no_petsc entry"
        assert alt["method"] in linsolve._METHODS
        assert alt["method"] not in ("petsc", "mumps"), (
            "the no-PETSc alternative must not itself need PETSc")
        # Gate D-2: names a real benchmark case.
        assert any(tag in alt["reason"] for tag in
                   ("B4", "B5", "B9", "U2DP", "U3DP")), alt["reason"]


@pytest.mark.parametrize("cell", PETSC_CELLS)
def test_np3_no_petsc_resolves_to_measured_alternative(no_petsc, cell):
    entry = linsolve._AUTO_EVIDENCE[cell]
    method, reason = linsolve.select_auto(*cell, dof=entry["min_dof"])
    assert method == entry["no_petsc"]["method"]
    assert entry["reason"] in reason
    assert entry["no_petsc"]["reason"] in reason
    assert "No PETSc backend" in reason


@pytest.mark.parametrize("cell", PETSC_CELLS)
def test_np4_floor_still_refuses_without_petsc(no_petsc, cell):
    entry = linsolve._AUTO_EVIDENCE[cell]
    method, reason = linsolve.select_auto(*cell, dof=entry["min_dof"] - 1)
    assert method == "direct"
    assert "refusing to extrapolate" in reason


@pytest.mark.parametrize("cell", PETSC_CELLS)
def test_np5_with_petsc_nothing_moves(with_petsc, cell):
    entry = linsolve._AUTO_EVIDENCE[cell]
    method, reason = linsolve.select_auto(*cell, dof=entry["min_dof"])
    assert method == "petsc"
    assert reason == entry["reason"]


def test_np6_non_petsc_cells_ignore_petsc_availability(monkeypatch):
    for cell, entry in linsolve._AUTO_EVIDENCE.items():
        if entry["method"] == "petsc":
            continue
        got = []
        for avail in (False, True):
            monkeypatch.setattr(linsolve, "petsc_available",
                                lambda a=avail: a)
            got.append(linsolve.select_auto(*cell, dof=entry["min_dof"]))
        assert got[0] == got[1], cell


def test_np7_device3d_equilibrium_without_petsc_matches_direct(monkeypatch):
    """End to end through Device3D.solve_equilibrium's real dispatch
    (B4's geometry at its quick size = the cell's min_dof): resolves to
    the alternative, converges without falling back, and lands on the
    same potential as a forced direct solve."""
    from pytcad import Device3D, Mesh3D, NewtonOptions
    from pytcad.mesh import uniform_mesh

    def build():
        xs = uniform_mesh(1.0e-4, 16)
        mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, 16))
        Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
        return Device3D(mesh, np.where(Z < 0.2e-4, 1e19, -1e17).ravel())

    ref = build()
    ref.solve_equilibrium(NewtonOptions(linsolve="direct"))

    monkeypatch.setattr(linsolve, "petsc_available", lambda: False)
    calls = []
    real = linsolve.solve_linear

    def spy(A, b, *a, **k):
        calls.append(k.get("method"))
        return real(A, b, *a, **k)

    monkeypatch.setattr(linsolve, "solve_linear", spy)
    dev = build()
    dev.solve_equilibrium(NewtonOptions(linsolve="auto"))
    alt = linsolve._AUTO_EVIDENCE[(3, False, False)]["no_petsc"]["method"]
    assert dev.last_auto_method == alt
    assert calls and set(calls) == {alt}, calls   # no direct fallbacks
    assert np.max(np.abs(np.ravel(dev.psi) - np.ravel(ref.psi))) < 1e-10
