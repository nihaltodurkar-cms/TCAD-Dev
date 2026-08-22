"""2D validation suite -- mirrors tests/test_validation.py's structure.

Every test compares the 2D solver against something independent: the
existing validated 1D solver (on a y-invariant structure), a finite
difference check, or an analytic formula.

    python -m pytest tests/test_validation_2d.py -q
    python tests/test_validation_2d.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np

from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D, control_volume_widths, check_mesh2d
from pytcad import Device1D, Models as Models1D, MOSCapacitor
from pytcad.device2d import Device2D, DirichletBC, GateBC
from pytcad.device import Models
from pytcad.mosfet import mosfet_doping, build_mosfet, id_vg_sweep

warnings.simplefilter("ignore")


def test_mesh2d_shapes_and_indexing():
    x = np.linspace(0.0, 1.0, 5)
    y = np.linspace(0.0, 2.0, 4)
    m = Mesh2D(x, y)
    assert m.Nx == 5 and m.Ny == 4 and m.N == 20
    assert m.hx.shape == (4,) and m.hy.shape == (3,)
    assert m.dVx.shape == (5,) and m.dVy.shape == (4,)
    assert m.dV.shape == (20,)
    # row-major: idx(i,j) = j*Nx + i
    assert m.idx(0, 0) == 0
    assert m.idx(4, 0) == 4
    assert m.idx(0, 1) == 5
    assert m.idx(2, 3) == 3 * 5 + 2


def test_control_volume_widths_sum_to_length():
    h = np.array([0.5, 0.5, 1.0])
    dv = control_volume_widths(h)
    assert dv.shape == (4,)
    assert abs(dv.sum() - h.sum()) < 1e-14
    # uniform interior spacing -> uniform interior width
    assert abs(dv[1] - 0.5) < 1e-14


def test_mesh2d_area_is_outer_product():
    x = np.array([0.0, 1.0, 3.0])
    y = np.array([0.0, 2.0])
    m = Mesh2D(x, y)
    dvx = control_volume_widths(m.hx)
    dvy = control_volume_widths(m.hy)
    expected = np.outer(dvy, dvx).ravel()
    assert np.allclose(m.dV, expected)


def test_check_mesh2d_reports_finite_ratio():
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    y = graded_mesh(1e-4, [0.0], 1e-8, 1e-6, 1.12)
    m = Mesh2D(x, y)
    doping = np.where(x[None, :] < 1e-4, -1e17, 1e17) * np.ones((m.Ny, 1))
    ratio = check_mesh2d(m, doping, verbose=False)
    assert np.isfinite(ratio) and ratio > 0.0


def test_equilibrium_2d_reduces_to_1d():
    """A uniformly-in-y block with contacts only on the left/right x faces
    must give a y-independent potential matching the 1D equilibrium solver
    on the equivalent 1D structure, to numerical tolerance."""
    L = 2e-4
    xj = 1e-4
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    # NOTE: the brief's literal call graded_mesh(5e-5, [], ...) hits a
    # pre-existing bug in mesh.py's graded_mesh (np.min on an empty
    # x_focus array raises ValueError) -- graded_mesh is off-limits to
    # modify for this task. Using [0.0] instead follows the same
    # precedent already used above in test_check_mesh2d_reports_finite_ratio
    # (grading from the y=0 edge, no real junction to focus on) and is
    # physically equivalent since 0.0 is already always an endpoint node.
    y = graded_mesh(5e-5, [0.0], 1e-7, 1e-5, 1.15)

    dop1d = np.where(x < xj, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))   # (Ny, Nx), same profile every row

    mesh = Mesh2D(x, y)
    dev2 = Device2D(mesh, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev2.solve_equilibrium()

    dev1 = Device1D(x, dop1d, models=Models1D(bgn=False))
    dev1.solve_equilibrium()

    psi2d = dev2.psi_V   # (Ny, Nx)
    assert np.allclose(psi2d, psi2d[0:1, :], atol=1e-9), "solution must be y-independent"
    assert np.allclose(psi2d[0, :], dev1.psi_V, atol=1e-6), \
        f"max diff {np.abs(psi2d[0,:]-dev1.psi_V).max():.3e}"


def test_dd_jacobian_matches_finite_differences():
    """The analytic 2D Newton Jacobian must match a numerical one --
    same check as test_jacobian_matches_finite_differences in 1D, run
    first whenever the 2D physics changes."""
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    # NOTE: [0.0] instead of the brief's literal [] -- see the comment in
    # test_equilibrium_2d_reduces_to_1d above; graded_mesh([]) hits a
    # pre-existing np.min-on-empty-array bug in mesh.py, which is
    # off-limits to modify for this task.
    y = graded_mesh(5e-5, [0.0], 2e-7, 1e-5, 1.2)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))

    mesh = Mesh2D(x, y)
    dev = Device2D(mesh, dop2d, models=Models(bgn=False))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev.solve_equilibrium()

    rng = np.random.default_rng(0)
    psi = dev.psi + 0.02 * rng.standard_normal((mesh.Ny, mesh.Nx))
    n = dev.n * (1 + 0.01 * rng.standard_normal((mesh.Ny, mesh.Nx)))
    p = dev.p * (1 + 0.01 * rng.standard_normal((mesh.Ny, mesh.Nx)))

    F, J, *_ = dev._residual_jacobian(psi, n, p, {"left": 0.3, "right": 0.0})
    # NOTE: J.toarray() would densify the full (3N, 3N) Jacobian -- at this
    # mesh scale that measured ~2.6GB peak RSS, which can OOM on
    # constrained environments. Only the 30 sampled columns are actually
    # needed, so keep J sparse (CSC, for fast column slicing) and extract
    # just those columns instead.
    Jc = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(3 * dev.N, 30, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        psi2 = u2[0::3].reshape(mesh.Ny, mesh.Nx)
        n2 = u2[1::3].reshape(mesh.Ny, mesh.Nx)
        p2 = u2[2::3].reshape(mesh.Ny, mesh.Nx)
        F2, *_ = dev._residual_jacobian(psi2, n2, p2, {"left": 0.3, "right": 0.0})
        an = np.asarray(Jc[:, c].todense()).ravel()
        worst = max(worst, np.abs((F2.ravel() - F.ravel()) / step - an).max()
                    / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"2D Jacobian error {worst:.2e}"


def test_bias_2d_reduces_to_1d():
    """A y-invariant p-n slab under forward bias must match the 1D
    drift-diffusion solver's current and band profile."""
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    # NOTE: [0.0] instead of the brief's literal [] -- same reason as above.
    y = graded_mesh(5e-5, [0.0], 1e-7, 1e-5, 1.15)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))

    mesh = Mesh2D(x, y)
    dev2 = Device2D(mesh, dop2d, models=Models(bgn=False))
    dev2.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev2.solve_equilibrium()
    dev2.solve_bias({"left": 0.5, "right": 0.0})

    dev1 = Device1D(x, dop1d, models=Models1D(bgn=False))
    dev1.solve_equilibrium()
    dev1.solve_bias([0.5, 0.0])
    J1, _ = dev1.current_density()

    Jtot_2d = dev2.Jn_x + dev2.Jp_x            # (Ny, Nx-1), should be ~y-independent
    assert np.allclose(Jtot_2d, Jtot_2d[0:1, :], rtol=1e-3, atol=1e-6)
    assert abs(Jtot_2d.mean() - J1) / abs(J1) < 0.02, \
        f"2D current {Jtot_2d.mean():.4e} vs 1D {J1:.4e}"


def test_gate_bc_is_mesh_independent_in_x():
    """The GateBC Robin flux must be weighted by the same dVx[i]
    control-volume face length as every other term in the residual, or
    the gate's coupling strength drifts with lateral mesh refinement (a
    code-review finding: the residual and Jacobian entries were being
    added as bare bc.kappa * (...), with no face-length weight at all).

    Build a laterally-uniform MOS-like slab: a gate strip covering the
    entire top row (j=0) and a body contact covering the entire bottom
    row (j=Ny-1), with no left/right contacts -- the box-integration
    assembly's implicit zero-flux Neumann condition at those domain edges
    is exact here because the structure has no lateral variation. Refining
    Nx 2x must leave the (laterally uniform) surface band-bending under
    the gate unchanged to a tight tolerance; before the dVx[i] weight was
    added this potential drifted with Nx instead of converging.
    """
    y = graded_mesh(2e-4, [0.0], 2e-7, 1e-5, 1.2)   # fine grading at the surface
    Nsub = -1e17           # uniform p-type body
    tox_cm, Vfb, Vg = 5e-7, -0.9, 1.0

    def surface_psi(Nx):
        x = np.linspace(0.0, 1e-4, Nx)
        mesh = Mesh2D(x, y)
        doping = np.full((mesh.Ny, mesh.Nx), Nsub)
        dev = Device2D(mesh, doping, models=Models(bgn=False))
        dev.add_gate("gate", i=list(range(mesh.Nx)), j=[0] * mesh.Nx,
                     tox_cm=tox_cm, Vfb=Vfb, Vg=Vg)
        dev.add_contact("body", i=list(range(mesh.Nx)), j=[mesh.Ny - 1], V=0.0)
        dev.solve_equilibrium()
        psi_surf = dev.psi_V[0, :]
        assert np.allclose(psi_surf, psi_surf[0], atol=1e-9), \
            "structure is laterally uniform -- surface potential must be too"
        return psi_surf[0]

    psi_coarse = surface_psi(6)
    psi_fine = surface_psi(12)
    rel_err = abs(psi_fine - psi_coarse) / abs(psi_coarse)
    assert rel_err < 1e-3, \
        (f"gate surface potential is mesh-dependent: {psi_coarse:.6f} V "
         f"(Nx=6) vs {psi_fine:.6f} V (Nx=12), rel err {rel_err:.2e}")


def test_terminal_current_conserves_charge():
    """Sum of terminal currents into a two-terminal resistor must be ~0.

    Uses a narrow top contact and a full-width bottom contact, so current
    entering the top contact spreads laterally before reaching the
    bottom -- the top contact's control volumes see a real lateral (x-
    direction) seam flux in addition to the vertical flux directly
    beneath them. The old edge-only extraction ignored that seam and
    under-counted the top terminal's current (measured ~6.7% error on a
    similar structure); the residual-based extraction picks up every
    edge touching the contact automatically, so conservation should hold
    to a much tighter tolerance once fixed.
    """
    x = np.linspace(0.0, 4e-4, 11)
    y = np.linspace(0.0, 2e-4, 9)
    mesh = Mesh2D(x, y)
    doping = np.full((mesh.Ny, mesh.Nx), 1e17)   # uniform n-type resistor

    dev = Device2D(mesh, doping, models=Models(bgn=False))
    top_i = list(range(3, 7))                    # narrow strip, not full width
    dev.add_contact("top", i=top_i, j=[0] * len(top_i), V=0.0)
    dev.add_contact("bottom", i=list(range(mesh.Nx)), j=[mesh.Ny - 1] * mesh.Nx, V=0.0)
    dev.solve_equilibrium()
    dev.solve_bias({"top": 0.05, "bottom": 0.0})

    I_top = dev.terminal_current("top")
    I_bottom = dev.terminal_current("bottom")
    rel_err = abs(I_top + I_bottom) / max(abs(I_top), abs(I_bottom))
    assert rel_err < 1e-6, \
        (f"terminal currents don't conserve charge: I_top={I_top:.6e} A/cm, "
         f"I_bottom={I_bottom:.6e} A/cm, rel err {rel_err:.2e}")


def test_mosfet_doping_sign_and_shape():
    Lsd, Lg, depth = 3e-5, 2e-5, 2e-5
    x = graded_mesh(2 * Lsd + Lg, [Lsd, Lsd + Lg], 2e-7, 1e-6, 1.15)
    y = graded_mesh(depth, [0.0], 5e-8, 1e-6, 1.15)
    mesh = Mesh2D(x, y)

    doping, Ntotal = mosfet_doping(mesh, Lsd, Lg, Na=1e17, Nsd_peak=1e19,
                                    sigma_y=5e-6, sigma_lat=3e-6)
    assert doping.shape == (mesh.Ny, mesh.Nx)
    assert Ntotal.shape == (mesh.Ny, mesh.Nx)

    i_src = np.argmin(np.abs(x - 0.0))
    i_chan = np.argmin(np.abs(x - (Lsd + Lg / 2)))
    i_drn = np.argmin(np.abs(x - (2 * Lsd + Lg)))
    # n-type (positive) right at the source/drain contacts, at the surface
    assert doping[0, i_src] > 0
    assert doping[0, i_drn] > 0
    # p-type (negative) in the middle of the channel, at the surface
    assert doping[0, i_chan] < 0
    # deep into the substrate, doping is just the uniform p background
    assert abs(doping[-1, i_chan] - (-1e17)) / 1e17 < 1e-3
    # Ntotal is everywhere >= |net doping| (sum of magnitudes, not net)
    assert np.all(Ntotal >= np.abs(doping) - 1e-6)


def _build_test_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=1e17, tox_cm=5e-7):
    # Lg=600nm, sigma_lat=10nm (not the original 200nm/30nm): with the
    # original geometry the source/drain lateral erfc tails cross zero net
    # doping ~70nm inside each gate edge (2.326*sigma_lat, see the code
    # review that flagged this), eating 140nm out of a 200nm gate and
    # leaving an effective p-type channel of only ~60nm -- short enough
    # that the "device" never really turns off (on/off ratio ~10x over a
    # 2V gate sweep, no visible subthreshold knee). Lg=600nm/sigma_lat=10nm
    # gives a junction depth of ~23nm/side, an effective channel of
    # ~550nm, and a clean off state (see test_mosfet_vth_matches_moscap_landmark).
    return build_mosfet(Lg=Lg, Lsd=Lsd, depth=depth, Na=Na, Nsd_peak=1e19,
                        tox_cm=tox_cm, gate="n+poly", sigma_y=5e-6,
                        sigma_lat=1e-6, nx=90, ny=50)


def _extract_vth_max_gm(Vg_list, Id, Vds):
    """Standard max-transconductance Vth extraction: fit the Id-Vg tangent
    line at the point of peak dId/dVg, find where it crosses Id=0, and
    apply the textbook linear-region correction Vth = Vg_at_max_gm -
    Id/gm - Vds/2 (the channel potential varies from 0 at the source to
    Vds at the drain, so the "effective" Vds seen by the simple
    Id=mu*Cox*(W/L)*(Vgs-Vth)*Vds formula is really Vgs-Vth-Vds/2; at
    Vds=0.05V this is a small ~0.025V correction but a real one).

    More robust than fitting a line deep into strong inversion, where
    mobility/series-resistance roll-off visibly bends the curve and biases
    a deep-Vg linear fit low (verified on this device: dId/dVg drops ~5%
    from the knee out to Vg=1.5V, and a deep-range fit gives a Vth several
    hundred mV more negative than the max-gm tangent)."""
    Vg_list = np.asarray(Vg_list, dtype=float)
    Id = np.asarray(Id, dtype=float)
    gm = np.gradient(Id, Vg_list)
    i = np.argmax(gm)
    return Vg_list[i] - Id[i] / gm[i] - Vds / 2.0


def test_mosfet_vth_matches_moscap_landmark():
    """Away from the junctions, the vertical cut under the gate is
    electrically a MOS-C: the Id-Vg curve must show genuine gate-controlled
    switching (a real off state, not just a weak on/off ratio at two
    arbitrary points) and the extracted threshold must land close to
    MOSCapacitor's analytic landmark for the same channel doping/oxide.

    Tolerance reasoning: a code-review round on this test (after the
    Lg/sigma_lat geometry fix documented in _build_test_mosfet's comment)
    found the *residual* ~0.36V gap between the extracted Vth and the
    landmark was not "expected landmark-vs-simulation bias" as first
    assumed here, but a real bug in Device2D's gate Robin BC: psi in this
    codebase is intrinsic-referenced (see _ohmic_values), so the neutral
    p-type bulk under the gate sits at psi_b*VT = -phi_F, not 0V -- the
    validated 1D moscap.py reference includes this term
    (`... - (psi[0] - self.psi_b)`) but Device2D's gate BC (both copies,
    in _residual_jacobian_poisson and _residual_jacobian) omitted it
    entirely, applying Vg relative to the wrong potential reference. Fixed
    in device2d.py by adding a per-node psi_b_local =
    arcsinh(C/(2*nie_s)) term to both gate BC residuals (Jacobian
    unchanged -- psi_b_local doesn't depend on psi). After that fix the
    extracted Vth lands ~0.03-0.06V from the landmark (see numbers in the
    task report), so 0.1V is a tight-but-real tolerance: per the review,
    a much wider tolerance (the original 0.5V) is wide enough to hide a
    normally-off-vs-depletion-mode sign error and isn't actually
    diagnostic.
    """
    Na, tox_cm = 1e17, 5e-7
    dev = _build_test_mosfet(Na=Na, tox_cm=tox_cm)
    Vg_list = np.linspace(-1.0, 1.0, 21)
    Vds = 0.05
    Id = id_vg_sweep(dev, Vg_list, Vds=Vds, verbose=False)

    mos = MOSCapacitor(Nsub=-Na, tox_cm=tox_cm, gate="n+poly")
    Vth_landmark = mos.analytic_landmarks()["V_th"]
    Vth_extracted = _extract_vth_max_gm(Vg_list, Id, Vds)

    # genuine gate-controlled switching: off state (Vg=-1.0V) is ~11
    # orders of magnitude below on state (Vg=+1.0V), not a razor-thin 10x
    on_current, off_current = Id[-1], Id[0]
    assert on_current > 1e6 * abs(off_current), \
        f"on/off ratio too small: on={on_current:.3e} off={off_current:.3e}"
    assert -0.5 < Vth_landmark < 1.5, Vth_landmark
    assert abs(Vth_extracted - Vth_landmark) < 0.1, \
        (f"Vth_extracted={Vth_extracted:.4f} V vs "
         f"Vth_landmark={Vth_landmark:.4f} V, diff too large")

    # Subthreshold swing: design spec section 4 calls for ~60-120 mV/decade
    # at 300 K for an undegraded long-channel device (the thermal limit is
    # VT*ln(10) = 59.5 mV/decade). Measured ~59.6 mV/decade on this device;
    # the lower bound is set a touch below that physical floor rather than
    # at the spec's 60 to leave a small margin, since SS can never actually
    # beat the thermal limit but numerical noise could nudge the measured
    # max slightly either way.
    d = np.diff(np.log10(np.abs(Id))) / np.diff(Vg_list)
    SS = 1000.0 / d.max()          # mV/decade
    assert 55.0 < SS < 120.0, SS


def test_id_vg_monotonic_above_threshold():
    dev = _build_test_mosfet()
    Vg_list = np.linspace(0.3, 1.5, 13)
    Id = id_vg_sweep(dev, Vg_list, Vds=0.05, verbose=False)
    assert np.all(np.diff(Id) > 0), Id


def test_mosfet_mesh_independence():
    Id_coarse = id_vg_sweep(_build_test_mosfet(), [1.0], Vds=0.05, verbose=False)[0]
    dev_fine = build_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=1e17,
                            Nsd_peak=1e19, tox_cm=5e-7, sigma_y=5e-6,
                            sigma_lat=1e-6, nx=180, ny=100)
    Id_fine = id_vg_sweep(dev_fine, [1.0], Vds=0.05, verbose=False)[0]
    assert abs(Id_fine - Id_coarse) / abs(Id_fine) < 0.10, (Id_coarse, Id_fine)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for f in fns:
        try:
            f()
            print(f"  PASS  {f.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {f.__name__}: {e}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
