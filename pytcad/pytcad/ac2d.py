"""M18 phase 2 -- small-signal AC (frequency-domain) N-port analysis for
Device2D.

Mirrors ac.py's shape (drives an existing device through its own
_residual_jacobian from the OUTSIDE; device2d.py is never touched) but
generalizes it to however many ports a Device2D actually has -- Device2D
routinely has more than the fixed two ohmic contacts Device1D always has
(a MOSFET has source/drain/body ohmic contacts PLUS a gate), so this
module lives separately from ac.py (same relationship transient2d.py has
to transient.py) rather than trying to grow ac.py's fixed 2-port
Device1D shape to fit.

Two port kinds exist in Device2D.bcs, and they enter the small-signal
problem differently:

  DirichletBC (ohmic contact): a pure Dirichlet row exactly like
  Device1D's contacts -- generalizes ac.py's one-port pattern directly.
  Driving forcing: unit AC voltage at every node the contact touches
  (b[3*m] = 1.0 for m in the contact's node set). Observed current:
  reuses terminal_current()'s own quantity (the box-integration
  continuity residual F_n+F_p, summed over the contact's nodes) via a
  finite-difference sensitivity -- Device2D.terminal_current()'s own
  docstring is the reason this generalizes to any contact shape with no
  edge-picking: F_n/F_p already sum over however many edges touch a
  node, contact or not.

  GateBC (Robin condition on psi only, oxide coupling): NOT a Dirichlet
  row, and unlike an ohmic contact, has NO particle current crossing it
  at all -- the entire gate current is displacement current through the
  oxide capacitor. Device2D's Poisson residual has no time derivative
  anywhere (only the n/p continuity rows do, which is exactly what
  Cmat/_storage_matrix already captures) -- the gate's contribution,
  `F[m] += kappa*w[m]*(Vg_s - Vfb_s - (psi_s[m]-psi_b[m]))`, is a pure
  D-field flux term (structurally identical to a bulk internal edge's
  et/h*dpsi flux -- see the Jacobian's own `-kappa*w` diagonal entry,
  already the correct STATIC sensitivity, no change needed there).
  Following the exact reasoning ac.py's own module docstring already
  uses for why the displacement-current piece at an ohmic contact is
  `-eps~[edge]/h[edge] * d(psi[k+1]-psi[k])/dt` (a flux term's time
  derivative IS the displacement current crossing that face), the gate's
  physical current is the time derivative of that SAME flux term:

      I_gate,i(w) = j*w_s * sum_{m in gate i's nodes} kappa*w[m] *
                    (delta_ik - du_k[3*m])

  where delta_ik is 1 only when gate i is the driven port (dVg_s=1
  there, 0 at every AC-grounded port) and du_k[3*m] is the psi-row
  response at m to driving port k. This is closed-form (no FD needed
  for the gate's own contribution) and is exactly standard multiport
  capacitor theory (a lossless capacitive port contributes +jwC to its
  own row, -jwC cross-coupled to the node it references) -- consistent
  with treating kappa*w as literally a capacitance-per-node coefficient,
  which `add_gate`'s own kappa = eps_ox*LD/(eps*tox_cm) construction
  already is.

  Driving forcing for a gate port: dF[m]/dVg_s = +kappa*w[m], so
  b[3*m] = -kappa*w[m] (same b = -dF/dVport convention ac.py's own
  ohmic forcing derivation uses).

Cmat itself (the n/p storage term) needs NO gate-row addition -- Poisson
has no time derivative in this codebase, full stop; the storage physics
lives entirely in the two continuity rows, at every node that is not an
S=0 ohmic-contact node (gate nodes keep full n/p storage: they are not
Dirichlet-overwritten, just Poisson-Robin-modified).

This is genuinely new territory for the codebase: transient2d.py's own
solve_transient() docstring explicitly notes time-varying GateBC voltage
is NOT supported yet (M17 phase 2 descoped it) -- no prior art here to
lean on, hence G-GATE-FD (tests/test_m18_ac2d.py) cross-checks the
closed-form gate forcing/sensitivity above against a direct finite
difference of two independent static solve_bias({"gate": ...}) calls
before anything else in this module is trusted.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu


def _time_scale(device):
    """Identical definition to ac.py/transient.py/transient2d.py's own
    _time_scale -- kept as a local one-liner so this module has no
    dependency on any of their internals."""
    return device.Ns / device.R0


def _dirichlet_excluded_nodes(device):
    """Flat node indices whose n/p continuity rows are OVERWRITTEN to a
    pure Dirichlet identity (S_n=S_p=0, the default) -- these must be
    excluded from Cmat's storage rows, exactly like ac.py's 1D
    `_storage_matrix` excludes both boundary nodes via `dV[1:-1]`.  When
    S_n/S_p != 0 the row stays a genuine (flux-BC) continuity row and
    keeps its storage term -- Device2D's own S_n/S_p are device-wide
    (Models fields, not per-contact), so this check is device-wide too.
    """
    from .device2d import DirichletBC
    Nx = device.Nx
    excl_n, excl_p = [], []
    for bc in device.bcs.values():
        if isinstance(bc, DirichletBC):
            kk = (bc.j * Nx + bc.i).astype(int)
            if device.models.S_n == 0.0:
                excl_n.append(kk)
            if device.models.S_p == 0.0:
                excl_p.append(kk)
    excl_n = np.unique(np.concatenate(excl_n)) if excl_n else np.array([], dtype=int)
    excl_p = np.unique(np.concatenate(excl_p)) if excl_p else np.array([], dtype=int)
    return excl_n, excl_p


def _storage_matrix(device):
    """The coefficient of j*w_s in J_ac(w): Device2D's box-integration
    n/p storage term (identical structure to Device1D's, dV -> dV.ravel()
    per node), zeroed at nodes whose row is Dirichlet-overwritten (see
    _dirichlet_excluded_nodes)."""
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


def _support_nodes(kk, Nx, Ny):
    """kk's own nodes plus every 4-connected (grid) neighbor -- the full
    set of nodes Device2D's box-integration F_n/F_p at kk can possibly
    depend on (a node's continuity residual only ever touches itself and
    its up/down/left/right neighbors)."""
    kk = np.asarray(kk, dtype=int)
    j, i = kk // Nx, kk % Nx
    parts = [kk]
    left = np.where(i > 0, kk - 1, -1)
    right = np.where(i < Nx - 1, kk + 1, -1)
    up = np.where(j > 0, kk - Nx, -1)
    down = np.where(j < Ny - 1, kk + Nx, -1)
    for arr in (left, right, up, down):
        parts.append(arr[arr >= 0])
    return np.unique(np.concatenate(parts))


def _ohmic_current_sensitivity(device, psi, n, p, voltages, kk):
    """Real sensitivity row S (length 3N) of the DC current INTO the
    device through an ohmic contact's node set `kk` (sum of F_n+F_p over
    those nodes -- terminal_current()'s own quantity) with respect to
    the full state vector, via a shared-step-size central finite
    difference over kk's support (see _support_nodes).

    ONE step size per state component, shared across every node in the
    support set (not computed per-node) -- generalizing the exact fix
    ac.py's own _edge_current_sensitivity needed (a per-node step size
    breaks the exact cancellation a rigid, multi-node state shift must
    produce, at a magnitude comparable to the genuine signal)."""
    Nx, Ny, N = device.Nx, device.Ny, device.N
    support = _support_nodes(kk, Nx, Ny)
    S = np.zeros(3 * N)

    def contact_I(psi_, n_, p_):
        *_, F_n, F_p = device._residual_jacobian(psi_, n_, p_, voltages)
        return float((F_n.ravel()[kk] + F_p.ravel()[kk]).sum())

    psi_f, n_f, p_f = psi.ravel().copy(), n.ravel().copy(), p.ravel().copy()
    bases = {0: psi_f, 1: n_f, 2: p_f}
    for comp, base in bases.items():
        scale = max(float(np.abs(base[support]).max()), 1.0)
        h = scale * 1e-6
        for node in support:
            arrs_p = [psi_f.copy(), n_f.copy(), p_f.copy()]
            arrs_m = [psi_f.copy(), n_f.copy(), p_f.copy()]
            arrs_p[comp][node] += h
            arrs_m[comp][node] -= h
            Ip = contact_I(arrs_p[0].reshape(Ny, Nx), arrs_p[1].reshape(Ny, Nx),
                            arrs_p[2].reshape(Ny, Nx))
            Im = contact_I(arrs_m[0].reshape(Ny, Nx), arrs_m[1].reshape(Ny, Nx),
                            arrs_m[2].reshape(Ny, Nx))
            S[3 * node + comp] = (Ip - Im) / (2 * h)
    return S


class YParamResult2D:
    """freqs [Hz]; Y complex N-port admittance matrix, shape
    (len(freqs), P, P) [A/V, i.e. S -- Device2D has no implicit
    unit-area convention the way Device1D does (a 2D device has a real
    finite lateral extent already baked into dVy/dVx), so Y here is a
    true per-device-width admittance, physical units already applied].
    port_names: tuple of device.bcs keys, in dict insertion order --
    the same order Y's port axes use."""

    def __init__(self, freqs, Y, port_names):
        self.freqs = np.asarray(freqs, dtype=float)
        self.Y = np.asarray(Y, dtype=complex)
        P = len(port_names)
        if self.Y.shape != (self.freqs.size, P, P):
            raise ValueError(
                f"Y must have shape (len(freqs), {P}, {P}); got {self.Y.shape}")
        self.port_names = tuple(port_names)


def y_parameters(device, freqs):
    """Full N-port complex Y-parameter matrix Y(f) of a Device2D at its
    CURRENT converged DC operating point (call solve_equilibrium()/
    solve_bias() first). Every entry of device.bcs (both DirichletBC
    ohmic contacts and GateBC gates) becomes one port, in dict insertion
    order (device.bcs is populated by add_contact/add_gate calls, so
    port order is exactly call order).

    Y[k,i,j] = dI_i/dV_j at freqs[k], all OTHER ports AC-grounded (held
    at their DC value/bias with zero AC perturbation) -- standard
    multiport short-circuit admittance definition, I_i positive flowing
    INTO terminal i. See this module's docstring for the two ports
    kinds' different forcing/observation formulas.

    Raises TypeError for anything but a Device2D (1D/3D AC analysis
    lives in ac.py / is out of scope -- see M18-AC-PLAN.md).
    """
    from .device2d import Device2D, DirichletBC, GateBC
    if not isinstance(device, Device2D):
        raise TypeError(
            "ac2d.y_parameters only supports Device2D; got "
            f"{type(device).__name__}. 1D AC analysis lives in ac.py; "
            "3D AC analysis is out of scope -- see M18-AC-PLAN.md.")
    if device.psi is None:
        raise RuntimeError(
            "y_parameters needs a converged DC operating point: call "
            "solve_equilibrium() or solve_bias() first")

    Nx, N = device.Nx, device.N
    psi0, n0, p0 = device.psi, device.n, device.p
    voltages = {name: bc.V for name, bc in device.bcs.items()
                if isinstance(bc, DirichletBC)}

    _, J0, *_ = device._residual_jacobian(psi0, n0, p0, voltages)
    Cmat = _storage_matrix(device)
    t0 = _time_scale(device)
    J0c = J0.tocsr().astype(complex)

    port_names = list(device.bcs.keys())
    P = len(port_names)

    # Per-port static data: node set, kind, forcing vector, and (ohmic
    # only) the real current-sensitivity row -- all frequency-independent,
    # built once.
    b_ports = []
    kinds = []
    node_sets = []
    gate_weights = []       # kappa*w per node, gate ports only (else None)
    S_ohmic = []            # real sensitivity row, ohmic ports only (else None)
    for name in port_names:
        bc = device.bcs[name]
        kk = (bc.j * Nx + bc.i).astype(int)
        node_sets.append(kk)
        b = np.zeros(3 * N, dtype=complex)
        if isinstance(bc, DirichletBC):
            kinds.append("ohmic")
            b[3 * kk] = 1.0
            gate_weights.append(None)
            S_ohmic.append(_ohmic_current_sensitivity(device, psi0, n0, p0, voltages, kk))
        elif isinstance(bc, GateBC):
            kinds.append("gate")
            w = bc.kappa * device.dVx[bc.i]
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

    # Physical scaling: every row of J0/Cmat (psi, n, and p alike) is
    # assembled by device2d.py into the SAME residual vector F with no
    # per-row rescaling (F[:,0]/[:,1]/[:,2] = F_psi/F_n/F_p, stacked
    # directly), so the same J0*LD conversion terminal_current() applies
    # to F_n+F_p (residual -> physical current [A/cm]) applies uniformly
    # to any row of this system -- ohmic AND gate ports alike -- and the
    # forcing convention (a unit SCALED port-voltage perturbation,
    # d(psi_s)=1, corresponds to a physical d(V)=VT) needs the matching
    # /VT to turn "per scaled-volt" into "per physical volt". Verified
    # empirically, not just by construction, via G-GATE-FD/G-MOSCAP-CV
    # (tests/test_m18_ac2d.py) rather than trusted on this argument alone.
    Y_phys = Y * device.J0 * device.LD / device.VT
    return YParamResult2D(freqs, Y_phys, port_names)


def cutoff_frequency(yres, port_in, port_out):
    """Current-gain cutoff frequency f_T: the frequency at which the
    short-circuit current gain h21(f) = Y[port_out, port_in](f) /
    Y[port_in, port_in](f) has |h21| = 1 -- the standard small-signal
    RF figure of merit (Sedra/Smith's or Sze's f_T definition),
    generalized from ac.py's `cutoff_frequency()` (which hardcodes the
    fixed 2-port (0, 1) Device1D case) to an N-port Y matrix with
    named/indexed ports -- e.g. `cutoff_frequency(yres, "gate",
    "drain")` for a MOSFET's standard current-gain fT.

    port_in/port_out: either a name looked up in `yres.port_names`, or
    an integer port index directly.

    Method: IDENTICAL log-log bisection logic to ac.cutoff_frequency
    (see that docstring for the full derivation, monotonicity
    assumption, and the flat/no-crossing/None caveats) -- only the two
    ports feeding h21 are now a parameter instead of hardcoded. This
    module previously had no fT support at all (Device1D's 2-terminal
    devices have no genuine current gain to speak of -- see
    ac.cutoff_frequency's own docstring -- so fT was never physically
    meaningful until a real 3+-terminal active device (a MOSFET) has a
    fixture: see tests/test_m18_ac2d.py's G-MOSFET-FT/G-MOSFET-GAIN,
    the first real (non-synthetic) validation of this crossing logic
    against actual device physics, not just a hand-built profile.

    Returns f_T [Hz], or None if |h21| never crosses 1 within the
    swept range (same two cases as ac.cutoff_frequency: starts below 1,
    or stays above 1 throughout -- reported as None rather than
    extrapolating past validated data)."""
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
        return None  # no useful gain even at the lowest swept frequency
    if mag[-1] >= 1.0:
        return None  # fT lies beyond the swept range

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
