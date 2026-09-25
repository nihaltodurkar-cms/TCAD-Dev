"""The GUI's default (engine="auto") solve goes through
`NewtonOptions(linsolve="auto")` -- the measured per-cell choice in
pytcad/linsolve.py's _AUTO_EVIDENCE -- instead of a hardcoded "direct",
and the run record names the solver that ACTUALLY ran, never the
unresolved word "auto".

Before this, every GUI job below the 20,000-node AMG/GPU gate solved
with direct regardless of the evidence (e.g. structured 3D equilibrium,
where direct measured 187s against gmres' 2.8s on B4 full)."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from gui.services import examples, solver_runner
from pytcad import linsolve

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def test_recorded_linsolve_passes_concrete_choices_through():
    dev = SimpleNamespace(last_auto_method="gmres")
    opts = SimpleNamespace(linsolve="bicgstab")
    assert solver_runner._recorded_linsolve(dev, opts) == "bicgstab"


def test_recorded_linsolve_reports_what_auto_resolved_to():
    dev = SimpleNamespace(last_auto_method="gmres")
    opts = SimpleNamespace(linsolve="auto")
    assert solver_runner._recorded_linsolve(dev, opts) == "gmres"


def test_recorded_linsolve_auto_without_a_resolution_is_direct():
    """Device1D/Device2D.solve_equilibrium never read opts.linsolve and
    always solve direct, so an equilibrium-only 1D/2D job leaves no
    last_auto_method behind -- and direct is what ran."""
    opts = SimpleNamespace(linsolve="auto")
    assert solver_runner._recorded_linsolve(SimpleNamespace(), opts) == "direct"
    dev = SimpleNamespace(last_auto_method=None)
    assert solver_runner._recorded_linsolve(dev, opts) == "direct"


def _run(spec, tmp_path, name):
    job = str(tmp_path / f"{name}.json")
    out = str(tmp_path / f"{name}.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    with np.load(out) as z:
        meta = json.loads(str(z["record__meta"]))
        psi = np.array(z["field__potential"])
    return meta["numerics"], psi


def test_default_3d_equilibrium_job_uses_and_records_the_auto_choice(tmp_path):
    """sic_power_mosfet_3d: 5,040 nodes -- above the (3, F, F) cell's
    4,913-DOF floor, below the GUI's own 20,000-node AMG gate, so the
    default path decides. Equilibrium-only so the recorded method is
    the equilibrium's."""
    spec = examples.sic_power_mosfet_3d_example_spec()
    spec.bias = None
    spec.engine = "auto"
    n = int(np.prod(spec.mesh.shape()))
    expected, _ = linsolve.select_auto(3, False, False, dof=n)

    numerics, psi = _run(spec, tmp_path, "auto")
    assert numerics["linsolve"] == expected
    assert numerics["linsolve_requested"] == "auto"

    spec.engine = "direct"
    numerics_d, psi_d = _run(spec, tmp_path, "direct")
    assert numerics_d["linsolve"] == "direct"
    assert numerics_d["linsolve_requested"] == "direct"
    assert np.max(np.abs(psi - psi_d)) < 1e-9 * max(1.0, np.max(np.abs(psi_d)))
