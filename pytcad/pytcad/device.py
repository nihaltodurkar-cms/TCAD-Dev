"""1D drift-diffusion device simulator (the "device TCAD" half of the tool).

THE EQUATIONS
-------------
We solve the classical van Roosbroeck system, self-consistently, in steady
state:

    Poisson        d/dx ( eps dpsi/dx ) = -q ( p - n + N_D^+ - N_A^- )
    electrons      dJn/dx = +q R
    holes          dJp/dx = -q R
    constitutive   Jn = q mu_n n E + q D_n dn/dx = q mu_n n dpsi/dx? ...

written in the drift-diffusion form with Einstein relation D = mu kT/q:

    Jn = q D_n ( -n dpsi/dx / V_T + dn/dx ) * (-1)   [sign per convention]
    Jp = -q D_p ( p dpsi/dx / V_T + dp/dx )

Symbols:
    psi   electrostatic potential [V]        n, p   carrier densities [cm^-3]
    Jn,Jp current densities [A/cm^2]         R      net recombination [cm^-3 s^-1]
    N_D^+, N_A^-  ionised dopant densities [cm^-3]  (full ionisation assumed)
    eps   permittivity [F/cm]                V_T = kT/q

Assumptions and their limits:
  * Boltzmann statistics -- breaks down above ~1e19 cm^-3 (degeneracy);
    the code warns you when the doping crosses that.
  * Full dopant ionisation -- fails at cryogenic temperature.
  * Classical (no quantisation) -- an inversion layer in a modern MOSFET is
    a ~2 nm quantum well; the classical result puts the charge centroid at
    the interface and overestimates gate capacitance by ~10-20%.
  * Steady state, isothermal, no impact ionisation or tunnelling.

DISCRETISATION
--------------
Box (finite-volume) integration on a non-uniform 1D mesh.  Currents on the
interfaces use the Scharfetter-Gummel scheme, which integrates the
drift-diffusion equation exactly under the assumption that J and E are
constant across one cell:

    Jn_{i+1/2} = (q D_n / h) [ n_{i+1} B(d) - n_i B(-d) ],  d = (psi_{i+1}-psi_i)/V_T

with the Bernoulli function B(x) = x / (e^x - 1).  This is the single most
important numerical ingredient: naive central differencing of the drift term
oscillates and goes negative as soon as the potential drop across a cell
exceeds ~2 V_T (52 mV), which happens everywhere in a depletion region.

SCALING
-------
Newton on the raw variables is hopeless: psi ~ 1, n ~ 1e20, R ~ 1e25.  We use
the de Mari scaling
    psi -> psi/V_T,  n,p -> n/n_i,  x -> x/L_D,  L_D = sqrt(eps V_T/(q n_i))
which brings every residual to order unity.
"""

from dataclasses import dataclass
import warnings

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from .constants import Q, EPS0, thermal_voltage
from .materials import (
    SILICON, Semiconductor, mobility_caughey_thomas, mobility_field,
    nie_effective, lifetime_scharfetter, recombination,
)

D0_REF = 1.0  # reference diffusivity for scaling [cm^2/s]


# ----------------------------------------------------------------------
#  Bernoulli function and its derivative (numerically stable)
# ----------------------------------------------------------------------
def bernoulli(x):
    """B(x) = x / (exp(x) - 1), with B(0) = 1."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)          # dummy to avoid 0/0
    out = np.where(small,
                   1.0 - x / 2.0 + x * x / 12.0,
                   xs / np.expm1(xs))
    return out


def dbernoulli(x):
    """dB/dx, computed as B(x) [1/x - 1/(1 - e^-x)] for stability."""
    x = np.clip(np.asarray(x, dtype=float), -700.0, 700.0)
    small = np.abs(x) < 1e-4
    xs = np.where(small, 1.0, x)
    B = np.where(small, 1.0, xs / np.expm1(xs))
    em = -np.expm1(-xs)                   # 1 - exp(-x)
    em = np.where(np.abs(em) < 1e-300, 1e-300, em)
    full = B * (1.0 / xs - 1.0 / em)
    series = -0.5 + x / 6.0 - x**3 / 180.0
    return np.where(small, series, full)


# ----------------------------------------------------------------------
#  Solver options
# ----------------------------------------------------------------------
@dataclass
class Models:
    doping_mobility: bool = True
    field_mobility: bool = False   # lagged; enable for high-field devices
    srh: bool = True
    auger: bool = True
    bgn: bool = True               # bandgap narrowing


@dataclass
class NewtonOptions:
    max_iter: int = 100
    tol_update: float = 1e-8       # max scaled update
    tol_residual: float = 1e-10
    max_dpsi: float = 5.0          # damping cap on scaled potential update
    verbose: bool = False


# ----------------------------------------------------------------------
#  Device
# ----------------------------------------------------------------------
class Device1D:
    """A 1D two-terminal semiconductor device with ohmic contacts.

    Parameters
    ----------
    x        : node positions [cm], ascending
    doping   : net doping N_D - N_A at each node [cm^-3] (positive = n-type)
    Ntotal   : total ionised impurity concentration for mobility/lifetime
               models [cm^-3]; defaults to |doping|
    """

    def __init__(self, x, doping, Ntotal=None, T=300.0,
                 material: Semiconductor = SILICON,
                 models: Models = None):
        self.x = np.asarray(x, dtype=float)
        self.N = self.x.size
        self.doping = np.asarray(doping, dtype=float)
        self.Ntot = np.abs(self.doping) if Ntotal is None else np.asarray(Ntotal, float)
        self.T = T
        # M11-S3: a single Semiconductor keeps the classic behavior; a
        # per-node sequence defines a heterostructure.  All material
        # fields below become node arrays in that case, and eps(x)
        # enters the Poisson flux form while chi/Eg enter the currents
        # through position-dependent nie (band offsets ride ln(nie)
        # edge factors -- see _residual_jacobian).
        if isinstance(material, Semiconductor):
            self.mats = [material] * len(np.atleast_1d(doping))
        else:
            self.mats = [m for m in material]
            if len(self.mats) != len(np.atleast_1d(doping)):
                raise ValueError(
                    "material list length must match the mesh")
            if not all(isinstance(m, Semiconductor) for m in self.mats):
                raise TypeError("material entries must be Semiconductor")
        self.mat = self.mats[0] if isinstance(material, Semiconductor) \
            else material
        self.models = models or Models()

        if self.Ntot.max() > 1e19:
            warnings.warn(
                "Doping exceeds ~1e19 cm^-3: Boltzmann statistics used here "
                "overestimate the carrier density. Treat results in the "
                "degenerate regions as qualitative."
            )

        self.VT = thermal_voltage(T)
        self.eps_arr = np.array([m.eps_r * EPS0 for m in self.mats])
        self.chi_arr = np.array([m.chi for m in self.mats])
        self.Eg0_arr = np.array([m.Eg0 for m in self.mats])
        self.eps = self.eps_arr[0]          # reference (legacy attribute)
        self.ni = self.mats[0].ni(T)

        # Concentration scale.  Using n_i (the classical de Mari choice)
        # makes the scaled majority density ~1e7 and the Poisson residual
        # loses ~8 digits to cancellation.  Scaling by the peak doping keeps
        # every majority-carrier term at order unity.
        self.Ns = max(float(np.abs(self.doping).max()), self.ni)
        self.LD = np.sqrt(self.eps * self.VT / (Q * self.Ns))
        self.J0 = Q * D0_REF * self.Ns / self.LD      # current scale [A/cm^2]
        self.R0 = D0_REF * self.Ns / self.LD**2       # rate scale [cm^-3 s^-1]

        # --- scaled geometry ---
        self.xs = self.x / self.LD
        self.h = np.diff(self.xs)
        self.dV = np.zeros(self.N)
        self.dV[1:-1] = 0.5 * (self.h[:-1] + self.h[1:])
        self.dV[0] = 0.5 * self.h[0]
        self.dV[-1] = 0.5 * self.h[-1]

        # --- scaled material fields ---
        self.C = self.doping / self.Ns
        # per-material grouping: each Semiconductor's parameter set is
        # applied only on its own nodes (arrays stay node-ordered)
        self.nie = np.empty(self.N)
        self.mu_n0 = np.empty(self.N)
        self.mu_p0 = np.empty(self.N)
        self.tau_n = np.empty(self.N)
        self.tau_p = np.empty(self.N)
        seen_mats = []                               # identity-unique, ordered
        for mm in self.mats:
            if not any(mm is m2 for m2 in seen_mats):
                seen_mats.append(mm)
        for m in seen_mats:
            nodes = np.array([mm is m for mm in self.mats])
            nt = self.Ntot[nodes]
            self.nie[nodes] = nie_effective(nt, m, T, self.models.bgn)
            self.mu_n0[nodes] = (
                mobility_caughey_thomas(nt, m, T, "n")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_n_max))
            self.mu_p0[nodes] = (
                mobility_caughey_thomas(nt, m, T, "p")
                if self.models.doping_mobility
                else np.full(int(nodes.sum()), m.mu_p_max))
            self.tau_n[nodes] = lifetime_scharfetter(nt, m.tau_n0,
                                                     m.tau_Nref)
            self.tau_p[nodes] = lifetime_scharfetter(nt, m.tau_p0,
                                                     m.tau_Nref)
        self.nie_s = self.nie / self.Ns

        # interface (harmonic-mean) diffusivities, scaled
        self._set_edge_diffusivity(self.mu_n0, self.mu_p0)

        self.psi = None
        self.n = None
        self.p = None

    # ------------------------------------------------------------------
    def _eps_tilde_edge(self):
        """Harmonic-mean scaled permittivity on edges, normalized by the
        FIRST material's eps so a uniform device gives exactly 1.0
        everywhere and every residual reduces to its original form."""
        et_n = self.eps_arr / self.eps_arr[0]
        return 2.0 * et_n[:-1] * et_n[1:] / (et_n[:-1] + et_n[1:])

    def _set_edge_diffusivity(self, mu_n, mu_p):
        """Einstein relation D = mu V_T; harmonic mean onto the interfaces.

        Harmonic averaging (rather than arithmetic) is the right choice for a
        flux-continuous quantity across an abrupt change in mobility.
        """
        def hmean(a):
            return 2.0 * a[:-1] * a[1:] / (a[:-1] + a[1:])
        self.dn_edge = hmean(mu_n) * self.VT / D0_REF
        self.dp_edge = hmean(mu_p) * self.VT / D0_REF

    def _contact_values(self, V):
        """Ohmic contact: local charge neutrality + thermal equilibrium.

            n0 - p0 = C,   n0 p0 = n_ie^2
        =>  n0 = 0.5 [ C + sqrt(C^2 + 4 n_ie^2) ]
            psi = V/V_T + ln(n0 / n_ie)

        Always evaluate the MAJORITY carrier from the square root and get the
        minority one from the mass-action law.  Doing it the other way round
        subtracts two nearly equal numbers -- for C/n_ie ~ 1e7 the minority
        density comes out with only two correct digits.
        """
        out = []
        for i in (0, self.N - 1):
            C, nie = self.C[i], self.nie_s[i]
            root = np.sqrt(C * C + 4.0 * nie * nie)
            if C >= 0.0:                     # n-type: electrons are majority
                n0 = 0.5 * (C + root)
                p0 = nie * nie / n0
            else:                            # p-type: holes are majority
                p0 = 0.5 * (-C + root)
                n0 = nie * nie / p0
            psi0 = V[0 if i == 0 else 1] / self.VT + np.log(n0 / nie)
            out.append((psi0, n0, p0))
        return out

    # ------------------------------------------------------------------
    #  Equilibrium (Poisson only, carriers slaved to psi)
    # ------------------------------------------------------------------
    def solve_equilibrium(self, opts: NewtonOptions = None):
        opts = opts or NewtonOptions()
        h, dV, C, nie = self.h, self.dV, self.C, self.nie_s
        et = self._eps_tilde_edge()

        psi = np.arcsinh(C / (2.0 * nie))          # neutral-bulk guess
        bc = self._contact_values([0.0, 0.0])
        psi[0], psi[-1] = bc[0][0], bc[1][0]

        for it in range(opts.max_iter):
            n = nie * np.exp(np.clip(psi, -700, 700))
            p = nie * np.exp(np.clip(-psi, -700, 700))

            F = np.zeros(self.N)
            F[1:-1] = (et[1:] * (psi[2:] - psi[1:-1]) / h[1:]
                   - et[:-1] * (psi[1:-1] - psi[:-2]) / h[:-1]
                   - dV[1:-1] * (n[1:-1] - p[1:-1] - C[1:-1]))
            F[0] = psi[0] - bc[0][0]
            F[-1] = psi[-1] - bc[1][0]

            main = np.zeros(self.N)
            lower = np.zeros(self.N - 1)
            upper = np.zeros(self.N - 1)
            main[1:-1] = (-et[1:] / h[1:] - et[:-1] / h[:-1]
                          - dV[1:-1] * (n[1:-1] + p[1:-1]))
            upper[1:] = et[1:] / h[1:]
            lower[:-1] = et[:-1] / h[:-1]
            main[0] = main[-1] = 1.0
            upper[0] = 0.0
            lower[-1] = 0.0

            rows = np.concatenate([np.arange(self.N),
                                   np.arange(1, self.N),
                                   np.arange(self.N - 1)])
            cols = np.concatenate([np.arange(self.N),
                                   np.arange(self.N - 1),
                                   np.arange(1, self.N)])
            vals = np.concatenate([main, lower, upper])
            A = csr_matrix((vals, (rows, cols)), shape=(self.N, self.N))

            d = spsolve(A, -F)
            d = np.clip(d, -opts.max_dpsi, opts.max_dpsi)
            psi = psi + d
            if opts.verbose:
                print(f"    eq it {it:2d}  |dpsi|={np.abs(d).max():.3e}")
            if np.abs(d).max() < opts.tol_update:
                break
        else:
            warnings.warn("Equilibrium Poisson solve did not converge.")

        self.psi = psi
        self.n = nie * np.exp(np.clip(psi, -700, 700))
        self.p = nie * np.exp(np.clip(-psi, -700, 700))
        return self

    # ------------------------------------------------------------------
    #  Coupled residual and Jacobian
    # ------------------------------------------------------------------
    def _residual_jacobian(self, psi, n, p, bc):
        N, h, dV, C = self.N, self.h, self.dV, self.C
        dn_e, dp_e = self.dn_edge, self.dp_edge

        # M11-S3: band-offset-aware SG deltas.  ln(nie) edge factors make
        # the current vanish identically at equilibrium even across an
        # abrupt material change; derivatives wrt psi are unchanged
        # because nie is fixed under the Newton update.
        # M11-S3 band-offset-aware SG deltas.  Electrons and holes need
        # OPPOSITE nie-factor signs (calibrated against equilibrium
        # detailed balance on every edge):
        #   electron: delta_n = dpsi + dln(nie_s)
        #   hole:     delta_p = dpsi - dln(nie_s)
        dlnnie = np.log(self.nie_s[1:] / self.nie_s[:-1])
        delta = (psi[1:] - psi[:-1]) + dlnnie          # electrons
        delta_p = (psi[1:] - psi[:-1]) - dlnnie        # holes
        Bp, Bm = bernoulli(delta), bernoulli(-delta)
        dBp, dBm = dbernoulli(delta), dbernoulli(-delta)
        Bp_h, Bm_h = bernoulli(delta_p), bernoulli(-delta_p)
        dBp_h, dBm_h = dbernoulli(delta_p), dbernoulli(-delta_p)
        et = self._eps_tilde_edge()

        an = dn_e / h
        ap = dp_e / h
        Jn = an * (n[1:] * Bp - n[:-1] * Bm)
        Jp = -ap * (p[1:] * Bm_h - p[:-1] * Bp_h)

        # recombination (unscaled physical densities)
        n_phys, p_phys = n * self.Ns, p * self.Ns
        R = np.empty_like(n_phys); dRdn = np.empty_like(n_phys)
        dRdp = np.empty_like(n_phys)
        for m in {id(mm): mm for mm in self.mats}.values():
            nodes = np.array([mm is m for mm in self.mats])
            R[nodes], dRdn[nodes], dRdp[nodes] = recombination(
                n_phys[nodes], p_phys[nodes], self.nie[nodes],
                self.tau_n[nodes], self.tau_p[nodes], m,
                auger=self.models.auger)
        if not self.models.srh:
            R = np.zeros_like(R); dRdn = np.zeros_like(R); dRdp = np.zeros_like(R)
        Rs = R / self.R0
        dRs_dn = dRdn * self.Ns / self.R0      # d(R/R0)/d(n/Ns)
        dRs_dp = dRdp * self.Ns / self.R0

        F = np.zeros(3 * N)
        rows, cols, vals = [], [], []

        def add(r, c, v):
            r = np.atleast_1d(np.asarray(r))
            c = np.atleast_1d(np.asarray(c))
            v = np.broadcast_to(np.asarray(v, dtype=float), r.shape)
            rows.append(r); cols.append(c); vals.append(np.array(v))

        i = np.arange(1, N - 1)
        # --- Poisson ---
        F[3 * i] = (et[1:] * (psi[2:] - psi[1:-1]) / h[1:]
                    - et[:-1] * (psi[1:-1] - psi[:-2]) / h[:-1]
                    - dV[1:-1] * (n[1:-1] - p[1:-1] - C[1:-1]))
        add(3 * i, 3 * i, -et[1:] / h[1:] - et[:-1] / h[:-1])
        add(3 * i, 3 * (i + 1), et[1:] / h[1:])
        add(3 * i, 3 * (i - 1), et[:-1] / h[:-1])
        add(3 * i, 3 * i + 1, -dV[1:-1])
        add(3 * i, 3 * i + 2, dV[1:-1])

        # --- electron continuity:  Jn_{i+1/2} - Jn_{i-1/2} - R dV = 0 ---
        F[3 * i + 1] = Jn[1:] - Jn[:-1] - Rs[1:-1] * dV[1:-1]
        add(3 * i + 1, 3 * i + 1, -an[1:] * Bm[1:] - an[:-1] * Bp[:-1]
            - dRs_dn[1:-1] * dV[1:-1])
        add(3 * i + 1, 3 * (i + 1) + 1, an[1:] * Bp[1:])
        add(3 * i + 1, 3 * (i - 1) + 1, an[:-1] * Bm[:-1])
        add(3 * i + 1, 3 * i + 2, -dRs_dp[1:-1] * dV[1:-1])
        dJn_dpsiR = an * (n[1:] * dBp + n[:-1] * dBm)      # d Jn_{k+1/2}/d psi_{k+1}
        add(3 * i + 1, 3 * i, -dJn_dpsiR[1:] - dJn_dpsiR[:-1])
        add(3 * i + 1, 3 * (i + 1), dJn_dpsiR[1:])
        add(3 * i + 1, 3 * (i - 1), dJn_dpsiR[:-1])

        # --- hole continuity:  Jp_{i+1/2} - Jp_{i-1/2} + R dV = 0 ---
        F[3 * i + 2] = Jp[1:] - Jp[:-1] + Rs[1:-1] * dV[1:-1]
        add(3 * i + 2, 3 * i + 2, ap[1:] * Bp_h[1:] + ap[:-1] * Bm_h[:-1]
            + dRs_dp[1:-1] * dV[1:-1])
        add(3 * i + 2, 3 * (i + 1) + 2, -ap[1:] * Bm_h[1:])
        add(3 * i + 2, 3 * (i - 1) + 2, -ap[:-1] * Bp_h[:-1])
        add(3 * i + 2, 3 * i + 1, dRs_dn[1:-1] * dV[1:-1])
        # d(delta_p)/d(psi_{k+1}) = +1 like the electron side, because the
        # minus from the hole Boltzmann exponent cancels the minus in the
        # delta definition -- verified by the FD-Jacobian test
        dJp_dpsiR = ap * (p[1:] * dBm_h + p[:-1] * dBp_h)
        add(3 * i + 2, 3 * i, -dJp_dpsiR[1:] - dJp_dpsiR[:-1])
        add(3 * i + 2, 3 * (i + 1), dJp_dpsiR[1:])
        add(3 * i + 2, 3 * (i - 1), dJp_dpsiR[:-1])

        # --- Dirichlet contacts ---
        for k, node in enumerate((0, N - 1)):
            psi0, n0, p0 = bc[k]
            F[3 * node] = psi[node] - psi0
            F[3 * node + 1] = n[node] - n0
            F[3 * node + 2] = p[node] - p0
            idx = 3 * node + np.arange(3)
            add(idx, idx, 1.0)

        J = csr_matrix((np.concatenate(vals),
                        (np.concatenate(rows), np.concatenate(cols))),
                       shape=(3 * N, 3 * N))
        return F, J, Jn, Jp

    # ------------------------------------------------------------------
    def solve_bias(self, V, opts: NewtonOptions = None):
        """Solve at applied bias V = [V_left, V_right] (volts)."""
        opts = opts or NewtonOptions()
        if self.psi is None:
            self.solve_equilibrium(opts)

        psi, n, p = self.psi.copy(), self.n.copy(), self.p.copy()
        bc = self._contact_values(V)
        psi[0], n[0], p[0] = bc[0]
        psi[-1], n[-1], p[-1] = bc[1]

        for it in range(opts.max_iter):
            if self.models.field_mobility:
                E = -(psi[1:] - psi[:-1]) * self.VT / (self.h * self.LD)
                mu_n = mobility_field(self.mu_n0, np.r_[np.abs(E), np.abs(E[-1])],
                                      self.mat, "n")
                mu_p = mobility_field(self.mu_p0, np.r_[np.abs(E), np.abs(E[-1])],
                                      self.mat, "p")
                self._set_edge_diffusivity(mu_n, mu_p)

            F, J, Jn, Jp = self._residual_jacobian(psi, n, p, bc)
            du = spsolve(J.tocsc(), -F)
            dpsi, dn, dp = du[0::3], du[1::3], du[2::3]

            dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)
            # keep densities positive: never let them fall below 1/10 or rise
            # above 10x in a single Newton step
            n_old, p_old = n, p
            n_new = np.clip(n + dn, 0.1 * n, 10.0 * n)
            p_new = np.clip(p + dp, 0.1 * p, 10.0 * p)
            psi = psi + dpsi
            n, p = n_new, p_new

            # Convergence is judged on the UPDATE, not the residual: the
            # Poisson residual subtracts terms of order 1/h^2 and hits a
            # floating-point cancellation floor well above tol_residual.
            rel_n = np.abs(n_new / np.maximum(n_old, 1e-300) - 1.0).max()
            rel_p = np.abs(p_new / np.maximum(p_old, 1e-300) - 1.0).max()
            err = max(np.abs(dpsi).max(), rel_n, rel_p)
            if opts.verbose:
                print(f"    it {it:2d}  |F|={np.abs(F).max():.3e}  "
                      f"|dpsi|={np.abs(dpsi).max():.3e}  "
                      f"|dn/n|={rel_n:.3e}")
            if err < opts.tol_update:
                break
        else:
            warnings.warn(f"Newton did not converge at V={V}; "
                          f"last update {err:.2e}")

        self.psi, self.n, self.p = psi, n, p
        _, _, Jn, Jp = self._residual_jacobian(psi, n, p, bc)
        self.Jn = Jn * self.J0
        self.Jp = Jp * self.J0
        return self

    # --- physical-unit accessors -------------------------------------
    @property
    def psi_V(self):
        """Electrostatic potential [V]."""
        return self.psi * self.VT

    @property
    def n_cm3(self):
        """Electron density [cm^-3]."""
        return self.n * self.Ns

    @property
    def p_cm3(self):
        """Hole density [cm^-3]."""
        return self.p * self.Ns

    @property
    def E_field(self):
        """Electric field on the mesh interfaces [V/cm]."""
        return -(self.psi[1:] - self.psi[:-1]) * self.VT / (self.h * self.LD)

    # ------------------------------------------------------------------
    def current_density(self):
        """Total current density [A/cm^2].

        In 1D steady state Jn + Jp is exactly constant; the spread across
        interfaces is a useful convergence diagnostic and is returned too.
        """
        Jt = self.Jn + self.Jp
        return float(np.mean(Jt)), float(np.std(Jt) / (np.abs(np.mean(Jt)) + 1e-30))

    def iv_sweep(self, voltages, terminal=0, opts: NewtonOptions = None,
                 verbose=True):
        """Ramp bias and record J(V).  The previous solution seeds the next
        bias point -- essential for convergence beyond a few hundred mV."""
        opts = opts or NewtonOptions()
        self.solve_equilibrium(opts)
        J = []
        for V in voltages:
            bias = [V, 0.0] if terminal == 0 else [0.0, V]
            self.solve_bias(bias, opts)
            j, spread = self.current_density()
            J.append(j)
            if verbose:
                print(f"  V = {V:+.3f} V   J = {j:+.6e} A/cm^2   "
                      f"(continuity spread {spread:.1e})")
        return np.array(J)

    # ------------------------------------------------------------------
    def band_diagram(self):
        """Conduction/valence band edges and quasi-Fermi levels [eV]."""
        VT = self.VT
        chi_arr = np.array([m.chi for m in self.mats])
        Eg_arr = np.array([m.Eg(self.T) for m in self.mats])
        Ec = -self.psi * VT - chi_arr
        Ev = Ec - Eg_arr
        Nc_arr = np.array([m.Nc(self.T) for m in self.mats])
        Nv_arr = np.array([m.Nv(self.T) for m in self.mats])
        EFn = Ec + VT * np.log(np.maximum(self.n * self.Ns, 1e-30)
                               / Nc_arr)
        EFp = Ev - VT * np.log(np.maximum(self.p * self.Ns, 1e-30)
                               / Nv_arr)
        return Ec, Ev, EFn, EFp

