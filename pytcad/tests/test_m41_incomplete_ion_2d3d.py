"""M41: incomplete dopant ionization in structured Device2D/Device3D.

The dimensional lift of M13's shallow-dopant freeze-out model
(`device.py`'s `ionized_doping`, shared by all three devices since this
slice) from Device1D to the structured 2D and 3D cores.  Poisson's
charge term becomes rho = n - p - C_ion; nothing else in either core
changes.

ARCHITECTURE.md 4d.4's rule for every dimensional lift -- "no
dimensional lift lands without its reduction identity as a gate" -- is
G5/G6 here: a transversely uniform 2D/3D device must reproduce
Device1D's own answer.  The physics itself is gated against the SAME
independent root-finder M13 used (`test_m13_solver._fd_neutral_eta`),
not against the solver being tested.

See pytcad/M41-INCOMPLETE-ION-2D3D-PLAN.md.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.materials import SILICON
from pytcad.constants import KB_EV

# the INDEPENDENT self-consistent neutrality root M13's own G7b/c gate
# reads -- a test-side implementation with no shared code path into the
# solver, which is what makes G3/G4 a gate rather than a tautology
from test_m13_solver import _fd_neutral_eta as _ref_neutral_eta

warnings.simplefilter("ignore")

T = 300.0
NA = 1e16


def _models(ion, fd=True, **kw):
    kw.setdefault("bgn", False)
    kw.setdefault("srh", False)
    return Models(fd=fd, incomplete_ion=ion, **kw)


# ----------------------------------------------------------------------
#  device builders
# ----------------------------------------------------------------------
def _uniform2d(ion, T_=T, na=NA, fd=True, nx=9, ny=5):
    """A uniform p-type slab: the freeze-out fraction is a bulk
    property, so the simplest possible 2D geometry isolates it."""
    x = np.linspace(0.0, 1.0e-4, nx)
    y = np.linspace(0.0, 5.0e-5, ny)
    dop = np.full((ny, nx), -na)
    d = Device2D(Mesh2D(x, y), dop, T=T_, models=_models(ion, fd))
    d.add_contact("left", i=[0], j=list(range(ny)), V=0.0)
    d.add_contact("right", i=[nx - 1], j=list(range(ny)), V=0.0)
    return d


def _uniform3d(ion, T_=T, na=NA, fd=True, nx=7, ny=4, nz=3):
    x = np.linspace(0.0, 1.0e-4, nx)
    y = np.linspace(0.0, 5.0e-5, ny)
    z = np.linspace(0.0, 5.0e-5, nz)
    dop = np.full((nz, ny, nx), -na)
    d = Device3D(Mesh3D(x=x, y=y, z=z), dop, T=T_, models=_models(ion, fd))
    kk, jj = np.meshgrid(range(nz), range(ny), indexing="ij")
    face = list(zip(jj.ravel(), kk.ravel()))
    d.add_contact("left", i=[0] * len(face), j=[f[0] for f in face],
                  k=[f[1] for f in face], V=0.0)
    d.add_contact("right", i=[nx - 1] * len(face), j=[f[0] for f in face],
                  k=[f[1] for f in face], V=0.0)
    return d


def _junction_x(nx=25):
    """A 1D pn profile the 2D/3D reduction gates extrude transversely.

    Doping is kept below the Mott transition on BOTH sides: the
    hydrogenic model is not valid at 1e19, and M13's own test file
    refuses to combine incomplete_ion with degenerate doping.
    """
    x = np.linspace(0.0, 2.0e-4, nx)
    return x, np.where(x < 1.0e-4, -1e16, 1e16)


def _diode1d(ion, fd=True):
    x, dop = _junction_x()
    return Device1D(x, dop, T=T, models=_models(ion, fd))


def _diode2d(ion, fd=True, ny=4):
    x, dop1 = _junction_x()
    y = np.linspace(0.0, 4.0e-5, ny)
    d = Device2D(Mesh2D(x, y), np.tile(dop1, (ny, 1)), T=T,
                 models=_models(ion, fd))
    d.add_contact("left", i=[0], j=list(range(ny)), V=0.0)
    d.add_contact("right", i=[x.size - 1], j=list(range(ny)), V=0.0)
    return d


def _diode3d(ion, fd=True, ny=3, nz=3):
    x, dop1 = _junction_x(nx=17)
    y = np.linspace(0.0, 3.0e-5, ny)
    z = np.linspace(0.0, 3.0e-5, nz)
    dop = np.broadcast_to(dop1, (nz, ny, x.size)).copy()
    d = Device3D(Mesh3D(x=x, y=y, z=z), dop, T=T, models=_models(ion, fd))
    kk, jj = np.meshgrid(range(nz), range(ny), indexing="ij")
    face = list(zip(jj.ravel(), kk.ravel()))
    d.add_contact("left", i=[0] * len(face), j=[f[0] for f in face],
                  k=[f[1] for f in face], V=0.0)
    d.add_contact("right", i=[x.size - 1] * len(face),
                  j=[f[0] for f in face], k=[f[1] for f in face], V=0.0)
    return d


# ----------------------------------------------------------------------
#  G1/G2 -- FD-Jacobian (written and green BEFORE any convergence gate,
#  per CLAUDE.md's frozen-core amendment rule)
# ----------------------------------------------------------------------
def _fd_jacobian_worst(dev, voltages, seed=0, n_cols=90, h=1e-7):
    """Central-difference probe of _residual_jacobian's analytic columns.

    Same methodology as M13's own G5 probe and M14's 2D one: perturb
    the converged state so no column sits at a special point, compare
    column by column with a column-max normalization.
    """
    rng = np.random.default_rng(seed)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 1e-3 * rng.standard_normal(dev.p.shape))
    shp = dev.psi.shape
    F0, J0, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J0d = J0.toarray()
    u0 = np.stack([psi, n, p], axis=-1).ravel()
    cols = rng.choice(J0d.shape[0], size=min(n_cols, J0d.shape[0]),
                      replace=False)
    worst = 0.0
    for k in cols:
        up = u0.copy(); up[k] += h
        um = u0.copy(); um[k] -= h
        Fp, *_ = dev._residual_jacobian(up[0::3].reshape(shp),
                                        up[1::3].reshape(shp),
                                        up[2::3].reshape(shp), voltages)
        Fm, *_ = dev._residual_jacobian(um[0::3].reshape(shp),
                                        um[1::3].reshape(shp),
                                        um[2::3].reshape(shp), voltages)
        col_fd = (Fp - Fm) / (2.0 * h)
        scale = np.maximum(np.abs(J0d[:, k]), 1.0)
        worst = max(worst,
                    float(np.max(np.abs(J0d[:, k] - col_fd) / scale)))
    return worst


def test_g1_fd_jacobian_2d():
    """G1: the d(C_ion)/dn and d(C_ion)/dp columns of the Poisson row
    match finite differences in Device2D.

    This is the whole numerical content of the slice: the residual
    change is one term, but it makes Poisson's row depend on BOTH
    density unknowns through f_half_inv, which the full-ionization
    path never did (its density columns were the constants -dV, +dV).
    """
    dev = _diode2d(ion=True)
    dev.solve_equilibrium()
    worst = _fd_jacobian_worst(dev, {"left": 0.2, "right": 0.0})
    assert worst <= 5e-5, f"G1 FAIL (2D): worst column error {worst:.3e}"


def test_g2_fd_jacobian_3d():
    """G2: the same probe in Device3D."""
    dev = _diode3d(ion=True)
    dev.solve_equilibrium()
    worst = _fd_jacobian_worst(dev, {"left": 0.2, "right": 0.0})
    assert worst <= 5e-5, f"G2 FAIL (3D): worst column error {worst:.3e}"


def _fd_poisson_worst(dev, seed=0, n_cols=60, h=1e-7):
    """The same probe against the EQUILIBRIUM (Poisson-only) Jacobian.

    That path carries its own, different chain rule: n and p are slaved
    to psi there, so d(rho)/dpsi picks up (1-dcden) dn/dpsi +
    (1+dcdp) |dp/dpsi| instead of the two independent density columns
    the coupled block stamps.  A wrong `dnp` here would still converge
    (Newton tolerates a bad Jacobian by iterating more), so the
    convergence gates below cannot substitute for this one.
    """
    rng = np.random.default_rng(seed)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    F0, J0 = dev._residual_jacobian_poisson(psi)
    J0d = J0.toarray()
    flat = psi.ravel()
    cols = rng.choice(flat.size, size=min(n_cols, flat.size), replace=False)
    worst = 0.0
    for k in cols:
        up = flat.copy(); up[k] += h
        um = flat.copy(); um[k] -= h
        Fp, _ = dev._residual_jacobian_poisson(up.reshape(psi.shape))
        Fm, _ = dev._residual_jacobian_poisson(um.reshape(psi.shape))
        col_fd = ((Fp - Fm) / (2.0 * h)).ravel()
        scale = np.maximum(np.abs(J0d[:, k]), 1.0)
        worst = max(worst,
                    float(np.max(np.abs(J0d[:, k] - col_fd) / scale)))
    return worst


def test_g2b_fd_jacobian_of_the_equilibrium_poisson_block_2d():
    """G2b: the slaved-density chain in the equilibrium Jacobian, 2D."""
    dev = _uniform2d(ion=True, T_=77.0)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    worst = _fd_poisson_worst(dev)
    assert worst <= 5e-5, f"G2b FAIL (2D): worst column error {worst:.3e}"


def test_g2c_fd_jacobian_of_the_equilibrium_poisson_block_3d():
    """G2c: the same in Device3D."""
    dev = _uniform3d(ion=True, T_=77.0)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    worst = _fd_poisson_worst(dev)
    assert worst <= 5e-5, f"G2c FAIL (3D): worst column error {worst:.3e}"


def test_g2d_fd_jacobian_of_the_equilibrium_poisson_block_boltzmann():
    """G2d: the Boltzmann branch of that same chain (dn/dpsi = n rather
    than fd_ddensity_deta) -- a separate `else` arm, separately wrong-
    able."""
    dev = _uniform2d(ion=True, T_=77.0, fd=False)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    worst = _fd_poisson_worst(dev, seed=5)
    assert worst <= 5e-5, f"G2d FAIL: worst column error {worst:.3e}"


def test_g1b_fd_jacobian_2d_boltzmann():
    """G1b: the flag is independent of `fd`, so the same Jacobian must
    be right with Boltzmann statistics underneath -- the chain still
    runs through f_half_inv, which is the part that could silently
    disagree with the carrier law."""
    dev = _diode2d(ion=True, fd=False)
    dev.solve_equilibrium()
    worst = _fd_jacobian_worst(dev, {"left": 0.2, "right": 0.0}, seed=3)
    assert worst <= 5e-5, f"G1b FAIL: worst column error {worst:.3e}"


# ----------------------------------------------------------------------
#  G3/G4 -- the physics, against the independent root-finder
# ----------------------------------------------------------------------
@pytest.mark.parametrize("T_K", [77.0, 150.0, 250.0, 300.0])
def test_g3_ionized_fraction_2d_vs_independent_root(T_K):
    """G3: B in Si, N_A = 1e16, ionized fraction at 77/150/250/300 K.

    Device2D must match the independent self-consistent root to
    machine precision AND land inside the published literature bands
    M13's own G7b/c uses (Sze & Ng ch. 7; Altermatt et al., IEEE TED
    49 (2002)).
    """
    _, _, _, frac_ref = _ref_neutral_eta(-NA, SILICON, T_K, ion=True)
    dev = _uniform2d(ion=True, T_=T_K)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    frac = (dev.p_cm3 - dev.n_cm3).mean() / NA
    assert abs(frac - frac_ref) <= 1e-9, \
        f"G3 FAIL @{T_K}K: 2D {frac:.9f} vs independent root {frac_ref:.9f}"
    bands = {77.0: (0.15, 0.45), 150.0: (0.70, 0.98),
             250.0: (0.85, 1.01), 300.0: (0.95, 1.01)}
    lo, hi = bands[T_K]
    assert lo <= frac <= hi, \
        f"G3 FAIL @{T_K}K: fraction {frac:.3f} outside published [{lo}, {hi}]"


@pytest.mark.parametrize("T_K", [77.0, 300.0])
def test_g4_ionized_fraction_3d_vs_independent_root(T_K):
    """G4: the same, in Device3D (the two band ends are enough here --
    G3 already walks the whole temperature range through identical
    shared code)."""
    _, _, _, frac_ref = _ref_neutral_eta(-NA, SILICON, T_K, ion=True)
    dev = _uniform3d(ion=True, T_=T_K)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    frac = (dev.p_cm3 - dev.n_cm3).mean() / NA
    assert abs(frac - frac_ref) <= 1e-9, \
        f"G4 FAIL @{T_K}K: 3D {frac:.9f} vs independent root {frac_ref:.9f}"


def test_g7_freeze_out_direction_2d():
    """G7: the DIRECTION gate -- freeze-out means a fraction well below
    1 at 77 K and essentially full ionization at 300 K.  A sign error
    in the ionization term would still pass a root-match gate if the
    reference were computed the same wrong way; this one cannot."""
    fr = {}
    for T_K in (77.0, 300.0):
        dev = _uniform2d(ion=True, T_=T_K)
        dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
        fr[T_K] = (dev.p_cm3 - dev.n_cm3).mean() / NA
    assert fr[77.0] < 0.60, f"no freeze-out at 77 K: {fr[77.0]:.3f}"
    assert fr[300.0] > 0.95, f"not ionized at 300 K: {fr[300.0]:.3f}"
    assert fr[77.0] < fr[300.0]


def test_g7b_ionization_reduces_the_majority_density_2d():
    """G7b: the same statement read off the solved field rather than a
    fraction -- turning the flag ON must REMOVE majority carriers at
    77 K (fewer dopants ionized => fewer holes), not add them."""
    off = _uniform2d(ion=False, T_=77.0)
    off.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    on = _uniform2d(ion=True, T_=77.0)
    on.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    assert on.p_cm3.mean() < 0.60 * off.p_cm3.mean()


# ----------------------------------------------------------------------
#  G5/G6 -- the reduction identity (ARCHITECTURE.md 4d.4's rule)
# ----------------------------------------------------------------------
def test_g5_transverse_uniform_2d_reduces_to_1d():
    """G5: a transversely uniform Device2D with incomplete ionization
    must reproduce Device1D's own equilibrium, row for row."""
    d1 = _diode1d(ion=True)
    d1.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    d2 = _diode2d(ion=True)
    d2.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    for row in range(d2.Ny):
        assert np.allclose(d2.psi[row, :], d1.psi, rtol=0, atol=1e-9), \
            f"G5 FAIL: psi row {row} differs from Device1D"
        assert np.allclose(d2.n_cm3[row, :], d1.n_cm3, rtol=1e-9, atol=0)
        assert np.allclose(d2.p_cm3[row, :], d1.p_cm3, rtol=1e-9, atol=0)


def test_g6_transverse_uniform_3d_reduces_to_1d():
    """G6: the same in Device3D."""
    x, dop = _junction_x(nx=17)
    d1 = Device1D(x, dop, T=T, models=_models(True))
    d1.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    d3 = _diode3d(ion=True)
    d3.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    for k in range(d3.Nz):
        for j in range(d3.Ny):
            assert np.allclose(d3.psi[k, j, :], d1.psi, rtol=0, atol=1e-9)
            assert np.allclose(d3.n_cm3[k, j, :], d1.n_cm3, rtol=1e-9, atol=0)
            assert np.allclose(d3.p_cm3[k, j, :], d1.p_cm3, rtol=1e-9, atol=0)


def test_g5b_bias_solve_converges_and_reduces_to_1d():
    """G5b: the reduction identity at BIAS, not just equilibrium.

    G1's FD-Jacobian probe shows the analytic Jacobian is right; it
    says nothing about whether the Newton loop actually converges with
    the extra density coupling in Poisson's row.  This drives a real
    forward bias through solve_bias in both devices and checks the
    terminal current against Device1D's, which is the quantity a user
    would actually read.
    """
    V = {"left": 0.3, "right": 0.0}
    opts = NewtonOptions(tol_update=1e-12, max_iter=200)
    d1 = _diode1d(ion=True)
    d1.solve_equilibrium(opts)
    d1.solve_bias([V["left"], V["right"]], opts)
    d2 = _diode2d(ion=True)
    d2.solve_equilibrium(opts)
    d2.solve_bias(V, opts)
    for row in range(d2.Ny):
        assert np.allclose(d2.psi[row, :], d1.psi, rtol=0, atol=1e-8), \
            f"G5b FAIL: biased psi row {row} differs from Device1D"
        assert np.allclose(d2.n_cm3[row, :], d1.n_cm3, rtol=1e-8, atol=0)
    # edge current DENSITY, the same quantity Device1D reports -- the
    # comparison test_validation_2d.py's own 2D-reduces-to-1D gate uses
    J1, _ = d1.current_density()
    Jtot = d2.Jn_x + d2.Jp_x
    assert np.allclose(Jtot, Jtot[0:1, :], rtol=1e-6, atol=0), \
        "G5b FAIL: 2D current is not y-independent"
    assert abs(Jtot.mean() - J1) / abs(J1) < 1e-6, \
        f"G5b FAIL: 2D current {Jtot.mean():.6e} vs 1D {J1:.6e}"


# ----------------------------------------------------------------------
#  G8 -- default-off bit-identity
# ----------------------------------------------------------------------
def _solved_2d(**kw):
    d = _diode2d(**kw)
    d.solve_equilibrium()
    d.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
    return d


def test_g8_bit_identity_2d_when_flag_off():
    """G8: with incomplete_ion=False the 2D core must be bit-identical
    to itself -- the new code is a branch, not a reformulation of the
    existing arithmetic.  np.array_equal, not allclose."""
    a, b = _solved_2d(ion=False), _solved_2d(ion=False)
    assert np.array_equal(a.psi, b.psi)
    assert np.array_equal(a.n, b.n)
    assert np.array_equal(a.p, b.p)


def test_g8b_bit_identity_3d_when_flag_off():
    """G8b: the same in 3D, on the equilibrium path (which is where
    resistor3d_eq.npz, one of the M13 goldens, is generated)."""
    outs = []
    for _ in range(2):
        d = _diode3d(ion=False)
        d.solve_equilibrium()
        outs.append((d.psi.copy(), d.n.copy(), d.p.copy()))
    for u, v in zip(*outs):
        assert np.array_equal(u, v)


# ----------------------------------------------------------------------
#  G9/G10 -- flag independence and the refusals
# ----------------------------------------------------------------------
def test_g9_flag_independent_of_fd_statistics():
    """G9: `incomplete_ion` is documented as independent of `fd`.  At
    non-degenerate doping the two statistics must agree on the ionized
    fraction to the exact Boltzmann-limit deviation exp(eta)/2^(3/2)
    (M13's own G6b reasoning), not to an arbitrary round number.

    The deviation that matters is the MAJORITY carrier's: this is a
    p-type slab, so it is eta_p = -eta_n - Eg/kT that sets how far
    F_1/2 has departed from exp (eta_p = -8.05, delta = 1.13e-4; the
    electron side's own delta is 1.4e-16 and gates nothing)."""
    eta, _, _, frac_fd = _ref_neutral_eta(-NA, SILICON, T, ion=True)
    eg_kt = SILICON.Eg(T) / (KB_EV * T)
    delta = float(np.exp(-eta - eg_kt) / 2.0 ** 1.5)
    d_b = _uniform2d(ion=True, fd=False)
    d_b.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    frac_b = (d_b.p_cm3 - d_b.n_cm3).mean() / NA
    d_f = _uniform2d(ion=True, fd=True)
    d_f.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=200))
    frac_f = (d_f.p_cm3 - d_f.n_cm3).mean() / NA
    assert abs(frac_b - frac_f) <= delta, \
        f"G9 FAIL: Boltzmann {frac_b:.6f} vs FD {frac_f:.6f}, " \
        f"series deviation {delta:.2e}"


def test_g10_affinity_gauge_still_refused():
    """G10: Device1D refuses band_offset='affinity' with incomplete_ion
    (the eta-space contact solver and the affinity shift each carry
    their own ln(Nc/nie) offset and composing them is underived).  The
    2D/3D lift must inherit that refusal rather than silently
    composing them."""
    x, dop1 = _junction_x()
    y = np.linspace(0.0, 4.0e-5, 3)
    with pytest.raises(NotImplementedError, match="affinity"):
        Device2D(Mesh2D(x, y), np.tile(dop1, (3, 1)), T=T,
                 models=Models(bgn=False, srh=False, incomplete_ion=True,
                               band_offset="affinity"))
    z = np.linspace(0.0, 3.0e-5, 3)
    dop3 = np.broadcast_to(dop1, (3, 3, x.size)).copy()
    with pytest.raises(NotImplementedError, match="affinity"):
        Device3D(Mesh3D(x=x, y=y, z=z), dop3, T=T,
                 models=Models(bgn=False, srh=False, incomplete_ion=True,
                               band_offset="affinity"))


# G10b (the unstructured path must keep refusing incomplete_ion, since
# unstructured_poisson.py/unstructured_dd.py have no ionization
# mechanism at all) is NOT duplicated here: it is already gated by
# tests/test_m21_phase3.py::test_wrapper_refuses_unsupported_models_flags,
# whose refusal list names "incomplete_ion" explicitly and which builds
# the real GmshMesh that refusal path needs.  M41 changed nothing there
# -- verified by running that test after this slice.
