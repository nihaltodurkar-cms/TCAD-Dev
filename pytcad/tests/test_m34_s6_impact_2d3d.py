"""M34-S6 gates: M15's coupled impact ionization in Device2D/Device3D.

See pytcad/M34-S6-PLAN.md.  The kernel is pytcad/ii_grid.py (node
generation from M15's smoothed edge currents and fields, the ionization
coefficients evaluated at the field component ALONG each carrier's
current -- the user's choice), stamped into the 2D/3D residuals with
M15's strength ladder and backtracking.

The central gate is dimensional reduction: a transversely uniform 2D or
3D diode must reproduce Device1D's M15 DISCRETE SOLUTION.  That reference
is Device1D's own residual/Jacobian driven to a fixed point with
undamped Newton steps, not Device1D.solve_bias's returned state: M15's
convergence test reads the line-search-DAMPED update, which a small step
passes early (measured at -30V: the returned state carries 0.698 of the
fixed point's current).  Tolerances are set from measured values,
quoted in each docstring.
"""
import os
import sys
import warnings

import numpy as np
import pytest
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import spsolve

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.dirichlet import eliminate_csr
from pytcad.ii_grid import grid_impact
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D

X = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=4e-6)
DOP = np.where(X < 3.0e-4, -1e16, 1e19)          # M15's one-sided junction
# coarser x for the genuinely 2D/3D devices (junction still at 3 um)
XC = graded_mesh(6.0e-4, [3.0e-4], h_min=5e-8, h_max=2e-5)
V_RED = 30.0                                     # reduction bias [V]


def _models(impact=True):
    return Models(bgn=False, srh=True, impact=impact)


def _one_sided(x):
    return np.where(x < 3.0e-4, -1e16, 1e19)


def _dev2(impact=True, x=X, y=None, dop2=None, right_rows=None):
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    if dop2 is None:
        dop2 = np.tile(_one_sided(x), (y.size, 1))
    d = Device2D(Mesh2D(x, y), dop2, T=300.0, models=_models(impact))
    d.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    d.add_contact("right", i=[x.size - 1],
                  j=list(range(y.size)) if right_rows is None else right_rows,
                  V=0.0)
    return d


def _dev3(impact=True, x=X, y=None, z=None, dop3=None, right=None):
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    z = np.linspace(0.0, 1e-5, 3) if z is None else z
    if dop3 is None:
        dop3 = np.broadcast_to(_one_sided(x), (z.size, y.size, x.size)).copy()
    d = Device3D(Mesh3D(x=x, y=y, z=z), dop3, T=300.0, models=_models(impact))
    kk, jj = np.meshgrid(range(z.size), range(y.size), indexing="ij")
    face = list(zip(jj.ravel(), kk.ravel()))
    rface = face if right is None else [f for f in face if right(y[f[0]], z[f[1]])]
    d.add_contact("left", i=[0] * len(face), j=[f[0] for f in face],
                  k=[f[1] for f in face], V=0.0)
    d.add_contact("right", i=[x.size - 1] * len(rface),
                  j=[f[0] for f in rface], k=[f[1] for f in rface], V=0.0)
    return d


def _corner(impact=True):
    """An L-shaped junction: n+ only in x > 3 um, y < 2 um; the n+
    contact covers only the n+ rows."""
    y = graded_mesh(6.0e-4, [2.0e-4], h_min=5e-7, h_max=1e-4)
    Y2, X2 = np.meshgrid(y, XC, indexing="ij")
    dop = np.where((X2 > 3.0e-4) & (Y2 < 2.0e-4), 1e19, -1e16)
    return _dev2(impact, x=XC, y=y, dop2=dop,
                 right_rows=[j for j in range(y.size) if y[j] < 2.0e-4])


def _corner3(impact=True):
    """A 3D corner: n+ only in x > 3 um, y < 2 um, z < 2 um (a cube
    corner of the junction); the n+ contact covers only the n+ face."""
    # small on purpose (3038 nodes): the gate needs genuinely 3D currents
    # where G peaks, which takes transverse nodes graded onto the 2 um
    # junction planes -- a uniform 1 um transverse mesh left the peak on
    # the finely meshed x-face with y-currents < 10% of x (measured)
    x = graded_mesh(6.0e-4, [3.0e-4], h_min=5e-7, h_max=1e-4)
    yz = np.array([0.0, 1.5, 1.9, 2.0, 2.1, 2.5, 4.0]) * 1e-4
    Z3, Y3, X3 = np.meshgrid(yz, yz, x, indexing="ij")
    dop = np.where((X3 > 3.0e-4) & (Y3 < 2.0e-4) & (Z3 < 2.0e-4), 1e19, -1e16)
    return _dev3(impact, x=x, y=yz, z=yz, dop3=dop,
                 right=lambda y, z: y < 2.0e-4 and z < 2.0e-4)


def _ramp(dev, vmax, step=2.0, record=None):
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for v in np.arange(step, vmax + 1e-9, step):
            if isinstance(dev, Device1D):
                dev.solve_bias([-float(v), 0.0], NewtonOptions())
            else:
                dev.solve_bias({"left": -float(v), "right": 0.0})
            if not dev.last_converged:
                bad.append(float(v))
            if record is not None:
                record.append(dev.terminal_current("left"))
    return bad


def _undamped(dev, args, k):
    """k plain Newton steps on the device's own residual/Jacobian (the
    solvers' density clipping, no line search) from its current state."""
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    for _ in range(k):
        F, J, *_ = dev._residual_jacobian(psi, n, p, args)
        Jd, rhs = eliminate_csr(J, -F, dev._dirichlet_rows)
        du = spsolve(Jd.tocsc(), rhs)
        sh = psi.shape
        psi = psi + du[0::3].reshape(sh)
        n = np.clip(n + du[1::3].reshape(sh), 0.1 * n, 10.0 * n)
        p = np.clip(p + du[2::3].reshape(sh), 0.1 * p, 10.0 * p)
    return psi, n, p


def _currents(out):
    """(Jn_x, ..., Jp_x, ...) from a 2D or 3D _residual_jacobian tuple."""
    J = out[2:-2]
    return J[:len(J) // 2], J[len(J) // 2:]


def test_field_along_the_current_is_what_ionizes():
    """The user's driving force, on the kernel itself: at a node where the
    current runs along x, a strong field along y does not enter E_par;
    turn the current to y and it does.  The transverse field weighs in
    only through M15's smoothing floor eps = 1e-6 max|J|, i.e. with
    weight eps/M -- that bound is the tolerance."""
    # node 0 has one x-edge (to node 1) and one y-edge (to node 2)
    psi = np.array([0.0, 10.0, 400.0])     # |E| 10 along x, 400 along y
    base = dict(h=np.array([1.0]), dJn_dpsiR=np.zeros(1), dJn_dnL=np.zeros(1),
                dJn_dnR=np.zeros(1), dJp_dpsiR=np.zeros(1),
                dJp_dpL=np.zeros(1), dJp_dpR=np.zeros(1))

    def e_par(jx, jy):
        axes = [dict(base, kL=np.array([0]), kR=np.array([1]),
                     Jn=np.array([jx]), Jp=np.array([jx])),
                dict(base, kL=np.array([0]), kR=np.array([2]),
                     Jn=np.array([jy]), Jp=np.array([jy]))]
        *_, (En, Ep) = grid_impact(3, axes, psi, 1.0, 1.0, 1.0, 1.0)
        assert En[0] == Ep[0]
        return En[0]

    assert abs(e_par(1.0, 0.0) - 10.0) <= 400.0 * 1.001e-6
    assert abs(e_par(0.0, 1.0) - 400.0) <= 10.0 * 1.001e-6
    # a 3-4-5 current direction: E_par = (3*10 + 4*400)/5
    assert e_par(3.0, 4.0) == pytest.approx(326.0, rel=1e-12)


@pytest.fixture(scope="module")
def ref1d():
    """Device1D's M15 discrete solution at -V_RED (see module docstring)."""
    d1 = Device1D(X, DOP, T=300.0, models=_models())
    d1_off = Device1D(X, DOP, T=300.0, models=_models(False))
    bad = _ramp(d1, V_RED) + _ramp(d1_off, V_RED)
    bc = d1._contact_values([-V_RED, 0.0])
    psi, n, p = _undamped(d1, bc, 4)
    _, _, Jn, Jp = d1._residual_jacobian(psi, n, p, bc)
    bco = d1_off._contact_values([-V_RED, 0.0])
    _, _, Jno, Jpo = d1_off._residual_jacobian(d1_off.psi, d1_off.n,
                                               d1_off.p, bco)
    return dict(bad=bad, psi=psi, n=n, p=p, j=Jn[0] + Jp[0],
                g=d1._ii_gs_cache.copy(), M=(Jn[0] + Jp[0]) / (Jno[0] + Jpo[0]))


def _check_reduction(dev, bad, ref, tol):
    """The gates of test_transverse_uniform_2d_reduces_to_1d_m15, for a
    2D or 3D device ramped to -V_RED; tol = (psi, dens, J, G)."""
    assert not ref["bad"] and not bad
    assert ref["M"] > 1.4
    cv = {"left": -V_RED, "right": 0.0}
    sh = dev.psi.shape
    dev._residual_jacobian(np.broadcast_to(ref["psi"], sh).copy(),
                           np.broadcast_to(ref["n"], sh).copy(),
                           np.broadcast_to(ref["p"], sh).copy(), cv)
    g = dev._ii_gs_cache.reshape(sh)
    g1 = ref["g"]
    assert g1.max() > 0.0
    assert np.abs(g[..., 1:-1] - g1[1:-1]).max() < tol[3] * g1.max()
    assert np.all(g[..., [0, -1]] == 0.0)      # contacts carry none

    floor = np.maximum(ref["n"] + ref["p"], 1e-10)
    assert np.abs(dev.psi - ref["psi"]).max() < tol[0]
    assert (np.abs(dev.n - ref["n"]) / floor).max() < tol[1]
    assert (np.abs(dev.p - ref["p"]) / floor).max() < tol[1]
    (Jn_x, *_), (Jp_x, *_) = _currents(
        dev._residual_jacobian(dev.psi, dev.n, dev.p, cv))
    j = Jn_x[..., 0] + Jp_x[..., 0]
    assert np.abs(j / ref["j"] - 1.0).max() < tol[2]
    # the solve_bias state is itself a fixed point
    (Jn_x, *_), (Jp_x, *_) = _currents(
        dev._residual_jacobian(*_undamped(dev, cv, 1), cv))
    assert np.abs((Jn_x[..., 0] + Jp_x[..., 0]) / j - 1.0).max() < tol[2]


def test_transverse_uniform_2d_reduces_to_1d_m15(ref1d):
    """A transversely uniform 2D M15 diode ramped to -30V equals Device1D's
    M15 discrete solution.  Measured 2026-09-12, limits in brackets:

    - multiplication at the 1D fixed point M = 1.5275 (> 1.4);
    - the generation the 2D device stamps at the 1D solution, every row:
      6.0e-9 of G_max (1e-6) -- the eps^2/(2 S^2) smoothing term;
    - psi 2.3e-13 (1e-9); densities against max(n + p, 1e-10), Device2D's
      M11-S5 floor: n 8.2e-12, p 4.1e-9 (1e-7);
    - the current on the p-side contact edge, every row: 4.4e-16 (1e-10).
      Read there, not as an edge mean: on the n+ side each SG current is
      a difference of O(1) densities and carries this diode's 3e-8 A/cm^2
      as round-off;
    - the 2D solve_bias state is itself a fixed point: one more undamped
      Newton step moves that current by 4.4e-16 (1e-10).  This is the gate
      on Device2D judging convergence on the full Newton correction."""
    d2 = _dev2()
    _check_reduction(d2, _ramp(d2, V_RED), ref1d, (1e-9, 1e-7, 1e-10, 1e-6))


def test_transverse_uniform_3d_reduces_to_1d_m15(ref1d):
    """Device3D's port: the same gates on a 3x3-transverse 3D diode (one
    interior transverse node, all three axes live) ramped to -30V."""
    d3 = _dev3()
    _check_reduction(d3, _ramp(d3, V_RED), ref1d, (1e-9, 1e-7, 1e-10, 1e-6))


def _fd_gate(off, on, V):
    """The FD gate of test_fd_jacobian_of_the_generation_genuinely_2d on
    any structured device: `off` is an impact-off device solved at -V,
    `on` the same device with impact on."""
    rng = np.random.default_rng(17)
    cv = {"left": -V, "right": 0.0}
    sh = off.psi.shape
    N = off.psi.size
    strides = [1, sh[-1], sh[-1] * sh[-2]][:len(sh)]   # x, y(, z)
    psi = off.psi + 1e-3 * rng.standard_normal(sh)
    n = off.n * (1 + 1e-3 * rng.standard_normal(sh))
    p = off.p * (1 + 1e-3 * rng.standard_normal(sh))

    def gen(u):
        out = on._residual_jacobian(u[0::3].reshape(sh), u[1::3].reshape(sh),
                                    u[2::3].reshape(sh), cv)
        return on._ii_gs_cache.copy(), _currents(out)

    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    G0, (Jns, Jps) = gen(u)
    # end nodes of the largest-|J| edge (axis a has stride strides[a])
    top = max(((float(np.abs(J).max()), J, strides[a]) for a, J in
               list(enumerate(Jns)) + list(enumerate(Jps))),
              key=lambda t: t[0])
    k0 = int(np.ravel_multi_index(
        np.unravel_index(int(np.argmax(np.abs(top[1]))), top[1].shape), sh))
    k_top = np.array([k0, k0 + top[2]])
    r, c, v = on._ii_jac_cache
    A = csc_matrix((v, (r, c)), shape=(N, 3 * N))
    hot = np.nonzero(G0 > 1e-3 * G0.max())[0]
    assert G0.max() > 0.0 and hot.size > 10

    # genuinely multi-dimensional: every transverse axis carries a
    # non-negligible electron current where ionization happens
    def node_sum(A, ax):
        acc = np.zeros(sh)
        lo = [slice(None)] * len(sh); lo[ax] = slice(None, -1)
        hi = [slice(None)] * len(sh); hi[ax] = slice(1, None)
        acc[tuple(lo)] += np.abs(A); acc[tuple(hi)] += np.abs(A)
        return acc.ravel()[hot]
    jx = node_sum(Jns[0], -1)
    for a in range(1, len(sh)):
        assert (node_sum(Jns[a], -1 - a) / jx).max() > 0.1, f"axis {a}"

    nb = np.concatenate([hot] + [hot + s for s in strides]
                        + [hot - s for s in strides])
    nb = np.unique(nb[(nb >= 0) & (nb < N)])
    cand = np.concatenate([3 * nb, 3 * nb + 1, 3 * nb + 2])
    picked = np.union1d(
        rng.choice(cand, size=min(150, cand.size), replace=False),
        np.concatenate([3 * k_top, 3 * k_top + 1, 3 * k_top + 2]))
    worst, used, used_top = 0.0, 0, 0
    for col in picked:
        step = (1e-9 * max(abs(u[col]), 1.0) if col % 3 == 0
                else 1e-7 * u[col])
        up = u.copy(); up[col] += step
        um = u.copy(); um[col] -= step
        fd = (gen(up)[0] - gen(um)[0]) / (2.0 * step)
        an = A[:, col].toarray().ravel()
        scale = max(np.abs(an).max(), np.abs(fd).max())
        # A deep-minority density column (p ~ 1e-15 scaled on the n+
        # side) has dG/dp ~ 1e-16: its step moves G below its own
        # round-off, and FD returns exactly 0.  Only columns that move G
        # by >= 1e-9 of its peak are resolvable (FD round-off then ~1e-7
        # of the column, far inside 5e-5).
        if scale * step < 1e-9 * G0.max():
            continue
        used += 1
        used_top += int(col // 3 in k_top)
        worst = max(worst, float(np.abs(fd - an).max() / scale))
    assert used >= 50, f"only {used} resolvable columns"
    assert used_top >= 2, "the eps-setting edge's columns were not exercised"
    assert worst <= 5e-5, f"FD-Jacobian gate: {worst:.3e} ({used} columns)"


def test_fd_jacobian_of_the_generation_genuinely_2d():
    """dG/du, analytic vs central FD, on a genuinely 2D (corner) junction
    at -12V.  The generation is compared ON ITS OWN, through Device2D's
    caches of the stamped G and of its Jacobian: at this bias G is ~1e-5
    in scaled units against O(1) Poisson/transport entries, so inside the
    full rows its derivatives sit below their round-off and a full-row FD
    gate cannot see them at all.

    M15 G-B methodology otherwise: a randomly perturbed state (here an
    impact-off solve -- the Jacobian identity needs a realistic state, not
    the II-converged one), column-max normalization, 5e-5.  The columns
    are the unknowns of the nodes where G is within 1e-3 of its peak and
    of their grid neighbours, plus -- always -- those of the largest-|J|
    edge, which set M15's smoothing eps (its term is first order in 2D;
    omitting it measured 1e-4, the same at every FD step).  Density columns
    step by 1e-7*u, purely relative: M34-S2's 1e-4 floor made the step
    1.6e-3 of an n = 6e-9 and the FD truncation 1e-4 (measured; it drops
    100x per 10x step).  Potential columns step by 1e-9*max(|psi|, 1):
    M15's 1e-7 gave alpha(E)'s curvature a 1.1e-3 truncation here
    (measured, again 100x per 10x step).  A column whose step moves G by
    less than 1e-9 of its peak is below FD round-off and is skipped (FD
    returns exactly 0 for a deep-minority density's ~1e-16 derivative);
    at least 50 must remain.  Damaging dalpha/dE or the smoothed sign by
    10% measured 1.0e-1 here -- the gate is not blind."""
    off = _corner(False)
    assert not _ramp(off, 12.0)
    _fd_gate(off, _corner(True), 12.0)


@pytest.mark.slow
def test_fd_jacobian_of_the_generation_genuinely_3d():
    """The same gate on Device3D at a cube corner of the junction, where
    both transverse axes carry current (asserted).

    Measured 2026-09-17 (fast-suite `--durations` profiling, in the
    course of investigating why the fast suite -- documented at ~70s in
    CLAUDE.md -- was actually taking ~31 minutes wall time under
    `-n 6`): this single test costs 1724.64s (28.7 minutes) by itself,
    ~92% of the entire fast-suite run at the time. Isolated with
    per-step timing (bypassing `_fd_gate`'s FD-column loop, which turned
    out NOT to be the cost) to `_ramp(off, 12.0)`'s bias solves on
    `_corner3(False)`: the FIRST bias step alone (-2V, plain SRH
    physics, impact=False) had not converged after 60+ CPU-seconds on a
    3038-node device that solves in well under a second in every sibling
    test in this file. This is the same class of issue CLAUDE.md's
    gotchas already document for Device2D's coarse corner junctions
    (plain Newton failing/oscillating just above the density floor) --
    apparently present, and much worse, in this 3D cube-corner fixture
    too. Not root-caused or fixed here (that would mean touching
    Device3D's frozen numerical core under the M11-S3 amendment
    mechanism, out of scope for a suite-speed pass); marked `slow` to
    match its neighbor `test_curved_junction_multiplies_more_than_planar`
    below, which already carries this mark for a lesser version of the
    same reason. The 2D sibling
    (`test_fd_jacobian_of_the_generation_genuinely_2d`, ~34s) stays
    unmarked -- it is not fast by fast-suite standards either, but it is
    not the ~50x outlier this one is."""
    off = _corner3(False)
    assert not _ramp(off, 12.0)
    _fd_gate(off, _corner3(True), 12.0)


@pytest.mark.slow
def test_curved_junction_multiplies_more_than_planar():
    """Junction curvature concentrates the field, so at the same reverse
    bias an L-shaped junction multiplies more than a planar one -- the
    effect behind curvature-limited breakdown.  Direction gate only: the
    published cylindrical-junction curves (Baliga-Ghandhi 1976) are
    paywalled (M34-S6-PLAN.md section 3).  Also the ramp gate: every
    2V step to -20V converges, impact on and off.

    Multiplication is the impact-on / impact-off current at the p-side
    contact.  Measured 2026-09-12 (same x mesh for both devices): planar
    1.0000 -> 1.1275, corner 1.0000 -> 1.3344 from -2V to -20V, both
    monotone; the corner exceeds the planar value at every bias from -2V
    on (1.00003 vs 1.00000 there)."""
    m = {}
    for name, make in (("planar", lambda imp: _dev2(imp, x=XC)),
                       ("corner", _corner)):
        on, off = [], []
        assert not _ramp(make(True), 20.0, record=on)
        assert not _ramp(make(False), 20.0, record=off)
        m[name] = np.array(on) / np.array(off)
    for name in m:        # M is 1 to round-off below ~-6V (planar)
        assert np.all(np.diff(m[name]) >= -1e-12), (name, m[name])
    assert m["planar"][-1] > 1.1
    assert np.all(m["corner"][1:] > m["planar"][1:])
    assert m["corner"][-1] / m["planar"][-1] > 1.1
