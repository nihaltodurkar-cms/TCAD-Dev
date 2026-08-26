"""MOS capacitor: 1D classical Poisson with an oxide boundary condition.

A MOS-C at DC carries no current, so the carriers stay in thermal equilibrium
with a single Fermi level and the drift-diffusion machinery is unnecessary:

    n = n_ie exp(psi/V_T),   p = n_ie exp(-psi/V_T)

and we solve Poisson alone.  The gate enters as a Robin (mixed) boundary
condition from Gauss's law across the Si/SiO2 interface:

    eps_ox (V_G - V_FB - phi_s) / t_ox = eps_s E_s(0)

with phi_s the surface band bending.  The resulting C-V is the LOW-FREQUENCY
(quasi-static) curve: the inversion layer responds to the AC signal, so the
capacitance returns to C_ox in strong inversion.  Measuring at 1 MHz on a
real substrate gives the high-frequency curve instead, where C saturates near
C_min, because minority carriers cannot be generated fast enough.

Not included: quantum confinement of the inversion layer (shifts the charge
centroid ~1 nm off the interface and lowers C_max by 10-20% in thin-oxide
devices), poly-gate depletion, interface trap capacitance D_it, and
tunnelling leakage through oxides below ~2 nm.
"""

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve

from .constants import KB_EV, Q, EPS0, thermal_voltage
from .device import fd_density, fd_ddensity_deta
from .fermi import FERMI_ETA_MAX, FERMI_ETA_MIN, f_half
from .materials import SILICON, Semiconductor, nie_effective

EPS_OX_R = 3.9   # SiO2 relative permittivity


def flatband_voltage(Nsub, tox_cm, gate="n+poly", Qf=0.0, T=300.0,
                     material: Semiconductor = SILICON):
    """V_FB = phi_ms - Q_f / C_ox  [V], for a MOS gate on substrate doping
    Nsub (negative = p-type).  Standalone so MOSFET structures can reuse
    it without building a full 1D MOSCapacitor."""
    VT = thermal_voltage(T)
    eps_s = material.eps_r * EPS0
    Cox = (EPS_OX_R * EPS0) / tox_cm
    ni = material.ni(T)
    nie = float(nie_effective(abs(Nsub), material, T, True))
    Ns = max(abs(float(Nsub)), ni)
    C = Nsub / Ns
    nie_s = nie / Ns
    psi_b = np.arcsinh(C / (2.0 * nie_s))

    chi, Eg = material.chi, material.Eg(T)
    if isinstance(gate, (int, float)):
        phi_m = float(gate)
    elif gate == "n+poly":
        phi_m = chi
    elif gate == "p+poly":
        phi_m = chi + Eg
    elif gate == "Al":
        phi_m = 4.10
    else:
        raise ValueError(f"unknown gate '{gate}'")
    phi_semi = chi + 0.5 * Eg - psi_b * VT
    return (phi_m - phi_semi) - Q * Qf / Cox


class MOSCapacitor:
    """Ideal-ish MOS capacitor on a uniformly doped substrate.

    Parameters
    ----------
    Nsub    : substrate doping [cm^-3]; negative = p-type (acceptors)
    tox_cm  : oxide thickness [cm]
    gate    : 'n+poly', 'p+poly', 'Al', or a work function in eV
    Qf      : fixed oxide charge [cm^-2] (positive charge, as usual for SiO2)
    """

    def __init__(self, Nsub, tox_cm, gate="n+poly", Qf=0.0, T=300.0,
                 material: Semiconductor = SILICON, L_cm=2e-4, nx=1200,
                 fd=False):
        self.mat = material
        self.T = T
        self.VT = thermal_voltage(T)
        self.eps_s = material.eps_r * EPS0
        self.eps_ox = EPS_OX_R * EPS0
        self.tox = tox_cm
        self.Cox = self.eps_ox / tox_cm            # [F/cm^2]
        self.Nsub = float(Nsub)
        self.Qf = Qf

        self.ni = material.ni(T)
        self.nie = float(nie_effective(abs(Nsub), material, T, True))
        # scale concentrations by the doping (see Device1D: scaling by n_i
        # costs ~8 digits of cancellation in the Poisson residual)
        self.Ns = max(abs(float(Nsub)), self.ni)
        self.LD = np.sqrt(self.eps_s * self.VT / (Q * self.Ns))

        # mesh: geometric grading away from the interface (the inversion
        # layer is only a few nm thick, the depletion region ~100 nm)
        s = np.linspace(0.0, 1.0, nx)
        self.x = L_cm * (np.expm1(6.0 * s) / np.expm1(6.0))
        self.xs = self.x / self.LD

        self.C = self.Nsub / self.Ns
        self.nie_s = self.nie / self.Ns

        # M13: Fermi-Dirac statistics branch (physical Nc/Nv form,
        # same construction as Device1D; default OFF => bit-identical).
        self.fd = bool(fd)
        if self.fd:
            nc_s = material.Nc(T) / self.Ns
            nv_s = material.Nv(T) / self.Ns
            self.nc_s, self.nv_s = float(nc_s), float(nv_s)
            self.ln_gn = float(np.log(nc_s / self.nie_s))
            self.ln_gp = float(np.log(nv_s / self.nie_s))
            self.eg_kt = material.Eg(T) / (KB_EV * T)

        if self.fd:
            # neutral-bulk potential from the FD neutrality root
            # (the Boltzmann arcsinh guess has the wrong gauge when
            # ln(Nc/nie) is comparable to the doping eta)
            lo, hi = -self.eg_kt - 80.0, float(FERMI_ETA_MAX)

            def imb(e):
                return (fd_density(self.nc_s, e)
                        - fd_density(self.nv_s,
                                     -e - self.eg_kt)) - self.C

            for _ in range(200):
                mid = 0.5 * (lo + hi)
                if imb(mid) < 0:
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 1e-13 * (1.0 + abs(lo)):
                    break
            eta_b = 0.5 * (lo + hi)
            if eta_b > FERMI_ETA_MAX - 2.0:
                raise ValueError(
                    "FD substrate neutrality eta beyond the validated "
                    "range (M13 G7 applicability).")
            self.psi_b = float(eta_b + self.ln_gn)
        else:
            self.psi_b = np.arcsinh(self.C / (2.0 * self.nie_s))
        self.kappa = self.eps_ox * self.LD / (self.eps_s * self.tox)

        self.Vfb = flatband_voltage(Nsub, tox_cm, gate, Qf, T, material)

    # ------------------------------------------------------------------
    def solve_psi(self, Vg, psi0=None, max_iter=200, tol=1e-10):
        """Nonlinear Poisson solve at gate bias Vg.  Returns scaled psi."""
        h = np.diff(self.xs)
        n_nodes = self.x.size
        dV = np.empty(n_nodes)
        dV[1:-1] = 0.5 * (h[:-1] + h[1:])
        dV[0] = 0.5 * h[0]
        dV[-1] = 0.5 * h[-1]

        psi = np.full(n_nodes, self.psi_b) if psi0 is None else psi0.copy()
        psi[-1] = self.psi_b
        Vg_s = Vg / self.VT
        Vfb_s = self.Vfb / self.VT

        for _ in range(max_iter):
            e = np.clip(psi, -700, 700)
            if self.fd:
                # M13: physical-statistics densities (same construction
                # and piecewise eta policy as Device1D)
                en = e - self.ln_gn
                ep = -e - self.ln_gp
                n = fd_density(self.nc_s, en)
                p = fd_density(self.nv_s, ep)
                dnp = fd_ddensity_deta(self.nc_s, en) \
                    + fd_ddensity_deta(self.nv_s, ep)
            else:
                n = self.nie_s * np.exp(e)
                p = self.nie_s * np.exp(-e)
                dnp = n + p
            rho = n - p - self.C

            F = np.zeros(n_nodes)
            F[1:-1] = ((psi[2:] - psi[1:-1]) / h[1:]
                       - (psi[1:-1] - psi[:-2]) / h[:-1]
                       - dV[1:-1] * rho[1:-1])
            # surface node: half box with the gate flux entering
            F[0] = ((psi[1] - psi[0]) / h[0]
                    + self.kappa * (Vg_s - Vfb_s - (psi[0] - self.psi_b))
                    - dV[0] * rho[0])
            F[-1] = psi[-1] - self.psi_b

            main = np.zeros(n_nodes)
            up = np.zeros(n_nodes - 1)
            lo = np.zeros(n_nodes - 1)
            main[1:-1] = (-1.0 / h[1:] - 1.0 / h[:-1]
                          - dV[1:-1] * dnp[1:-1])
            up[1:] = 1.0 / h[1:]
            lo[:-1] = 1.0 / h[:-1]
            main[0] = -1.0 / h[0] - self.kappa - dV[0] * dnp[0]
            up[0] = 1.0 / h[0]
            main[-1] = 1.0
            lo[-1] = 0.0

            A = diags([lo, main, up], [-1, 0, 1], format="csc")
            d = spsolve(A, -F)
            d = np.clip(d, -3.0, 3.0)
            psi = psi + d
            if np.abs(d).max() < tol:
                break
        return psi

    # ------------------------------------------------------------------
    def cv_sweep(self, Vg_list):
        """Quasi-static C-V.  Returns (phi_s [V], Qg [C/cm^2], C [F/cm^2])."""
        Vg_list = np.asarray(Vg_list, dtype=float)
        phis, Qg = [], []
        guess = None
        for Vg in Vg_list:
            psi = self.solve_psi(Vg, psi0=guess)
            guess = psi
            ps = (psi[0] - self.psi_b) * self.VT
            phis.append(ps)
            Qg.append(self.Cox * (Vg - self.Vfb - ps))
        phis, Qg = np.array(phis), np.array(Qg)
        C = np.gradient(Qg, Vg_list)
        return phis, Qg, C

    # ------------------------------------------------------------------
    def analytic_landmarks(self):
        """Textbook depletion-approximation landmarks, for cross-checking.

            phi_F   = V_T ln(N/n_i)
            W_max   = sqrt(4 eps_s phi_F / (q N))       (strong inversion)
            C_min   = (1/C_ox + W_max/eps_s)^-1
            V_T,lin = V_FB + 2 phi_F + sqrt(4 eps_s q N phi_F)/C_ox
        """
        N = abs(self.Nsub)
        phiF = self.VT * np.log(N / self.ni)
        Wmax = np.sqrt(4.0 * self.eps_s * phiF / (Q * N))
        Cmin = 1.0 / (1.0 / self.Cox + Wmax / self.eps_s)
        # p-substrate (Nsub < 0) -> n-channel, V_th > 0; n-substrate -> V_th < 0
        sign = 1.0 if self.Nsub < 0 else -1.0
        Vth = self.Vfb + sign * (2 * phiF
                                 + np.sqrt(4.0 * self.eps_s * Q * N * phiF)
                                 / self.Cox)
        return {"phi_F": phiF, "W_max": Wmax, "C_ox": self.Cox,
                "C_min": Cmin, "V_th": Vth, "V_FB": self.Vfb}
