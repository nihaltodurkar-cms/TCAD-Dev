"""NATIVE-DESKTOP-PLAN.md P2-S2 gates for PlotView (16.4): runs the C++
Qt Test binary tcad_desktop_plot_tests (desktop/tests/test_plot.cpp) --
the REAL widget rendered with grab() and probed pixel by pixel -- at
display scales 1, 1.5 and 2 (QT_SCALE_FACTOR), and its bench.

The probes (no golden images, section 15.5): each series' colour at its
samples; a NaN leaves a gap, also through decimation; markers at <= 40
points only; a log axis shows |v| and gaps at 0 (decision 8); a right-hand
axis's series on its own scale; ticks are the locator port's and drawn
where it says; legend (placed "best") and title present; tick labels never
overlap; hover names the sample pointed at, skips NaN (the QML defect),
reads raw samples of a decimated series, works on log x and both AC axes,
lists ties; fit shows every sample; zoom/pan keep a log axis positive and
reset returns to fit.

Bench (16.4): pan and zoom frames at 1,000 and 100,000 points <= 16.7 ms
p95 (a frame: the view change plus a synchronous repaint of a shown
window; the compositor's flush is excluded, as in the P1 bench), hover
<= 1 ms p95.
"""
import json
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _run(tmp_path, scale, extra_env=None, args=()):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env["QT_SCALE_FACTOR"] = scale
    env.update(extra_env or {})
    report = tmp_path / f"plot_{scale}.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["plot_tests"]), *args, "-o", f"{report},txt"],
                         capture_output=True, text=True, env=env, timeout=600)
    text = report.read_text(encoding="utf-8")
    return out.returncode, text


@pytest.mark.parametrize("scale", ["1", "1.5", "2"])
def test_plot_view_gates_pass_at_scale(tmp_path, scale):
    code, text = _run(tmp_path, scale)
    assert code == 0 and ", 0 failed," in text, text
    passed = int(text.split("Totals: ")[1].split(" passed")[0])
    assert passed >= 22, text          # every gate ran, not just the harness


@pytest.mark.timing  # wall-clock budget: run serially (pytest.ini "timing")
def test_plot_view_bench_meets_the_budgets(tmp_path):
    out = tmp_path / "bench.json"
    code, text = _run(tmp_path, "1", {"TCAD_PLOT_BENCH": str(out)}, ["bench"])
    assert code == 0 and ", 0 failed," in text, text
    report = json.loads(out.read_text())
    for n in ("1000", "100000"):
        r = report[n]
        assert r["pan_p95_ms"] <= 16.7, report
        assert r["zoom_p95_ms"] <= 16.7, report
        assert r["hover_p95_ms"] <= 1.0, report
    assert report["100000"]["drawn_vertices"] < 100000 / 4, "decimation ran at 100k points"
