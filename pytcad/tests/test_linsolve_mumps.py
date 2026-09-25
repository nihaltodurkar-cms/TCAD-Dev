"""`solve_linear(method="mumps")`: an exact sparse LU through PETSc/MUMPS,
and `select_auto`'s 3D structured coupled cell moving to it.

WHY (2026-09-24): `auto` resolved Device3D.solve_bias to scipy gmres +
node block-Jacobi on the strength of ONE fixture (S3D, a cube-shaped
diode, where SuperLU's fill-in is heavy and GMRES converges fast). On a
thin, gated mesh the ranking inverts -- measured on the tri-gate FinFET
of tests/test_model_benchmarks.py's M26 gate, GMRES is several times
slower than a direct solve and gets worse as the channel inverts, while
PETSc GMRES stops converging outright. MUMPS LU is exact on both shapes
and competitive with the fastest option on each (the study numbers live
in linsolve._AUTO_EVIDENCE's reason for the cell, from
benchmarks/preconditioners.py, not here).

Gates:
  M-1  method="mumps" solves to direct precision on a real device
       Jacobian (not a tolerance-loose iterative answer).
  M-2  both PETSc backends (compiled and petsc4py) agree bit-for-bit,
       the same contract method="petsc" has.
  M-3  with no MUMPS-capable backend, method="mumps" raises
       LinearSolveError (which every caller already falls back on) and
       select_auto resolves to "direct" instead of recommending a method
       that cannot run.
  M-4  select_auto's (3, False, True) cell resolves to "mumps" above its
       floor when MUMPS is available.
"""
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from pytcad import _accel, linsolve


def _device_jacobian_3d():
    """A real coupled (psi, n, p) Jacobian from a small structured 3D
    diode under forward bias -- the shape Device3D.solve_bias hands to
    solve_linear."""
    from pytcad import Device3D, Mesh3D
    from pytcad.mesh import uniform_mesh

    xs = uniform_mesh(1.0e-4, 8)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(1.0e-4, 8))
    Z, _, _ = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    dev = Device3D(mesh, np.where(Z < 0.5e-4, 1e17, -1e16).ravel())
    jj, ii = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nx), indexing="ij")
    jj, ii = jj.ravel(), ii.ravel()
    dev.add_contact("top", i=ii, j=jj, k=np.zeros_like(ii))
    dev.add_contact("bot", i=ii, j=jj, k=np.full_like(ii, mesh.Nz - 1))
    dev.solve_equilibrium()

    captured = []
    orig = linsolve.solve_linear

    def spy(A, b, **kw):
        if A.shape[0] == 3 * dev.N and not captured:
            captured.append((sp.csr_matrix(A, copy=True), np.array(b, copy=True)))
        return orig(A, b, **kw)

    linsolve.solve_linear = spy
    try:
        from pytcad import NewtonOptions
        dev.solve_bias({"top": 0.0, "bot": 0.3}, NewtonOptions(linsolve="direct"))
    finally:
        linsolve.solve_linear = orig
    assert captured, "solve_bias never reached solve_linear"
    return captured[0]


@pytest.fixture(scope="module")
def jac3d():
    return _device_jacobian_3d()


_needs_mumps = pytest.mark.skipif(
    not linsolve.mumps_available(),
    reason="no MUMPS-capable PETSc backend (compiled _core or petsc4py)")


@_needs_mumps
def test_m1_mumps_matches_direct_to_factorization_precision(jac3d):
    A, b = jac3d
    x, info = linsolve.solve_linear(A, b, method="mumps")
    ref = spsolve(A.tocsc(), b)
    assert info["method"] == "mumps"
    assert info["converged"] is True
    assert info["residual"] < 1e-12
    assert np.linalg.norm(x - ref) / np.linalg.norm(ref) < 1e-10


@pytest.mark.skipif(
    not (_accel.have_mumps() and linsolve._petsc4py_has_mumps()),
    reason="needs BOTH a MUMPS-enabled compiled backend and petsc4py+MUMPS")
def test_m2_mumps_backends_are_bit_identical(monkeypatch, jac3d):
    A, b = jac3d
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    xc, ic = linsolve.solve_linear(A, b, method="mumps")
    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    xp, ip = linsolve.solve_linear(A, b, method="mumps")
    assert ic["backend"] == "cpp"
    assert ip["backend"] == "petsc4py"
    assert np.array_equal(xc, xp)


def test_m3_unavailable_mumps_raises_and_auto_refuses(monkeypatch, jac3d):
    monkeypatch.setattr(_accel, "have_mumps", lambda: False)
    monkeypatch.setattr(linsolve, "_petsc4py_has_mumps", lambda: False)
    assert not linsolve.mumps_available()
    A, b = jac3d
    with pytest.raises(linsolve.LinearSolveError, match="MUMPS"):
        linsolve.solve_linear(A, b, method="mumps")
    method, reason = linsolve.select_auto(3, False, True, dof=10**6)
    assert method == "direct"
    assert "MUMPS" in reason


@_needs_mumps
def test_m4_auto_resolves_3d_structured_coupled_to_mumps():
    entry = linsolve._AUTO_EVIDENCE[(3, False, True)]
    assert entry["method"] == "mumps"
    method, reason = linsolve.select_auto(3, False, True, dof=entry["min_dof"])
    assert method == "mumps"
    assert reason == entry["reason"]


def test_mumps_is_a_listed_method():
    assert "mumps" in linsolve._METHODS
