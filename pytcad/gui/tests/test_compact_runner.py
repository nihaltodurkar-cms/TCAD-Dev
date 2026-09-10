"""M38 Phase 4: gui.services.compact_runner as a subprocess entry point.

Plan: `M38-PHASE4-PLAN.md`. Runs the module exactly as JobRunner would
(a CLI subprocess), mirroring `test_process_runner.py`'s own pattern,
and checks the manifest recovers known parameters from a real
`Device1D`/`Device2D` sweep to the same tolerances
`tests/test_m38_compact_model.py`'s G1-TCAD/G2-TCAD gates use.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _run_cli(job, tmp_path, name):
    job_path = str(tmp_path / f"{name}-job.json")
    out_path = str(tmp_path / f"{name}-result.json")
    with open(job_path, "w") as fh:
        json.dump(job, fh)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.compact_runner",
         job_path, out_path],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    return proc, out_path


def test_diode_extraction_matches_ideal_diode_law(tmp_path):
    job = {
        "kind": "diode",
        "scale": 1.0,          # 1 cm^2 -- keeps the run clear of the
                                # circuit.Circuit floating-node guard
        "L_um": 2.0, "xj_um": 1.0, "Na": 1e17, "Nd": 1e17,
        "v_start": 0.0, "v_stop": 0.76, "v_step": 0.025,
        "v_fit_min": 0.35, "v_fit_max": 0.60,
    }
    proc, out_path = _run_cli(job, tmp_path, "diode")
    assert proc.returncode == 0, proc.stderr
    assert "RESULT_PATH=" in proc.stdout
    with open(out_path) as fh:
        manifest = json.load(fh)

    assert manifest["kind"] == "diode"
    assert manifest["converged"]
    p = manifest["params"]
    # Same band test_m38_compact_model.py's G1-TCAD uses for this exact
    # fixture (a real pn-diode ideality factor near 1.0).
    assert 0.9 <= p["N"] <= 1.1
    assert p["Is"] > 0.0
    assert manifest["netlist"].startswith("* PyTCAD")
    assert len(manifest["curve"]["v"]) == len(manifest["curve"]["i_tcad"])
    assert len(manifest["curve"]["i_fit"]) == len(manifest["curve"]["v"])


def test_mosfet_extraction_matches_long_channel_theory(tmp_path):
    job = {
        "kind": "mosfet1",
        "scale": 1.0e-4,        # 1 um width, matching the library gate
        "Lg_um": 1.0, "Lsd_um": 0.5, "depth_um": 1.0,
        "Na": 5e16, "Nsd_peak": 5e18, "tox_nm": 10.0,
        "vg_start": 0.5, "vg_stop": 3.01, "vg_step": 0.25, "vds_lin": 0.1,
        "vd_start": 1.6, "vd_stop": 3.01, "vd_step": 0.2, "vgs_sat": 1.5,
    }
    proc, out_path = _run_cli(job, tmp_path, "mosfet")
    assert proc.returncode == 0, proc.stderr
    with open(out_path) as fh:
        manifest = json.load(fh)

    assert manifest["kind"] == "mosfet1"
    assert manifest["converged"]
    p = manifest["params"]
    # Same bound test_m38_compact_model.py's G2-TCAD uses for this
    # exact fixture.
    assert p["rel_rms_error"] < 0.06
    assert p["kp_WL"] > 0.0
    assert manifest["netlist"].startswith("* PyTCAD")
    assert len(manifest["curve"]["vg"]) == len(manifest["curve"]["ig_tcad"])
    assert len(manifest["curve"]["vd"]) == len(manifest["curve"]["id_tcad"])


def test_unknown_kind_fails_cleanly(tmp_path):
    proc, out_path = _run_cli({"kind": "bogus"}, tmp_path, "bogus")
    assert proc.returncode != 0
    assert "PYTCAD_ERROR=" in proc.stderr
    assert not os.path.exists(out_path)
