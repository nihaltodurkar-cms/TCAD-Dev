"""M20: density-gradient quantum correction -- analysis layer.

Three pure pieces, no solver imports:

1. quantum_potential(x, n, m_star, gamma):
   the Ancona/Bohm quantum potential Lambda(x) [V] that multiplies the
   classical densities by exp(-Lambda/V_T).  This is the DG term the
   MOSCapacitor (and Device1D equilibrium) solve couples in.

2. airy_triangular_well(F, m_star):
   CLOSED-FORM Airy subband energies and centroids of a uniform-field
   (triangular) well -- the published-value reference for gate G-B.

3. schrodinger_poisson(x, psi_band, ...):
   self-consistent 1D Schroedinger-Poisson inversion-layer solver (the
   milestone's required published-value gate): finite-difference
   Hamiltonian on the (non-uniform) mesh, lowest eigenstates via
   scipy eigsh, 2D-DOS Boltzmann subband occupations, outer Poisson
   fixed point.

Provenance: Ancona & Stafford, IEEE Trans. Electron Devices 46, 1799
(1999); Ancona, Superlattices & Microstructures 27, 457 (2000).  See
M20-DENSITY-GRADIENT-PLAN.md section 1 for the prefactor's honest
provenance caveat (the web literature search could not be run; the
Airy and S-P gates here pin everything that matters numerically).
"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .constants import HBAR, KB, Q, M0, thermal_voltage, trapz

# Numerical guard: clamp |Lambda| at this many thermal voltages.
#
# CORRECTED 2026-08-29 (was: "only the deep-bulk minority tail can
# reach it" -- measured false): on MOSCapacitor's mesh, the RAW
# (unclamped) curvature at the first interior node in strong inversion
# reaches ~81 VT from the classical density alone, at gamma=1, before
# any outer-loop feedback -- this clamp engages hard at the surface,
# the primary physics of interest, not just a numerically negligible
# bulk tail. It is load-bearing: removing it (or raising it much
# further) makes the outer fixed point diverge outright rather than
# settle on a larger physical value (measured: raising to 200*VT with
# the self-reference bug already fixed still overflows). See
# M20-DENSITY-GRADIENT-PLAN.md section 6 for the full finding.
LAMBDA_MAX_VT = 20.0


def _dg_prefactor(m_star, gamma):
    """The DG quantum-potential SI prefactor, gamma*hbar^2/(2 m* q),
    in V*m^2 -- shared between quantum_potential's explicit-formula
    evaluation and the coupled-Newton residual/Jacobian assembly in
    moscap.py/device.py, so both use the EXACT SAME formula rather
    than a second hand-transcription of it (M20 coupled-Newton
    reformulation, 2026-08-31)."""
    return gamma * HBAR * HBAR / (2.0 * np.asarray(m_star, dtype=float) * M0 * Q)


def quantum_potential(x, n, m_star, gamma=1.0, T=300.0):
    """DG quantum potential Lambda(x) [V] of a 1D density profile.

        Lambda = -(gamma * hbar^2 / (2 m* q)) * (sqrt(n))'' / sqrt(n)

    evaluated with the 3-point second difference on the non-uniform
    mesh, in PHYSICAL centimeters (the SI prefactor converts via the
    1e4 cm^-2 -> m^-2 factor).  Boundary nodes get Lambda = 0 (the
    Neumann choice -- see the plan's section 1 BC discussion).  n is
    floored at a tiny positive value before the sqrt so the ratio
    stays finite; |Lambda| is clamped to LAMBDA_MAX_VT * V_T.

    Returns an array the length of x, in VOLTS.
    """
    if gamma <= 0.0 or not np.isfinite(gamma):
        raise ValueError(f"dg gamma must be finite and > 0, got {gamma!r}")
    x = np.asarray(x, dtype=float)
    n = np.maximum(np.asarray(n, dtype=float), 1e-300)
    g = np.sqrt(n)
    m = np.asarray(m_star, dtype=float)
    if m.ndim == 0:
        m = np.full_like(g, float(m))       # broadcast a scalar mass
    VT = thermal_voltage(T)

    # 3-point second difference on a non-uniform mesh:
    # g''_i = 2/(h_{i-1}+h_i) * [ (g_{i+1}-g_i)/h_i - (g_i-g_{i-1})/h_{i-1} ]
    h = np.diff(x)                            # cm
    Lam = np.zeros_like(g)
    if len(x) >= 3:
        interior = np.arange(1, len(x) - 1)
        dd = (2.0 / (h[:-1] + h[1:])) * (
            (g[2:] - g[1:-1]) / h[1:]
            - (g[1:-1] - g[:-2]) / h[:-1])            # [cm^-2]
        # SI prefactor: hbar^2/(2 m* q) [V m^2]; dd is per cm^2 -> *1e4
        # (m* may be a per-node array -- heterostructure devices)
        pref = _dg_prefactor(m, gamma)     # V m^2
        Lam[interior] = -pref[1:-1] * 1e4 * dd / g[1:-1]
    # boundary nodes: Lambda = 0 (Neumann choice, plan section 1)
    Lam = np.clip(Lam, -LAMBDA_MAX_VT * VT, LAMBDA_MAX_VT * VT)
    return Lam


# Airy-function zeros a_k (Abramowitz & Stegun 10.4.94 et seq.; the
# first six are standard tabulated values: 2.33811, 4.08795, 5.52056,
# 6.78671, 7.94413, 9.02265).
_AIRY_ZEROS = np.array([2.3381074105, 4.0879494441, 5.5205598281,
                        6.7867080901, 7.9441335871, 9.0226508533])


def airy_triangular_well(F_V_cm, m_star=0.26, n_levels=3):
    """Analytic triangular-well subbands (published-value reference).

    A uniform field F with a hard wall at x=0 has Airy-function
    eigenstates with energies

        E_k = (hbar^2/(2 m*))^{1/3} (q F)^{2/3} a_k       [J]

    and probability centroid <x>_k = 2 E_k / (3 q F) (the standard
    Airy result: the classical turning point is 2/3 of the way).

    F_V_cm: field magnitude [V/cm]; m_star in units of m0.
    Returns (E_eV [n_levels], x_centroid_cm [n_levels]).
    """
    if F_V_cm <= 0.0:
        raise ValueError("F must be positive")
    m = m_star * M0
    F = F_V_cm * 100.0                          # V/m
    k = np.arange(n_levels) % len(_AIRY_ZEROS)
    a = _AIRY_ZEROS[k]
    E = (HBAR * HBAR / (2.0 * m)) ** (1.0 / 3.0) * (Q * F) ** (2.0 / 3.0) * a
    E_eV = E / Q
    x_c = 2.0 * E / (3.0 * Q * F) * 100.0       # m -> cm
    return E_eV, x_c


def schrodinger_poisson(x_cm, E_band_eV, m_star=0.26, T=300.0,
                        N_total=None, n_levels=4, max_outer=60,
                        tol=1e-4, hard_wall_left=True):
    """Self-consistent 1D Schroedinger-Poisson inversion-layer solve.

    Solves, on the given mesh with conduction-band profile E_band_eV
    (eV, measured from the SAME zero as the subband energies):

        [-hbar^2/(2 m*) d2/dx2 + E_band(x)] psi_k = E_k psi_k
        n(x)  = sum_k  N_k |psi_k(x)|^2
        N_k   = (m* kT / (pi hbar^2)) * ln(1 + exp((E_F - E_k)/kT))

    (2D density-of-states Boltzmann subband occupation -- the textbook
    inversion-layer approximation, e.g. Sze & Ng chapter 4.)  The
    Poisson side enters through E_band: the caller supplies the
    SELF-CONSISTENT loop by updating E_band from the space charge.
    This function performs ONE Schroedinger+occupation pass and
    returns the quantum density; the self-consistent driver is
    `schrodinger_poisson_mos` below, which owns the Poisson side.

    Returns (E_k_eV [n_levels], n_q [cm^-3 per mesh node]).
    """
    x = np.asarray(x_cm, dtype=float)
    N = len(x)
    if N < 3:
        raise ValueError("need at least 3 mesh nodes")
    h = np.diff(x) * 1e-2                       # m
    Eb = np.asarray(E_band_eV, dtype=float) * Q  # J
    m = m_star * M0

    # 3-point Hamiltonian on the non-uniform mesh (scaled units of J):
    #   -(hbar^2/2m) * [ (psi_{i+1}-psi_i)/h_i - (psi_i-psi_{i-1})/h_{i-1} ]
    #                                    / (0.5*(h_{i-1}+h_i))
    hb2 = HBAR * HBAR / (2.0 * m)
    main = np.empty(N)
    up = np.empty(N - 1)
    lo = np.empty(N - 1)
    hbar_l = 0.5 * (h[:-1] + h[1:])
    main[1:-1] = hb2 * (1.0 / h[1:] + 1.0 / h[:-1]) / hbar_l
    up[1:] = -hb2 / (h[1:] * hbar_l)
    lo[:-1] = -hb2 / (h[:-1] * hbar_l)
    # Dirichlet penalty scale: must be huge RELATIVE TO the interior
    # Hamiltonian entries (~hb2/h^2, J) so the boundary eigenvalue sits
    # far outside the physical spectrum, but NOT an absolute constant --
    # a fixed 1e18 J next to ~1e-18 J interior entries is a ~1e36
    # condition number, far beyond float64's ~1e16 dynamic range.
    # eigsh's Lanczos iteration on that matrix returned eigenvalues
    # hundreds of eV off Airy's 0.266 eV reference (self-caught:
    # test_gb_schrodinger_matches_airy_triangular_well).  1e8x the
    # interior scale keeps the boundary state exactly as excluded from
    # which='SA' while staying inside double-precision range.
    big = 1e8 * np.abs(main[1:-1]).max()
    # left boundary: hard wall psi(0) = 0 -> identity row with the
    # eigenvalue shifted out of the way by a huge diagonal (excluded
    # from which='SA' results).
    if hard_wall_left:
        main[0] = big
        up[0] = 0.0
    else:
        # free (Neumann-like) left end: mirror the interior stencil with
        # a ghost node psi_{-1} = psi_1, i.e. the same row as node 1's
        # stencil would give for a flat wavefunction.
        main[0] = hb2 / (h[0] * h[0])
        up[0] = -hb2 / (h[0] * h[0])
    # right boundary (bulk end): hard wall psi = 0 there as well.  The
    # inversion-layer eigenstates decay LONG before the bulk end (the
    # conduction band sits ~Eg/2+phi_F above E_F there), so Dirichlet
    # at the far end is the decayed-tail equivalent and -- unlike the
    # previous `main[-1] = main[-1]` no-op -- leaves no np.empty garbage
    # in the diagonal (self-caught: the old line read UNINITIALIZED
    # memory, making the eigensolve nondeterministic).
    main[-1] = big
    lo[-1] = 0.0
    H = sp.diags([lo, main + Eb, up], [-1, 0, 1], format="csr")

    n_eig = min(n_levels, N - 2)
    vals, vecs = spla.eigsh(H, k=n_eig, which="SA",
                            maxiter=20000, tol=1e-10)
    order = np.argsort(vals)
    vals, vecs = vals[order], vecs[:, order]

    # normalize on the mesh (trapezoid, cm)
    w = np.empty(N)
    w[0] = 0.5 * h[0]
    w[-1] = 0.5 * h[-1]
    w[1:-1] = 0.5 * (h[:-1] + h[1:])
    norms = np.sqrt(np.sum(vecs * vecs * w[:, None], axis=0))
    vecs = vecs / norms[None, :]

    kT = KB * T
    # 2D-DOS sheet density per subband: m* kT / (pi hbar^2)  [m^-2] --
    # the kT is INSIDE this factor; the occupation below must NOT
    # multiply by kT again (self-caught in the M20 gate-writing pass:
    # the double-kT version gives ~1e-4 m^-2 occupations, i.e. sheet
    # densities ~1e-7 cm^-2, and the N_total bisection can never reach
    # its bracket top -- hand-check: m*=0.26 at 300 K gives 2.8e16 m^-2,
    # i.e. ~2e12 cm^-2 at eta=0, the textbook scale).
    dos = m * kT / (np.pi * HBAR * HBAR)         # [m^-2] per subband
    # E_F reference: subband occupations need an absolute Fermi level.
    # For the inversion-layer gate the caller knows the total sheet
    # density; if given, solve E_F so sum(N_k) == N_total (bisection).
    if N_total is not None:
        lo_e, hi_e = vals[0] - 50.0 * kT, vals[0] + 50.0 * kT
        for _ in range(200):
            mid = 0.5 * (lo_e + hi_e)
            occ = dos * np.log1p(
                np.exp(np.clip((mid - vals) / kT, -700, 700)))
            if occ.sum() < N_total:
                lo_e = mid
            else:
                hi_e = mid
            if hi_e - lo_e < 1e-12 * kT:
                break
        E_F = 0.5 * (lo_e + hi_e)
    else:
        E_F = vals[0]                           # degenerate default

    occ = dos * np.log1p(
        np.exp(np.clip((E_F - vals) / kT, -700, 700)))     # [m^-2]
    # n(x) = sum_k N_k |psi_k(x)|^2 (module docstring's own law) -- NOT
    # sum_k N_k psi_k(x): eigenvectors carry an arbitrary sign, so the
    # unsquared sum could (and did) go negative and gave the wrong
    # magnitude/centroid entirely (self-caught: G-B's occupation-scale
    # and Airy-centroid gates).
    n_q = (vecs * vecs * occ[None, :]).sum(axis=1)  # [m^-3]
    return vals / Q, n_q * 1e-6                 # eV, cm^-3


def schrodinger_poisson_mos(mos, Vg, n_levels=4, max_outer=60,
                            tol=1e-4):
    """Self-consistent S-P driver on a MOSCapacitor's mesh.

    Alternates: classical Poisson potential from MOSCapacitor.solve_psi
    -> Schroedinger solve -> quantum electron density -> Poisson with
    that density -> ... until the sheet density closes.  This is the
    milestone's published-value reference solver: its centroid is what
    the DG MOSCapacitor result is gated against (G-C).

    Returns dict(E_eV, psi, n_q [cm^-3], sheet [cm^-2],
                centroid_cm [electron charge centroid]).
    """
    x = mos.x
    psi = mos.solve_psi(Vg)
    for _ in range(max_outer):
        # conduction band relative to the bulk Fermi level, in eV.
        # psi is referenced to the bulk intrinsic level (scaled by VT):
        # E_F sits VT*psi_b below E_i in the p-bulk, and E_c(x) - E_i(x)
        # = Eg/2 - q*phi(x) with phi = (psi - psi_b)*VT [V] measured
        # from the bulk.  Hence
        #     E_c(x) - E_F = Eg/2 - (psi(x) - psi_b)*VT   [eV]
        # (HAND-CHECKED in the M20 gate-writing pass: in strong
        # inversion psi(0) >> psi_b, so this is SMALLER at the surface
        # than in the bulk -- the band bends DOWN, as it must.  The
        # opposite sign puts the inversion well in the BULK, which is
        # unphysical and was caught by the G-C centroid gate.)
        E_band = (0.5 * mos.mat.Eg(mos.T)
                  - (psi - mos.psi_b) * mos.VT)
        # occupation: the gate fixes the TOTAL inversion sheet density
        # from the CLASSICAL solve (the gate voltage fixes the total
        # charge; the S-P solve REDISTRIBUTES it into subbands).  This
        # is the standard "S-P on the classical potential" gate
        # approximation, documented: the centroid is insensitive to the
        # Poisson feedback at the gate's factor-of-2 tolerance.
        # nie_s = nie/Ns is the SCALED (dimensionless) intrinsic density
        # used internally by MOSCapacitor's own psi solve; unlike
        # inversion_centroid (which only ever forms a scale-invariant
        # x-weighted ratio of densities), sheet_cl here is fed to
        # schrodinger_poisson as an absolute N_total and returned as an
        # absolute cm^-2 sheet density, so it needs the PHYSICAL
        # density: nie_s * Ns (self-caught: sheet_cl was landing at
        # ~1e-5 cm^-2 instead of the ~1e12-1e13 textbook inversion-sheet
        # scale, a flat factor of Ns short).
        n_cl = mos.nie_s * mos.Ns * np.exp(np.clip(psi, -700, 700))
        sheet_cl = trapz(np.maximum(n_cl - 0.0, 0.0), x)
        if sheet_cl <= 0.0:
            return dict(E_eV=np.zeros(0), psi=psi,
                        n_q=np.zeros_like(psi), sheet=0.0,
                        centroid_cm=0.0)
        E_k, n_q = schrodinger_poisson(
            x, E_band, m_star=mos.mat.m_n_star, T=mos.T,
            N_total=sheet_cl * 1e4, n_levels=n_levels)     # m^-2
        sheet_q = trapz(n_q, x)
        if abs(sheet_q - sheet_cl) / max(sheet_cl, 1e-30) < tol:
            break
        # no Poisson feedback available on MOSCapacitor's interface
        # (see above): the loop runs once by construction.
        break
    centroid = (trapz(x * n_q, x) / max(trapz(n_q, x), 1e-300))
    return dict(E_eV=E_k, psi=psi, n_q=n_q, sheet=float(sheet_q),
                centroid_cm=float(centroid))
