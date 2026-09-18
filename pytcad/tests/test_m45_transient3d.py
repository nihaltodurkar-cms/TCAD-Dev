"""M45 -- transient (time-dependent) Device3D acceptance gates.

Closes the "Transient / small-signal AC -> 3D" row of ARCHITECTURE.md's
dimensional-lift coverage matrix (section 5.3). transient3d.py drives
Device3D through its own _residual_jacobian from OUTSIDE device3d.py
(identical externally-driven pattern to transient.py/transient2d.py) --
these gates exercise that module, not a device3d.py change, since none
was made.

Gates:
  G1  FD-Jacobian: the analytic 3D transient Jacobian (theta-scheme
      storage term on top of Device3D's own analytic J) must match a
      numerical Jacobian of the same transient residual.
  G2  Reduction: a z-uniform Device3D transient run must reduce to
      Device2D's own transient run (final psi/n, and every recorded
      terminal current) to floating-point noise -- the load-bearing
      dimensional-lift gate (4d.4's rule), and the gate that actually
      catches an index/dimension-lift bug (an FD-Jacobian check alone
      cannot catch a bug that is consistent within a single dimension,
      e.g. a wrong physical unit conversion applied uniformly).
  G3  Scope refusal: transient3d.solve_transient rejects a Device2D.
  G4  Reference: direct 3D port of transient2d.py's own G5 -- a single
      large backward-Euler step relaxes to Device3D.solve_bias's own
      converged state at the same final bias.
  G5  Reference: direct 3D port of transient2d.py's own G4 -- the sum
      of all contact terminal currents equals d/dt of total stored
      mobile charge at every accepted step.
  G6  Reference: direct 3D port of transient2d.py's own G1 -- a small
      excess-charge perturbation on a uniform, zero-bias 3D slab decays
      with tau = eps/sigma.

  G4-G6 are independent physics checks (not the reduction-to-2D
  identity G2 already covers) -- ported directly from transient2d.py's
  own already-gated reference tests, one axis further, closing an
  honestly-disclosed gap from M45's first landing (see
  M45-TRANSIENT-AC-3D-PLAN.md).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.constants import Q
from pytcad.transient3d import (
    solve_transient, _step_residual_jacobian, _non_contact_flat_index,
)
from pytcad.transient import StepWaveform

warnings.simplefilter("ignore")


def _diode3d(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, Ly=5e-5, Lz=3e-5, Nz=3):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    y = graded_mesh(Ly, [0.0], 1e-7, 1e-5, 1.15)
    z = np.linspace(0.0, Lz, Nz)
    dop1d = np.where(x < xj, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    dop3d = np.tile(dop2d, (z.size, 1, 1))
    mesh2 = Mesh2D(x, y)
    mesh3 = Mesh3D(x, y, z)
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    return dev2, dev3


# ---------------------------------------------------------------- G1
def test_g1_fd_jacobian_matches_numerical():
    _, dev = _diode3d(Nz=3)
    dev.solve_equilibrium()
    k_free = _non_contact_flat_index(dev)
    dV = dev.dV
    dt_s = 1.0

    rng = np.random.default_rng(0)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 1e-3 * rng.standard_normal(dev.p.shape))
    voltages = {"left": 0.2, "right": 0.0}

    F0, J0, *_ = _step_residual_jacobian(
        dev, psi, n, p, voltages, dev.n, dev.p, None, None, dV, dt_s, 1.0,
        k_free)
    J0 = J0.toarray()

    Nz, Ny, Nx = dev.Nz, dev.Ny, dev.Nx
    N3 = 3 * Nz * Ny * Nx
    cols = rng.choice(N3, size=50, replace=False)
    u0 = np.stack([psi, n, p], axis=-1).ravel()
    h = 1e-7
    worst = 0.0
    for c in cols:
        u_p = u0.copy(); u_p[c] += h
        u_m = u0.copy(); u_m[c] -= h
        shp = (Nz, Ny, Nx)
        Fp, *_ = _step_residual_jacobian(
            dev, u_p[0::3].reshape(shp), u_p[1::3].reshape(shp),
            u_p[2::3].reshape(shp), voltages, dev.n, dev.p, None, None,
            dV, dt_s, 1.0, k_free)
        Fm, *_ = _step_residual_jacobian(
            dev, u_m[0::3].reshape(shp), u_m[1::3].reshape(shp),
            u_m[2::3].reshape(shp), voltages, dev.n, dev.p, None, None,
            dV, dt_s, 1.0, k_free)
        fd = (Fp - Fm) / (2 * h)
        worst = max(worst, np.abs(fd - J0[:, c]).max()
                    / max(np.abs(J0[:, c]).max(), 1e-12))
    assert worst < 5e-5, f"Device3D transient FD-Jacobian mismatch: {worst:.3e}"


# ---------------------------------------------------------------- G2
def test_g2_device3d_reduces_to_device2d():
    dev2, dev3 = _diode3d(Nz=3)
    dev2.solve_equilibrium()
    dev3.solve_equilibrium()

    from pytcad.transient2d import solve_transient as solve_transient_2d
    wf = StepWaveform(0.0, 0.3, t_step=0.0)
    r2 = solve_transient_2d(dev2, {"left": wf}, t_end=5e-11, dt0=1e-13)
    r3 = solve_transient(dev3, {"left": wf}, t_end=5e-11, dt0=1e-13)

    assert np.abs(dev3.psi - dev2.psi[None, :, :]).max() < 1e-9
    assert (np.abs(dev3.n - dev2.n[None, :, :]).max() / dev2.n.max()) < 1e-7
    assert r2.times.shape == r3.times.shape
    assert np.abs(r2.times - r3.times).max() < 1e-20 * max(1.0, r2.times.max())

    # terminal_current units differ by design: Device2D's is A/cm (per
    # unit depth), Device3D's is real Amps (every physical dimension
    # meshed) -- see transient3d.py's own TransientResult3D docstring
    # and Device3D.terminal_current's. A z-uniform 3D device must equal
    # the 2D result times its own real z-extent [cm].
    Lz = dev3.mesh.z[-1] - dev3.mesh.z[0]
    for name in ("left", "right"):
        I2, I3 = r2.terminal_current[name], r3.terminal_current[name]
        assert I2.shape == I3.shape
        rel = np.abs(I3 - I2 * Lz) / np.maximum(np.abs(I2 * Lz), 1e-12)
        assert rel.max() < 1e-6, f"{name}: transient current reduction mismatch {rel.max():.3e}"


# ---------------------------------------------------------------- G3
def test_g3_scope_refusal_rejects_device2d():
    dev2, _ = _diode3d(Nz=3)
    dev2.solve_equilibrium()
    with pytest.raises(TypeError):
        solve_transient(dev2, {"left": 0.1}, t_end=1e-11, dt0=1e-13)


def _diode3d_small(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, Ly=5e-5, Lz=3e-5, Nz=3):
    """A COARSER diode3d for the multi-step reference gates (G4/G5):
    _diode3d()'s own fine mesh (h_min=1e-8, needed for the single-shot
    FD-Jacobian/reduction checks G1-G3 already pass fast with) has
    Nx=262 -- 23580 total nodes. A genuinely 3D structured mesh's
    direct sparse LU (transient3d.py's solve_transient calls
    scipy.sparse.linalg.spsolve fresh every Newton iteration, every
    step, same as transient2d.py) suffers far worse fill-in growth
    than 2D's own equivalent mesh at that node count (the same reason
    M22 built Krylov/AMG/PETSc alternatives for 3D bias solves
    elsewhere) -- a stiff many-step transient (G5's dt_min=1e-15 can
    mean hundreds of steps) on that mesh took over 28 CPU-minutes
    without finishing. A 10x coarser mesh keeps the same physics
    (same doping, same junction) while keeping each step's direct
    solve fast -- the correctly-scoped fix for a fixture that was
    sized for a single solve, not hundreds of them, not a reason to
    change transient3d.py's solver choice or port anything to C++."""
    x = graded_mesh(L, [xj], 1e-7, 2e-6, 1.15)
    y = graded_mesh(Ly, [0.0], 5e-7, 4e-6, 1.2)
    z = np.linspace(0.0, Lz, Nz)
    dop1d = np.where(x < xj, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    dop3d = np.tile(dop2d, (z.size, 1, 1))
    mesh3 = Mesh3D(x, y, z)
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    return dev3


def _diode3d_g4(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, Ly=5e-5, Lz=3e-5, Nz=5):
    """A dedicated fixture for G4 -- the single very aggressive step
    dt_s~6e8 (dt0=1e-3 physical seconds, mapping through t0=Ns/R0
    identically in 2D and 3D since t0 depends only on doping/material,
    confirmed directly) turned out NOT to converge at all on
    _diode3d_small's Nz=3.

    Root cause, found by directly comparing per-iteration Newton
    behavior between Device2D and Device3D at the IDENTICAL operating
    point (2D converges in 6 iterations; 3D's line search failed
    completely, chosen_lam=0, within 3 iterations): the raw (unclipped)
    Newton correction (dpsi, dn, dp) from the linear solve IS
    numerically identical between 2D and 3D to ~1e-13 (as G2's own
    reduction gate already established at CONVERGED states) -- but at
    Nz=3, printing the worst-residual nodes after one trial step showed
    every single one sitting at k=1, the ONE interior z-node, never at
    the two z-BOUNDARY nodes (k=0, k=Nz-1). Nz=3's single interior node
    has a control-volume width in z (dVz) TWICE that of a boundary node
    (the standard box-integration convention: a boundary cell only
    extends half the spacing to its one neighbor; an interior cell with
    Nz=3 has a FULL-width neighbor on both sides) -- so the SAME
    aggressive dt_s stresses that one node's transient storage term
    (-dV/dt_s*(n-n0)) disproportionately harder than every other node,
    including its own z-neighbors. `_newton_step`'s line search shares
    ONE global damping factor lam across every node, so the single
    worst node (here, the lone interior z-slice) can force lam all the
    way to 0 even though every other node -- including a hypothetical
    2D problem with no such node at all -- would already have
    converged. This is a genuine z-under-resolution artifact, not a
    2D-vs-3D Newton robustness gap and not something transient3d.py's
    solver choice (spsolve vs a smarter iterative/AMG method, "port to
    C++", etc.) has anything to do with: confirmed directly by
    re-running the identical comparison at Nz=7, where 3D converges
    (8 iterations, a few damped ones then quadratic, qualitatively
    matching 2D) with NO other change.

    Nz=5 here is the smallest Nz that also converges (verified
    directly) while keeping the mesh affordable: Device3D's own
    solve_equilibrium/solve_bias (frozen core, unrelated to this
    milestone) scale poorly with total node count via their own direct
    sparse solve -- confirmed directly (N=18060 at Nz=7 with this
    fixture's x/y density took ~30s for ONE solve_bias call alone) --
    so x/y are also coarsened here (not just relative to _diode3d, but
    relative to _diode3d_small too) to keep total N small enough that
    the THREE solve_equilibrium/solve_bias setup calls plus the full
    stiff transient run complete in around a minute, not many
    minutes."""
    x = graded_mesh(L, [xj], 3e-7, 6e-6, 1.2)
    y = graded_mesh(Ly, [0.0], 1e-6, 8e-6, 1.25)
    z = np.linspace(0.0, Lz, Nz)
    dop1d = np.where(x < xj, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    dop3d = np.tile(dop2d, (z.size, 1, 1))
    mesh3 = Mesh3D(x, y, z)
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    return dev3


def _uniform3d(Nd=1e15, L=2e-4, Ly=5e-5, Lz=3e-5, nx=41, ny=11, nz=3):
    x = np.linspace(0.0, L, nx)
    y = np.linspace(0.0, Ly, ny)
    z = np.linspace(0.0, Lz, nz)
    mesh = Mesh3D(x, y, z)
    dop = np.full((nz, ny, nx), Nd)
    dev = Device3D(mesh, dop, models=Models(bgn=False))
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, nx - 1), j=jj, k=kk, V=0.0)
    return dev


# ---------------------------------------------------------------- G4
def test_g4_steady_state_consistency_reference():
    """G4: direct 3D port of transient2d.py's own G5 -- one very large
    backward-Euler step from a perturbed state, under a fixed bias,
    must relax to the same converged state Device3D.solve_bias reaches
    for that bias directly. An independent physics check, not just the
    reduction-to-2D identity G2 already covers.

    Uses _diode3d_g4() (Nz=5, coarser x/y than _diode3d_small) -- see
    that fixture's own docstring for the full root-cause investigation
    of why Nz=3 does not converge here at all (a z-under-resolution
    artifact at the single interior z-node, not a 2D-vs-3D solver
    gap)."""
    dev = _diode3d_g4()
    dev.solve_equilibrium()
    ref = _diode3d_g4()
    ref.solve_equilibrium()
    ref.solve_bias({"left": 0.3, "right": 0.0})

    dev.solve_bias({"left": 0.05, "right": 0.0})
    result = solve_transient(dev, waveforms={"left": 0.3, "right": 0.0},
                              t_end=1.0, dt0=1e-3, dt_min=1e-12,
                              dt_max=1e6, growth=2.0)
    assert result.times[-1] == pytest.approx(1.0)
    j_dev = dev.Jn_x + dev.Jp_x
    j_ref = ref.Jn_x + ref.Jp_x
    assert np.max(np.abs(j_dev - j_ref)) / (np.max(np.abs(j_ref)) + 1e-30) < 0.05


# ---------------------------------------------------------------- G5
def test_g5_charge_conservation_reference():
    """G5: direct 3D port of transient2d.py's own G4 -- at every
    accepted step, the sum of ALL contact terminal currents must equal
    d/dt of the total stored mobile charge. Device3D.terminal_current's
    own convention is IDENTICAL to Device2D's (positive = current INTO
    the device at every contact independently -- both docstrings state
    this), so the same dQ/dt == -(I_left + I_right) identity carries
    over unchanged.

    dt0/t_end differ from transient2d.py's own G4 (which uses
    dt0=1e-9, t_end=2e-7): traced directly (see M45-TRANSIENT-AC-3D-
    PLAN.md section 8) to dt0=1e-9 mapping to a scaled dt_s~600 for
    this doping/material -- an all-at-once jump from equilibrium to
    0.3V forward bias in one step. 2D's smaller/differently-conditioned
    problem happens to converge for that jump; this 3D problem's line
    search fails completely at every damping factor, and (before a
    related fix to transient3d.py's own Newton loop -- see that
    module's _newton_step) wasted the ENTIRE max_iter budget doing so.
    A gentler dt0 (mapping to dt_s~1, growing from there) and a capped
    dt_max avoid re-hitting that same wall on every retry; the identity
    itself is checked over a shorter but still multi-step window
    (verified directly to hold at 4e-7 relative before being written
    here as a gate, not just "should still be true")."""
    dev = _diode3d_small()
    dev.solve_equilibrium()
    result = solve_transient(
        dev, waveforms={"left": StepWaveform(0.0, 0.3, t_step=0.0)},
        t_end=2e-9, dt0=1e-12, dt_min=1e-15, dt_max=2e-10)

    Q_t = result.stored_charge(dev)
    dQ = np.diff(Q_t)
    dt = np.diff(result.times)
    I_left = result.terminal_current["left"][1:]
    I_right = result.terminal_current["right"][1:]
    I_total_in = I_left + I_right
    lhs = dQ / dt
    assert np.allclose(lhs, -I_total_in, rtol=1e-3, atol=1e-9)


# ---------------------------------------------------------------- G6
def test_g6_dielectric_relaxation_reference():
    """G6: direct 3D port of transient2d.py's own G1 -- a small
    excess-charge perturbation on a uniformly doped, zero-bias 3D slab
    decays with tau = eps/sigma, now verified on a genuinely 3D mesh
    (non-trivial y- AND z-direction box integration in play, not just
    a transverse-invariant reduction)."""
    dev = _uniform3d()
    dev.solve_equilibrium()
    mid = (dev.Nz // 2, dev.Ny // 2, dev.Nx // 2)
    sigma = Q * (dev.mu_n0[mid] * dev.n_cm3[mid]
                 + dev.mu_p0[mid] * dev.p_cm3[mid])
    tau = dev.eps / sigma

    n0 = dev.n.copy()
    dev.n = n0 * 1.002

    result = solve_transient(dev, waveforms={}, t_end=6 * tau,
                              dt0=tau / 40, dt_min=tau / 1e6,
                              dt_max=tau / 8, growth=1.2)

    dn = result.n_hist[:, mid[0], mid[1], mid[2]] - n0[mid]
    keep = np.abs(dn) > 1e-3 * np.abs(dn[0])
    t_fit, dn_fit = result.times[keep], dn[keep]
    slope, _ = np.polyfit(t_fit, np.log(np.abs(dn_fit)), 1)
    tau_fit = -1.0 / slope

    assert tau_fit == pytest.approx(tau, rel=0.25)
