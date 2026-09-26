"""NATIVE-DESKTOP-PLAN.md P1 S5c: the native app's nearest-shading patch
edges equal matplotlib's own for pcolormesh(x, y, z, shading="nearest"),
which the QML viewport draws with, bit for bit.

The axes are real: the solved MOSFET's and resistor's, in um as the QML
viewport passes them. Also a graded axis, and 2- and 1-node axes (for
one node matplotlib gives a zero-width patch).
"""
import json
import os
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop", "bench"))
BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _cpp_edges(x):
    with open(MANIFEST) as fh:
        m = json.load(fh)
    out = subprocess.run([os.path.join(BUILD, m["tools"]["theme_dump"]), "--edges", *[repr(float(v)) for v in x]],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _mpl_edges(x, y):
    from matplotlib.figure import Figure
    ax = Figure().subplots()
    mesh = ax.pcolormesh(np.asarray(x), np.asarray(y), np.zeros((len(y), len(x))), shading="nearest")
    c = mesh.get_coordinates()          # (ny + 1, nx + 1, 2)
    return list(c[0, :, 0]), list(c[:, 0, 1])


@pytest.fixture(scope="module")
def axes_um(tmp_path_factory):
    import run_bench
    from gui.services.result_store import NpzResultStore
    d = str(tmp_path_factory.mktemp("edges"))
    out = {}
    for name in ("mosfet_2d", "resistor_2d"):
        a = NpzResultStore(run_bench._solve(d, name)).mesh_axes().axes
        out[name] = (list(np.asarray(a["x"]) * 1e4), list(np.asarray(a["y"]) * 1e4))
    graded = list(np.cumsum(np.linspace(1.0, 3.0, 37)) * 1e-3)
    out["graded"] = (graded, graded[:11])
    out["two-nodes"] = ([0.0, 0.25], [1.0, 3.5])
    return out


@pytest.mark.parametrize("case", ["mosfet_2d", "resistor_2d", "graded", "two-nodes"])
def test_edges_equal_matplotlib(axes_um, case):
    x, y = axes_um[case]
    want_x, want_y = _mpl_edges(x, y)
    assert _cpp_edges(x) == want_x
    assert _cpp_edges(y) == want_y


def test_one_node_axis_is_a_zero_width_patch_like_matplotlib():
    from matplotlib.figure import Figure
    ax = Figure().subplots()
    mesh = ax.pcolormesh(np.array([2.0]), np.array([0.0, 1.0]), np.zeros((2, 1)), shading="nearest")
    want = list(mesh.get_coordinates()[0, :, 0])
    assert _cpp_edges([2.0]) == want == [2.0, 2.0]
