"""M45 -- small-signal AC (frequency-domain) N-port analysis for Device3D,
closing the "Transient / small-signal AC -> 3D" row of ARCHITECTURE.md's
dimensional-lift coverage matrix (section 5.3).

A direct lift of ac2d.py's own pattern one axis further (same
relationship ac2d.py has to ac.py): drives an existing Device3D through
its own _residual_jacobian from the OUTSIDE; device3d.py is never
touched. Every entry of device.bcs (DirichletBC ohmic contacts and
GateBC gates) becomes one port, exactly as in ac2d.py.

The two port kinds enter the small-signal problem identically to 2D:

  DirichletBC (ohmic contact): unit AC voltage forcing at every node the
  contact touches; observed current reuses terminal_current()'s own
  quantity (F_n+F_p summed over the contact's nodes) via a
  finite-difference sensitivity, generalized from ac2d.py's 4-connected
  `_support_nodes` to Device3D's 6-connected (x/y/z) neighbor set.

  GateBC (Robin condition on psi only): the closed-form forcing/
  observation is IDENTICAL to ac2d.py's own derivation (see that
  module's docstring for the full argument -- a lossless capacitive
  port contributing +jwC to its own row, -jwC cross-coupled). One real
  difference from ac2d.py: Device2D's GateBC always sits on the same
  (vertical) face, so ac2d.py hardcodes its area weight as
  `kappa*dVx[i]`; Device3D's GateBC can sit on a face normal to ANY of
  x/y/z (device3d.py's own `_gate_face_weight` already picks the right
  pair of control-volume widths per normal_axis), so this module calls
  that helper directly instead of re-deriving the area weight --
  reusing device3d.py's own already-gated helper rather than an
  independent re-derivation that could silently disagree with it.

Cmat (n/p storage) needs no gate-row addition, for the identical reason
ac2d.py's own docstring gives: Poisson has no time derivative in this
codebase, full stop.

Raises TypeError for anything but a Device3D (1D/2D AC analysis lives
in ac.py/ac2d.py).
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu


def _time_scale(device):
    """Identical definition to ac.py/ac2d.py/transient3d.py's own
    _time_scale -- kept as a local one-liner so this module has no
    dependency on any of their internals."""
    return device.Ns / device.R0


def _dirichlet_excluded_nodes(device):
    """Flat node indices whose n/p continuity rows are OVERWRITTEN to a
    pure Dirichlet identity (S_n=S_p=0, the default) -- excluded from
    Cmat's storage rows, identically to ac2d.py's own
    `_dirichlet_excluded_nodes` one axis further."""
    from .device3d import DirichletBC
    Ny, Nx = device.Ny, device.Nx
    excl_n, excl_p = [], []
    for bc in device.bcs.values():
        if isinstance(bc, DirichletBC):
            kk = (bc.k * Ny * Nx + bc.j * Nx + bc.i).astype(int)
            if device.models.S_n == 0.0:
                excl_n.append(kk)
            if device.models.S_p == 0.0:
                excl_p.append(kk)
    excl_n = np.unique(np.concatenate(excl_n)) if excl_n else np.array([], dtype=int)
    excl_p = np.unique(np.concatenate(excl_p)) if excl_p else np.array([], dtype=int)
    return excl_n, excl_p


def _storage_matrix(device):
    """The coefficient of j*w_s in J_ac(w): Device3D's box-integration
    n/p storage term, zeroed at nodes whose row is Dirichlet-overwritten
    (see _dirichlet_excluded_nodes)."""
    N = device.N
    dVf = device.dV.ravel()
    excl_n, excl_p = _dirichlet_excluded_nodes(device)

    all_k = np.arange(N)
    keep_n = np.setdiff1d(all_k, excl_n, assume_unique=False)
    keep_p = np.setdiff1d(all_k, excl_p, assume_unique=False)

    idx_n = 3 * keep_n + 1
    idx_p = 3 * keep_p + 2
    extra_rows = np.concatenate([idx_n, idx_p])
    extra_vals = np.concatenate([-dVf[keep_n], dVf[keep_p]])
    return sp.csr_matrix((extra_vals, (extra_rows, extra_rows)),
                          shape=(3 * N, 3 * N))


def _support_nodes(kk, Nx, Ny, Nz):
    """kk's own nodes plus every 6-connected (grid) neighbor -- the full
    set of nodes Device3D's box-integration F_n/F_p at kk can possibly
    depend on (a node's continuity residual only ever touches itself and
    its +/-x, +/-y, +/-z neighbors). Direct 3D generalization of
    ac2d.py's own 4-connected `_support_nodes`."""
    kk = np.asarray(kk, dtype=int)
    k_, rem = np.divmod(kk, Nx * Ny)
    j_, i_ = np.divmod(rem, Nx)
    parts = [kk]
    left = np.where(i_ > 0, kk - 1, -1)
    right = np.where(i_ < Nx - 1, kk + 1, -1)
    up = np.where(j_ > 0, kk - Nx, -1)
    down = np.where(j_ < Ny - 1, kk + Nx, -1)
    back = np.where(k_ > 0, kk - Nx * Ny, -1)
    front = np.where(k_ < Nz - 1, kk + Nx * Ny, -1)
    for arr in (left, right, up, down, back, front):
        parts.append(arr[arr >= 0])
    return np.unique(np.concatenate(parts))


def _ohmic_current_sensitivity(device, psi, n, p, voltages, kk):
    """Real sensitivity row S (length 3N) of the DC current INTO the
    device through an ohmic contact's node set `kk`, via a
    shared-step-size central finite difference over kk's support --
    identical method to ac2d.py's own `_ohmic_current_sensitivity`, one
    axis further."""
    Nx, Ny, Nz, N = device.Nx, device.Ny, device.Nz, device.N
    support = _support_nodes(kk, Nx, Ny, Nz)
    S = np.zeros(3 * N)

    def contact_I(psi_, n_, p_):
        *_, F_n, F_p = device._residual_jacobian(psi_, n_, p_, voltages)
        return float((F_n.ravel()[kk] + F_p.ravel()[kk]).sum())

    psi_f, n_f, p_f = psi.ravel().copy(), n.ravel().copy(), p.ravel().copy()
    bases = {0: psi_f, 1: n_f, 2: p_f}
    shp = (Nz, Ny, Nx)
    for comp, base in bases.items():
        scale = max(float(np.abs(base[support]).max()), 1.0)
        h = scale * 1e-6
        for node in support:
            arrs_p = [psi_f.copy(), n_f.copy(), p_f.copy()]
            arrs_m = [psi_f.copy(), n_f.copy(), p_f.copy()]
            arrs_p[comp][node] += h
            arrs_m[comp][node] -= h
            Ip = contact_I(arrs_p[0].reshape(shp), arrs_p[1].reshape(shp),
                            arrs_p[2].reshape(shp))
            Im = contact_I(arrs_m[0].reshape(shp), arrs_m[1].reshape(shp),
                            arrs_m[2].reshape(shp))
            S[3 * node + comp] = (Ip - Im) / (2 * h)
    return S


class YParamResult3D:
    """freqs [Hz]; Y complex N-port admittance matrix, shape
    (len(freqs), P, P) [A/V], real Amps convention (like
    Device3D.terminal_current, unlike Device2D's A/cm -- 3D meshes
    every physical dimension, no implicit unit-depth). port_names: tuple
    of device.bcs keys, in dict insertion order."""

    def __init__(self, freqs, Y, port_names):
        self.freqs = np.asarray(freqs, dtype=float)
        self.Y = np.asarray(Y, dtype=complex)
        P = len(port_names)
        if self.Y.shape != (self.freqs.size, P, P):
            raise ValueError(
                f"Y must have shape (len(freqs), {P}, {P}); got {self.Y.shape}")
        self.port_names = tuple(port_names)


def y_parameters(device, freqs):
    """Full N-port complex Y-parameter matrix Y(f) of a Device3D at its
    CURRENT converged DC operating point (call solve_equilibrium()/
    solve_bias() first). Identical definition to ac2d.py's own
    y_parameters, one axis further -- see that module's docstring for
    the full forcing/observation derivation of each port kind.

    Raises TypeError for anything but a Device3D.
    """
    from .device3d import Device3D, DirichletBC, GateBC
    if not isinstance(device, Device3D):
        raise TypeError(
            "ac3d.y_parameters only supports Device3D; got "
            f"{type(device).__name__}. 1D/2D AC analysis lives in "
            "ac.py / ac2d.py.")
    if device.psi is None:
        raise RuntimeError(
            "y_parameters needs a converged DC operating point: call "
            "solve_equilibrium() or solve_bias() first")

    Nx, Ny, N = device.Nx, device.Ny, device.N
    psi0, n0, p0 = device.psi, device.n, device.p
    voltages = {name: bc.V for name, bc in device.bcs.items()
                if isinstance(bc, DirichletBC)}

    _, J0, *_ = device._residual_jacobian(psi0, n0, p0, voltages)
    Cmat = _storage_matrix(device)
    t0 = _time_scale(device)
    J0c = J0.tocsr().astype(complex)

    port_names = list(device.bcs.keys())
    P = len(port_names)

    b_ports = []
    kinds = []
    node_sets = []
    gate_weights = []       # kappa*w per node, gate ports only (else None)
    S_ohmic = []            # real sensitivity row, ohmic ports only (else None)
    for name in port_names:
        bc = device.bcs[name]
        kk = (bc.k * Ny * Nx + bc.j * Nx + bc.i).astype(int)
        node_sets.append(kk)
        b = np.zeros(3 * N, dtype=complex)
        if isinstance(bc, DirichletBC):
            kinds.append("ohmic")
            b[3 * kk] = 1.0
            gate_weights.append(None)
            S_ohmic.append(_ohmic_current_sensitivity(device, psi0, n0, p0, voltages, kk))
        elif isinstance(bc, GateBC):
            kinds.append("gate")
            w = bc.kappa * device._gate_face_weight(bc)
            b[3 * kk] = -w
            gate_weights.append(w)
            S_ohmic.append(None)
        else:
            raise TypeError(f"y_parameters: unsupported BC type {type(bc).__name__} "
                             f"for port {name!r}")
        b_ports.append(b)

    Y = np.empty((len(freqs), P, P), dtype=complex)
    for kf, f in enumerate(freqs):
        omega_s = 2.0 * np.pi * f * t0
        J_ac = (J0c + 1j * omega_s * Cmat).tocsc()
        lu = splu(J_ac)
        du = [lu.solve(b_ports[k]) for k in range(P)]
        for k in range(P):
            for i in range(P):
                if kinds[i] == "ohmic":
                    Y[kf, i, k] = S_ohmic[i].astype(complex) @ du[k]
                else:
                    delta_ik = 1.0 if i == k else 0.0
                    kk_i = node_sets[i]
                    Y[kf, i, k] = (1j * omega_s
                                   * np.sum(gate_weights[i] * (delta_ik - du[k][3 * kk_i])))

    # Physical scaling: an AREA conversion (J0*LD**2), not 2D's LENGTH
    # conversion (J0*LD) -- see Device3D.terminal_current's own
    # docstring for the identical reasoning (3D meshes every physical
    # dimension, no remaining implicit unit-depth). Verified empirically
    # via this module's own gates (tests/test_m45_ac3d.py), not trusted
    # on this argument alone -- same discipline ac2d.py's own comment
    # here insists on.
    Y_phys = Y * device.J0 * device.LD ** 2 / device.VT
    return YParamResult3D(freqs, Y_phys, port_names)


def cutoff_frequency(yres, port_in, port_out):
    """Current-gain cutoff frequency f_T -- IDENTICAL method to
    ac2d.cutoff_frequency (see that docstring for the full derivation),
    only the two ports feeding h21 are a parameter."""
    def _idx(p):
        return yres.port_names.index(p) if isinstance(p, str) else int(p)
    i_in, i_out = _idx(port_in), _idx(port_out)

    freqs = yres.freqs
    Y_in = yres.Y[:, i_in, i_in]
    Y_out = yres.Y[:, i_out, i_in]
    with np.errstate(divide="ignore", invalid="ignore"):
        h21 = np.where(np.abs(Y_in) > 0, Y_out / Y_in, np.inf)
    mag = np.abs(h21)

    if not np.any(np.isfinite(mag)):
        return None
    if mag[0] < 1.0:
        return None
    if mag[-1] >= 1.0:
        return None

    below = np.where(mag < 1.0)[0]
    i1 = int(below[0])
    i0 = i1 - 1
    if i0 < 0:
        return None

    lf0, lf1 = np.log(freqs[i0]), np.log(freqs[i1])
    lm0, lm1 = np.log(mag[i0]), np.log(mag[i1])
    if lm0 == lm1:
        return float(freqs[i0])
    frac = (0.0 - lm0) / (lm1 - lm0)
    log_fT = lf0 + frac * (lf1 - lf0)
    return float(np.exp(log_fT))
