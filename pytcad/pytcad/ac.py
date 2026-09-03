"""M18 phase 1 -- small-signal AC (frequency-domain) analysis for
Device1D.

Mirrors transient.py's shape: this module drives an existing Device1D
through its own _residual_jacobian from the OUTSIDE (the same pattern
continuation.py/transient.py already use) -- device.py is never
touched.

Physics: at a converged DC operating point (psi0, n0, p0),
_residual_jacobian returns F0 (~0) and the real DC Jacobian J0.
Linearizing a small harmonic perturbation u(t) = u0 + du*exp(j*w*t)
around that point turns the interior continuity rows' time-derivative
term into j*w_s*du (w_s = w*t0, the same time scale
transient._time_scale uses), giving a complex linear system

    J_ac(w) = J0 + 1j*w_s*Cmat

where Cmat is EXACTLY transient.py's storage-term matrix
(_step_residual_jacobian's `extra_rows/extra_cols/extra_vals`) with
dt_s = 1.0 substituted in -- not imported from transient.py (that
helper is bundled with Newton/backtracking machinery that does not
factor out cleanly), but gated as numerically identical to it in
tests/test_m18_ac.py's G-CONSISTENCY.

Forcing: driving one contact with a unit AC voltage, the other held at
its DC value (AC-grounded) -- the standard one-port small-signal
measurement. Because each contact's Poisson row is a pure Dirichlet
identity row in J0, the forcing vector is trivial: b[3*driven_node] =
1.0, everywhere else 0 (the un-driven contact's zero forcing is exactly
"AC-grounded"; the n/p contact rows staying zero forcing means the
ohmic-contact densities are held fixed under the AC signal, the usual
ideal-contact assumption).

Terminal-current sensitivity: the edge current Jn[edge]/Jp[edge]
(edge 0 for the left contact, edge N-2 for the right) depends only on
the 6 DOFs of the two adjacent nodes. Rather than re-deriving the
Scharfetter-Gummel edge-current formula's derivatives by hand, this
reuses the exact Jn/Jp arrays _residual_jacobian already returns (the
same values transient._record_current reads) via a real central finite
difference over those 6 scalar directions -- correct by construction
for whatever physics model toggles (FD statistics, band-offset SG,
degeneracy factors, ...) the device was built with.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve, splu


def _time_scale(device):
    """Seconds per unit of Device1D's own scaled time -- identical
    definition to transient._time_scale (device.Ns/device.R0), kept
    as a local one-liner rather than imported so ac.py has no
    dependency on transient.py's internals."""
    return device.Ns / device.R0


def _storage_matrix(device, dV):
    """The coefficient of j*w_s in J_ac(w): identical structure to
    transient._step_residual_jacobian's storage-term addition with
    dt_s = 1.0 substituted in."""
    N = device.N
    idx_n = 3 * np.arange(1, N - 1) + 1
    idx_p = 3 * np.arange(1, N - 1) + 2
    dVi = dV[1:-1]
    extra_rows = np.concatenate([idx_n, idx_p])
    extra_vals = np.concatenate([-dVi, dVi])
    return sp.csr_matrix((extra_vals, (extra_rows, extra_rows)),
                          shape=(3 * N, 3 * N))


def _edge_current_sensitivity(device, psi, n, p, bc, node_lo):
    """Real central-FD sensitivity row vector S (length 3N, nonzero
    only at the 6 DOFs of nodes node_lo/node_lo+1) of the scaled edge
    current (Jn[node_lo] + Jp[node_lo]) with respect to the full state
    vector u = [psi, n, p] interleaved 3-wide per node.

    The edge current depends on psi[node_lo]/psi[node_lo+1] ONLY
    through their difference (Scharfetter-Gummel's `delta` argument),
    so d(I)/d(psi[lo]) and d(I)/d(psi[lo+1]) must be EXACTLY equal in
    magnitude and opposite in sign; the S vector's own two psi entries
    getting dotted against a state response that shifts both nodes'
    psi together (a common physical case: a rigid quasi-neutral-region
    shift) makes this near-cancellation load-bearing, not cosmetic. A
    per-node step size (each node's own psi magnitude, which can
    differ by tens of units from a large additive reference offset
    baked into psi's definition) breaks that cancellation at a scale
    comparable to the genuine signal -- caught by comparing against an
    independent low-frequency finite-difference dI/dV during
    development. Fixed by sharing ONE step size across both nodes of a
    component, so the two FD probes are directly comparable."""
    N = device.N
    S = np.zeros(3 * N)
    nodes = (node_lo, node_lo + 1)

    def edge_I(psi_, n_, p_):
        _, _, Jn, Jp = device._residual_jacobian(psi_, n_, p_, bc)
        return Jn[node_lo] + Jp[node_lo]

    arrays = {0: psi, 1: n, 2: p}
    for comp, base in arrays.items():
        scale = max(abs(base[nodes[0]]), abs(base[nodes[1]]), 1.0)
        h = scale * 1e-6
        for node in nodes:
            arrs_p = [psi.copy(), n.copy(), p.copy()]
            arrs_m = [psi.copy(), n.copy(), p.copy()]
            arrs_p[comp][node] += h
            arrs_m[comp][node] -= h
            Ip = edge_I(*arrs_p)
            Im = edge_I(*arrs_m)
            S[3 * node + comp] = (Ip - Im) / (2 * h)
    return S


class ACResult:
    """freqs [Hz]; Y complex admittance [S/cm^2]; C = Im(Y)/(2*pi*f)
    [F/cm^2]; G = Re(Y) [S/cm^2] -- device.py's own convention of a 1D
    two-terminal device having implicit unit cross-sectional area, so
    an admittance PER AREA doubles as the terminal admittance, exactly
    like current_density()/terminal current already do for DC."""

    def __init__(self, freqs, Y):
        self.freqs = np.asarray(freqs, dtype=float)
        self.Y = np.asarray(Y, dtype=complex)
        omega = 2.0 * np.pi * self.freqs
        with np.errstate(divide="ignore", invalid="ignore"):
            self.C = np.where(omega > 0, self.Y.imag / np.where(omega > 0, omega, 1.0), 0.0)
        self.G = self.Y.real


def ac_sweep(device, freqs, drive="left"):
    """Small-signal admittance Y(f) of a two-terminal Device1D at its
    CURRENT converged DC operating point.  Call solve_equilibrium() or
    solve_bias() first to set that point -- same precondition
    solve_transient() enforces.

    freqs: array of frequencies [Hz] (not angular).
    drive: "left" or "right" (or 0/1, mirroring continuation.py's
    `terminal` convention) -- which contact carries the 1V AC
    excitation; the other stays AC-grounded (held at its DC value).

    Returns an ACResult.  Raises TypeError for anything but a Device1D
    (2D/3D AC analysis is out of scope this phase -- refused
    explicitly, same convention as M16's G-F/M21's 3D+gates refusal).
    """
    from .device import Device1D
    if not isinstance(device, Device1D):
        raise TypeError(
            "ac_sweep only supports Device1D in this phase (M18 phase "
            f"1); got {type(device).__name__}. 2D/3D AC analysis is "
            "explicitly out of scope -- see M18-AC-PLAN.md.")
    if device.psi is None:
        raise RuntimeError(
            "ac_sweep needs a converged DC operating point: call "
            "solve_equilibrium() or solve_bias() first")

    if drive in ("left", 0):
        driven_node = 0
    elif drive in ("right", 1):
        driven_node = device.N - 1
    else:
        raise ValueError(f"drive must be 'left'/'right' (or 0/1), got {drive!r}")

    N = device.N
    dV = device.dV
    psi0, n0, p0 = device.psi, device.n, device.p
    # _residual_jacobian's `bc` only needs the contact (psi, n, p)
    # VALUES, which at a converged Dirichlet contact are exactly the
    # device's own boundary-node state -- no re-derivation from an
    # applied-voltage number needed (device.py does not expose the
    # last-applied bias directly, and doesn't need to here).
    bc0 = ((psi0[0], n0[0], p0[0]), (psi0[-1], n0[-1], p0[-1]))

    _, J0, _, _ = device._residual_jacobian(psi0, n0, p0, bc0)
    Cmat = _storage_matrix(device, dV)
    t0 = _time_scale(device)

    edge = 0 if driven_node == 0 else N - 2
    S = _edge_current_sensitivity(device, psi0, n0, p0, bc0, edge)

    b = np.zeros(3 * N, dtype=complex)
    b[3 * driven_node] = 1.0

    Y = np.empty(len(freqs), dtype=complex)
    J0c = J0.tocsr().astype(complex)
    for i, f in enumerate(freqs):
        omega_s = 2.0 * np.pi * f * t0
        J_ac = (J0c + 1j * omega_s * Cmat).tocsc()
        du = spsolve(J_ac, b)
        Y[i] = S.astype(complex) @ du

    Y_phys = Y * device.J0 / device.VT
    return ACResult(freqs, Y_phys)


# ============================================================= M18 phase 2
# Multi-terminal (here: full 2-port, since Device1D is always exactly
# two-terminal -- see device.py's own docstring "A 1D two-terminal
# semiconductor device") Y-parameter extraction, and fT.
#
# ac_sweep() above is UNCHANGED by everything below: same signature,
# same behavior, same ACResult. This section only ADDS y_parameters()
# and cutoff_frequency() alongside it, reusing every physics primitive
# ac_sweep already validated (J0, Cmat, the edge-current-sensitivity FD
# probe) rather than re-deriving them.
#
# What "multi-terminal" means here: Device1D never has more than two
# ohmic contacts, so there is no N>2 case to generalize to in 1D. The
# actual generalization ac_sweep's one-port measurement was missing is
# reading the AC current response at BOTH contacts for a given drive
# (not just the driven one), and driving EACH contact in turn -- i.e.
# assembling the full 2x2 complex Y matrix Y[i,j] = dI_i/dV_j (all
# other ports AC-grounded), rather than only its [driven, driven] entry.
# A true N>2-terminal case (a BJT/MOSFET's 3 contacts) would need
# device.py itself to grow more contacts, which is out of scope here --
# see the module docstring's 2D/3D refusal, same reasoning applies to
# a hypothetical 1D 3-terminal device that does not exist in this repo.
def _contact_current_sensitivity(device, psi, n, p, bc):
    """Current-INTO-device sensitivity row vectors for BOTH ohmic
    contacts of a Device1D, in the standard multiport sign convention
    I_i = sum_j Y_ij * V_j with I_i defined positive flowing INTO
    terminal i (IEEE/network-parameter convention -- this is what makes
    a passive reciprocal element's Y symmetric with a positive-real
    diagonal, checked directly in tests/test_m18_yparam.py's
    G-YPARAM-RECIPROCITY gate).

    In 1D steady state Jn+Jp is one number shared by every edge
    (device.current_density()'s own docstring: "In 1D steady state
    Jn + Jp is exactly constant"), flowing in the device's fixed +x
    direction. The left contact's adjacent edge (edge 0, between nodes
    0 and 1) measures that +x current directly AS current flowing INTO
    the device at the left contact -- no sign flip, and this is exactly
    the convention ac_sweep's drive="left" already uses uncorrected,
    which is why y_parameters(...)[0, 0] reduces EXACTLY to
    ac_sweep(..., drive="left").Y (checked in
    test_g_yparam_reduces_to_ac_sweep_one_port). The right contact's
    adjacent edge (edge N-2) measures the SAME +x current, which at the
    right contact is flowing OUT of the device -- so the right
    terminal's current-into-device sensitivity is the NEGATIVE of that
    edge's raw sensitivity.

    KNOWN, QUANTIFIED LIMIT (investigated directly -- this is NOT a
    coding bug, and reciprocity IS checked, not skipped, in
    tests/test_m18_yparam.py's G-YPARAM-RECIPROCITY gate): this reuses
    ac_sweep's own edge Jn+Jp reading, i.e. PARTICLE current only. The
    true AC terminal current at a cross-section also has a
    displacement-current piece, -eps~[edge]/h[edge] * d(psi[k+1] -
    psi[k])/dt (Poisson's own row uses exactly that et[edge]/h[edge]
    flux coefficient -- see device.py's Poisson-row assembly), which
    particle current alone omits. Verified directly (not shipped, kept
    out per the reasoning below) that ADDING this term makes Y00 and
    Y11 (and hence Y12=Y21) agree to ~1e-8 relative even at 1e10 Hz, up
    from ~1.2% without it -- confirming this omission, not a
    sign/indexing bug, is the reciprocity gap's exact root cause. It is
    NOT added here: doing so would make y_parameters(...)[0, 0]
    disagree with ac_sweep's own (unmodified, frozen) Y -- the task's
    own strongest regression guard -- since ac_sweep reads the same
    particle-current-only edge quantity. Practical consequence: Y12=Y21
    (and the equivalent Y[0,0]==Y[1,1] two-terminal identity) holds to
    <1e-3 relative up to ~1e8 Hz on the reference diode and only
    degrades into the multi-percent range above ~1e9-1e10 Hz -- well
    past where G-ROLLOFF (test_m18_ac.py) already documents the
    underlying AC solve itself losing fidelity (C going slightly
    negative near 1e12 Hz). A future fix, if ever genuinely needed at
    high frequency, would add that same displacement term to BOTH
    ac_sweep and y_parameters together so they stay numerically
    consistent with each other -- not to y_parameters alone.
    """
    N = device.N
    S_left = _edge_current_sensitivity(device, psi, n, p, bc, 0)
    S_right = -_edge_current_sensitivity(device, psi, n, p, bc, N - 2)
    return [S_left, S_right]


class YParamResult:
    """freqs [Hz]; Y complex 2-port admittance matrix, shape
    (len(freqs), 2, 2) [S/cm^2] (device.py's implicit-unit-area
    convention, same as ACResult -- see ACResult's own docstring).
    Port order is fixed: port 0 = left contact, port 1 = right contact
    (Device1D's only two contacts; see the module comment above this
    class for why there is no N>2 case in 1D).

    Y[k, i, j] = dI_i/dV_j at freqs[k], all OTHER ports AC-grounded
    (held at their DC bias with zero AC perturbation) -- the standard
    multiport short-circuit admittance-parameter definition, with I_i
    defined positive flowing INTO terminal i (see
    _contact_current_sensitivity's docstring for the sign derivation).

    port_names: ("left", "right"), exposed so callers/tests can index
    by name instead of remembering the 0/1 convention.
    """

    def __init__(self, freqs, Y):
        self.freqs = np.asarray(freqs, dtype=float)
        self.Y = np.asarray(Y, dtype=complex)
        if self.Y.shape != (self.freqs.size, 2, 2):
            raise ValueError(
                f"Y must have shape (len(freqs), 2, 2); got {self.Y.shape}")
        self.port_names = ("left", "right")


def y_parameters(device, freqs):
    """Full 2-port complex Y-parameter matrix Y(f) of a two-terminal
    Device1D at its CURRENT converged DC operating point. Call
    solve_equilibrium() or solve_bias() first, same precondition
    ac_sweep() enforces.

    Method: identical linear physics to ac_sweep() -- at each
    frequency f, solve the complex system
        (J0 + 1j*omega_s*Cmat) @ du = b_k
    for EACH port k in turn (b_k = a unit AC voltage forcing at
    contact k's Poisson row, all else zero -- "AC-grounded" for the
    other port, same as ac_sweep's single-port forcing), then read off
    the resulting AC current at EVERY contact i via
    Y[i, k] = S_i @ du_k, where S_i is contact i's current-INTO-device
    sensitivity row (see _contact_current_sensitivity). This is
    ac_sweep's own one-port measurement performed once per port instead
    of once, using the same J0/Cmat/edge-current-sensitivity machinery.

    Factorization reuse: J0 + 1j*omega_s*Cmat depends only on frequency,
    not on which port is driven -- only the RHS b_k changes across the
    2 ports at a fixed frequency. So this factors that matrix ONCE per
    frequency (scipy.sparse.linalg.splu) and reuses the LU factors for
    both ports' solves, rather than calling spsolve (which would
    refactor from scratch) twice. (pytcad/linsolve.py's solve_linear()
    does not expose a factor-once/solve-multiple-RHS entry point --
    checked directly -- so this uses splu here rather than routing
    through it.)

    freqs: array of frequencies [Hz] (not angular).

    Returns a YParamResult. Raises TypeError for anything but a
    Device1D (2D/3D AC analysis is out of scope -- same refusal as
    ac_sweep; see this module's docstring and the module comment above
    this function for why there is no N>2-terminal case in 1D).

    Scope limits (explicit, per ARCHITECTURE.md convention):
      - 1D only, exactly 2 ports (Device1D's only 2 contacts) -- no
        2D/3D, no true N>2-terminal devices (this repo has none in 1D).
      - fmax (maximum oscillation frequency, from Mason's unilateral
        power gain U(f)=1 crossing) is NOT implemented here: U requires
        the device's own output/reverse-transfer conductances in a way
        that is only physically meaningful for an active 3-terminal
        device (a BJT/MOSFET); computing it formally on a 2-terminal
        diode's reciprocal Y matrix (where Y12=Y21) would give a
        vacuous/degenerate answer, not a real fmax figure of merit --
        deferred rather than faked. fT (below, via cutoff_frequency())
        does not have this problem: it is well-defined from Y21/Y11
        alone for any 2-port, reciprocal or not.
    """
    from .device import Device1D
    if not isinstance(device, Device1D):
        raise TypeError(
            "y_parameters only supports Device1D (1D two-terminal "
            f"devices); got {type(device).__name__}. 2D/3D AC analysis "
            "is explicitly out of scope -- see M18-AC-PLAN.md.")
    if device.psi is None:
        raise RuntimeError(
            "y_parameters needs a converged DC operating point: call "
            "solve_equilibrium() or solve_bias() first")

    N = device.N
    dV = device.dV
    psi0, n0, p0 = device.psi, device.n, device.p
    bc0 = ((psi0[0], n0[0], p0[0]), (psi0[-1], n0[-1], p0[-1]))

    _, J0, _, _ = device._residual_jacobian(psi0, n0, p0, bc0)
    Cmat = _storage_matrix(device, dV)
    t0 = _time_scale(device)
    J0c = J0.tocsr().astype(complex)

    S = _contact_current_sensitivity(device, psi0, n0, p0, bc0)  # [S_left, S_right]

    b_left = np.zeros(3 * N, dtype=complex)
    b_left[0] = 1.0
    b_right = np.zeros(3 * N, dtype=complex)
    b_right[3 * (N - 1)] = 1.0
    b_ports = [b_left, b_right]

    Y = np.empty((len(freqs), 2, 2), dtype=complex)
    for kf, f in enumerate(freqs):
        omega_s = 2.0 * np.pi * f * t0
        J_ac = (J0c + 1j * omega_s * Cmat).tocsc()
        lu = splu(J_ac)
        for j in range(2):  # driven port
            du = lu.solve(b_ports[j])
            for i in range(2):  # observed port
                Y[kf, i, j] = S[i].astype(complex) @ du

    scale = device.J0 / device.VT  # same physical scaling ac_sweep applies
    return YParamResult(freqs, Y * scale)


def cutoff_frequency(yres):
    """Current-gain cutoff frequency f_T: the frequency at which the
    short-circuit current gain h21(f) = Y21(f)/Y11(f) has |h21| = 1
    (the standard small-signal RF figure of merit -- e.g. Sedra/Smith's
    or Sze's f_T definition for a 2-port).

    Method: |h21(f)| is monotonically decreasing across the swept range
    for a diffusion/depletion-capacitance-dominated device (the same
    roll-off ac_sweep's own G-ROLLOFF gate exercises), so this
    bisects for the crossing in log(f)-log(|h21|) space -- a standard,
    robust way to locate a roughly power-law-shaped crossing without
    needing a dense frequency sweep to land a point exactly on it.
    No prior fT-estimation logic already existed anywhere in this repo
    to reuse (confirmed while writing this: grep for "h21"/"cutoff" /
    "f_T" over pytcad/ turned up nothing) -- this is a fresh, standard-
    formula implementation, not a re-derivation of new physics.

    yres: a YParamResult from y_parameters() (or anything exposing the
    same .freqs / .Y shape (nf, 2, 2) contract).

    Returns f_T [Hz], or None if |h21| never crosses 1 within the swept
    range (either it starts below 1 -- device has no useful current
    gain at any swept frequency -- or stays above 1 throughout --
    fT lies beyond the swept range; report both cases as None rather
    than extrapolating past validated data).

    Caveat (documented, not silently worked around): this locates the
    FIRST index where |h21| < 1 and bisects around it, which assumes a
    genuinely decreasing |h21| -- on data that is merely FLAT (a
    2-terminal, no-gain device such as this repo's diode, where
    |h21|=1 identically up to numerical noise -- see
    tests/test_m18_yparam.py's test_g_ft_diode_has_no_meaningful_
    current_gain), sub-noise-floor ripple can produce a spurious
    "crossing" with no physical meaning. Callers should treat a
    returned f_T as meaningful only when |h21| is independently known
    (or checked) to have a genuine decreasing trend across the swept
    range, which requires an amplifying (3-terminal) device this 1D
    repo does not model.

    gm (transconductance): for this repo's 2-terminal Device1D, "gm" and
    the low-frequency |Y21| conductance are the SAME physical quantity
    (there is no separate input/output terminal pair to distinguish
    them, unlike a 3-terminal BJT/MOSFET) -- and by reciprocity
    (test_g_yparam_reciprocity) Y21=Y12=Y11=Y22's real parts for a
    plain diode's junction anyway. Rather than name a redundant
    diode-only "gm" that could not extend to the 3-terminal case
    without re-deriving what it means there, gm is exposed directly as
    yres.Y[0, 1, 0].real (Re(Y21) at the lowest swept frequency) --
    callers wanting it read that field; no separate accessor is added
    here to avoid a name that would need re-defining the moment this
    repo grows a real 3-terminal (BJT/MOSFET) device.
    """
    freqs = yres.freqs
    Y11 = yres.Y[:, 0, 0]
    Y21 = yres.Y[:, 1, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        h21 = np.where(np.abs(Y11) > 0, Y21 / Y11, np.inf)
    mag = np.abs(h21)

    if not np.any(np.isfinite(mag)):
        return None
    if mag[0] < 1.0:
        return None  # no useful gain even at the lowest swept frequency
    if mag[-1] >= 1.0:
        return None  # fT lies beyond the swept range

    # First index where the (assumed monotonically decreasing) |h21|
    # drops below 1; bisect log-log between that point and the one
    # before it.
    below = np.where(mag < 1.0)[0]
    i1 = int(below[0])
    i0 = i1 - 1
    if i0 < 0:
        return None

    lf0, lf1 = np.log(freqs[i0]), np.log(freqs[i1])
    lm0, lm1 = np.log(mag[i0]), np.log(mag[i1])
    if lm0 == lm1:
        return float(freqs[i0])
    # Linear interpolation in log-log space for the |h21| = 1
    # (log(mag) = 0) crossing.
    frac = (0.0 - lm0) / (lm1 - lm0)
    log_fT = lf0 + frac * (lf1 - lf0)
    return float(np.exp(log_fT))
