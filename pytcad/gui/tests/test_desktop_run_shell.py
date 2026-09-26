"""NATIVE-DESKTOP-PLAN.md P3-S4 gates: the Run dock, the Console, Run/Stop
and open-on-success, in the native app's REAL window, run by the Qt Test
executable tcad_desktop_run_shell_tests (desktop/tests/test_run_shell.cpp).

Every run goes through the real backend service and the real solver:
- the view keeps most of the window with the Run and Console docks added;
- no Python starts until the Run dock is used;
- the diode's bias, equilibrium, sweep, transient and AC runs, a C-V run,
  and mosfet_2d / resistor_3d, each opened in its natural view from the runs
  directory, the console holding its stage lines and no record text;
- a DeviceSpec file runs; a project runs with its armed sweep and its
  models config (auger off reaches the result's run record); a flow-only
  project is refused, named;
- an invalid configuration is refused with QML's title and nothing runs; a
  non-number never leaves the form;
- Stop during the solve (no process, no file, the previous result kept) and
  before the solver starts (nothing starts); closing the window mid-run;
- Save result as; the console cap; the runs directory's retention.

Needs a real GL surface (the child runs without QT_QPA_PLATFORM=offscreen);
skipped when the app is not built.
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


def _data(d):
    from gui.services import examples
    from gui.services.device_spec import SweepSpec
    from gui.services.process_model import ProcessFlow, ProcessStep
    from gui.services.project_store import save_project
    from gui.services.solver_runner import run_job
    from gui.services.structure_model import BoundarySpec, ContactModel, MeshModel, RegionSpec, StructureModel
    examples.EXAMPLES["diode_1d"]().to_json(os.path.join(d, "diode_spec.json"))
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("p", "P side", 0.0, 2e-5, 0.0, 2e-5, -1e17),
        RegionSpec("n", "N side", 2e-5, 4e-5, 0.0, 2e-5, 1e17)],
        contacts=[ContactModel("c1", "anode", BoundarySpec("left"), 0.0),
                  ContactModel("c2", "cathode", BoundarySpec("right"), 0.0)])
    save_project(os.path.join(d, "project_models.json"), "Models project", structure, MeshModel(nx=12, ny=6),
                 ProcessFlow(), SweepSpec(contact="anode", start=0.0, stop=0.2, step=0.1), {"auger": False})
    flow = ProcessFlow()
    flow.add_step(ProcessStep(id="s1", name="Substrate", operation="substrate",
                              parameters={"doping_cm3": 1e16, "type": "p"}))
    save_project(os.path.join(d, "flow_only.json"), "Flow only", None, None, flow)
    job, res = os.path.join(d, "prev.json"), os.path.join(d, "prev.npz")
    examples.EXAMPLES["diode_1d"]().to_json(job)
    run_job(job, res)


def test_run_shell_end_to_end(tmp_path):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    assert "run_shell_tests" in manifest["tools"], "rebuild: desktop_runtime.json predates P3-S4"
    data = tmp_path / "run_shell_data"
    data.mkdir()
    _data(str(data))
    env = {k: v for k, v in os.environ.items()
           if k not in ("QT_QPA_PLATFORM", "PYTHONIOENCODING", "PYTHONUTF8", "TCAD_BACKEND_PYTHON")}
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    env["TCAD_TEST_DATA"] = str(data)
    if os.environ.get("TCAD_SHELL_SNAPSHOT"):   # window grabs to look at
        env["TCAD_SHELL_SNAPSHOT"] = os.environ["TCAD_SHELL_SNAPSHOT"]
    report = tmp_path / "run_shell.txt"
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["run_shell_tests"]), "-o", f"{report},txt"],
                         capture_output=True, text=True, env=env, timeout=1200)
    text = report.read_text(encoding="utf-8") if report.exists() else out.stdout + out.stderr
    assert out.returncode == 0, (f"exit {out.returncode & 0xFFFFFFFF:#x}\n--- report tail ---\n{text[-6000:]}"
                                 f"\n--- child output tail ---\n{(out.stdout + out.stderr)[-6000:]}")
    assert ", 0 failed," in text, text[-6000:]
