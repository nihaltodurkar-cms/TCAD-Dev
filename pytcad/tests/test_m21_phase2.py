"""M21 phase 2 gates: 2D/3D separable adaptive h-refinement on tensor-product
meshes.

Gate reference: M21-MESHING-PLAN.md section 4 (G1-G9), extended for 2D/3D.
Phase 2 is a PURE ADDITION -- adapt.py consumes Device2D/Device3D through
their public interface and touches no residual, no Jacobian.

The separable limitation is structural and stated: refining one cell
refines an entire row/column, so a localised 2D feature costs O(N) nodes.
That waste is precisely the motivation for phase 3.
"""
import os
import sys
import warnings as warn_module

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad import Device2D, Device3D, Models
from pytcad.mesh import graded_mesh, uniform_mesh
from pytcad.mesh2d import Mesh2D, check_mesh2d
from pytcad.mesh3d import Mesh3D, check_mesh3d
from pytcad import adapt


# ------------------------------------------------------------ helpers
def _build_2d(models=None, na=1e16, nd=1e17, xj=3.0e-4):
    """Return a build_device(mesh) closure for a 2D p-n diode.

    Device2D reshapes its `doping` argument as (Ny, Nx) (device2d.py:123).
    `np.meshgrid(x, y, indexing='ij')` instead produces (Nx, Ny) -- for
    Nx != Ny (true of essentially every mesh here, adaptive or not) a
    flat .reshape(Ny, Nx) on that array silently REINTERPRETS the buffer
    with the wrong axis order rather than raising, corrupting close to
    half the doping array's spatial placement (measured: ~49% of nodes
    end up with the wrong value for their position) while still only
    ever containing the two valid values -na/nd, so nothing about the
    array's CONTENTS looked wrong under casual inspection. Build the
    array directly in (Ny, Nx) order instead -- doping only depends on
    x, so this is a plain 1-D broadcast, no meshgrid needed.
    """
    def build(mesh):
        L = 6.0e-4
        x = np.linspace(0, L, mesh.Nx)
        dop = np.broadcast_to(
            np.where(x[None, :] < xj, -na, nd), (mesh.Ny, mesh.Nx)).copy()
        return Device2D(mesh, dop, T=300.0, models=models or Models())
    return build


def _build_3d(models=None, na=1e16, nd=1e17, xj=3.0e-4):
    """Return a build_device(mesh) closure for a 3D p-n diode (z-invariant).

    Same axis-order bug as _build_2d, one dimension up: Device3D expects
    (Nz, Ny, Nx) (device3d.py:145) but `meshgrid(x, y, z, indexing='ij')`
    produces (Nx, Ny, Nz), corrupting the doping array via the same
    silent reshape whenever Nx != Nz (always, here).
    """
    def build(mesh):
        L = 6.0e-4
        x = np.linspace(0, L, mesh.Nx)
        dop = np.broadcast_to(
            np.where(x[None, None, :] < xj, -na, nd),
            (mesh.Nz, mesh.Ny, mesh.Nx)).copy()
        return Device3D(mesh, dop, T=300.0, models=models or Models())
    return build


def _solve_eq(dev):
    dev.solve_equilibrium()


def _qoi_2d(dev):
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho.ravel()) * dev.mesh.dV))


def _qoi_3d(dev):
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho.ravel()) * dev.mesh.dV))


# ---------------------------------------------------------------- G1
def test_reduce_x_y_returns_correct_shapes():
    """G1 (2D): reduce_x and reduce_y produce arrays of the correct
    length matching the cell counts on each axis."""
    Nx, Ny = 20, 15
    eta_x = np.random.default_rng(0).random((Ny, Nx - 1))
    eta_y = np.random.default_rng(1).random((Ny - 1, Nx))

    rx = adapt.reduce_x(eta_x)
    ry = adapt.reduce_y(eta_y)

    assert rx.shape == (Nx - 1,), f"reduce_x shape mismatch: {rx.shape}"
    assert ry.shape == (Ny - 1,), f"reduce_y shape mismatch: {ry.shape}"


def test_reduce_z_returns_correct_shape():
    """G1 (3D): reduce_z produces an array of length Nz-1.

    The 3D indicator has shape (Nz-1, Ny, Nx) -- one z-cell per
    (y,x) face.  Reduction averages across y and x.
    """
    Nx, Ny, Nz = 10, 8, 6
    eta = np.random.default_rng(2).random((Nz - 1, Ny, Nx))
    rz = adapt.reduce_z(eta)
    assert rz.shape == (Nz - 1,), f"reduce_z shape mismatch: {rz.shape}"


def test_reduce_preserves_mass_order():
    """G1: reduction preserves the relative ordering of indicator mass
    along each axis for a known profile."""
    # x-axis: indicator concentrated near one edge
    Nx, Ny = 30, 20
    eta_x = np.zeros((Ny, Nx - 1))
    # Put high indicator values near x = L/2
    center = (Nx - 1) // 3
    eta_x[:, center:center + 3] = 1.0
    eta_x[:, center - 2:center] = 0.5

    rx = adapt.reduce_x(eta_x)
    # The peak should be near the center
    peak_idx = int(np.argmax(rx))
    assert abs(peak_idx - center) <= 2, \
        f"reduce_x peak {peak_idx} not near expected {center}"


# ---------------------------------------------------------------- G2
def test_adequate_2d_mesh_is_returned_unchanged():
    """G2 (2D): on a mesh that already satisfies every criterion the
    driver stops refining -- same mesh and same solution."""
    L, W = 6.0e-4, 2.0e-4
    # Use a fine uniform mesh so indicators are below threshold.
    x = uniform_mesh(L, 120)
    y = uniform_mesh(W, 80)
    mesh0 = Mesh2D(x, y)

    # Uniform doping so the solution is flat and indicators are near-zero.
    def _build_2d_flat(mesh):
        xx = np.linspace(0, L, mesh.Nx)
        yy = np.linspace(0, W, mesh.Ny)
        xx2, yy2 = np.meshgrid(xx, yy, indexing='ij')
        dop = np.full_like(xx2, 1e15)  # uniform n-type
        return Device2D(mesh, dop, T=300.0, models=Models())

    direct = _build_2d_flat(mesh0)
    direct.solve_equilibrium()

    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d_flat, mesh0, solve=_solve_eq, qoi=_qoi_2d,
        tol=1e-2, max_passes=4)

    assert np.array_equal(mesh.x, mesh0.x), "G2 FAIL: 2D x mesh was modified"
    assert np.array_equal(mesh.y, mesh0.y), "G2 FAIL: 2D y mesh was modified"
    assert np.array_equal(dev.psi, direct.psi), "G2 FAIL: 2D psi differs"
    # The mesh is already adequate, so no refinement should occur.
    assert hist[-1]["marked_x"] == 0 and hist[-1]["marked_y"] == 0, \
        f"G2 FAIL: 2D marked cells on adequate mesh: {hist[-1]}"


def test_adequate_3d_mesh_is_returned_unchanged():
    """G2 (3D): on a mesh that already satisfies every criterion the
    driver is INERT.

    W, D are Debye-scale, not the diode's usual 2.0e-4/1.0e-4 cm: at
    the doping used here (1e16/1e17), the minimum Debye length is
    ~1.29e-6 cm, so ANY uniform y/z mesh across a 2.0e-4 cm width
    violates the h/L_D<=1 constraint everywhere -- the mesh this test
    used to build (ny=50, nz=30 across that width) was never actually
    debye-adequate; it never got caught because the driver crashed
    before reaching this assertion for unrelated reasons.  On top of
    being wrong, it was also a 4,774,620-node mesh that drove
    Device3D's direct spsolve to allocate hundreds of MB of index
    arrays and the host to tens of GB resident.  This domain is
    verified debye-adequate (zero violations on every axis) at 39,060
    nodes -- an actually-inert mesh, not just a case the driver never
    reached.
    """
    L, W, D = 6.0e-4, 1.0e-5, 1.0e-5
    x = graded_mesh(L, [3.0e-4], h_min=1e-7, h_max=1e-6)
    y = uniform_mesh(W, 8)
    z = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x, y, z)

    build = _build_3d()
    direct = build(mesh0)
    direct.solve_equilibrium()

    dev, mesh, hist = adapt.adapt_solve_3d(
        build, mesh0, solve=_solve_eq, qoi=_qoi_3d,
        tol=1e-2, max_passes=4)

    assert np.array_equal(mesh.x, mesh0.x), "G2 FAIL: 3D x mesh was modified"
    assert np.array_equal(mesh.y, mesh0.y), "G2 FAIL: 3D y mesh was modified"
    assert np.array_equal(mesh.z, mesh0.z), "G2 FAIL: 3D z mesh was modified"
    assert np.array_equal(dev.psi, direct.psi), "G2 FAIL: 3D psi differs"
    assert hist[-1]["cause"] == "already_adequate", \
        f"G2 FAIL: 3D terminated on {hist[-1]['cause']!r}"


# ---------------------------------------------------------------- G3
def test_adapted_2d_matches_resolved_reference():
    """G3 (2D): an adapted 2D solution agrees with a resolved reference
    on the built-in potential to within stated tolerance.

    Reference resolution is chosen well above the starting mesh (below)
    but far below phase 1's 1D reference (h_min=5e-9): that value is
    safe as a 1D node count (12020) but tensor-producted across a
    second axis and pushed through Device2D's DIRECT sparse solve it
    is not -- it drove the process to tens of GB of resident memory.
    320-620-node x-references keep the same "resolved reference" intent
    at a DOF count (~1e4) direct spsolve handles without blowing up.
    """
    L, W = 6.0e-4, 2.0e-4
    x_ref = graded_mesh(L, [3.0e-4], h_min=1e-7, h_max=1e-6)
    y_ref = uniform_mesh(W, 15)
    mesh_ref = Mesh2D(x_ref, y_ref)

    build = _build_2d()
    ref = build(mesh_ref)
    ref.solve_equilibrium()

    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    dev, mesh, hist = adapt.adapt_solve_2d(
        build, mesh0, solve=_solve_eq, qoi=_qoi_2d,
        tol=1e-2, max_passes=8, max_nodes=500000)

    vbi_ref = float(ref.psi.max() - ref.psi.min()) * ref.VT
    vbi_ad = float(dev.psi.max() - dev.psi.min()) * dev.VT
    assert abs(vbi_ad - vbi_ref) / vbi_ref <= 5e-2, \
        f"G3 FAIL (2D): Vbi {vbi_ad:.6f} vs reference {vbi_ref:.6f}"

    q_ref, q_ad = _qoi_2d(ref), _qoi_2d(dev)
    assert abs(q_ad - q_ref) / abs(q_ref) <= 1e-1, \
        f"G3 FAIL (2D): QoI {q_ad:.6e} vs reference {q_ref:.6e}"


def test_adapted_3d_matches_resolved_reference():
    """G3 (3D): an adapted 3D solution agrees with a resolved reference
    on the built-in potential.

    See test_adapted_2d_matches_resolved_reference for why the
    reference is NOT phase 1's 1D h_min=5e-9 grading: tensor-producted
    across two extra axes and solved with Device3D's direct spsolve,
    that reference reaches ~4e6 nodes / ~1.2e7 DOF and drove the host
    to tens of GB of resident memory. This coarser reference keeps the
    "well-resolved relative to the starting mesh" intent at a DOF count
    (~1e5) a direct 3D solve can actually handle.
    """
    L, W, D = 6.0e-4, 2.0e-4, 1.0e-4
    x_ref = graded_mesh(L, [3.0e-4], h_min=2e-7, h_max=2e-6)
    y_ref = uniform_mesh(W, 10)
    z_ref = uniform_mesh(D, 8)
    mesh_ref = Mesh3D(x_ref, y_ref, z_ref)

    build = _build_3d()
    ref = build(mesh_ref)
    ref.solve_equilibrium()

    x0 = uniform_mesh(L, 12)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    dev, mesh, hist = adapt.adapt_solve_3d(
        build, mesh0, solve=_solve_eq, qoi=_qoi_3d,
        tol=1e-2, max_passes=6, max_nodes=200000)

    vbi_ref = float(ref.psi.max() - ref.psi.min()) * ref.VT
    vbi_ad = float(dev.psi.max() - dev.psi.min()) * dev.VT
    assert abs(vbi_ad - vbi_ref) / vbi_ref <= 1e-1, \
        f"G3 FAIL (3D): Vbi {vbi_ad:.6f} vs reference {vbi_ref:.6f}"


# ---------------------------------------------------------------- G4
def test_qoi_2d_converges_monotonically():
    """G4 (2D): refinement converges monotonically."""
    L, W = 6.0e-4, 2.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d(), mesh0, solve=_solve_eq, qoi=_qoi_2d,
        tol=1e-2, max_passes=8, max_nodes=500000)

    assert hist[-1]["cause"] == "converged", \
        f"G4 FAIL (2D): did not converge ({hist[-1]['cause']})"
    qs = np.array([h["qoi"] for h in hist])
    assert qs.size >= 3, "G4 FAIL (2D): too few passes"
    deltas = np.abs(np.diff(qs)) / np.abs(qs[1:])
    assert np.all(np.diff(deltas) < 1e-10), \
        f"G4 FAIL (2D): QoI changes not decreasing: {deltas}"
    assert np.all(np.diff([h["nodes"] for h in hist]) > 0), \
        "G4 FAIL (2D): refinement added no nodes"


def test_qoi_3d_converges_monotonically():
    """G4 (3D): refinement converges monotonically.

    W, D are Debye-scale (see test_adequate_3d_mesh_is_returned_unchanged
    for why): at the original W=2.0e-4/D=1.0e-4, every y- and z-cell
    across the WHOLE domain violates the h/L_D<=1 constraint on average
    (adapt_solve_3d's per-axis debye check averages over the other two
    axes), so the driver bisects all three axes fully every pass --
    measured node growth of ~7x/pass, and reaching tol=1e-2 that way
    needs millions of nodes, which a DIRECT 3D solve cannot fit in
    memory (measured: SuperLU's `gssv` runs out of memory around
    ~240,000 nodes on this host). At Debye scale the debye constraint
    is satisfied within a couple of passes and the remaining refinement
    is driven by the (much gentler) curvature/log-density indicator;
    measured to converge cleanly at 65,648 nodes on pass 6.
    """
    L, W, D = 6.0e-4, 1.0e-5, 1.0e-5
    x0 = uniform_mesh(L, 10)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    dev, mesh, hist = adapt.adapt_solve_3d(
        _build_3d(), mesh0, solve=_solve_eq, qoi=_qoi_3d,
        tol=1e-2, max_passes=8, max_nodes=100000)

    assert hist[-1]["cause"] == "converged", \
        f"G4 FAIL (3D): did not converge ({hist[-1]['cause']})"
    qs = np.array([h["qoi"] for h in hist])
    assert qs.size >= 3, "G4 FAIL (3D): too few passes"
    deltas = np.abs(np.diff(qs)) / np.abs(qs[1:])
    assert np.all(np.diff(deltas) < 1e-10), \
        f"G4 FAIL (3D): QoI changes not decreasing: {deltas}"


# ---------------------------------------------------------------- G5
def test_2d_separable_refinement_adds_nodes():
    """G5 (2D): when the physics has separated scales, 2D refinement
    adds nodes and the mesh grows.

    na=1e18 gives a minimum Debye length of ~4.1e-7 cm; the debye
    constraint is checked as a Y-CELL AVERAGE across the full x-width
    (adapt_solve_2d's `debye_y.mean(axis=1)`), so once any real share of
    the 1.0e-3 cm domain sits in the na=1e18 region, y needs comparably
    fine resolution too, not just a thin x-band at the junction.
    Measured (see the driver's own history): this genuinely converges
    at ~5.6e5 nodes, not because of a design flaw but because of how
    demanding this doping/domain combination actually is -- the
    original max_nodes=200000 was budgeted before the doping-array
    axis-order bug (see _build_2d/_build_3d) was fixed; against the
    corrupted doping it apparently converged early by accident.
    """
    L, W = 1.0e-3, 2.0e-4
    x0 = uniform_mesh(L, 20)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d(na=1e18, nd=1e15), mesh0, solve=_solve_eq,
        qoi=_qoi_2d, tol=1e-2, max_passes=12, max_nodes=700000)

    assert mesh.N > mesh0.N, \
        f"G5 FAIL (2D): mesh did not grow ({mesh0.N} -> {mesh.N})"
    assert hist[-1]["cause"] == "converged", \
        f"G5 FAIL (2D): did not converge ({hist[-1]['cause']})"


def test_3d_separable_refinement_adds_nodes():
    """G5 (3D): when the physics has separated scales, 3D refinement
    adds nodes."""
    L, W, D = 1.0e-3, 2.0e-4, 1.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    dev, mesh, hist = adapt.adapt_solve_3d(
        _build_3d(na=1e18, nd=1e15), mesh0, solve=_solve_eq,
        qoi=_qoi_3d, tol=1e-2, max_passes=6, max_nodes=100000)

    assert mesh.N > mesh0.N, \
        f"G5 FAIL (3D): mesh did not grow ({mesh0.N} -> {mesh.N})"


# ---------------------------------------------------------------- G6
def test_2d_refinement_invariants():
    """G6 (2D): refined 2D mesh satisfies invariants."""
    L, W = 6.0e-4, 2.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d(), mesh0, solve=_solve_eq, qoi=_qoi_2d,
        tol=1e-2, max_passes=6, max_nodes=100000)

    # Nodes strictly increasing on each axis
    assert np.all(np.diff(mesh.x) > 0), "2D: x nodes not increasing"
    assert np.all(np.diff(mesh.y) > 0), "2D: y nodes not increasing"
    # Endpoints preserved
    assert mesh.x[0] == 0.0 and mesh.x[-1] == L, "2D: x endpoints not preserved"
    assert mesh.y[0] == 0.0 and mesh.y[-1] == W, "2D: y endpoints not preserved"
    # All original nodes retained
    assert np.all(np.isin(mesh0.x, mesh.x)), \
        "2D: an input x node was dropped"
    assert np.all(np.isin(mesh0.y, mesh.y)), \
        "2D: an input y node was dropped"


def test_3d_refinement_invariants():
    """G6 (3D): refined 3D mesh satisfies invariants."""
    L, W, D = 6.0e-4, 2.0e-4, 1.0e-4
    x0 = uniform_mesh(L, 10)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    dev, mesh, hist = adapt.adapt_solve_3d(
        _build_3d(), mesh0, solve=_solve_eq, qoi=_qoi_3d,
        tol=1e-2, max_passes=4, max_nodes=50000)

    assert np.all(np.diff(mesh.x) > 0), "3D: x nodes not increasing"
    assert np.all(np.diff(mesh.y) > 0), "3D: y nodes not increasing"
    assert np.all(np.diff(mesh.z) > 0), "3D: z nodes not increasing"
    assert mesh.x[0] == 0.0 and mesh.x[-1] == L, "3D: x endpoints"
    assert mesh.y[0] == 0.0 and mesh.y[-1] == W, "3D: y endpoints"
    assert mesh.z[0] == 0.0 and mesh.z[-1] == D, "3D: z endpoints"


def test_2d_grading_never_worsens():
    """G6 (2D): refinement never makes grading worse than the input."""
    L, W = 6.0e-4, 2.0e-4
    x0 = graded_mesh(L, [3.0e-4], h_min=2e-8, h_max=2e-7)
    y0 = uniform_mesh(W, 50)
    mesh0 = Mesh2D(x0, y0)

    h0_x = np.diff(mesh0.x)
    h0_y = np.diff(mesh0.y)
    g0_x = np.maximum(h0_x[1:] / h0_x[:-1], h0_x[:-1] / h0_x[1:]).max() \
        if h0_x.size > 1 else 1.0
    g0_y = np.maximum(h0_y[1:] / h0_y[:-1], h0_y[:-1] / h0_y[1:]).max() \
        if h0_y.size > 1 else 1.0

    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d(), mesh0, solve=_solve_eq, qoi=_qoi_2d,
        tol=1e-2, max_passes=6, max_nodes=100000)

    hx = np.diff(mesh.x)
    hy = np.diff(mesh.y)
    gx = np.maximum(hx[1:] / hx[:-1], hx[:-1] / hx[1:]).max() if hx.size > 1 else 1.0
    gy = np.maximum(hy[1:] / hy[:-1], hy[:-1] / hy[1:]).max() if hy.size > 1 else 1.0

    assert gx <= max(2.0, g0_x) + 1e-9, \
        f"2D: x grading {gx:.4f} worse than input {g0_x:.4f}"
    assert gy <= max(2.0, g0_y) + 1e-9, \
        f"2D: y grading {gy:.4f} worse than input {g0_y:.4f}"


# ---------------------------------------------------------------- G7
def test_driver_2d_preserves_physics_flag():
    """G7 (2D): the driver reproduces the physics it was handed.

    W is deliberately Debye-scale (not the diode's 2.0e-4 cm width used
    elsewhere): at that width and this doping, h_y/L_D <= 1 needs y0
    resolved to a similar node count as x0, and the original
    (h_min=2e-8, h_max=2e-7, ny=50) combination started ABOVE its own
    max_nodes=100000 budget -- refine_2d's budget check then reverted
    every attempted refinement, forcing cause="max_nodes" and failing
    the assertion below.  This combination is verified debye-adequate
    with zero violations at only 5580 nodes.
    """
    L, W = 6.0e-4, 1.0e-5
    x0 = graded_mesh(L, [3.0e-4], h_min=1e-7, h_max=1e-6)
    y0 = uniform_mesh(W, 8)
    mesh0 = Mesh2D(x0, y0)

    models = Models(srh=True, tat=True)
    dev, mesh, hist = adapt.adapt_solve_2d(
        _build_2d(models=models), mesh0, solve=_solve_eq,
        qoi=_qoi_2d, tol=1e-3, max_passes=6, max_nodes=100000)

    assert hist[-1]["cause"] in ("already_adequate", "converged")
    for flag in ("srh", "tat"):
        assert getattr(dev.models, flag) is True, \
            f"G7 FAIL (2D): {flag} lost"


def test_driver_3d_preserves_physics_flag():
    """G7 (3D): the driver reproduces the physics it was handed.

    See test_driver_2d_preserves_physics_flag: the original
    (h_min=2e-8, h_max=2e-7, W=2e-4/ny=50, D=1e-4/nz=30) combination
    produced a 4,774,620-node starting mesh -- Device3D's direct
    spsolve on that tried to allocate hundreds of MB just for the
    Jacobian's index arrays and drove the host to tens of GB resident.
    This Debye-scale domain is verified debye-adequate (zero
    violations) at 39,060 nodes.
    """
    L, W, D = 6.0e-4, 1.0e-5, 1.0e-5
    x0 = graded_mesh(L, [3.0e-4], h_min=1e-7, h_max=1e-6)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    models = Models(srh=True)
    dev, mesh, hist = adapt.adapt_solve_3d(
        _build_3d(models=models), mesh0, solve=_solve_eq,
        qoi=_qoi_3d, tol=1e-3, max_passes=4, max_nodes=50000)

    assert hist[-1]["cause"] in ("already_adequate", "converged")
    assert getattr(dev.models, "srh") is True, "G7 FAIL (3D): srh lost"


# ---------------------------------------------------------------- G8
def test_2d_node_budget_warns():
    """G8 (2D): a budget-limited run warns and records cause."""
    L, W = 6.0e-4, 2.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    with pytest.warns(UserWarning, match="node budget"):
        dev, mesh, hist = adapt.adapt_solve_2d(
            _build_2d(), mesh0, solve=_solve_eq, qoi=_qoi_2d,
            tol=1e-14, max_passes=8, max_nodes=mesh0.N + 50)

    assert hist[-1]["cause"] == "max_nodes", \
        f"G8 FAIL (2D): cause recorded as {hist[-1]['cause']!r}"


def test_3d_node_budget_warns():
    """G8 (3D): a budget-limited run warns and records cause."""
    L, W, D = 6.0e-4, 2.0e-4, 1.0e-4
    x0 = uniform_mesh(L, 10)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    with pytest.warns(UserWarning, match="node budget"):
        dev, mesh, hist = adapt.adapt_solve_3d(
            _build_3d(), mesh0, solve=_solve_eq, qoi=_qoi_3d,
            tol=1e-14, max_passes=6, max_nodes=mesh0.N + 20)

    assert hist[-1]["cause"] == "max_nodes", \
        f"G8 FAIL (3D): cause recorded as {hist[-1]['cause']!r}"


def test_2d_pass_limit_warns():
    """The other non-converged exit must be equally loud."""
    L, W = 6.0e-4, 2.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    with pytest.warns(UserWarning, match="pass limit"):
        dev, mesh, hist = adapt.adapt_solve_2d(
            _build_2d(), mesh0, solve=_solve_eq, qoi=_qoi_2d,
            tol=1e-14, max_passes=2, max_nodes=10**6)

    assert hist[-1]["cause"] == "max_passes"


# ---------------------------------------------------------------- G9
def test_non_finite_2d_is_refused():
    """A NaN in the QoI must stop the driver loudly."""
    L, W = 6.0e-4, 2.0e-4
    x0 = uniform_mesh(L, 15)
    y0 = uniform_mesh(W, 10)
    mesh0 = Mesh2D(x0, y0)

    def bad_qoi(dev):
        return float("nan")

    with pytest.raises(ValueError, match="quantity of interest"):
        adapt.adapt_solve_2d(_build_2d(), mesh0, solve=_solve_eq,
                             qoi=bad_qoi, max_passes=2)


def test_non_finite_3d_is_refused():
    """A NaN in the QoI must stop the 3D driver loudly."""
    L, W, D = 6.0e-4, 2.0e-4, 1.0e-4
    x0 = uniform_mesh(L, 10)
    y0 = uniform_mesh(W, 8)
    z0 = uniform_mesh(D, 6)
    mesh0 = Mesh3D(x0, y0, z0)

    def bad_qoi(dev):
        return float("nan")

    with pytest.raises(ValueError, match="quantity of interest"):
        adapt.adapt_solve_3d(_build_3d(), mesh0, solve=_solve_eq,
                             qoi=bad_qoi, max_passes=2)


# ------------------------------------------------------- layering pin
def test_adapt_module_layering_2d_3d():
    """adapt.py is a driver ABOVE the core: the core must not import it,
    and it must not reach sideways into workbench or gui."""
    import inspect
    src = inspect.getsource(adapt)
    assert "workbench" not in src and "import gui" not in src, \
        "adapt.py must not depend on workbench or gui"
    import pytcad.device2d as core2d
    import pytcad.device3d as core3d
    assert "import adapt" not in inspect.getsource(core2d), \
        "Device2D must not import the adaptive driver"
    assert "import adapt" not in inspect.getsource(core3d), \
        "Device3D must not import the adaptive driver"


def test_refine_2d_preserves_input_nodes():
    """refine_2d: every input node survives (phase 1-2 never coarsen)."""
    L, W = 6.0e-4, 2.0e-4
    x0 = np.array([0.0, 1.0e-4, 3.0e-4, 4.0e-4, 6.0e-4])
    y0 = np.array([0.0, 5.0e-5, 1.0e-4, 2.0e-4])
    mesh0 = Mesh2D(x0, y0)

    marked_x = np.array([0, 2], dtype=int)
    marked_y = np.array([1], dtype=int)

    mesh_new = adapt.refine_2d(mesh0, marked_x, marked_y, ratio=2.0)

    assert np.all(np.isin(mesh0.x, mesh_new.x)), \
        "refine_2d: input x nodes were dropped"
    assert np.all(np.isin(mesh0.y, mesh_new.y)), \
        "refine_2d: input y nodes were dropped"
    assert mesh_new.N > mesh0.N, \
        "refine_2d: mesh did not grow"


def test_refine_3d_preserves_input_nodes():
    """refine_3d: every input node survives."""
    L, W, D = 6.0e-4, 2.0e-4, 1.0e-4
    x0 = np.array([0.0, 2.0e-4, 4.0e-4, 6.0e-4])
    y0 = np.array([0.0, 1.0e-4, 2.0e-4])
    z0 = np.array([0.0, 5.0e-5, 1.0e-4])
    mesh0 = Mesh3D(x0, y0, z0)

    marked_x = np.array([1], dtype=int)
    marked_y = np.array([0], dtype=int)
    marked_z = np.array([], dtype=int)

    mesh_new = adapt.refine_3d(mesh0, marked_x, marked_y, marked_z, ratio=2.0)

    assert np.all(np.isin(mesh0.x, mesh_new.x)), \
        "refine_3d: input x nodes were dropped"
    assert np.all(np.isin(mesh0.y, mesh_new.y)), \
        "refine_3d: input y nodes were dropped"
    assert np.all(np.isin(mesh0.z, mesh_new.z)), \
        "refine_3d: input z nodes were dropped"
    assert mesh_new.N > mesh0.N, \
        "refine_3d: mesh did not grow"


def test_2d_separable_refinement_is_wasteful_on_localised_feature():
    """G5 (converse, stated honestly): phase 2's separable refinement
    refines an entire row/column when only one cell needs it.

    This is the structural limitation that motivates phase 3.
    """
    L, W = 6.0e-4, 2.0e-4
    # Very coarse mesh
    x0 = uniform_mesh(L, 8)
    y0 = uniform_mesh(W, 6)
    mesh0 = Mesh2D(x0, y0)

    # Mark only ONE cell in x
    marked_x = np.array([3], dtype=int)
    marked_y = np.array([], dtype=int)

    mesh_new = adapt.refine_2d(mesh0, marked_x, marked_y, ratio=2.0)

    # The x axis should have grown (one cell bisected + grading)
    assert mesh_new.Nx > mesh0.Nx, \
        "separable refinement should grow x axis"
    # The y axis should be unchanged (nothing marked along y)
    assert mesh_new.Ny == mesh0.Ny, \
        "separable refinement should not grow y when nothing marked"
    # But total nodes grew due to the x refinement
    assert mesh_new.N > mesh0.N, \
        "total node count should grow"
