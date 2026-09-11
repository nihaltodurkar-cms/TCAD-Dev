"""M34-S3 gates: nonlocal path Kane BTBT in structured Device2D/Device3D.

See pytcad/M34-PLAN.md section 4 and pytcad/nonlocal_path.py
(build_structured traces field-line paths; `evaluate` is the same engine
Device1D uses).  The central gate is DIMENSIONAL REDUCTION: a 2D or 3D
device uniform across its transverse axes must reproduce Device1D's
solution, which holds only if every piece -- start screen, stepping,
stencils, boundary handling, deposits, refresh -- matches 1D exactly.
Measured 2026-09-11: psi to 1.4e-13, densities to 4e-14 of n+p,
current to 1.3e-14 (2D and 3D).  Thresholds are set well above those
round-off values but far below any physical difference.
"""
import copy
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
from pytcad.materials import SILICON
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.nonlocal_path import build_structured, evaluate
from pytcad.btbt import M0_SI, Q_SI

X = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
DOP = np.where(X < 5.0e-6, -5e19, 5e19)
YZ3 = np.linspace(0.0, 1e-6, 2)


def _models(nl=True):
    return Models(bgn=False, srh=True, btbt_nonlocal=nl)


def _dev2(nl=True, ny=3):
    y = np.linspace(0.0, 2e-6, ny)
    d = Device2D(Mesh2D(X, y), np.tile(DOP, (ny, 1)), T=300.0,
                 models=_models(nl))
    d.add_contact("left", i=[0], j=list(range(ny)), V=0.0)
    d.add_contact("right", i=[X.size - 1], j=list(range(ny)), V=0.0)
    return d


def _dev3(nl=True):
    d = Device3D(Mesh3D(x=X, y=YZ3, z=YZ3), np.tile(DOP, (2, 2, 1)), T=300.0,
                 models=_models(nl))
    jj, kk = np.meshgrid(range(2), range(2), indexing="ij")
    j, k = jj.ravel().tolist(), kk.ravel().tolist()
    d.add_contact("left", i=[0] * 4, j=j, k=k, V=0.0)
    d.add_contact("right", i=[X.size - 1] * 4, j=j, k=k, V=0.0)
    return d


def _ramp(dev, stop=-6.0, step=0.5):
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for V in np.arange(-step, stop - 1e-9, -step):
            if isinstance(dev, Device1D):
                dev.solve_bias([float(V), 0.0], NewtonOptions())
            else:
                dev.solve_bias({"left": float(V), "right": 0.0})
            if not dev.last_converged:
                bad.append(round(float(V), 3))
    return bad


@pytest.fixture(scope="module")
def solved():
    out = {}
    for name, dev in (("1d", Device1D(X, DOP, T=300.0, models=_models())),
                      ("2d", _dev2()), ("3d", _dev3())):
        out[name] = (dev, _ramp(dev))
    return out


def _off_twin(dev):
    """A btbt_nonlocal=False device on the same mesh/doping and contacts."""
    twin = _dev2(False) if isinstance(dev, Device2D) else _dev3(False)
    for name, bc in dev.bcs.items():
        twin.bcs[name].V = bc.V
    return twin


def test_default_off_is_bit_identical_2d_3d():
    """btbt_nonlocal=False is the plain solver, bit for bit, in 2D and
    3D -- the refresh wrapper around the Newton loop runs it once."""
    for make in (_dev2, _dev3):
        a, b = make(False), make(False)
        b.models = Models(bgn=False, srh=True)
        assert not _ramp(a, -1.0) and not _ramp(b, -1.0)
        assert np.array_equal(a.psi, b.psi)
        assert np.array_equal(a.n, b.n) and np.array_equal(a.p, b.p)


def test_heterostructure_refused_2d_3d():
    """Homojunction only, as in Device1D: a second material refuses."""
    other = copy.copy(SILICON)
    y = np.linspace(0.0, 2e-6, 3)
    mats = [SILICON] * X.size * 2 + [other] * X.size
    with pytest.raises(NotImplementedError, match="homojunction"):
        Device2D(Mesh2D(X, y), np.tile(DOP, (3, 1)), material=mats,
                 models=_models())
    mats3 = [SILICON] * X.size * 3 + [other] * X.size
    with pytest.raises(NotImplementedError, match="homojunction"):
        Device3D(Mesh3D(x=X, y=YZ3, z=YZ3), np.tile(DOP, (2, 2, 1)),
                 material=mats3, models=_models())


@pytest.mark.parametrize("dim", [2, 3])
def test_paths_follow_a_uniform_field_exactly(dim):
    """In a uniform field along a diagonal the field lines are straight
    and eq (8)'s tunnel length is Eg/(qF) (Esseni 2017 sec 2.1).  Paths
    whose straight extension stays inside the box must reproduce it to
    rounding (the multilinear stencil is exact for a linear psi).  Paths
    that meet a face are excluded: a uniform diagonal field is not a
    device solution (it has a normal component at the faces), and the
    tracer deliberately keeps paths inside at an insulating boundary.
    Measured worst relative length error: 4.2e-12 (2D), 1.1e-10 (3D --
    a 3D path is split at x, y AND z faces, ~3x the segments)."""
    VT, Eg_eV = 0.025852, SILICON.Eg(300.0)
    mc, mv = SILICON.m_n_star * M0_SI, SILICON.m_p_star * M0_SI
    mr = 1.0 / (1.0 / mc + 1.0 / mv)
    F = 3e5                                              # V/cm
    L = Eg_eV / F                                        # cm
    g = np.linspace(0.0, 1e-5, 41)
    u = np.array([0.3, 0.5, 0.81][:dim])
    u = u / np.linalg.norm(u)
    grids = np.meshgrid(*[g] * dim, indexing="ij")
    psi = F * sum(ui * G for ui, G in zip(u, grids)) / VT
    P = build_structured([g] * dim, psi, VT, Eg_eV,
                         np.zeros(psi.shape, dtype=bool))
    ev = evaluate(P, psi.ravel(), VT, Eg_eV * Q_SI, mr, mc, mv)
    start_pos = np.stack([G.ravel()[P.start] for G in grids], axis=1)
    end_pos = start_pos + 1.6 * L * u
    inside = np.all((end_pos >= 0.0) & (end_pos <= g[-1]), axis=1)
    assert inside.sum() > 50
    assert ev.reached[inside].all()
    assert np.allclose(ev.length[inside], L * 1e-2, rtol=1e-9, atol=0.0)


@pytest.mark.parametrize("name", ["2d", "3d"])
def test_transverse_uniform_device_reduces_to_1d(solved, name):
    """The dimensional-reduction gate: at -6V (0.5V ramp) every row of
    a transversely uniform 2D/3D tunnel diode equals the 1D solution,
    with the same path set per row and a self-consistent refresh."""
    (d1, bad1), (dn, badn) = solved["1d"], solved[name]
    assert not bad1 and not badn
    assert dn.last_btbt_nl_stable
    rows = dn.psi.size // X.size
    assert dn._btbt_nl_paths.n_paths == rows * d1._btbt_nl_paths.n_paths
    psi = dn.psi.reshape(rows, X.size)
    nn = dn.n.reshape(rows, X.size)
    pp = dn.p.reshape(rows, X.size)
    tot = d1.n + d1.p
    assert np.abs(psi - d1.psi).max() < 1e-9
    assert (np.abs(nn - d1.n) / tot).max() < 1e-9
    assert (np.abs(pp - d1.p) / tot).max() < 1e-9
    if name == "2d":
        j2 = (dn.Jn_x + dn.Jp_x).mean()
        assert j2 == pytest.approx(d1.current_density()[0], rel=1e-9)


@pytest.mark.parametrize("name", ["2d", "3d"])
def test_pair_conservation(solved, name):
    """One electron per hole: the box-integrated electron and hole
    injections of the nonlocal block are equal, and Poisson rows are
    untouched."""
    dev, bad = solved[name]
    assert not bad
    cv = {n: bc.V for n, bc in dev.bcs.items()}
    dev._btbt_nl_paths = None
    F_on, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, cv)
    F_off, *_ = _off_twin(dev)._residual_jacobian(dev.psi, dev.n, dev.p, cv)
    d = F_on - F_off
    assert np.all(d[0::3] == 0.0)
    assert d[1::3].sum() > 0.0
    assert d[1::3].sum() == pytest.approx(-d[2::3].sum(), rel=1e-12)


@pytest.mark.parametrize("name,ncols", [("2d", None), ("3d", 80)])
def test_fd_jacobian(solved, name, ncols):
    """Analytic vs FD Jacobian, psi columns, paths frozen as within one
    Newton solve, house tolerance 5e-5 (every column in 2D, 80 random
    in 3D).  Measured: 6e-8 (2D), 1.6e-8 (3D)."""
    dev, bad = solved[name]
    assert not bad
    cv = {n: bc.V for n, bc in dev.bcs.items()}
    dev._btbt_nl_paths = None
    F0, J0, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, cv)
    paths = dev._btbt_nl_paths
    assert paths.n_paths > 0
    Jc = J0.tocsc()
    ps0 = dev.psi.ravel()
    cols = (range(dev.N) if ncols is None
            else np.random.default_rng(0).choice(dev.N, ncols, replace=False))
    worst = 0.0
    for k in cols:
        ps = ps0.copy()
        ps[k] += 1e-6
        dev._btbt_nl_paths = paths
        F1, *_ = dev._residual_jacobian(ps.reshape(dev.psi.shape),
                                        dev.n, dev.p, cv)
        fd = (F1 - F0) / 1e-6
        an = Jc[:, 3 * k].toarray().ravel()
        worst = max(worst, np.abs(fd - an).max()
                    / max(np.abs(fd).max(), np.abs(an).max(), 1e-300))
    assert worst < 5e-5, f"{name}: {worst:.3e}"


def test_genuinely_two_dimensional_corner_junction():
    """An L-shaped p+/n+ junction (n+ only in the x > 5 um, y < 1 um
    quadrant) has a two-dimensional field: paths near the corner leave
    their start row.  The solve must converge through a reverse ramp
    with a self-consistent refresh, conserve pairs, and pass the FD
    gate on a column sample."""
    y = graded_mesh(2.0e-6, [1.0e-6], h_min=2e-8, h_max=2e-7)
    Y2, X2 = np.meshgrid(y, X, indexing="ij")
    dop = np.where((X2 > 5.0e-6) & (Y2 < 1.0e-6), 5e19, -5e19)
    dev = Device2D(Mesh2D(X, y), dop, T=300.0, models=_models())
    dev.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    ntop = [j for j in range(y.size) if y[j] < 1.0e-6]
    dev.add_contact("right", i=[X.size - 1], j=ntop, V=0.0)
    assert not _ramp(dev, -3.0)
    assert dev.last_btbt_nl_stable
    P = dev._btbt_nl_paths
    rows_touched = [np.unique(P.sidx[P.offset[q]:P.offset[q + 1]]
                              [P.swts[P.offset[q]:P.offset[q + 1]] > 0]
                              // X.size).size for q in range(P.n_paths)]
    assert max(rows_touched) >= 3, "no path leaves its start row"
    cv = {n: bc.V for n, bc in dev.bcs.items()}
    dev._btbt_nl_paths = None
    F0, J0, *_ = dev._residual_jacobian(dev.psi, dev.n, dev.p, cv)
    off = Device2D(Mesh2D(X, y), dop, T=300.0, models=_models(False))
    off.add_contact("left", i=[0], j=list(range(y.size)), V=cv["left"])
    off.add_contact("right", i=[X.size - 1], j=ntop, V=cv["right"])
    F_off, *_ = off._residual_jacobian(dev.psi, dev.n, dev.p, cv)
    d = F0 - F_off
    assert d[1::3].sum() == pytest.approx(-d[2::3].sum(), rel=1e-12)
    paths = dev._btbt_nl_paths
    Jc = J0.tocsc()
    ps0 = dev.psi.ravel()
    worst = 0.0
    for k in np.random.default_rng(1).choice(dev.N, 60, replace=False):
        ps = ps0.copy()
        ps[k] += 1e-6
        dev._btbt_nl_paths = paths
        F1, *_ = dev._residual_jacobian(ps.reshape(dev.psi.shape),
                                        dev.n, dev.p, cv)
        fd = (F1 - F0) / 1e-6
        an = Jc[:, 3 * k].toarray().ravel()
        worst = max(worst, np.abs(fd - an).max()
                    / max(np.abs(fd).max(), np.abs(an).max(), 1e-300))
    assert worst < 5e-5, f"corner junction FD: {worst:.3e}"
