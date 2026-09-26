"""AC-SENSITIVITY-PLAN.md gates: the ohmic-port current-sensitivity row
of ac2d / ac3d y_parameters(), computed from the assembler's own raw
continuity rows instead of ~2*3*|support| full re-assemblies.

G1  off path unchanged: _residual_jacobian(..., current_rows_for=None)
    and with the rows requested return byte-identical F, J, F_n, F_p (the
    request only stashes a copy). Portable: a comparison within one run,
    not a stored digest (those pin one machine's summation order).
G2  analytic == finite difference, within the FD's OWN measured error:
    |S_a - S_fd(h)| <= 10 * |S_fd(h) - S_fd(h/2)| + floor, per ohmic port,
    for every physics configuration y_parameters is used with. The FD row
    is the pre-change implementation, kept as the oracle.
G4  (elsewhere) every existing AC gate passes with its tolerance unchanged.

Devices are deliberately small: the FD oracle is exactly the expensive
thing being replaced, run twice per case here.
"""
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import Models, NewtonOptions
from pytcad import ac2d, ac3d
from pytcad.device2d import Device2D, DirichletBC as DirichletBC2D
from pytcad.device3d import Device3D, DirichletBC as DirichletBC3D
from pytcad.materials import GAAS, SILICON
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.moscap import flatband_voltage
from pytcad.mosfet import build_mosfet, mosfet_doping

OPTS = NewtonOptions(max_iter=60)


def _quiet(fn, *a, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # degenerate-doping advisory
        return fn(*a, **kw)


# ------------------------------------------------------------------ fixtures
def _diode2d(models, Na=1e17, Nd=1e17, bias=0.3, material=None, schottky=False):
    x = np.linspace(0.0, 2e-4, 17)
    y = np.linspace(0.0, 5e-5, 7)
    mesh = Mesh2D(x, y)
    dop = np.where(x[None, :] < 1e-4, -Na, Nd) * np.ones((y.size, 1))
    dev = Device2D(mesh, dop, models=models, material=material) if material else \
        Device2D(mesh, dop, models=models)
    rows = list(range(y.size))
    dev.add_contact("left", i=[0], j=rows, V=0.0)
    if schottky:
        dev.add_schottky_contact("right", i=[x.size - 1], j=rows,
                                 phi_metal_eV=4.3, A_star=112.0, V=0.0)
    else:
        dev.add_contact("right", i=[x.size - 1], j=rows, V=0.0)
    _quiet(dev.solve_equilibrium, OPTS)
    _quiet(dev.solve_bias, {"left": bias}, OPTS)
    assert dev.last_converged
    return dev


def _mosfet2d(surface_mobility=False):
    dev = build_mosfet(Lg=0.3e-4, Lsd=0.2e-4, depth=0.5e-4, Na=1e17,
                       Nsd_peak=1e20, tox_cm=3e-7, nx=24, ny=12)
    dev.models.surface_mobility = surface_mobility   # test_m14's own pattern
    _quiet(dev.solve_equilibrium, OPTS)
    _quiet(dev.solve_bias, {"drain": 0.1, "gate": 1.0}, OPTS)
    assert dev.last_converged
    return dev


def _diode3d(models, Na=1e17, Nd=1e17, bias=0.3, schottky=False):
    x = np.linspace(0.0, 2e-4, 11)
    y = np.linspace(0.0, 2e-5, 4)
    z = np.linspace(0.0, 2e-5, 3)
    mesh = Mesh3D(x, y, z)
    dop = np.broadcast_to(np.where(x < 1e-4, -Na, Nd), (z.size, y.size, x.size)).copy()
    dev = Device3D(mesh, dop, models=models)
    jj, kk = np.meshgrid(np.arange(y.size), np.arange(z.size))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    if schottky:
        dev.add_schottky_contact("right", i=np.full_like(jj, x.size - 1), j=jj, k=kk,
                                 phi_metal_eV=4.3, V=0.0)
    else:
        dev.add_contact("right", i=np.full_like(jj, x.size - 1), j=jj, k=kk, V=0.0)
    _quiet(dev.solve_equilibrium, OPTS)
    if bias is not None:   # None: equilibrium only (DG is equilibrium-only, M20/M42)
        _quiet(dev.solve_bias, {"left": bias}, OPTS)
        assert dev.last_converged
    return dev


def _mosfet3d():
    Lg, Lsd, depth, Na, tox = 0.3e-4, 0.2e-4, 0.5e-4, 1e17, 3e-7
    x, y, z = np.linspace(0.0, 2 * Lsd + Lg, 12), np.linspace(0.0, depth, 8), np.linspace(0.0, 5e-6, 3)
    mesh3 = Mesh3D(x, y, z)
    dop2d, nt2d = mosfet_doping(Mesh2D(x, y), Lsd, Lg, Na, 1e20, Lg / 4.0, Lg / 4.0)
    dev = Device3D(mesh3, np.tile(dop2d, (3, 1, 1)), Ntotal=np.tile(nt2d, (3, 1, 1)))
    kk_all = np.arange(3)

    def face(i_range, j_val):
        ii, kk = np.meshgrid(i_range, kk_all)
        return ii.ravel(), np.full(ii.size, j_val), kk.ravel()

    for name, ir, jv in (("source", np.where(x <= Lsd)[0], 0), ("drain", np.where(x >= Lsd + Lg)[0], 0),
                         ("body", np.arange(x.size), y.size - 1)):
        i, j, k = face(ir, jv)
        dev.add_contact(name, i=i, j=j, k=k, V=0.0)
    gi, gj, gk = face(np.where((x > Lsd) & (x < Lsd + Lg))[0], 0)
    dev.add_gate("gate", i=gi, j=gj, k=gk, tox_cm=tox,
                 Vfb=flatband_voltage(-Na, tox, "n+poly", 0.0, 300.0), Vg=0.0, normal_axis="y")
    _quiet(dev.solve_equilibrium, OPTS)
    _quiet(dev.solve_bias, {"drain": 0.1, "gate": 1.0}, OPTS)
    assert dev.last_converged
    return dev


B = dict(bgn=False)
CASES_2D = {
    "default": lambda: _diode2d(Models(**B)),
    "fermi_dirac": lambda: _diode2d(Models(**B, fd=True), Na=1e19, Nd=1e19, bias=0.2),
    "incomplete_ion": lambda: _diode2d(Models(**B, incomplete_ion=True)),
    "impact": lambda: _diode2d(Models(**B, impact=True), Na=1e18, Nd=1e18, bias=-3.0),
    "btbt": lambda: _diode2d(Models(**B, btbt=True), Na=5e19, Nd=5e19, bias=-1.0),
    "robin_Sn_Sp": lambda: _diode2d(Models(**B, S_n=1e5, S_p=1e5)),
    "schottky_robin": lambda: _diode2d(Models(**B), schottky=True, bias=0.1),
    "hetero": lambda: _hetero2d(),
    "mosfet": lambda: _mosfet2d(),
    "mosfet_surface_mobility": lambda: _mosfet2d(surface_mobility=True),
}
CASES_3D = {
    "default": lambda: _diode3d(Models(**B)),
    "impact": lambda: _diode3d(Models(**B, impact=True), Na=1e18, Nd=1e18, bias=-3.0),
    "btbt": lambda: _diode3d(Models(**B, btbt=True), Na=5e19, Nd=5e19, bias=-1.0),
    "incomplete_ion": lambda: _diode3d(Models(**B, incomplete_ion=True)),
    "dg": lambda: _diode3d(Models(**B, dg=True), bias=None),
    "schottky": lambda: _diode3d(Models(**B), schottky=True, bias=0.1),
    "mosfet": _mosfet3d,
}


def _hetero2d():
    """Si | GaAs along x, as test_m13_solver's hetero fixture (1D) lifted."""
    x = np.linspace(0.0, 1e-4, 21)
    y = np.linspace(0.0, 2e-5, 5)
    dop = np.where(x[None, :] < 0.5e-4, -1e17, 1e17) * np.ones((y.size, 1))
    mats = []
    for _j in range(y.size):
        mats += [SILICON] * 10 + [GAAS] * 11
    dev = Device2D(Mesh2D(x, y), dop, models=Models(**B), material=mats)
    rows = list(range(y.size))
    dev.add_contact("left", i=[0], j=rows, V=0.0)
    dev.add_contact("right", i=[x.size - 1], j=rows, V=0.0)
    _quiet(dev.solve_equilibrium, OPTS)
    _quiet(dev.solve_bias, {"left": 0.3}, OPTS)
    assert dev.last_converged
    return dev


# --------------------------------------------------------------------- helpers
def _ohmic_ports(dev):
    """y_parameters' own ohmic-port rule: isinstance(bc, DirichletBC)
    (SchottkyBC is a subclass), node index k*Nx*Ny + j*Nx + i."""
    three_d = isinstance(dev, Device3D)
    dirichlet = DirichletBC3D if three_d else DirichletBC2D
    out = []
    for name, bc in dev.bcs.items():
        if isinstance(bc, dirichlet):
            if three_d:
                kk = (bc.k * dev.Nx * dev.Ny + bc.j * dev.Nx + bc.i).astype(int)
            else:
                kk = (bc.j * dev.Nx + bc.i).astype(int)
            out.append((name, kk))
    return out


def _voltages(dev):
    """y_parameters' own voltages dict: every DirichletBC's V."""
    dirichlet = DirichletBC3D if isinstance(dev, Device3D) else DirichletBC2D
    return {name: bc.V for name, bc in dev.bcs.items() if isinstance(bc, dirichlet)}


def _check_g2(dev, ac):
    psi, n, p = dev.psi, dev.n, dev.p
    voltages = _voltages(dev)
    ports = _ohmic_ports(dev)
    analytic = ac._ohmic_current_sensitivities(dev, psi, n, p, voltages, [kk for _, kk in ports])
    for (name, kk), S_a in zip(ports, analytic):
        S_h = ac._ohmic_current_sensitivity_fd(dev, psi, n, p, voltages, kk, rel_step=1e-6)
        S_h2 = ac._ohmic_current_sensitivity_fd(dev, psi, n, p, voltages, kk, rel_step=5e-7)
        scale = max(np.abs(S_h).max(), 1e-300)
        fd_err = np.abs(S_h - S_h2).max()
        err = np.abs(S_a - S_h).max()
        assert S_a.shape == S_h.shape
        assert np.abs(S_a).max() > 0.0, f"{name}: analytic row is all zero"
        assert err <= 10.0 * fd_err + 1e-12 * scale, (
            f"{name}: |S_analytic - S_fd| = {err:.3e} ({err / scale:.2e} rel) exceeds 10x the FD's "
            f"own error {fd_err:.3e} ({fd_err / scale:.2e} rel)")


# ----------------------------------------------------------------------- G1
@pytest.mark.parametrize("case", ["default", "robin_Sn_Sp", "impact", "mosfet"])
def test_g1_2d_requesting_the_rows_changes_no_output(case):
    dev = CASES_2D[case]()
    voltages = _voltages(dev)
    nodes = np.concatenate([kk for _, kk in _ohmic_ports(dev)])
    plain = dev._residual_jacobian(dev.psi, dev.n, dev.p, voltages)
    asked = dev._residual_jacobian(dev.psi, dev.n, dev.p, voltages, current_rows_for=nodes)
    assert len(plain) == len(asked)
    for a, b in zip(plain, asked):
        if hasattr(a, "tocsr"):
            a, b = a.tocsr(), b.tocsr()
            assert np.array_equal(a.indptr, b.indptr) and np.array_equal(a.indices, b.indices)
            assert np.array_equal(a.data, b.data)
        else:
            assert np.array_equal(np.asarray(a), np.asarray(b))


@pytest.mark.parametrize("case", ["default", "impact", "mosfet"])
def test_g1_3d_requesting_the_rows_changes_no_output(case):
    dev = CASES_3D[case]()
    voltages = _voltages(dev)
    nodes = np.concatenate([kk for _, kk in _ohmic_ports(dev)])
    plain = dev._residual_jacobian(dev.psi, dev.n, dev.p, voltages)
    asked = dev._residual_jacobian(dev.psi, dev.n, dev.p, voltages, current_rows_for=nodes)
    assert len(plain) == len(asked)
    for a, b in zip(plain, asked):
        if hasattr(a, "tocsr"):
            a, b = a.tocsr(), b.tocsr()
            assert np.array_equal(a.indptr, b.indptr) and np.array_equal(a.indices, b.indices)
            assert np.array_equal(a.data, b.data)
        else:
            assert np.array_equal(np.asarray(a), np.asarray(b))


# ----------------------------------------------------------------------- G2
@pytest.mark.parametrize("case", sorted(CASES_2D))
def test_g2_2d_analytic_row_equals_fd_within_its_error(case):
    _check_g2(CASES_2D[case](), ac2d)


@pytest.mark.parametrize("case", sorted(CASES_3D))
def test_g2_3d_analytic_row_equals_fd_within_its_error(case):
    _check_g2(CASES_3D[case](), ac3d)


def test_y_parameters_uses_one_assembly_for_every_ohmic_port():
    """The point of the change: y_parameters' ohmic rows cost ONE
    _residual_jacobian call, not ~2*3*|support| per port."""
    dev = _mosfet3d()
    calls = []
    orig = dev._residual_jacobian

    def counting(*a, **kw):
        calls.append(kw.get("current_rows_for") is not None)
        return orig(*a, **kw)

    dev._residual_jacobian = counting
    try:
        ac3d.y_parameters(dev, np.array([1.0]))
    finally:
        del dev._residual_jacobian
    assert sum(calls) == 1, calls
    assert len(calls) <= 3, f"{len(calls)} assemblies (was thousands with finite differences)"
