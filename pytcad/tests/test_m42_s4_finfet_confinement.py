"""M42-S4 -- FinFET/GAA fin-corner confinement demonstration
(M42-DENSITY-GRADIENT-2D3D-PLAN.md section 10.8's own scope note:
"confinement from two faces at once in a fin corner. Report as a
QUALITATIVE TREND unless a published FinFET quantum-correction curve
is actually in hand"). No such curve was sought or found (M14-G-A's
standing lesson already documented in this repo) -- every gate below
checks an internally-consistent, physically-motivated TREND (corner
vs. flat-face confinement), not a quantitative match to any published
number.

Two builders in pytcad/finfet3d.py support this slice:
  - build_finfet3d(dg=True, dg_gamma=...): the SAME production
    tri-gate FinFET template M26 already validates (mosfet_doping's
    Gaussian source/drain profile), now DG-capable. Additive: dg=False
    (the default) reproduces the pre-S4 Models() exactly.
  - build_fin_corner_slab(...): a NEW, controlled uniform-doping
    fin-corner geometry (same gate topology/corner-avoidance
    convention as build_finfet3d, but isolating the corner-confinement
    question the way S2's own _build_gated_device isolates the
    single-gate one) -- this is what the quantitative comparison gates
    below actually use, since a full source/drain doping profile adds
    confounds this demonstration does not need.

Gates:
  S4-G1  FD-Jacobian of the full 3N system on the ACTUAL fin-corner
         topology (two orthogonal GateBC faces sharing corner nodes,
         a mesh shape S1-S3's simpler test devices never exercised).
  S4-G2  dg=False bit-identity on build_finfet3d: unaffected by the
         new dg/dg_gamma passthrough.
  S4-CONF the load-bearing gate: at matched bias, the density
         suppression ratio (classical n / DG n) at a corner-adjacent
         node is LARGER than at a flat-face-adjacent node, at every
         bias tried -- the corner feels confinement from two walls at
         once, the flat face from one.
  S4-MONO the corner/flat suppression-ratio gap does not vanish under
         mesh refinement (a spurious node-placement artifact would).
  S4-SMOKE build_finfet3d(dg=True) (the actual production tri-gate
         geometry, mosfet_doping profile and all) solves cleanly to a
         finite state -- confirms S4 is not solely validated on the
         simplified slab.
  extra  refused compositions and solve_bias still refuse dg=True on
         both builders, matching every other Device3D DG gate.
  S4-GAA (added same day, closing the "no GAA geometry" gap) a fourth
         gate face (build_fin_corner_slab(gaa=True)) wraps the fin
         all the way around; the corner effect still holds under this
         topology, with the ohmic reference relocated to the fin's
         long-axis end face (freed from the lateral faces, all four of
         which are now gated).
"""
import warnings

import numpy as np
import pytest

from pytcad.device import Models, NewtonOptions
from pytcad.finfet3d import build_fin_corner_slab, build_finfet3d


def _corner_and_flat_suppression(Vfb, NY=6, NZ=6, Na=1e17):
    dev_dg = build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=Na,
                                   Vfb=Vfb, NY=NY, NZ=NZ, dg=True)
    dev_cl = build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=Na,
                                   Vfb=Vfb, NY=NY, NZ=NZ, dg=False)
    kmid = dev_dg.Nz // 2
    supp_corner = dev_cl.n[1, 1, 1] / dev_dg.n[1, 1, 1]
    supp_flat = dev_cl.n[kmid, 1, 1] / dev_dg.n[kmid, 1, 1]
    return supp_corner, supp_flat


# ---------------------------------------------------------------- S4-G1
def test_g1_fd_jacobian_fin_corner():
    """FD-Jacobian on the actual fin-corner topology: two orthogonal
    GateBC faces (top + side) sharing the corner columns exactly as
    build_finfet3d/build_fin_corner_slab assign them (top claims
    k=0/k=Nz-1; the side gates start at j=1) -- a mesh/BC shape S1-S3's
    simpler single-gate or no-gate test devices never exercised."""
    # A genuinely tiny HAND-BUILT device (not build_fin_corner_slab,
    # whose h_min/h_max-from-NY/NZ formula produces a much larger mesh
    # than NY/NZ suggests -- confirmed directly: NY=3,NZ=4 there yields
    # Ny=13,Nz=21) -- same two-orthogonal-gate corner topology and
    # corner-avoidance convention, at a size actually small enough for
    # a fast 90-column FD-Jacobian sweep.
    from pytcad.mesh3d import Mesh3D
    from pytcad.device3d import Device3D

    x_t = np.array([0.0, 0.4e-4, 1e-4])
    y = np.linspace(0.0, 6e-6, 4)
    z = np.linspace(0.0, 8e-6, 5)
    mesh = Mesh3D(x_t, y, z)
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), -1e17)
    dev = Device3D(mesh, dop, models=Models(bgn=False, dg=True))
    ii = np.arange(mesh.Nx)
    far_i, far_k = np.meshgrid(ii, np.arange(mesh.Nz), indexing="ij")
    dev.add_contact("far", far_i.ravel(),
                    np.full(far_i.size, mesh.Ny - 1), far_k.ravel(), V=0.0)
    top_i, top_k = np.meshgrid(ii, np.arange(mesh.Nz), indexing="ij")
    dev.add_gate("top", top_i.ravel(), np.zeros(top_i.size, dtype=int),
                 top_k.ravel(), tox_cm=2e-7, Vfb=-0.9, normal_axis="y")
    j_side = np.arange(1, mesh.Ny)
    l_i, l_j = np.meshgrid(ii, j_side, indexing="ij")
    dev.add_gate("left", l_i.ravel(), l_j.ravel(),
                 np.zeros(l_i.size, dtype=int),
                 tox_cm=2e-7, Vfb=-0.9, normal_axis="z")
    r_i, r_j = np.meshgrid(ii, j_side, indexing="ij")
    dev.add_gate("right", r_i.ravel(), r_j.ravel(),
                 np.full(r_i.size, mesh.Nz - 1, dtype=int),
                 tox_cm=2e-7, Vfb=-0.9, normal_axis="z")
    N = dev.N
    rng = np.random.default_rng(0)
    shp = (dev.Nz, dev.Ny, dev.Nx)
    # Fresh, moderate random state -- NOT offset from the converged
    # solve above (which sits at large psi / near-pinned Lambda under
    # this bias): matches S1/S3's own FD-Jacobian convention
    # (rng.uniform(-2,2)/(-1e-3,1e-3)), which tests the KERNEL on this
    # mesh's new corner topology, not FD roundoff in an extreme regime.
    psi0 = rng.uniform(-2, 2, shp)
    Lam_n0 = rng.uniform(-1e-3, 1e-3, shp)
    Lam_p0 = rng.uniform(-1e-3, 1e-3, shp)

    F0, J0 = dev._dg_residual_jacobian_eq(psi0, Lam_n0, Lam_p0, gamma=1.0)
    J0d = J0.toarray()

    x0 = np.empty(3 * N)
    x0[0::3] = psi0.ravel()
    x0[1::3] = Lam_n0.ravel()
    x0[2::3] = Lam_p0.ravel()

    def unpack(v):
        return (v[0::3].reshape(shp), v[1::3].reshape(shp), v[2::3].reshape(shp))

    # eps=1e-6 (S1/S3's own value) is roundoff-dominated for at least
    # one column on THIS specific device/draw -- measured directly:
    # fd=-2.1771e-05 vs an=-2.1782e-05 (the two genuinely agree to
    # ~3 significant figures) but the column-max-relative metric
    # amplifies that to 8.8e-5, just over 5e-5. eps=1e-5 was swept and
    # confirmed to bring the SAME worst column down to 6.7e-6 -- an
    # eps choice, not a loosened tolerance.
    eps = 1e-5
    rng2 = np.random.default_rng(1)
    cols = rng2.choice(3 * N, size=min(3 * N, 90), replace=False)
    worst = 0.0
    for c in cols:
        xp, xm = x0.copy(), x0.copy()
        xp[c] += eps
        xm[c] -= eps
        Fp, _ = dev._dg_residual_jacobian_eq(*unpack(xp), gamma=1.0)
        Fm, _ = dev._dg_residual_jacobian_eq(*unpack(xm), gamma=1.0)
        fd_col = (Fp - Fm) / (2 * eps)
        an_col = J0d[:, c]
        denom = max(np.abs(an_col).max(), 1e-12)
        worst = max(worst, np.abs(fd_col - an_col).max() / denom)
    assert worst < 5e-5, f"FD-Jacobian mismatch on fin-corner topology: {worst:.3e}"


# ---------------------------------------------------------------- S4-G2
def test_g2_off_bit_identity_build_finfet3d():
    """build_finfet3d's new dg/dg_gamma passthrough must not change the
    dg=False path -- Models(dg=False, dg_gamma=1.0) is field-for-field
    identical to the pre-S4 Models()."""
    kwargs = dict(Lg=1e-6, Lsd=1e-6, Hfin=6e-7, Wfin=8e-7, tox_cm=2e-7,
                  Na=1e17, Nsd_peak=1e19, NX=2, NY=2, NZ=3, mesh_ratio=1.4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the doping-scale UserWarning
        dev_explicit = build_finfet3d(dg=False, dg_gamma=1.0, **kwargs)
        dev_default = build_finfet3d(**kwargs)
    assert np.array_equal(dev_explicit.C, dev_default.C)
    assert dev_explicit.models.dg == dev_default.models.dg == False
    dev_explicit.solve_equilibrium(NewtonOptions(max_iter=200))
    dev_default.solve_equilibrium(NewtonOptions(max_iter=200))
    assert np.array_equal(dev_explicit.psi, dev_default.psi)
    assert np.array_equal(dev_explicit.n, dev_default.n)


# -------------------------------------------------------------- S4-CONF
@pytest.mark.parametrize("Vfb", [-0.6, -0.9, -1.2])
def test_conf_corner_confinement_exceeds_flat_face(Vfb):
    """The load-bearing gate: DG's density suppression (classical n /
    DG n) is LARGER at a corner-adjacent node (one step in from BOTH
    the top gate face and a side gate face at once) than at a
    flat-face-adjacent node (one step from the top face only, far from
    either sidewall) -- the physically expected fin-corner effect
    (Colinge, "FinFETs and Other Multi-Gate Transistors", already
    cited in finfet3d.py's own M26 docstring): a corner is confined by
    two orthogonal gate walls, a flat face by one."""
    supp_corner, supp_flat = _corner_and_flat_suppression(Vfb)
    assert supp_corner > supp_flat, (
        f"Vfb={Vfb}: corner suppression {supp_corner:.3e} not > "
        f"flat-face suppression {supp_flat:.3e}")
    # Not just "larger" -- a genuine physical effect, not FD noise.
    assert supp_corner > 2.0 * supp_flat, (
        f"Vfb={Vfb}: corner/flat suppression ratio "
        f"{supp_corner / supp_flat:.3f} too close to 1 to be a real effect")


# -------------------------------------------------------------- S4-MONO
def test_mono_corner_effect_survives_mesh_refinement():
    """Mesh convergence: the corner/flat suppression GAP must not be a
    coarse-mesh node-placement artifact -- same spirit as S2's own
    test_gmesh_centroid_convergence."""
    supp_corner_coarse, supp_flat_coarse = _corner_and_flat_suppression(
        Vfb=-0.9, NY=4, NZ=4)
    supp_corner_fine, supp_flat_fine = _corner_and_flat_suppression(
        Vfb=-0.9, NY=8, NZ=8)
    assert supp_corner_coarse > supp_flat_coarse
    assert supp_corner_fine > supp_flat_fine
    ratio_coarse = supp_corner_coarse / supp_flat_coarse
    ratio_fine = supp_corner_fine / supp_flat_fine
    # Both comfortably above 1 (not a marginal/borderline effect that
    # mesh refinement could flip); the exact ratio is not pinned to a
    # tolerance since node placement legitimately shifts WHICH physical
    # location "one step in" corresponds to as NY/NZ change.
    assert ratio_coarse > 1.5
    assert ratio_fine > 1.5


# ------------------------------------------------------------- S4-SMOKE
def test_smoke_production_finfet_dg_solves():
    """The actual production tri-gate template (mosfet_doping's
    Gaussian source/drain profile, not the simplified uniform-doping
    slab) also solves with dg=True, to a finite, deterministic state --
    confirms S4 is not validated ONLY on the simplified geometry."""
    kwargs = dict(Lg=1e-6, Lsd=1e-6, Hfin=6e-7, Wfin=8e-7, tox_cm=2e-7,
                  Na=1e17, Nsd_peak=1e19, NX=2, NY=2, NZ=3, mesh_ratio=1.4,
                  dg=True, dg_gamma=1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the doping-scale UserWarning
        dev_a = build_finfet3d(**kwargs)
        dev_b = build_finfet3d(**kwargs)
    for name in ("gate_top", "gate_left", "gate_right"):
        dev_a.bcs[name].Vfb -= 0.6
        dev_b.bcs[name].Vfb -= 0.6
    dev_a.solve_equilibrium(NewtonOptions(max_iter=400))
    dev_b.solve_equilibrium(NewtonOptions(max_iter=400))
    assert np.all(np.isfinite(dev_a.psi))
    assert np.all(np.isfinite(dev_a._dg_Lam_n))
    assert np.all(np.isfinite(dev_a._dg_Lam_p))
    assert np.array_equal(dev_a.psi, dev_b.psi), "not deterministic"


# --------------------------------------------------------------- S4-GAA
def test_gaa_corner_effect_holds_with_fourth_gate_face():
    """gaa=True wraps a fourth gate face (bottom, y=Ly) -- a genuine
    gate-all-around cross-section, closing the "no GAA geometry" gap.
    The ohmic reference relocates to the fin's long-axis end face
    (i=0), freed from the lateral faces now that all four are gated.
    The corner-confinement trend (S4-CONF) must still hold under this
    topology."""
    dev_dg = build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=1e17,
                                   Vfb=-0.9, gaa=True, dg=True)
    dev_cl = build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=1e17,
                                   Vfb=-0.9, gaa=True, dg=False)
    assert np.all(np.isfinite(dev_dg.psi))
    kmid = dev_dg.Nz // 2
    supp_corner = dev_cl.n[1, 1, 1] / dev_dg.n[1, 1, 1]
    supp_flat = dev_cl.n[kmid, 1, 1] / dev_dg.n[kmid, 1, 1]
    assert supp_corner > 2.0 * supp_flat, (
        f"GAA corner/flat suppression ratio "
        f"{supp_corner / supp_flat:.3f} too close to 1")


def test_gaa_false_default_unaffected():
    """gaa=False (the default) must reproduce build_fin_corner_slab's
    pre-GAA behavior exactly -- additive, not a topology change for
    every existing S4 caller."""
    kwargs = dict(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=1e17, Vfb=-0.9, dg=False)
    dev_explicit = build_fin_corner_slab(gaa=False, **kwargs)
    dev_default = build_fin_corner_slab(**kwargs)
    assert set(dev_explicit.bcs.keys()) == set(dev_default.bcs.keys())
    assert np.array_equal(dev_explicit.psi, dev_default.psi)


# --------------------------------------------------------------- extra
def test_solve_bias_refuses_dg_on_finfet3d():
    dev = build_fin_corner_slab(Ly=6e-6, Lz=8e-6, tox_cm=2e-7, Na=1e17,
                                Vfb=-0.9, NY=3, NZ=4, dg=True)
    with pytest.raises(NotImplementedError):
        dev.solve_bias({"top": 0.0})


@pytest.mark.parametrize("extra", [
    dict(fd=True),
    dict(incomplete_ion=True),
])
def test_refused_compositions_via_finfet3d(extra):
    kwargs = dict(Lg=1e-6, Lsd=1e-6, Hfin=6e-7, Wfin=8e-7, tox_cm=2e-7,
                  Na=1e17, Nsd_peak=1e19, NX=2, NY=2, NZ=3, mesh_ratio=1.4,
                  dg=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(NotImplementedError):
            _build_with_extra_models(kwargs, extra)


def _build_with_extra_models(kwargs, extra):
    """build_finfet3d itself has no passthrough for fd/incomplete_ion --
    the refusal lives in Device3D's own constructor, so this drives it
    the same way build_finfet3d does internally (Mesh3D/Device3D
    directly) rather than adding unrelated new parameters to
    build_finfet3d for a one-off gate."""
    from pytcad.mesh import graded_mesh
    from pytcad.mesh2d import Mesh2D
    from pytcad.mesh3d import Mesh3D
    from pytcad.device3d import Device3D
    from pytcad.mosfet import mosfet_doping

    Lg, Lsd, Hfin, Wfin = kwargs["Lg"], kwargs["Lsd"], kwargs["Hfin"], kwargs["Wfin"]
    NX, NY, NZ = kwargs["NX"], kwargs["NY"], kwargs["NZ"]
    ratio = kwargs["mesh_ratio"]
    L = 2 * Lsd + Lg
    x = graded_mesh(L, [Lsd, Lsd + Lg], h_min=L / (NX * 20), h_max=L / NX, ratio=ratio)
    y = graded_mesh(Hfin, [0.0], h_min=Hfin / (NY * 20), h_max=Hfin / NY, ratio=ratio)
    z = graded_mesh(Wfin, [0.0, Wfin], h_min=Wfin / (NZ * 20), h_max=Wfin / NZ, ratio=ratio)
    mesh2 = Mesh2D(x, y)
    dop2d, ntot2d = mosfet_doping(mesh2, Lsd, Lg, kwargs["Na"], kwargs["Nsd_peak"],
                                  Lg / 4.0, Lg / 4.0)
    doping = np.tile(dop2d, (z.size, 1, 1))
    ntotal = np.tile(ntot2d, (z.size, 1, 1))
    mesh3 = Mesh3D(x, y, z)
    return Device3D(mesh3, doping, Ntotal=ntotal,
                    models=Models(dg=True, **extra))
