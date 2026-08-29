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

    Cell size follows the gradient-limited target

        s(x) = min(h_max, h_min + (ratio - 1) * dist(x, x_focus))

    so spacing is h_min at a focus point and grows linearly away from it,
    with adjacent cells never differing by more than `ratio` (keep <= ~1.2;
    larger grading ratios degrade the second-order accuracy of the box
    discretisation).

    Nodes are placed at equal increments of the arc length
    t(x) = integral dx / s(x), which honours s(x) everywhere WITHOUT
    truncating any step.  The previous implementation walked forward and
    clamped each step onto the next focus point and onto L; every clamp
    left a stub cell whose neighbour could be many times larger, and the
    worst jump of the whole mesh landed on the ohmic contact cell
    (measured up to 11.06x against a stated ratio of 1.15).

    All lengths in cm.
    """
    L = float(L)
    x_focus = np.clip(np.atleast_1d(np.asarray(x_focus, dtype=float)),
                      0.0, L)
    h_min = float(h_min)
    h_max = max(float(h_max), h_min)
    g = ratio - 1.0

    # Dense sampling must resolve h_min, or the arc-length integral
    # under-counts the refined region.
    m_uncapped = 50.0 * L / max(h_min, 1e-30)
    m = int(min(2_000_001, max(2001, m_uncapped) + 1))
    if m_uncapped > 2_000_000:
        # The dense sampling this arc-length construction relies on is
        # capped at 2,000,001 points; above this L/h_min ratio the grid
        # near a focus point is coarser than h_min itself, so the
        # trapezoidal arc-length integral under-counts the sharp peak in
        # 1/s(x) there and the realised minimum spacing silently ends up
        # a factor of ~2-2.4x above the requested h_min (measured).  Warn
        # rather than let the "spacing is h_min at a focus point"
        # guarantee documented above fail silently.
        import warnings
        warnings.warn(
            f"graded_mesh: L/h_min = {L / max(h_min, 1e-30):.3g} exceeds "
            "the dense-sampling cap; the realised minimum cell size near "
            "a focus point may be coarser than the requested h_min "
            f"({h_min:.3g} cm).")
    xs = np.linspace(0.0, L, m)
    d = np.min(np.abs(xs[:, None] - x_focus[None, :]), axis=1)
    s = np.minimum(h_max, h_min + g * d)

    inv = 1.0 / s
    t = np.concatenate(([0.0], np.cumsum(0.5 * (inv[1:] + inv[:-1])
                                         * np.diff(xs))))
    n_cells = max(1, int(np.ceil(t[-1])))
    t *= n_cells / t[-1]                 # land exactly on an integer
    nodes = np.interp(np.arange(n_cells + 1), t, xs)
    nodes[0], nodes[-1] = 0.0, L
    if n_cells < 3 or g <= 0.0:
        return nodes

    # Gradient-limit the realised cell sizes.  A cell spans a stretch over
    # which the target size is still growing, so the realised spacing
    # slightly exceeds s(x) and the realised ratio slightly exceeds
    # `ratio`.  Two sweeps clamp h[i+1] <= ratio*h[i] (and the mirror),
    # done in log space so each is a cumulative minimum; the clamp only
    # SHRINKS cells, and the uniform rescale that restores sum(h) = L
    # cancels in every ratio.  The fixed point therefore satisfies the
    # documented bound exactly while still spanning [0, L].
    h = np.diff(nodes)
    lr = np.log(ratio)
    k = np.arange(h.size)
    for _ in range(50):
        lh = np.log(h)
        lh = np.minimum.accumulate(lh - k * lr) + k * lr           # forward
        lh = np.minimum.accumulate((lh + k * lr)[::-1])[::-1] - k * lr  # back
        h = np.exp(lh)
        h *= L / h.sum()                 # scale-invariant for grading
        r = np.maximum(h[1:] / h[:-1], h[:-1] / h[1:]).max()
        if r <= ratio * (1.0 + 1e-12):
            break
    nodes = np.concatenate(([0.0], np.cumsum(h)))
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
