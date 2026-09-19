"""M47 Slice 1 groundwork: `unstructured_dd3d.py`'s own interior-physics
assembly (`_residual_jacobian_poisson3d`, `_residual_jacobian_dd3d`) had
NO direct FD-Jacobian gate before this file -- only physics/reduction/
regression tests (`test_unstructured_dd3d.py`, `test_m26_finfet3d.py`).
Per CLAUDE.md's mandatory "FD-Jacobian-first" rule, this gap is closed
here, against the PURE-PYTHON oracle, BEFORE any C++ kernel is written
for M47 Slice 1 -- see M47-3D-ENGINE-PLAN.md's validation plan.

Same relative-step, per-column-normalized convention as
test_validation_3d.py's own `test_dd_jacobian_matches_finite_differences`
(structured Device3D) and test_m13_solver.py's `_jacobian_probe`.
"""
import numpy as np
import pytest

from pytcad.constants import Q, EPS0
from pytcad.device import thermal_voltage, D0_REF
from pytcad.gmsh_mesh3d import build_diode_mesh3d
from pytcad.materials import SILICON
from pytcad.unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d)
from pytcad.unstructured_dd3d import (
    _residual_jacobian_poisson3d_py, _residual_jacobian_dd3d_py,
    evaluate_doping_at_nodes3d)

pytestmark = pytest.mark.filterwarnings("ignore")


def _fixture():
    mesh = build_diode_mesh3d(Lx=1.0e-4, Ly=2.5e-5, Lz=1.5e-5, Xj=0.5e-4,
                              Nd_scale=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = evaluate_doping_at_nodes3d(mesh.nodes, mesh.tets, region_of_tet,
                                   {"p_region": -1e17, "n_region": 1e17})

    material = SILICON
    T = 300.0
    VT = thermal_voltage(T)
    eps = material.eps_r * EPS0
    nie = material.ni(T)
    Ns = max(float(np.abs(C).max()), nie)
    LD = np.sqrt(eps * VT / (Q * Ns))
    R0 = D0_REF * Ns / LD ** 3

    C_s = C / Ns
    nie_s = nie / Ns
    vols_s = node_vols / LD ** 3
    eps_trans = trans / LD
    N = C.shape[0]
    tau_n = np.full_like(C, material.tau_n0)
    tau_p = np.full_like(C, material.tau_p0)
    i_e = edges[:, 0]
    D_n_s = np.full(i_e.shape[0], material.mu_n_max * VT / D0_REF)
    D_p_s = np.full(i_e.shape[0], material.mu_p_max * VT / D0_REF)
    return dict(N=N, C_s=C_s, nie_s=nie_s, vols_s=vols_s, edges=edges,
               trans=trans, eps_trans=eps_trans, D_n_s=D_n_s, D_p_s=D_p_s,
               R0=R0, tau_n=tau_n, tau_p=tau_p, material=material, Ns=Ns,
               LD=LD)


def test_poisson_equilibrium_jacobian_matches_fd():
    fx = _fixture()
    N = fx["N"]
    rng = np.random.default_rng(0)
    psi = (np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"]))
          + 0.01 * rng.standard_normal(N))

    F, J = _residual_jacobian_poisson3d_py(
        psi, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"], fx["eps_trans"])
    Jc = J.tocsc()

    worst = 0.0
    for c in rng.choice(N, min(30, N), replace=False):
        step = 1e-7 * max(abs(psi[c]), 1.0)
        psi2 = psi.copy(); psi2[c] += step
        F2, _ = _residual_jacobian_poisson3d_py(
            psi2, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"], fx["eps_trans"])
        an = np.asarray(Jc[:, c].todense()).ravel()
        num = (F2 - F) / step
        worst = max(worst, np.abs(num - an).max() / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"Poisson-equilibrium Jacobian error {worst:.2e}"


def test_coupled_dd_jacobian_matches_fd():
    fx = _fixture()
    N = fx["N"]
    rng = np.random.default_rng(1)
    psi = (np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"]))
          + 0.01 * rng.standard_normal(N))
    n = np.where(
        fx["C_s"] >= 0,
        0.5 * (fx["C_s"] + np.sqrt(fx["C_s"] ** 2 + 4 * fx["nie_s"] ** 2)),
        fx["nie_s"] ** 2 / np.maximum(
            0.5 * (-fx["C_s"] + np.sqrt(fx["C_s"] ** 2 + 4 * fx["nie_s"] ** 2)),
            1e-300))
    p = fx["nie_s"] ** 2 / np.maximum(n, 1e-300)
    n = n * (1.0 + 0.01 * rng.standard_normal(N))
    p = p * (1.0 + 0.01 * rng.standard_normal(N))

    def assemble(psi_, n_, p_):
        return _residual_jacobian_dd3d_py(
            psi_, n_, p_, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
            fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
            fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=True, auger=True)

    F, J, Jn, Jp = assemble(psi, n, p)
    Jc = J.tocsc()
    u = np.stack([psi, n, p], axis=1).ravel()

    worst = 0.0
    for c in rng.choice(3 * N, min(30, 3 * N), replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        psi2, n2, p2 = u2[0::3], u2[1::3], u2[2::3]
        F2, *_ = assemble(psi2, n2, p2)
        an = np.asarray(Jc[:, c].todense()).ravel()
        num = (F2 - F) / step
        worst = max(worst, np.abs(num - an).max() / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"Coupled DD Jacobian error {worst:.2e}"


def test_coupled_dd_jacobian_matches_fd_srh_off_no_auger():
    """A second combination (srh=False) -- the SRH/Auger COO block
    (_srh_auger_coo) is skipped entirely when both are off, so this
    exercises the F/J assembly path with that block absent, not just
    zeroed."""
    fx = _fixture()
    N = fx["N"]
    rng = np.random.default_rng(2)
    psi = (np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"]))
          + 0.01 * rng.standard_normal(N))
    n = np.full(N, fx["nie_s"] * 2.0) * (1 + 0.02 * rng.standard_normal(N))
    p = np.full(N, fx["nie_s"] * 0.5) * (1 + 0.02 * rng.standard_normal(N))

    def assemble(psi_, n_, p_):
        return _residual_jacobian_dd3d_py(
            psi_, n_, p_, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
            fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
            fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=False, auger=False)

    F, J, Jn, Jp = assemble(psi, n, p)
    Jc = J.tocsc()
    u = np.stack([psi, n, p], axis=1).ravel()

    worst = 0.0
    for c in rng.choice(3 * N, min(20, 3 * N), replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        psi2, n2, p2 = u2[0::3], u2[1::3], u2[2::3]
        F2, *_ = assemble(psi2, n2, p2)
        an = np.asarray(Jc[:, c].todense()).ravel()
        num = (F2 - F) / step
        worst = max(worst, np.abs(num - an).max() / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"Coupled DD (srh=False) Jacobian error {worst:.2e}"
