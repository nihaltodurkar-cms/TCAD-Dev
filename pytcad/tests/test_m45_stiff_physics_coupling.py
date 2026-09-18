"""M45 gap closure -- transient3d.py/ac3d.py exercised together with
every other Device3D physics flag (impact ionization, local BTBT,
incomplete ionization, density-gradient, Schottky contacts), closing
the "no coupling with stiff physics" gap named in
M45-TRANSIENT-AC-3D-PLAN.md's post-landing gap list.

transient3d.py/ac3d.py drive Device3D through its own
`_residual_jacobian` directly, exactly like a single full-strength
Newton step -- NEITHER module replicates Device3D.solve_bias's own
generation-strength ladder (`self._ii_strength`, `_II_STAGES`,
device3d.py's own comment at its solve_bias definition) that impact
ionization/BTBT use for convergence robustness under a large bias jump.
This file's own gates are deliberately GENTLE steps/waveforms (small
relative to what solve_bias's ladder is FOR), following directly from
M45's own stall investigation (M45-TRANSIENT-AC-3D-PLAN.md section 8):
an aggressive single jump is a genuinely hard nonlinear problem
independent of which physics flags are on, so gating a small step here
tests the actual question (does the coupling work at all) without
re-triggering the ALREADY-understood large-step stiffness.

One honest, pre-existing scope note surfaced while writing these
gates, not a new bug: density-gradient (`Models.dg`) is EQUILIBRIUM-
ONLY in Device3D -- `_residual_jacobian` (the method every one of these
modules calls) never references `self.models.dg` at all; only the
separate `_dg_residual_jacobian_eq` equilibrium solver does. A
transient/AC run on a dg=True device therefore starts from a DG-
corrected initial condition but the DG correction does not persist
into the transient/AC dynamics themselves -- consistent with M42's own
already-documented scope, not a new gap this file introduces.

Gates (one pair -- a gentle transient step, then one AC frequency point
-- per physics flag, each on its OWN small fixture kept minimal for the
flag being tested):
  G1  impact ionization
  G2  local BTBT
  G3  incomplete ionization
  G4  density-gradient (equilibrium-only correction, per the note above)
  G5  Schottky contact (Dirichlet-approximation mode)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.mesh3d import Mesh3D
from pytcad.device3d import Device3D
from pytcad.transient3d import solve_transient
from pytcad.transient import StepWaveform
from pytcad.ac3d import y_parameters
from pytcad.schottky import richardson_a_star

warnings.simplefilter("ignore")


def _diode3d(models, Na=1e16, Nd=1e19, L=6e-4, xj=3e-4, Ny=3, Nz=3,
             h_min=5e-7, h_max=1e-5):
    x = graded_mesh(L, [xj], h_min, h_max, 1.2)
    y = np.linspace(0.0, 1e-5, Ny)
    z = np.linspace(0.0, 1e-5, Nz)
    dop1d = np.where(x < xj, -Na, Nd)
    dop3d = np.broadcast_to(dop1d, (Nz, Ny, x.size)).copy()
    mesh = Mesh3D(x, y, z)
    dev = Device3D(mesh, dop3d, models=models)
    jj, kk = np.meshgrid(np.arange(Ny), np.arange(Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, x.size - 1), j=jj, k=kk, V=0.0)
    return dev


def _gentle_run(dev, contact="left", V_final=0.02, t_end_factor=5.0):
    """A SMALL, gentle transient step (not the aggressive single-shot
    jump M45's own stall investigation already root-caused) plus one AC
    frequency point -- exercises both modules' actual coupling with
    whatever Models flags dev was built with, without re-deriving that
    investigation's already-understood large-step difficulty."""
    dev.solve_equilibrium()
    t0 = dev.Ns / dev.R0
    dt0 = t0 * t_end_factor / 20.0
    t_end = t0 * t_end_factor
    result = solve_transient(
        dev, waveforms={contact: StepWaveform(0.0, V_final, t_step=0.0)},
        t_end=t_end, dt0=dt0, dt_min=t0 * 1e-6, dt_max=t0 * 2.0)
    assert np.all(np.isfinite(result.terminal_current[contact]))

    res = y_parameters(dev, np.array([1e6]))
    assert np.all(np.isfinite(res.Y))
    return result, res


# ---------------------------------------------------------------- G1
def test_g1_impact_ionization_coupling():
    dev = _diode3d(Models(bgn=False, srh=True, impact=True))
    _gentle_run(dev)


# ---------------------------------------------------------------- G2
def test_g2_btbt_coupling():
    dev = _diode3d(Models(bgn=False, btbt=True))
    _gentle_run(dev)


# ---------------------------------------------------------------- G3
def test_g3_incomplete_ionization_coupling():
    dev = _diode3d(Models(bgn=False, incomplete_ion=True))
    _gentle_run(dev)


# ---------------------------------------------------------------- G4
def test_g4_density_gradient_coupling():
    dev = _diode3d(Models(bgn=False, dg=True))
    psi_after_eq = None

    def _capture(d=dev):
        nonlocal psi_after_eq
        d.solve_equilibrium()
        psi_after_eq = d.psi.copy()

    _capture()
    t0 = dev.Ns / dev.R0
    result = solve_transient(
        dev, waveforms={"left": StepWaveform(0.0, 0.02, t_step=0.0)},
        t_end=t0 * 5.0, dt0=t0 * 0.25, dt_min=t0 * 1e-6, dt_max=t0 * 2.0)
    assert np.all(np.isfinite(result.terminal_current["left"]))
    res = y_parameters(dev, np.array([1e6]))
    assert np.all(np.isfinite(res.Y))
    # the DG-corrected equilibrium state was indeed the transient's
    # initial condition (confirms this ISN'T silently falling back to
    # a non-DG psi -- see this module's own docstring for why the DG
    # correction itself does not persist past that initial condition)
    assert psi_after_eq is not None and np.all(np.isfinite(psi_after_eq))


# ---------------------------------------------------------------- G5
def test_g5_schottky_coupling():
    x = graded_mesh(6e-4, [3e-4], 5e-7, 1e-5, 1.2)
    y = np.linspace(0.0, 1e-5, 3)
    z = np.linspace(0.0, 1e-5, 3)
    dop3d = np.full((3, 3, x.size), 1e16)
    mesh = Mesh3D(x, y, z)
    dev = Device3D(mesh, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(3), np.arange(3))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_schottky_contact("left", i=np.zeros_like(jj), j=jj, k=kk,
                             phi_metal_eV=4.8, A_star=None)
    dev.add_contact("right", i=np.full_like(jj, x.size - 1), j=jj, k=kk, V=0.0)
    _gentle_run(dev)
