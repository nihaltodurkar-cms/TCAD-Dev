"""M22 phase-1 gates: linear-solve abstraction (Krylov + ILU).

Gate reference: M22-LINSOLVE-PLAN.md section 3.
"""
import os
import sys

import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad import linsolve


def _random_spd_system(n, seed, density=0.02):
    """A random, strongly diagonally dominant (hence nonsingular and
    well-conditioned) sparse system -- easy for both direct and Krylov
    methods, which is exactly what a parity gate should probe."""
    rng = np.random.default_rng(seed)
    A = sp.random(n, n, density=density, random_state=rng,
                 data_rvs=lambda k: rng.standard_normal(k)).tocsr()
    A = A + A.T
    A = A + sp.diags(np.abs(A).sum(axis=1).A1 + 1.0)
    b = rng.standard_normal(n)
    return A.tocsr(), b


# ---------------------------------------------------------------- G2
def test_direct_method_matches_spsolve_bit_for_bit():
    """G2: solve_linear(method='direct') is spsolve, exactly -- on
    whatever sparse format the caller passes, not a canonicalized copy.

    The reference here used to be spsolve(A.tocsc(), b) regardless of
    A's own format; a hard-debug pass found that scipy's SuperLU
    wrapper solves CSR natively (a format flag, not a Python-side
    conversion), so spsolve(A_csr, b) and spsolve(A_csr.tocsc(), b)
    are only equal to ~1e-16 relative error, NOT bit-identical --
    confirmed empirically. Every pre-M22 call site called plain
    spsolve(A, ...) on whatever format it already had (some CSR, some
    already-CSC), so the honest G2 reference is spsolve(A, b) with no
    reformatting -- reformatting to CSC first is exactly the bug that
    broke the M13/M22 equilibrium-solve goldens when solve_linear's
    "direct" branch used to force .tocsc() before spsolve."""
    for n, seed in ((5, 0), (50, 1), (400, 2)):
        A, b = _random_spd_system(n, seed)
        x, info = linsolve.solve_linear(A, b, method="direct")
        ref = spsolve(A, b)
        assert np.array_equal(x, ref), f"G2 FAIL: n={n} seed={seed}"
        assert info["method"] == "direct"
        assert info["converged"] is True


# ---------------------------------------------------------------- G3
def test_iterative_methods_agree_with_direct_within_rtol():
    """G3: gmres/bicgstab agree with the direct solution within rtol,
    on random well-conditioned systems."""
    for method in ("gmres", "bicgstab"):
        for n, seed in ((30, 10), (300, 11), (2000, 12)):
            A, b = _random_spd_system(n, seed)
            ref = spsolve(A.tocsc(), b)
            x, info = linsolve.solve_linear(A, b, method=method,
                                            rtol=1e-10)
            assert info["converged"], f"{method} n={n} did not converge"
            rel = np.linalg.norm(x - ref) / max(np.linalg.norm(ref), 1e-300)
            assert rel <= 1e-6, \
                f"G3 FAIL: {method} n={n} rel={rel:.3e}"


def test_iterative_methods_on_a_real_device_jacobian():
    """G3 (real physics): the Jacobian of an actual device solve, not
    just a synthetic random system."""
    from pytcad import Device1D, Models, NewtonOptions
    from pytcad.mesh import uniform_mesh

    x = uniform_mesh(6.0e-4, 200)
    dop = np.where(x < 3.0e-4, -1e16, 1e17)
    dev = Device1D(x, dop, T=300.0, models=Models(srh=True))
    dev.solve_equilibrium()
    bc = dev._contact_values([0.3, 0.0])
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    psi[0], n[0], p[0] = bc[0]
    psi[-1], n[-1], p[-1] = bc[1]
    F, J, _, _ = dev._residual_jacobian(psi, n, p, bc)

    ref = spsolve(J.tocsc(), -F)
    for method in ("gmres", "bicgstab"):
        x_it, info = linsolve.solve_linear(J, -F, method=method, rtol=1e-10)
        assert info["converged"]
        rel = np.linalg.norm(x_it - ref) / max(np.linalg.norm(ref), 1e-300)
        assert rel <= 1e-6, f"G3 FAIL: {method} on device Jacobian rel={rel:.3e}"


# ---------------------------------------------------------------- G4
def test_non_convergence_raises_not_silent():
    """G4: an iterative method that cannot converge within maxiter must
    RAISE, never return a half-solved state silently -- the M15 debug
    pass found exactly that failure mode elsewhere in this codebase."""
    n = 200
    rng = np.random.default_rng(99)
    # A poorly conditioned, non-symmetric system with maxiter=1: no
    # Krylov method converges to 1e-12 in one iteration on this.
    A = sp.random(n, n, density=0.05, random_state=rng,
                 data_rvs=lambda k: rng.standard_normal(k)).tocsr()
    A = A + sp.eye(n) * 1e-3          # keep it merely singular-ish, not exactly
    b = rng.standard_normal(n)
    for method in ("gmres", "bicgstab"):
        with pytest.raises(linsolve.LinearSolveError):
            linsolve.solve_linear(A, b, method=method, rtol=1e-14,
                                  maxiter=1)


# ---------------------------------------------------------------- G5
def test_singular_and_non_finite_input_raise():
    """G5: singular or non-finite systems raise clearly under every
    method, rather than returning NaN."""
    n = 10
    A = sp.csr_matrix((n, n))          # all-zero: singular
    b = np.ones(n)
    for method in ("direct", "gmres", "bicgstab"):
        with pytest.raises(linsolve.LinearSolveError):
            linsolve.solve_linear(A, b, method=method)

    A2, b2 = _random_spd_system(10, 1)
    b2 = b2.copy(); b2[3] = np.nan
    for method in ("direct", "gmres", "bicgstab"):
        with pytest.raises(linsolve.LinearSolveError):
            linsolve.solve_linear(A2, b2, method=method)


def test_unknown_method_raises():
    A, b = _random_spd_system(10, 2)
    with pytest.raises(ValueError, match="method"):
        linsolve.solve_linear(A, b, method="not_a_method")


# ---------------------------------------------------------------- G1
def test_default_linsolve_is_bit_identical_to_pre_m22():
    """G1: NewtonOptions() with no linsolve argument reproduces the M13
    goldens exactly.  This is the amendment proof for wiring linsolve
    into the core Newton loops -- it must run before any gate that
    exercises a non-default method."""
    from pytcad import Device1D, Models, NewtonOptions

    GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "goldens", "m13")
    meshes = np.load(os.path.join(GOLDEN_DIR, "frozen_meshes.npz"))
    x = meshes["diode1d_x"]
    dop = np.where(x < 1.0e-4, -1e17, 1e17)
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=True, auger=True))
    dev.solve_equilibrium()
    gold = np.load(os.path.join(GOLDEN_DIR, "diode1d_eq.npz"))
    assert np.array_equal(dev.psi, gold["psi"])
    assert np.array_equal(dev.n, gold["n"])
    assert np.array_equal(dev.p, gold["p"])

    dev.solve_bias([0.6, 0.0], NewtonOptions())
    goldf = np.load(os.path.join(GOLDEN_DIR, "diode1d_fwd.npz"))
    assert np.array_equal(dev.psi, goldf["psi"])
    assert np.array_equal(dev.n, goldf["n"])
    assert np.array_equal(dev.p, goldf["p"])
    assert np.array_equal(dev.Jn, goldf["Jn"])
    assert np.array_equal(dev.Jp, goldf["Jp"])

    assert NewtonOptions().linsolve == "direct"


def test_device1d_bias_solve_with_iterative_linsolve():
    """G3 (end-to-end): solving through Device1D.solve_bias with
    linsolve='gmres' agrees with the direct default within tolerance."""
    from pytcad import Device1D, Models, NewtonOptions
    from pytcad.mesh import uniform_mesh

    x = uniform_mesh(6.0e-4, 150)
    dop = np.where(x < 3.0e-4, -1e16, 1e17)

    d_direct = Device1D(x, dop, T=300.0, models=Models(srh=True))
    d_direct.solve_equilibrium()
    d_direct.solve_bias([0.3, 0.0], NewtonOptions())

    d_iter = Device1D(x, dop, T=300.0, models=Models(srh=True))
    d_iter.solve_equilibrium()
    d_iter.solve_bias([0.3, 0.0],
                      NewtonOptions(linsolve="gmres", linsolve_rtol=1e-10))

    rel_psi = np.abs(d_iter.psi - d_direct.psi).max()
    rel_n = np.abs(d_iter.n / d_direct.n - 1.0).max()
    assert rel_psi <= 1e-6, f"psi mismatch {rel_psi:.3e}"
    assert rel_n <= 1e-5, f"n mismatch {rel_n:.3e}"


# ---------------------------------------------------------------- G6
@pytest.mark.slow
def test_3d_scaling_target_completes():
    """G6: a >=64k-node 3D resistor completes with the iterative path.

    RESOLVED (2026-08-27, same session): plain scalar ILU is not an
    adequate preconditioner for this Jacobian's coupled psi/n/p rows at
    scale -- GMRES made no visible progress in 500 iterations even at
    n=20 (27783 unknowns).  Root cause: ILU treats the matrix as one
    undifferentiated block and ignores the per-node (psi,n,p)
    interleaving every device core in this tree uses.  Fixed with a
    node-block-Jacobi preconditioner (linsolve.solve_linear's
    block_size=3): the SAME 27783-unknown Jacobian that stalled scalar
    ILU converges in 30 iterations / 0.05s with it.  See
    M22-LINSOLVE-PLAN.md section 6.
    """
    import time
    from pytcad import Device3D, Models, NewtonOptions
    from pytcad.mesh import uniform_mesh
    from pytcad.mesh3d import Mesh3D

    n = 40                              # (n+1)^3 = 68921 nodes
    mx = my = mz = uniform_mesh(2.0e-4, n)
    mesh = Mesh3D(mx, my, mz)
    dop = np.full((mz.size, my.size, mx.size), 1e16)
    dev = Device3D(mesh, dop, models=Models(srh=False))
    jj, kk = np.meshgrid(np.arange(my.size), np.arange(mz.size))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("r", i=np.full_like(jj, mx.size - 1), j=jj, k=kk, V=0.1)
    dev.solve_equilibrium()

    t0 = time.time()
    dev.solve_bias({"r": 0.1},
                   NewtonOptions(linsolve="gmres", linsolve_rtol=1e-8,
                                max_iter=60))
    dt = time.time() - t0
    print(f"\nG6: {(n + 1) ** 3} nodes ({3 * (n + 1) ** 3} unknowns), "
          f"block-Jacobi GMRES bias solve = {dt:.2f}s")
    assert np.all(np.isfinite(dev.psi))


def test_block_jacobi_preconditioner_matches_exact_block_inverse():
    """The block extraction/inversion must be exact, not approximate:
    applying the preconditioner to any vector must equal solving each
    node's dense block directly."""
    rng = np.random.default_rng(3)
    n_nodes, bs = 200, 3
    n = n_nodes * bs
    A = sp.lil_matrix((n, n))
    for k in range(n_nodes):
        blk = rng.standard_normal((bs, bs)) * 3 + np.eye(bs) * 10.0
        A[3 * k:3 * k + 3, 3 * k:3 * k + 3] = blk
    # a few off-block-diagonal entries -- the preconditioner must ignore them
    for _ in range(50):
        i, j = rng.integers(0, n, size=2)
        A[i, j] += rng.standard_normal()
    A = A.tocsr()

    M = linsolve._build_block_jacobi_preconditioner(A, bs)
    assert M is not None
    x = rng.standard_normal(n)
    y = M.matvec(x)

    Ad = A.toarray()
    y_ref = np.zeros(n)
    for k in range(n_nodes):
        blk = Ad[3 * k:3 * k + 3, 3 * k:3 * k + 3]
        y_ref[3 * k:3 * k + 3] = np.linalg.solve(blk, x[3 * k:3 * k + 3])
    assert np.abs(y - y_ref).max() < 1e-10


def test_block_jacobi_unsticks_the_coupled_3d_jacobian():
    """Regression pin for the actual M22 G6 finding: the 27783-unknown
    Jacobian that made GMRES+scalar-ILU stall completely (no visible
    residual progress in 500 iterations) converges in well under 100
    iterations once the preconditioner respects the psi/n/p block
    structure."""
    import warnings as _w
    from pytcad import Device3D, Models, NewtonOptions
    from pytcad.mesh import uniform_mesh
    from pytcad.mesh3d import Mesh3D

    n = 20
    mx = my = mz = uniform_mesh(2.0e-4, n)
    mesh = Mesh3D(mx, my, mz)
    dop = np.full((mz.size, my.size, mx.size), 1e16)
    dev = Device3D(mesh, dop, models=Models(srh=False))
    jj, kk = np.meshgrid(np.arange(my.size), np.arange(mz.size))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("r", i=np.full_like(jj, mx.size - 1), j=jj, k=kk, V=0.1)
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        dev.solve_equilibrium()
    F, J, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, {"r": 0.1})

    x, info = linsolve.solve_linear(J, -F, method="gmres", rtol=1e-8,
                                    maxiter=500, block_size=3)
    assert info["converged"]
    assert info["iterations"] < 100, \
        f"G6 regression: took {info['iterations']} iterations"
