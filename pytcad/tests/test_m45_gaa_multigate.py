"""M45 gap closure -- transient3d.py/ac3d.py exercised against a
GENUINELY multi-gate (GAA, 4 simultaneous GateBC objects on 4 different
faces -- 'top'/'bottom' both normal_axis='y', 'left'/'right' both
normal_axis='z') Device3D, closing the "no multi-gate (FinFET/GAA)
transient or AC test" gap named in M45-TRANSIENT-AC-3D-PLAN.md's
post-landing gap list.

Reuses `pytcad.finfet3d.build_fin_corner_slab(gaa=True)` (M42-S4's own
already-gated fixture) rather than building a new one -- it already
returns a solved Device3D with 4 simultaneous gates plus one ohmic
contact ("far", the fin's long-axis end face). No new device-core
mechanism is exercised here that ac3d.py/transient3d.py's own single-
gate gates (test_m45_ac3d.py/test_m45_transient3d.py) do not already
cover per-axis -- the point of this file is specifically to prove
SEVERAL GateBC objects (with different normal_axis, sharing one device)
work together through both modules, not any single new axis case.

Gates:
  G1  ac3d.y_parameters runs cleanly on all 5 ports (far + 4 gates);
      every gate's own low-frequency self-admittance is purely
      capacitive with a POSITIVE capacitance (a physically sane
      MOS-like oxide capacitor, not a sign error or NaN).
  G2  transient3d.solve_transient runs cleanly driving the single
      ohmic contact with a small step, all 4 gates held fixed; the
      recorded terminal current is finite for the whole run.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad.finfet3d import build_fin_corner_slab
from pytcad.ac3d import y_parameters
from pytcad.transient3d import solve_transient
from pytcad.transient import StepWaveform

warnings.simplefilter("ignore")


def _gaa_device():
    return build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=1e17,
                                 Vfb=-0.9, gaa=True, dg=False)


# ---------------------------------------------------------------- G1
def test_g1_gaa_ac_all_gates_positive_capacitance():
    dev = _gaa_device()
    assert set(dev.bcs.keys()) == {"far", "top", "left", "right", "bottom"}

    res = y_parameters(dev, np.array([1.0]))
    assert np.all(np.isfinite(res.Y))

    for gate in ("top", "left", "right", "bottom"):
        gi = res.port_names.index(gate)
        Y_gg = res.Y[0, gi, gi]
        C = Y_gg.imag / (2 * np.pi * 1.0)
        assert C > 0.0, f"gate {gate!r}: expected positive capacitance, got C={C:.3e}"


# ---------------------------------------------------------------- G2
def test_g2_gaa_transient_all_gates_fixed():
    dev = _gaa_device()
    result = solve_transient(
        dev, waveforms={"far": StepWaveform(0.0, 0.05, t_step=0.0)},
        t_end=1e-9, dt0=1e-13, dt_min=1e-15, dt_max=1e-10)
    assert result.times[-1] == pytest.approx(1e-9)
    I = result.terminal_current["far"]
    assert np.all(np.isfinite(I))
    # every gate's own bc.V is untouched by a transient run driving a
    # DIFFERENT (ohmic) contact -- GateBC voltage is not part of the
    # transient state at all (see transient3d.py's own module docstring
    # on why time-varying GateBC voltage is out of scope).
    for gate in ("top", "left", "right", "bottom"):
        assert dev.bcs[gate].Vg == 0.0
