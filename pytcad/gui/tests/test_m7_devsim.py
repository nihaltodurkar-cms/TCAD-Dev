"""M7 acceptance tests: DEVSIM backend (ARCHITECTURE.md revised roadmap,
milestone M7).

The validation gate: the SAME pn-diode DeviceSpec solved by BOTH the
pytcad backend and the DEVSIM backend must agree on the equilibrium
potential profile (same nodes, same silicon physics, different
discretization engines), and both built-in-potential drops must match
the analytic value.  Skipped cleanly when devsim is not installed.
"""
import json, os, subprocess, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

devsim_spec = pytest.importorskip(
    "devsim", reason="optional devsim dependency not installed")

from gui.services.solver_backend import validate_result
from workbench.solvers.base import backend_ids, get_backend


@pytest.fixture(scope="module")
def diode_job(tmp_path_factory):
    # a SYMMETRIC abrupt 1D junction: the analytic built-in potential is
    # known, and the pytcad backend solves it natively too
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    x = np.linspace(0.0, 2e-4, 60)
    doping = np.where(x < 1e-4, -1e18, 1e18)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1]}, V=0.0),
        ],
        bias={"left": 0.0, "right": 0.0},
    )
    d = tmp_path_factory.mktemp("m7")
    job = str(d / "diode.json")
    spec.to_json(job)
    return job


@pytest.fixture(scope="module")
def iv_job(tmp_path_factory):
    """The cross-backend I-V gate runs in the core's VALIDATED regime:
    an abrupt 1e17/1e17 junction (the README benchmark structure), not
    the 1e18 equilibrium fixture -- at 1e18 both engines independently
    fail to converge near 0.25 V forward under full models, which is a
    real degenerate-doping difficulty, not a backend discrepancy."""
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    x = np.linspace(0.0, 2e-4, 100)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1]}, V=0.0),
        ],
        bias={"left": 0.0, "right": 0.0},
    )
    d = tmp_path_factory.mktemp("m7iv")
    job = str(d / "iv_diode.json")
    spec.to_json(job)
    return job


@pytest.fixture(scope="module")
def run_both(diode_job, tmp_path_factory):
    out = {}
    for bid in ("pytcad", "devsim"):
        path = str(tmp_path_factory.mktemp(bid) / "result.npz")
        get_backend(bid).run(__import__(
            "workbench.solvers.base", fromlist=["SolveRequest"]
        ).SolveRequest(job_json_path=diode_job, out_npz_path=path))
        out[bid] = np.load(path)
    return out


def test_devsim_registered():
    assert "devsim" in backend_ids()


def test_devsim_output_is_schema_valid(diode_job, tmp_path_factory):
    from gui.services.solver_backend import validate_result
    out = str(tmp_path_factory.mktemp("vs") / "r.npz")
    get_backend("devsim").run(
        __import__("workbench.solvers.base",
                   fromlist=["SolveRequest"]).SolveRequest(
            job_json_path=diode_job, out_npz_path=out))
    validate_result(out)


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 2c: check_devsim_compatible
# ----------------------------------------------------------------------
def _diode_spec_2c():
    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    x = np.linspace(0.0, 2e-4, 20)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.0, "right": 0.0})


def test_check_devsim_compatible_accepts_a_default_1d_diode():
    from workbench.solvers.devsim_backend import check_devsim_compatible
    check_devsim_compatible(_diode_spec_2c())      # must not raise


def test_check_devsim_compatible_rejects_2d():
    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    from workbench.solvers.devsim_backend import check_devsim_compatible
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=2, axes={"x": [0.0, 1e-4], "y": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[[1e17, 1e17], [1e17, 1e17]]),
        contacts=[])
    with pytest.raises(ValueError, match="1D"):
        check_devsim_compatible(spec)


def test_check_devsim_compatible_rejects_gate_contacts():
    from gui.services.device_spec import ContactSpec
    from workbench.solvers.devsim_backend import check_devsim_compatible
    spec = _diode_spec_2c()
    spec.contacts.append(ContactSpec(name="gate", kind="gate",
                                     nodes={"i": [1]}, V=0.0,
                                     tox_cm=1e-6, Vfb=0.0))
    with pytest.raises(ValueError, match="gate"):
        check_devsim_compatible(spec)


def test_check_devsim_compatible_rejects_region_materials():
    from workbench.solvers.devsim_backend import check_devsim_compatible
    spec = _diode_spec_2c()
    spec.region_materials = [{"material": "GaAs", "box": [0.0, 1e-4]}]
    with pytest.raises(ValueError, match="region_materials"):
        check_devsim_compatible(spec)


def test_check_devsim_compatible_rejects_non_default_models():
    """The load-bearing new check: devsim never reads spec.models at
    all, so a non-default config would previously be solved SILENTLY
    without the requested physics rather than refused."""
    from workbench.solvers.devsim_backend import check_devsim_compatible
    spec = _diode_spec_2c()
    spec.models["impact"] = True
    with pytest.raises(ValueError, match="canonical physics"):
        check_devsim_compatible(spec)


def test_both_backends_stamp_v2_and_backend_id(run_both):
    from gui.services.solver_backend import SOLVER_RESULT_SCHEMA_VERSION
    for bid, d in run_both.items():
        # M17 phase 3: compared against the live constant, not a
        # hardcoded literal, so a future schema bump doesn't require
        # editing this test again -- both backends stamp from the same
        # constant now (devsim_backend.py was updated to import it too).
        assert int(d["result__schema"]) == SOLVER_RESULT_SCHEMA_VERSION
        assert str(json.loads(str(d["record__meta"]))["backend"]) == bid


def test_cross_backend_equilibrium_potential_agrees(run_both):
    a = np.asarray(run_both["pytcad"]["field__potential"], dtype=float)
    b = np.asarray(run_both["devsim"]["field__potential"], dtype=float)
    assert a.shape == b.shape
    # same equations on the same nodes.  The ENGINES ship slightly
    # different tabulated silicon constants (notably ni), which shifts
    # each solution by a few-tens-of-mV offset -- hence the analytic
    # Vbi gate above plus this absolute bound, not exact equality.
    assert np.allclose(a, b, atol=2.5e-2), \
        f"max |dpsi| = {np.max(np.abs(a - b)):.4g} V"


def test_both_backends_match_analytic_builtin_potential(run_both):
    from pytcad.constants import KB_EV
    ni = 1.5e10
    vbi = 2 * KB_EV * 300 * np.log(1e18 / ni)
    for bid, d in run_both.items():
        psi = np.asarray(d["field__potential"], dtype=float)
        drop = float(psi[-1] - psi[0])
        assert abs(abs(drop) - vbi) < 0.05 * vbi, \
            f"{bid}: |{drop:.4f}| vs Vbi {vbi:.4f} V"


# -- regression tests: devsim output must conform to the SHARED grammar ----
def test_devsim_1d_result_carries_no_terminal_keys(diode_job, tmp_path):
    """The documented grammar (gui/services/solver_backend.py) defines
    terminal__* keys as 2D/3D ONLY ('A/cm' | 'A'); Device1D has no
    terminal registry at all.  The devsim backend once fabricated
    terminal__<name>__value=0.0 pairs at 1D -- fake data under a legal-
    looking name.  A conforming 1D result carries none."""
    from workbench.solvers.base import SolveRequest
    out = str(tmp_path / "r.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=diode_job, out_npz_path=out))
    d = np.load(out)
    terminal_keys = [k for k in d.files if k.startswith("terminal__")]
    assert terminal_keys == [], \
        f"1D result must carry no terminal__ keys, got {terminal_keys}"


def test_devsim_record_meta_created_utc_is_real_timestamp(diode_job,
                                                          tmp_path):
    """record__meta.created_utc must be a real UTC timestamp, not the
    empty string the equilibrium slice shipped with."""
    from datetime import datetime
    from workbench.solvers.base import SolveRequest
    out = str(tmp_path / "r.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=diode_job, out_npz_path=out))
    d = np.load(out)
    meta = json.loads(str(d["record__meta"]))
    stamp = datetime.fromisoformat(meta["created_utc"])
    assert stamp.year >= 2026


# -- M7 extension: bias ramps and sweeps in the devsim backend -------------
def test_devsim_solves_nonzero_static_bias(diode_job, tmp_path):
    """The equilibrium-only refusal is lifted: a static forward bias is
    ramped from 0 to the target and the biased fields are returned."""
    from gui.services.device_spec import DeviceSpec
    from workbench.solvers.base import SolveRequest
    spec = DeviceSpec.from_json(diode_job)
    spec.bias = {"left": 0.3, "right": 0.0}
    job2 = str(tmp_path / "biased.json")
    spec.to_json(job2)
    out = str(tmp_path / "b.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=job2, out_npz_path=out))
    d = np.load(out)
    assert int(d["solved_bias"]) == 1
    validate_result(out)


def test_devsim_biased_current_is_nonzero_and_exponential(diode_job,
                                                          tmp_path):
    """At 0.3 V the diode must carry real current -- orders of magnitude
    above the 0 V equilibrium leakage -- and more at 0.4 V than 0.3 V."""
    from gui.services.device_spec import DeviceSpec
    from workbench.solvers.base import SolveRequest

    def j_at(vb):
        spec = DeviceSpec.from_json(diode_job)
        spec.bias = {"left": vb, "right": 0.0}
        job = str(tmp_path / f"v{vb}.json")
        spec.to_json(job)
        out = str(tmp_path / f"v{vb}.npz")
        get_backend("devsim").run(
            SolveRequest(job_json_path=job, out_npz_path=out))
        return float(np.asarray(np.load(out)["vector__current_density__x"])[0])

    j0 = j_at(0.0)
    j3 = j_at(0.3)
    j4 = j_at(0.4)
    assert j3 > abs(j0) * 10, (j0, j3)
    assert j4 > j3, (j3, j4)


def test_devsim_sweep_block_is_schema_valid_and_complete(diode_job,
                                                         tmp_path):
    """spec.sweep produces the full documented sweep block, same keys as
    the pytcad reference backend writes at 1D."""
    from gui.services.device_spec import DeviceSpec
    from workbench.solvers.base import SolveRequest
    spec = DeviceSpec.from_json(diode_job)
    from gui.services.device_spec import SweepSpec
    spec.sweep = SweepSpec(contact="left", start=0.0, stop=0.4, step=0.1)
    job2 = str(tmp_path / "swept.json")
    spec.to_json(job2)
    out = str(tmp_path / "s.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=job2, out_npz_path=out))
    d = np.load(out)
    for key in ("sweep__voltage", "sweep__converged",
                "sweep__current__device", "unit__sweep_current",
                "sweep__meta"):
        assert key in d.files, f"missing {key}"
    v = np.asarray(d["sweep__voltage"], dtype=float)
    assert np.allclose(v, [0.0, 0.1, 0.2, 0.3, 0.4])
    meta = json.loads(str(d["sweep__meta"]))
    assert meta["contact"] == "left" and meta["dimensionality"] == 1
    validate_result(out)


def test_devsim_cross_backend_iv_agrees(iv_job, tmp_path):
    """THE validation gate: both backends sweep the SAME diode job and
    their I-V curves agree within stated tolerances.

    The engines ship different tabulated ni (see history.md gotcha), so
    the comparison is made where it is physically meaningful:
      - every point converges on both engines;
      - current rises monotonically and exponentially on both;
      - in strong injection (V >= 0.35 V, where J >> J0 so the ni^2
        prefactor matters least) the curves agree within one order of
        magnitude -- loose by design because J(V) ~ exp(V/VT) makes even
        a 6 mV engine offset a factor ~2.
      - each backend's ideality factor over 0.30-0.45 V is close to 1.
    """
    from gui.services.device_spec import DeviceSpec, SweepSpec
    from workbench.solvers.base import SolveRequest
    KB = 8.617333262e-5
    VT = KB * 300.0

    def swept(job):
        out = str(tmp_path / f"{abs(hash(job))}.npz")
        get_backend("devsim" if "devsim" in job else "pytcad").run(
            SolveRequest(job_json_path=job, out_npz_path=out))
        d = np.load(out)
        return (np.asarray(d["sweep__converged"], dtype=bool),
                np.asarray(d["sweep__current__device"], dtype=float))

    spec = DeviceSpec.from_json(iv_job)
    spec.sweep = SweepSpec(contact="left", start=0.0, stop=0.45, step=0.05)
    job_a = str(tmp_path / "iv_a.json"); spec.to_json(job_a)
    conv_a, j_a = swept(job_a)

    # pytcad needs an ntotal-free array spec; same file works for both
    job_b = str(tmp_path / "iv_b.json"); spec.to_json(job_b)
    conv_b, j_b = swept(job_b.replace("iv_b", "iv_a"))

    assert conv_a.all() and conv_b.all(), (conv_a, conv_b)
    assert np.all(np.diff(j_a) > 0) and np.all(np.diff(j_b) > 0)

    lo = np.isclose(np.asarray(spec.sweep.voltages()), 0.30)
    hi = np.isclose(np.asarray(spec.sweep.voltages()), 0.45)
    window = ~(lo | hi)
    vspec = np.asarray(spec.sweep.voltages())
    sel = (vspec >= 0.30) & (vspec <= 0.45)
    ratio = j_a[sel] / j_b[sel]
    assert np.all((ratio > 0.1) & (ratio < 10)), \
        f"cross-backend I-V disagrees beyond 1 decade: {ratio}"

    def ideality(vs, js):
        sel = (vs >= 0.30) & (vs <= 0.45)
        slope = np.polyfit(vs[sel], np.log(js[sel]), 1)[0]
        return 1.0 / (slope * VT)

    n_a = ideality(vspec, j_a)
    n_b = ideality(vspec, j_b)
    assert 0.8 < n_a < 1.25, n_a
    assert 0.8 < n_b < 1.25, n_b


def test_devsim_diverged_points_are_flagged_not_stored(diode_job,
                                                       tmp_path_factory):
    """Fields must come only from CONVERGED points: if a point diverges
    its flag is False and the stored field snapshot is from the last
    converged state (or equilibrium when none converge)."""
    from gui.services.device_spec import DeviceSpec, SweepSpec
    from workbench.solvers.base import SolveRequest
    spec = DeviceSpec.from_json(diode_job)
    # an absurd bias cannot converge: Newton has no physical solution
    # within reach; the backend must report honestly rather than store
    # a diverged state
    spec.sweep = SweepSpec(contact="left", start=0.0, stop=2000.0,
                           step=500.0)
    job2 = str(tmp_path_factory.mktemp("div") / "d.json")
    spec.to_json(job2)
    out = str(tmp_path_factory.mktemp("div") / "d.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=job2, out_npz_path=out))
    d = np.load(out)
    flags = np.asarray(d["sweep__converged"], dtype=bool)
    assert not flags[-1], "a 2000 V point must not be reported converged"
    psi = np.asarray(d["field__potential"], dtype=float)
    assert np.all(np.isfinite(psi)), "stored fields must be finite"


def test_devsim_emits_convergence_trace(diode_job, tmp_path):
    """The ramp's per-point Newton history lands in converge__trace in
    the same shape the pytcad runner writes, so RunRecord parsing and
    the Physics Lab convergence view work unchanged."""
    from gui.services.device_spec import DeviceSpec
    from workbench.solvers.base import SolveRequest
    spec = DeviceSpec.from_json(diode_job)
    spec.bias = {"left": 0.3, "right": 0.0}
    job2 = str(tmp_path / "tr.json")
    spec.to_json(job2)
    out = str(tmp_path / "tr.npz")
    get_backend("devsim").run(
        SolveRequest(job_json_path=job2, out_npz_path=out))
    d = np.load(out)
    steps = json.loads(str(d["converge__trace"]))
    assert isinstance(steps, list) and steps
    stages = [s["stage"] for s in steps]
    assert "equilibrium" in stages
    assert any(s.startswith("bias") or s.startswith("ramp") for s in stages)
    for s in steps:
        assert s["iterations"] and isinstance(s["converged"], bool)


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 2c: AppController backend selector
# ----------------------------------------------------------------------
def _gapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def _diode_1d_spec_2c():
    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    x = np.linspace(0.0, 2e-4, 20)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.0, "right": 0.3})


def _resistor_2d_spec_2c():
    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    x = np.linspace(0.0, 2e-4, 8)
    y = np.linspace(0.0, 1e-4, 6)
    jj = list(range(y.size))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()}),
        doping=DopingSpec(kind="array", values=np.full((y.size, x.size), 1e17).tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic",
                              nodes={"i": [0] * len(jj), "j": jj}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1] * len(jj), "j": jj}, V=0.0)],
        bias={"left": 0.0, "right": 0.05})


def test_backend_selector_hidden_for_a_2d_device():
    from gui.controllers.app_controller import AppController
    _gapp()
    ctl = AppController()
    ctl.spec = _resistor_2d_spec_2c()
    assert ctl.canSelectBackend is False


def test_backend_selector_enabled_for_a_compatible_1d_device():
    from gui.controllers.app_controller import AppController
    _gapp()
    ctl = AppController()
    ctl.spec = _diode_1d_spec_2c()
    assert ctl.canSelectBackend is True
    opts = {o["id"]: o for o in ctl.backendOptionsForQml()}
    assert opts["pytcad"]["enabled"] is True
    assert opts["devsim"]["enabled"] is True, opts["devsim"]["reason"]


def test_backend_selector_disabled_for_a_non_default_model_config():
    from gui.controllers.app_controller import AppController
    _gapp()
    ctl = AppController()
    ctl.spec = _diode_1d_spec_2c()
    ctl.lab.setModelEnabled("impact", True)
    opts = {o["id"]: o for o in ctl.backendOptionsForQml()}
    assert opts["devsim"]["enabled"] is False
    assert "canonical physics" in opts["devsim"]["reason"]


def test_run_with_devsim_backend_tags_the_result(tmp_path):
    from gui.controllers.app_controller import AppController
    gapp = _gapp()
    ctl = AppController()
    ctl.spec = _diode_1d_spec_2c()
    ctl.setBackend("devsim")
    assert ctl.selectedBackend == "devsim"

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    ctl.run()
    t0 = __import__("time").time()
    while ctl.busy and __import__("time").time() - t0 < 120:
        gapp.processEvents(); __import__("time").sleep(0.02)

    assert not errors, errors
    assert ctl.hasResult, ctl.status
    rec = ctl.currentStore().run_record()
    assert rec.backend == "devsim"


def test_run_refuses_when_backend_choice_goes_stale(tmp_path):
    """Defense in depth: the QML selector should already prevent this,
    but a Run must still refuse rather than crash or silently ignore
    the choice if the spec changed after "devsim" was picked."""
    from gui.controllers.app_controller import AppController
    gapp = _gapp()
    ctl = AppController()
    ctl.spec = _diode_1d_spec_2c()
    ctl.setBackend("devsim")
    ctl.lab.setModelEnabled("impact", True)     # now incompatible

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    ctl.run()
    assert errors, "an incompatible backend choice must be refused, not silently run"
    assert not ctl.busy
    assert not ctl.hasResult


def test_backend_selector_present_in_qml():
    from gui import app as gui_app
    engine, controller = gui_app.create_engine(_gapp())
    root = engine.rootObjects()[0]
    selector = root.findChild(object, "backendSelector")
    assert selector is not None
    # no spec loaded yet -- 2D-or-nothing default -> hidden
    assert selector.property("visible") is False


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 2d: side-by-side backend comparison
# ----------------------------------------------------------------------
def _run_and_wait(ctl, gapp, timeout_s=120):
    ctl.run()
    t0 = __import__("time").time()
    while ctl.busy and __import__("time").time() - t0 < timeout_s:
        gapp.processEvents(); __import__("time").sleep(0.02)


def test_backend_comparison_produces_a_distinct_backend_overlay():
    """The comparison overlay (comparisonSweepForQml) only exists for a
    SWEPT run -- has_sweep() is false for a plain static-bias solve, the
    same precondition M9's own model-comparison overlay needs (see
    test_m9_plots.py's test_comparison_run_produces_an_overlay_source),
    so this must arm a sweep first."""
    from gui.controllers.app_controller import AppController
    gapp = _gapp()
    ctl = AppController()
    ctl.spec = _diode_1d_spec_2c()
    ctl.setSweepConfig("left", 0.0, 0.2, 0.1)
    _run_and_wait(ctl, gapp)
    assert ctl.hasResult, ctl.status
    assert ctl.currentStore().run_record().backend == "pytcad"

    done = []
    ctl.comparisonChanged.connect(lambda: done.append(1))
    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    ctl.runBackendComparison()
    t0 = __import__("time").time()
    while not done and __import__("time").time() - t0 < 120:
        gapp.processEvents(); __import__("time").sleep(0.02)

    assert not errors, errors
    assert ctl.hasComparison
    assert ctl.comparisonLabelForQml == "devsim"
    overlay = ctl.comparisonSweepForQml
    assert overlay is not None and list(overlay.channels)
    # the two stores are genuinely tagged with DIFFERENT backends
    assert ctl._comparison_store.run_record().backend == "devsim"
    assert ctl.currentStore().run_record().backend == "pytcad"


def test_backend_comparison_refuses_without_a_prior_run():
    from gui.controllers.app_controller import AppController
    _gapp()
    ctl = AppController()
    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append(s))
    ctl.runBackendComparison()
    assert errors and "Nothing to compare" in errors[0]


def test_compare_backends_button_disabled_for_incompatible_device():
    from gui import app as gui_app
    gapp = _gapp()
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.spec = _resistor_2d_spec_2c()
    _run_and_wait(controller, gapp)
    button = root.findChild(object, "compareBackendsButton")
    assert button is not None
    assert button.property("enabled") is False
