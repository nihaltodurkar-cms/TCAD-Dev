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
  parity item (parity2d*);
- P2-S3 (16.3): one test per curve mode (curveMode*) on real 1D runs --
  the diode's fields, an I-V sweep, a C-V sweep, a transient and an AC
  run, the convergence trace, and the 1D bands and recombination through
  the backend; modes a result cannot show are absent; switching views
  never re-creates the GL context, and costs <= 50 ms p95.

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
    run_bench._solve(d, "diode_1d")
    _curve_results(d)                                    # P2-S3: the curve modes' inputs
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


def _curve_results(d):
    """Real runs for every curve block (as test_desktop_contracts.py's
    series_solved): a 1D I-V sweep, a transient and an AC run of the
    diode, and a C-V sweep from moscap_runner."""
    from gui.services import examples, moscap_runner
    from gui.services.device_spec import ACSpec, SweepSpec, TransientSpec, WaveformSpec
    from gui.services.solver_runner import run_job

    def solve(name, spec):
        job, res = os.path.join(d, name + ".json"), os.path.join(d, name + ".npz")
        with open(job, "w") as fh:
            json.dump(spec.to_dict(), fh)
        run_job(job, res)

    spec = examples.EXAMPLES["diode_1d"]()
    spec.sweep = SweepSpec(contact="anode", start=0.0, stop=0.6, step=0.1)
    solve("diode_1d_iv", spec)
    spec = examples.EXAMPLES["diode_1d"]()
    spec.transient = TransientSpec(contact="anode",
                                   waveform=WaveformSpec(kind="step", v0=0.3, v1=0.0, t0=0.0),
                                   t_end=1e-9, dt0=1e-10)
    solve("diode_1d_transient", spec)
    spec = examples.EXAMPLES["diode_1d"]()
    spec.ac = ACSpec(contact="anode", f_start=1.0, f_stop=1e9, n_points=7)
    solve("diode_1d_ac", spec)
    job, res = os.path.join(d, "cv.json"), os.path.join(d, "cv.npz")
    with open(job, "w") as fh:
        json.dump({"nsub_cm3": -1e17, "tox_nm": 5.0, "gate": "n+poly", "qf_cm2": 1e12,
                   "T": 300.0, "vstart": -2.0, "vstop": 2.0, "vstep": 0.1}, fh)
    moscap_runner.run_job(job, res)
    # No real run here rejects a step: the same I-V run with sweep:1 marked
    # rejected, for the convergence mode's red cross.
    with np.load(os.path.join(d, "diode_1d_iv.npz")) as z:
        arrays = {k: z[k] for k in z.files}
    trace = json.loads(str(arrays["converge__trace"]))
    assert trace[2]["stage"] == "sweep:1"
    trace[2]["converged"] = False
    arrays["converge__trace"] = np.array(json.dumps(trace))
    np.savez(os.path.join(d, "diode_1d_rejected.npz"), **arrays)
    # P2-S5 overlays: sweeps that may be drawn over diode_1d_iv (other ramps,
    # so each must be drawn on its OWN voltages), and ones that differ from it
    # in exactly one respect, which must be refused naming it.
    for name, ramp in (("diode_1d_iv_fine", (0.0, 0.4, 0.05)), ("diode_1d_iv_coarse", (0.0, 0.6, 0.3))):
        spec = examples.EXAMPLES["diode_1d"]()
        spec.sweep = SweepSpec(contact="anode", start=ramp[0], stop=ramp[1], step=ramp[2])
        solve(name, spec)
    spec = examples.EXAMPLES["diode_1d"]()
    spec.sweep = SweepSpec(contact="cathode", start=0.0, stop=0.2, step=0.1)
    solve("diode_1d_iv_cathode", spec)
    np.savez(os.path.join(d, "diode_1d_iv_unit.npz"),
             **{**arrays, "unit__sweep_current": np.array("mA/cm^2")})
    renamed = {("sweep__current__other" if k == "sweep__current__device" else k): v for k, v in arrays.items()}
    np.savez(os.path.join(d, "diode_1d_iv_channel.npz"), **renamed)
    # quantity alone differing (the real C-V file also sweeps another contact,
    # which is named first): the I-V run stamped as capacitance, and the C-V
    # run with its stamp removed (read as current, the store's default)
    meta = json.loads(str(arrays["sweep__meta"]))
    np.savez(os.path.join(d, "diode_1d_iv_quantity.npz"),
             **{**arrays, "sweep__meta": np.array(json.dumps({**meta, "quantity": "capacitance"}))})
    with np.load(os.path.join(d, "cv.npz")) as z:
        cv_arrays = {k: z[k] for k in z.files}
    cv_meta = {k: v for k, v in json.loads(str(cv_arrays["sweep__meta"])).items() if k != "quantity"}
    np.savez(os.path.join(d, "cv_as_current.npz"), **{**cv_arrays, "sweep__meta": np.array(json.dumps(cv_meta))})
    # two channels, so an overlay drawn from the wrong channel is visible:
    # "extra" = 3 x "device", on the primary and on the fine-ramp overlay
    for src, dst in (("diode_1d_iv.npz", "diode_1d_iv_2ch.npz"), ("diode_1d_iv_fine.npz", "diode_1d_iv_fine_2ch.npz")):
        with np.load(os.path.join(d, src)) as z:
            two = {k: z[k] for k in z.files}
        two["sweep__current__extra"] = 3.0 * two["sweep__current__device"]
        np.savez(os.path.join(d, dst), **two)
    # P2-S6 adversarial curve files, each a real run with one thing broken
    with np.load(os.path.join(d, "diode_1d_iv.npz")) as z:
        iv = {k: z[k] for k in z.files}
    n = iv["sweep__voltage"].size
    np.savez(os.path.join(d, "adv_all_unconverged.npz"),
             **{**iv, "sweep__converged": np.zeros(n, dtype=bool)})
    one = {k: (v[:1] if k in ("sweep__voltage", "sweep__converged", "sweep__current__device") else v)
           for k, v in iv.items()}
    np.savez(os.path.join(d, "adv_one_point.npz"), **one)
    no_metrics = json.loads(str(iv["converge__trace"]))
    for step in no_metrics:
        step["metrics"] = {}
    np.savez(os.path.join(d, "adv_trace_no_metrics.npz"),
             **{**iv, "converge__trace": np.array(json.dumps(no_metrics))})
    with np.load(os.path.join(d, "diode_1d_transient.npz")) as z:
        tr = {k: z[k] for k in z.files}
    tr["transient__current__cathode"] = np.full_like(tr["transient__current__cathode"], np.nan)
    np.savez(os.path.join(d, "adv_nan_channel.npz"), **tr)
    with np.load(os.path.join(d, "diode_1d_ac.npz")) as z:
        ac = {k: (z[k][:1] if k in ("ac__freqs", "ac__C", "ac__G") else z[k]) for k in z.files}
    np.savez(os.path.join(d, "adv_ac_one_freq.npz"), **ac)
    job, res = os.path.join(d, "cv_fine.json"), os.path.join(d, "cv_fine.npz")
    with open(job, "w") as fh:
        json.dump({"nsub_cm3": -1e17, "tox_nm": 5.0, "gate": "n+poly", "qf_cm2": 1e12,
                   "T": 300.0, "vstart": -2.0, "vstop": 2.0, "vstep": 0.25}, fh)
    moscap_runner.run_job(job, res)


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
    # A crash (0xC0000005 once, under the full suite's load: plan 16.10) ends
    # the report early; Qt prints the stack trace to the child's own output,
    # so show that too, or the next occurrence is as unexplained as the last.
    assert out.returncode == 0, (f"exit {out.returncode & 0xFFFFFFFF:#x}\n--- report tail ---\n{text[-4000:]}"
                                 f"\n--- child stdout/stderr tail ---\n{(out.stdout + out.stderr)[-8000:]}")
    assert ", 0 failed," in text, text[-6000:]
