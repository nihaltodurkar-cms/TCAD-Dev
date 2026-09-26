"""NATIVE-DESKTOP-PLAN.md P1 S3 shell gates: the native app's real
MainWindow, driven in a real window by the Qt Test executable
tcad_desktop_shell_tests (desktop/tests/test_shell.cpp).

What it covers:
- opening a result, by path and by a synthesized drop;
- failed opens (missing, not .npz, corrupt, schema 99, two files dropped)
  report a named error and keep the current result on screen;
- a non-ASCII directory;
- recent files: de-duplicated case-insensitively, capped, deleted
  entries removed, and kept across a restart;
- the dock layout and window size kept across a restart; a corrupt or
  other-version saved layout falls back to the default;
- a read-only settings file;
- floating and re-docking a panel leaves the GL view rendering;
- the field list, the log action, the hover readout and the Fit shortcut
  drive the view;
- S5: the Display panel and the derived maps;
- S6 (NATIVE-DESKTOP-PLAN.md 15.19): one test per 3D parity item --
  slices, the central z-plane, clipping, isosurface, colour maps, volume
  presets, glyphs, streamlines, exploded view and playback -- driven
  through the 3D and Playback panels;
- S8 (15.23/15.24): a result deleted or replaced while open (memory keeps
  working, backend calls are refused with the reason); the section 15.5
  scenario as one test with synthesized input; one named test per 2D
  parity item (parity2d*).

This module builds the test data, runs the executable, and fails on any
failed Qt Test function. Like test_desktop_selftest.py, it needs a real
GL surface (the child runs without the suite's QT_QPA_PLATFORM=offscreen)
and is skipped when the app is not built.
"""
import json
import os
import shutil
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

UNICODE_DIR = "µm € \U0001f600"   # µm € 😀 -- test_shell.cpp names it the same


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    import run_bench   # desktop/bench: the benchmark's own dataset builders
    d = str(tmp_path_factory.mktemp("shell_data"))
    mosfet = run_bench._solve(d, "mosfet_2d")
    run_bench._solve(d, "resistor_3d")
    run_bench._synthetic(d, "layers3d", (24, 18, 14))   # S6: vectors, snapshots, regions
    with open(mosfet, "rb") as fh:
        raw = fh.read()
    with open(os.path.join(d, "corrupt.npz"), "wb") as fh:
        fh.write(raw[: len(raw) // 2])                     # truncated archive
    np.savez(os.path.join(d, "schema99.npz"), result__schema=np.int64(99),
             solved_bias=np.array(True), dimensionality=np.int64(1),
             axis_x=np.array([0.0, 1e-4]))
    with np.load(mosfet) as z:   # a result without doping: the R entry must say so
        np.savez(os.path.join(d, "mosfet_no_doping.npz"),
                 **{k: z[k] for k in z.files if k not in ("field__doping", "unit__doping")})
    with open(os.path.join(d, "notes.txt"), "w") as fh:
        fh.write("not a result\n")
    os.makedirs(os.path.join(d, UNICODE_DIR))
    shutil.copy(mosfet, os.path.join(d, UNICODE_DIR, "mosfet_2d.npz"))
    return d


def test_shell_end_to_end(data_dir, tmp_path):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env["TCAD_TEST_DATA"] = data_dir
    report = tmp_path / "shell.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["shell_tests"]),
                          "-o", f"{report},txt"], capture_output=True, text=True,
                         env=env, timeout=600)
    text = report.read_text(encoding="utf-8") if report.exists() else out.stdout + out.stderr
    assert out.returncode == 0, text[-6000:]
    assert ", 0 failed," in text, text[-6000:]
