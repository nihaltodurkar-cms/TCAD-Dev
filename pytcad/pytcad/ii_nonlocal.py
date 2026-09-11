"""M34-S2: nonlocal (effective-field) impact ionization for Device1D.

The local M15 model evaluates the van Overstraeten-de Man coefficients
alpha(E) at the LOCAL field.  Carriers do not gain energy instantly:
over an energy relaxation length lambda they lag the field, so at a
narrow field peak they are colder -- and ionize less -- than the peak
field implies.  This module replaces the local field by a per-carrier
EFFECTIVE field obtained from the relaxation equation along the
carrier's drift direction s:

    lambda * dE_eff/ds + E_eff = |E|

Source and honest scope.  J.W. Slotboom, G. Streutker, M.J. van Dort,
P.H. Woerlee, A. Pruijmboom, D.J. Gravesteijn, "Non-local impact
ionization in silicon devices", IEDM Tech. Dig. 1991 (IEEE Xplore
document 235484).  Only the ABSTRACT was accessible (2026-09-11).  It
states that the simplified energy balance equation with the energy
relaxation length lambda_e as parameter gives the electron temperature
for a given field distribution, that lambda_e = 650 A was found from
MBE-grown bipolar transistors and scaled submicron MOS transistors, and
that electrons gain much less energy than the maximum field implies
when the field peak is narrow.  The equation above is the drift-
dominated relaxation form of that simplified energy balance: mapping
the carrier temperature back to a field through the uniform-field
relation cancels the energy-balance constant, so E_eff depends on
lambda alone and equals |E| exactly in a uniform field.  The paper's
own equations were NOT read; that mapping is stated here as this
module's construction, not as a quotation.

Named simplifications:
  * lambda_p = lambda_n: no hole value was accessible.  This is the same
    pattern hydrodynamic.py's TAU_W_P already uses.
  * Transport direction per edge.  On a STRONG edge (|E| >= E_STRONG_VCM
    = 100 V/cm) it is the drift direction from the field sign:
    electrons toward higher psi, holes toward lower.  A weaker edge
    inherits the direction of the nearest strong edge: hot carriers
    leaving a high-field region keep going the way they were going
    while their energy relaxes.  Why not the local sign everywhere:
    in a quasi-neutral region under reverse bias both the field and
    the majority current are round-off (measured |dpsi| ~ 1e-14 and
    Jn changing sign 8 times across the n+ edge of a junction), so
    their signs are noise and made E_eff flip between Newton iterates.
    No edge below 100 V/cm can ionize anyway (alpha = A exp(-B/E) with
    B >= 1.2e6 V/cm underflows to exactly 0 there).  With no strong
    edge at all, every node is cold.  Inflow boundaries are cold
    (E_eff = 0).  The direction pattern changes only when the set of
    strong edges does -- not in a reverse-biased junction.
  * A node with two inflowing edges (a sink) takes the mean of the two
    upstream values.

Discretization.  With the field piecewise constant per edge, the exact
solution of the relaxation equation across an edge of length h is
    E_eff(downstream) = a * E_eff(upstream) + (1 - a) * |E_edge|,
    a = exp(-h / lambda)
so the recursion is exact on any mesh.  E_eff is linear in the edge
field magnitudes for a fixed direction pattern, E_eff = W |E_edge|,
which gives the analytic Jacobian.
"""
import numpy as np

LAMBDA_E_SLOTBOOM_CM = 6.5e-6    # 650 A (Slotboom et al., IEDM 1991)
E_STRONG_VCM = 1.0e2             # edges below this never ionize; they
                                 # inherit a transport direction


def effective_field(x_cm, psi, VT, lam_cm, carrier, jacobian=False):
    """Per-node effective field [V/cm] of `carrier` ('n' or 'p').

    x_cm : node coordinates [cm];  psi : potential in units of VT;
    VT   : thermal voltage [V];    lam_cm : relaxation length [cm].

    Returns E_eff (N,), plus, if jacobian=True, the dense (N, N) matrix
    d(E_eff)/d(psi).  The direction pattern is piecewise constant, so it
    contributes nothing to the derivative.
    """
    x = np.asarray(x_cm, dtype=float)
    psi = np.asarray(psi, dtype=float)
    if carrier not in ("n", "p"):
        raise ValueError(f"carrier must be 'n' or 'p', got {carrier!r}")
    if not lam_cm > 0.0:
        raise ValueError(f"relaxation length must be > 0, got {lam_cm}")
    N = x.size
    h = np.diff(x)
    dpsi = np.diff(psi)
    Emag = np.abs(dpsi) * VT / h                      # V/cm per edge
    s = np.sign(dpsi) if carrier == "n" else -np.sign(dpsi)
    strong = Emag >= E_STRONG_VCM
    if not strong.any():
        s = np.zeros_like(s)                         # everything cold
    elif not strong.all():
        # weak edges inherit the nearest strong edge's direction (by
        # edge-midpoint distance; a tie goes to the left one)
        xm = 0.5 * (x[1:] + x[:-1])
        si = np.nonzero(strong)[0]
        j = np.clip(np.searchsorted(xm[si], xm), 1, si.size - 1) \
            if si.size > 1 else np.zeros(xm.size, dtype=int)
        if si.size > 1:
            left, right = si[j - 1], si[j]
            near = np.where(np.abs(xm - xm[left]) <= np.abs(xm[right] - xm),
                            left, right)
        else:
            near = np.full(xm.size, si[0])
        s = np.where(strong, s, s[near])
    fwd = s > 0.0             # edge k carries flow k -> k+1
    bwd = s < 0.0             # edge k carries flow k+1 -> k
    a = np.exp(-h / lam_cm)
    E = np.zeros(N)
    W = np.zeros((N, N - 1)) if jacobian else None
    # Topological order (Kahn): a 1D chain is acyclic for ANY direction
    # pattern, so every node is visited after all its upstream nodes.
    indeg = np.zeros(N, dtype=int)
    indeg[1:] += fwd
    indeg[:-1] += bwd
    stack = list(np.nonzero(indeg == 0)[0][::-1])
    order = []
    while stack:
        v = stack.pop()
        order.append(v)
        if v < N - 1 and fwd[v]:
            indeg[v + 1] -= 1
            if indeg[v + 1] == 0:
                stack.append(v + 1)
        if v > 0 and bwd[v - 1]:
            indeg[v - 1] -= 1
            if indeg[v - 1] == 0:
                stack.append(v - 1)
    for v in order:
        ins = []
        if v > 0 and fwd[v - 1]:
            ins.append((v - 1, v - 1))        # (edge, upstream node)
        if v < N - 1 and bwd[v]:
            ins.append((v, v + 1))
        if not ins:
            continue                          # cold: E_eff = 0
        w = 1.0 / len(ins)
        for e, u in ins:
            E[v] += w * (a[e] * E[u] + (1.0 - a[e]) * Emag[e])
            if jacobian:
                W[v] += w * a[e] * W[u]
                W[v, e] += w * (1.0 - a[e])
    if not jacobian:
        return E
    # d|E_e|/dpsi: sign(dpsi_e) * VT/h_e on psi_{e+1}, the negative on psi_e
    g = np.sign(dpsi) * VT / h
    D = np.zeros((N, N))
    D[:, 1:] += W * g
    D[:, :-1] -= W * g
    return E, D
