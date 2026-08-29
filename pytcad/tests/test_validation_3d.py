"""3D validation suite -- mirrors tests/test_validation_2d.py's structure.

Every test compares the 3D solver against something independent: the
existing validated 2D solver (on a z-invariant structure), a finite
difference check, or a conservation identity.

    python -m pytest tests/test_validation_3d.py -q
    python tests/test_validation_3d.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np

from pytcad.mesh import graded_mesh
from pytcad.mesh3d import Mesh3D, check_mesh3d
from pytcad.mesh2d import Mesh2D
from pytcad.device2d import Device2D
from pytcad.device import Models
from pytcad.device3d import Device3D, DirichletBC, GateBC

warnings.simplefilter("ignore")


def test_mesh3d_shapes_and_indexing():
    x = np.linspace(0.0, 1.0, 4)
    y = np.linspace(0.0, 2.0, 3)
    z = np.linspace(0.0, 3.0, 5)
    m = Mesh3D(x, y, z)
    assert m.Nx == 4 and m.Ny == 3 and m.Nz == 5 and m.N == 60
    assert m.hx.shape == (3,) and m.hy.shape == (2,) and m.hz.shape == (4,)
    assert m.dVx.shape == (4,) and m.dVy.shape == (3,) and m.dVz.shape == (5,)
    assert m.dV.shape == (60,)
    # row-major: idx(i,j,k) = k*Nx*Ny + j*Nx + i
    assert m.idx(0, 0, 0) == 0
    assert m.idx(3, 0, 0) == 3
    assert m.idx(0, 1, 0) == 4
    assert m.idx(0, 0, 1) == 12          # Nx*Ny = 4*3 = 12
    assert m.idx(2, 1, 3) == 3 * 12 + 1 * 4 + 2


def test_mesh3d_volume_is_triple_outer_product():
    x = np.array([0.0, 1.0, 3.0])
    y = np.array([0.0, 2.0])
    z = np.array([0.0, 1.0, 2.0, 5.0])
    m = Mesh3D(x, y, z)
    from pytcad.mesh2d import control_volume_widths
    dvx = control_volume_widths(m.hx)
    dvy = control_volume_widths(m.hy)
    dvz = control_volume_widths(m.hz)
    expected = (dvz[:, None, None] * dvy[None, :, None] * dvx[None, None, :]).ravel()
    assert np.allclose(m.dV, expected)
    assert abs(m.dV.sum() - 3.0 * 2.0 * 5.0) < 1e-10   # total volume = Lx*Ly*Lz


def test_check_mesh3d_reports_finite_ratio():
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    y = graded_mesh(1e-4, [0.0], 1e-8, 1e-6, 1.12)
    z = graded_mesh(1e-4, [0.0], 1e-8, 1e-6, 1.12)
    m = Mesh3D(x, y, z)
    doping = np.where(x[None, None, :] < 1e-4, -1e17, 1e17) * np.ones((m.Nz, m.Ny, 1))
    ratio = check_mesh3d(m, doping, verbose=False)
    assert np.isfinite(ratio) and ratio > 0.0


def test_equilibrium_3d_reduces_to_2d():
    """A z-invariant extrusion of an already-validated 2D structure must
    give a z-independent solution matching the 2D equilibrium solver on
    the equivalent 2D structure, to numerical tolerance.

    Mesh is deliberately coarser than the 2D/1D tests' own x-resolution:
    those need fine (~1e-8 cm) spacing to resolve a real diode's Debye
    length for accurate I-V physics.  This test only checks that the 3D
    assembly reproduces the 2D assembly when z-invariant -- both solves
    run on the IDENTICAL (x,y) mesh, so any mesh-coarseness error is
    common to both sides of the comparison and cancels out.  A fine mesh
    here multiplies across all three axes (Nx*Ny*Nz), unlike 2D where it
    only multiplies across two -- at the original 1D/2D-style resolution
    this test took ~8 minutes; at this resolution it is fast.
    """
    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
    z = graded_mesh(3e-5, [0.0], 2e-6, 8e-6, 1.2)

    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))            # (Ny, Nx)
    dop3d = np.tile(dop2d, (z.size, 1, 1))          # (Nz, Ny, Nx)

    mesh2 = Mesh2D(x, y)
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
    dev2.solve_equilibrium()

    mesh3 = Mesh3D(x, y, z)
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    dev3.solve_equilibrium()

    psi3d = dev3.psi_V   # (Nz, Ny, Nx)
    assert np.allclose(psi3d, psi3d[0:1, :, :], atol=1e-9), \
        "solution must be z-independent"
    assert np.allclose(psi3d[0, :, :], dev2.psi_V, atol=1e-6), \
        f"max diff {np.abs(psi3d[0,:,:]-dev2.psi_V).max():.3e}"


def test_dd_jacobian_matches_finite_differences():
    """The analytic 3D Newton Jacobian must match a numerical one -- same
    check as the 1D/2D equivalents, run first whenever the 3D physics
    changes.  Uses sparse column-slice extraction throughout, never
    J.toarray() on the full matrix.  Mesh is coarsened the same way
    test_equilibrium_3d_reduces_to_2d is, for the same reason (Nx*Ny*Nz
    growth) -- see that test's docstring."""
    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
    z = graded_mesh(4e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop3d = np.tile(dop1d, (z.size, y.size, 1))

    mesh = Mesh3D(x, y, z)
    dev = Device3D(mesh, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
    dev.solve_equilibrium()

    rng = np.random.default_rng(0)
    shape = (mesh.Nz, mesh.Ny, mesh.Nx)
    psi = dev.psi + 0.02 * rng.standard_normal(shape)
    n = dev.n * (1 + 0.01 * rng.standard_normal(shape))
    p = dev.p * (1 + 0.01 * rng.standard_normal(shape))

    F, J, *_ = dev._residual_jacobian(psi, n, p, {"left": 0.3, "right": 0.0})
    Jc = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(3 * dev.N, 30, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        psi2 = u2[0::3].reshape(shape)
        n2 = u2[1::3].reshape(shape)
        p2 = u2[2::3].reshape(shape)
        F2, *_ = dev._residual_jacobian(psi2, n2, p2, {"left": 0.3, "right": 0.0})
        an = np.asarray(Jc[:, c].todense()).ravel()
        worst = max(worst, np.abs((F2.ravel() - F.ravel()) / step - an).max()
                    / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"3D Jacobian error {worst:.2e}"


def test_bias_3d_reduces_to_2d():
    """A z-invariant p-n slab under forward bias must match the 2D
    drift-diffusion solver's current and band profile."""
    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
    z = graded_mesh(3e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))
    dop3d = np.tile(dop2d, (z.size, 1, 1))

    mesh2 = Mesh2D(x, y)
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
    dev2.solve_equilibrium()
    dev2.solve_bias({"left": 0.5, "right": 0.0})

    mesh3 = Mesh3D(x, y, z)
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    dev3.solve_equilibrium()
    dev3.solve_bias({"left": 0.5, "right": 0.0})

    Jtot_3d = dev3.Jn_x + dev3.Jp_x            # (Nz, Ny, Nx-1)
    assert np.allclose(Jtot_3d, Jtot_3d[0:1, :, :], rtol=1e-3, atol=1e-6), \
        "current density must be z-independent"
    Jtot_2d = dev2.Jn_x + dev2.Jp_x            # (Ny, Nx-1)
    assert np.allclose(Jtot_3d[0], Jtot_2d, rtol=1e-3, atol=1e-6), \
        f"max diff {np.abs(Jtot_3d[0]-Jtot_2d).max():.3e}"


def test_terminal_current_conserves_charge_3d():
    """Sum of terminal currents into a two-terminal 3D resistor must be
    ~0, extracted via the residual-based (automatically conserving)
    method -- built in correctly from the start."""
    x = np.linspace(0.0, 4e-4, 9)
    y = np.linspace(0.0, 2e-4, 7)
    z = np.linspace(0.0, 2e-4, 7)
    mesh = Mesh3D(x, y, z)
    doping = np.full((mesh.Nz, mesh.Ny, mesh.Nx), 1e17)   # uniform n-type

    dev = Device3D(mesh, doping, models=Models(bgn=False))
    # narrow top-face contact (forces a real lateral seam flux), full
    # bottom-face contact
    ti, tj = np.meshgrid(np.arange(2, 6), np.arange(2, 5))
    ti, tj = ti.ravel(), tj.ravel()
    dev.add_contact("top", i=ti, j=tj, k=np.zeros_like(ti), V=0.0)
    bi, bj = np.meshgrid(np.arange(mesh.Nx), np.arange(mesh.Ny))
    bi, bj = bi.ravel(), bj.ravel()
    dev.add_contact("bottom", i=bi, j=bj, k=np.full_like(bi, mesh.Nz - 1), V=0.0)
    dev.solve_equilibrium()
    dev.solve_bias({"top": 0.05, "bottom": 0.0})

    I_top = dev.terminal_current("top")
    I_bottom = dev.terminal_current("bottom")
    rel_err = abs(I_top + I_bottom) / max(abs(I_top), abs(I_bottom))
    assert rel_err < 1e-6, \
        (f"terminal currents don't conserve charge: I_top={I_top:.6e} A, "
         f"I_bottom={I_bottom:.6e} A, rel err {rel_err:.2e}")


def test_benchmark_helper_runs_at_small_scale():
    """Fast regression check that the benchmarking helper itself works
    (construction, assembly, solve, memory measurement) -- not a timing
    assertion, just confirms the code path is correct.  The full
    benchmark sweep (20/30/40/50 per axis) is run manually via
    benchmarks/bench_device3d.py, not as part of the regular test suite
    (too slow for routine `pytest tests/`)."""
    from pytcad.benchmarks.bench_device3d import run_one_benchmark
    result = run_one_benchmark(n_per_axis=6, verbose=False)
    assert result["N"] == 6 ** 3
    assert result["newton_time_s"] > 0.0
    assert result["peak_memory_mb"] > 0.0
    assert result["converged"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for f in fns:
        try:
            f()
            print(f"  PASS  {f.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {f.__name__}: {e}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
