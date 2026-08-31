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
from scipy.sparse.linalg import spsolve


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
