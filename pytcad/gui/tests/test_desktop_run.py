"""NATIVE-DESKTOP-PLAN.md P3-S3 gates for the native app's C++ JobRunner
(desktop/src/run/), run by the Qt Test executable tcad_desktop_run_tests
(desktop/tests/test_run.cpp).

Against the REAL solver_runner, with job files written by the QML path
(run_config.configure_run, then DeviceSpec.to_json):
- the 1D diode's bias run opens as a result, with its progress records
  (stage first, done naming the result) and no record text in the console;
- a sweep gives one sweep_point record per point, and the result holds them;
- a job the solver refuses fails with the solver's own named error;
- a run in a directory named with non-ASCII characters succeeds;
- unflushed lines arrive while the child runs.

Against fake solvers (desktop/tests/fake_solver.py): a crash, a non-zero
exit, a PYTCAD_ERROR payload, no RESULT_PATH, a missing result file, a
result at another path, a stderr flood, garbage, over-long lines, lines
split across reads. Each ends in a named failure or a success, never a
hang; memory stays bounded. Cancel: at once, with no file left, the whole
process tree killed; a cancel followed at once by a new run never touches
the new run; one run at a time; destroying the runner mid-run kills
silently.

Also: the job file is the given bytes, verbatim (the byte contract with
the QML job file is gated in test_run_config.py).

Skipped when the app is not built. Needs no display: the runner is Qt
Core only.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _write_jobs(d):
    from gui.services import examples, run_config
    from gui.services.device_spec import SweepSpec
    base = examples.EXAMPLES["diode_1d"]()
    run_config.configure_run(base).to_json(os.path.join(d, "diode_bias.json"))
    sweep = SweepSpec(contact="anode", start=0.0, stop=0.3, step=0.1)
    run_config.configure_run(base, sweep=sweep).to_json(os.path.join(d, "diode_sweep.json"))
    with open(os.path.join(d, "diode_sweep.count"), "w") as fh:
        fh.write(str(sweep.n_points()))


def test_job_runner(tmp_path):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    assert manifest["backend_python"], "build.ps1 found no tcad-dev interpreter"
    assert "run_tests" in manifest["tools"], "rebuild: desktop_runtime.json predates P3-S3"
    data = tmp_path / "run_data"
    data.mkdir()
    _write_jobs(str(data))
    # conda run exports these; the runner must work without them (it sets
    # the child's own), so the test process does not pass them on.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONUNBUFFERED")}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env.update({
        "TCAD_TEST_PYTHON": manifest["backend_python"],
        "TCAD_TEST_ROOT": manifest["backend_root"],
        "TCAD_TEST_DATA": str(data),
        "TCAD_TEST_FAKE": os.path.join(ROOT, "desktop", "tests", "fake_solver.py"),
        "TCAD_TEST_STRIP": manifest["runtime_bin"],
    })
    report = tmp_path / "run.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["run_tests"]), "-o", f"{report},txt"],
                         capture_output=True, text=True, env=env, timeout=900)
    text = report.read_text(encoding="utf-8") if report.exists() else out.stdout + out.stderr
    assert out.returncode == 0 and ", 0 failed," in text, text[-6000:]
