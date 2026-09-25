"""Run the whole test suite as fast as this machine allows.

    python run_tests.py                 # everything (fast + slow)
    python run_tests.py -m "not slow"   # extra args go to both pytest phases

Phase 1 runs every test in parallel on 6 xdist workers -- never more:
a 10-worker run on this PC made timing tests fail from CPU contention and
lost a worker mid-run (2026-09-25). Work-stealing scheduling lets a
worker that finishes early take queued tests from a busy one, so a few
long slow-marked gates don't leave workers idle at the end, and BLAS/
OpenMP are pinned to one thread per worker (otherwise each worker spawns
its own pool and they oversubscribe the CPU).

Phase 2 runs the absolute throughput floors (test_accel_parity.py
test_throughput_floor) serially, on an otherwise idle machine. They time
a kernel against a fixed rate, so under a fully loaded parallel run they
measure CPU contention instead of the kernel -- measured 2026-09-25:
1.67e6/s against a 2e6/s floor with 10 busy workers, comfortably above it
alone. Nothing is skipped or weakened; the floors just run on their own.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TIMING = "tests/test_accel_parity.py::test_throughput_floor"
WORKERS = 6            # hard cap -- see the module docstring


def main(extra):
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", QT_QPA_PLATFORM="offscreen")
    base = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    workers = str(WORKERS)
    phase1 = base + ["tests/", "gui/tests/", "-n", workers, "--dist", "worksteal",
                     "--deselect", TIMING, "--durations=25"] + extra
    phase2 = base + [TIMING] + extra
    print(f"[run_tests] phase 1: whole suite, {workers} workers", flush=True)
    r1 = subprocess.call(phase1, cwd=HERE, env=env)
    print("[run_tests] phase 2: throughput floors, serial", flush=True)
    r2 = subprocess.call(phase2, cwd=HERE, env=env)
    # pytest exit code 5 = "no tests collected" (e.g. -m excluded them all)
    bad = [r for r in (r1, r2) if r not in (0, 5)]
    return bad[0] if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
