"""M21 phase-1 gates: solution-driven adaptive h-refinement (1D).

Gate reference: M21-MESHING-PLAN.md section 4.  Phase 1 is a PURE
ADDITION -- pytcad/adapt.py consumes Device1D through its public
interface and touches no residual, no Jacobian and no committed golden.

Gate order follows plan section 5 deliberately: the pure-function gates
(G1, G6) and the inert-path gate (G2) come before anything that needs a
solve, so a failure localises to indicator arithmetic rather than to the
physics.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad import Device1D, Models
from pytcad.mesh import graded_mesh, uniform_mesh, check_mesh
from pytcad import adapt


# ------------------------------------------------------------ helpers
def _diode_doping(x, na=1e16, nd=1e17):
    return np.where(x < 3.0e-4, -na, nd)


def _build(models=None):
    """Return a build_device(x) closure -- the driver never owns the
    physics, so it cannot silently drop a model flag (G7)."""
    def build(x):
        return Device1D(x, _diode_doping(x), T=300.0,
                        models=models or Models())
    return build


def _solve_eq(dev):
    dev.solve_equilibrium()


def _qoi_depletion_charge(dev):
    """Smoother than terminal current (plan 10.3): total |rho| dV."""
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho) * dev.dV))


# ---------------------------------------------------------------- G1
def test_indicators_match_analytic_forms():
    """G1: every indicator is verified against a case with a known
    closed form, not against another implementation of itself."""
    x = uniform_mesh(1.0, 50)
    a, b = 0.7, -1.3
    u = a * x**3 + b * x**2 + 2.0 * x + 0.5
    u2 = adapt.second_derivative(x, u)
    exact = 6.0 * a * x + 2.0 * b
    rel = np.abs(u2[1:-1] - exact[1:-1]) / np.abs(exact[1:-1]).max()
    assert rel.max() <= 1e-10, \
        f"G1 FAIL: cubic second derivative off by {rel.max():.3e}"

    xn = np.sort(np.r_[0.0, 1.0, np.random.default_rng(3).uniform(0, 1, 40)])
    uq = 3.0 * xn**2 - 2.0 * xn + 1.0
    u2q = adapt.second_derivative(xn, uq)
    assert np.abs(u2q[1:-1] - 6.0).max() <= 1e-8, \
        "G1 FAIL: quadratic second derivative not exact on a graded mesh"

    k = 4321.0
    xs = uniform_mesh(1e-3, 60)
    nn = 1e10 * np.exp(k * xs)
    pp = np.full_like(xs, 1e5)
    eta = adapt.indicator_log_density(xs, nn, pp)
    h = np.diff(xs)
    assert np.abs(eta / h - k).max() / k <= 1e-12, \
        "G1 FAIL: log-density indicator does not recover exp decay rate"

    xd = graded_mesh(6.0e-4, [3.0e-4], h_min=1e-7, h_max=1e-5)
    dop = _diode_doping(xd)
    ratio = check_mesh(xd, dop, verbose=False)
    assert np.array_equal(adapt.indicator_debye(xd, dop), ratio), \
        "G1 FAIL: debye indicator disagrees with check_mesh"

    xr = uniform_mesh(1.0, 40)
    dV = np.full_like(xr, 1.0 / 40)
    rate = np.exp(-((xr - 0.3) ** 2) / 1e-3)
    share = adapt.indicator_rate(xr, rate, dV)
    assert abs(share.sum() - 1.0) <= 1e-12, "G1 FAIL: rate share not normalised"
    centres = 0.5 * (xr[1:] + xr[:-1])
    assert abs(centres[int(np.argmax(share))] - 0.3) <= 0.05, \
        "G1 FAIL: rate indicator does not peak with the rate"


# ---------------------------------------------------------------- G2
def test_adequate_mesh_is_returned_unchanged():
    """G2: on a mesh that already satisfies every criterion the driver
    is INERT -- same mesh and same solution, bit for bit."""
    x0 = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=2e-7)
    build = _build()
    direct = build(x0)
    direct.solve_equilibrium()

    dev, mesh, hist = adapt.adapt_solve_1d(
        build, x0, solve=_solve_eq, qoi=_qoi_depletion_charge,
        tol=1e-2, max_passes=4)

    assert np.array_equal(mesh, x0), "G2 FAIL: adequate mesh was modified"
    assert np.array_equal(dev.psi, direct.psi), "G2 FAIL: psi differs"
    assert np.array_equal(dev.n, direct.n), "G2 FAIL: n differs"
    assert np.array_equal(dev.p, direct.p), "G2 FAIL: p differs"
    assert hist[-1]["cause"] == "already_adequate", \
        f"G2 FAIL: terminated on {hist[-1]['cause']!r}"


# ---------------------------------------------------------------- G6
def test_refinement_invariants_under_fuzz():
    """G6: whatever the input, the output mesh is well formed."""
    rng = np.random.default_rng(2026)
    ratio = 2.0    # 2:1 balance -- the bisection limit, see adapt._enforce_grading
    for trial in range(200):
        L = 10.0 ** rng.uniform(-4, -3)
        nseed = int(rng.integers(8, 60))
        x = uniform_mesh(L, nseed) if rng.random() < 0.5 else \
            graded_mesh(L, [L * rng.uniform(0.2, 0.8)],
                        h_min=L / (40 * nseed), h_max=L / nseed)
        ncell = x.size - 1
        k = int(rng.integers(0, ncell + 1))
        marked = (rng.choice(ncell, size=k, replace=False)
                  if k else np.array([], dtype=int))
        cap = int(rng.integers(x.size, x.size * 4 + 5))

        y = adapt.refine_1d(x, marked, ratio=ratio, max_nodes=cap)

        assert np.all(np.diff(y) > 0), f"trial {trial}: mesh not increasing"
        assert y[0] == x[0] and y[-1] == x[-1], \
            f"trial {trial}: endpoints not preserved exactly"
        assert y.size <= cap, f"trial {trial}: {y.size} nodes exceeds cap {cap}"
        assert np.all(np.isin(x, y)), f"trial {trial}: an input node was dropped"
        hh = np.diff(y)
        g = np.maximum(hh[1:] / hh[:-1], hh[:-1] / hh[1:])
        h0 = np.diff(x)
        g0 = np.maximum(h0[1:] / h0[:-1], h0[:-1] / h0[1:]).max() \
            if h0.size > 1 else 1.0
        # NOTE: the input is not guaranteed to be graded.  mesh.graded_mesh
        # violates its OWN documented ratio at the final cell (measured up
        # to 11.06x against a stated 1.15) because the last step is
        # truncated onto L.  Refinement must therefore never make grading
        # WORSE; demanding an absolute bound would be asserting something
        # the inputs do not provide.
        assert g.max() <= max(ratio, g0) + 1e-9, \
            f"trial {trial}: grading {g.max():.4f} worse than input {g0:.4f}"


def test_grading_violation_is_repaired_when_the_budget_allows():
    """Given headroom, refinement restores the grading invariant even on
    an input that arrives violating it."""
    x = np.array([0.0, 1.0, 1.1, 1.15, 1.175, 3.0])      # 1.825 / 0.025 jump
    h0 = np.diff(x)
    assert np.maximum(h0[1:] / h0[:-1], h0[:-1] / h0[1:]).max() > 2.0

    y = adapt.refine_1d(x, np.array([], dtype=int), ratio=2.0,
                        max_nodes=1000000)
    hh = np.diff(y)
    g = np.maximum(hh[1:] / hh[:-1], hh[:-1] / hh[1:]).max()
    assert g <= 2.0 + 1e-9, f"grading not repaired: {g:.4f}"
    assert np.all(np.isin(x, y)), "repair dropped an input node"


def test_sub_two_grading_ratio_is_refused_not_approximated():
    """Bisection cannot deliver a ratio below 2 (a refined cell abuts an
    unrefined one at exactly 2).  Asking for one must RAISE, not spin to
    the sweep cap and return a mesh that quietly fails the request."""
    x = np.array([0.0, 1.0, 1.1, 3.0])
    with pytest.raises(ValueError, match="unachievable by bisection"):
        adapt.refine_1d(x, np.array([0], dtype=int), ratio=1.2)


def test_mark_dorfler_selects_the_stated_mass():
    """Dorfler marking: the selected cells carry at least theta of the
    indicator mass, and no more cells than that requires."""
    rng = np.random.default_rng(11)
    for _ in range(50):
        eta = rng.random(int(rng.integers(5, 80))) ** 3
        for theta in (0.1, 0.5, 0.9):
            idx = adapt.mark_dorfler(eta, theta)
            assert eta[idx].sum() >= theta * eta.sum() - 1e-12
            if idx.size > 1:
                assert np.sort(eta[idx])[1:].sum() < theta * eta.sum(), \
                    "marked more cells than the mass criterion needs"
    assert adapt.mark_dorfler(np.zeros(10), 0.5).size == 0, \
        "a zero indicator must mark nothing"


# ---------------------------------------------------------------- G5
def test_flat_band_equilibrium_is_exact():
    """G5 (baseline): uniform doping at equilibrium is exactly flat, at
    every resolution -- the discretisation adds no spurious structure."""
    for n in (25, 50, 100, 200):
        x = uniform_mesh(2.0e-4, n)
        dev = Device1D(x, np.full_like(x, 1e16), T=300.0,
                       models=Models(srh=False))
        dev.solve_equilibrium()
        err = float(np.abs(dev.psi - dev.psi.mean()).max())
        assert err < 1e-9, f"G5 FAIL: flat band off by {err:.3e} at n={n}"


def test_refinement_beats_uniform_under_scale_separation():
    """G5: where the physics has SEPARATED SCALES, refining on the
    indicator beats spending the same nodes uniformly.

    The device is deliberately high-contrast (1e15 / 1e18 across a
    10 um base): L_D differs ~32x between the two sides, so a uniform
    mesh must pay the FINE spacing everywhere while an adaptive one may
    coarsen the lightly-doped drift region.  That contrast is the whole
    mechanism by which adaptivity pays, and a gate posed without it
    measures nothing -- see the companion test below.
    """
    L, XJ = 1.0e-3, 1.5e-4

    def dop(x):
        return np.where(x < XJ, 1e18, -1e15)

    def build(x):
        return Device1D(x, dop(x), T=300.0, models=Models())

    ref = build(graded_mesh(L, [XJ], h_min=2e-9, h_max=2e-7))
    ref.solve_equilibrium()
    q_ref = _qoi_depletion_charge(ref)

    dev, mesh, hist = adapt.adapt_solve_1d(
        build, uniform_mesh(L, 80), solve=_solve_eq,
        qoi=_qoi_depletion_charge, tol=1e-2, max_passes=12,
        max_nodes=200000)
    assert hist[-1]["cause"] == "converged", \
        f"G5 FAIL: did not converge ({hist[-1]['cause']})"
    err_adapt = abs(_qoi_depletion_charge(dev) - q_ref) / abs(q_ref)

    dev_u = build(uniform_mesh(L, mesh.size - 1))
    dev_u.solve_equilibrium()
    err_unif = abs(_qoi_depletion_charge(dev_u) - q_ref) / abs(q_ref)

    assert err_adapt < 0.5 * err_unif, (
        f"G5 FAIL: adaptive {err_adapt:.3e} vs uniform {err_unif:.3e} "
        f"at {mesh.size} nodes -- expected at least 2x better")
    h = np.diff(mesh)
    assert h.max() / h.min() >= 4.0, \
        f"G5 FAIL: mesh is near-uniform (span {h.max() / h.min():.1f}x)"


def test_scale_uniform_device_yields_a_near_uniform_mesh():
    """G5 (converse, stated honestly): when the physics does NOT have
    separated scales, a uniform mesh is already near-optimal and the
    driver must produce one rather than inventing false locality.

    On a 1e16/1e17 junction L_D differs by only 3.2x, so h/L_D -- a
    global CONSTRAINT, not an error indicator -- accounts for nearly all
    the refinement.  Claiming an adaptive win here would be claiming
    something untrue of the physics.
    """
    dev, mesh, hist = adapt.adapt_solve_1d(
        _build(), uniform_mesh(6.0e-4, 50), solve=_solve_eq,
        qoi=_qoi_depletion_charge, tol=1e-3, max_passes=10,
        max_nodes=100000)
    assert hist[-1]["cause"] == "converged"
    h = np.diff(mesh)
    # Bisection levels make the span a power of 2; this mesh sits at 8x
    # (three levels) against 64x for the scale-separated device above.
    # The bound is loose on purpose -- the claim is "no strong locality",
    # not an exact node count.
    assert h.max() / h.min() <= 16.0, (
        f"expected a near-uniform mesh on a scale-uniform device, got "
        f"span {h.max() / h.min():.1f}x")


# ---------------------------------------------------------------- G4
def test_qoi_converges_monotonically():
    """G4: refinement converges monotonically (parity-plan acceptance)."""
    dev, mesh, hist = adapt.adapt_solve_1d(
        _build(), uniform_mesh(6.0e-4, 50), solve=_solve_eq,
        qoi=_qoi_depletion_charge, tol=1e-3, max_passes=10,
        max_nodes=100000)

    assert hist[-1]["cause"] == "converged", \
        f"G4 FAIL: did not converge ({hist[-1]['cause']})"
    qs = np.array([h["qoi"] for h in hist])
    assert qs.size >= 3, "G4 FAIL: too few passes to judge convergence"
    deltas = np.abs(np.diff(qs)) / np.abs(qs[1:])
    assert np.all(np.diff(deltas) < 1e-12), \
        f"G4 FAIL: successive QoI changes not decreasing: {deltas}"
    assert np.all(np.diff([h["nodes"] for h in hist]) > 0), \
        "G4 FAIL: refinement added no nodes"


# ---------------------------------------------------------------- G3
def test_adapted_diode_matches_resolved_reference():
    """G3 (standing rule 3): a new mesh path ships with a golden parity
    test against the validated tensor-product path before use."""
    build = _build()
    ref = build(graded_mesh(6.0e-4, [3.0e-4], h_min=5e-9, h_max=5e-8))
    ref.solve_equilibrium()

    dev, mesh, hist = adapt.adapt_solve_1d(
        build, uniform_mesh(6.0e-4, 80), solve=_solve_eq,
        qoi=_qoi_depletion_charge, tol=1e-3, max_passes=10,
        max_nodes=100000)

    vbi_ref = float(ref.psi.max() - ref.psi.min()) * ref.VT
    vbi_ad = float(dev.psi.max() - dev.psi.min()) * dev.VT
    assert abs(vbi_ad - vbi_ref) / vbi_ref <= 1e-3, \
        f"G3 FAIL: Vbi {vbi_ad:.6f} vs reference {vbi_ref:.6f}"

    q_ref, q_ad = _qoi_depletion_charge(ref), _qoi_depletion_charge(dev)
    assert abs(q_ad - q_ref) / abs(q_ref) <= 5e-2, \
        f"G3 FAIL: depletion charge {q_ad:.6e} vs reference {q_ref:.6e}"


# ---------------------------------------------------------------- G7
def test_driver_preserves_every_physics_flag():
    """G7: the driver reproduces the physics it was handed.

    Motivated by the M15 hard-debug finding that Device2D/Device3D
    silently ignored Models(impact=True) -- a dropped flag is a hidden
    failure, so the driver must be shown never to drop one."""
    # An already-adequate mesh: one solve per flag, so the expensive
    # combinations (fd costs ~11 s per solve) stay affordable while
    # still proving the flags reach the device the driver returns.
    adequate = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=2e-7)
    for kw in ({"srh": True}, {"srh": True, "fd": True},
               {"srh": True, "tat": True},
               {"srh": True, "incomplete_ion": True},
               {"srh": True, "bgn": True}):
        dev, mesh, hist = adapt.adapt_solve_1d(
            _build(Models(**kw)), adequate, solve=_solve_eq,
            qoi=_qoi_depletion_charge, tol=1e-3, max_passes=10,
            max_nodes=100000)
        assert hist[-1]["cause"] in ("already_adequate", "converged")
        for flag, want in kw.items():
            assert getattr(dev.models, flag) == want, \
                f"G7 FAIL: driver dropped {flag} for {kw}"

    # ...and the flags must also survive an ACTUAL refinement, where the
    # driver rebuilds the device on a new mesh each pass.
    models = Models(srh=True, tat=True, bgn=True)
    dev, mesh, hist = adapt.adapt_solve_1d(
        _build(models), uniform_mesh(6.0e-4, 50), solve=_solve_eq,
        qoi=_qoi_depletion_charge, tol=1e-3, max_passes=10,
        max_nodes=100000)
    assert mesh.size > 51, "G7 FAIL: no refinement happened, nothing proven"
    assert hist[-1]["cause"] == "converged"
    for flag in ("srh", "tat", "bgn"):
        assert getattr(dev.models, flag) is True, \
            f"G7 FAIL: {flag} lost across refinement passes"


# ---------------------------------------------------------------- G8
def test_node_budget_warns_and_records_cause():
    """G8: a budget-limited result must never be presented as converged."""
    x0 = uniform_mesh(6.0e-4, 40)
    with pytest.warns(UserWarning, match="node budget"):
        dev, mesh, hist = adapt.adapt_solve_1d(
            _build(), x0, solve=_solve_eq, qoi=_qoi_depletion_charge,
            tol=1e-14, max_passes=8, max_nodes=x0.size + 12)
    assert hist[-1]["cause"] == "max_nodes", \
        f"G8 FAIL: cause recorded as {hist[-1]['cause']!r}"
    assert mesh.size <= x0.size + 12, "G8 FAIL: budget exceeded"


def test_pass_limit_warns_and_records_cause():
    """The other non-converged exit must be equally loud."""
    with pytest.warns(UserWarning, match="pass limit"):
        dev, mesh, hist = adapt.adapt_solve_1d(
            _build(), uniform_mesh(6.0e-4, 40), solve=_solve_eq,
            qoi=_qoi_depletion_charge, tol=1e-14, max_passes=2,
            max_nodes=10**6)
    assert hist[-1]["cause"] == "max_passes"


def test_non_finite_state_is_refused_not_refined_upon():
    """A NaN anywhere in the solution must stop the driver loudly.

    Without this, NaNs flow into the indicator, argsort places them
    arbitrarily, and refinement proceeds on nonsense without a word --
    the same silent-garbage failure mode the M15 pass kept turning up.
    """
    with pytest.raises(ValueError, match="non-finite"):
        adapt.mark_dorfler(np.array([1.0, np.nan, 2.0]), 0.5)

    def bad_qoi(dev):
        return float("nan")

    with pytest.raises(ValueError, match="quantity of interest"):
        adapt.adapt_solve_1d(_build(), uniform_mesh(6.0e-4, 20),
                             solve=_solve_eq, qoi=bad_qoi, max_passes=2)

    with pytest.raises(ValueError, match="non-finite"):
        adapt.adapt_solve_1d(
            _build(), uniform_mesh(6.0e-4, 20), solve=_solve_eq,
            qoi=_qoi_depletion_charge,
            indicator=lambda d: np.full(d.N - 1, np.nan), max_passes=2)


def test_zero_theta_marks_nothing():
    """theta=0: the empty set already carries zero of the mass.  Marking
    "one cell anyway" would refine forever on a criterion that asked for
    no refinement at all."""
    assert adapt.mark_dorfler(np.array([5.0, 1.0, 0.1]), 0.0).size == 0
    assert adapt.mark_dorfler(np.array([5.0, 1.0, 0.1]), -1.0).size == 0


# ------------------------------------------------------- layering pin
def test_adapt_module_layering():
    """adapt.py is a driver ABOVE the core: the core must not import it,
    and it must not reach sideways into workbench or gui."""
    import inspect
    src = inspect.getsource(adapt)
    assert "workbench" not in src and "import gui" not in src, \
        "adapt.py must not depend on workbench or gui"
    import pytcad.device as core
    assert "import adapt" not in inspect.getsource(core), \
        "the core must not import the adaptive driver"
