"""1D non-uniform mesh construction.

Meshing is where most drift-diffusion simulations actually fail.  The rule of
thumb: the spacing must resolve the Debye length

    L_D = sqrt(eps kT / (q^2 N))

in every region, and must be far finer than that across a junction, where the
potential changes by ~V_bi over a distance of order L_D.  A uniform mesh that
looks "fine" (1 nm) in the depletion region is wastefully fine in the neutral
bulk, and a uniform 10 nm mesh silently produces a wrong built-in field.
"""

import numpy as np

from .constants import Q, EPS0, KB


def debye_length(N, eps_r=11.7, T=300.0):
    """Extrinsic Debye length [cm] for doping N [cm^-3]."""
    N = np.maximum(np.asarray(N, dtype=float), 1.0)
    return np.sqrt(eps_r * EPS0 * KB * T / (Q**2 * N))


def uniform_mesh(L, n):
    """n+1 nodes uniformly spanning [0, L] cm."""
    return np.linspace(0.0, L, n + 1)


def graded_mesh(L, x_focus, h_min, h_max, ratio=1.15):
    """Mesh on [0, L] refined around the positions in x_focus.

    Grows geometrically from h_min at each focus point up to h_max, with
    successive spacings limited by `ratio` (keep <= ~1.2; larger grading
    ratios degrade the second-order accuracy of the box discretisation).

    All lengths in cm.
    """
    x_focus = np.atleast_1d(np.asarray(x_focus, dtype=float))
    pts = {0.0, float(L)}
    for xf in x_focus:
        pts.add(float(np.clip(xf, 0.0, L)))

    # Gradient-limited spacing: the allowed cell size grows linearly with
    # distance from the nearest focus point, with slope (ratio - 1).  This
    # guarantees adjacent cells never differ by more than `ratio`.
    g = ratio - 1.0
    nodes = [0.0]
    x = 0.0
    while x < L - 1e-14:
        d = np.min(np.abs(x - x_focus))
        h = min(h_max, h_min + g * d)
        # do not step over a focus point
        ahead = x_focus[x_focus > x + 1e-14]
        if ahead.size:
            h = min(h, max(ahead.min() - x, h_min))
        x = min(x + h, L)
        nodes.append(x)
    nodes = np.array(nodes)
    nodes[-1] = L
    return nodes


def merge_mesh(*arrays, tol=1e-10):
    """Union of node sets, sorted, with near-duplicates removed."""
    x = np.sort(np.concatenate([np.atleast_1d(a) for a in arrays]))
    keep = np.concatenate([[True], np.diff(x) > tol])
    return x[keep]


def check_mesh(x, doping, eps_r=11.7, T=300.0, verbose=True):
    """Report the worst spacing-to-Debye-length ratio.  Aim for < ~1."""
    LD = debye_length(np.abs(doping), eps_r, T)
    h = np.diff(x)
    ratio = h / np.minimum(LD[:-1], LD[1:])
    if verbose:
        print(f"  nodes = {len(x)}, max h/L_D = {ratio.max():.2f} "
              f"at x = {x[np.argmax(ratio)]*1e4:.4f} um")
    return ratio
