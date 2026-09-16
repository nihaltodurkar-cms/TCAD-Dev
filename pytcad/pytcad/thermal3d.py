"""M43 phase 2 -- steady-state lattice self-heating for Device3D.

Same architecture as thermal.py (1D) and thermal2d.py (2D): device3d.py
is NOT touched -- Device3D shares Device1D/Device2D's exact scalar-T-
at-__init__ scaling, so the same "outer isothermal-DD + Gummel thermal
loop" reasoning that ruled out a monolithic psi/n/p/T Newton coupling
in M19-SELFHEATING-PLAN.md applies unchanged here.

The residual/Jacobian assembly itself is NOT hand-duplicated a third
time: this module is a thin wrapper over thermal_grid.py's
dimension-generic (D=2 or 3) core, the same core thermal2d.py was
refactored onto -- mirrors ii_grid.py/btbt_grid.py's "one kernel for
Device2D and Device3D" pattern (M34-S6). joule_heating_density_3d is
the one genuinely new piece per dimension (it reads device3d.py's own
Jn_x/Jp_x/Jn_y/Jp_y/Jn_z/Jp_z, which thermal_grid.py has no reason to
know about).

Phase 2 scope (M43-SELFHEATING-2D3D-PLAN.md): closes M43's remaining
deferred dimension (2D landed phase 1). Device3D only -- no new physics
constant, no device3d.py edit, same honest limits as 1D/2D (Gummel/
lagged coupling only, no recombination/generation heat, no Seebeck/
Peltier, library-only/no GUI).
"""
import numpy as np

from .mesh2d import control_volume_widths
from .thermal import ThermalBC, ThermalOptions  # noqa: F401 (re-exported)
from .thermal_grid import (
    _residual_jacobian_grid, solve_lattice_temperature_grid,
)


def _residual_jacobian_3d(x, y, z, T, H, material, T_ambient,
                           bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                           bc_z_lo, bc_z_hi):
    """Residual/Jacobian of the steady 3D heat equation on a
    tensor-product mesh (x, y, z) [cm]. T/H shape (Nz, Ny, Nx) --
    device3d.py's own row-major (z, y, x) convention. Thin wrapper over
    thermal_grid._residual_jacobian_grid."""
    return _residual_jacobian_grid(
        [z, y, x], T, H, material, T_ambient,
        [(bc_z_lo, bc_z_hi), (bc_y_lo, bc_y_hi), (bc_x_lo, bc_x_hi)])


def solve_lattice_temperature_3d(x, y, z, H, material, T_ambient,
                                  bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                                  bc_z_lo, bc_z_hi, opts=None):
    """Steady-state 3D lattice temperature [K] on a tensor-product mesh
    (x, y, z) [cm] under heat-source density H(x,y,z) [W/cm^3] (shape
    (Nz,Ny,Nx)), one ThermalBC per box face. Thin wrapper over
    thermal_grid.solve_lattice_temperature_grid."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    return solve_lattice_temperature_grid(
        [z, y, x], H, material, T_ambient,
        [(bc_z_lo, bc_z_hi), (bc_y_lo, bc_y_hi), (bc_x_lo, bc_x_hi)],
        opts=opts)


def joule_heating_density_3d(device):
    """Node-based Joule heating density H(x,y,z) [W/cm^3] (shape
    (Nz,Ny,Nx)) from a converged Device3D solve. Same Wachutka (1990)
    quasi-Fermi-potential-gradient dissipation term as the 1D/2D
    modules (H = Jn.E_n + Jp.E_p, never the raw field), box-integrated
    with device3d.py's own dVy*dVz/dVx*dVz/dVx*dVy flux-divergence
    cross-section convention (device3d.py:993-998) -- not a
    re-derivation, a dual of an already-gated operation."""
    psi, n, p, nie_s = device.psi, device.n, device.p, device.nie_s
    phi_n = psi - np.log(np.maximum(n, 1e-300) / nie_s)
    phi_p = psi + np.log(np.maximum(p, 1e-300) / nie_s)

    hx_phys = device.hx * device.LD
    hy_phys = device.hy * device.LD
    hz_phys = device.hz * device.LD
    dVx_phys = control_volume_widths(hx_phys)
    dVy_phys = control_volume_widths(hy_phys)
    dVz_phys = control_volume_widths(hz_phys)

    E_n_x = -(phi_n[:, :, 1:] - phi_n[:, :, :-1]) * device.VT / hx_phys[None, None, :]
    E_p_x = -(phi_p[:, :, 1:] - phi_p[:, :, :-1]) * device.VT / hx_phys[None, None, :]
    E_n_y = -(phi_n[:, 1:, :] - phi_n[:, :-1, :]) * device.VT / hy_phys[None, :, None]
    E_p_y = -(phi_p[:, 1:, :] - phi_p[:, :-1, :]) * device.VT / hy_phys[None, :, None]
    E_n_z = -(phi_n[1:, :, :] - phi_n[:-1, :, :]) * device.VT / hz_phys[:, None, None]
    E_p_z = -(phi_p[1:, :, :] - phi_p[:-1, :, :]) * device.VT / hz_phys[:, None, None]

    H_edge_x = device.Jn_x * E_n_x + device.Jp_x * E_p_x   # (Nz,Ny,Nx-1)
    H_edge_y = device.Jn_y * E_n_y + device.Jp_y * E_p_y   # (Nz,Ny-1,Nx)
    H_edge_z = device.Jn_z * E_n_z + device.Jp_z * E_p_z   # (Nz-1,Ny,Nx)

    Nz, Ny, Nx = device.Nz, device.Ny, device.Nx
    # half of each edge's total dissipated power (H_edge * edge length *
    # cross-section) goes to each endpoint node, then divide by that
    # node's own physical control-volume, generalizing thermal2d.py's
    # 2D half-edge distribution to the third axis.
    power = np.zeros((Nz, Ny, Nx))
    contrib_x = (0.5 * H_edge_x * hx_phys[None, None, :]
                 * dVy_phys[None, :, None] * dVz_phys[:, None, None])
    power[:, :, :-1] += contrib_x
    power[:, :, 1:] += contrib_x
    contrib_y = (0.5 * H_edge_y * hy_phys[None, :, None]
                 * dVx_phys[None, None, :] * dVz_phys[:, None, None])
    power[:, :-1, :] += contrib_y
    power[:, 1:, :] += contrib_y
    contrib_z = (0.5 * H_edge_z * hz_phys[:, None, None]
                 * dVx_phys[None, None, :] * dVy_phys[None, :, None])
    power[:-1, :, :] += contrib_z
    power[1:, :, :] += contrib_z

    dV_phys = (dVz_phys[:, None, None] * dVy_phys[None, :, None]
               * dVx_phys[None, None, :])
    return power / dV_phys


def solve_electrothermal_3d(build_device, bias, T_ambient,
                             bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                             bc_z_lo, bc_z_hi, material, max_outer=30,
                             tol=1e-3, opts=None, thermal_opts=None):
    """Outer Gummel loop between an isothermal Device3D electrical
    solve and the steady 3D lattice-temperature solve above. Mirrors
    thermal.py's solve_electrothermal / thermal2d.py's
    solve_electrothermal_2d exactly, one dimension up.

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

        H = joule_heating_density_3d(device)
        T_profile = solve_lattice_temperature_3d(
            device.xs * device.LD, device.ys * device.LD,
            device.zs * device.LD, H, material, T_ambient,
            bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi, bc_z_lo, bc_z_hi,
            opts=thermal_opts)

        T_new = float(T_profile.max())
        T_history.append(T_new)
        if abs(T_new - T_candidate) < tol * max(1.0, abs(T_candidate)):
            T_candidate = T_new
            break
        T_candidate = T_new
    else:
        raise RuntimeError(
            "solve_electrothermal_3d outer loop did not converge "
            f"(candidate T still moving after {max_outer} passes: "
            f"{T_history[-3:]})")

    return device, T_profile, T_history
