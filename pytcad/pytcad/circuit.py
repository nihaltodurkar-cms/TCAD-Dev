"""M27 -- mixed-mode device + circuit: a Modified Nodal Analysis (MNA)
SPICE-style circuit solver, with a genuine pytcad `Device1D` embeddable
as a nonlinear two-terminal circuit element alongside ordinary V/I
sources, resistors, capacitors, an exponential diode, and a level-1
(Shichman-Hodges square-law) MOSFET.

HONEST SCOPE STATEMENT
-----------------------
  * "conductance from the existing analytic Jacobian" (M27's own spec
    wording) is NOT literally what `DeviceStamp` does: extracting a
    true small-signal terminal conductance from Device1D's internal
    coupled psi/n/p Jacobian would need solving an adjoint/sensitivity
    system this pass does not build. Instead `DeviceStamp` uses a
    FINITE-DIFFERENCE conductance -- two full `Device1D.solve_bias`
    calls per Newton iteration (base point + a small perturbation) --
    which is the standard SPICE "companion model" technique applied to
    a black-box nonlinear I-V source, just not the literal
    "reuse the Jacobian" mechanism the spec sentence suggested. This is
    disclosed, not silently substituted.
  * `MOSFET1` is a genuine long-channel Shichman-Hodges square-law
    model (triode/saturation regions, first-order channel-length
    modulation), the standard "level-1" SPICE model -- but has NO body
    effect (source and body are always the same node, an explicit
    simplification) and no subthreshold conduction (hard cutoff at
    V_gs = V_t0, so an off-state MOSFET carries exactly zero current,
    not a physically realistic leakage floor).
  * `transient()` only implements backward-Euler (unconditionally
    stable, first-order accurate) -- no adaptive timestep, no local
    error control. A `DeviceStamp` element inside a transient circuit
    is solved as a fresh quasi-static DC operating point at every
    timestep (Device1D itself has no capacitive/transient terminal
    model coupled into this circuit layer) -- this is fine for a
    device whose own internal RC time constants are fast compared to
    the circuit timestep, and wrong (missing displacement current)
    otherwise; not attempted here.
  * No convergence-failure recovery beyond the fixed Newton step clamp
    (`max_dv`) -- a circuit that does not converge raises, it does not
    silently return a stale/wrong operating point.
"""
import numpy as np

GND = "0"

# Relative floor on the Newton step convergence test (see Circuit._newton).
_NEWTON_RTOL = 1.0e-12


class _MNA:
    """Node-name <-> unknown-index bookkeeping for Modified Nodal
    Analysis: one unknown per non-ground node voltage, plus one branch-
    current unknown per independent voltage source (the standard MNA
    augmentation, needed because an ideal voltage source has no fixed
    conductance to stamp directly)."""

    def __init__(self, node_names, vsrc_names):
        self.node_index = {name: i for i, name in enumerate(node_names)}
        self.n_nodes = len(self.node_index)
        self.vsrc_index = {name: self.n_nodes + i
                           for i, name in enumerate(vsrc_names)}
        self.size = self.n_nodes + len(vsrc_names)

    def idx(self, node):
        """Unknown-vector index for a node name, or None for ground."""
        if node is None or node == GND:
            return None
        return self.node_index[node]


def _stamp_dependent_current(G, z, out_p, out_n, terms, Ieq):
    """Stamp a branch current I = Ieq + sum(coeff * v_k for (k, coeff)
    in terms) flowing from node `out_p` to node `out_n` (either end may
    be None = ground) into the MNA matrix/RHS. This ONE helper covers
    every element in this module: a plain resistor is `terms=[(p, g),
    (n, -g)], Ieq=0`; a linearized (companion-model) nonlinear element
    at operating point v0 with local conductance g is the same `terms`
    with `Ieq = I(v0) - g*v0`; a voltage-controlled current source
    (the MOSFET's gm term) adds a THIRD control-node term with no
    matching entry in (out_p, out_n) at all."""
    for k, coeff in terms:
        if k is None:
            continue
        if out_p is not None:
            G[out_p, k] += coeff
        if out_n is not None:
            G[out_n, k] -= coeff
    if out_p is not None:
        z[out_p] -= Ieq
    if out_n is not None:
        z[out_n] += Ieq


class VSource:
    """Ideal independent voltage source, V = V(p) - V(n)."""

    def __init__(self, name, p, n, V):
        self.name, self.p, self.n, self.V = name, p, n, V

    def stamp(self, mna, x, G, z):
        k = mna.vsrc_index[self.name]
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        if ip is not None:
            G[ip, k] += 1.0
            G[k, ip] += 1.0
        if iN is not None:
            G[iN, k] -= 1.0
            G[k, iN] -= 1.0
        z[k] += self.V


class ISource:
    """Ideal independent current source: I amps is injected INTO node
    p and drawn OUT of node n (conventional "arrow points into +"
    current-source symbol)."""

    def __init__(self, name, p, n, I):
        self.name, self.p, self.n, self.I = name, p, n, I

    def stamp(self, mna, x, G, z):
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        if ip is not None:
            z[ip] += self.I
        if iN is not None:
            z[iN] -= self.I


class Resistor:
    def __init__(self, name, p, n, R):
        self.name, self.p, self.n, self.R = name, p, n, R

    def stamp(self, mna, x, G, z):
        g = 1.0 / self.R
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        _stamp_dependent_current(G, z, ip, iN, [(ip, g), (iN, -g)], 0.0)


class Capacitor:
    """Backward-Euler companion model: DC (no history set) is an open
    circuit; once `set_history(dt, v_prev)` is called (by `transient`),
    it behaves as a resistor R=dt/C in parallel with a Norton current
    source of value (C/dt)*v_prev -- the standard SPICE capacitor
    companion model."""

    def __init__(self, name, p, n, C):
        self.name, self.p, self.n, self.C = name, p, n, C
        self._dt = None
        self._v_prev = 0.0

    def set_history(self, dt, v_prev):
        self._dt, self._v_prev = dt, v_prev

    def clear_history(self):
        self._dt = None

    def stamp(self, mna, x, G, z):
        if self._dt is None:
            return
        g = self.C / self._dt
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        Ieq = -g * self._v_prev
        _stamp_dependent_current(G, z, ip, iN, [(ip, g), (iN, -g)], Ieq)


class Diode:
    """Shockley exponential diode, I = Is*(exp(V/(N*VT)) - 1)."""

    def __init__(self, name, p, n, Is=1e-14, N=1.0, VT=0.025852):
        self.name, self.p, self.n = name, p, n
        self.Is, self.N, self.VT = Is, N, VT

    def stamp(self, mna, x, G, z):
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        vp = x[ip] if ip is not None else 0.0
        vn = x[iN] if iN is not None else 0.0
        VTn = self.N * self.VT
        # clip the operating point used for linearization only -- keeps
        # exp() from overflowing during Newton transients without
        # biasing the converged answer (a converged v sits well inside
        # this range for any physically sane circuit).
        v = float(np.clip(vp - vn, -5.0, 1.5))
        ev = np.exp(v / VTn)
        I = self.Is * (ev - 1.0)
        g = max(self.Is / VTn * ev, 1e-15)
        Ieq = I - g * v
        _stamp_dependent_current(G, z, ip, iN, [(ip, g), (iN, -g)], Ieq)


class MOSFET1:
    """Level-1 (Shichman-Hodges) long-channel square-law MOSFET.
    `kind='n'` or `'p'`; source doubles as body (no body effect -- see
    module honesty clause). `kp` is the process transconductance
    parameter [A/V^2] and `W_L` the width/length ratio, so the
    effective beta = kp*W_L; `lam` is the channel-length-modulation
    coefficient [1/V]."""

    def __init__(self, name, d, g, s, kind="n", Vt0=0.7, kp=2.0e-4,
                W_L=1.0, lam=0.02):
        self.name, self.d, self.g, self.s = name, d, g, s
        if kind not in ("n", "p"):
            raise ValueError(f"kind must be 'n' or 'p', got {kind!r}")
        self.kind = kind
        self.Vt0, self.beta, self.lam = Vt0, kp * W_L, lam

    def stamp(self, mna, x, G, z):
        idn, ign, isn = mna.idx(self.d), mna.idx(self.g), mna.idx(self.s)
        vd = x[idn] if idn is not None else 0.0
        vg = x[ign] if ign is not None else 0.0
        vs = x[isn] if isn is not None else 0.0
        sgn = 1.0 if self.kind == "n" else -1.0
        vgs = sgn * (vg - vs)
        vds = sgn * (vd - vs)
        Vt, beta, lam = self.Vt0, self.beta, self.lam
        vov = vgs - Vt

        if vov <= 0.0:
            Id, gm, gds = 0.0, 0.0, 1e-12
        elif vds < vov:
            onepl = 1.0 + lam * vds
            Id = beta * (vov * vds - 0.5 * vds ** 2) * onepl
            gm = beta * vds * onepl
            gds = beta * (vov - vds) * onepl \
                + beta * (vov * vds - 0.5 * vds ** 2) * lam
        else:
            onepl = 1.0 + lam * vds
            Id = 0.5 * beta * vov ** 2 * onepl
            gm = beta * vov * onepl
            gds = 0.5 * beta * vov ** 2 * lam

        # Id/gm/gds above are in the "sgn" (NMOS-equivalent) frame,
        # where the drain current genuinely flows drain->source. For a
        # PMOS (sgn=-1) the physical current flows source->drain, so
        # negate once here to get the real d->s branch current and its
        # sensitivities in the ACTUAL (unflipped) node-voltage frame:
        # d(sgn*Id_frame)/d(vg) = sgn*gm*sgn = gm (sgn^2=1), etc. --
        # the sensitivities are frame-invariant, only Id itself flips.
        Id_real = sgn * Id
        # dId_real/dvg = gm ; dId_real/dvd = gds ; dId_real/dvs = -(gm+gds)
        Ieq = Id_real - gm * vg - gds * vd + (gm + gds) * vs
        _stamp_dependent_current(
            G, z, idn, isn,
            [(ign, gm), (idn, gds), (isn, -(gm + gds))], Ieq)


class DeviceStamp:
    """Embed a real pytcad `Device1D` as a nonlinear two-terminal
    circuit element: `p` maps to the device's contact 0 ("left"), `n`
    to contact 1 ("right") -- Device1D's own fixed 2-terminal
    convention. Each Newton iteration re-solves the device's FULL
    coupled Poisson/continuity system at the current (and a slightly
    perturbed) circuit node voltage to get a finite-difference
    terminal conductance -- see module honesty clause for why this is
    NOT literally "conductance from the existing analytic Jacobian"."""

    def __init__(self, name, p, n, device, area_cm2=1.0e-4, dv=1.0e-3,
                opts=None):
        self.name, self.p, self.n = name, p, n
        self.device = device
        self.area_cm2 = area_cm2
        self.dv = dv
        self.opts = opts
        self.last_current = 0.0

    def _terminal_current(self, vp, vn):
        self.device.solve_bias([vp, vn], self.opts)
        J, _spread = self.device.current_density()
        return J * self.area_cm2

    def stamp(self, mna, x, G, z):
        ip, iN = mna.idx(self.p), mna.idx(self.n)
        vp = x[ip] if ip is not None else 0.0
        vn = x[iN] if iN is not None else 0.0
        I0 = self._terminal_current(vp, vn)
        I1 = self._terminal_current(vp + self.dv, vn)
        g = (I1 - I0) / self.dv
        self.last_current = I0
        Ieq = I0 - g * (vp - vn)
        _stamp_dependent_current(G, z, ip, iN, [(ip, g), (iN, -g)], Ieq)


class Circuit:
    """A netlist: an unordered bag of elements, each a 2- or 3-terminal
    object exposing `.stamp(mna, x, G, z)` (and, for a `VSource`,
    `.name` used as its own branch-current unknown's key)."""

    def __init__(self):
        self.elements = []

    def add(self, element):
        self.elements.append(element)
        return element

    def _build_mna(self):
        nodes = set()
        vsrc_names = []
        for e in self.elements:
            for attr in ("p", "n", "d", "g", "s"):
                v = getattr(e, attr, None)
                if v is not None and v != GND:
                    nodes.add(v)
            if isinstance(e, VSource):
                vsrc_names.append(e.name)
        return _MNA(sorted(nodes), vsrc_names)

    def _newton(self, mna, x0, max_iter, tol, max_dv):
        x = x0.copy()
        converged = False
        for _ in range(max_iter):
            G = np.zeros((mna.size, mna.size))
            z = np.zeros(mna.size)
            for e in self.elements:
                e.stamp(mna, x, G, z)
            G += np.eye(mna.size) * 1.0e-12   # floating-node guard
            x_new = np.linalg.solve(G, z)
            step = np.clip(x_new - x, -max_dv, max_dv)
            x = x + step
            # tol is absolute, plus a relative floor: a large branch
            # current (a diode at 1.2 V draws ~1.4e7 A) has an ulp of
            # ~2e-9, above tol=1e-9, so its converged step cycles at
            # round-off (measured 6.5e-8, i.e. 4.6e-15 relative) and the
            # absolute test alone could never pass. _NEWTON_RTOL=1e-12
            # adds at most ~1e-11 for ordinary volt/mA circuits.
            if np.all(np.abs(step) <= tol + _NEWTON_RTOL * np.abs(x)):
                converged = True
                break
        if not converged:
            raise RuntimeError(
                f"circuit Newton solve did not converge in {max_iter} "
                "iterations.")
        return x

    def dc_operating_point(self, x0=None, max_iter=100, tol=1.0e-9,
                           max_dv=1.0):
        """Newton-Raphson MNA solve at DC (every Capacitor is an open
        circuit unless it still carries stale history from a previous
        `transient()` call -- always call `clear_history()` first if
        mixing the two)."""
        mna = self._build_mna()
        x0 = np.zeros(mna.size) if x0 is None else x0
        x = self._newton(mna, x0, max_iter, tol, max_dv)
        return x, mna

    def transient(self, t_stop, dt, initial_conditions=None, max_iter=100,
                 tol=1.0e-9, max_dv=1.0):
        """Backward-Euler time march from t=0 to t_stop in fixed steps
        of dt. Returns (times, x_history, mna): `x_history[k]` is the
        full MNA unknown vector at `times[k]`.

        initial_conditions: optional {node_name: V} overriding the
        t=0 state that would otherwise come from `dc_operating_point()`
        -- needed for a circuit whose true DC operating point is an
        UNSTABLE equilibrium it would otherwise sit at forever (e.g. a
        symmetric ring oscillator: every stage at the same voltage is
        itself a valid, but unstable, fixed point). Only the named
        nodes are overridden; every other node still starts from its
        converged DC value."""
        capacitors = [e for e in self.elements if isinstance(e, Capacitor)]
        for c in capacitors:
            c.clear_history()
        mna = self._build_mna()
        x = self._newton(mna, np.zeros(mna.size), max_iter, tol, max_dv)
        if initial_conditions:
            for name, V in initial_conditions.items():
                idx = mna.idx(name)
                if idx is not None:
                    x[idx] = V

        times = [0.0]
        history = [x.copy()]
        t = 0.0
        while t < t_stop - 1.0e-15:
            for c in capacitors:
                ip, iN = mna.idx(c.p), mna.idx(c.n)
                vp = x[ip] if ip is not None else 0.0
                vn = x[iN] if iN is not None else 0.0
                c.set_history(dt, vp - vn)
            x = self._newton(mna, x, max_iter, tol, max_dv)
            t += dt
            times.append(t)
            history.append(x.copy())
        for c in capacitors:
            c.clear_history()
        return np.array(times), np.array(history), mna

    @staticmethod
    def node_voltage(x, mna, name):
        idx = mna.idx(name)
        return 0.0 if idx is None else float(x[idx])
