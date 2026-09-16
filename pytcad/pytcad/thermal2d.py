"""M43 phase 1 -- steady-state lattice self-heating for Device2D.

Same architecture as thermal.py's 1D module (device2d.py itself is NOT
touched -- Device2D's entire scaling framework is built ONCE at
__init__ from a single SCALAR T, exactly like Device1D, so the same
"outer isothermal-DD + Gummel thermal loop" reasoning that ruled out a
monolithic psi/n/p/T Newton coupling in M19-SELFHEATING-PLAN.md applies
unchanged here -- see that plan's "Why not monolithic" section):

1. solve_lattice_temperature_2d(x, y, H, material, T_ambient, bc_x_lo,
   bc_x_hi, bc_y_lo, bc_y_hi): steady-state 2D heat equation,
   -div(kappa_th(T) grad T) = H(x,y), on a tensor-product mesh. Fully
   VECTORIZED assembly (no per-node Python loop) -- thermal.py's own
   1D assembly has the one scalar Python loop ARCHITECTURE.md flags as
   pairing naturally with M31 P4; this module does not repeat it.

2. joule_heating_density_2d(device): the 2D analogue of thermal.py's
   joule_heating_density, using the SAME Wachutka (1990)
   quasi-Fermi-potential-gradient dissipation term (H = Jn.E_n + Jp.E_p,
   never the raw field) -- reuses device.Jn_x/Jp_x/Jn_y/Jp_y (already
   computed by Device2D.solve_bias's own Scharfetter-Gummel assembly)
   and box-integrates onto nodes with the SAME dVy/dVx-weighted
   flux-divergence convention device2d.py's own Poisson/continuity
   residual already uses (_residual_jacobian's div_Jn_x/div_Jn_y
   scatter, device2d.py:977-983) -- not a re-derivation, a dual of an
   already-gated operation.

3. solve_electrothermal_2d(...): the 2D analogue of
   solve_electrothermal -- an outer Gummel loop between the
   (unmodified) Device2D electrical solve and the 2D thermal solve
   above.

Phase 1 scope (M43-SELFHEATING-2D3D-PLAN.md): Device2D only. Device3D
is explicitly deferred to a later phase -- same "N-D first, then N+1-D"
staging M19 itself used (1D landed, 2D explicitly deferred "out of
scope" in that plan's own words; this module delivers that deferred
piece and defers 3D the same way).
"""
import numpy as np

from .mesh2d import control_volume_widths
from .thermal import ThermalBC, ThermalOptions  # noqa: F401 (re-exported)
from .thermal_grid import (
    _residual_jacobian_grid, solve_lattice_temperature_grid,
)


def _residual_jacobian_2d(x, y, T, H, material, T_ambient,
                           bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi):
    """Residual/Jacobian of the steady 2D heat equation on a
    tensor-product mesh (x, y) [cm]. T/H shape (Ny, Nx) -- device2d.py's
    own row-major (y, x) convention. Thin wrapper over
    thermal_grid._residual_jacobian_grid (M43 phase 2): T's axis 0 is
    y, axis 1 is x, so coords/bcs are ordered [y, x] to match."""
    return _residual_jacobian_grid(
        [y, x], T, H, material, T_ambient,
        [(bc_y_lo, bc_y_hi), (bc_x_lo, bc_x_hi)])


def solve_lattice_temperature_2d(x, y, H, material, T_ambient,
                                  bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                                  opts=None):
    """Steady-state 2D lattice temperature [K] on a tensor-product mesh
    (x, y) [cm] under heat-source density H(x,y) [W/cm^3] (shape
    (Ny,Nx)), one ThermalBC per rectangle edge. Thin wrapper over
    thermal_grid.solve_lattice_temperature_grid."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return solve_lattice_temperature_grid(
        [y, x], H, material, T_ambient,
        [(bc_y_lo, bc_y_hi), (bc_x_lo, bc_x_hi)], opts=opts)


def joule_heating_density_2d(device):
    """Node-based Joule heating density H(x,y) [W/cm^3] (shape
    (Ny,Nx)) from a converged Device2D solve. See module docstring --
    same Wachutka quasi-Fermi-potential dissipation term as the 1D
    joule_heating_density, box-integrated with device2d.py's own
    dVy/dVx flux-divergence convention (device2d.py:977-983)."""
    psi, n, p, nie_s = device.psi, device.n, device.p, device.nie_s
    phi_n = psi - np.log(np.maximum(n, 1e-300) / nie_s)
    phi_p = psi + np.log(np.maximum(p, 1e-300) / nie_s)

    hx_phys = device.hx * device.LD
    hy_phys = device.hy * device.LD
    dVx_phys = control_volume_widths(hx_phys)
    dVy_phys = control_volume_widths(hy_phys)

    E_n_x = -(phi_n[:, 1:] - phi_n[:, :-1]) * device.VT / hx_phys[None, :]
    E_p_x = -(phi_p[:, 1:] - phi_p[:, :-1]) * device.VT / hx_phys[None, :]
    E_n_y = -(phi_n[1:, :] - phi_n[:-1, :]) * device.VT / hy_phys[:, None]
    E_p_y = -(phi_p[1:, :] - phi_p[:-1, :]) * device.VT / hy_phys[:, None]

    H_edge_x = device.Jn_x * E_n_x + device.Jp_x * E_p_x   # (Ny, Nx-1)
    H_edge_y = device.Jn_y * E_n_y + device.Jp_y * E_p_y   # (Ny-1, Nx)

    Ny, Nx = device.Ny, device.Nx
    # half of each edge's total dissipated power (H_edge * edge length *
    # cross-section) goes to each endpoint node, then divide by that
    # node's own physical control-volume area -- the 2D generalization
    # of thermal.py's joule_heating_density half-edge distribution.
    power = np.zeros((Ny, Nx))
    contrib_x = 0.5 * H_edge_x * hx_phys[None, :] * dVy_phys[:, None]
    power[:, :-1] += contrib_x
    power[:, 1:] += contrib_x
    contrib_y = 0.5 * H_edge_y * hy_phys[:, None] * dVx_phys[None, :]
    power[:-1, :] += contrib_y
    power[1:, :] += contrib_y

    dV_phys = np.outer(dVy_phys, dVx_phys)
    return power / dV_phys


def solve_electrothermal_2d(build_device, bias, T_ambient,
                             bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                             material, max_outer=30, tol=1e-3, opts=None,
                             thermal_opts=None):
    """Outer Gummel loop between an isothermal Device2D electrical
    solve and the steady 2D lattice-temperature solve above. Mirrors
    thermal.py's solve_electrothermal exactly, one dimension up:
    build_device(T) returns a fresh, unsolved Device2D at scalar T;
    each pass solves equilibrium+bias (unmodified Device2D calls),
    computes 2D Joule heating, solves for T(x,y), and takes its PEAK as
    the next candidate device temperature.

    Returns (device, T_profile, T_history)."""
    thermal_opts = thermal_opts or ThermalOptions()
    T_candidate = float(T_ambient)
    T_history = [T_candidate]
    device = None
    T_profile = None

    for _ in range(max_outer):
        device = build_device(T_candidate)
        device.solve_equilibrium(opts)
        device.solve_bias(bias, opts)

        H = joule_heating_density_2d(device)
        T_profile = solve_lattice_temperature_2d(
            device.xs * device.LD, device.ys * device.LD, H, material,
            T_ambient, bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
            opts=thermal_opts)

        T_new = float(T_profile.max())
        T_history.append(T_new)
        if abs(T_new - T_candidate) < tol * max(1.0, abs(T_candidate)):
            T_candidate = T_new
            break
        T_candidate = T_new
    else:
        raise RuntimeError(
            "solve_electrothermal_2d outer loop did not converge "
            f"(candidate T still moving after {max_outer} passes: "
            f"{T_history[-3:]})")

    return device, T_profile, T_history
