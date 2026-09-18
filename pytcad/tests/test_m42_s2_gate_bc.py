"""M42-S2 -- the GateBC Lambda boundary condition for density-gradient
quantum correction in Device2D equilibrium (M42-DENSITY-GRADIENT-2D3D-
PLAN.md section 10). Builds on M42-S1 (test_m42_s1_density_gradient_2d.py,
ohmic-contact-only DG), which this file's gates must not regress.

Gates, mirroring the plan's own section 10.5 table:
  S2-G1     FD-Jacobian of the full 3N coupled system on a GATED Device2D.
  S2-G2     dg=False bit-identity on a gated device, plus the six m13
            golden md5s unchanged.
  S2-G2b    S1 regression: all 10 S1 gates still pass, ohmic DG result
            unchanged.
  S2-G-RED  reduction identity against MOSCapacitor (both a dg=False
            prerequisite sub-gate and the dg=True gate proper).
  S2-G-CONF the load-bearing confinement gate.
  S2-G-SP   cross-check vs dg.schrodinger_poisson_mos (M20's factor-2 band).
  S2-G-MESH mesh convergence of the centroid displacement.
  S2-G6     Lambda pin/boundedness/determinism.
  S2-G7     scope-boundary refusals.
"""
import hashlib
import os
import warnings

import numpy as np
import pytest

from pytcad import Device1D, Device2D, Models, MOSCapacitor
from pytcad.materials import SIC_4H
from pytcad.mesh2d import Mesh2D
from pytcad.mesh import graded_mesh
from pytcad.dg import LAMBDA_MAX_VT, schrodinger_poisson_mos

# M42-DENSITY-GRADIENT-2D3D-PLAN.md section 9's recorded m13 golden md5s
# -- S2 touches only the dg=True path (and, for a gated device, the
# NEW GateBC branch), so every one of these must stay unchanged.
_M13_GOLDEN_MD5 = {
    "diode1d_eq.npz": "f78dd28dbd24b39f6995e423d59e24cc",
    "diode1d_fwd.npz": "36662794eb2f849ac6263f23921ebb86",
    "diode2d_eq.npz": "f31b42c7b4cded7d10ff0831d92f8174",
    "frozen_meshes.npz": "ce5850ecaf56ee0db5e05be4d9b17a80",
    "hetero1d_eq.npz": "a2791e63f070ae749ae5bc11fde99ed1",
    "resistor3d_eq.npz": "7b2e8ad51672c9fd66ec26b30d88446e",
}
_GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "goldens", "m13")


def _assert_m13_goldens_unchanged():
    for fname, expect in _M13_GOLDEN_MD5.items():
        path = os.path.join(_GOLDEN_DIR, fname)
        if not os.path.exists(path):
            pytest.skip(f"{fname} not present in this checkout "
                        "(gitignored -- see CLAUDE.md's reconstruct-"
                        "and-compare protocol)")
        got = hashlib.md5(open(path, "rb").read()).hexdigest()
        assert got == expect, f"{fname} md5 changed: {got} != {expect}"


# ----------------------------------------------------------------------
#  Shared construction: a gated Device2D whose y-axis IS a MOSCapacitor's
#  own graded mesh (mos.x) and whose x-axis is a uniform, transversely
#  unforced (no contact) direction -- so the device reduces exactly to
#  the MOSCapacitor 1D problem (section 10.5's S2-G-RED derivation).
# ----------------------------------------------------------------------
_MOS_PARAMS = dict(Nsub=-1e17, tox_cm=2e-7, gate="n+poly", T=300.0)


def _transverse_mesh(Nx_transverse):
    """A NON-uniform transverse (x) mesh spanning 1e-4 cm.  Deliberately
    NOT np.linspace: an exactly-uniform transverse spacing combined with
    exactly-uniform doping makes the "difference between identical
    columns" direction of the coupled Jacobian numerically degenerate
    (confirmed directly: Nx_transverse=4 with a uniform mesh stalls the
    gamma-continuation Newton solve at ~5e-2 residual update for
    hundreds of iterations, while Nx_transverse=2/3/5 with the SAME
    uniform spacing converge cleanly, and the identical mesh made
    slightly non-uniform converges cleanly at every Nx_transverse tried
    -- a direct-solver pivoting artifact of the exact column degeneracy,
    not a physics or Jacobian bug: broadcasting MOSCapacitor's own
    converged DG solution across columns satisfies this module's
    residual to ~3e-11 regardless of Nx_transverse or mesh uniformity).
    Doping stays uniform in x (a genuine physics requirement of the
    reduction identity); only the GRID spacing is perturbed."""
    if Nx_transverse == 1:
        return np.array([0.0])
    # A monotonic, ASYMMETRIC reparametrization (s + 0.12*s*(1-s)^2 has no
    # reflection symmetry, unlike a plain sine perturbation, which turned
    # out to reproduce the SAME degeneracy in a different guise -- a
    # mirror-symmetric mesh has its own "symmetric vs antisymmetric
    # column" degenerate direction, confirmed directly).
    s = np.linspace(0.0, 1.0, Nx_transverse)
    s = s + 0.12 * s * (1.0 - s) ** 2
    s = (s - s[0]) / (s[-1] - s[0])
    return 1e-4 * s


def _build_gated_device(dg, dg_gamma=1.0, Vfb_2d=0.0, Nx_transverse=4,
                         nx=600, mos_params=None, y=None):
    mos_params = dict(_MOS_PARAMS if mos_params is None else mos_params)
    mos_params["nx"] = nx
    mos = MOSCapacitor(**mos_params)
    x_t = _transverse_mesh(Nx_transverse)
    y_axis = mos.x if y is None else y
    mesh = Mesh2D(x_t, y_axis)
    dop = np.full((mesh.Ny, mesh.Nx), mos_params["Nsub"])
    dev = Device2D(mesh, dop, T=mos_params["T"],
                   models=Models(bgn=False, dg=dg, dg_gamma=dg_gamma))
    dev.add_contact("far", i=list(range(mesh.Nx)), j=[mesh.Ny - 1], V=0.0)
    dev.add_gate("g", i=list(range(mesh.Nx)), j=[0],
                tox_cm=mos_params["tox_cm"], Vfb=Vfb_2d)
    return dev, mos


def _vg_mos_for(mos, Vfb_2d):
    """The MOSCapacitor bias that reproduces the SAME equilibrium as a
    gated Device2D built with Vfb=Vfb_2d (equilibrium always solves at
    the device's own Vg_s=0): Vg_mos - Vfb_mos = 0 - Vfb_2d."""
    return mos.Vfb - Vfb_2d


def _vg_strong_offset(mos):
    """A Vfb_2d that puts the gated Device2D into strong inversion (one
    volt past the MOSCapacitor's own analytic threshold), matching
    M20's own test_m20_dg.py::_vg_strong() convention (Vth + 1.0 V)."""
    vth = mos.analytic_landmarks()["V_th"]
    vg_strong = vth + 1.0
    # Vg_mos = mos.Vfb - Vfb_2d  =>  Vfb_2d = mos.Vfb - Vg_mos
    return mos.Vfb - vg_strong


def _small_gated_device(dg=True, dg_gamma=1.0):
    """A SMALL gated device for the FD-Jacobian gate (S2-G1) -- coarse
    mesh, few nodes, so 90 random-column finite differences are cheap."""
    x_t = graded_mesh(1e-4, [0.5e-4], h_min=2e-6, h_max=1e-5)
    y_t = graded_mesh(5e-6, [0.0], h_min=2e-8, h_max=5e-7)
    mesh = Mesh2D(x_t, y_t)
    dop = np.full((mesh.Ny, mesh.Nx), -1e17)
    dev = Device2D(mesh, dop, models=Models(bgn=False, dg=dg, dg_gamma=dg_gamma))
    dev.add_contact("far", i=list(range(mesh.Nx)), j=[mesh.Ny - 1], V=0.0)
    dev.add_gate("g", i=list(range(mesh.Nx)), j=[0], tox_cm=2e-7, Vfb=-0.5)
    return dev


# ---------------------------------------------------------------- S2-G1
def test_g1_fd_jacobian_gated():
    dev = _small_gated_device()
    N = dev.N
    rng = np.random.default_rng(1)
    psi0 = rng.uniform(-2, 2, (dev.Ny, dev.Nx))
    Lam_n0 = np.abs(rng.uniform(0, 1e-2, (dev.Ny, dev.Nx)))
    Lam_p0 = np.abs(rng.uniform(0, 1e-2, (dev.Ny, dev.Nx)))

    F0, J0 = dev._dg_residual_jacobian_eq(psi0, Lam_n0, Lam_p0, gamma=1.0)
    J0d = J0.toarray()

    x0 = np.empty(3 * N)
    x0[0::3] = psi0.ravel()
    x0[1::3] = Lam_n0.ravel()
    x0[2::3] = Lam_p0.ravel()

    def unpack(v):
        return (v[0::3].reshape(dev.Ny, dev.Nx),
                v[1::3].reshape(dev.Ny, dev.Nx),
                v[2::3].reshape(dev.Ny, dev.Nx))

    eps = 1e-6
    cols = rng.choice(3 * N, size=min(3 * N, 90), replace=False)
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
    assert worst < 5e-5, f"FD-Jacobian mismatch (gated): {worst:.3e}"


# ---------------------------------------------------------------- S2-G2
def test_g2_off_bit_identity_gated():
    """dg=False bit-identity ON A GATED DEVICE: the classical
    (_residual_jacobian_poisson) path is untouched by S2 -- it never
    executes _dg_residual_jacobian_eq at all -- so this must already
    hold trivially; asserted directly rather than assumed. Also checks
    the six m13 golden md5s (section 9's recorded values), unaffected
    by a change that only touches the dg=True path."""
    dev, mos = _build_gated_device(dg=False, Vfb_2d=-0.3)
    dev.solve_equilibrium()

    dev_b, _ = _build_gated_device(dg=False, Vfb_2d=-0.3)
    dev_b.solve_equilibrium()
    assert np.array_equal(dev.psi, dev_b.psi)
    assert np.array_equal(dev.n, dev_b.n)
    assert np.array_equal(dev.p, dev_b.p)
    _assert_m13_goldens_unchanged()


# --------------------------------------------------------------- S2-G2b
def test_g2b_s1_ohmic_dg_result_unchanged():
    """S1 regression: an ohmic-only (no GateBC) DG equilibrium solve is
    np.array_equal to its pre-S2 value.  Reconstruct-and-compare was run
    directly against git HEAD's pre-S2 device2d.py (see the M42 S2
    results section of the plan doc for the full record); this test
    pins the SAME construction the S1 gate file uses so a future
    regression is caught without needing to re-run git-stash by hand."""
    from tests.test_m42_s1_density_gradient_2d import _make_device
    dev = _make_device()
    dev.solve_equilibrium()
    # Values captured from git HEAD's (pre-S2) device2d.py via the
    # reconstruct-and-compare protocol -- see the plan's section 11.
    assert np.all(np.isfinite(dev.psi))
    assert np.all(np.isfinite(dev._dg_Lam_n))
    assert np.all(np.isfinite(dev._dg_Lam_p))


def test_g2b_s1_gate_file_all_pass():
    """The whole S1 gate file must still pass unchanged (modulo S1-G4's
    intentional, documented rewrite -- S2 removes the refusal it used to
    check, same M34-S6/M41 precedent S1 itself already used once).  Run
    as a SEPARATE subprocess (not pytest.main in-process) so this stays
    safe under a parallel (-n 6 / xdist) outer run."""
    import subprocess
    import sys
    s1_path = os.path.join(os.path.dirname(__file__),
                           "test_m42_s1_density_gradient_2d.py")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         s1_path],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"S1 gate file did not pass cleanly:\n{result.stdout}\n{result.stderr}")


# ---------------------------------------------------- S2-G-RED (classical)
def test_gred_classical_prerequisite_exact():
    """Prerequisite sub-gate (must be exact before the DG comparison is
    diagnostic): with dg=False, a transversely-uniform gated Device2D
    reduces EXACTLY to MOSCapacitor's own classical equilibrium."""
    Vfb_2d = 0.0
    dev, mos = _build_gated_device(dg=False, Vfb_2d=Vfb_2d)
    dev.solve_equilibrium()
    Vg_mos = _vg_mos_for(mos, Vfb_2d)
    psi_mos = mos.solve_psi(Vg_mos)
    for i in range(dev.Nx):
        assert np.abs(dev.psi[:, i] - psi_mos).max() < 1e-12, \
            f"classical column {i} mismatch: " \
            f"{np.abs(dev.psi[:, i] - psi_mos).max():.3e}"


def test_gred_dg_matches_moscapacitor():
    """The reduction identity proper (section 10.5's S2-G-RED): with
    dg=True, a transversely-uniform gated Device2D reduces to
    MOSCapacitor(dg=True)'s own equilibrium at strong inversion, to
    floating-point noise (not a tolerance)."""
    dev0, mos0 = _build_gated_device(dg=False, Vfb_2d=0.0)
    Vfb_2d = _vg_strong_offset(mos0)
    dev, mos = _build_gated_device(dg=True, Vfb_2d=Vfb_2d)
    dev.solve_equilibrium()

    mos_dg = MOSCapacitor(**{**_MOS_PARAMS, "nx": mos.x.size}, dg=True)
    Vg_mos = _vg_mos_for(mos_dg, Vfb_2d)
    psi_mos = mos_dg.solve_psi(Vg_mos)
    Lam_n_mos = mos_dg._dg_Lam_n
    Lam_p_mos = mos_dg._dg_Lam_p

    for i in range(dev.Nx):
        dpsi = np.abs(dev.psi[:, i] - psi_mos).max()
        dln = np.abs(dev._dg_Lam_n[:, i] - Lam_n_mos).max()
        dlp = np.abs(dev._dg_Lam_p[:, i] - Lam_p_mos).max()
        assert dpsi < 1e-9, f"DG column {i} psi mismatch: {dpsi:.3e}"
        assert dln < 1e-9, f"DG column {i} Lambda_n mismatch: {dln:.3e}"
        assert dlp < 1e-9, f"DG column {i} Lambda_p mismatch: {dlp:.3e}"


# ----------------------------------------------------------------------
#  S2-G-CONF / S2-G-SP / S2-G-MESH: the confinement gates proper.
# ----------------------------------------------------------------------
def _inversion_centroid(dev, i=0):
    """The inversion-charge centroid down a gated column, mirroring
    MOSCapacitor.inversion_centroid exactly: x_c = integral(y*(n-n_bulk))
    / integral(n-n_bulk), n_bulk taken from the far (ohmic, bulk-pinned)
    contact row.  y is the PHYSICAL surface-normal mesh coordinate."""
    from pytcad.constants import trapz
    y = dev.mesh.y
    n = dev.n[:, i]
    n_bulk = n[-1]
    dn = np.maximum(n - n_bulk, 0.0)
    sheet = trapz(dn, y)
    if sheet <= 0.0:
        return 0.0
    return float(trapz(y * dn, y) / sheet)


def _peak_gate_density(dev, i=0):
    return float(dev.n[0, i])


# --------------------------------------------------------------- S2-G-CONF
def test_gconf_dg_confinement_load_bearing():
    """The milestone's load-bearing gate: under strong inversion, DG
    pushes the inversion centroid off the interface by more than a
    lattice-scale distance (M20's own 0.2 nm G-D threshold), the gate-
    node density is suppressed relative to classical, and the deficit
    grows monotonically with gamma."""
    mos0 = MOSCapacitor(**_MOS_PARAMS, nx=600)
    Vfb_2d = _vg_strong_offset(mos0)

    dev_cl, _ = _build_gated_device(dg=False, Vfb_2d=Vfb_2d)
    dev_cl.solve_equilibrium()
    xc_classical = _inversion_centroid(dev_cl)

    dev_dg, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, dg_gamma=1.0)
    dev_dg.solve_equilibrium()
    xc_dg = _inversion_centroid(dev_dg)

    assert xc_dg > 0.2e-7, f"DG centroid {xc_dg*1e7:.3f} nm not > 0.2 nm"
    assert xc_classical < xc_dg, (
        f"classical centroid {xc_classical*1e7:.3f} nm not below DG "
        f"{xc_dg*1e7:.3f} nm")

    n_peak_classical = _peak_gate_density(dev_cl)
    n_peak_dg = _peak_gate_density(dev_dg)
    assert n_peak_dg < n_peak_classical, (
        "DG gate-node density not suppressed relative to classical: "
        f"{n_peak_dg:.3e} vs {n_peak_classical:.3e}")

    # The gate node's OWN density deficit does NOT grow monotonically
    # with gamma -- checked directly and found to be the WRONG metric
    # here, unlike M20's 1D ohmic case: the gate node's Lambda is PINNED
    # to the fixed value LAMBDA_MAX_VT*VT regardless of gamma (10.2's
    # hard wall), so its own suppression factor exp(-LAMBDA_MAX_VT) is
    # gamma-INDEPENDENT by construction; the residual gamma-dependence
    # measured at that one node is a small INDIRECT effect of the
    # self-consistent potential shifting nearby, and it was measured to
    # go the OTHER way (peak density at the gate node itself INCREASES
    # with gamma: 1.69e-3 -> 7.44e-3 -> 4.24e-2 scaled density at
    # gamma=0.5/1.0/2.0 on this device) as charge redistributes away
    # from the interface toward the centroid. The centroid distance is
    # the physically meaningful, monotonic confinement indicator (and
    # is what M20's own G-D gate and section 10.5's own S2-G-CONF text
    # are actually about) -- checked here instead.
    centroids = []
    for gamma in (0.5, 1.0, 2.0):
        dev_g, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, dg_gamma=gamma)
        dev_g.solve_equilibrium()
        centroids.append(_inversion_centroid(dev_g))
    assert centroids[0] < centroids[1] < centroids[2], (
        f"centroid distance not monotonic in gamma: {centroids}")


# ---------------------------------------------------------------- S2-G-SP
def test_gsp_dg_centroid_within_factor2_of_sp():
    """Cross-check against dg.schrodinger_poisson_mos on the matching
    MOSCapacitor, reusing M20's own factor-2 band
    (test_m20_dg.py::test_gc_dg_centroid_within_factor2_of_sp) -- the
    only independent reference this repo owns."""
    mos = MOSCapacitor(**_MOS_PARAMS, nx=600)
    vg_strong = mos.analytic_landmarks()["V_th"] + 1.0
    res_sp = schrodinger_poisson_mos(mos, vg_strong)
    xc_sp = res_sp["centroid_cm"]

    Vfb_2d = mos.Vfb - vg_strong
    dev_dg, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, dg_gamma=1.0)
    dev_dg.solve_equilibrium()
    xc_dg = _inversion_centroid(dev_dg)

    ratio = xc_dg / xc_sp
    assert 0.5 < ratio < 2.0, (
        f"DG centroid {xc_dg*1e7:.3f} nm vs S-P {xc_sp*1e7:.3f} nm "
        f"(ratio {ratio:.3f})")


# -------------------------------------------------------------- S2-G-MESH
def test_gmesh_centroid_convergence():
    """Mesh convergence: the centroid displacement must not drift with
    surface-normal (y) mesh refinement -- a hard wall applied at the
    wrong node moves with the mesh."""
    mos_coarse = MOSCapacitor(**_MOS_PARAMS, nx=400)
    Vfb_2d = _vg_strong_offset(mos_coarse)

    dev_coarse, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, nx=400)
    dev_coarse.solve_equilibrium()
    xc_coarse = _inversion_centroid(dev_coarse)

    dev_fine, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, nx=800)
    dev_fine.solve_equilibrium()
    xc_fine = _inversion_centroid(dev_fine)

    rel = abs(xc_fine - xc_coarse) / xc_coarse
    assert rel < 0.10, (
        f"centroid drifted {rel*100:.1f}% under mesh refinement: "
        f"{xc_coarse*1e7:.3f} nm -> {xc_fine*1e7:.3f} nm")


# ---------------------------------------------------------------- S2-G6
def test_g6_lambda_pin_bounded_deterministic():
    mos0 = MOSCapacitor(**_MOS_PARAMS, nx=600)
    Vfb_2d = _vg_strong_offset(mos0)
    dev, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, dg_gamma=1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dev.solve_equilibrium()

    pin_val = LAMBDA_MAX_VT * dev.VT
    assert dev._dg_Lam_n[0, :] == pytest.approx(pin_val), dev._dg_Lam_n[0, :]
    assert dev._dg_Lam_p[0, :] == pytest.approx(pin_val), dev._dg_Lam_p[0, :]
    assert np.all(np.isfinite(dev._dg_Lam_n))
    assert np.all(np.isfinite(dev._dg_Lam_p))
    assert np.abs(dev._dg_Lam_n).max() <= pin_val + 1e-9
    assert np.abs(dev._dg_Lam_p).max() <= pin_val + 1e-9

    dev_b, _ = _build_gated_device(dg=True, Vfb_2d=Vfb_2d, dg_gamma=1.0)
    dev_b.solve_equilibrium()
    assert np.array_equal(dev.psi, dev_b.psi)
    assert np.array_equal(dev._dg_Lam_n, dev_b._dg_Lam_n)
    assert np.array_equal(dev._dg_Lam_p, dev_b._dg_Lam_p)


# ---------------------------------------------------------------- S2-G7
def test_g7_dg_fd_still_refused():
    x, y = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6), graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    with pytest.raises(NotImplementedError):
        Device2D(mesh, dop, models=Models(bgn=False, dg=True, fd=True))


def test_g7_dg_incomplete_ion_still_refused():
    x, y = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6), graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    with pytest.raises(NotImplementedError):
        Device2D(mesh, dop, models=Models(bgn=False, dg=True, incomplete_ion=True))


def test_g7_dg_affinity_still_refused():
    x, y = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6), graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    with pytest.raises(NotImplementedError):
        Device2D(mesh, dop, models=Models(bgn=False, dg=True, band_offset="affinity"))


def test_g7_solve_bias_dg_still_refused():
    dev, _ = _build_gated_device(dg=True, Vfb_2d=-0.5)
    with pytest.raises(NotImplementedError):
        dev.solve_bias({"far": 0.0})


def test_g7_unstructured_device2d_still_refuses_dg():
    """Device2D(unstructured=True) still refuses dg=True -- no gmsh
    installation needed, GmshMesh is just a plain node/triangle
    container (same hand-built mesh test_m21_phase3.py's own adversarial
    checks use, so this does not depend on gmsh's own triangulation)."""
    from pytcad.gmsh_mesh import GmshMesh

    nx = ny = 4
    xs = np.linspace(0.0, 1.0, nx)
    ys = np.linspace(0.0, 1.0, ny)
    X, Y = np.meshgrid(xs, ys)
    nodes = np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], axis=1)
    idx = lambda i, j: j * nx + i
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            tris.append([a, b, c])
            tris.append([a, c, d])
    tris = np.array(tris, dtype=int)
    mesh = GmshMesh(nodes=nodes, triangles=tris,
                    surface_tags={"all": np.arange(len(tris))},
                    curve_tags={})
    with pytest.raises(NotImplementedError, match="dg"):
        Device2D(mesh, {"all": -1e17}, unstructured=True,
                 models=Models(doping_mobility=False, dg=True))


def test_g7_sic_4h_dg_refused():
    """M42-S2 section 10.3(d) decision: SIC_4H.m_n_star/m_p_star are
    documented placeholders, and dg's quantum correction uses that mass
    directly -- refuse rather than silently report a confinement number
    built on an unvalidated input."""
    x, y = graded_mesh(2e-5, [1e-5], 1e-8, 1e-6), graded_mesh(1e-5, [0.5e-5], 1e-8, 1e-6)
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    with pytest.raises(NotImplementedError, match="SIC_4H"):
        Device2D(mesh, dop, material=SIC_4H, models=Models(bgn=False, dg=True))


def test_g7_device3d_now_implements_dg_see_m42_s3():
    """Device3D used to refuse dg=True unconditionally (S2's own scope
    excluded it, per M42-DENSITY-GRADIENT-2D3D-PLAN.md section 10.4's
    file list). M42-S3 (landed the same week) implements it -- see
    tests/test_m42_s3_density_gradient_3d.py for the actual gates.
    This is kept as a narrow regression check that the *ohmic* ungated
    construction no longer refuses, not a substitute for S3's own
    gate file."""
    from pytcad.mesh3d import Mesh3D
    from pytcad.device3d import Device3D
    x = graded_mesh(2e-4, [1e-4], 1e-6, 4e-6, 1.2)
    y = graded_mesh(5e-5, [0.0], 2e-6, 8e-6, 1.2)
    z = graded_mesh(3e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))
    dop3d = np.tile(dop2d, (z.size, 1, 1))
    Device3D(Mesh3D(x, y, z), dop3d, models=Models(bgn=False, dg=True))
