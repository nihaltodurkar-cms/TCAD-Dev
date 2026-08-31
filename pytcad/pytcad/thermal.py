"""M19 phase 1 -- steady-state lattice self-heating for Device1D.

Two pieces, both new sibling modules to device.py (device.py itself is
NOT touched -- see M19-SELFHEATING-PLAN.md for why a fully monolithic
psi/n/p/T Newton coupling was rejected: Device1D's entire scaling
framework (VT, Ns, LD, J0, mu_n0/mu_p0, nie, tau_n/tau_p, ...) is built
ONCE at __init__ from a single SCALAR T and used as fixed arrays
throughout every Newton solve -- making T a genuine per-node coupled
unknown would mean rearchitecting that whole framework, a far larger
undertaking than the acceptance gates require):

1. solve_lattice_temperature(x, H, material, T_ambient, bc_left,
   bc_right): a standalone steady-state 1D heat equation solve,
   -d/dx(kappa_th(T) dT/dx) = H(x), genuinely nonlinear because
   kappa_th depends on T (materials.Semiconductor.kappa_th) -- its own
   small Newton system, FD-Jacobian gated on its own terms.

2. solve_electrothermal(...): an OUTER Gummel loop between the
   (unmodified, isothermal) Device1D electrical solve and the thermal
   solve above -- the standard "isothermal DD + outer thermal loop"
   architecture many production TCAD tools offer, chosen deliberately
   here (not a shortcut around a known-bad pattern the way M20's DG
   lagging was -- see the plan doc's Honest Limits).
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve


class ThermalBC:
    """One boundary's thermal condition.

    ThermalBC.isothermal() -- Dirichlet T = T_ambient.
    ThermalBC.resistance(R_th_area) -- Robin: heat flux out of the rod
    at this boundary equals (T_boundary - T_ambient) / R_th_area
    [W/cm^2], R_th_area in K*cm^2/W.
    """

    def __init__(self, kind, R_th_area=None):
        if kind not in ("isothermal", "resistance"):
            raise ValueError(f"unknown ThermalBC kind {kind!r}")
        if kind == "resistance" and (R_th_area is None or R_th_area <= 0.0):
            raise ValueError("resistance BC needs R_th_area > 0")
        self.kind = kind
        self.R_th_area = R_th_area

    @classmethod
    def isothermal(cls):
        return cls("isothermal")

    @classmethod
    def resistance(cls, R_th_area):
        return cls("resistance", R_th_area)


class ThermalOptions:
    def __init__(self, max_iter=200, tol=1e-8, max_dT=50.0):
        self.max_iter = max_iter
        self.tol = tol
        self.max_dT = max_dT


def _thermal_residual_jacobian(x, T, H, material, T_ambient, bc_left, bc_right):
    """Residual/Jacobian of the steady 1D heat equation on mesh x [cm].

    kappa_edge[i] = material.kappa_th(0.5*(T[i]+T[i+1])) (edge-averaged
    temperature, the simplest consistent choice); H is a node-based
    heat-source density [W/cm^3], already box-integrated by the caller
    is NOT required -- this function does the dV weighting itself, the
    same way device.py's own Poisson row does with dV*rho.
    """
    N = len(x)
    h = np.diff(x)
    dV = np.empty(N)
    dV[1:-1] = 0.5 * (h[:-1] + h[1:])
    dV[0] = 0.5 * h[0]
    dV[-1] = 0.5 * h[-1]

    Tavg = 0.5 * (T[:-1] + T[1:])
    ke = material.kappa_th(Tavg)                       # edge kappa, len N-1
    dke_dTavg = ke * (-1.33 / Tavg)                     # d(kappa)/dTavg
    dke_dT_each = 0.5 * dke_dTavg                       # chain rule, per node

    F = np.zeros(N)
    rows, cols, vals = [], [], []

    def add(r, c, v):
        rows.append(r); cols.append(c); vals.append(v)

    # ---- left boundary ----
    if bc_left.kind == "isothermal":
        F[0] = T[0] - T_ambient
        add(0, 0, 1.0)
    else:
        Rth = bc_left.R_th_area
        F[0] = ke[0] * (T[1] - T[0]) / h[0] - (T[0] - T_ambient) / Rth + H[0] * dV[0]
        add(0, 0, dke_dT_each[0] * (T[1] - T[0]) / h[0] - ke[0] / h[0] - 1.0 / Rth)
        add(0, 1, dke_dT_each[0] * (T[1] - T[0]) / h[0] + ke[0] / h[0])

    # ---- right boundary ----
    if bc_right.kind == "isothermal":
        F[N - 1] = T[N - 1] - T_ambient
        add(N - 1, N - 1, 1.0)
    else:
        Rth = bc_right.R_th_area
        F[N - 1] = (-ke[-1] * (T[N - 1] - T[N - 2]) / h[-1]
                    - (T[N - 1] - T_ambient) / Rth + H[N - 1] * dV[N - 1])
        add(N - 1, N - 1,
            -dke_dT_each[-1] * (T[N - 1] - T[N - 2]) / h[-1] - ke[-1] / h[-1] - 1.0 / Rth)
        add(N - 1, N - 2,
            -dke_dT_each[-1] * (T[N - 1] - T[N - 2]) / h[-1] + ke[-1] / h[-1])

    # ---- interior nodes ----
    for i in range(1, N - 1):
        keR, keL = ke[i], ke[i - 1]
        dkeR_dTi, dkeR_dTip1 = dke_dT_each[i], dke_dT_each[i]
        dkeL_dTim1, dkeL_dTi = dke_dT_each[i - 1], dke_dT_each[i - 1]

        F[i] = (keR * (T[i + 1] - T[i]) / h[i]
                - keL * (T[i] - T[i - 1]) / h[i - 1]
                + H[i] * dV[i])

        d_dTim1 = (keL - dkeL_dTim1 * (T[i] - T[i - 1])) / h[i - 1]
        d_dTi = (dkeR_dTi * (T[i + 1] - T[i]) / h[i] - keR / h[i]
                 - (dkeL_dTi * (T[i] - T[i - 1]) + keL) / h[i - 1])
        d_dTip1 = (keR + dkeR_dTip1 * (T[i + 1] - T[i])) / h[i]

        add(i, i - 1, d_dTim1)
        add(i, i, d_dTi)
        add(i, i + 1, d_dTip1)

    J = sp.csr_matrix((vals, (rows, cols)), shape=(N, N))
    return F, J


def solve_lattice_temperature(x, H, material, T_ambient, bc_left, bc_right,
                               opts=None):
    """Steady-state 1D lattice temperature [K] on mesh x [cm] under
    heat-source density H(x) [W/cm^3], with a ThermalBC at each end.

    kappa_th(T) is nonlinear in T, so this is a genuine (small) Newton
    solve, gated with its own FD-Jacobian check
    (tests/test_m19_thermal.py G-FD).
    """
    opts = opts or ThermalOptions()
    N = len(x)
    x = np.asarray(x, dtype=float)
    H = np.asarray(H, dtype=float)
    T = np.full(N, float(T_ambient))

    for _ in range(opts.max_iter):
        F, J = _thermal_residual_jacobian(x, T, H, material, T_ambient,
                                          bc_left, bc_right)
        d = spsolve(J.tocsc(), -F)
        d = np.clip(d, -opts.max_dT, opts.max_dT)
        T = T + d
        if np.abs(d).max() < opts.tol:
            break
    else:
        raise RuntimeError(
            "solve_lattice_temperature did not converge "
            f"(|dT| still {np.abs(d).max():.3e} K at the iteration cap)")
    return T


def joule_heating_density(device):
    """Node-based Joule heating density H(x) [W/cm^3] from a converged
    Device1D solve.

    H_edge = Jn*E_n + Jp*E_p, where E_n = -grad(phi_n), E_p =
    -grad(phi_p) are the QUASI-FERMI-POTENTIAL gradients (Wachutka
    1990's electrical dissipation term -- no recombination/generation
    or Peltier/Seebeck heat, see M19-SELFHEATING-PLAN.md Honest
    Limits), NOT the raw electric field E=-grad(psi). This matters:
    an earlier version of this function used device.E_field directly
    (Jn+Jp)*E_field, which reduces to the same thing ONLY where
    diffusion is negligible (a uniform resistor, where G-PARABOLA's
    gate lives). In a diode's diffusion-dominated depletion region
    that formula gives spurious, thermodynamically-impossible
    LOCAL NEGATIVE heat (measured directly during development: peaks
    of -3e4 W/cm^3 right at the junction) because it ignores that
    diffusion current also does work. phi_n/phi_p are reconstructed
    from the device's own converged (psi, n, p) -- not a new physics
    derivation, the standard quasi-Fermi-potential definition
    phi_n = psi - ln(n/nie), phi_p = psi + ln(p/nie) already used
    elsewhere in this codebase's band_diagram().

    Box-integrated onto nodes with the same half-box convention
    device.py's own dV uses. Reuses device.Jn/device.Jp/device.psi/
    device.n/device.p/device.nie_s/device.VT/device.h -- does not
    re-derive the Scharfetter-Gummel current.
    """
    psi, n, p, nie_s = device.psi, device.n, device.p, device.nie_s
    phi_n = psi - np.log(np.maximum(n, 1e-300) / nie_s)
    phi_p = psi + np.log(np.maximum(p, 1e-300) / nie_s)
    h_phys = device.h * device.LD                          # cm
    E_n = -(phi_n[1:] - phi_n[:-1]) * device.VT / h_phys    # V/cm
    E_p = -(phi_p[1:] - phi_p[:-1]) * device.VT / h_phys
    H_edge = device.Jn * E_n + device.Jp * E_p              # W/cm^3, len N-1
    N = device.N
    H = np.zeros(N)
    H[1:-1] = 0.5 * (H_edge[:-1] * h_phys[:-1] + H_edge[1:] * h_phys[1:]) \
        / (0.5 * (h_phys[:-1] + h_phys[1:]))
    H[0] = H_edge[0]
    H[-1] = H_edge[-1]
    return H


def solve_electrothermal(build_device, bias, T_ambient, bc_left, bc_right,
                         material, max_outer=30, tol=1e-3, opts=None,
                         thermal_opts=None):
    """Outer Gummel loop between an isothermal Device1D electrical
    solve and the steady lattice-temperature solve above.

    build_device(T) must return a FRESH, unsolved Device1D at scalar
    temperature T (e.g. `lambda T: Device1D(x, dop, T=T, models=...)`)
    -- reuses Device1D's existing scalar-T constructor unmodified, no
    new constructor argument. Each outer pass: build at the current
    candidate T, solve_equilibrium() + solve_bias(bias) (both
    unmodified, existing calls), compute H(x) via
    joule_heating_density, solve for the lattice T(x), and take its
    PEAK as the next candidate device temperature (the value that
    actually matters for mobility/roll-off). Converges when the
    candidate temperature stops moving by more than `tol` (relative).

    Returns (device, T_profile, T_history) -- the final converged
    device (already solved at bias), the last lattice T(x) profile,
    and the per-pass candidate-temperature history.
    """
    thermal_opts = thermal_opts or ThermalOptions()
    T_candidate = float(T_ambient)
    T_history = [T_candidate]
    device = None
    T_profile = None

    for _ in range(max_outer):
        device = build_device(T_candidate)
        device.solve_equilibrium(opts)
        device.solve_bias(bias, opts)

        H = joule_heating_density(device)
        T_profile = solve_lattice_temperature(
            device.x, H, material, T_ambient, bc_left, bc_right,
            opts=thermal_opts)

        T_new = float(T_profile.max())
        T_history.append(T_new)
        if abs(T_new - T_candidate) < tol * max(1.0, abs(T_candidate)):
            T_candidate = T_new
            break
        T_candidate = T_new
    else:
        raise RuntimeError(
            "solve_electrothermal outer loop did not converge "
            f"(candidate T still moving after {max_outer} passes: "
            f"{T_history[-3:]})")

    return device, T_profile, T_history
