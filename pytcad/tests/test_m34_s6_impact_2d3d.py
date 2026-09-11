"""M34-S6 gates: M15's coupled impact ionization in Device2D/Device3D.

See pytcad/M34-S6-PLAN.md.  The kernel is pytcad/ii_grid.py (node
generation from M15's smoothed edge currents and fields, the ionization
coefficients evaluated at the field component ALONG each carrier's
current -- the user's choice), stamped into the 2D/3D residuals with
M15's strength ladder and backtracking.

The central gate is dimensional reduction: a transversely uniform 2D
diode must reproduce Device1D's M15 solution.  Tolerances are set from
measured values, quoted in each docstring.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.ii_grid import grid_impact
from pytcad.ionization import E_SWITCH_N, E_SWITCH_P
from pytcad.mesh import graded_mesh, uniform_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D

X = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=4e-6)
DOP = np.where(X < 3.0e-4, -1e16, 1e19)          # M15's one-sided junction


def _models(impact=True):
    return Models(bgn=False, srh=True, impact=impact)


def _dev2(impact=True, ny=3, dop2=None, right_rows=None, y=None):
    y = np.linspace(0.0, 1e-5, ny) if y is None else y
    d = Device2D(Mesh2D(X, y), np.tile(DOP, (y.size, 1)) if dop2 is None
                 else dop2, T=300.0, models=_models(impact))
    d.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    d.add_contact("right", i=[X.size - 1],
                  j=list(range(y.size)) if right_rows is None else right_rows,
                  V=0.0)
    return d


def _ramp(dev, vmax, step=2.0):
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
    return bad


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
def reduced():
    d1 = Device1D(X, DOP, T=300.0, models=_models())
    d2 = _dev2()
    return (d1, _ramp(d1, 30.0)), (d2, _ramp(d2, 30.0))


def test_transverse_uniform_2d_reduces_to_1d_m15(reduced):
    """A transversely uniform 2D M15 diode, ramped to -30V, equals
    Device1D's M15 solution row by row."""
    (d1, bad1), (d2, bad2) = reduced
    assert not bad1 and not bad2
    tot = d1.n + d1.p
    assert np.abs(d2.psi - d1.psi[None, :]).max() < 1e-9
    assert (np.abs(d2.n - d1.n[None, :]) / tot).max() < 1e-9
    assert (np.abs(d2.p - d1.p[None, :]) / tot).max() < 1e-9
    j2 = (d2.Jn_x + d2.Jp_x).mean()
    assert j2 == pytest.approx(d1.current_density()[0], rel=1e-9)
    g2 = d2._ii_gs_cache.reshape(d2.psi.shape)
    assert g2.max() > 0.0


def _corner(impact=True):
    """An L-shaped junction: n+ only in x > 3 um, y < 2 um."""
    y = graded_mesh(6.0e-4, [2.0e-4], h_min=2e-7, h_max=4e-5)
    Y2, X2 = np.meshgrid(y, X, indexing="ij")
    dop = np.where((X2 > 3.0e-4) & (Y2 < 2.0e-4), 1e19, -1e16)
    return _dev2(impact, dop2=dop, y=y,
                 right_rows=[j for j in range(y.size) if y[j] < 2.0e-4])


def test_fd_jacobian_genuinely_2d():
    """Analytic vs central FD (M15 G-B methodology: randomly perturbed
    state, column-max normalization, 5e-5) on 300 random columns of a
    genuinely 2D junction at -20V, where the transverse terms of the
    kernel are exercised.  Density columns step by 1e-7*max(|u|, 1e-4)
    (M34-S2's floor; M15's absolute 1e-7 is truncation-limited near a
    zero-crossing |J|)."""
    dev = _corner()
    assert not _ramp(dev, 20.0)
    rng = np.random.default_rng(17)
    cv = {"left": -20.0, "right": 0.0}
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1 + 1e-3 * rng.standard_normal(dev.p.shape))
    F0, J, *_ = dev._residual_jacobian(psi, n, p, cv)
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    Jc = J.tocsc()
    worst = 0.0
    for c in rng.choice(u.size, size=300, replace=False):
        step = (1e-7 * max(abs(u[c]), 1.0) if c % 3 == 0
                else 1e-7 * max(abs(u[c]), 1e-4))
        up = u.copy()
        up[c] += step
        um = u.copy()
        um[c] -= step
        sh = dev.psi.shape
        Fp_, *_ = dev._residual_jacobian(up[0::3].reshape(sh), up[1::3].reshape(sh),
                                         up[2::3].reshape(sh), cv)
        Fm_, *_ = dev._residual_jacobian(um[0::3].reshape(sh), um[1::3].reshape(sh),
                                         um[2::3].reshape(sh), cv)
        fd = (Fp_ - Fm_) / (2.0 * step)
        an = Jc[:, c].toarray().ravel()
        worst = max(worst, float(np.abs(fd - an).max() / (np.abs(an).max() + 1e-30)))
    assert worst <= 5e-5, f"FD-Jacobian gate: {worst:.3e}"


def test_curved_junction_multiplies_more_than_planar():
    """Junction curvature concentrates the field, so at the same reverse
    bias an L-shaped junction multiplies more than a planar one -- the
    effect behind curvature-limited breakdown.  Multiplication measured
    as the impact-on / impact-off contact-current ratio."""
    def mult(make):
        on, off = make(True), make(False)
        assert not _ramp(on, 20.0) and not _ramp(off, 20.0)
        return on.terminal_current("left") / off.terminal_current("left")
    m_planar = mult(lambda imp: _dev2(imp))
    m_curved = mult(_corner)
    assert m_planar > 1.0
    assert m_curved > m_planar


def test_device3d_still_refuses_impact_until_s6b():
    mesh3d = Mesh3D(x=uniform_mesh(1e-4, 2), y=uniform_mesh(1e-4, 2),
                    z=uniform_mesh(1e-4, 2))
    with pytest.raises(NotImplementedError, match="impact"):
        Device3D(mesh3d, np.full((3, 3, 3), 1e15), models=_models())
