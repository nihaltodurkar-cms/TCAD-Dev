"""M47 Slice 2a: raw-COO parity between device3d.py's own Python
oracle block functions (_poisson_flux_row_coo, _electron_continuity_coo,
_hole_continuity_coo, _base_diagonal_coo -- kept as validation
reference only, NOT production fallback, see M47-3D-ENGINE-PLAN.md's
architectural constraint) and the compiled
pytcad._core.device3d_{poisson_flux_row,electron_continuity,
hole_continuity,base_diagonal} kernels.

Unlike M47 Slice 1's unstructured module, these 4 blocks are
flag-independent (they stamp whatever derivative arrays are handed to
them -- fd/incomplete_ion affect the VALUES computed upstream in
Python, not which code stamps them), so ANY device fixture exercises
the same kernel code; a plain diode is enough, plus a synthetic
incomplete_ion=True case for base_diagonal's other branch.
"""
import numpy as np
import pytest

from pytcad import _accel
from pytcad.device3d import (
    Device3D, Mesh3D, _poisson_flux_row_coo, _electron_continuity_coo,
    _hole_continuity_coo, _base_diagonal_coo, _edge_pairs_x, _edge_pairs_y,
    _edge_pairs_z)
from pytcad.mesh import uniform_mesh

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL,
                                reason="pytcad._core not built")


def _fixture():
    n = 8
    xs = uniform_mesh(1.0e-4, n)
    mesh = Mesh3D(xs, xs.copy(), uniform_mesh(0.6e-4, n))
    Z, Y, X = np.meshgrid(mesh.z, mesh.y, mesh.x, indexing="ij")
    doping = np.where(Z < 0.2e-4, 1e19, -1e17)
    dev = Device3D(mesh, doping.ravel())
    dev.add_contact(
        "left", i=[0], j=list(range(mesh.y.size)) * mesh.z.size,
        k=[k for k in range(mesh.z.size) for _ in range(mesh.y.size)], V=0.0)
    dev.solve_equilibrium()

    Nx, Ny, Nz = dev.Nx, dev.Ny, dev.Nz
    hx, hy, hz = dev.hx, dev.hy, dev.hz
    dVx, dVy, dVz = dev.dVx, dev.dVy, dev.dVz
    kLx, kRx = _edge_pairs_x(Nx, Ny, Nz)
    kSy, kNy = _edge_pairs_y(Nx, Ny, Nz)
    kDz, kUz = _edge_pairs_z(Nx, Ny, Nz)
    wx_area = np.broadcast_to(dVy[None, :, None] * dVz[:, None, None], (Nz, Ny, Nx - 1))
    wy_area = np.broadcast_to(dVx[None, None, :] * dVz[:, None, None], (Nz, Ny - 1, Nx))
    wz_area = np.broadcast_to(dVx[None, None, :] * dVy[None, :, None], (Nz - 1, Ny, Nx))
    wx_h = wx_area * dev.et_x / hx[None, None, :]
    wy_h = wy_area * dev.et_y / hy[None, :, None]
    wz_h = wz_area * dev.et_z / hz[:, None, None]
    return dict(dev=dev, kLx=kLx, kRx=kRx, kSy=kSy, kNy=kNy, kDz=kDz, kUz=kUz,
               wx_area=wx_area, wy_area=wy_area, wz_area=wz_area,
               wx_h=wx_h, wy_h=wy_h, wz_h=wz_h)


def test_poisson_flux_row_matches_oracle():
    fx = _fixture()
    py = _poisson_flux_row_coo(fx["kLx"], fx["kRx"], fx["wx_h"],
                               fx["kSy"], fx["kNy"], fx["wy_h"],
                               fx["kDz"], fx["kUz"], fx["wz_h"])
    cpp = _accel.core.device3d_poisson_flux_row(
        fx["kLx"], fx["kRx"], fx["wx_h"].ravel(),
        fx["kSy"], fx["kNy"], fx["wy_h"].ravel(),
        fx["kDz"], fx["kUz"], fx["wz_h"].ravel())
    for a, b in zip(py, cpp):
        assert np.array_equal(a, b)


def test_electron_and_hole_continuity_match_oracle():
    fx = _fixture()
    rng = np.random.default_rng(1)
    args = {}
    for axis, w in (("x", fx["wx_area"]), ("y", fx["wy_area"]), ("z", fx["wz_area"])):
        args[f"dpsiR_{axis}"] = rng.standard_normal(w.shape)
        args[f"dL_{axis}"] = rng.standard_normal(w.shape)
        args[f"dR_{axis}"] = rng.standard_normal(w.shape)

    py = _electron_continuity_coo(
        fx["kLx"], fx["kRx"], fx["wx_area"], args["dpsiR_x"], args["dL_x"], args["dR_x"],
        fx["kSy"], fx["kNy"], fx["wy_area"], args["dpsiR_y"], args["dL_y"], args["dR_y"],
        fx["kDz"], fx["kUz"], fx["wz_area"], args["dpsiR_z"], args["dL_z"], args["dR_z"])
    cpp = _accel.core.device3d_electron_continuity(
        fx["kLx"], fx["kRx"], fx["wx_area"].ravel(), args["dpsiR_x"].ravel(),
        args["dL_x"].ravel(), args["dR_x"].ravel(),
        fx["kSy"], fx["kNy"], fx["wy_area"].ravel(), args["dpsiR_y"].ravel(),
        args["dL_y"].ravel(), args["dR_y"].ravel(),
        fx["kDz"], fx["kUz"], fx["wz_area"].ravel(), args["dpsiR_z"].ravel(),
        args["dL_z"].ravel(), args["dR_z"].ravel())
    for a, b in zip(py, cpp):
        assert np.array_equal(a, b)

    py_h = _hole_continuity_coo(
        fx["kLx"], fx["kRx"], fx["wx_area"], args["dpsiR_x"], args["dL_x"], args["dR_x"],
        fx["kSy"], fx["kNy"], fx["wy_area"], args["dpsiR_y"], args["dL_y"], args["dR_y"],
        fx["kDz"], fx["kUz"], fx["wz_area"], args["dpsiR_z"], args["dL_z"], args["dR_z"])
    cpp_h = _accel.core.device3d_hole_continuity(
        fx["kLx"], fx["kRx"], fx["wx_area"].ravel(), args["dpsiR_x"].ravel(),
        args["dL_x"].ravel(), args["dR_x"].ravel(),
        fx["kSy"], fx["kNy"], fx["wy_area"].ravel(), args["dpsiR_y"].ravel(),
        args["dL_y"].ravel(), args["dR_y"].ravel(),
        fx["kDz"], fx["kUz"], fx["wz_area"].ravel(), args["dpsiR_z"].ravel(),
        args["dL_z"].ravel(), args["dR_z"].ravel())
    for a, b in zip(py_h, cpp_h):
        assert np.array_equal(a, b)


def test_base_diagonal_both_branches_match_oracle():
    fx = _fixture()
    dev = fx["dev"]
    N = dev.N
    dV = dev.dV
    rng = np.random.default_rng(2)
    dRs_dn = rng.random(dV.shape)
    dRs_dp = rng.random(dV.shape)
    diag_k = np.arange(N)

    py_off = _base_diagonal_coo(diag_k, dV, None, None, dRs_dn, dRs_dp)
    cpp_off = _accel.core.device3d_base_diagonal(
        N, dV.ravel(), False, np.zeros(0), np.zeros(0),
        dRs_dn.ravel(), dRs_dp.ravel())
    for a, b in zip(py_off, cpp_off):
        assert np.array_equal(a, b)

    dcden = rng.random(dV.shape)
    dcdp = rng.random(dV.shape)
    py_on = _base_diagonal_coo(diag_k, dV, dcden, dcdp, dRs_dn, dRs_dp)
    cpp_on = _accel.core.device3d_base_diagonal(
        N, dV.ravel(), True, dcden.ravel(), dcdp.ravel(),
        dRs_dn.ravel(), dRs_dp.ravel())
    for a, b in zip(py_on, cpp_on):
        assert np.array_equal(a, b)


def test_reproducibility_same_input_twice():
    fx = _fixture()
    args = (fx["kLx"], fx["kRx"], fx["wx_h"].ravel(), fx["kSy"], fx["kNy"],
           fx["wy_h"].ravel(), fx["kDz"], fx["kUz"], fx["wz_h"].ravel())
    out1 = _accel.core.device3d_poisson_flux_row(*args)
    out2 = _accel.core.device3d_poisson_flux_row(*args)
    for a, b in zip(out1, out2):
        assert np.array_equal(a, b)
