"""Automated tests for the 3D 4H-SiC vertical power MOSFET reference
example (pytcad.sic_vmosfet, examples/07_3d_sic_power_mosfet.py).

Mirrors tests/test_validation_3d.py's house convention: every physics
claim is checked against something independent (an FD-Jacobian spot
check, a charge-conservation identity, or a documented physical trend),
not merely "it ran without crashing." Meshes here are deliberately
SMALL (not the full adaptive mesh the example itself uses) -- these are
fast correctness gates for the geometry/physics wiring, not a
regenerated version of the example's own expensive adaptive run.

    python -m pytest tests/test_sic_vmosfet.py -q
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad.mesh import uniform_mesh
from pytcad.mesh3d import Mesh3D, check_mesh3d
from pytcad.device import Models, NewtonOptions
from pytcad.materials import SIC_4H
from pytcad.sic_vmosfet import (
    SiCVMOSFETParams, sic_vmosfet_doping, build_sic_vmosfet,
)

warnings.simplefilter("ignore")

P = SiCVMOSFETParams()


def _small_mesh(nx=10, ny=9, nz=5):
    x = uniform_mesh(P.Lcell, nx)
    y = uniform_mesh(P.depth, ny)
    z = uniform_mesh(P.W, nz)
    return Mesh3D(x, y, z)


# ---------------------------------------------------------------- geometry
def test_params_reject_inconsistent_lateral_ordering():
    """Lbt < Ln < Lch < Lcell is a load-bearing geometric invariant (the
    doping builder's erfc-rolloff regions assume this ordering) -- must
    fail loudly, not silently build a nonsensical structure."""
    with pytest.raises(ValueError):
        SiCVMOSFETParams(Ln=1e-4, Lch=5e-5)   # Ln > Lch, invalid


def test_doping_shape_and_dominant_sign_per_region():
    """Net doping must have Device3D's expected (Nz,Ny,Nx) shape, and
    each named physical region must show the dopant sign the geometry
    docstring claims -- the actual gate: a mislabeled region here would
    build a device with completely wrong electrical behavior while
    still solving without error."""
    mesh = _small_mesh()
    dop, Ntot = sic_vmosfet_doping(mesh, P)
    assert dop.shape == (mesh.Nz, mesh.Ny, mesh.Nx)
    assert Ntot.shape == dop.shape
    assert np.all(Ntot >= np.abs(dop) - 1e-6)   # Ntot >= |net| always

    ix = lambda x_cm: int(np.argmin(np.abs(mesh.x - x_cm)))
    iy = lambda y_cm: int(np.argmin(np.abs(mesh.y - y_cm)))
    iz_mid = mesh.Nz // 2   # away from the z=0 body-tie notch

    # N+ source: surface, x well inside [0, Ln], away from the notch.
    assert dop[iz_mid, 0, ix(P.Ln * 0.5)] > 1e18

    # P-body: a bit deeper than the source, x inside [Ln, Lch].
    assert dop[iz_mid, iy(P.y_body * 0.6), ix((P.Ln + P.Lch) / 2)] < -1e15

    # N- drift, exposed at the surface in the JFET region (x > Lch).
    surf_jfet = dop[iz_mid, 0, ix((P.Lch + P.Lcell) / 2)]
    assert 0.5 * P.Nd_drift < surf_jfet < 2.0 * P.Nd_drift

    # N+ substrate/drain, at the bottom.
    assert dop[iz_mid, -1, ix(P.Ln * 0.5)] > 1e18

    # P+ body-tie: surface, x inside [0, Lbt], INSIDE the notch (z small).
    assert dop[0, 0, ix(P.Lbt * 0.5)] < -1e18

    # Outside the notch (z well past Wbt) the same (x, y) must be N+
    # source instead -- confirms the notch is genuinely finite in z,
    # not (by a mistake) applied for the whole stripe length.
    assert dop[mesh.Nz - 1, 0, ix(P.Lbt * 0.5)] > 1e18


# ---------------------------------------------------------------- mesh
def test_mesh_sanity_check_runs_and_reports_finite_ratio():
    mesh = _small_mesh()
    dop, _ = sic_vmosfet_doping(mesh, P)
    ratio = check_mesh3d(mesh, dop, eps_r=SIC_4H.eps_r, T=P.T, verbose=False)
    assert np.isfinite(ratio) and ratio > 0.0


# ---------------------------------------------------------------- physics setup
def test_build_succeeds_with_the_supported_model_combination():
    mesh = _small_mesh()
    dev = build_sic_vmosfet(mesh, P, models=Models(
        fd=True, srh=True, auger=True, bgn=True, doping_mobility=True))
    assert set(dev.bcs.keys()) == {"source", "gate", "drain"}
    assert dev.mat is SIC_4H


@pytest.mark.parametrize("flag,kwargs", [
    ("field_mobility", dict(field_mobility=True)),
    ("impact", dict(impact=True)),
    ("btbt", dict(btbt=True)),
    ("dg", dict(dg=True)),
    ("incomplete_ion", dict(incomplete_ion=True)),
    ("S_n", dict(S_n=1e4)),
])
def test_unsupported_3d_models_are_refused_not_silently_ignored(flag, kwargs):
    """Device3D's own house convention: an unimplemented-for-3D physics
    flag must raise NotImplementedError at construction, never solve
    silently as if the flag had no effect. Confirmed directly against
    device3d.py's constructor guards before writing this example (see
    the module docstring / README capability matrix) -- this test
    guards against that inventory going stale."""
    mesh = _small_mesh(nx=4, ny=4, nz=3)
    with pytest.raises(NotImplementedError):
        build_sic_vmosfet(mesh, P, models=Models(**kwargs))


def test_surface_mobility_is_a_documented_silent_gap_not_a_claimed_feature():
    """Found during investigation, not assumed: Device3D has NO guard
    against Models(surface_mobility=True) at all (device2d.py reads the
    flag; device3d.py never checks it), so it silently builds and
    solves as if the flag were off. This test pins that CURRENT
    behavior down (construction does not raise) so a future fix that
    adds the missing guard is a deliberate, visible change to this
    test, not a silent behavior flip -- and so this example's own
    choice to leave the flag at its False default is not mistaken for
    "untested" but a documented avoidance of a real gap (see the
    example script's own comment and README capability matrix)."""
    mesh = _small_mesh(nx=4, ny=4, nz=3)
    dev = build_sic_vmosfet(mesh, P, models=Models(surface_mobility=True))
    assert dev is not None   # did NOT raise -- the gap, pinned down


# ---------------------------------------------------------------- convergence
def test_fd_jacobian_matches_finite_differences():
    """Same check as test_validation_3d.py's own Device3D gate, run on
    this structure specifically -- a heterostructure-free but
    materially different (4H-SiC, degenerate FD-regime doping, a real
    gate BC) fixture from what that file already covers."""
    mesh = _small_mesh(nx=8, ny=7, nz=4)
    dev = build_sic_vmosfet(mesh, P, models=Models(fd=True))
    dev.solve_equilibrium(NewtonOptions(max_iter=80))

    rng = np.random.default_rng(0)
    shape = (mesh.Nz, mesh.Ny, mesh.Nx)
    psi = dev.psi + 0.02 * rng.standard_normal(shape)
    n = dev.n * (1 + 0.01 * rng.standard_normal(shape))
    p = dev.p * (1 + 0.01 * rng.standard_normal(shape))

    voltages = {"source": 0.0, "gate": 5.0, "drain": 0.1}
    F, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    Jc = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(3 * dev.N, 30, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        psi2 = u2[0::3].reshape(shape)
        n2 = u2[1::3].reshape(shape)
        p2 = u2[2::3].reshape(shape)
        F2, *_ = dev._residual_jacobian(psi2, n2, p2, voltages)
        an = np.asarray(Jc[:, c].todense()).ravel()
        worst = max(worst, np.abs((F2.ravel() - F.ravel()) / step - an).max()
                    / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"3D Jacobian error {worst:.2e}"


def test_terminal_currents_conserve_charge_at_a_biased_point():
    """Sum of all THREE terminal currents (source + gate's displacement
    current is not a DirichletBC current -- only source/drain carry
    particle current in this structure) into the device must be ~0 at
    a real 3-terminal bias point -- same conservation identity
    test_validation_3d.py's own 2-terminal gate checks, extended to a
    device with a gate present."""
    mesh = _small_mesh(nx=10, ny=9, nz=5)
    dev = build_sic_vmosfet(mesh, P, models=Models(fd=True))
    dev.solve_equilibrium(NewtonOptions(max_iter=80))
    dev.solve_bias({"drain": 0.1, "gate": 10.0}, NewtonOptions(max_iter=100))

    I_source = dev.terminal_current("source")
    I_drain = dev.terminal_current("drain")
    # The gate carries no PARTICLE current (GateBC has no terminal_current
    # -- it's a Robin BC on psi only, not a DirichletBC); at Vds=0.1V
    # (near-equilibrium, not a fast transient) the gate's displacement
    # current is negligible compared to the channel current, so
    # source+drain alone should very nearly conserve charge.
    rel_err = abs(I_source + I_drain) / max(abs(I_source), abs(I_drain), 1e-30)
    assert rel_err < 1e-6, \
        (f"source+drain don't conserve charge: I_source={I_source:.6e} A, "
         f"I_drain={I_drain:.6e} A, rel err {rel_err:.2e}")


# ---------------------------------------------------------------- output sanity
def test_off_state_leakage_much_smaller_than_on_state_current():
    """The one indispensable MOSFET sanity check: a device that cannot
    turn off is not a MOSFET. Off/on ratio must be many orders of
    magnitude, not merely 'smaller'."""
    mesh = _small_mesh(nx=12, ny=10, nz=5)
    dev = build_sic_vmosfet(mesh, P, models=Models(fd=True))
    dev.solve_equilibrium(NewtonOptions(max_iter=80))
    opts = NewtonOptions(max_iter=100)

    dev.solve_bias({"drain": 0.1, "gate": 0.0}, opts)
    I_off = abs(dev.terminal_current("drain"))
    dev.solve_bias({"drain": 0.1, "gate": 15.0}, opts)
    I_on = abs(dev.terminal_current("drain"))

    assert I_on > 0.0
    assert I_off < I_on * 1e-3, \
        f"I_off={I_off:.3e} A not << I_on={I_on:.3e} A -- device does not turn off"


def test_drain_current_is_monotonically_increasing_with_gate_voltage():
    """Basic n-channel enhancement-mode MOSFET trend: Id(Vg) must not
    decrease as Vg increases at fixed small Vds (no negative
    transconductance anywhere in this regime)."""
    mesh = _small_mesh(nx=12, ny=10, nz=5)
    dev = build_sic_vmosfet(mesh, P, models=Models(fd=True))
    dev.solve_equilibrium(NewtonOptions(max_iter=80))
    opts = NewtonOptions(max_iter=100)

    Vg_list = [0.0, 3.0, 6.0, 10.0]
    Id = []
    for Vg in Vg_list:
        dev.solve_bias({"drain": 0.1, "gate": Vg}, opts)
        Id.append(dev.terminal_current("drain"))
    Id = np.array(Id)
    assert np.all(np.diff(Id) >= -1e-12), f"Id(Vg) not monotonic: {Id}"


def test_e_field_derivation_and_off_state_field_peaks_near_the_junction():
    """The example script derives E-field from psi_V via a finite
    difference (there is no E_field accessor on Device3D -- confirmed
    directly, ordinary numpy). This test checks that derivation on a
    real off-state-biased point, and that the peak field lands near
    the metallurgical body/drift junction depth, not at some unrelated
    location -- a basic physical-plausibility check on the extraction,
    not a claim about the exact peak value."""
    mesh = _small_mesh(nx=12, ny=12, nz=5)
    dev = build_sic_vmosfet(mesh, P, models=Models(fd=True))
    dev.solve_equilibrium(NewtonOptions(max_iter=80))
    opts = NewtonOptions(max_iter=100)
    # Ramp incrementally (warm-starting each step) rather than jumping
    # straight to 20V -- a single large jump on this coarse a mesh left
    # Newton unconverged (caught by actually checking, not assumed).
    for Vd in (0.0, 5.0, 10.0, 15.0, 20.0):
        dev.solve_bias({"drain": Vd, "gate": 0.0}, opts)

    psi = dev.psi_V
    Ey = -np.diff(psi, axis=1) / np.diff(mesh.y)[None, :, None]
    assert np.all(np.isfinite(Ey))
    assert np.abs(Ey).max() > 0.0

    # Peak field should sit within the drift region depth range, well
    # below the shallow source/body-tie junctions and well above the
    # substrate -- a coarse but real physical-location check.
    peak_j = int(np.unravel_index(np.argmax(np.abs(Ey)), Ey.shape)[1])
    y_peak = mesh.y[peak_j]
    assert P.y_body * 0.3 < y_peak < P.y_body + P.t_drift, \
        f"peak field at y={y_peak*1e4:.2f} um, expected within the " \
        f"body/drift depletion region"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for f in fns:
        try:
            if hasattr(f, "pytestmark"):
                continue   # parametrized -- run via pytest, not this loop
            f()
            print(f"  PASS  {f.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {f.__name__}: {e}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed (run via pytest for the "
         "parametrized guard-refusal tests)")
    sys.exit(1 if fails else 0)
