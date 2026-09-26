"""NATIVE-DESKTOP-PLAN.md P1 S5f: the native app's contour levels equal
matplotlib's own for ax.contour(z, levels=8) -- the QML viewport's contour
overlay -- compared with ContourSet.levels itself, not with a reading of
matplotlib's code.

Cases: 60 generated ranges (unit, huge, tiny, negative, crossing zero,
large offsets relative to the span, log-scaled values), plus the edge
cases: a constant field, zero, and a range of exact integers.
"""
import json
import os
import subprocess
import warnings

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _cases():
    rng = np.random.default_rng(20260925)
    cases = [(0.0, 1.0), (-1.0, 1.0), (0.0, 0.0), (5.0, 5.0), (-3.0, -3.0), (1.0, 7.0),
             (1e17, 1e17 * (1 + 1e-9)), (0.123456, 0.123457), (-4.05, -3.98), (1e-30, 3e-30)]
    # Ranges where a port using floor(a / b) instead of Python's float floor
    # division (1.0 // 0.1 == 9.0, floor(1.0 / 0.1) == 10) picks different
    # levels -- found by searching; without them the gate could not tell
    # the two apart (a mutant survived the 70 cases above).
    cases += [(0.9, 1.8), (1.0, 2.7), (1.0, 1.3), (1.8, 3.5), (2.0, 2.3000000000000003),
              (2.0, 3.7), (2.1, 3.0), (2.6, 3.5), (0.03, 0.12), (1.3199999999999999e-08, 1.65e-08)]
    for _ in range(60):
        kind = rng.integers(0, 5)
        if kind == 0:     # any magnitude
            a, b = sorted(rng.normal(size=2) * 10.0 ** rng.integers(-12, 19))
        elif kind == 1:   # a big offset relative to the span
            c = rng.normal() * 10.0 ** rng.integers(0, 18)
            a, b = sorted(c + rng.normal(size=2) * abs(c) * 10.0 ** -rng.integers(3, 12))
        elif kind == 2:   # log10 of densities
            a, b = sorted(rng.uniform(-30, 21, 2))
        elif kind == 3:   # potentials / band edges
            a, b = sorted(rng.uniform(-6, 2, 2))
        else:             # crossing zero, asymmetric
            a, b = -rng.uniform(0, 1) * 10.0 ** rng.integers(0, 6), rng.uniform(0, 1) * 10.0 ** rng.integers(0, 6)
        cases.append((float(a), float(b)))
    return cases


def _matplotlib_levels(zmin, zmax):
    from matplotlib.figure import Figure
    ax = Figure().subplots()
    z = np.array([[zmin, zmax], [zmin, zmax]], dtype=float)
    with warnings.catch_warnings(record=True):   # a constant field warns "no levels found"
        warnings.simplefilter("always")
        return list(ax.contour(z, levels=8).levels)


def _cpp_levels(zmin, zmax):
    with open(MANIFEST) as fh:
        m = json.load(fh)
    out = subprocess.run([os.path.join(BUILD, m["tools"]["theme_dump"]), "--contour-levels", repr(zmin), repr(zmax)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.parametrize("zmin,zmax", _cases())
def test_levels_equal_matplotlib(zmin, zmax):
    want = _matplotlib_levels(zmin, zmax)
    got = _cpp_levels(zmin, zmax)
    assert len(got) == len(want), (got, want)
    assert got == want, [(g, w) for g, w in zip(got, want) if g != w][:3]
