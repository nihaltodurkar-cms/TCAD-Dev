"""NATIVE-DESKTOP-PLAN.md P1 S4 gates for the native app's C++ BackendClient
(desktop/src/backend/), run by the Qt Test executable
tcad_desktop_backend_tests (desktop/tests/test_backend.cpp).

Against the REAL backend service:
- the handshake;
- examples.list equal to Python's;
- 20 queued calls answered in order;
- a band map read back through the C++ .npz reader and ResultModel;
- a non-ASCII path through the pipe;
- the backend loads no DLL from outside its own environment (the test
  process has the GUI env's DLL directory on PATH, as the app does);
- a timeout replaces the backend;
- a kill mid-call fails the pending call in < 1.5 s;
- a crash reports its exit code and stderr;
- three crashes give up until reset;
- a missing interpreter is a named error;
- shutdown leaves no process and no scratch directory.

Against fake backends (desktop/tests/fake_backend.py): garbage, silence,
a wrong reply id, a wrong protocol, an immediate exit, a stderr message
then exit, CRLF plus split lines, and a 10 MB line. Each must end in a
named failure (or, for the last two, success), never a hang.

Skipped when the app is not built. Needs no display: the client is Qt
Core only.
"""
import json
import os
import shutil
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

UNICODE_DIR = "µm € \U0001f600"   # test_backend.cpp names it the same


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    import run_bench
    from gui.services import examples
    d = str(tmp_path_factory.mktemp("backend_data"))
    mosfet = run_bench._solve(d, "mosfet_2d")
    run_bench._solve(d, "resistor_3d")  # an export target: loads pyvista/VTK in the backend
    os.makedirs(os.path.join(d, UNICODE_DIR))
    shutil.copy(mosfet, os.path.join(d, UNICODE_DIR, "mosfet_2d.npz"))
    with open(os.path.join(d, "examples.json"), "w") as fh:
        json.dump(sorted(examples.EXAMPLES), fh)
    return d


def test_backend_client(data_dir, tmp_path):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    assert manifest["backend_python"], "build.ps1 found no tcad-dev interpreter"
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "TCAD_BACKEND_DEBUG")}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env.update({
        "TCAD_TEST_PYTHON": manifest["backend_python"],
        "TCAD_TEST_ROOT": manifest["backend_root"],
        "TCAD_TEST_DATA": data_dir,
        "TCAD_TEST_FAKE": os.path.join(ROOT, "desktop", "tests", "fake_backend.py"),
        "TCAD_TEST_STRIP": manifest["runtime_bin"],
    })
    report = tmp_path / "backend.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["backend_tests"]), "-o", f"{report},txt"],
                         capture_output=True, text=True, env=env, timeout=900)
    text = report.read_text(encoding="utf-8") if report.exists() else out.stdout + out.stderr
    assert out.returncode == 0 and ", 0 failed," in text, text[-6000:]
