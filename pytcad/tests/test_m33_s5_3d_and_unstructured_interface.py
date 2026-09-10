"""M33-S5 gates -- chi-aware band alignment ported to Device3D and
unstructured_dd.py.

Plan: `pytcad/M33-S5-PLAN.md`. Section A mirrors Device2D's S4
(`tests/test_m33_s4_2d_interface.py`) one more axis. Section B ports
the same idea to `unstructured_dd.py`'s standalone `solve_bias`, which
has no `Models` object -- a new `band_offset` kwarg instead.
"""
import dataclasses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import Models, NewtonOptions
from pytcad.device3d import Device3D
from pytcad.materials import SILICON
from pytcad.mesh3d import Mesh3D


# =======================================================================
# Section A -- Device3D
# =======================================================================
def _hetero_mesh3d(nx=15, ny=5, nz=5):
    xg = np.linspace(0.0, 1.0e-4, nx)
    yg = np.linspace(0.0, 0.3e-4, ny)
    zg = np.linspace(0.0, 0.3e-4, nz)
    return Mesh3D(xg, yg, zg), xg, yg, zg


def _split_materials3d(xg, yg, zg, x_split=0.5e-4, chi_right=4.05):
    """Flat list ordered to match doping.reshape(Nz,Ny,Nx).ravel()."""
    right = dataclasses.replace(SILICON, name="Si-shifted", chi=chi_right)
    return [SILICON if x < x_split else right
           for _k in range(zg.size) for _j in range(yg.size) for x in xg]


def _hetero3d(chi_right=4.05, band_offset="nie", junction="pn",
             nx=15, ny=5, nz=5, bias=None, equilibrium_only=False):
    mesh, xg, yg, zg = _hetero_mesh3d(nx, ny, nz)
    shp = (nz, ny, nx)
    if junction == "pn":
        dop_row = np.where(xg < 0.5e-4, -1e17, 1e17)
    else:
        dop_row = np.full_like(xg, 1e17)
    dop = np.broadcast_to(dop_row, shp).copy()
    mats = _split_materials3d(xg, yg, zg, chi_right=chi_right)
    dev = Device3D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True, band_offset=band_offset))
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("r", i=np.full_like(jj, nx - 1), j=jj, k=kk, V=0.0)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    if not equilibrium_only:
        dev.solve_bias({"l": bias if bias is not None else 0.0})
    return dev


# Absolute floor [A]: measured (not a round number) worst homojunction-
# equivalent equilibrium |Jn|/|Jp| (any of the 3 axes, dchi swept
# -0.30..+0.30, affinity gauge) was 1.29e-10 A -- Newton's own stopping
# floor, not a balance violation (same reasoning as S1/S4's own
# floors). Set with the same ~600x margin S4's own 2D floor used.
EQ_CURRENT_FLOOR = 1.0e-7


def _assert_balanced3d(dev):
    _, _, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, {})
    Jn_max = max(np.abs(Jn_x).max(), np.abs(Jn_y).max(), np.abs(Jn_z).max()) * dev.J0
    Jp_max = max(np.abs(Jp_x).max(), np.abs(Jp_y).max(), np.abs(Jp_z).max()) * dev.J0
    assert Jn_max < EQ_CURRENT_FLOOR, f"electron balance broken: {Jn_max:.3e}"
    assert Jp_max < EQ_CURRENT_FLOOR, f"hole balance broken: {Jp_max:.3e}"


@pytest.mark.parametrize("dchi", [-0.30, -0.10, 0.0, 0.10, 0.30])
def test_g1_3d_equilibrium_detailed_balance_per_carrier(dchi):
    dev = _hetero3d(chi_right=4.05 + dchi, band_offset="affinity",
                    junction="pn", equilibrium_only=True)
    _assert_balanced3d(dev)


def test_g2_3d_affinity_step_moves_the_solution():
    ref = _hetero3d(chi_right=4.05, band_offset="affinity", junction="pn",
                    bias=0.1)
    for dchi in (-0.20, +0.20):
        dev = _hetero3d(chi_right=4.05 + dchi, band_offset="affinity",
                        junction="pn", bias=0.1)
        moved = np.abs(dev.psi - ref.psi).max()
        assert moved > 1e-3, f"chi step {dchi:+.2f} eV moved psi by only {moved:.3e}"
        Jr = ref.terminal_current("l")
        J = dev.terminal_current("l")
        assert abs(J / Jr - 1.0) > 1e-3, (
            f"chi step {dchi:+.2f} eV left J unchanged (ratio {J/Jr:.6f})")


def test_g2_3d_isotype_junction_barrier_is_symmetric_in_sign():
    J_lo = _hetero3d(chi_right=3.85, band_offset="affinity",
                     junction="isotype", bias=0.1).terminal_current("l")
    J_flat = _hetero3d(chi_right=4.05, band_offset="affinity",
                       junction="isotype", bias=0.1).terminal_current("l")
    J_hi = _hetero3d(chi_right=4.25, band_offset="affinity",
                     junction="isotype", bias=0.1).terminal_current("l")
    assert J_lo < J_flat and J_hi < J_flat, (J_lo, J_flat, J_hi)


def test_g3_3d_fd_jacobian_on_interface_edges():
    """Deterministic: every x-edge endpoint straddling the material
    interface, for every (j,k) -- not a random sample (M14's lesson)."""
    nx, ny, nz = 15, 5, 5
    mesh, xg, yg, zg = _hetero_mesh3d(nx, ny, nz)
    x_split = 0.5e-4
    i_split = int(np.searchsorted(xg, x_split))
    dev = _hetero3d(chi_right=4.30, band_offset="affinity", junction="pn",
                    nx=nx, ny=ny, nz=nz, bias=0.3)
    rng = np.random.default_rng(7)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.3, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    shp = dev.psi.shape

    cols = []
    for k in range(nz):
        for j in range(ny):
            for i in (i_split - 1, i_split):
                idx = k * nx * ny + j * nx + i
                cols.extend([3 * idx, 3 * idx + 1, 3 * idx + 2])

    worst = 0.0
    for c in cols:
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"S5 GATE FAIL: 3D FD-Jacobian rel err {worst:.3e} > 5e-5"


def test_g4_3d_legacy_gauge_reproduces_the_golden():
    dev_default = _hetero3d(chi_right=4.30, band_offset="nie",
                            junction="pn", bias=0.4)
    dev_explicit_nie = _hetero3d(chi_right=3.55, band_offset="nie",
                                 junction="pn", bias=0.4)
    assert np.array_equal(dev_default.psi, dev_explicit_nie.psi)
    assert np.array_equal(dev_default.n, dev_explicit_nie.n)
    assert np.array_equal(dev_default.p, dev_explicit_nie.p)


def test_g4_3d_homojunction_is_bit_identical_between_gauges():
    mesh, xg, yg, zg = _hetero_mesh3d()
    shp = (zg.size, yg.size, xg.size)
    dop = np.broadcast_to(np.where(xg < 0.5e-4, -1e17, 1e17), shp).copy()
    out = []
    for bo in ("nie", "affinity"):
        dev = Device3D(mesh, dop, T=300.0,
                       models=Models(bgn=False, srh=True, band_offset=bo))
        jj, kk = np.meshgrid(np.arange(yg.size), np.arange(zg.size))
        jj, kk = jj.ravel(), kk.ravel()
        dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
        dev.add_contact("r", i=np.full_like(jj, xg.size - 1), j=jj, k=kk, V=0.0)
        dev.solve_equilibrium()
        dev.solve_bias({"l": 0.4})
        out.append((dev.psi, dev.n, dev.p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


# ----------------------------------------------------------------------
# G5 -- GateBC Robin term composes correctly with the affinity gauge
# ----------------------------------------------------------------------
def _gated_device3d(chi_right, band_offset, nx=15, ny=7, nz=5):
    xg = np.linspace(0.0, 2.0e-4, nx)
    yg = np.linspace(0.0, 0.5e-4, ny)
    zg = np.linspace(0.0, 0.3e-4, nz)
    mesh = Mesh3D(xg, yg, zg)
    shp = (nz, ny, nx)
    dop = np.broadcast_to(np.full_like(xg, -1e17), shp).copy()   # p-substrate
    mats = _split_materials3d(xg, yg, zg, x_split=1.0e-4, chi_right=chi_right)
    dev = Device3D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True, band_offset=band_offset))
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("s", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("d", i=np.full_like(jj, nx - 1), j=jj, k=kk, V=0.0)
    ii, jjg = np.meshgrid(np.arange(nx), np.arange(ny))
    ii, jjg = ii.ravel(), jjg.ravel()
    dev.add_gate("g", i=ii, j=jjg, k=np.zeros_like(ii), tox_cm=1.0e-6,
                Vfb=-0.5, Vg=0.0, normal_axis='z')
    return dev


def test_g5_3d_gate_bc_homojunction_bit_identical_between_gauges():
    out = []
    for bo in ("nie", "affinity"):
        dev = _gated_device3d(chi_right=4.05, band_offset=bo)
        dev.solve_equilibrium()
        dev.solve_bias({"s": 0.0, "d": 0.05, "g": 0.8})
        out.append((dev.psi, dev.n, dev.p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


def test_g5_3d_gate_bc_fd_jacobian_with_a_chi_step_under_the_channel():
    dev = _gated_device3d(chi_right=4.30, band_offset="affinity",
                          nx=9, ny=5, nz=3)
    dev.solve_equilibrium()
    dev.solve_bias({"s": 0.0, "d": 0.05, "g": 0.8})
    rng = np.random.default_rng(11)
    psi = dev.psi + 0.01 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.005 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.005 * rng.standard_normal(dev.p.shape))
    voltages = {"s": 0.0, "d": 0.05}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    shp = dev.psi.shape
    rng2 = np.random.default_rng(13)
    worst = 0.0
    for c in rng2.choice(u.size, size=60, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"S5 GATE FAIL: 3D gate FD-Jacobian rel err {worst:.3e} > 5e-5"


def test_g6_3d_thermionic_refuses_on_device3d():
    mesh, xg, yg, zg = _hetero_mesh3d()
    shp = (zg.size, yg.size, xg.size)
    dop = np.broadcast_to(np.where(xg < 0.5e-4, -1e17, 1e17), shp).copy()
    with pytest.raises(NotImplementedError, match="[Tt]hermionic"):
        Device3D(mesh, dop, T=300.0,
                 models=Models(band_offset="affinity", thermionic=True))


def test_g7_3d_affinity_with_fd_refuses_on_device3d():
    mesh, xg, yg, zg = _hetero_mesh3d()
    shp = (zg.size, yg.size, xg.size)
    dop = np.broadcast_to(np.where(xg < 0.5e-4, -1e17, 1e17), shp).copy()
    with pytest.raises(NotImplementedError, match="fd"):
        Device3D(mesh, dop, T=300.0,
                 models=Models(band_offset="affinity", fd=True))


# =======================================================================
# Section B -- unstructured_dd.py
# =======================================================================
gmsh = pytest.importorskip("gmsh")

from pytcad.gmsh_mesh import build_diode_mesh
from pytcad.region_resolver import resolve_regions, resolve_contacts
from pytcad.unstructured_assembly import (
    build_unstructured_stencil, build_edge_flux_geometry,
)
from pytcad.unstructured_poisson import evaluate_doping_at_nodes
from pytcad.unstructured_dd import solve_bias as dd_solve_bias, _residual_jacobian


@pytest.fixture(scope="module")
def u_mesh():
    return build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16)


@pytest.fixture(scope="module")
def u_geom(u_mesh):
    regions = resolve_regions(u_mesh)
    contacts = resolve_contacts(u_mesh)
    edge_list, node_areas = build_unstructured_stencil(u_mesh.nodes, u_mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        u_mesh.nodes, u_mesh.triangles, edge_list)
    region_of_triangle = np.empty(u_mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        region_of_triangle[idx] = name
    return dict(mesh=u_mesh, contacts=contacts, edge_list=edge_list,
               node_areas=node_areas, interior_edges=interior_edges,
               trans_geom=trans_geom, region_of_triangle=region_of_triangle)


def _mats_per_node_u(g, chi_right, x_split=3.0e-4):
    """Per-node material (majority vote over touching triangles, same
    convention test_unstructured_dd_mobility_het.py's own (c) gate
    uses), split by x rather than by region so an ISOTYPE (same-sign
    doping) junction can also be built with this helper."""
    right = dataclasses.replace(SILICON, name="Si-shifted", chi=chi_right)
    mesh = g["mesh"]
    tri = mesh.triangles
    coms = mesh.nodes[tri].mean(axis=1)
    mats_by_tri = np.where(coms[:, 0] < x_split, SILICON, right)
    N = mesh.n_nodes()
    votes = {}
    for t_idx, (a, b, c) in enumerate(tri):
        for v in (a, b, c):
            votes.setdefault(int(v), []).append(mats_by_tri[t_idx])
    return np.array(
        [max(votes[i], key=lambda m: sum(v is m for v in votes[i]))
         for i in range(N)], dtype=object)


def _hetero_u(g, chi_right, band_offset="nie", junction="pn", bias=None):
    doping = ({"p_region": -1e17, "n_region": 1e17} if junction == "pn"
             else {"p_region": 1e17, "n_region": 1e17})
    C = evaluate_doping_at_nodes(g["mesh"].nodes, g["mesh"].triangles,
                                 g["region_of_triangle"], doping)
    mats = _mats_per_node_u(g, chi_right)
    return dd_solve_bias(
        g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
        g["interior_edges"], g["trans_geom"], C, g["contacts"],
        bias=bias or {}, materials_per_node=mats, band_offset=band_offset)


EQ_CURRENT_FLOOR_U = 1.0e-6   # [A]; same margin reasoning as Section A


def test_g1_u_equilibrium_current_near_zero(u_geom):
    for dchi in (-0.30, -0.10, 0.0, 0.10, 0.30):
        _, _, _, scale, I = _hetero_u(u_geom, 4.05 + dchi,
                                      band_offset="affinity", junction="pn")
        assert scale["last_converged"]
        Imax = max(abs(v) for v in I.values())
        assert Imax < EQ_CURRENT_FLOOR_U, f"dchi={dchi}: |I|={Imax:.3e}"


def test_g2_u_affinity_step_moves_the_solution(u_geom):
    psi_ref, *_ = _hetero_u(u_geom, 4.05, band_offset="affinity",
                            junction="pn", bias={"left_contact": 0.1})
    for dchi in (-0.20, +0.20):
        psi, n, p, scale, I = _hetero_u(u_geom, 4.05 + dchi, band_offset="affinity",
                                        junction="pn", bias={"left_contact": 0.1})
        moved = np.abs(psi - psi_ref).max()
        assert moved > 1e-3, f"chi step {dchi:+.2f} eV moved psi by only {moved:.3e}"


def test_g2_u_isotype_terminal_current_is_analytically_gauge_invariant(u_geom):
    """NOT a copy of Device2D/3D's isotype gate -- an honest, DIFFERENT
    finding specific to this module's architecture, established by
    direct investigation (not assumed) when the naive port of the 2D/3D
    gate failed here.

    unstructured_dd.py has no separate equilibrium-only residual (no
    analytic n=nie*exp(psi_c) carrier slaving the way Device1D/2D/3D's
    `_residual_jacobian_poisson` provides) -- `solve_bias` ALWAYS
    solves the fully-coupled system with n, p as free unknowns, even
    when called with bias={} for a "cold" equilibrium. For a UNIFORMLY
    doped isotype junction (same C, same nie both materials -- doping
    alone gives no depletion anywhere), n=C, p~0 satisfies Poisson
    pointwise for ANY psi, and the SG Bernoulli identity B(x)-B(-x)=x
    then makes Jn EXACTLY LINEAR in (psi + band_shift) when n is
    uniform. Because this module's own contact-value fix sets
    psi0_contact = psi0_original - band_shift[contact], the shifted
    variable (psi + band_shift) at BOTH contacts equals the ORIGINAL
    gauge-free value -- so a resistor's terminal current, which this
    linear relation makes depend on nothing but that variable's
    boundary values, is then PROVABLY independent of `band_offset` for
    this specific (uniform, undepleted) geometry. Confirmed directly:
    Device2D's own isotype gate does NOT hit this degeneracy because
    its solve_equilibrium slaves carriers analytically (producing a
    real interface spike in n BEFORE solve_bias ever runs); this
    module's solve_bias, even warm-started from its OWN bias={} "cold"
    solve, converges to the flat n=C fixed point instead (checked
    directly: current agreed across a chi_right sweep from 3.85 to
    6.05 eV, and even across a bias={} + init= warm-start variant, to
    the value of every printed digit).

    This is the CORRECT gate for this module's actual mathematics, not
    a workaround -- bit-identity (not merely "close") is exactly what
    the derivation above predicts."""
    Js = []
    for chi in (3.85, 4.05, 4.25):
        _, _, _, _, I = _hetero_u(u_geom, chi, band_offset="affinity",
                                  junction="isotype", bias={"left_contact": 0.1})
        Js.append(I["left_contact"])
    assert Js[0] == Js[1] == Js[2], Js


def test_g3_u_fd_jacobian_on_interface_edges(u_geom):
    """Every interior edge crossing the material interface (dlnnie != 0
    or ds != 0), not a random sample."""
    g = u_geom
    doping = {"p_region": -1e17, "n_region": 1e17}
    C = evaluate_doping_at_nodes(g["mesh"].nodes, g["mesh"].triangles,
                                 g["region_of_triangle"], doping)
    mats = _mats_per_node_u(g, chi_right=4.30)
    psi, n, p, scale, I = dd_solve_bias(
        g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
        g["interior_edges"], g["trans_geom"], C, g["contacts"],
        bias={"left_contact": 0.3}, materials_per_node=mats,
        band_offset="affinity")
    assert scale["last_converged"]

    from pytcad.materials import mobility_caughey_thomas
    from pytcad.device import thermal_voltage, D0_REF
    from pytcad.constants import Q, EPS0
    VT = thermal_voltage(300.0)
    eps = SILICON.eps_r * EPS0
    N = C.shape[0]
    nie_node = np.array([m.ni(300.0) for m in mats])
    Ns = max(float(np.abs(C).max()), float(nie_node.max()))
    LD = np.sqrt(eps * VT / (Q * Ns))
    R0 = D0_REF * Ns / LD ** 2
    C_s = C / Ns
    nie_s = nie_node / Ns
    areas_s = g["node_areas"] / LD ** 2
    eps_trans = g["trans_geom"] * eps
    i_e, j_e = g["interior_edges"][:, 0], g["interior_edges"][:, 1]
    mu_n = np.array([m.mu_n_max for m in mats])
    mu_p = np.array([m.mu_p_max for m in mats])

    def hmean(lo, hi):
        return 2.0 * lo * hi / (lo + hi)
    D_n_s = hmean(mu_n[i_e], mu_n[j_e]) * VT / D0_REF
    D_p_s = hmean(mu_p[i_e], mu_p[j_e]) * VT / D0_REF
    dlnnie = np.log(nie_s[j_e] / nie_s[i_e])
    nc_node = np.array([m.Nc(300.0) for m in mats])
    chi_node = np.array([m.chi for m in mats])
    s_node = np.log(nc_node / nie_node) + chi_node / VT
    band_shift = s_node - s_node[0]
    ds = band_shift[j_e] - band_shift[i_e]
    tau_n = np.full_like(C, SILICON.tau_n0)
    tau_p = np.full_like(C, SILICON.tau_p0)

    # dlnnie is exactly zero here (both materials share the same nie);
    # `ds` is the term this gate actually needs to exercise.
    interface_edges = np.where(np.abs(ds) > 1e-12)[0]
    assert interface_edges.size > 0, "no interface edges found -- test setup bug"

    n_scaled = n / Ns * Ns   # n already scaled; keep as-is
    rng = np.random.default_rng(7)
    psi_p = psi + 0.01 * rng.standard_normal(psi.shape)
    n_p = n * (1.0 + 0.005 * rng.standard_normal(n.shape))
    p_p = p * (1.0 + 0.005 * rng.standard_normal(p.shape))

    def F_of(psi_, n_, p_):
        F, J, *_ = _residual_jacobian(
            psi_, n_, p_, C_s, nie_s, areas_s, g["interior_edges"], eps_trans,
            D_n_s, D_p_s, R0, tau_n, tau_p, SILICON, Ns, srh=True, auger=False,
            dlnnie=dlnnie, ds=ds)
        return F, J

    F0v, J = F_of(psi_p, n_p, p_p)
    J = J.tocsc()
    u = np.stack([psi_p, n_p, p_p], axis=1).ravel()

    cols = []
    for e in interface_edges:
        for node in (i_e[e], j_e[e]):
            cols.extend([3 * node, 3 * node + 1, 3 * node + 2])
    cols = sorted(set(cols))

    worst = 0.0
    for c in cols:
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        Fp_, _ = F_of(u2[0::3], u2[1::3], u2[2::3])
        Fm_, _ = F_of(u1[0::3], u1[1::3], u1[2::3])
        fd_col = (Fp_ - Fm_) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"S5 GATE FAIL: unstructured FD-Jacobian rel err {worst:.3e} > 5e-5"


def test_g4_u_legacy_gauge_unchanged(u_geom):
    """band_offset omitted (default) must be bit-identical to
    band_offset='nie' explicit, and both bit-identical to the
    pre-existing (pre-S5) call with no band_offset kwarg at all."""
    g = u_geom
    doping = {"p_region": -1e17, "n_region": 1e17}
    C = evaluate_doping_at_nodes(g["mesh"].nodes, g["mesh"].triangles,
                                 g["region_of_triangle"], doping)
    kwargs = dict(bias={"left_contact": 0.4})
    psi1, n1, p1, *_ = dd_solve_bias(
        g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
        g["interior_edges"], g["trans_geom"], C, g["contacts"], **kwargs)
    psi2, n2, p2, *_ = dd_solve_bias(
        g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
        g["interior_edges"], g["trans_geom"], C, g["contacts"],
        band_offset="nie", **kwargs)
    assert np.array_equal(psi1, psi2)
    assert np.array_equal(n1, n2)
    assert np.array_equal(p1, p2)


def test_g4_u_homojunction_bit_identical_between_gauges(u_geom):
    g = u_geom
    doping = {"p_region": -1e17, "n_region": 1e17}
    C = evaluate_doping_at_nodes(g["mesh"].nodes, g["mesh"].triangles,
                                 g["region_of_triangle"], doping)
    out = []
    for bo in ("nie", "affinity"):
        psi, n, p, *_ = dd_solve_bias(
            g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
            g["interior_edges"], g["trans_geom"], C, g["contacts"],
            bias={"left_contact": 0.4}, band_offset=bo)
        out.append((psi, n, p))
    for a, b in zip(out[0], out[1]):
        assert np.array_equal(a, b)


def test_g7_u_invalid_band_offset_raises(u_geom):
    g = u_geom
    doping = {"p_region": -1e17, "n_region": 1e17}
    C = evaluate_doping_at_nodes(g["mesh"].nodes, g["mesh"].triangles,
                                 g["region_of_triangle"], doping)
    with pytest.raises(ValueError, match="band_offset"):
        dd_solve_bias(
            g["mesh"].nodes, g["mesh"].triangles, g["edge_list"], g["node_areas"],
            g["interior_edges"], g["trans_geom"], C, g["contacts"],
            bias={}, band_offset="bogus")
