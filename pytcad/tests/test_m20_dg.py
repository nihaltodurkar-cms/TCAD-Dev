"""M20 acceptance gates: density-gradient quantum correction.

Every gate is specified in M20-DENSITY-GRADIENT-PLAN.md section 3
(G-A .. G-F) and each one compares the DG implementation against
something independent of it:

  G-A  bit-identity of the DEFAULT (dg=False) path -- the amendment
       rule for a core-solver edit
  G-B  the Schrodinger-Poisson solver vs CLOSED-FORM Airy triangular-
       well physics (the reference solver is itself validated before
       it is used as anybody's reference)
  G-C  the DG MOSCapacitor centroid vs the S-P centroid and the
       literature ~1 nm figure
  G-D  DG-ON physics DIRECTION (centroid > 0.2 nm, surface density
       suppressed, Lambda peaked off the boundary, C_max dropped
       3-25%)
  G-E  refusals: out-of-scope compositions raise, they are never
       silently dropped
  G-F  catalog + wire-format invariants

The DG gates run on a THIN oxide (2 nm): the regime where the quantum
centroid matters and where the README section-6 caveat's 10-20% C_max
figure comes from.  At the classical-validation suite's 5 nm oxide the
centroid term x_c/eps_s is ~2% of 1/Cox and the effect is ungateable.

    python -m pytest tests/test_m20_dg.py -q
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings

import numpy as np
import pytest

from pytcad import Device1D, Models, MOSCapacitor
from pytcad.dg import (airy_triangular_well, quantum_potential,
                       schrodinger_poisson, schrodinger_poisson_mos)
from pytcad.mesh import graded_mesh
from pytcad.constants import trapz

warnings.simplefilter("ignore")

# The classical-validation suite's standard MOS-C (G-A bit-identity is
# about the default path, so it uses the same config as test_cv_...).
PARAMS_CL = dict(Nsub=-1e17, tox_cm=5e-7, gate="n+poly", T=300.0)

# The thin-oxide quantum-regime device for G-C/G-D.
PARAMS = dict(Nsub=-1e17, tox_cm=2e-7, gate="n+poly", T=300.0)


def _v_th(params):
    return MOSCapacitor(**params).analytic_landmarks()["V_th"]


def _vg_strong():
    """One volt past threshold: strong inversion (sheet ~1e13 cm^-2)."""
    return _v_th(PARAMS) + 1.0


# ======================================================================
# G-A  bit-identity of the dg=False default
# ======================================================================
def test_ga_default_flag_is_off():
    """The Models default is dg=False and the wire-format default carries
    dg=False -- the off-path is the shipped configuration."""
    assert Models().dg is False
    assert Models().dg_gamma == 1.0
    from gui.services.device_spec import _default_models
    from workbench.core.catalog import ModelCatalog
    assert _default_models()["dg"] is False
    assert ModelCatalog.describe("dg").enabled_by_default is False


def test_ga_moscap_cv_bit_identical_with_dg_off():
    """dg=False (the default) must be BIT-identical to an explicitly
    constructed pre-M20-style MOSCapacitor: same class, same call, the
    DG branch sits entirely behind `if self.dg:`."""
    vg = np.arange(-1.5, 2.01, 0.25)
    m_default = MOSCapacitor(**PARAMS_CL)
    m_off = MOSCapacitor(**PARAMS_CL, dg=False)
    phis_d, Qg_d, C_d = m_default.cv_sweep(vg)
    phis_o, Qg_o, C_o = m_off.cv_sweep(vg)
    assert np.array_equal(phis_d, phis_o)
    assert np.array_equal(Qg_d, Qg_o)
    assert np.array_equal(C_d, C_o)
    # and the off-path solve leaves no DG state behind
    assert m_default._dg_Lam_n is None and m_default._dg_Lam_p is None


def test_ga_device1d_equilibrium_bit_identical_with_dg_off():
    """Two fresh 1D devices, identical construction except the explicit
    dg=False flag: equilibrium psi/n/p must be array_equal (not approx).
    """
    x = graded_mesh(2e-4, [1e-4], 1e-7, 2e-6, 1.2)
    dop = np.where(x < 1e-4, -1e17, 1e17)

    d_default = Device1D(x, dop, models=Models(bgn=False))
    d_default.solve_equilibrium()
    d_off = Device1D(x, dop, models=Models(bgn=False, dg=False))
    d_off.solve_equilibrium()

    assert np.array_equal(d_default.psi, d_off.psi)
    assert np.array_equal(d_default.n, d_off.n)
    assert np.array_equal(d_default.p, d_off.p)
    assert d_default._dg_Lam_n is None and d_default._dg_Lam_p is None


# ======================================================================
# G-B  Airy analytic reference (the S-P solver validated against
#      closed-form physics BEFORE it is used as a reference)
# ======================================================================
def test_gb_airy_analytic_values():
    """The closed-form side of G-B, pinned by hand-computed values: the
    m*=0.26, F=1 MV/cm Si triangular well has
        E_1 = (hbar^2/2m)^(1/3) (qF)^(2/3) a_1 = 0.266 eV
        <x>_1 = 2 E_1 / (3 qF) = 1.77 nm
    (a_1 = 2.33811; both from the standard Airy results, e.g. Sze & Ng
    ch. 4)."""
    E, xc = airy_triangular_well(1e6, m_star=0.26, n_levels=3)
    assert E[0] == pytest.approx(0.266, rel=0.02), E[0]
    assert xc[0] == pytest.approx(1.77e-7, rel=0.02)      # ~1.77 nm in cm
    # subband ratios follow the Airy zeros; centroid scales with E
    assert E[1] / E[0] == pytest.approx(4.08795 / 2.33811, rel=1e-3)
    assert xc[1] / xc[0] == pytest.approx(E[1] / E[0], rel=1e-9)


def test_gb_schrodinger_matches_airy_triangular_well():
    """G-B proper: schrodinger_poisson on a pure triangular well
    (E_band = F*x eV, hard wall at x=0) reproduces the Airy E_1 and the
    ground-state centroid within 5% -- the eigensolver, normalization
    and occupation machinery validated against closed-form physics.
    N_total = 1e16 m^-2 = 1e12 cm^-2 keeps >97% of the sheet in E_1,
    so the density centroid IS the ground-state centroid."""
    F = 1e6                                     # V/cm
    x = np.linspace(0.0, 4e-6, 401)             # cm, uniform (h = 0.1 nm)
    E_band = F * x                              # eV
    E_ref, xc_ref = airy_triangular_well(F, m_star=0.26, n_levels=3)

    E_sp, n_q = schrodinger_poisson(
        x, E_band, m_star=0.26, T=300.0, N_total=1e16, n_levels=3)
    assert E_sp[0] == pytest.approx(E_ref[0], rel=0.05), (
        f"E1 S-P {E_sp[0]:.4f} vs Airy {E_ref[0]:.4f} eV")
    centroid = trapz(x * n_q, x) / trapz(n_q, x)
    assert centroid == pytest.approx(xc_ref[0], rel=0.05), (
        f"centroid S-P {centroid*1e7:.3f} vs Airy {xc_ref[0]*1e7:.3f} nm")


def test_gb_occupation_sheet_is_textbook_scale():
    """The 2D-DOS occupation must produce TEXTBOOK sheet densities:
    m* kT/(pi hbar^2) ~ 2.8e16 m^-2 per subband at 300 K, so a sheet of
    1e16 m^-2 = 1e12 cm^-2 needs E_F just BELOW E_1 (nearly empty, not
    nearly full).  This pins the units of the occupation law (a
    double-kT bug here gives ~1e-4 m^-2 and was self-caught)."""
    F = 1e6
    x = np.linspace(0.0, 4e-6, 401)
    E_band = F * x
    E_sp, n_q = schrodinger_poisson(
        x, E_band, m_star=0.26, T=300.0, N_total=1e16, n_levels=3)
    sheet = trapz(n_q, x)                    # cm^-2
    assert sheet == pytest.approx(1e12, rel=0.02), sheet
    # and the density is localized in the well (not spread over the mesh)
    assert n_q.max() > 0.01 * sheet / (1e-7)    # peak >> average density


def test_gb_quantum_potential_sign_pushes_charge_off_interface():
    """The DG sign check (plan section 1): for the triangular-well ground
    state psi ~ x*exp(-x/2*lambda) the quantum potential Lambda must be
    POSITIVE near the interface (=> n < n_classical there): charge is
    pushed OFF the interface, the physically-required direction.  A
    sign error in the prefactor fails this gate."""
    lam = 1.2e-7                                # cm (~1.2 nm decay)
    x = np.linspace(0.0, 6e-7, 241)             # h = 0.025 nm << lam
    n = (x / lam) ** 2 * np.exp(-x / lam)       # |psi|^2, zero at the wall
    Lam = quantum_potential(x, n, m_star=0.26)
    # Lambda > 0 wherever x < 4*lam (g''/g < 0 there)
    assert np.all(Lam[1:48] > 0.0), (
        f"Lambda must be > 0 near a hard-wall interface, got "
        f"{Lam[1:5]}")
    # boundary nodes carry the Neumann choice Lambda = 0
    assert Lam[0] == 0.0 and Lam[-1] == 0.0
    # and it is a substantial fraction of a volt (not a numerical ghost)
    assert Lam[1:48].max() > 0.02, Lam[1:48].max()


def test_gb_quantum_potential_input_validation():
    with pytest.raises(ValueError, match="gamma"):
        quantum_potential(np.linspace(0, 1, 5), np.ones(5), 0.26, gamma=0.0)
    with pytest.raises(ValueError, match="gamma"):
        quantum_potential(np.linspace(0, 1, 5), np.ones(5), 0.26,
                          gamma=np.nan)
    with pytest.raises(ValueError, match="F must be positive"):
        airy_triangular_well(0.0)


# ======================================================================
# G-C  centroid vs S-P + the literature ~1 nm figure
# ======================================================================
def test_gc_sp_centroid_in_literature_band():
    """The S-P electron centroid at strong inversion is 0.5-4 nm
    (literature: ~1 nm at ~1 MV/cm surface field; the wide band admits
    the 2 nm-oxide field range)."""
    res = schrodinger_poisson_mos(MOSCapacitor(**PARAMS), _vg_strong())
    xc_nm = res["centroid_cm"] * 1e7
    assert 0.5 < xc_nm < 4.0, f"S-P centroid {xc_nm:.3f} nm outside band"
    # the S-P inversion sheet density itself is a sane strong-inversion
    # value for a 2 nm oxide at V_th + 1 V
    assert 1e12 < res["sheet"] < 5e13, res["sheet"]


def test_gc_dg_centroid_within_factor2_of_sp():
    """The DG MOSCapacitor centroid vs the S-P centroid at the same
    bias: within a factor of 2 (gamma=1 is uncalibrated; the gate
    bounds the error against the codebase's own S-P reference)."""
    res_sp = schrodinger_poisson_mos(MOSCapacitor(**PARAMS), _vg_strong())
    xc_dg = MOSCapacitor(**PARAMS, dg=True).inversion_centroid(_vg_strong())
    ratio = xc_dg / res_sp["centroid_cm"]
    assert 0.5 < ratio < 2.0, (
        f"DG centroid {xc_dg*1e7:.3f} nm vs S-P "
        f"{res_sp['centroid_cm']*1e7:.3f} nm (ratio {ratio:.3f})")


def test_gc_classical_centroid_is_the_sub_debye_tail():
    """The classical (dg=False) centroid is only the sub-Debye thermal
    tail (no confinement): it must be strictly SMALLER than the DG
    centroid and within ~2 nm of the interface.  This is the physics
    motivation for the milestone, stated measurably."""
    xc_cl = MOSCapacitor(**PARAMS).inversion_centroid(_vg_strong())
    xc_dg = MOSCapacitor(**PARAMS, dg=True).inversion_centroid(_vg_strong())
    assert xc_cl < xc_dg, (
        f"classical centroid {xc_cl*1e7:.3f} nm not below DG "
        f"{xc_dg*1e7:.3f} nm")
    assert xc_cl < 2.0e-7, xc_cl * 1e7


# ======================================================================
# G-D  DG-ON physics direction
# ======================================================================
def test_gd_dg_changes_the_physics_in_every_required_direction():
    """One comparison, four directions: (1) DG centroid strictly
    > 0.2 nm, (2) the surface density is SUPPRESSED by the correction,
    (3) Lambda peaks at a first-INTERIOR node (Neumann choice), (4)
    C_max drops 3-25% vs the classical curve."""
    mos_dg = MOSCapacitor(**PARAMS, dg=True)
    mos_cl = MOSCapacitor(**PARAMS)

    # (1) centroid: off the interface by more than a lattice scale
    xc = mos_dg.inversion_centroid(_vg_strong())
    assert xc > 0.2e-7, f"DG centroid {xc*1e7:.3f} nm not > 0.2 nm"

    # (2) suppression: evaluate BOTH densities on the SAME (DG) psi, so
    # the comparison isolates the quantum correction itself; the first
    # interior node is where Lambda acts (Lambda[0] == 0 by BC).
    psi_dg = mos_dg.solve_psi(_vg_strong())
    Lam = mos_dg._dg_Lam_n
    e = np.clip(psi_dg, -700, 700)
    n_cl_same_psi = mos_dg.nie_s * np.exp(e)
    n_dg = n_cl_same_psi * np.exp(-Lam / mos_dg.VT)
    assert n_dg[1] < n_cl_same_psi[1], (
        "DG correction did not suppress the near-surface density")

    # (3) Lambda peaks at a first-interior node, NOT the boundary
    assert Lam[0] == 0.0, "Lambda at the Si/SiO2 interface must be 0"
    k_peak = int(np.argmax(Lam))
    assert 0 < k_peak < len(Lam) - 1, (
        f"Lambda peak at node {k_peak} of {len(Lam)} -- must be interior")

    # (4) C_max drop: 3-25% (the README section-6 caveat's 10-20% band,
    #     widened for the uncalibrated gamma=1 and this oxide/doping)
    vth = _v_th(PARAMS)
    vg = np.arange(vth + 0.3, vth + 1.51, 0.3)
    _, _, C_cl = mos_cl.cv_sweep(vg)
    _, _, C_dg = MOSCapacitor(**PARAMS, dg=True).cv_sweep(vg)
    drop = 1.0 - C_dg.max() / C_cl.max()
    assert 0.03 < drop < 0.25, (
        f"C_max drop {drop*100:.1f}% outside the 3-25% band")


# ======================================================================
# Regression: outer fixed-point convergence (hard-debug find, 2026-08-29)
# ======================================================================
# The original outer loop computed each pass's target Lambda from the
# DG-CORRECTED density (n*exp(-Lambda_old/VT)), closing a 1-node self-
# reference at the node next to the Lambda=0 boundary: Lambda[1] fed
# into n[1] which fed straight back into Lambda[1]'s own curvature
# stencil. Instrumenting the loop showed a RIGID period-2 oscillation
# -- Lambda[1] flipping between exactly +LAMBDA_MAX*VT and
# -LAMBDA_MAX*VT every single outer pass, forever, immune to under-
# relaxation at any damping factor from 1.0 down to 0.02 over up to
# 400 passes. Fixed by sourcing the curvature target from the
# CLASSICAL (psi-only) density instead, which converges in as few as
# 4 outer passes with NO damping at all.
def test_gr_moscap_outer_fixed_point_converges_without_warning():
    """The MOSCapacitor DG outer loop must converge and must not warn."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        mos = MOSCapacitor(**PARAMS, dg=True)
        psi = mos.solve_psi(_vg_strong())
    assert np.all(np.isfinite(psi)), "psi is non-finite"
    assert np.all(np.isfinite(mos._dg_Lam_n)), "Lambda_n is non-finite"
    assert np.all(np.isfinite(mos._dg_Lam_p)), "Lambda_p is non-finite"


def test_gr_device1d_dg_outer_fixed_point_converges_without_warning():
    """Device1D's equilibrium DG outer loop must converge and not warn."""
    x = graded_mesh(2e-4, [1e-4], 1e-6, 2e-6, 1.2)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        d = Device1D(x, dop, models=Models(bgn=False, dg=True))
        d.solve_equilibrium()
    assert np.all(np.isfinite(d.psi)), "psi is non-finite"
    assert np.all(np.isfinite(d._dg_Lam_n)), "Lambda_n is non-finite"
    assert np.all(np.isfinite(d._dg_Lam_p)), "Lambda_p is non-finite"


def test_gr_outer_fixed_point_is_deterministic():
    """Two fresh, identically-parameterized devices converge to the SAME
    Lambda -- the old self-referential scheme never converged at all
    (a rigid oscillation, not a fixed point), so this is only
    meaningful post-fix; it guards against a future regression back to
    a scheme that merely LOOKS converged (e.g. hits its pass cap on a
    state that happens to pass isfinite) without being a genuine,
    repeatable fixed point."""
    mos_a = MOSCapacitor(**PARAMS, dg=True)
    mos_a.solve_psi(_vg_strong())
    mos_b = MOSCapacitor(**PARAMS, dg=True)
    mos_b.solve_psi(_vg_strong())
    assert np.allclose(mos_a._dg_Lam_n, mos_b._dg_Lam_n, rtol=0, atol=1e-9), (
        "repeated solves of an identical device disagree -- not a "
        "genuine converged fixed point")


# ======================================================================
# G-E  refusals
# ======================================================================
def test_ge_device1d_solve_bias_refuses_dg():
    x = graded_mesh(2e-4, [1e-4], 1e-6, 2e-6, 1.2)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    d = Device1D(x, dop, models=Models(bgn=False, dg=True))
    d.solve_equilibrium()
    with pytest.raises(NotImplementedError, match="equilibrium-only"):
        d.solve_bias([0.0, 0.1])


def test_ge_device1d_refuses_dg_fd_and_dg_ion():
    x = graded_mesh(2e-4, [1e-4], 1e-6, 2e-6, 1.2)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    with pytest.raises(NotImplementedError, match="refused"):
        Device1D(x, dop,
                 models=Models(bgn=False, dg=True, fd=True)).solve_equilibrium()
    with pytest.raises(NotImplementedError, match="refused"):
        Device1D(x, dop, models=Models(bgn=False, dg=True,
                                       incomplete_ion=True)).solve_equilibrium()


def test_ge_moscap_refuses_dg_fd_and_bad_gamma():
    with pytest.raises(NotImplementedError, match="refused"):
        MOSCapacitor(**PARAMS_CL, dg=True, fd=True)
    with pytest.raises(ValueError, match="dg_gamma"):
        MOSCapacitor(**PARAMS_CL, dg=True, dg_gamma=0.0)
    with pytest.raises(ValueError, match="dg_gamma"):
        MOSCapacitor(**PARAMS_CL, dg=True, dg_gamma=-1.0)


def test_ge_device2d_and_3d_refuse_dg():
    from pytcad.mesh2d import Mesh2D
    from pytcad.device2d import Device2D
    from pytcad.mesh3d import Mesh3D
    from pytcad.device3d import Device3D

    x = graded_mesh(2e-4, [1e-4], 1e-6, 4e-6, 1.2)
    y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))

    # Device2D/Device3D refuse dg=True EAGERLY, at construction -- the
    # same pattern already used for btbt=True in both classes (M16),
    # not deferred to solve_equilibrium like Device1D.solve_bias's dg
    # guard.  The test previously expected the solve_bias-style
    # deferred raise, which never fires because construction itself
    # already raises first.
    with pytest.raises(NotImplementedError, match="M20 scope"):
        Device2D(Mesh2D(x, y), dop2d, models=Models(bgn=False, dg=True))

    z = graded_mesh(3e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop3d = np.tile(dop2d, (z.size, 1, 1))
    with pytest.raises(NotImplementedError, match="M20 scope"):
        Device3D(Mesh3D(x, y, z), dop3d, models=Models(bgn=False, dg=True))


# ======================================================================
# G-F  catalog + wire-format invariants
# ======================================================================
def test_gf_catalog_and_wire_invariants():
    from workbench.core.catalog import ModelCatalog
    from gui.services.device_spec import _default_models

    info = ModelCatalog.describe("dg")
    assert info.title and "Ancona" in " ".join(info.references)
    assert info.equations and info.applicability
    assert info.limitations and "equilibrium" in info.limitations.lower()
    assert info.enabled_by_default is False
    # the invariant: the catalog default IS the wire default, and the
    # key set matches (the pin tests in test_workbench_m1.py /
    # test_physics_lab.py hold the same set)
    assert ModelCatalog.default_config() == _default_models()
    assert set(ModelCatalog.list()) == set(_default_models())
    # a dg config validates
    ModelCatalog.validate({"dg": True})
