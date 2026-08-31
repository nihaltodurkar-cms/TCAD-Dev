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

M20 (2026-08-29): density-gradient quantum correction.  dg=True adds
the Ancona-Stafford DG correction n -> n*exp(-Lambda/V_T) (charge
centroid ~1 nm off the interface, C_max lowered by up to ~20% on thin
oxides) via a lagged-Lambda outer fixed point -- see pytcad/dg.py and
M20-DENSITY-GRADIENT-PLAN.md.  Default OFF is bit-identical.

Still not included: poly-gate depletion, and tunnelling leakage
through oxides below ~2 nm.

M14 (2026-08-28): interface trap capacitance D_it. C_it = q * D_it
[F/cm^2], matching M14-SURFACE-MOBILITY-PLAN.md's spec text exactly.
(A first pass here second-guessed this as "should be q^2*D_it" from a
misremembered textbook heuristic, without re-deriving it -- that
version is numerically negligible, off by ~1e-21x kappa, i.e. it does
nothing. Re-derived from first principles instead: D_it [cm^-2 eV^-1]
times an energy shift in eV gives a state-density shift in cm^-2; a
band-bending change of dphi_s volts is a dphi_s-eV energy shift
numerically (the entire point of the eV unit, eV = q*volts), so
dN_it = D_it*dphi_s [cm^-2] and dQ_it = q*dN_it = q*D_it*dphi_s --
ONE factor of q, not two. Verified numerically: q*D_it at D_it=1e11 is
~0.02 in the same dimensionless units kappa=0.86 uses -- a real,
measurable fraction; the q^2 version was ~1e-21, i.e. a no-op.)
Q_it = C_it * phi_s, phi_s already referenced to flatband (phi_s=0
there), so phi_s_0 does not appear separately. Default D_it=0.0 is
bit-identical to the pre-M14 solve.
"""

import warnings

import numpy as np
from scipy.sparse import diags, csr_matrix

from . import linsolve
from .constants import KB_EV, Q, EPS0, thermal_voltage, trapz
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
    D_it    : interface trap density [cm^-2 eV^-1] (M14); 0.0 (default) is
              bit-identical to the no-D_it solve. See module docstring
              for the C_it = q^2*D_it formula and citation.
    """

    def __init__(self, Nsub, tox_cm, gate="n+poly", Qf=0.0, T=300.0,
                 material: Semiconductor = SILICON, L_cm=2e-4, nx=1200,
                 fd=False, D_it=0.0, dg=False, dg_gamma=1.0):
        self.mat = material
        self.T = T
        self.VT = thermal_voltage(T)
        self.eps_s = material.eps_r * EPS0
        self.eps_ox = EPS_OX_R * EPS0
        self.tox = tox_cm
        self.Cox = self.eps_ox / tox_cm            # [F/cm^2]
        self.Nsub = float(Nsub)
        self.Qf = Qf
        # M20: density-gradient quantum correction.  Default OFF is
        # bit-identical to the pre-M20 solve (the DG branch sits behind
        # `if self.dg:` only).  dg+fd is REFUSED: composing the DG
        # exponential correction with FD statistics needs a joint
        # derivation nobody has validated here (see
        # M20-DENSITY-GRADIENT-PLAN.md section 5).
        self.dg = bool(dg)
        self.dg_gamma = float(dg_gamma)
        if self.dg and self.dg_gamma <= 0.0:
            raise ValueError("dg_gamma must be > 0")
        if self.dg and fd:
            raise NotImplementedError(
                "dg=True with fd=True is refused: the DG correction and "
                "FD statistics compose through a joint density law that "
                "has not been derived/validated here (M20 plan sec 5).")

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

        # M14: interface-trap term, dimensionless (same scaling as
        # kappa): dit_coeff * (psi[0]-psi_b) == Q_it_scaled, where
        # Q_it = C_it*phi_s = q*D_it*phi_s and phi_s=(psi[0]-psi_b)*VT
        # -- the VT cancels against the 1/VT that nondimensionalizing
        # Q_it into the flux-balance residual introduces (same algebra
        # that makes kappa dimensionless for the Cox*(Vg-Vfb-phi_s)
        # term). D_it=0.0 (default) makes this exactly 0.0.
        self.D_it = float(D_it)
        self.dit_coeff = Q * self.D_it * self.LD / self.eps_s

        self.Vfb = flatband_voltage(Nsub, tox_cm, gate, Qf, T, material)

    # ------------------------------------------------------------------
    def solve_psi(self, Vg, psi0=None, max_iter=200, tol=1e-10):
        """Nonlinear Poisson solve at gate bias Vg.  Returns scaled psi.

        M20: with dg=True this delegates to _solve_psi_dg_coupled, a
        genuinely COUPLED Newton solve of (psi, Lambda_n, Lambda_p)
        together (see that method's docstring for why: an earlier
        LAGGED outer-fixed-point scheme converged cleanly but to
        wrong physics -- M20-DENSITY-GRADIENT-PLAN.md section 6).
        dg=False (this method, unchanged) is the classical Poisson
        Newton solve, bit-identical to every pre-M20 call.
        """
        if self.dg:
            return self._solve_psi_dg_coupled(Vg, psi0, max_iter, tol)

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
                # Clamp to FERMI_ETA_MAX before evaluating, matching the
                # np.minimum(..., FERMI_ETA_MAX) guard used for the same
                # quantity in the neutrality bisection above -- a
                # transient Newton overshoot must not abort the whole
                # solve when the converged answer would be valid.
                en = np.minimum(e - self.ln_gn, FERMI_ETA_MAX)
                ep = np.minimum(-e - self.ln_gp, FERMI_ETA_MAX)
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
            # surface node: half box with the gate flux entering, minus
            # the M14 interface-trap charge (0.0 at the default D_it=0)
            F[0] = ((psi[1] - psi[0]) / h[0]
                    + self.kappa * (Vg_s - Vfb_s - (psi[0] - self.psi_b))
                    - self.dit_coeff * (psi[0] - self.psi_b)
                    - dV[0] * rho[0])
            F[-1] = psi[-1] - self.psi_b

            main = np.zeros(n_nodes)
            up = np.zeros(n_nodes - 1)
            lo = np.zeros(n_nodes - 1)
            main[1:-1] = (-1.0 / h[1:] - 1.0 / h[:-1]
                          - dV[1:-1] * dnp[1:-1])
            up[1:] = 1.0 / h[1:]
            lo[:-1] = 1.0 / h[:-1]
            main[0] = (-1.0 / h[0] - self.kappa - self.dit_coeff
                       - dV[0] * dnp[0])
            up[0] = 1.0 / h[0]
            main[-1] = 1.0
            lo[-1] = 0.0

            A = diags([lo, main, up], [-1, 0, 1], format="csc")
            # linsolve.solve_linear(method="direct") no longer
            # reformats A before calling spsolve, so this stays
            # bit-identical to the raw spsolve(A, -F) call while adding
            # the finiteness/singularity checks a raw call silently
            # skips.
            d, _ = linsolve.solve_linear(A, -F, method="direct")
            d = np.clip(d, -3.0, 3.0)
            psi = psi + d
            if np.abs(d).max() < tol:
                break
        self._dg_Lam_n = None
        self._dg_Lam_p = None
        if self.fd:
            # The clamp above protects against a TRANSIENT overshoot
            # during iteration; it must not also silently accept a
            # CONVERGED psi genuinely outside the validated eta range --
            # check the raw, unclamped eta on the value actually
            # returned, matching fd_density's own "no silent
            # extrapolation" contract (M13 G7).
            e = np.clip(psi, -700, 700)
            en_raw = e - self.ln_gn
            ep_raw = -e - self.ln_gp
            if np.any(en_raw > FERMI_ETA_MAX) or np.any(ep_raw > FERMI_ETA_MAX):
                raise ValueError(
                    f"FD MOS-C solve converged to eta_n={en_raw.max():.1f} / "
                    f"eta_p={ep_raw.max():.1f}, beyond +{FERMI_ETA_MAX:.0f}: "
                    "outside the validated Fermi-integral range (M13 G7 "
                    "applicability).  Refusing to extrapolate.")
        return psi

    # ------------------------------------------------------------------
    def _dg_residual_jacobian(self, psi, Lam_n, Lam_p, Vg_s, Vfb_s, h, dV,
                               gamma=None):
        """M20 coupled-Newton DG residual/Jacobian.

        Unknowns interleaved [psi_i, Lambda_n_i, Lambda_p_i] per node
        (3N total), replacing the lagged outer fixed point that
        M20-DENSITY-GRADIENT-PLAN.md section 6 found converges cleanly
        to the WRONG physics (a hard bifurcation in gamma with no
        intermediate, S-P-matching regime).

        Poisson rows are EXACTLY solve_psi's classical flux-divergence
        residual, with n, p now COUPLED (Lambda_n/Lambda_p are live
        Newton unknowns, not a lagged array) rather than lagged.

        Lambda_n/Lambda_p rows are the residual form of dg.
        quantum_potential's own defining equation,

            Lambda*sqrt(n) + pref*(sqrt(n))'' = 0     (interior nodes)
            Lambda = 0                                 (boundary nodes)

        evaluated on the PHYSICAL mesh self.x (cm) -- NOT the scaled
        self.xs the Poisson rows use -- matching quantum_potential's
        own convention exactly (solve_psi's old lagged branch called
        quantum_potential(self.x, ...) with physical x). pref comes
        from dg._dg_prefactor, the SAME formula quantum_potential
        itself uses, not a second hand-transcription.

        Returns (F [3N], J [3N x 3N] csr_matrix).
        """
        from .dg import _dg_prefactor, LAMBDA_MAX_VT
        N = self.x.size
        VT = self.VT
        gamma = self.dg_gamma if gamma is None else gamma

        e = np.clip(psi, -700, 700)
        n = self.nie_s * np.exp(e) * np.exp(-Lam_n / VT)
        p = self.nie_s * np.exp(-e) * np.exp(-Lam_p / VT)
        dnp = n + p          # d(rho)/d(psi) at fixed Lambda -- same
                              # classical form as before (Lambda is a
                              # separate column now, not folded in)
        rho = n - p - self.C

        h_phys = np.diff(self.x)                       # cm, PHYSICAL
        pref_n = float(_dg_prefactor(self.mat.m_n_star, gamma))
        pref_p = float(_dg_prefactor(self.mat.m_p_star, gamma))
        # dg.quantum_potential's own 1e4 cm^-2 -> m^-2 unit factor
        pref_n *= 1e4
        pref_p *= 1e4

        gn = np.sqrt(np.maximum(n, 1e-300))
        gp = np.sqrt(np.maximum(p, 1e-300))

        F = np.zeros(3 * N)
        rows, cols, vals = [], [], []

        def add(r, c, v):
            rows.append(r); cols.append(c); vals.append(v)

        def ip(i): return 3 * i        # psi_i column/row
        def iln(i): return 3 * i + 1   # Lambda_n_i column/row
        def ilp(i): return 3 * i + 2   # Lambda_p_i column/row

        # ---- Poisson rows (same shape as the classical branch) -----
        F[ip(0)] = ((psi[1] - psi[0]) / h[0]
                    + self.kappa * (Vg_s - Vfb_s - (psi[0] - self.psi_b))
                    - self.dit_coeff * (psi[0] - self.psi_b)
                    - dV[0] * rho[0])
        add(ip(0), ip(0), -1.0 / h[0] - self.kappa - self.dit_coeff
            - dV[0] * dnp[0])
        add(ip(0), ip(1), 1.0 / h[0])
        add(ip(0), iln(0), dV[0] * n[0] / VT)
        add(ip(0), ilp(0), -dV[0] * p[0] / VT)

        F[ip(N - 1)] = psi[N - 1] - self.psi_b
        add(ip(N - 1), ip(N - 1), 1.0)

        if N >= 3:
            i = np.arange(1, N - 1)
            F[3 * i] = ((psi[i + 1] - psi[i]) / h[i]
                        - (psi[i] - psi[i - 1]) / h[i - 1]
                        - dV[i] * rho[i])
        for i in range(1, N - 1):
            add(ip(i), ip(i - 1), 1.0 / h[i - 1])
            add(ip(i), ip(i), -1.0 / h[i] - 1.0 / h[i - 1] - dV[i] * dnp[i])
            add(ip(i), ip(i + 1), 1.0 / h[i])
            add(ip(i), iln(i), dV[i] * n[i] / VT)
            add(ip(i), ilp(i), -dV[i] * p[i] / VT)

        # ---- Lambda_n / Lambda_p rows -------------------------------
        # Interface node (0): HARD WALL, not the old Lambda=0 Neumann
        # choice.  Pin Lambda_n[0]/Lambda_p[0] at the same numerical
        # clamp LAMBDA_MAX_VT*VT the rest of this module already uses
        # (dg.LAMBDA_MAX_VT) -- large enough to suppress n[0]/p[0] to
        # numerical zero via exp(-Lambda/VT), the discrete equivalent
        # of the S-P reference's exact psi_k(0)=0 hard-wall wavefunction
        # condition (n_q(0)=0 identically there).  This is the second
        # half of the hard-wall fix above: suppressing only the node-1
        # curvature ghost (leaving Lambda[0]=0) left n[0] itself at its
        # full unsuppressed classical value, which still dominated the
        # centroid integral and kept it short of the S-P reference --
        # measured directly during development.
        F[iln(0)] = Lam_n[0] - LAMBDA_MAX_VT * VT
        add(iln(0), iln(0), 1.0)
        F[ilp(0)] = Lam_p[0] - LAMBDA_MAX_VT * VT
        add(ilp(0), ilp(0), 1.0)
        F[iln(N - 1)] = Lam_n[N - 1]
        add(iln(N - 1), iln(N - 1), 1.0)
        F[ilp(N - 1)] = Lam_p[N - 1]
        add(ilp(N - 1), ilp(N - 1), 1.0)

        # Interior nodes: Lambda*g + pref*dd = 0, dd the 3-point
        # non-uniform second difference of g = sqrt(n) (or sqrt(p)),
        # on the PHYSICAL mesh h_phys.
        #
        # HARD-WALL interface treatment (2026-08-31 finding): a plain
        # Lambda[0]=0 Neumann choice leaves the CLASSICAL (large)
        # density value at node 0 feeding node 1's curvature stencil
        # unchanged -- verified directly (both in this coupled solve
        # and by evaluating the pre-existing quantum_potential formula
        # on a classical MOS profile in isolation) to give NEGATIVE
        # Lambda near the surface, i.e. the correction ENHANCES rather
        # than suppresses the near-interface density, backwards from
        # the required physics (M20-DENSITY-GRADIENT-PLAN.md section 6
        # already flagged a "boundary-condition mismatch" hypothesis,
        # tested only in the old LAGGED scheme and found insufficient
        # there). Researched how production tools treat this: DEVSIM's
        # density-gradient reference implementation explicitly extends
        # the mesh into the oxide with its own quantum prefactor and a
        # surface term (Wettstein et al. 2002; Garcia-Loureiro et al.
        # 2011) -- i.e. the interface is NOT a free (Neumann) boundary
        # for the quantum unknown. This MOSCapacitor has no oxide mesh
        # to extend into (the oxide is a lumped Robin/Cox term, not
        # meshed), so the equivalent treatment available here is the
        # infinite-barrier LIMIT of that same physics: force the
        # density feeding the curvature stencil to ZERO exactly at the
        # interface (a hard quantum wall), matching this codebase's
        # OWN Schrodinger-Poisson reference solver's convention
        # (dg.schrodinger_poisson's hard_wall_left=True: psi_k(0)=0
        # exactly, so n_q(0)=0 identically there too) -- consistency
        # with the very reference these gates check against, not an
        # independent guess. Implemented by using a GHOST value of 0
        # (not the real, large classical g[0]) only in node 1's
        # curvature stencil; the electrostatic Poisson row at node 0
        # is UNCHANGED (still uses the real n[0]/p[0] for charge
        # balance -- this only affects the quantum-confinement
        # curvature calculation, not the classical charge balance).
        for i in range(1, N - 1):
            hm, hp = h_phys[i - 1], h_phys[i]
            c0 = 2.0 / (hm + hp)
            hard_wall_left = (i == 1)

            for g, Lam, pref, dens, idx, sign in (
                (gn, Lam_n, pref_n, n, iln, +1.0),
                (gp, Lam_p, pref_p, p, ilp, -1.0),
            ):
                # sign = dpsi-derivative sign of g (electrons: g grows
                # with psi; holes: g shrinks with psi, sign=-1)
                g_im1 = 0.0 if hard_wall_left else g[i - 1]
                dd_i = c0 * ((g[i + 1] - g[i]) / hp - (g[i] - g_im1) / hm)
                F[idx(i)] = Lam[i] * g[i] + pref * dd_i

                dg_dpsi_i = sign * g[i] / 2.0
                dg_dLam_i = -g[i] / (2.0 * VT)
                # g[0] is a fixed ghost (0.0) at the hard wall -- no
                # dependence on psi[0]/Lambda[0], so its Jacobian
                # contribution is zero there (not the normal formula).
                dg_dpsi_im1 = 0.0 if hard_wall_left else sign * g[i - 1] / 2.0
                dg_dLam_im1 = 0.0 if hard_wall_left else -g[i - 1] / (2.0 * VT)
                dg_dpsi_ip1 = sign * g[i + 1] / 2.0
                dg_dLam_ip1 = -g[i + 1] / (2.0 * VT)

                ddd_dgi = -c0 * (1.0 / hp + 1.0 / hm)
                ddd_dgim1 = c0 / hm
                ddd_dgip1 = c0 / hp

                # same-node columns (psi_i, Lambda_i)
                add(idx(i), ip(i),
                    Lam[i] * dg_dpsi_i + pref * ddd_dgi * dg_dpsi_i)
                add(idx(i), idx(i),
                    g[i] + Lam[i] * dg_dLam_i + pref * ddd_dgi * dg_dLam_i)
                # neighbor columns (zero at the hard wall by construction)
                add(idx(i), ip(i - 1), pref * ddd_dgim1 * dg_dpsi_im1)
                add(idx(i), (iln(i - 1) if idx is iln else ilp(i - 1)),
                    pref * ddd_dgim1 * dg_dLam_im1)
                add(idx(i), ip(i + 1), pref * ddd_dgip1 * dg_dpsi_ip1)
                add(idx(i), (iln(i + 1) if idx is iln else ilp(i + 1)),
                    pref * ddd_dgip1 * dg_dLam_ip1)

        J = csr_matrix((vals, (rows, cols)), shape=(3 * N, 3 * N))
        return F, J

    # ------------------------------------------------------------------
    def _dg_newton_solve(self, psi, Lam_n, Lam_p, Vg_s, Vfb_s, h, dV, gamma,
                          max_iter, tol):
        """One coupled-Newton solve of the 3N (psi, Lambda_n, Lambda_p)
        system at a FIXED gamma, from the given warm-start state.
        Returns (psi, Lam_n, Lam_p, converged) -- never raises on
        non-convergence or a singular step (both are reported via the
        `converged` flag so the gamma-ladder driver can retry with a
        smaller step instead)."""
        n_nodes = psi.size
        for _ in range(max_iter):
            F, J = self._dg_residual_jacobian(
                psi, Lam_n, Lam_p, Vg_s, Vfb_s, h, dV, gamma=gamma)
            try:
                d, _ = linsolve.solve_linear(J.tocsc(), -F, method="direct")
            except linsolve.LinearSolveError:
                return psi, Lam_n, Lam_p, False
            if not np.all(np.isfinite(d)):
                return psi, Lam_n, Lam_p, False
            d_psi = np.clip(d[0::3], -3.0, 3.0)
            d_ln = np.clip(d[1::3], -10.0 * self.VT, 10.0 * self.VT)
            d_lp = np.clip(d[2::3], -10.0 * self.VT, 10.0 * self.VT)
            psi = psi + d_psi
            Lam_n = Lam_n + d_ln
            Lam_p = Lam_p + d_lp
            err = max(np.abs(d_psi).max(), np.abs(d_ln).max(), np.abs(d_lp).max())
            if err < tol:
                return psi, Lam_n, Lam_p, True
        return psi, Lam_n, Lam_p, False

    def _solve_psi_dg_coupled(self, Vg, psi0=None, max_iter=200, tol=1e-10):
        """M20 coupled-Newton DG solve: (psi, Lambda_n, Lambda_p) solved
        SIMULTANEOUSLY (3N unknowns), replacing the lagged outer
        fixed-point scheme (M20-DENSITY-GRADIENT-PLAN.md section 6:
        the lagged scheme converges cleanly but to a hard-bifurcated,
        physically-wrong answer at every gamma tried; the diagnosis is
        that lagging a nonlocal quantum potential outside the Newton
        loop is the wrong architecture, and production TCAD tools
        solve it coupled -- this method is that fix).

        A single Newton solve at the full target gamma from a
        Lambda=0 initial guess does NOT reliably converge (measured
        directly: it returns a singular/non-finite step at strong
        inversion) -- the DG coupling is genuinely stiff. So this
        ramps gamma from 0 up to the target in a strength ladder (the
        same continuation pattern device.py's M15/M16 stiff-generation
        solve_bias already uses), warm-restarting (psi, Lambda_n,
        Lambda_p) between stages. At gamma=0 the Lambda rows force
        Lambda=0 exactly and the Poisson row reduces to the classical
        equation, so the first stage is (up to solver tolerance) the
        already-trusted classical solve -- a natural, physically
        grounded starting point, not an arbitrary guess.
        """
        h = np.diff(self.xs)
        n_nodes = self.x.size
        dV = np.empty(n_nodes)
        dV[1:-1] = 0.5 * (h[:-1] + h[1:])
        dV[0] = 0.5 * h[0]
        dV[-1] = 0.5 * h[-1]

        psi = np.full(n_nodes, self.psi_b) if psi0 is None else psi0.copy()
        psi[-1] = self.psi_b
        Lam_n = np.zeros(n_nodes)
        Lam_p = np.zeros(n_nodes)
        Vg_s = Vg / self.VT
        Vfb_s = self.Vfb / self.VT

        target_gamma = self.dg_gamma
        stages = [0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0]
        k = 0
        retries_at_stage = 0
        converged_final = True
        while k < len(stages):
            gamma_k = target_gamma * stages[k]
            psi_new, Ln_new, Lp_new, ok = self._dg_newton_solve(
                psi, Lam_n, Lam_p, Vg_s, Vfb_s, h, dV, gamma_k,
                max_iter, tol)
            if ok:
                psi, Lam_n, Lam_p = psi_new, Ln_new, Lp_new
                k += 1
                retries_at_stage = 0
                continue
            # Stage failed: bisect the gap between the last converged
            # gamma and this stage's target instead of giving up
            # outright (mirrors continuation.py's shrink-on-failure).
            retries_at_stage += 1
            if retries_at_stage > 20:
                converged_final = False
                break
            stages.insert(k, 0.5 * (stages[k - 1] if k > 0 else 0.0) + 0.5 * stages[k])
        if not converged_final:
            warnings.warn("M20 DG coupled-Newton solve did not converge "
                          "(gamma continuation stalled).")
        self._dg_Lam_n = Lam_n
        self._dg_Lam_p = Lam_p
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
            # M14: Q_g = Cox*(Vg-Vfb-phi_s) - Q_it, Q_it = q*D_it*phi_s
            # (0.0 at the default D_it=0) -- consistent with solve_psi's
            # own dit_coeff term, which is what actually shapes phi_s(Vg).
            Qg.append(self.Cox * (Vg - self.Vfb - ps) - Q * self.D_it * ps)
        phis, Qg = np.array(phis), np.array(Qg)
        C = np.gradient(Qg, Vg_list)
        return phis, Qg, C

    # ------------------------------------------------------------------
    def inversion_centroid(self, Vg):
        """M20: charge centroid of the inversion layer at gate bias Vg.

        x_c = integral(x * (n - n_bulk)) dx / integral((n - n_bulk)) dx
        with the DG-corrected electron density when dg=True and the
        classical one otherwise.  This is the quantity the README
        section-6 caveat is about: classically x_c = 0 (charge ON the
        interface); quantum mechanically it sits ~1 nm deep, lowering
        C_max by 10-20% in thin-oxide devices.

        Requires dg=True to return anything but ~0; returns the
        CLASSICAL centroid (essentially the first mesh cell) otherwise,
        so the on/off comparison is directly gateable.
        """
        psi = self.solve_psi(Vg)
        Lam = self._dg_Lam_n if self.dg else np.zeros_like(psi)
        e = np.clip(psi, -700, 700)
        n = self.nie_s * np.exp(e) * np.exp(-Lam / self.VT)
        n_bulk = self.nie_s * np.exp(self.psi_b)
        dn = np.maximum(n - n_bulk, 0.0)
        sheet = trapz(dn, self.x)
        if sheet <= 0.0:
            return 0.0
        return float(trapz(self.x * dn, self.x) / sheet)

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
