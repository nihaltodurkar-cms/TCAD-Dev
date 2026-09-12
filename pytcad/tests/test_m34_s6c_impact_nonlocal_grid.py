"""M34-S6c gates: the nonlocal (effective-field) impact-ionization model
on structured 2D/3D grids.

See pytcad/M34-S6-PLAN.md section 2.  The kernel is pytcad/
ii_nonlocal_grid.py (`effective_field_grid`, the grid generalization of
Device1D's own pytcad/ii_nonlocal.py), feeding pytcad/ii_grid.py's
`grid_impact(..., eff=...)` -- the same generation/Jacobian stamping S6a/
S6b already gate, now with the field-along-current replaced by the
per-carrier effective field.

Reuses test_m34_s6_impact_2d3d's mesh/doping and its Device1D-fixed-point
methodology (a transversely uniform 2D/3D diode must reduce to Device1D's
own M34-S2 discrete solution, not solve_bias's damped return -- see that
module's docstring).
"""
import os
import sys

import numpy as np
import pytest
from scipy.sparse import csc_matrix

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pytcad import Device1D, Models

import test_m34_s6_impact_2d3d as s6
from test_m34_s6_impact_2d3d import (
    V_RED, _ramp, _undamped, _currents, _check_reduction,
)
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D

# S6c's own, COARSER meshes.  Every Newton iteration of every S6a/S7
# strength-ladder stage now does a sparse LU factor-and-solve (E_eff and
# its exact Jacobian, pytcad/ii_nonlocal_grid.py) instead of vectorized
# numpy -- measured on S6a's own X (h_min 2e-8 cm): a fine edge gives
# a = exp(-h/lambda) close to 1, so the exact Jacobian decays slowly
# along a chain (rows averaging ~400 entries before the 1e-15 prune),
# and one 3D reduction ramp took 237s. Coarsening h_min alone (same
# junction, same physics) cut that to 64s at N=1017 vs N=1881 -- the
# short chains this leaves are still long enough to exercise the
# nonlocal lag (test_effective_field_lags_the_local_field_at_a_narrow_
# peak needs h_min << lambda_e = 6.5e-6 cm at the peak, satisfied here).
X = s6.graded_mesh(6.0e-4, [3.0e-4], h_min=2e-7, h_max=8e-6)   # 113 nodes
DOP = np.where(X < 3.0e-4, -1e16, 1e19)
# 2D and 3D corner meshes are tuned SEPARATELY (not shared): the 2D FD
# gate needs enough nodes within 1e-3 of G's peak (`_fd_gate`'s own
# `hot.size > 10` gate) and failed at 44x43 (hot.size == 10); the 3D FD
# gate needs the global eps-setting edge (largest |J|, which sets M15's
# smoothing floor) to sit where perturbing it moves G by more than FD
# round-off, and failed (`used_top == 0`) once the 3D corner was made as
# fine as the 2D fix required -- the two constraints pull in opposite
# directions on the SAME knob, so each gets its own mesh, coarsest first.
XC2 = s6.graded_mesh(6.0e-4, [3.0e-4], h_min=1e-6, h_max=4e-5)  # 53 nodes
YC2 = s6.graded_mesh(6.0e-4, [2.0e-4], h_min=1e-6, h_max=3e-5)  # 54 nodes
XC3 = s6.graded_mesh(6.0e-4, [3.0e-4], h_min=2e-6, h_max=8e-5)  # 44 nodes
YZC3 = np.array([0.0, 1.5, 1.9, 2.0, 2.1, 2.5, 4.0]) * 1e-4     # S6a's own


def _one_sided(x):
    return np.where(x < 3.0e-4, -1e16, 1e19)


def _models_nl(impact=True, nl=True):
    return Models(bgn=False, srh=True, impact=impact, impact_nonlocal=nl)


def _dev2_nl(impact=True, nl=True, x=None, y=None, dop2=None, right_rows=None):
    x = X if x is None else x
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    if dop2 is None:
        dop2 = np.tile(_one_sided(x), (y.size, 1))
    d = Device2D(Mesh2D(x, y), dop2, T=300.0, models=_models_nl(impact, nl))
    d.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    d.add_contact("right", i=[x.size - 1],
                  j=list(range(y.size)) if right_rows is None else right_rows,
                  V=0.0)
    return d


def _dev3_nl(impact=True, nl=True, x=None, y=None, z=None, dop3=None, right=None):
    x = X if x is None else x
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    z = np.linspace(0.0, 1e-5, 3) if z is None else z
    if dop3 is None:
        dop3 = np.broadcast_to(_one_sided(x), (z.size, y.size, x.size)).copy()
    d = Device3D(Mesh3D(x=x, y=y, z=z), dop3, T=300.0,
                models=_models_nl(impact, nl))
    kk, jj = np.meshgrid(range(z.size), range(y.size), indexing="ij")
    face = list(zip(jj.ravel(), kk.ravel()))
    rface = face if right is None else [f for f in face if right(y[f[0]], z[f[1]])]
    d.add_contact("left", i=[0] * len(face), j=[f[0] for f in face],
                  k=[f[1] for f in face], V=0.0)
    d.add_contact("right", i=[x.size - 1] * len(rface),
                  j=[f[0] for f in rface], k=[f[1] for f in rface], V=0.0)
    return d


def _corner_nl(impact=True, nl=True):
    Y2, X2 = np.meshgrid(YC2, XC2, indexing="ij")
    dop = np.where((X2 > 3.0e-4) & (Y2 < 2.0e-4), 1e19, -1e16)
    return _dev2_nl(impact, nl, x=XC2, y=YC2, dop2=dop,
                    right_rows=[j for j in range(YC2.size) if YC2[j] < 2.0e-4])


def _corner3_nl(impact=True, nl=True):
    Z3, Y3, X3 = np.meshgrid(YZC3, YZC3, XC3, indexing="ij")
    dop = np.where((X3 > 3.0e-4) & (Y3 < 2.0e-4) & (Z3 < 2.0e-4), 1e19, -1e16)
    return _dev3_nl(impact, nl, x=XC3, y=YZC3, z=YZC3, dop3=dop,
                    right=lambda y, z: y < 2.0e-4 and z < 2.0e-4)


def _fd_gate_nl(off, on, V):
    """`test_m34_s6_impact_2d3d._fd_gate`, minus its `used_top >= 2`
    check: that check requires the smoothing eps's OWN edge (the
    globally largest |J|) to move G by more than FD round-off, which
    holds for the LOCAL model (measured there) but not here.  Why: in
    the nonlocal branch, `ii_grid.grid_impact`'s `gSn`/`gSp` are
    `K*alpha*u` (alpha's E-dependence is carried by the SEPARATE E_eff
    Jacobian block, `Dn`/`Dp`), dropping the local branch's
    `dalpha*(Ea - E*u)` term -- so d(G)/d(eps) is smaller in the
    nonlocal model by construction, not by a defect.  Measured directly
    (verified at S6a's own full-resolution corner mesh too, N=5978, so
    this is not a mesh-coarseness artifact): every one of the eps edge's
    6 columns lands below the same 1e-9-of-peak resolvability floor
    `_fd_gate` itself uses to skip unresolvable columns.  Everything else
    -- the `worst <= 5e-5` analytic-vs-FD check over >= 50 resolvable
    columns, which DOES include the eps-Jacobian's contribution at every
    other node -- is unchanged."""
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
    r, c, v = on._ii_jac_cache
    A = csc_matrix((v, (r, c)), shape=(N, 3 * N))
    hot = np.nonzero(G0 > 1e-3 * G0.max())[0]
    assert G0.max() > 0.0 and hot.size > 10

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
    picked = rng.choice(cand, size=min(150, cand.size), replace=False)
    worst, used = 0.0, 0
    for col in picked:
        step = (1e-9 * max(abs(u[col]), 1.0) if col % 3 == 0
                else 1e-7 * u[col])
        up = u.copy(); up[col] += step
        um = u.copy(); um[col] -= step
        fd = (gen(up)[0] - gen(um)[0]) / (2.0 * step)
        an = A[:, col].toarray().ravel()
        scale = max(np.abs(an).max(), np.abs(fd).max())
        if scale * step < 1e-9 * G0.max():
            continue
        used += 1
        worst = max(worst, float(np.abs(fd - an).max() / scale))
    assert used >= 50, f"only {used} resolvable columns"
    assert worst <= 5e-5, f"FD-Jacobian gate: {worst:.3e} ({used} columns)"


def test_grid_kernel_reduces_to_1d_on_a_single_line():
    """`effective_field_grid` on a 1-row (Ny=1) 2D "grid" -- really a
    single x line -- must reproduce `ii_nonlocal.effective_field` to
    round-off: the direction/weak-edge-inherit/DAG-walk logic collapses
    to the 1D chain when there is only one line per axis and no y-axis
    at all. Measured: E max abs diff 1.8e-12 V/cm, Jacobian bit-identical."""
    from pytcad.ii_nonlocal import effective_field
    from pytcad.ii_nonlocal_grid import effective_field_grid

    rng = np.random.default_rng(0)
    Nx = 12
    x_cm = np.cumsum(rng.uniform(1e-6, 3e-6, Nx)); x_cm -= x_cm[0]
    VT, LD, lam = 0.02585, 1e-4, 6.5e-6
    psi = np.cumsum(rng.uniform(-2, 2, Nx))
    kL = np.arange(Nx - 1); kR = kL + 1
    h = np.diff(x_cm) / LD
    axes = [dict(kL=kL, kR=kR, h=h)]

    for carrier in ("n", "p"):
        E1, D1 = effective_field(x_cm, psi, VT, lam, carrier, jacobian=True)
        Eg, Dg = effective_field_grid((1, Nx), axes, psi, VT, LD, carrier, lam)
        assert np.abs(E1 - Eg).max() < 1e-10
        assert np.abs(D1 - Dg.toarray()).max() < 1e-10


@pytest.fixture(scope="module")
def ref1d_nl():
    """Device1D's M15+M34-S2 discrete solution at -V_RED: the coupled
    local model with the coefficients evaluated at the nonlocal effective
    field, driven to its own undamped-Newton fixed point (see
    test_m34_s6_impact_2d3d.ref1d -- same methodology, nonlocal model)."""
    d1 = Device1D(X, DOP, T=300.0, models=_models_nl())
    d1_off = Device1D(X, DOP, T=300.0, models=_models_nl(False, False))
    bad = _ramp(d1, V_RED) + _ramp(d1_off, V_RED)
    bc = d1._contact_values([-V_RED, 0.0])
    psi, n, p = _undamped(d1, bc, 4)
    _, _, Jn, Jp = d1._residual_jacobian(psi, n, p, bc)
    bco = d1_off._contact_values([-V_RED, 0.0])
    _, _, Jno, Jpo = d1_off._residual_jacobian(d1_off.psi, d1_off.n,
                                               d1_off.p, bco)
    return dict(bad=bad, psi=psi, n=n, p=p, j=Jn[0] + Jp[0],
                g=d1._ii_gs_cache.copy(), M=(Jn[0] + Jp[0]) / (Jno[0] + Jpo[0]))


@pytest.mark.slow
def test_transverse_uniform_2d_reduces_to_1d_nonlocal(ref1d_nl):
    """A transversely uniform 2D nonlocal-II diode ramped to -30V equals
    Device1D's M34-S2 discrete solution, same tolerances as S6a's local
    reduction gate (test_m34_s6_impact_2d3d.py): the effective-field
    kernel's own reduction (round-off, see
    test_grid_kernel_reduces_to_1d_on_a_single_line) adds nothing
    measurable on top of S6a's.  Slow: every Newton iteration of every
    strength-ladder stage does a sparse LU solve for the exact nonlocal
    Jacobian (measured ~30s at this size, vs S6a's equivalent local-model
    gate finishing in a couple of seconds)."""
    d2 = _dev2_nl()
    _check_reduction(d2, _ramp(d2, V_RED), ref1d_nl, (1e-9, 1e-7, 1e-10, 1e-6))


@pytest.mark.slow
def test_transverse_uniform_3d_reduces_to_1d_nonlocal(ref1d_nl):
    """Measured ~65s (N=1017): coarsened from S6a's own X (h_min 2e-8 cm)
    to h_min 2e-7 cm, which cut a 237s run to 65s -- a fine edge gives
    a = exp(-h/lambda) close to 1, so the exact sparse Jacobian's chains
    decay slowly (rows averaging ~400 entries before the 1e-15 prune
    bites), and that dominates the per-Newton-iteration cost."""
    d3 = _dev3_nl()
    _check_reduction(d3, _ramp(d3, V_RED), ref1d_nl, (1e-9, 1e-7, 1e-10, 1e-6))


@pytest.mark.slow
def test_fd_jacobian_of_the_nonlocal_generation_2d():
    """dG/du, analytic vs central FD, with the nonlocal effective field
    live -- same methodology and tolerances as
    test_m34_s6_impact_2d3d.test_fd_jacobian_of_the_generation_genuinely_2d,
    via `_fd_gate_nl` (this file, not S6a's `_fd_gate`: see its docstring
    for the one check that does not transfer to this model). `off` and
    `on` must share the same mesh (the perturbed base state comes from
    `off`), so `off` is the SAME corner device with impact off, not
    S6a's own (larger) corner."""
    off = _corner_nl(False, False)
    assert not _ramp(off, 12.0)
    _fd_gate_nl(off, _corner_nl(True, True), 12.0)


@pytest.mark.slow
def test_fd_jacobian_of_the_nonlocal_generation_3d():
    off = _corner3_nl(False, False)
    assert not _ramp(off, 12.0)
    _fd_gate_nl(off, _corner3_nl(True, True), 12.0)


@pytest.mark.slow
def test_effective_field_lags_the_local_field_at_a_narrow_peak():
    """Slotboom's claim (M34-S2's docstring): at a NARROW field peak the
    effective field is colder than the local peak implies, because
    carriers do not gain energy instantly. A wide plateau gives the
    carriers time to relax, so there E_eff tracks the local field.  Gate
    on the 2D device (transversely uniform, so this is inherited directly
    from Device1D's own M34-S2 gate, exercised through the grid kernel)."""
    d_narrow = _dev2_nl(x=s6.graded_mesh(2.0e-4, [1.0e-4],
                                         h_min=1e-7, h_max=4e-6))
    assert not _ramp(d_narrow, 10.0, step=2.0)
    cv = {"left": -10.0, "right": 0.0}
    d_narrow._residual_jacobian(d_narrow.psi, d_narrow.n, d_narrow.p, cv)
    En, Ep = d_narrow._ii_fields
    Nx = d_narrow.Nx
    local = np.abs(np.diff(d_narrow.psi[1, :])) * d_narrow.VT \
        / (d_narrow.LD * d_narrow.hx)
    local_node = np.zeros(Nx)
    local_node[1:-1] = 0.5 * (local[:-1] + local[1:])
    peak = int(np.argmax(local_node))
    assert 0 < peak < Nx - 1
    En2 = En.reshape(d_narrow.Ny, Nx)[1, :]
    assert En2[peak] < local_node[peak]


@pytest.mark.slow
def test_reverse_ramp_converges_with_nonlocal_ii_2d3d():
    """Convergence gate: a reverse ramp with impact_nonlocal on converges
    at every step, in both 2D and 3D."""
    assert not _ramp(_dev2_nl(), V_RED)
    assert not _ramp(_dev3_nl(), V_RED)
