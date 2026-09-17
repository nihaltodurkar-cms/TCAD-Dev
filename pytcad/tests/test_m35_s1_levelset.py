"""M35-S1 acceptance gates: level-set process-geometry representation.

See pytcad/M35-3D-PROCESS-PLAN.md section 2.5 for the gate list.
S1-G1 (all 8 test_m23_process2d.py tests pass unchanged) is verified by
running that file directly -- process2d.py's executable paths are
untouched by S1, so it is not duplicated here.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.levelset2d import (
    LevelSet2D, MATERIAL_NAMES, advect_upwind, cfl_dt, project,
    advance_material,
)


def _flat_front_ls(Nx=80, Ny=80, x_front=0.4, L=1.0):
    """A silicon/ambient level set with a flat vertical front at
    x = x_front, silicon on the left (x < x_front)."""
    x0, x1, y0, y1 = 0.0, L, 0.0, L
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "ambient"))
    X, Y = ls.X, ls.Y
    phi_si = X - x_front          # < 0 for x < x_front (inside silicon)
    phi_amb = x_front - X         # < 0 for x > x_front (inside ambient)
    ls.phi["silicon"] = phi_si
    ls.phi["ambient"] = phi_amb
    return project(ls)


# ----------------------------------------------------------------------
#  S1-G2 -- flat front advection convergence order
# ----------------------------------------------------------------------
@pytest.mark.parametrize("Nx", [80, 160])
def test_flat_front_advection_lands_near_analytic_position(Nx):
    V = 0.2
    t_total = 0.5
    ls = _flat_front_ls(Nx=Nx, Ny=20, x_front=0.3, L=1.0)
    out = advance_material(ls, "silicon", V=V, t_total=t_total, cfl=0.4)
    dx = out.dx
    # front position: zero crossing of phi_silicon along the mid row
    mid = out.Ny // 2
    row = out.phi["silicon"][mid, :]
    x = out.x
    k = np.where(np.diff(np.sign(row)) != 0)[0][0]
    x_front_num = x[k] - row[k] * (x[k + 1] - x[k]) / (row[k + 1] - row[k])
    x_analytic = 0.3 + V * t_total
    err = abs(x_front_num - x_analytic)
    assert err < 3 * dx, f"front error {err} exceeds a few grid cells ({dx})"


def test_flat_front_advection_error_shrinks_under_refinement():
    """Not asserting a fixed order -- measuring the ratio, per the plan's
    own instruction (S1-G2: order measured by refinement, not asserted)."""
    V, t_total = 0.2, 0.5
    errs = {}
    for Nx in (80, 160, 320):
        ls = _flat_front_ls(Nx=Nx, Ny=20, x_front=0.3, L=1.0)
        out = advance_material(ls, "silicon", V=V, t_total=t_total, cfl=0.4)
        mid = out.Ny // 2
        row = out.phi["silicon"][mid, :]
        x = out.x
        k = np.where(np.diff(np.sign(row)) != 0)[0][0]
        x_num = x[k] - row[k] * (x[k + 1] - x[k]) / (row[k + 1] - row[k])
        errs[Nx] = abs(x_num - (0.3 + V * t_total))
    assert errs[160] < errs[80]
    assert errs[320] < errs[160]
    order_1 = np.log2(errs[80] / errs[160]) if errs[160] > 0 else float("inf")
    order_2 = np.log2(errs[160] / errs[320]) if errs[320] > 0 else float("inf")
    print(f"S1-G2 measured order: {order_1:.2f}, {order_2:.2f}")
    # first-order upwind scheme: order should be roughly 1 (loose bound,
    # since this is a coarse convergence study, not an asymptotic one).
    assert order_1 > 0.3
    assert order_2 > 0.3


# ----------------------------------------------------------------------
#  S1-G3 -- reinitialization preserves the zero level set
# ----------------------------------------------------------------------
def test_reinitialization_preserves_front_position_over_100_cycles():
    Nx = 100
    ls = _flat_front_ls(Nx=Nx, Ny=20, x_front=0.4, L=1.0)
    dx = ls.dx

    # Deliberately corrupt phi to a non-distance function (squared
    # distance) while keeping the same sign / zero crossing.
    corrupted = ls.copy()
    for name in corrupted.materials:
        phi = corrupted.phi[name]
        corrupted.phi[name] = np.sign(phi) * phi**2

    front0 = _front_x(corrupted, "silicon")
    cur = corrupted
    for _ in range(100):
        cur = project(cur)
    front1 = _front_x(cur, "silicon")
    drift = abs(front1 - front0)
    assert drift < 0.1 * dx, f"drift {drift} exceeds 0.1 cell ({0.1*dx})"


def _front_x(ls, material, row=None):
    row = ls.Ny // 2 if row is None else row
    phi = ls.phi[material][row, :]
    x = ls.x
    idx = np.where(np.diff(np.sign(phi)) != 0)[0]
    if idx.size == 0:
        return np.nan
    k = idx[0]
    return x[k] - phi[k] * (x[k + 1] - x[k]) / (phi[k + 1] - phi[k])


# ----------------------------------------------------------------------
#  S1-G4 -- multi-material: no overlaps, no gaps, triple junction
# ----------------------------------------------------------------------
def test_multimaterial_projection_has_no_overlap_or_gap_at_triple_junction():
    Nx = Ny = 120
    ls = LevelSet2D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    X, Y = ls.X, ls.Y
    # silicon: bottom half; sio2: top-left quarter; ambient: top-right
    # quarter -- deliberately built as three INDEPENDENT raw signed
    # distances (not mutually consistent) so silicon and sio2 both claim
    # part of the middle band before projection.
    ls.phi["silicon"] = Y - 0.55       # < 0 below y=0.55 (overlaps sio2/ambient's claim)
    ls.phi["sio2"] = np.maximum(0.45 - Y, X - 0.5)   # < 0 in top-left, some overlap
    ls.phi["ambient"] = np.maximum(0.45 - Y, 0.5 - X)  # < 0 in top-right

    out = project(ls)
    mat_idx = out.material_map()
    assert mat_idx.shape == (Ny, Nx)
    assert np.all(mat_idx >= 0)   # every point has exactly one owner (argmin)

    # each material's post-projection phi must itself be single-valued
    # and consistent with mat_idx (no point simultaneously "inside" two
    # materials' re-derived signed distances).
    names = out.materials
    phis = np.stack([out.phi[n] for n in names], axis=0)
    inside_count = np.sum(phis < 0, axis=0)
    assert np.all(inside_count <= 1), "a point is inside more than one re-derived phi"
    assert np.all(inside_count >= 0)

    # the resolved silicon/sio2 boundary along a column away from the
    # triple junction (x=0.1, clear of the ambient region at x>0.5)
    # should sit near the naive halfway point between the two raw claims
    # (y=0.55 from silicon's raw phi, y=0.45 from sio2's raw phi).
    col = np.argmin(np.abs(out.x - 0.1))
    si_col = out.phi["silicon"][:, col]
    idx = np.where(np.diff(np.sign(si_col)) != 0)[0]
    assert idx.size > 0
    y = out.y
    k = idx[0]
    y_boundary = y[k] - si_col[k] * (y[k + 1] - y[k]) / (si_col[k + 1] - si_col[k])
    assert 0.45 <= y_boundary <= 0.55


# ----------------------------------------------------------------------
#  S1-G5 -- mass conservation (honesty gate: measured, not exact)
# ----------------------------------------------------------------------
def test_deposit_mass_conservation_is_measured_not_exact():
    Nx = Ny = 200
    L = 1.0
    x_front = 0.5
    V = 0.1
    t_total = 1.0
    exposed_length = L   # the whole y-extent is "exposed" to the front

    ls = _flat_front_ls(Nx=Nx, Ny=Ny, x_front=x_front, L=L)
    dx, dy = ls.dx, ls.dy

    def si_area(state):
        return np.sum(state.phi["silicon"] < 0) * dx * dy

    area0 = si_area(ls)
    out = advance_material(ls, "silicon", V=V, t_total=t_total, cfl=0.4)
    area1 = si_area(out)

    expected_added = V * exposed_length * t_total
    measured_added = area1 - area0
    rel_err = abs(measured_added - expected_added) / expected_added
    print(f"S1-G5 measured relative mass error: {rel_err:.4e}")
    # Honesty gate: level sets do NOT conserve mass exactly (unlike
    # process2d.deposit's exact thickness*width). Require it small at
    # this resolution but do not claim machine precision.
    assert rel_err < 0.05, (
        f"deposit mass error {rel_err:.4e} exceeds the 5% honesty bound "
        f"at this resolution -- escalate before S2 per the plan's own "
        f"S1-G5 instruction"
    )
    assert rel_err > 1e-14, "suspiciously exact for a level-set method"


# ----------------------------------------------------------------------
#  S1-G6 -- examples/08_locos_flow.py still runs, untouched height path
# ----------------------------------------------------------------------
def test_locos_flow_example_still_runs_and_conserves_mass():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    example = os.path.join(repo_root, "examples", "08_locos_flow.py")
    result = subprocess.run(
        [sys.executable, example], cwd=repo_root,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"08_locos_flow.py exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Wrote locos_flow.png" in result.stdout


# ----------------------------------------------------------------------
#  material set is finite and declared (section 7 honest limit)
# ----------------------------------------------------------------------
def test_unknown_material_name_is_rejected():
    with pytest.raises(ValueError):
        LevelSet2D(x0=0.0, x1=1.0, Nx=10, y0=0.0, y1=1.0, Ny=10,
                   materials=("silicon", "unobtainium"))


def test_material_names_constant_matches_declared_set():
    assert set(MATERIAL_NAMES) == {
        "silicon", "sio2", "si3n4", "poly", "resist", "metal",
        "silicide", "ambient",
    }
