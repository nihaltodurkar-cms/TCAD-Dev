"""Memory and performance benchmarks for Device3D, per the design spec's
Section 6.  Not part of the routine test suite (too slow) -- run
directly:

    python -m pytcad.benchmarks.bench_device3d   (from the pytcad/ project root)

Benchmarks a uniformly-doped cubic resistor at increasing mesh
resolution (20/30/40/50 nodes per axis, i.e. up to 125,000 cells,
375,000 DOF for the full drift-diffusion system).  Records mesh
construction time, Jacobian assembly time, linear solve time, total
Newton time, and peak memory (via tracemalloc -- portable, no external
dependency).

KNOWN RISK, documented not fixed here (see design spec Section 6):
scipy.sparse.linalg.spsolve is a direct sparse solve; fill-in during LU
factorization scales worse in 3D than 2D for structured grids.  This
script's job is to measure and report that honestly, not to work around
it -- an iterative/preconditioned solver is out of scope for this
sub-project.
"""
import time
import tracemalloc

import numpy as np

from ..mesh3d import Mesh3D
from ..device3d import Device3D
from ..device import Models, NewtonOptions


def run_one_benchmark(n_per_axis, verbose=True):
    """Build and solve a uniform-doping cubic resistor at n_per_axis
    nodes per axis.  Returns a dict of timing/memory/convergence results."""
    L = 2e-4   # 2 um cube
    tracemalloc.start()

    t0 = time.perf_counter()
    x = np.linspace(0.0, L, n_per_axis)
    y = np.linspace(0.0, L, n_per_axis)
    z = np.linspace(0.0, L, n_per_axis)
    mesh = Mesh3D(x, y, z)
    t_mesh = time.perf_counter() - t0

    doping = np.full((mesh.Nz, mesh.Ny, mesh.Nx), 1e17)
    dev = Device3D(mesh, doping, models=Models(bgn=False))

    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)

    t1 = time.perf_counter()
    dev.solve_equilibrium()
    t_equilibrium = time.perf_counter() - t1

    t2 = time.perf_counter()
    F, J, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, {"left": 0.0, "right": 0.0})
    t_assembly = time.perf_counter() - t2

    from scipy.sparse.linalg import spsolve
    t3 = time.perf_counter()
    _ = spsolve(J.tocsc(), -F)
    t_solve = time.perf_counter() - t3

    t4 = time.perf_counter()
    converged = True
    try:
        dev.solve_bias({"left": 0.1, "right": 0.0}, NewtonOptions(max_iter=50))
    except Exception:
        converged = False
    t_newton = time.perf_counter() - t4

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result = {
        "n_per_axis": n_per_axis,
        "N": mesh.N,
        "dof": 3 * mesh.N,
        "mesh_time_s": t_mesh,
        "equilibrium_time_s": t_equilibrium,
        "jacobian_assembly_time_s": t_assembly,
        "single_solve_time_s": t_solve,
        "newton_time_s": t_newton,
        "peak_memory_mb": peak / (1024 * 1024),
        "converged": converged,
    }
    if verbose:
        print(f"  n={n_per_axis:3d}  N={mesh.N:7d}  DOF={3*mesh.N:7d}  "
              f"mesh={t_mesh:.3f}s  eq={t_equilibrium:.3f}s  "
              f"assembly={t_assembly:.3f}s  solve={t_solve:.3f}s  "
              f"newton={t_newton:.3f}s  peak={peak/(1024*1024):.1f}MB  "
              f"converged={converged}")
    return result


if __name__ == "__main__":
    print("Device3D memory/performance benchmark")
    print("=" * 100)
    results = []
    for n in (20, 30, 40, 50):
        results.append(run_one_benchmark(n))
    print("=" * 100)
    print(f"{'n':>4} {'N':>8} {'DOF':>8} {'mesh(s)':>8} {'eq(s)':>8} "
          f"{'asm(s)':>8} {'solve(s)':>9} {'newton(s)':>10} {'peakMB':>8}")
    for r in results:
        print(f"{r['n_per_axis']:>4} {r['N']:>8} {r['dof']:>8} "
              f"{r['mesh_time_s']:>8.3f} {r['equilibrium_time_s']:>8.3f} "
              f"{r['jacobian_assembly_time_s']:>8.3f} {r['single_solve_time_s']:>9.3f} "
              f"{r['newton_time_s']:>10.3f} {r['peak_memory_mb']:>8.1f}")
