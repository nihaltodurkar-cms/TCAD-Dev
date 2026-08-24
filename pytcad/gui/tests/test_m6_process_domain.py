"""M6 acceptance tests: Process Builder -- checkpoints become
DomainDevices; per-region implants; 1D scope strictly kept
(ARCHITECTURE.md revised roadmap, milestone M6).

Contract under test:
  - A process checkpoint state maps losslessly onto an IMPORTED-shape
    DomainDevice (explicit axes + array doping), which validates and
    solves through the standard chain like any other device.
  - Implant steps accept an OPTIONAL "x_range_cm" mask (an ion-implanter
    window): zero contribution outside, unchanged inside.  Flows without
    the key behave byte-identically to before.
"""
import json, os, subprocess, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.process_model import (
    ProcessFlow, ProcessStep, validate_flow,
)
from gui.services.process_runner import run_flow


def _flow(steps):
    flow = ProcessFlow(steps=steps)
    flow_path = "/tmp/opencode/m6_flow.json"
    manifest_path = "/tmp/opencode/m6_manifest.json"
    for p in (flow_path, manifest_path):
        if os.path.exists(p):
            os.remove(p)
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        return json.load(fh)


def _substrate():
    return ProcessStep(id="sub", name="Substrate", operation="substrate",
                       parameters={"length_cm": 1e-3,
                                   "background_doping_cm3": -1e16,
                                   "mesh": {"h_min_cm": 2e-8,
                                            "h_max_cm": 2e-6,
                                            "ratio": 1.15}})


def _implant(sid, **extra):
    params = {"species": "P", "energy_keV": 50.0, "dose_cm2": 5e14}
    params.update(extra)
    return ProcessStep(id=sid, name="Implant " + sid, operation="implant",
                       parameters=params)


# ----------------------------------------------------------------------
#  checkpoint state -> DomainDevice (lossless)
# ----------------------------------------------------------------------
def test_state_maps_to_valid_imported_domain_device():
    from workbench.adapters.process import domain_from_process_state
    manifest = _flow([_substrate(), _implant("i1")])
    x = np.asarray(manifest["state_paths"])
    # load the actual checkpoint for the last step
    store_paths = manifest["state_paths"]
    last = manifest["step_ids"][-1]
    d = np.load(store_paths[last])
    dev = domain_from_process_state(d["x"], d["net_doping"],
                                    ntotal=d.get("ntotal"))
    dev.validate()
    assert dev.dimensionality == 1
    assert dev.axes["x"] == pytest.approx(np.asarray(d["x"]).tolist())
    assert np.allclose(dev.explicit_doping, d["net_doping"])


def test_spec_from_1d_checkpoint_solves(tmp_path):
    """The strongest proof: a checkpoint becomes a runnable device."""
    from gui.services.device_spec import DeviceSpec
    from gui.services.solver_backend import validate_result
    from workbench.adapters.spec import spec_from_domain
    from workbench.adapters.process import domain_from_process_store
    from gui.services.process_result_store import ProcessResultStore

    manifest = _flow([_substrate(), _implant("i1", **{"x_range_cm": [0.0, 5e-4]}),
                      _implant("i2", species="B", energy_keV=30.0,
                               dose_cm2=2e14)])
    store = ProcessResultStore(manifest)
    dev = store.domain_device("i1")
    dev.validate()
    spec = spec_from_domain(dev)
    assert isinstance(spec, DeviceSpec)
    assert spec.mesh.dimensionality == 1

    job = str(tmp_path / "ckpt.json"); out = str(tmp_path / "ckpt.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    validate_result(out)


# ----------------------------------------------------------------------
#  per-region implants
# ----------------------------------------------------------------------
def test_region_mask_implants_only_inside_window():
    manifest_masked = _flow([
        _substrate(),
        _implant("win", **{"x_range_cm": [0.0, 5e-4]}),
    ])
    manifest_open = _flow([_substrate(), _implant("open")])

    sm = np.load(manifest_masked["state_paths"]["win"])
    so = np.load(manifest_open["state_paths"]["open"])
    x = sm["x"]
    inside = (x >= 0.0) & (x <= 5e-4)

    # OUTSIDE the window: pure background -- the mask is a hard wall
    assert np.all(sm["net_doping"][~inside] == -1e16)
    # INSIDE: implanted phosphorus dominates somewhere
    assert np.max(np.abs(sm["net_doping"][inside])) > 1e16


def test_full_range_mask_matches_unmasked_exactly():
    manifest_a = _flow([_substrate(), _implant("a")])
    manifest_b = _flow([
        _substrate(),
        _implant("b", **{"x_range_cm": [0.0, 1e-3]}),
    ])
    da = np.load(manifest_a["state_paths"]["a"])
    db = np.load(manifest_b["state_paths"]["b"])
    assert np.array_equal(da["net_doping"], db["net_doping"])
    assert np.array_equal(da["species_P"], db["species_P"])


def test_window_outside_substrate_rejected_not_silently_noop():
    flow = ProcessFlow(steps=[
        _substrate(),
        _implant("bad", **{"x_range_cm": [5e-3, 6e-3]}),
    ])
    errs = validate_flow(flow)
    assert any("outside the device" in e.message for e in errs), errs
