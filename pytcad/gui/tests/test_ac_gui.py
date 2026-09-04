"""M18 Phase 4: GUI exposure for the AC/Y-parameter analysis
(pytcad/ac.py for Device1D, pytcad/ac2d.py for Device2D). See
pytcad/M18-AC-PLAN.md sections 12-16 for the full design.

Contract under test:
  - ACSpec (gui/services/device_spec.py) validates and round-trips
    through DeviceSpec's JSON boundary, same shape as SweepSpec/
    TransientSpec.
  - solver_runner.run_job() dispatches to pytcad.ac.y_parameters()
    (Device1D) / pytcad.ac2d.y_parameters() (Device2D) -- the
    ALREADY-GATED M18 phase 1-3 solvers, never reimplemented here --
    and stamps an ac__* block NpzResultStore reads back correctly.
  - AppController's AC config slots/properties mirror the sweep/
    transient ones (arm/clear/read-back, 3-way mutual exclusion,
    pre-flight validation before Run starts a subprocess).
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    ACSpec, ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
)
from gui.tests.test_solver_backend import _diode_1d_spec, _resistor_2d_spec


# ---------------------------------------------------------------- ACSpec
def test_ac_spec_validate_values_rejects_bad_frequencies():
    with pytest.raises(ValueError, match="f_start"):
        ACSpec(contact="a", f_start=0.0, f_stop=1e9).validate_values()
    with pytest.raises(ValueError, match="f_stop"):
        ACSpec(contact="a", f_start=1e6, f_stop=1e6).validate_values()
    with pytest.raises(ValueError, match="f_stop"):
        ACSpec(contact="a", f_start=1e9, f_stop=1e6).validate_values()


def test_ac_spec_validate_values_rejects_bad_n_points():
    with pytest.raises(ValueError, match="n_points"):
        ACSpec(contact="a", f_start=1.0, f_stop=1e9, n_points=1).validate_values()


def test_ac_spec_validate_rejects_unregistered_contact():
    spec = ACSpec(contact="ghost", f_start=1.0, f_stop=1e9)
    with pytest.raises(ValueError, match="not a registered contact"):
        spec.validate(["anode", "cathode"])


def test_device_spec_ac_round_trips_through_json(tmp_path):
    spec = _diode_1d_spec(with_sweep=False)
    spec.ac = ACSpec(contact="left", f_start=1.0, f_stop=1e9, n_points=20)
    path = str(tmp_path / "spec.json")
    spec.to_json(path)
    loaded = DeviceSpec.from_json(path)
    assert loaded.ac.contact == "left"
    assert loaded.ac.f_start == pytest.approx(1.0)
    assert loaded.ac.f_stop == pytest.approx(1e9)
    assert loaded.ac.n_points == 20
    # additive-field contract: a spec with no ac configured still
    # round-trips to None, same as sweep/transient/region_materials
    plain = _diode_1d_spec(with_sweep=False)
    plain.to_json(path)
    assert DeviceSpec.from_json(path).ac is None


def test_old_job_file_without_ac_key_still_loads(tmp_path):
    import json
    d = _diode_1d_spec(with_sweep=False).to_dict()
    assert "ac" in d
    del d["ac"]
    path = str(tmp_path / "old.json")
    json.dump(d, open(path, "w"))
    assert DeviceSpec.from_json(path).ac is None


# ---------------------------------------------------------------- ACResult / ResultStore
def test_spec_result_store_answers_has_ac_honestly():
    from gui.services.result_store import SpecResultStore
    spec = _diode_1d_spec(with_sweep=False)
    store = SpecResultStore(spec)
    assert store.has_ac() is False
    with pytest.raises(KeyError):
        store.ac_result()


def test_npz_result_store_reads_back_a_hand_stamped_ac_block(tmp_path):
    from gui.services.result_store import NpzResultStore
    from gui.services.solver_backend import SOLVER_RESULT_SCHEMA_VERSION, GEOM_STRUCTURED
    x = np.linspace(0.0, 2e-4, 10)
    out = str(tmp_path / "ac_hand.npz")
    np.savez(out,
             dimensionality=np.array(1),
             solved_bias=np.array(True),
             axis_x=x,
             field__potential=np.zeros_like(x),
             unit__potential=np.array("V"),
             result__schema=np.array(SOLVER_RESULT_SCHEMA_VERSION),
             geom__kind=np.array(GEOM_STRUCTURED),
             mesh__shape=np.array([x.size]),
             nodes__count=np.array(int(x.size)),
             nodes__coords=x.reshape(-1, 1),
             ac__freqs=np.array([1.0, 10.0, 100.0]),
             ac__C=np.array([1e-7, 9e-8, 5e-8]),
             ac__G=np.array([1e-3, 2e-3, 5e-3]),
             ac__port=np.array("left"),
             unit__ac_capacitance=np.array("F/cm^2"),
             unit__ac_conductance=np.array("S/cm^2"))
    store = NpzResultStore(out)
    assert store.has_ac() is True
    res = store.ac_result()
    assert res.port == "left"
    assert np.allclose(res.freqs, [1.0, 10.0, 100.0])
    assert np.allclose(res.C, [1e-7, 9e-8, 5e-8])
    assert np.allclose(res.G, [1e-3, 2e-3, 5e-3])
    assert res.unit_c == "F/cm^2"
    assert res.unit_g == "S/cm^2"


def test_npz_result_store_has_ac_false_on_a_plain_run(tmp_path):
    from gui.services.result_store import NpzResultStore
    spec = _diode_1d_spec(with_sweep=False)
    from gui.services.solver_runner import run_job
    job, out = str(tmp_path / "job.json"), str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    assert NpzResultStore(out).has_ac() is False


# ---------------------------------------------------------------- solver dispatch (1D)
def test_cli_1d_ac_stamps_the_expected_block_and_matches_direct_call(tmp_path):
    """G-AC-1D: the stamped ac__C/ac__G must match a DIRECT call to
    pytcad.ac.y_parameters() on an independently-built, independently-
    solved copy of the SAME device -- a wiring/dispatch gate, not a
    fresh physics gate (the physics itself is already gated by
    tests/test_m18_ac.py / tests/test_m18_yparam.py)."""
    from gui.services.device_spec import ACSpec
    from gui.services.solver_runner import run_job
    from gui.services.result_store import NpzResultStore

    spec = _diode_1d_spec(with_sweep=False)
    spec.ac = ACSpec(contact="left", f_start=1.0, f_stop=1e6, n_points=5)
    job, out = str(tmp_path / "job.json"), str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)

    store = NpzResultStore(out)
    assert store.has_ac() is True
    res = store.ac_result()
    assert res.port == "left"
    assert res.freqs.size == 5
    assert np.allclose(res.freqs, np.logspace(0, 6, 5))

    # Independent reference: build + solve the SAME device directly
    # against pytcad's own core, bypassing solver_runner entirely.
    from pytcad import Device1D, Models
    from pytcad.ac import y_parameters
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    dev = Device1D(x, doping, models=Models(bgn=False))
    dev.solve_equilibrium()
    dev.solve_bias([0.3, 0.0])   # spec.bias = {"left": 0.3, "right": 0.0}
    ref = y_parameters(dev, res.freqs)
    li = ref.port_names.index("left")
    C_ref = ref.Y[:, li, li].imag / (2 * np.pi * res.freqs)
    G_ref = ref.Y[:, li, li].real
    assert np.allclose(res.C, C_ref, rtol=1e-6)
    assert np.allclose(res.G, G_ref, rtol=1e-6)


def test_cli_1d_ac_driving_the_second_contact_uses_the_right_port(tmp_path):
    """Confirms the positional contacts[0]->left/contacts[1]->right
    resolution (M18-AC-PLAN.md section 13's port-resolution note) reads
    off the CORRECT diagonal Y entry for whichever contact is driven.

    NOTE (discovered by running the real physics, not assumed): for any
    genuine two-terminal 1D device, Y11 == Y22 EXACTLY -- a consequence
    of total-current continuity (the AC current entering the left
    terminal always equals minus the current leaving the right terminal;
    there is no third conduction path in a 2-terminal Device1D).
    Confirmed directly against pytcad.ac.y_parameters() itself: driving
    "left" and driving "right" on this diode produce bit-identical C/G.
    So a "must differ" assertion is unsatisfiable for ANY correct
    dispatch on this device class -- instead, each driven contact's
    result is cross-checked against the independently-computed
    reference at ITS OWN expected port index (same style as the
    previous test's rtol=1e-6 check), which still catches a wrong
    scale/sign/unit bug even though no diagonal-value-based test can
    distinguish a port_idx=0-vs-1 swap on a 2-terminal device.
    """
    from gui.services.device_spec import ACSpec
    from gui.services.solver_runner import run_job
    from gui.services.result_store import NpzResultStore
    from pytcad import Device1D, Models
    from pytcad.ac import y_parameters

    def _run(contact):
        spec = _diode_1d_spec(with_sweep=False)
        spec.ac = ACSpec(contact=contact, f_start=1.0, f_stop=10.0, n_points=2)
        job = str(tmp_path / f"job_{contact}.json")
        out = str(tmp_path / f"out_{contact}.npz")
        spec.to_json(job)
        run_job(job, out)
        return NpzResultStore(out).ac_result()

    left = _run("left")
    right = _run("right")
    assert left.port == "left" and right.port == "right"

    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    dev = Device1D(x, doping, models=Models(bgn=False))
    dev.solve_equilibrium()
    dev.solve_bias([0.3, 0.0])
    ref = y_parameters(dev, left.freqs)
    for res, port_idx in ((left, 0), (right, 1)):
        C_ref = ref.Y[:, port_idx, port_idx].imag / (2 * np.pi * res.freqs)
        G_ref = ref.Y[:, port_idx, port_idx].real
        assert np.allclose(res.C, C_ref, rtol=1e-6)
        assert np.allclose(res.G, G_ref, rtol=1e-6)


def test_ac_absent_when_not_armed(tmp_path):
    from gui.services.solver_runner import run_job
    from gui.services.result_store import NpzResultStore
    spec = _diode_1d_spec(with_sweep=False)
    job, out = str(tmp_path / "job.json"), str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    assert NpzResultStore(out).has_ac() is False


# ---------------------------------------------------------------- solver dispatch (3D refusal)
def test_ac_refuses_on_device3d(tmp_path):
    """G-AC-3D-REFUSAL: a clear ValueError naming AC/Device3D, not a
    bare crash from deep inside ac2d.py (there is no ac3d module to
    even import)."""
    from gui.services.device_spec import ACSpec, ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    from gui.services.solver_runner import run_job
    import subprocess, sys, json

    x = np.linspace(0.0, 2e-4, 5)
    y = np.linspace(0.0, 1e-4, 4)
    z = np.linspace(0.0, 1e-4, 4)
    doping = np.full((z.size, y.size, x.size), 1e17)
    jj, kk = np.meshgrid(np.arange(y.size), np.arange(z.size))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj, "k": kk}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1] * len(jj), "j": jj, "k": kk}, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
        ac=ACSpec(contact="left", f_start=1.0, f_stop=1e6, n_points=3),
    )
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "AC" in proc.stderr and "Device3D" in proc.stderr
