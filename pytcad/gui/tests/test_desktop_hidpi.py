"""NATIVE-DESKTOP-PLAN.md P1 S3e HiDPI gates: the native viewer at display
scale factors 1, 1.5 and 2 (QT_SCALE_FACTOR).

At each scale:
- `tcad_desktop --selftest` passes all of its checks. That includes the
  3D hover oracle, which uses the device pixel ratio, and the new
  scale check:
    - the GL surface is the widget's logical size times the DPR;
    - hovering at the logical pixel where a 2D mesh node is drawn names
      that exact node (200 seeded nodes).
- The shell's view-driving and dock float/re-dock e2e tests pass.
- S8g (15.23): a synthetic 3D result with every layer's data (a current
  density, sweep snapshots, regions) runs the S6 layer checks at each
  scale too -- face and slice pixels, isosurface, volume, glyphs,
  streamlines, exploded view, playback and the cropped hover oracle.

The view runs at 600x360 logical so 2x (1200x720 device px) fits this
PC's 1920x1080 screen with the window chrome (section 15.13 rev. 1).
The hover-centre string is NOT compared across scales: the MOSFET's view
centre falls exactly between two nodes (section 14.3), so a sub-pixel
shift may legitimately snap either way. The node round-trip is the
DPR-sensitive check. Needs a real GL surface; skipped when the app is
not built.
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

SCALES = ["1", "1.5", "2"]


def _env(scale, extra=None):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env["QT_SCALE_FACTOR"] = scale
    env.update(extra or {})
    return env, manifest


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    import run_bench
    d = str(tmp_path_factory.mktemp("hidpi"))
    return {"mosfet_2d": run_bench._solve(d, "mosfet_2d"),
            "resistor_3d": run_bench._solve(d, "resistor_3d"),
            "graded_2d": run_bench._synthetic(d, "graded_2d", (90, 70)),
            "layers_3d": run_bench._synthetic(d, "layers_3d", (24, 18, 14))}


@pytest.mark.parametrize("scale", SCALES)
def test_selftest_passes_at_scale(results, scale):
    env, manifest = _env(scale)
    files = [results["mosfet_2d"], results["resistor_3d"], results["graded_2d"], results["layers_3d"]]
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["desktop"]), "--selftest", *files,
                          "--size", "600x360"], capture_output=True, text=True, env=env, timeout=600)
    report = json.loads(out.stdout)
    failed = [f for f in report["files"] if not f.get("ok", True)]
    assert out.returncode == 0 and report["ok"], json.dumps(failed, indent=1)[:4000]
    for f in report["files"]:
        s = f["scale"]
        assert s["dpr"] == pytest.approx(float(scale)), s
        assert s["render_size_ok"], s
        if f["dimensionality"] == 2:
            assert s["node_probes"] > 50 and s["node_mismatches"] == 0, s
    layers = report["files"][3]["layers"]   # every S6 layer, at this scale
    assert layers["ok"] and layers["face_mismatches"] == 0 and layers["slice_mismatches"] == 0
    assert layers["playback"]["mismatched"] == 0 and all(r["ok"] for r in layers["exploded"])
    assert layers["hover_cropped"]["mismatch_vs_oracle"] == 0


@pytest.mark.parametrize("scale", SCALES)
def test_shell_view_driving_at_scale(results, scale, tmp_path):
    env, manifest = _env(scale, {"TCAD_TEST_DATA": os.path.dirname(results["mosfet_2d"])})
    report = tmp_path / "shell.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["shell_tests"]),
                          "fieldListLogFitAndHoverDriveTheView", "floatAndRedockKeepsTheViewRendering",
                          "-o", f"{report},txt"], capture_output=True, text=True, env=env, timeout=600)
    text = report.read_text(encoding="utf-8") if report.exists() else out.stdout + out.stderr
    assert out.returncode == 0 and ", 0 failed," in text, text[-4000:]
