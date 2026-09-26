"""NATIVE-DESKTOP-PLAN.md P1 S2 correctness gates, run through the real
native viewer (`tcad_desktop --selftest`, desktop/src/bench/selftest.cpp).

S2 made the viewer fast by building the displayed geometry once per
result and gathering values into it, and by picking 3D hovers through a
static cell locator. These gates check that the fast paths still show
the same numbers:

- every displayed point sits on the grid node its carried index names;
- for every field, linear and log, the displayed scalars are
  bit-identical to a fresh decode, and the colour range equals P0's
  (GetRange over every node);
- 3D hovers agree with an analytic ray-box oracle on hit/miss and
  readout, over 1000 seeded pixels per file;
- files are opened in sequence into ONE window, so nothing (geometry,
  node ids, locator) may survive from the previous result.

S6 (NATIVE-DESKTOP-PLAN.md 15.19) moved 3D to nearest shading (a voxel
per node) and added the interior layers. On every 3D file:

- face and slice pixels are their node's LUT colour, viewed along z;
- each slice's cells are exactly one node plane's patches;
- every isosurface vertex lies on one grid edge, at the linear
  interpolation of the level;
- the volume's colour function is the view's table and its opacity the
  preset's, and it changes pixels only inside the device's silhouette;
- glyph arrows sit on nodes and carry THAT node's J; the longest is the
  spacing long;
- streamlines stay inside the device, each chord parallel to the mean of
  its ends' J;
- exploded regions sit on their nodes' patch boxes, offset along z;
- each sweep snapshot's displayed values are bit-identical to a fresh
  decode, over the union range;
- the hover oracle holds on a crop box too.
The synthetic graded_3d file carries a current density, five snapshots
and two regions (run_bench._layers_3d), so every layer is exercised.

The viewer needs a real GL surface: the child process runs WITHOUT the
suite's QT_QPA_PLATFORM=offscreen and briefly opens a window. Skipped
(not failed) when the desktop app has not been built.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop", "bench"))

BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _run(args, offscreen=False, timeout=600):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    return subprocess.run([os.path.join(BUILD, "tcad_desktop.exe"), *args],
                          capture_output=True, text=True, env=env, timeout=timeout)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    import run_bench   # desktop/bench: the same datasets the benchmark times
    d = str(tmp_path_factory.mktemp("selftest"))
    return {
        "mosfet_2d": run_bench._solve(d, "mosfet_2d"),
        "resistor_3d": run_bench._solve(d, "resistor_3d"),
        "graded_3d": run_bench._synthetic(d, "graded_3d", (30, 20, 15)),
        "graded_2d": run_bench._synthetic(d, "graded_2d", (120, 80)),
    }


def test_fast_paths_show_the_same_numbers(results):
    # 2D -> 3D -> a 3D of different geometry -> 2D: each switch would
    # expose geometry, node ids or a pick locator kept from before.
    order = ["mosfet_2d", "resistor_3d", "graded_3d", "graded_2d"]
    out = _run(["--selftest", *[results[k] for k in order]])
    report = json.loads(out.stdout)
    failed = [f for f in report["files"] if not f.get("ok", True)]
    assert out.returncode == 0 and report["ok"], json.dumps(failed, indent=1)[:4000]
    by_name = dict(zip(order, report["files"]))
    for name in order:
        f = by_name[name]
        assert f["node_ids"]["mismatched"] == 0
        assert f["fields"] and all(c["mismatched_values"] == 0 for c in f["fields"])
        assert {c["log"] for c in f["fields"]} == {False, True}
    for name in ("resistor_3d", "graded_3d"):
        hover = by_name[name]["hover"]
        assert hover["hits"] > 100, "the probe must actually land on the device"
        assert hover["mismatch_vs_oracle"] == 0
        layers = by_name[name]["layers"]
        assert layers["ok"]
        assert layers["face_probes"] >= 20 and layers["face_mismatches"] == 0
        assert layers["slice_probes"] >= 20 and layers["slice_mismatches"] == 0
        assert all(s["mismatched"] == 0 for s in layers["slices"])
        assert layers["iso"]["vertices"] > 0 and layers["iso"]["mismatched"] == 0
        assert layers["volume"]["changed_inside"] > 0 and layers["volume"]["changed_outside"] == 0
        assert layers["glyphs"]["mismatched"] == 0
        assert layers["streamlines"]["points"] > 0 and layers["streamlines"]["outside_device"] == 0
        assert layers["hover_cropped"]["mismatch_vs_oracle"] == 0
    full = by_name["graded_3d"]["layers"]   # the file with every layer's data
    assert len(full["exploded"]) == 2 and all(r["ok"] for r in full["exploded"])
    assert len(full["playback"]["frames"]) == 5 and full["playback"]["mismatched"] == 0


def test_no_gl_surface_fails_clearly_instead_of_hanging(results):
    """Under the offscreen platform there is no GL surface; before S2 the
    wait for one spun forever."""
    out = _run(["--selftest", results["resistor_3d"]], offscreen=True, timeout=120)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "no OpenGL context" in json.loads(out.stdout)["error"]
