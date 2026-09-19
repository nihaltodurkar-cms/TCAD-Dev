"""M47 Slice 1: raw-COO and full-CSR parity between the pure-Python
oracle (`unstructured_dd3d._residual_jacobian_poisson3d`/
`_residual_jacobian_dd3d`, kept as the validation reference -- NOT a
production fallback, see M47-3D-ENGINE-PLAN.md's architectural
constraint) and the compiled `pytcad._core.unstructured3d_residual_
jacobian_equilibrium`/`_coupled` kernels.

Two-tier validation (M47 design review item 1):
  tier 1: raw (rows, cols, vals) -- Python's own block functions
          (_poisson_flux_geometry_coo etc.) vs the C++ kernel's raw COO
          output, BEFORE any csr_matrix is built.
  tier 2: the final assembled csr_matrix (data/indices/indptr) and F,
          via np.array_equal -- catches a concatenation-order bug tier 1
          alone (block-by-block) would not, since tier 1 compares each
          block in isolation.

Production dispatch is NOT wired up yet (`_residual_jacobian_dd3d`/
`_poisson3d` still call the pure-Python path only) -- this file proves
the compiled kernels are correct BEFORE that wiring lands, per the
Python-reference-then-C++-production validation order the plan commits
to.
"""
import numpy as np
import pytest

from pytcad import _accel
from pytcad.constants import Q, EPS0
from pytcad.device import thermal_voltage, D0_REF, bernoulli, dbernoulli
from pytcad.gmsh_mesh3d import build_diode_mesh3d
from pytcad.materials import SILICON
from pytcad.unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d)
from pytcad.unstructured_dd3d import (
    _residual_jacobian_poisson3d_py, _residual_jacobian_dd3d_py,
    _poisson_flux_geometry_coo, _poisson_equilibrium_diag_coo,
    _poisson_charge_coupling_coo, _srh_auger_coo, _sg_carrier_coo,
    evaluate_doping_at_nodes3d)

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL,
                                reason="pytcad._core not built")


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
               LD=LD, nie=nie)


def test_tier1_raw_coo_poisson_flux_geometry_equilibrium():
    fx = _fixture()
    i_idx, j_idx = fx["edges"][:, 0], fx["edges"][:, 1]
    py_r, py_c, py_v = _poisson_flux_geometry_coo(i_idx, j_idx, fx["eps_trans"])
    # No direct C++ export of the individual block -- exercised through
    # the full equilibrium kernel and re-derived from ITS raw output by
    # slicing the first 4*E entries (the block order the header
    # documents: geometry first).
    rng = np.random.default_rng(0)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])
    n = fx["nie_s"] * np.exp(np.clip(psi, -700, 700))
    p = fx["nie_s"] * np.exp(np.clip(-psi, -700, 700))
    flux = fx["eps_trans"] * (psi[j_idx] - psi[i_idx])

    F_cpp, r_cpp, c_cpp, v_cpp = _accel.core.unstructured3d_residual_jacobian_equilibrium(
        n, p, fx["C_s"], fx["vols_s"], i_idx.astype(np.int64), j_idx.astype(np.int64),
        fx["eps_trans"], flux)
    E4 = 4 * i_idx.shape[0]
    assert np.array_equal(r_cpp[:E4], py_r)
    assert np.array_equal(c_cpp[:E4], py_c)
    assert np.array_equal(v_cpp[:E4], py_v)


def test_tier2_full_csr_equilibrium_matches_python_oracle():
    fx = _fixture()
    i_idx, j_idx = fx["edges"][:, 0], fx["edges"][:, 1]
    rng = np.random.default_rng(1)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])

    F_py, J_py = _residual_jacobian_poisson3d_py(
        psi, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"], fx["eps_trans"])

    n = fx["nie_s"] * np.exp(np.clip(psi, -700, 700))
    p = fx["nie_s"] * np.exp(np.clip(-psi, -700, 700))
    flux = fx["eps_trans"] * (psi[j_idx] - psi[i_idx])
    F_cpp, r_cpp, c_cpp, v_cpp = _accel.core.unstructured3d_residual_jacobian_equilibrium(
        n, p, fx["C_s"], fx["vols_s"], i_idx.astype(np.int64), j_idx.astype(np.int64),
        fx["eps_trans"], flux)
    import scipy.sparse as sp
    J_cpp = sp.csr_matrix((v_cpp, (r_cpp, c_cpp)), shape=(fx["N"], fx["N"]))

    assert np.array_equal(F_py, F_cpp)
    Jc_py, Jc_cpp = J_py.tocsc(), J_cpp.tocsc()
    assert np.array_equal(Jc_py.indptr, Jc_cpp.indptr)
    assert np.array_equal(Jc_py.indices, Jc_cpp.indices)
    assert np.array_equal(Jc_py.data, Jc_cpp.data)


def test_tier2_full_csr_coupled_matches_python_oracle():
    fx = _fixture()
    i_idx, j_idx = fx["edges"][:, 0], fx["edges"][:, 1]
    rng = np.random.default_rng(2)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])
    n = np.where(
        fx["C_s"] >= 0,
        0.5 * (fx["C_s"] + np.sqrt(fx["C_s"] ** 2 + 4 * fx["nie_s"] ** 2)),
        fx["nie_s"] ** 2 / np.maximum(
            0.5 * (-fx["C_s"] + np.sqrt(fx["C_s"] ** 2 + 4 * fx["nie_s"] ** 2)),
            1e-300))
    p = fx["nie_s"] ** 2 / np.maximum(n, 1e-300)
    n = n * (1.0 + 0.01 * rng.standard_normal(fx["N"]))
    p = p * (1.0 + 0.01 * rng.standard_normal(fx["N"]))

    F_py, J_py, Jn_py, Jp_py = _residual_jacobian_dd3d_py(
        psi, n, p, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
        fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
        fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=True, auger=True)

    flux = fx["eps_trans"] * (psi[j_idx] - psi[i_idx])
    delta = psi[j_idx] - psi[i_idx]
    Bp, Bm = bernoulli(delta), bernoulli(-delta)
    dBp, dBm = dbernoulli(delta), dbernoulli(-delta)

    (F_cpp, r_cpp, c_cpp, v_cpp, Jn_cpp, Jp_cpp) = (
        _accel.core.unstructured3d_residual_jacobian_coupled(
            n, p, fx["C_s"], fx["vols_s"], i_idx.astype(np.int64),
            j_idx.astype(np.int64), fx["eps_trans"], flux, fx["eps_trans"] * fx["LD"],
            fx["D_n_s"], fx["D_p_s"], Bp, Bm, dBp, dBm, fx["nie_s"] * fx["Ns"], fx["tau_n"], fx["tau_p"],
            fx["Ns"], fx["R0"], True, True, fx["material"].Cn_auger,
            fx["material"].Cp_auger))

    import scipy.sparse as sp
    J_cpp = sp.csr_matrix((v_cpp, (r_cpp, c_cpp)), shape=(3 * fx["N"], 3 * fx["N"]))

    assert np.array_equal(F_py, F_cpp)
    assert np.array_equal(Jn_py, Jn_cpp)
    assert np.array_equal(Jp_py, Jp_cpp)
    Jc_py, Jc_cpp = J_py.tocsc(), J_cpp.tocsc()
    assert np.array_equal(Jc_py.indptr, Jc_cpp.indptr)
    assert np.array_equal(Jc_py.indices, Jc_cpp.indices)
    assert np.array_equal(Jc_py.data, Jc_cpp.data)


def test_tier2_coupled_srh_off_matches_python_oracle():
    """A second parameter combination (srh=False) -- exercises the
    branch where the SRH diagonal COO block is emitted with all-zero
    values (present, not absent -- see kernels.cpp's own comment)."""
    fx = _fixture()
    i_idx, j_idx = fx["edges"][:, 0], fx["edges"][:, 1]
    rng = np.random.default_rng(3)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])
    n = np.full(fx["N"], fx["nie_s"] * 2.0) * (1 + 0.02 * rng.standard_normal(fx["N"]))
    p = np.full(fx["N"], fx["nie_s"] * 0.5) * (1 + 0.02 * rng.standard_normal(fx["N"]))

    F_py, J_py, Jn_py, Jp_py = _residual_jacobian_dd3d_py(
        psi, n, p, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
        fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
        fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=False, auger=False)

    flux = fx["eps_trans"] * (psi[j_idx] - psi[i_idx])
    delta = psi[j_idx] - psi[i_idx]
    Bp, Bm = bernoulli(delta), bernoulli(-delta)
    dBp, dBm = dbernoulli(delta), dbernoulli(-delta)

    (F_cpp, r_cpp, c_cpp, v_cpp, Jn_cpp, Jp_cpp) = (
        _accel.core.unstructured3d_residual_jacobian_coupled(
            n, p, fx["C_s"], fx["vols_s"], i_idx.astype(np.int64),
            j_idx.astype(np.int64), fx["eps_trans"], flux, fx["eps_trans"] * fx["LD"],
            fx["D_n_s"], fx["D_p_s"], Bp, Bm, dBp, dBm, fx["nie_s"] * fx["Ns"], fx["tau_n"], fx["tau_p"],
            fx["Ns"], fx["R0"], False, False, fx["material"].Cn_auger,
            fx["material"].Cp_auger))

    import scipy.sparse as sp
    J_cpp = sp.csr_matrix((v_cpp, (r_cpp, c_cpp)), shape=(3 * fx["N"], 3 * fx["N"]))

    assert np.array_equal(F_py, F_cpp)
    assert np.array_equal(Jn_py, Jn_cpp)
    assert np.array_equal(Jp_py, Jp_cpp)
    Jc_py, Jc_cpp = J_py.tocsc(), J_cpp.tocsc()
    assert np.array_equal(Jc_py.indptr, Jc_cpp.indptr)
    assert np.array_equal(Jc_py.indices, Jc_cpp.indices)
    assert np.array_equal(Jc_py.data, Jc_cpp.data)


def test_reproducibility_coupled_kernel_same_input_twice():
    """Same input twice -> bit-identical output -- the one property the
    sole compiled path can still verify against itself, matching
    M43-phase-4's own reproducibility-not-cross-path-parity convention
    for kernels with no surviving pure-Python PRODUCTION fallback (the
    Python function here is a retained ORACLE, not a fallback -- see
    M47-3D-ENGINE-PLAN.md's architectural constraint)."""
    fx = _fixture()
    i_idx, j_idx = fx["edges"][:, 0], fx["edges"][:, 1]
    rng = np.random.default_rng(4)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])
    n = np.full(fx["N"], fx["nie_s"] * 2.0)
    p = np.full(fx["N"], fx["nie_s"] * 0.5)
    flux = fx["eps_trans"] * (psi[j_idx] - psi[i_idx])
    delta = psi[j_idx] - psi[i_idx]
    Bp, Bm = bernoulli(delta), bernoulli(-delta)
    dBp, dBm = dbernoulli(delta), dbernoulli(-delta)

    args = (n, p, fx["C_s"], fx["vols_s"], i_idx.astype(np.int64),
           j_idx.astype(np.int64), fx["eps_trans"], flux, fx["eps_trans"] * fx["LD"],
           fx["D_n_s"], fx["D_p_s"], Bp, Bm, dBp, dBm, fx["nie_s"] * fx["Ns"],
           fx["tau_n"], fx["tau_p"], fx["Ns"], fx["R0"], True, True,
           fx["material"].Cn_auger, fx["material"].Cp_auger)
    out1 = _accel.core.unstructured3d_residual_jacobian_coupled(*args)
    out2 = _accel.core.unstructured3d_residual_jacobian_coupled(*args)
    for a, b in zip(out1, out2):
        assert np.array_equal(a, b)


def test_production_dispatch_equilibrium_matches_oracle():
    """End-to-end check of the PRODUCTION dispatcher itself (the
    non-`_py` `_residual_jacobian_poisson3d`, which flux/n/p Python
    recomputes internally before calling the compiled kernel) against
    the oracle -- not just a direct call to the raw C++ binding as the
    tier-1/2 tests above do. Confirms the wiring in
    unstructured_dd3d.py, not only the kernel."""
    from pytcad.unstructured_dd3d import _residual_jacobian_poisson3d
    fx = _fixture()
    rng = np.random.default_rng(5)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])

    F_py, J_py = _residual_jacobian_poisson3d_py(
        psi, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"], fx["eps_trans"])
    F_prod, J_prod = _residual_jacobian_poisson3d(
        psi, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"], fx["eps_trans"])

    assert np.array_equal(F_py, F_prod)
    Jc_py, Jc_prod = J_py.tocsc(), J_prod.tocsc()
    assert np.array_equal(Jc_py.indptr, Jc_prod.indptr)
    assert np.array_equal(Jc_py.indices, Jc_prod.indices)
    assert np.array_equal(Jc_py.data, Jc_prod.data)


def test_production_dispatch_coupled_matches_oracle():
    from pytcad.unstructured_dd3d import _residual_jacobian_dd3d
    fx = _fixture()
    rng = np.random.default_rng(6)
    psi = np.arcsinh(fx["C_s"] / (2.0 * fx["nie_s"])) + 0.01 * rng.standard_normal(fx["N"])
    n = np.full(fx["N"], fx["nie_s"] * 2.0) * (1 + 0.02 * rng.standard_normal(fx["N"]))
    p = np.full(fx["N"], fx["nie_s"] * 0.5) * (1 + 0.02 * rng.standard_normal(fx["N"]))

    F_py, J_py, Jn_py, Jp_py = _residual_jacobian_dd3d_py(
        psi, n, p, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
        fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
        fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=True, auger=True)
    F_prod, J_prod, Jn_prod, Jp_prod = _residual_jacobian_dd3d(
        psi, n, p, fx["C_s"], fx["nie_s"], fx["vols_s"], fx["edges"],
        fx["eps_trans"], fx["D_n_s"], fx["D_p_s"], fx["R0"], fx["tau_n"],
        fx["tau_p"], fx["material"], fx["Ns"], fx["LD"], srh=True, auger=True)

    assert np.array_equal(F_py, F_prod)
    assert np.array_equal(Jn_py, Jn_prod)
    assert np.array_equal(Jp_py, Jp_prod)
    Jc_py, Jc_prod = J_py.tocsc(), J_prod.tocsc()
    assert np.array_equal(Jc_py.indptr, Jc_prod.indptr)
    assert np.array_equal(Jc_py.indices, Jc_prod.indices)
    assert np.array_equal(Jc_py.data, Jc_prod.data)
