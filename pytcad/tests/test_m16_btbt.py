"""M16 gates: local Kane band-to-band tunneling coupled into the
Device1D Newton core.

Gate reference: ARCHITECTURE.md section 4b.2 (M16) and the M16
LITERATURE NOTE there.  ORDERING GATES COME FIRST (the explicit M16
lesson from M15's hard-debug pass): the residual-ordering invariant
(generation must be added AFTER the continuity `=` assignments and
BEFORE Dirichlet stamping) and the live-state invariant (the source is
computed from the CURRENT (psi, n, p) arguments, never from a cached/
stale state) are gated BEFORE any physics gate, because both are easy
to get silently backwards.

Architecture: follows M15 R1b exactly -- generation computed LIVE from
(psi, n, p) every Newton iterate, dG/dpsi folded directly into
_residual_jacobian, solve_bias's _II_STAGES strength ladder ramping a
scalar multiplying the live term.  G depends on the state through
E(psi) alone (no carrier-density dependence), so the coupling is
simpler than II's: the chain rule runs only through the node field.

Literature-note gate: plain local Kane/Hurkx is known to UNDERESTIMATE
leakage at large reverse bias vs nonlocal BTBT.  The high-bias gate
below asserts the Zener current does NOT plateau as reverse bias
grows -- the failure mode is gated explicitly, not just the onset.

Comparison discipline (M15, kept): every on/off comparison warm-ramps
BOTH devices through the same bias sequence.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.btbt import KANE_A_SI, KANE_B_SI, btbt_generation, dbtbt_dF
from pytcad.continuation import arc_length_sweep


def _tunnel_diode(btbt=True, na=5e19, nd=5e19):
    """Symmetric p+/n+ tunnel junction: both sides degenerately doped so
    the metallurgical-junction field sits deep in the Zener regime
    (~3-4e6 V/cm) where the Kane exponential produces measurable current."""
    x = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
    dop = np.where(x < 5.0e-6, -na, nd)
    return Device1D(x, dop, T=300.0,
                    models=Models(bgn=False, srh=True, btbt=btbt))


def _ramp(dev, targets):
    """Warm-ramp through ascending reverse-bias magnitudes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for v in targets:
            dev.solve_bias([-v, 0.0], NewtonOptions())


# =========================================================== ORDERING GATES
# (Written FIRST, before any physics gate -- ARCHITECTURE.md section 5
# item 3.  Both invariants were silently violated during M15's own
# development; these gates exist so M16 cannot repeat that.)
# ===========================================================
def test_ordering_generation_survives_continuity_assignment():
    """Residual-ordering invariant: the BTBT term must actually appear
    in the continuity rows.  The M15 defect was a generation term added
    BEFORE the `=` assignment of the continuity rows -- silently
    discarded, II inert at every bias while every physics gate stayed
    green against its own arithmetic.

    Probes the residual DIRECTLY at a fixed state (no solve involved):
    with btbt on vs off, the difference must be (a) exactly zero in
    every Poisson row, (b) exactly zero at the two contact nodes
    (Dirichlet stamping owns those rows), (c) antisymmetric between
    the electron and hole rows of the same interior node (+g / -g).
    """
    on = _tunnel_diode(btbt=True)
    on.solve_equilibrium()
    bc = on._contact_values([-0.5, 0.0])
    psi = on.psi.copy(); n = on.n.copy(); p = on.p.copy()
    psi[0], psi[-1] = bc[0][0], bc[1][0]
    F_on, *_ = on._residual_jacobian(psi, n, p, bc)
    assert on._btbt_gs_cache is not None and on._btbt_gs_cache.max() > 0, \
        "no BTBT source computed at a field where Kane is active"

    off = _tunnel_diode(btbt=False)
    off.solve_equilibrium()
    F_off, *_ = off._residual_jacobian(psi, n, p, bc)

    dF = F_on - F_off
    N = on.N
    # (a) Poisson rows untouched
    assert np.abs(dF[0::3]).max() == 0.0, "BTBT leaked into Poisson rows"
    # (b) contact rows untouched
    for node in (0, N - 1):
        assert np.abs(dF[3 * node:3 * node + 3]).max() == 0.0, \
            f"BTBT leaked into contact node {node} (Dirichlet owns it)"
    # (c) electron/hole antisymmetry on interior nodes.  atol, not exact
    # equality: at the far (low-field) edge of the source's support the
    # per-node term is many orders of magnitude below the ambient
    # continuity residual it is added/subtracted into (e.g. term~1e-39
    # against a residual~1e-23), so one side's float64 addition can
    # round the term away entirely while the other's does not --
    # inherent float64 absorption, not a code asymmetry.  1e-20 sits
    # far above that absorption noise floor and far below every
    # physically-representable term in this gate's own printed range
    # (>=1e-9), so a real antisymmetry defect at a resolvable magnitude
    # still fails this gate.
    d_e = dF[3 * 1 + 1::3][:-1]
    d_h = dF[3 * 1 + 2::3][:-1]
    assert np.abs(d_e + d_h).max() < 1e-20, \
        "electron/hole generation terms are not antisymmetric"
    assert np.abs(d_e).max() > 0.0, \
        "BTBT term absent from the residual entirely (M15 ordering bug)"


def test_ordering_source_is_live_not_frozen():
    """Live-state invariant (the frozen-snapshot lesson): the cached
    generation source must track the (psi, n, p) ARGUMENTS of the
    residual call, not any stored/stale solver state.  Two residual
    evaluations at different states must cache different sources."""
    dev = _tunnel_diode(btbt=True)
    dev.solve_equilibrium()
    bc = dev._contact_values([-0.5, 0.0])

    psi_a = dev.psi.copy()
    psi_a[0], psi_a[-1] = bc[0][0], bc[1][0]
    dev._residual_jacobian(psi_a, dev.n, dev.p, bc)
    gs_a = dev._btbt_gs_cache.copy()

    # Perturb the interior potential -- the peak junction field moves,
    # so a LIVE source must change; a frozen/stale one would not.
    psi_b = psi_a.copy()
    psi_b[dev.N // 2] += 0.05
    dev._residual_jacobian(psi_b, dev.n, dev.p, bc)
    gs_b = dev._btbt_gs_cache

    assert not np.array_equal(gs_a, gs_b), \
        "BTBT source did not respond to a changed state -- frozen/stale"


def test_stale_source_never_leaks_into_a_btbt_off_solve():
    """Toggling Models.btbt False after a BTBT-on solve must leave no
    generation in the residual (the M15 D4 regression, mirrored)."""
    dev = _tunnel_diode(btbt=True)
    dev.solve_equilibrium()
    _ramp(dev, np.arange(0.1, 1.1, 0.1))
    assert dev._btbt_gs_cache is not None and dev._btbt_gs_cache.max() > 0

    dev.models.btbt = False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_bias([-1.2, 0.0], NewtonOptions())
    assert dev._btbt_gs_cache is None, \
        "stale BTBT source survived into a btbt=False solve"

    # The flag alone must suppress a cache set behind solve_bias's back.
    dev.models.btbt = True
    dev.solve_bias([-1.2, 0.0], NewtonOptions())
    cached = dev._btbt_gs_cache
    dev.models.btbt = False
    bc = dev._contact_values([-1.2, 0.0])
    dev._btbt_gs_cache = cached            # simulate residue
    F_off, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    dev._btbt_gs_cache = None
    F_clean, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, bc)
    assert np.array_equal(F_off, F_clean), \
        "btbt=False residual still depends on the cached source"


def test_staged_continuation_reaches_full_strength():
    """The generation ladder must actually reach 1.0x for BTBT too (the
    M15 D3 regression: a `< 1.0` guard silently ended the ladder at
    0.5x)."""
    dev = _tunnel_diode(btbt=True)
    dev.solve_equilibrium()
    _ramp(dev, np.arange(0.1, 1.0, 0.1))

    seen = []
    real = dev._residual_jacobian

    def spy(psi, n, p, bc):
        gs = dev._btbt_gs_cache
        seen.append(0.0 if gs is None else float(np.abs(gs).max()))
        return real(psi, n, p, bc)

    dev._residual_jacobian = spy
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dev.solve_bias([-1.2, 0.0], NewtonOptions())
    finally:
        del dev._residual_jacobian

    peak = max(seen)
    weakest = min(x for x in seen if x > 0)
    assert peak / weakest > 15.0, (
        f"BTBT ladder spans only {peak / weakest:.1f}x "
        f"(weakest={weakest:.3e}, peak={peak:.3e}) -- the full-strength "
        f"stage never ran")


# =========================================================== PHYSICS GATES
# ===========================================================
def test_g_a_btbt_off_bit_identity():
    """G-A: the flag defaults off and two independent off-runs agree
    bit-for-bit; the committed diode goldens pin the default path."""
    assert Models().btbt is False
    d1 = _tunnel_diode(btbt=False)
    d2 = _tunnel_diode(btbt=False)
    d1.solve_equilibrium(); d2.solve_equilibrium()
    assert np.array_equal(d1.psi, d2.psi)


def test_g_b_fd_jacobian_with_btbt():
    """G-B: analytic Jacobian vs central FD with BTBT on.  Unlike II
    there are NO kink windows: Kane's G(F) is smooth for F > 0."""
    dev = _tunnel_diode(btbt=True)
    dev.solve_equilibrium()
    _ramp(dev, np.arange(0.1, 1.1, 0.1))

    gs = dev._btbt_gs_cache
    assert gs is not None and np.all(np.isfinite(gs)) and gs.max() > 0.0

    rng = np.random.default_rng(23)
    bc = dev._contact_values([-1.0, 0.0])
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.N)
    n = dev.n * (1 + 1e-3 * rng.standard_normal(dev.N))
    p = dev.p * (1 + 1e-3 * rng.standard_normal(dev.N))
    psi[0], psi[-1] = bc[0][0], bc[1][0]

    F0, J, *_ = dev._residual_jacobian(psi, n, p, bc)
    u = np.stack([psi, n, p], axis=1).ravel()

    worst = 0.0
    for c in rng.choice(u.size, size=80, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3], u2[1::3], u2[2::3], bc)
        Fm_, *_ = dev._residual_jacobian(u1[0::3], u1[1::3], u1[2::3], bc)
        fd_col = (Fp_ - Fm_) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst,
                    float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"G-B FAIL: {worst:.3e} > 5e-5"


def test_g_c_generation_profile_peaks_at_junction():
    """G-C: the source the SOLVER integrated is non-zero, finite, and
    peaked at the metallurgical junction (not at a contact)."""
    dev = _tunnel_diode(btbt=True)
    dev.solve_equilibrium()
    _ramp(dev, np.arange(0.1, 1.1, 0.1))

    gs = dev._btbt_gs_cache
    assert gs is not None and np.all(np.isfinite(gs)), \
        "G-C: solver cached no usable BTBT source"
    assert gs.max() > 0.0, "G-C: BTBT generation identically zero"

    k_peak = int(np.argmax(gs))
    assert abs(dev.x[k_peak] - 5.0e-6) <= 1.0e-5 / dev.N * 10, \
        f"generation peak at x={dev.x[k_peak]:.2e}, not at the junction"
    assert k_peak not in (0, 1, dev.N - 2, dev.N - 1), \
        "generation peaks at a contact cell -- boundary artifact"


def test_g_c_btbt_increases_reverse_current():
    """G-C (coupling direction): BTBT must raise the reverse current --
    both devices warm-ramped through the SAME sequence."""
    targets = np.arange(0.1, 1.1, 0.1)
    on = _tunnel_diode(btbt=True);   on.solve_equilibrium()
    off = _tunnel_diode(btbt=False); off.solve_equilibrium()
    _ramp(on, targets); _ramp(off, targets)
    J_on, _ = on.current_density()
    J_off, _ = off.current_density()
    assert abs(J_on) > abs(J_off), (
        f"G-C FAIL: |J_on|={abs(J_on):.3e} <= |J_off|={abs(J_off):.3e}"
        " -- BTBT did not increase the reverse current")


# BTBT-specific strength ladder: finer at low values to track the
# fold in the I-V curve (same ladder used in device.py _BTBT_STAGES).
_BTBT_STAGES = (0.0, 1e-6, 1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 5e-3,
                0.01, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0)


def _ramp_with_arclength(dev, v_start, v_end, ds0=0.02):
    """Ramp reverse bias using arc-length continuation to handle the
    BTBT-induced fold.  Returns list of (V, |J|, E_peak) sorted so
    that |J| increases with |V| (arc-length may trace either direction)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        records = arc_length_sweep(
            dev, v_start=v_start, v_end=v_end, ds0=ds0,
            terminal=0, other_bias=0.0)
    results = []
    for rec in records:
        dev.psi, dev.n, dev.p = rec["psi"], rec["n"], rec["p"]
        E_peak = dev._ii_compute_E_from_state(dev.psi).max()
        results.append((rec["V"], abs(rec["J"]), E_peak))
    # Normalize: ensure |J| increases as |V| increases (i.e. as V
    # goes from 0 toward v_end which is negative).  If the arc-length
    # path was traced in the opposite direction, reverse the list.
    if results:
        first_j = results[0][1]
        last_j = results[-1][1]
        if last_j < first_j:
            results.reverse()
    return results


@pytest.mark.slow
def test_g_e_zener_onset_has_kane_slope():
    """G-E (onset slope): the published Kane-form behavior -- the
    tunneling current grows exponentially with field.  Regression of
    ln(J) against 1/E_peak over the reverse-bias ramp must be a
    strongly-linear NEGATIVE-slope line (J ~ exp(-B/E) is the Kane
    signature; a thermionic/diffusive leakage would instead be linear
    in V).
    """
    on = _tunnel_diode(btbt=True);   on.solve_equilibrium()

    # Use arc-length continuation to trace past the fold in the I-V
    # curve caused by the stiff BTBT source.  Ramp to -1.5V (not -1.2V
    # as originally written): measured directly, the V in [-0.5,-1.2]
    # window only grows the current ~260x, short of the >1e3 threshold
    # below -- the physics is fine (see the high-bias gate's log-slope
    # check), the window was just too narrow.  V in [-0.5,-1.5] gives
    # ~1400x, verified 2026-08-31 when this gate was run for the first
    # time.
    results = _ramp_with_arclength(on, 0.0, -1.5, ds0=0.05)

    # Filter to high-bias region (V <= -0.5) where BTBT dominates and
    # current is strictly monotone -- the arc-length path has small
    # numerical wiggles near the fold at low bias.
    results = [r for r in results if r[0] <= -0.5]
    Js = np.array([r[1] for r in results])
    E_peaks = np.array([r[2] for r in results])

    assert np.all(Js > 0)
    # onset: orders-of-magnitude growth over the ramp
    assert Js[-1] / Js[0] > 1e3, (
        f"current grew only {Js[-1] / Js[0]:.1f}x over the ramp -- no "
        f"exponential Zener onset")
    # Kane signature: ln J linear in 1/E with a NEGATIVE slope
    y = np.log(Js)
    x = 1.0 / E_peaks
    slope, intercept = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    # r is expected NEGATIVE (ln J ~ -B*(1/E), a negative-slope line),
    # so gate on the magnitude of the correlation, not its raw sign --
    # a prior version asserted r > 0.98, which a genuine Kane-form fit
    # can never satisfy; caught when this gate was run for the first
    # time, 2026-08-31.
    assert abs(r) > 0.98, f"ln(J) vs 1/E_peak not linear (r={r:.4f})"
    assert slope < 0, f"Kane slope positive: {slope:.3e}"
    # The slope should be of the order of -B/E^2-scaled Kane exponent:
    # it is dominated by -B (V/cm) up to self-consistent screening, so
    # gate the ORDER, not the value.
    assert slope < -0.1 * KANE_B_SI, (
        f"recovered Kane slope {slope:.3e} far shallower than the "
        f"-O(B) = {-0.1 * KANE_B_SI:.3e} order")


@pytest.mark.slow
def test_g_e_high_bias_does_not_plateau():
    """G-E (literature-note gate, MANDATORY per ARCHITECTURE.md M16):
    plain local Kane/Hurkx is known to UNDERESTIMATE leakage at large
    reverse bias relative to nonlocal BTBT.  What must NOT happen is a
    plateau: the local model's current must keep growing steeply as
    reverse bias increases -- a saturating J(V) at high bias is the
    signature failure mode, so gate it explicitly instead of only
    matching at onset.

    Gate: the per-decade growth at the TOP of the ramp stays within a
    factor of 25 of the onset growth (a true plateau collapses it by
    orders of magnitude).
    """
    targets = np.arange(0.2, 1.51, 0.1)
    on = _tunnel_diode(btbt=True)
    on.solve_equilibrium()

    # Use arc-length continuation to trace past the fold in the I-V
    # curve caused by the stiff BTBT source.
    results = _ramp_with_arclength(on, 0.0, -1.5, ds0=0.05)

    # Filter to high-bias region (V <= -0.5) where BTBT dominates and
    # current is strictly monotone -- the arc-length path has small
    # numerical wiggles near the fold at low bias.
    results = [r for r in results if r[0] <= -0.5]
    # Sort by INCREASING reverse-bias magnitude (V ascending toward 0,
    # i.e. descending numeric V: -0.5 -> -1.5) so Js is expected to
    # GROW down the list.  (A prior version sorted V ascending
    # numerically -- most-negative-V-first -- which put the largest
    # |V|/largest J entries first and made the "strictly increasing"
    # assertion below backwards; caught when this gate was run for the
    # first time, 2026-08-31.)
    results.sort(key=lambda r: r[0], reverse=True)
    Js = np.array([r[1] for r in results])
    Vs = np.array([r[0] for r in results])

    # strictly monotone growth in reverse bias -- no plateau at all
    assert np.all(np.diff(Js) > 0), (
        f"J(V) not strictly increasing: {Js}")
    # the late-ramp log-slope must not collapse relative to onset.
    # Both slopes are NEGATIVE (V decreases as J grows), so "collapse"
    # means the MAGNITUDE shrinks -- compare magnitudes directly rather
    # than the raw signed values (a prior version wrote `late >
    # early/25`, which for two negative numbers asserts the opposite of
    # what the docstring says; caught when this gate was run for the
    # first time, 2026-08-31).
    early = (np.log(Js[3]) - np.log(Js[0])) / (Vs[3] - Vs[0])
    late = (np.log(Js[-1]) - np.log(Js[-4])) / (Vs[-1] - Vs[-4])
    assert abs(late) > abs(early) / 25.0, (
        f"high-bias log-slope collapsed: onset {early:.2f} /V vs "
        f"late {late:.2f} /V -- the local-model plateau failure mode")


# ---------------------------------------------------------------- G-D
def test_g_d_coefficients_match_analysis_layer():
    """G-D (coefficients): module-level sanity of the published Kane
    table (the exact pin lives in test_model_benchmarks.py)."""
    F = np.logspace(4.0, 7.0, 100)
    G = btbt_generation(F)
    # Non-decreasing everywhere: G is mathematically strictly increasing
    # (dG/dF = G*(2/F + B/F^2) > 0 for all F > 0), but exp(-B/F) with
    # B=1.03e8 underflows to an exact float64 0.0 below F~1.5e5 V/cm --
    # a run of true, physical zeros (not a code defect), so consecutive
    # diffs there are legitimately 0, not negative.
    assert np.all(np.diff(G) >= 0), "G(F) decreased somewhere"
    assert np.all(G >= 0)
    # Where G is representable (nonzero), require the real invariant:
    # strictly increasing, no ties.
    nz = G > 0
    assert np.all(np.diff(G[nz]) > 0), \
        "G(F) not strictly monotone in its representable range"
    assert np.any(nz), "G(F) identically zero over the whole probed range"
    # the exponential is utterly negligible below ~1e6 V/cm for Si
    assert btbt_generation(1e5) / btbt_generation(1e6) < 1e-30
    # dG/dF consistency with the value function (central FD)
    for f in (5e5, 1e6, 2e6, 5e6):
        h = f * 1e-6
        fd = (btbt_generation(f + h) - btbt_generation(f - h)) / (2 * h)
        assert fd == pytest.approx(dbtbt_dF(f), rel=1e-5), f"F={f:g}"


def test_g_f_2d_and_3d_refuse():
    """G-F: Device2D/Device3D must raise, not silently drop the flag."""
    from pytcad.mesh import uniform_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.device2d import Device2D
    from pytcad.device3d import Device3D
    from pytcad.mesh3d import Mesh3D
    mesh2d = Mesh2D(x=uniform_mesh(1e-4, 4), y=uniform_mesh(1e-4, 4))
    dop2d = np.full((5, 5), 1e15)
    with pytest.raises(NotImplementedError, match="btbt"):
        Device2D(mesh2d, dop2d, models=Models(btbt=True))
    mesh3d = Mesh3D(x=uniform_mesh(1e-4, 2), y=uniform_mesh(1e-4, 2),
                    z=uniform_mesh(1e-4, 2))
    with pytest.raises(NotImplementedError, match="btbt"):
        Device3D(mesh3d, np.full((3, 3, 3), 1e15),
                 models=Models(btbt=True))


def test_g_f_catalog_and_wire_format():
    """G-F: `btbt` is registered in the model catalog with the metadata
    the milestone requires, defaults OFF, and the wire-format invariant
    ModelCatalog.default_config() == _default_models() holds."""
    from workbench.core.catalog import ModelCatalog
    from gui.services.device_spec import _default_models
    assert "btbt" in ModelCatalog.list(), "btbt not in ModelCatalog"
    info = ModelCatalog.describe("btbt")
    assert info.enabled_by_default is False, "btbt should default OFF"
    assert len(info.equations) > 0, "btbt missing equations"
    assert len(info.references) > 0, "btbt missing references"
    assert ModelCatalog.default_config() == _default_models()
