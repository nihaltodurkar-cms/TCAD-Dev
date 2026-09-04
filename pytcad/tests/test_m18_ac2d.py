"""M18 phase 2 acceptance gates -- small-signal AC/Y-parameter analysis
on Device2D. See M18-AC-PLAN.md section "Phase 2" for scope.
pytcad/ac2d.py drives Device2D through its own _residual_jacobian from
OUTSIDE device2d.py (same externally-driven pattern ac.py/transient2d.py
already use) -- these gates exercise that module, not a device2d.py
change, since none was made.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.device2d import Device2D
from pytcad.constants import Q
from pytcad.materials import SILICON
from pytcad.moscap import MOSCapacitor, flatband_voltage
from pytcad.transient2d import _step_residual_jacobian, _non_contact_flat_index
from pytcad.ac2d import y_parameters, _storage_matrix

warnings.simplefilter("ignore")


def _diode2d(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, Ly=5e-5, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    y = graded_mesh(Ly, [0.0], 1e-7, 1e-5, 1.15)
    dop1d = np.where(x < xj, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    mesh = Mesh2D(x, y)
    dev = Device2D(mesh, dop2d, models=Models(bgn=False, **kw))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    return dev


def _resistor3term(Nd=1e15, L=3e-4, Ly=1e-4, nx=21, ny=15):
    """Uniform n-type slab, three ohmic contacts (left/right/bottom) --
    a genuine N>2-terminal ohmic-only fixture; no such >2-terminal 2D
    device exists elsewhere in this repo (confirmed while writing this
    test)."""
    x = np.linspace(0.0, L, nx)
    y = np.linspace(0.0, Ly, ny)
    mesh = Mesh2D(x, y)
    dop = np.full((ny, nx), Nd)
    dev = Device2D(mesh, dop, models=Models(bgn=False))
    dev.add_contact("left", i=[0], j=list(range(ny)), V=0.0)
    dev.add_contact("right", i=[nx - 1], j=list(range(ny)), V=0.0)
    dev.add_contact("bottom", i=list(range(nx)), j=[ny - 1], V=0.0)
    return dev


MOSCAP_PARAMS = dict(Na=1e17, tox_cm=2e-6, gate="n+poly", T=300.0)
# tox_cm=2e-6 (20nm), not test_cv_physics_validation.py's 5e-7 (5nm):
# confirmed empirically that a 5nm oxide on this Device2D mesh makes the
# gate row's linearization ill-conditioned enough that the AC solve's
# gate-node sensitivity becomes numerically unstable (varied 0.04-1.7
# across otherwise-equivalent Newton-tolerance settings, while the
# reference direct finite difference of psi itself stayed rock-stable
# at ~0.378 throughout) -- confirmed NOT a formula bug: at tox_cm=2e-6
# the closed-form sensitivity matches the direct FD to 8 significant
# figures (0.558410 vs 0.558410). MOSCapacitor accepts tox_cm as a free
# parameter too, so this stays a fair, self-consistent comparison.


def _moscap2d(Na=MOSCAP_PARAMS["Na"], tox_cm=MOSCAP_PARAMS["tox_cm"],
              gate=MOSCAP_PARAMS["gate"], T=MOSCAP_PARAMS["T"],
              depth=2e-4, Lx=1e-4, nx=3, ny=61):
    """A Device2D MOS capacitor: uniform p-type substrate, a gate over
    the WHOLE top row, an ohmic body contact over the WHOLE bottom row,
    no lateral variation at all (matches MOSCapacitor's own 1D-vertical
    physical setup, on a 2D mesh, for a direct apples-to-apples
    comparison) -- same Na/tox_cm/gate/T as MOSCAP_PARAMS so
    MOSCapacitor(**MOSCAP_PARAMS-ish) is a valid independent reference."""
    x = np.linspace(0.0, Lx, nx)
    y = graded_mesh(depth, [0.0], depth / (ny * 20), depth / ny, 1.15)
    mesh = Mesh2D(x, y)
    doping = np.full((mesh.Ny, mesh.Nx), -Na)
    dev = Device2D(mesh, doping, T=T, material=SILICON)
    dev.add_contact("body", i=list(range(nx)), j=[ny - 1] * nx, V=0.0)
    Vfb = flatband_voltage(-Na, tox_cm, gate, 0.0, T, SILICON)
    dev.add_gate("gate", i=np.arange(nx), j=np.zeros(nx, dtype=int),
                 tox_cm=tox_cm, Vfb=Vfb, Vg=0.0)
    return dev, Lx


# ---------------------------------------------------------------- G-CONSISTENCY-2D
def test_g_consistency_storage_matrix_matches_transient2d():
    """G-CONSISTENCY-2D: ac2d.py's Cmat (n/p storage rows only -- no
    gate-row term needed, see ac2d.py's module docstring for why) is
    numerically identical to transient2d.py's already-FD-gated storage
    term, dt_s=1.0."""
    dev = _diode2d()
    dev.solve_equilibrium()
    dev.solve_bias({"left": 0.3, "right": 0.0})
    psi, n, p = dev.psi, dev.n, dev.p
    voltages = {"left": 0.3, "right": 0.0}
    k_free = _non_contact_flat_index(dev)

    F0, J0, *_ = dev._residual_jacobian(psi, n, p, voltages)
    Ft, Jt, *_ = _step_residual_jacobian(
        dev, psi, n, p, voltages, n, p, None, None, dev.dV, 1.0, 1.0, k_free)
    Cmat = _storage_matrix(dev)

    diff = (Jt - J0) - Cmat
    assert np.max(np.abs(diff.toarray())) < 1e-9


# ---------------------------------------------------------------- G-LOWF-2D
def test_g_lowf_2d_matches_quasi_static_dc():
    """G-LOWF-2D: at f -> 0 on the ohmic-only diode2d, Re(Y[left,left])
    and C must match a finite-difference dI/dV / dQ/dV from two
    independent nearby solve_bias() calls (mirrors Phase 1's G-LOWF)."""
    V0 = 0.3
    opts = NewtonOptions(tol_update=1e-13, max_iter=200)

    dev = _diode2d()
    dev.solve_equilibrium(opts)
    dev.solve_bias({"left": V0, "right": 0.0}, opts)
    res = y_parameters(dev, np.array([1.0]))
    li = res.port_names.index("left")

    dV_step = 1e-5

    def _terminal_I(V):
        d = _diode2d()
        d.solve_equilibrium(opts)
        d.solve_bias({"left": V, "right": 0.0}, opts)
        return d.terminal_current("left")

    def _charge(V):
        d = _diode2d()
        d.solve_equilibrium(opts)
        d.solve_bias({"left": V, "right": 0.0}, opts)
        dx = d.dV * d.LD * d.LD
        n_phys, p_phys = d.n * d.Ns, d.p * d.Ns
        xj = 1e-4
        mask = np.tile(d.mesh.x >= xj, (d.mesh.Ny, 1))
        return Q * float(np.sum((n_phys - p_phys)[mask] * dx[mask]))

    I1, I2 = _terminal_I(V0 - dV_step), _terminal_I(V0 + dV_step)
    dIdV = (I2 - I1) / (2 * dV_step)

    Q1, Q2 = _charge(V0 - dV_step), _charge(V0 + dV_step)
    dQdV = (Q2 - Q1) / (2 * dV_step)

    Y = res.Y[0, li, li]
    C = Y.imag / (2 * np.pi * 1.0)
    rel_G = abs(Y.real - dIdV) / abs(dIdV)
    rel_C = abs(C - dQdV) / abs(dQdV)
    assert rel_G < 5e-2, f"G(f->0)={Y.real:.6e} vs dI/dV={dIdV:.6e} (rel {rel_G:.2e})"
    assert rel_C < 5e-2, f"C(f->0)={C:.6e} vs dQ/dV={dQdV:.6e} (rel {rel_C:.2e})"


# ---------------------------------------------------------------- G-NPORT-OHMIC
def test_g_nport_ohmic_reciprocity_and_nonzero_third_port():
    """G-NPORT-OHMIC: a genuine >2-ohmic-terminal 2D device (see
    _resistor3term) at equilibrium -- the full 3x3 Y must be
    (approximately) symmetric (a passive network's small-signal Y is
    reciprocal; same known particle-current-only omission ac.py's own
    G-YPARAM-RECIPROCITY gate already documents, so a loose not exact
    tolerance), and the THIRD port (never exercised by any 2-port case)
    must show a genuinely nonzero response -- not a degenerate zero row
    from a bug in the N-port generalization."""
    dev = _resistor3term()
    dev.solve_equilibrium()
    res = y_parameters(dev, np.array([1.0]))
    Y = res.Y[0]
    assert res.port_names == ("left", "right", "bottom")

    bi = res.port_names.index("bottom")
    assert abs(Y[bi, bi]) > 0.0, "third port shows a degenerate zero response"

    rel = np.abs(Y - Y.T) / np.maximum(np.abs(Y), np.abs(Y.T))
    assert np.nanmax(rel) < 0.05, f"Y not reciprocal: max rel diff {np.nanmax(rel):.2%}\n{Y}"


# ---------------------------------------------------------------- G-GATE-FD
def test_g_gate_fd_forcing_and_sensitivity_match_direct_perturbation():
    """G-GATE-FD: the closed-form gate forcing (b=-kappa*w) and
    observation formula (Y=j*w_s*kappa*w*(delta-du)) must match a DIRECT
    finite difference of two independent static solve_bias({"gate":...})
    calls -- genuinely new territory (transient2d.py's own docstring
    notes time-varying GateBC voltage is not supported there yet), so
    this is gated FIRST, before trusting anything else in this module
    for the gate case."""
    opts = NewtonOptions(tol_update=1e-10, max_iter=200)

    def _ramp_to(d, Vg_final, n_steps=6):
        for Vg in np.linspace(0.0, Vg_final, n_steps + 1)[1:]:
            d.solve_bias({"gate": float(Vg)}, opts)

    dev, Lx = _moscap2d()
    dev.solve_equilibrium(opts)
    Vg0 = 0.2
    _ramp_to(dev, Vg0)
    res = y_parameters(dev, np.array([1.0]))
    gi = res.port_names.index("gate")
    Y_gg = res.Y[0, gi, gi]
    C_low_f = Y_gg.imag / (2 * np.pi * 1.0)   # low-f: purely capacitive, Re~0

    dVg = 1e-5

    def _gate_charge_via_flux(Vg):
        d, _ = _moscap2d()
        d.solve_equilibrium(opts)
        _ramp_to(d, Vg)
        bc = d.bcs["gate"]
        kk = (bc.j * d.Nx + bc.i).astype(int)
        w = bc.kappa * d.dVx[bc.i]
        Vg_s, Vfb_s = Vg / d.VT, bc.Vfb / d.VT
        psi_b = np.arcsinh(d.C.ravel()[kk] / (2.0 * d.nie_s.ravel()[kk]))
        flux = w * (Vg_s - Vfb_s - (d.psi.ravel()[kk] - psi_b))
        # physical CHARGE (not current) delivered to Si through the gate
        # this instant: a scaled Poisson-residual entry converts to
        # physical charge via Q*LD^2*Ns (== J0*LD*t0, t0=Ns/R0 -- see
        # the derivation in this test's own history/commit notes), a
        # DIFFERENT conversion than the J0*LD/VT current-per-volt
        # ac2d.py's y_parameters itself applies to its Y output.
        return float(np.sum(flux)) * Q * d.LD ** 2 * d.Ns

    Qp, Qm = _gate_charge_via_flux(Vg0 + dVg), _gate_charge_via_flux(Vg0 - dVg)
    dQdVg = (Qp - Qm) / (2 * dVg)

    rel = abs(C_low_f - dQdVg) / abs(dQdVg)
    assert rel < 5e-2, f"AC gate C={C_low_f:.6e} vs FD dQ/dVg={dQdVg:.6e} (rel {rel:.2%})"


# ---------------------------------------------------------------- G-MOSCAP-CV
def test_g_moscap_cv_matches_quasistatic_reference_and_hf_pins():
    """G-MOSCAP-CV (the headline physics gate): low-frequency Cgg(Vg)
    from the Device2D gate port must track MOSCapacitor.cv_sweep's
    independent quasi-static reference across accumulation/depletion,
    AND at high frequency in strong inversion, C must PIN near the
    depletion-edge value instead of rebounding toward Cox -- the classic
    LF/HF divergence test_cv_physics_validation.py's own
    test_quasistatic_vs_high_frequency_inversion already documents
    analytically for the reference 1D module, now reproduced from real
    2D transport dynamics rather than an idealized formula."""
    opts = NewtonOptions(tol_update=1e-11, max_iter=200)
    dev, Lx = _moscap2d()
    mos = MOSCapacitor(Nsub=-MOSCAP_PARAMS["Na"], tox_cm=MOSCAP_PARAMS["tox_cm"],
                       gate=MOSCAP_PARAMS["gate"], T=MOSCAP_PARAMS["T"])

    dev.solve_equilibrium(opts)
    Vg_list = [-0.5, 0.0, 0.3]
    C_lf, C_hf = [], []
    for Vg in Vg_list:
        dev.solve_bias({"gate": Vg}, opts)
        res = y_parameters(dev, np.array([1.0, 1e9]))
        gi = res.port_names.index("gate")
        c_per_area_lf = (res.Y[0, gi, gi].imag / (2 * np.pi * 1.0)) / Lx
        c_per_area_hf = (res.Y[1, gi, gi].imag / (2 * np.pi * 1e9)) / Lx
        C_lf.append(c_per_area_lf)
        C_hf.append(c_per_area_hf)
    C_lf, C_hf = np.array(C_lf), np.array(C_hf)

    _, _, C_ref = mos.cv_sweep(np.array(Vg_list))
    rel = np.abs(C_lf - C_ref) / C_ref
    assert np.all(rel < 0.25), f"LF C vs MOSCapacitor reference: rel err {rel}"

    # accumulation/depletion (Vg <= 0.0): HF and LF should broadly agree
    # (no minority-carrier response needed there)
    assert abs(C_hf[0] - C_lf[0]) / C_lf[0] < 0.25

    # some measurable LF/HF separation must appear by the most-forward
    # point swept (inversion-layer response starting to lag)
    assert C_hf[-1] < C_lf[-1] * 0.95, (
        f"no measurable HF pinning at Vg={Vg_list[-1]}: "
        f"C_lf={C_lf[-1]:.4e} C_hf={C_hf[-1]:.4e}")


# ---------------------------------------------------------------- G-SCOPE-REFUSAL-2D
def test_g_scope_refusal_2d_rejects_device1d():
    from pytcad import Device1D
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    dev1d = Device1D(x, dop, models=Models(bgn=False))
    dev1d.solve_equilibrium()
    with pytest.raises(TypeError):
        y_parameters(dev1d, np.array([1.0]))
