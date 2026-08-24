"""Regression tests for the spec-only-session persistence gap found while
GUI-testing v0.4: a session whose only device is a built-in example (raw
v0.1 DeviceSpec) saves a project file with NO device in it, and the armed
sweep used to be restored into that empty project as a dangling setting.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import QCoreApplication

from gui.services.device_spec import SweepSpec
from gui.services.project_store import save_project


def _console_texts(app):
    m = app.consoleModel
    return [str(m.data(m.index(r, 0))) for r in range(m.rowCount())]


# ----------------------------------------------------------------------
# saving an example-only session must warn (loudly) but still write the
# sweep configuration
# ----------------------------------------------------------------------
def test_save_spec_only_session_warns_but_saves(tmp_path=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    app.loadExample("mosfet_2d")
    app.setSweepConfig("gate", 0.0, 1.0, 0.1)
    assert app.hasSweepConfig

    path = str(tmp_path / "spec_only.json") if tmp_path else "/tmp/opencode/spec_only.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    errors = []
    app.errorRaised.connect(lambda s, d: errors.append((s, d)))
    app.saveProject(path, "SpecOnly")

    assert os.path.exists(path), "warning path must still save the file"
    assert errors, "saving a deviceless session silently is the bug"
    summary, details = errors[-1]
    assert "device" in summary.lower() or "example" in summary.lower(), (summary, details)
    assert "sweep" in details.lower(), details
    # the save itself still succeeded and stayed clean
    assert not app.isDirty


# ----------------------------------------------------------------------
# loading a project that contains no device must NOT restore its sweep
# ----------------------------------------------------------------------
def test_load_deviceless_project_drops_dangling_sweep(tmp_path=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    # simulate exactly what the buggy save produced: structure=None,
    # empty process flow, sweep pointing at a contact from a dead device
    path = str(tmp_path / "dangling.json") if tmp_path else "/tmp/opencode/dangling.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_project(path, "Dangling", None, None,
                 sweep=SweepSpec(contact="gate", start=0.0, stop=1.0, step=0.1))

    app.loadProject(path)
    assert not app.hasSweepConfig, \
        "sweep restored into a project with no device -- dangling setting"
    assert any("sweep" in t.lower() for t in _console_texts(app)), \
        _console_texts(app)[-3:]
    # and Run must still fail honestly, not execute anything stale
    started = []
    errors = []
    app.errorRaised.connect(lambda s, d: errors.append(s))
    app._runner.start = lambda spec: started.append(spec)
    app.run()
    assert not started and errors and "Nothing to run" in errors[0]


# ----------------------------------------------------------------------
# a process-only project still has a route to a device (process handoff),
# so its saved sweep must survive the load untouched
# ----------------------------------------------------------------------
def test_load_process_only_project_keeps_sweep(tmp_path=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    flow_src = AppController()
    flow_src.addProcessStep("substrate", "Substrate",
                            {"length_cm": 1e-3, "background_doping_cm3": -1e16,
                             "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6,
                                      "ratio": 1.2}})

    path = str(tmp_path / "proc_only.json") if tmp_path else "/tmp/opencode/proc_only.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_project(path, "ProcOnly", None, None, flow_src.process_flow,
                 SweepSpec(contact="drain", start=0.0, stop=0.5, step=0.05))

    app = AppController()
    app.loadProject(path)
    assert app.hasSweepConfig, \
        "process-only projects keep their route to a device; sweep must survive"
    cfg = app._sweep_config
    assert (cfg.contact, cfg.stop) == ("drain", 0.5)
