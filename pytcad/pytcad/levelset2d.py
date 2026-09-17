"""M35-S1: multi-material level-set process-geometry representation.

Replaces (additively -- see process2d.py's `level_set` field) the
single-valued height-field representation with a signed-distance level
set phi<0-inside, one field per MATERIAL on a fixed **uniform**
background grid. Geometry queries ("which material is at this point",
"where is the interface") become sign tests and zero-crossing
interpolation rather than column bookkeeping.

See pytcad/M35-3D-PROCESS-PLAN.md section 2 for the design rationale.
This module does not touch process2d.py's existing deposit/etch/
oxidize_2d/implant_2d arithmetic at all (S1-G1); wiring those onto the
level set is S2's job.

The background grid is deliberately its OWN uniform grid, independent
of `mesh2d.Mesh2D` (which is a graded tensor-product mesh -- the
standard level-set machinery, upwind Hamilton-Jacobi advection and
signed-distance reinitialization, assumes uniform spacing and loses its
order on a graded grid). The process level set resolves the *front*;
the device mesh resolves the *solution*; conflating them is out of
scope (section 2.4).

HONESTY CLAUSE
--------------
* Level sets do NOT conserve mass exactly, unlike process2d.deposit's
  exact thickness*width bookkeeping. See test_m35_s1_levelset.py's
  S1-G5 for the measured error at a stated resolution.
* The material set is finite and declared (below); anything else
  raises ValueError.
* Multi-material bookkeeping uses the Voronoi-assignment + projection
  rule (argmin phi -> owner, then re-derive each owner's phi as a true
  signed distance via `scipy.ndimage.distance_transform_edt`). This
  guarantees no point is claimed by two materials and no point is
  claimed by none, by construction of the argmin step.
"""

from dataclasses import dataclass, field
import numpy as np
from scipy.ndimage import distance_transform_edt, binary_dilation

MATERIAL_NAMES = (
    "silicon", "sio2", "si3n4", "poly", "resist", "metal", "silicide",
    "ambient",
)


def _check_materials(materials):
    materials = tuple(materials)
    unknown = [m for m in materials if m not in MATERIAL_NAMES]
    if unknown:
        raise ValueError(
            f"unknown material(s) {unknown}: declared set is {MATERIAL_NAMES}"
        )
    if len(set(materials)) != len(materials):
        raise ValueError(f"duplicate materials in {materials}")
    return materials


# ----------------------------------------------------------------------
#  Grid + multi-material state
# ----------------------------------------------------------------------
@dataclass
class LevelSet2D:
    """A signed-distance level set per material on a uniform background
    grid. `phi[name] < 0` means "inside material `name`".

    x0, x1, Nx : lateral extent [cm] and node count
    y0, y1, Ny : depth extent [cm] and node count (y increases downward,
                 matching process2d's convention)
    materials  : tuple of material names present in this level set,
                 ordered by priority (used only to break exact phi ties
                 in `material_map`)
    phi        : dict name -> (Ny, Nx) array; if not supplied, every
                 material initializes to "everywhere outside" (phi = +inf
                 is impractical, so phi = a large positive constant
                 proportional to the grid diagonal)
    """
    x0: float
    x1: float
    Nx: int
    y0: float
    y1: float
    Ny: int
    materials: tuple = MATERIAL_NAMES
    phi: dict = None

    def __post_init__(self):
        self.materials = _check_materials(self.materials)
        self.x = np.linspace(self.x0, self.x1, self.Nx)
        self.y = np.linspace(self.y0, self.y1, self.Ny)
        self.dx = (self.x1 - self.x0) / (self.Nx - 1)
        self.dy = (self.y1 - self.y0) / (self.Ny - 1)
        self.X, self.Y = np.meshgrid(self.x, self.y)   # each (Ny, Nx)
        if self.phi is None:
            far = 10.0 * np.hypot(self.x1 - self.x0, self.y1 - self.y0)
            self.phi = {m: np.full((self.Ny, self.Nx), far) for m in self.materials}
        else:
            self.phi = {m: np.asarray(v, dtype=float).copy()
                        for m, v in self.phi.items()}

    def copy(self):
        out = LevelSet2D(self.x0, self.x1, self.Nx, self.y0, self.y1, self.Ny,
                          materials=self.materials,
                          phi={k: v.copy() for k, v in self.phi.items()})
        return out

    def material_map(self):
        """(Ny, Nx) int array: index into `self.materials` of the owner
        at each grid point (argmin phi, ties broken by materials order)."""
        stack = np.stack([self.phi[m] for m in self.materials], axis=0)
        return np.argmin(stack, axis=0)


# ----------------------------------------------------------------------
#  Advection: dphi/dt + V|grad phi| = 0  (Osher-Sethian upwind Godunov)
# ----------------------------------------------------------------------
def _grad_upwind_components(phi, dx, dy):
    """One-sided forward/backward differences along x and y."""
    Dxm = np.empty_like(phi); Dxp = np.empty_like(phi)
    Dym = np.empty_like(phi); Dyp = np.empty_like(phi)

    Dxm[:, 1:] = (phi[:, 1:] - phi[:, :-1]) / dx
    Dxm[:, 0] = Dxm[:, 1]
    Dxp[:, :-1] = (phi[:, 1:] - phi[:, :-1]) / dx
    Dxp[:, -1] = Dxp[:, -2]

    Dym[1:, :] = (phi[1:, :] - phi[:-1, :]) / dy
    Dym[0, :] = Dym[1, :]
    Dyp[:-1, :] = (phi[1:, :] - phi[:-1, :]) / dy
    Dyp[-1, :] = Dyp[-2, :]

    return Dxm, Dxp, Dym, Dyp


def _godunov_grad_mag(phi, dx, dy, V):
    """|grad phi| via the Osher-Sethian entropy-satisfying Godunov
    scheme, evaluated with the sign convention appropriate to the local
    (scalar or array) normal speed V."""
    Dxm, Dxp, Dym, Dyp = _grad_upwind_components(phi, dx, dy)
    Vpos = V > 0
    Vneg = ~Vpos

    def pp(a): return np.maximum(a, 0.0)
    def nn(a): return np.minimum(a, 0.0)

    grad_pos = np.sqrt(
        np.maximum(pp(Dxm) ** 2, nn(Dxp) ** 2)
        + np.maximum(pp(Dym) ** 2, nn(Dyp) ** 2)
    )
    grad_neg = np.sqrt(
        np.maximum(nn(Dxm) ** 2, pp(Dxp) ** 2)
        + np.maximum(nn(Dym) ** 2, pp(Dyp) ** 2)
    )
    return np.where(Vpos, grad_pos, np.where(Vneg, grad_neg, 0.0))


def advect_upwind(phi, V, dx, dy, dt):
    """One explicit-Euler step of dphi/dt + V|grad phi| = 0.

    V may be a scalar or an (Ny, Nx) array of per-point normal speeds
    (positive V grows the "inside" region, matching phi<0-inside)."""
    V = np.asarray(V, dtype=float)
    grad_mag = _godunov_grad_mag(phi, dx, dy, V if V.ndim else np.full_like(phi, V))
    return phi - dt * V * grad_mag


def cfl_dt(V, dx, dy, cfl=0.5):
    """A stable explicit time step for the upwind advection scheme."""
    Vmax = float(np.max(np.abs(V)))
    if Vmax == 0.0:
        return np.inf
    return cfl * min(dx, dy) / Vmax


# ----------------------------------------------------------------------
#  Multi-material projection (Voronoi assignment + signed-distance
#  re-derivation) -- section 2.2 decision 1.
# ----------------------------------------------------------------------
def project(ls):
    """Resolve multi-material drift: assign every grid point to exactly
    one material (argmin phi, i.e. the most-negative/"most inside"
    claim), then re-derive each material's phi as the true signed
    distance to its own assigned region.

    Serves both roles the plan asks of one function: called on an
    unchanged material map, this is reinitialization (S1-G3); called
    after independent advection has let two materials' raw phi overlap
    or gap, this is the multi-material fix (S1-G4).
    """
    return _project_from_owner(ls, ls.material_map())


def _far_value(ls):
    """The "everywhere outside" convention LevelSet2D.__post_init__
    uses: a large positive constant proportional to the grid diagonal
    (phi=+inf is impractical). Shared with `_project_from_owner` so a
    material that owns nothing gets a genuinely LARGE phi, not scipy's
    degenerate `distance_transform_edt` of an all-True/all-False array
    (which measures distance to the array's own edge, not "far" --
    confirmed directly: it returns small values near a corner, which
    broke advance_front's seeding step during development)."""
    return 10.0 * np.hypot(ls.x1 - ls.x0, ls.y1 - ls.y0)


def _project_from_owner(ls, mat_idx):
    """Re-derive every material's phi as a true signed distance to the
    region `mat_idx` assigns it, via `scipy.ndimage.distance_transform_edt`.
    Split out of `project` so `advance_material` can supply an ownership
    map it trusts more than a blind argmin over a stale phi (see its
    docstring).

    The degenerate cases (a material owning ALL or NONE of the grid)
    are handled explicitly rather than by calling
    `distance_transform_edt` on an all-True/all-False mask: scipy's EDT
    with no background pixels to measure against computes distance to
    the array's OWN EDGE (increasing from a corner), which is not a
    "far" or "deep interior" distance at all and silently produced tiny,
    wrong phi values near a corner (see `_far_value`'s docstring)."""
    far = _far_value(ls)
    out = ls.copy()
    for i, name in enumerate(ls.materials):
        inside = (mat_idx == i)
        if np.all(inside):
            out.phi[name] = np.full(inside.shape, -far)
        elif not np.any(inside):
            out.phi[name] = np.full(inside.shape, far)
        else:
            d_in = distance_transform_edt(inside, sampling=(ls.dy, ls.dx))
            d_out = distance_transform_edt(~inside, sampling=(ls.dy, ls.dx))
            out.phi[name] = np.where(inside, -d_in, d_out)
    return out


# ----------------------------------------------------------------------
#  Advance one material's front under a normal speed for a total time
# ----------------------------------------------------------------------
def advance_material(ls, material, V, t_total, cfl=0.5):
    """Advect `material`'s phi at normal speed `V` (scalar or (Ny,Nx))
    for `t_total`, CFL-limited internally into many explicit-Euler
    substeps, and project (multi-material fix + reinitialize to a
    signed distance) exactly ONCE at the end. Returns a new LevelSet2D.

    Reinitializing between every internal substep (rather than once per
    process step) was tried and is wrong: `project`'s boolean-mask +
    EDT reinit is quantized to grid-cell membership, so if a substep
    moves the front by less than one cell (the CFL-limited normal case),
    a per-substep reinit reconstructs the IDENTICAL cell ownership and
    silently discards that substep's progress -- the front never moves.
    The plan's own wording ("reinitialize phi to a signed distance
    BETWEEN steps") means between process steps, which is what this
    does: the PDE is left to evolve `material`'s own phi continuously
    across all substeps of one call, and the grid-resolution snap
    happens once, at the end.

    Ownership at that final snap is NOT a blind argmin over every
    material's raw phi: only `material`'s own phi was just advected by
    the PDE, so every OTHER material's phi is stale (it still describes
    the geometry from before this call) and comparing a fresh phi
    against a stale one is meaningless -- a stale field can spuriously
    "win" the comparison at points the active material legitimately
    just claimed, silently reverting the very motion this function
    computed (confirmed directly: this was the actual bug during
    development, not a hypothetical). So ownership is instead: wherever
    the freshly-advected `material` phi is negative, `material` owns
    the point; everywhere else, ownership carries over unchanged from
    `ls`'s OWN (already self-consistent, pre-advection) material map.

    HONEST S1 LIMIT: this rule only handles a GROWING active material
    (deposit-style, V >= 0 everywhere it matters). If `material` recedes
    from a point it owned before (etch-style, V < 0) with no other
    material's phi advected to claim it, there is no principled owner to
    hand that point to from S1's information alone -- this raises
    NotImplementedError naming S2, which is exactly where deposit/etch
    become real topology operations with their own ownership rules
    (section 3 of the plan).
    """
    if material not in ls.materials:
        raise ValueError(f"{material!r} not in this level set's materials {ls.materials}")
    idx_active = ls.materials.index(material)
    prev_owner = ls.material_map()
    cur = ls.copy()
    Varr = np.asarray(V, dtype=float)
    t = 0.0
    while t < t_total - 1e-15:
        dt = cfl_dt(Varr, ls.dx, ls.dy, cfl)
        dt = min(dt, t_total - t)
        cur.phi[material] = advect_upwind(cur.phi[material], Varr, ls.dx, ls.dy, dt)
        t += dt

    active_inside = cur.phi[material] < 0
    if np.any((prev_owner == idx_active) & ~active_inside):
        raise NotImplementedError(
            f"{material!r} receded from a point it owned with no other "
            f"material advected to claim it -- real deposit/etch topology "
            f"with a defined ownership handoff is S2 scope, not S1"
        )
    new_owner = np.where(active_inside, idx_active, prev_owner)
    return _project_from_owner(cur, new_owner)


# ----------------------------------------------------------------------
#  M35-S2: deposit/etch as real topology -- a shared moving front
#  between exactly two materials (one recedes, one grows into it).
# ----------------------------------------------------------------------
def advance_front(ls, receding, growing, V, t_total, cfl=0.5, reinit=True):
    """Advance the shared interface between `receding` (which loses
    territory) and `growing` (which gains it): `V` (scalar or (Ny,Nx),
    a non-negative magnitude) is `receding`'s own RECESSION speed.

    This is the general two-material case `advance_material` (S1)
    explicitly declined to handle (a receding material with no declared
    successor raised NotImplementedError there). Deposit is `receding=
    "ambient"`; etch is `growing="ambient"`.

    The key design point, found by getting it wrong first: `growing`
    has no valid signed-distance function of its own to advect (it may
    not exist anywhere yet). `receding` DOES -- `ls` is assumed
    self-consistent (already projected), so `receding`'s own phi is
    already a true signed distance to its own real shape. So this
    erodes `receding`'s OWN phi (advect_upwind with speed `-V`, which
    shrinks its "inside" region, per the "+V grows inside" convention
    used everywhere else in this module), and hands whatever `receding`
    gives up to `growing`.

    The first implementation instead seeded `growing`'s phi from
    `receding`'s and grew `growing` with `+V` -- this is backwards: it
    expands the borrowed shape OUTWARD from `receding`'s current
    boundary, i.e. into whatever is on the far side of that boundary
    (typically a THIRD material, not deeper into `receding`), the exact
    opposite of what deposit/etch need. Confirmed directly: a
    conformal-deposit test with a silicon/ambient/sio2 stack had sio2
    growing straight into silicon at the trench sidewalls. Eroding
    `receding`'s own valid phi instead cannot overrun a third material
    even in principle: erosion is bounded by `receding`'s own real
    extent, so a narrow feature (a thin ambient trench, say) simply
    saturates -- fully consumed -- rather than overflowing into
    whatever is beyond it. That is also what makes trench pinch-off
    "just happen": once erosion consumes all of a pocket of `receding`,
    every point in it transfers to `growing` in the same step.
    """
    if receding not in ls.materials:
        raise ValueError(f"{receding!r} not in this level set's materials {ls.materials}")
    if growing not in ls.materials:
        raise ValueError(f"{growing!r} not in this level set's materials {ls.materials}")
    if receding == growing:
        raise ValueError("receding and growing must be different materials")

    idx_recede = ls.materials.index(receding)
    idx_grow = ls.materials.index(growing)
    prev_owner = ls.material_map()

    # A non-"ambient" `receding` material may border a THIRD material as
    # well as `growing` (e.g. silicon under an SiO2 cap, with ambient
    # only on the open side) -- a first version eroded receding's WHOLE
    # boundary uniformly and broke straight through the cap into
    # silicon it should have protected (confirmed directly: an
    # etch-under-a-hard-mask test showed silicon retreating at the SAME
    # rate under the cap as in the open area). Fix: restrict erosion to
    # wherever `receding` is DIRECTLY, LOCALLY adjacent (one grid cell)
    # to `growing`'s current region.
    #
    # This is adjacency, not "nearest by distance" -- a second version
    # used a nearest-neighbor-index distance transform (whichever OTHER
    # material has the closest single point, anywhere), which is the
    # wrong concept here and cannot produce undercut EVEN IN PRINCIPLE:
    # a point right under a continuous cap is always essentially
    # touching the cap material (distance ~0, directly above it), while
    # `growing` (ambient) can only be reached by a longer path AROUND
    # the newly-exposed sidewall corner -- straight-line distance will
    # therefore favor the cap forever, no matter how deep the open area
    # etches (confirmed directly: zero undercut at any depth with that
    # approach). Direct grid adjacency has no such bias: once erosion
    # exposes a new sidewall cell next to ambient, the cell immediately
    # under the cap beside it becomes locally adjacent to ambient too,
    # regardless of the cap's overall proximity.
    #
    # And this must be recomputed EVERY substep, not once up front: a
    # first fix computed it once from the t=0 geometry and held it
    # fixed -- undercut is exactly the case where a NEW patch of
    # `receding` becomes exposed only as the front evolves, so freezing
    # exposure at t=0 can never discover it either.
    #
    # The per-substep ownership estimate does NOT compare the evolving
    # `phi_recede` against the OTHER materials' phi (a third attempt
    # tried that and broke down as erosion accumulated: territory
    # `receding` already gave up earlier in this same call needs to
    # count as `growing`'s for the NEXT substep's adjacency test, but
    # `growing`'s own phi is static -- untouched -- for the whole call,
    # so it never reflects newly-vacated territory). Instead ownership
    # is tracked directly from what advance_front already knows: a
    # point still belongs to `receding` while `phi_recede_now < 0` and
    # its PRIOR owner was `receding`; everything `receding` has already
    # given up this call belongs to `growing`, on top of whatever
    # `growing` owned before. No other material's phi is needed.
    #
    # "ambient" is exempt from this restriction entirely: it is the
    # universal processing environment, exposed uniformly to whatever it
    # borders (a blanket deposit legitimately coats EVERY
    # currently-exposed solid surface, including one under a
    # pre-existing mask/cap, not just wherever the newly-forming film
    # happens to already exist -- which is usually nowhere at all on a
    # first deposit, making the restriction meaningless there anyway).
    def _exposure_mask(phi_recede_now):
        if receding == "ambient":
            return phi_recede_now < 0
        recede_region_now = (prev_owner == idx_recede) & (phi_recede_now < 0)
        growing_region_now = (prev_owner == idx_grow) | (
            (prev_owner == idx_recede) & (phi_recede_now >= 0))
        if not np.any(recede_region_now) or not np.any(growing_region_now):
            return np.zeros_like(recede_region_now)
        return recede_region_now & binary_dilation(growing_region_now)

    # The mask is applied by SELECTIVE REVERSION, not by baking V=0 into
    # the PDE stencil at protected cells (mathematically the same thing
    # here, since a masked cell's update is multiplied by V=0 either
    # way -- this form is just clearer about what "protected" means).
    #
    # A masked/heterogeneous-rate erosion like this needs periodic
    # reinitialization of `receding`'s own phi -- purely local, NOT
    # `project`'s multi-material ownership snap -- something the plain
    # unmasked S1 flat-front case never needed (its whole front always
    # moves together, so it stays a valid signed distance without any
    # reinit until the very end). Without it, this stalled completely:
    # once ANY cell crosses zero and its velocity there subsequently
    # drops to 0 (masked/protected, or simply already-consumed), its
    # phi value freezes at whatever tiny residual it crossed with,
    # instead of growing outward the way a true distance function
    # would. The STILL-exposed neighbor's one-sided difference against
    # that near-zero value then reads a shrunken, wrong gradient
    # magnitude (should be ~1) -- confirmed directly: a supposedly
    # constant-speed erosion decayed geometrically toward a dead stop
    # a few cells in, instead of advancing linearly, and undercut never
    # developed past the very first row. Fix: re-sign `receding`'s own
    # phi from its CURRENT sign pattern (a single-material distance
    # transform, not `project`'s multi-material one) whenever
    # accumulated travel since the last reinit reaches about one grid
    # cell -- frequent enough to keep the gradient valid, infrequent
    # enough that real sub-cell progress accumulates between snaps
    # rather than being discarded by it (the S1 lesson: reinitializing
    # EVERY substep, before even one cell of travel has accumulated,
    # reconstructs the identical cell boundary and the front never
    # moves at all).
    Vmag = np.asarray(V, dtype=float)
    phi_recede = ls.phi[receding].copy()
    t = 0.0
    dist_since_reinit = 0.0
    reinit_every = min(ls.dx, ls.dy)
    while t < t_total - 1e-15:
        dt = cfl_dt(Vmag, ls.dx, ls.dy, cfl)
        dt = min(dt, t_total - t)
        if receding == "ambient":
            phi_recede = advect_upwind(phi_recede, -Vmag, ls.dx, ls.dy, dt)
        else:
            mask = _exposure_mask(phi_recede)
            updated = advect_upwind(phi_recede, -Vmag, ls.dx, ls.dy, dt)
            phi_recede = np.where(mask, updated, phi_recede)
            dist_since_reinit += dt * float(np.max(Vmag))
            if dist_since_reinit >= reinit_every:
                inside = phi_recede < 0
                if np.any(inside) and not np.all(inside):
                    d_in = distance_transform_edt(inside, sampling=(ls.dy, ls.dx))
                    d_out = distance_transform_edt(~inside, sampling=(ls.dy, ls.dx))
                    phi_recede = np.where(inside, -d_in, d_out)
                dist_since_reinit = 0.0
        t += dt

    gave_up = (prev_owner == idx_recede) & (phi_recede >= 0)
    new_owner = np.where(gave_up, idx_grow, prev_owner)
    cur = ls.copy()
    cur.phi[receding] = phi_recede
    if reinit:
        return _project_from_owner(cur, new_owner)

    # reinit=False: for a driver that calls advance_front repeatedly
    # with a FRESH velocity field each time (e.g. M35-S3's oxidation,
    # which re-solves a diffusion PDE between calls because the flux
    # itself evolves as the interface moves -- unlike S2's deposit/etch,
    # where V is constant for the whole call). The default (reinit=True)
    # is wrong for that use: `_project_from_owner`'s boolean-mask EDT
    # snap is exactly the same quantization S1's advance_material hit
    # once already -- if ONE call's own total displacement is smaller
    # than a grid cell (the normal case for a driver taking many small
    # steps so it can re-solve its PDE often), the mandatory reinit
    # reconstructs the IDENTICAL cell ownership every time and the
    # front never moves AT ALL across repeated calls. Confirmed
    # directly: 25 chained calls of dt=0.04h each stayed pinned to the
    # exact seeded position, while one call over the full 1h moved
    # correctly. Fix: skip the snap and preserve `receding`'s accurate
    # (sub-cell) evolved phi across calls; mirror it into `growing`
    # wherever ownership just transferred (a cheap sign-consistent
    # proxy, not a true distance) so a LATER call's own
    # `ls.material_map()` still gives the right owner even without an
    # intervening full reinit. The caller is responsible for calling
    # `project()` explicitly every so often (not every call, or this
    # reproduces the same stall) to keep phi a genuinely valid signed
    # distance function away from the immediate frontier.
    cur.phi[growing] = np.where(gave_up, -np.abs(phi_recede), cur.phi[growing])
    return cur


def deposit_conformal(ls, material, thickness_um, rate_um_s=1.0, x_windows=None):
    """Blanket (or patterned) conformal deposition of `material`,
    growing out of whatever is currently `ambient` by `thickness_um`
    (normal offset -- genuine sidewall coverage and trench pinch-off
    fall out of the level-set advection itself, not a special case).

    M35-S4: `x_windows`, an optional list of `(x_lo, x_hi)` pairs in
    `ls`'s own x units (cm, matching `ls.x0`/`ls.x1`), makes this a
    FIRST-CLASS mask/pattern constructor rather than a separate
    function -- a patterned mask IS just deposition with zero rate
    outside the window, reusing `advance_front`'s existing per-point
    array-`V` support (already exercised by `etch_directional`) with no
    new topology code. Once deposited, the masked material is ordinary
    real geometry: `etch_isotropic`/`etch_directional`'s existing
    undercut/shadowing behavior applies to it with no special case
    needed (see their own docstrings). Default `x_windows=None` is
    exactly today's blanket behavior, unchanged."""
    t_total = thickness_um / rate_um_s
    if x_windows is not None:
        allowed = np.zeros(ls.Nx, dtype=bool)
        for lo, hi in x_windows:
            allowed |= (ls.x >= lo) & (ls.x <= hi)
        V = np.where(allowed[None, :], rate_um_s, 0.0) * np.ones((ls.Ny, 1))
    else:
        V = rate_um_s
    return advance_front(ls, receding="ambient", growing=material,
                          V=V, t_total=t_total)


def deposit_epitaxial(ls, material, thickness_um, rate_fn=None, rate_um_s=1.0):
    """M35-S4: facet-dependent deposition -- normal speed
    V(n_hat) = rate_um_s * max(rate_fn(nx, ny), 0), where (nx, ny) is
    `ambient`'s own local outward normal (central differences, exactly
    `etch_directional`'s existing normal-computation pattern, reused
    here rather than reimplemented -- there it differentiates the
    RECEDING material's phi to find which way to point the anisotropic
    etch; here `ambient` IS the receding material, so the same
    computation on `ls.phi["ambient"]` gives the growing front's own
    local normal instead).

    `rate_fn=None` means isotropic growth, and reduces EXACTLY (the
    same code path, not merely a numerically close result) to
    `deposit_conformal` -- checked as a gate below, not assumed.

    Honest limit: this is a purely GEOMETRIC facet-rate model. The
    caller supplies whatever `rate_fn(nx, ny)` reflects their own
    crystallographic rate anisotropy; no Miller-index-dependent
    epitaxial growth-rate table is built in or claimed."""
    if rate_fn is None:
        return deposit_conformal(ls, material, thickness_um, rate_um_s)
    # grad(phi_ambient) points from INSIDE ambient toward outside (i.e.
    # from ambient into whatever solid it borders) -- the OPPOSITE of
    # the growing surface's own outward normal (which points away from
    # the solid, into the ambient it is about to consume). Negate it so
    # `rate_fn` receives the physically intuitive convention: (nx, ny)
    # is the direction material is about to grow INTO.
    gx = np.gradient(ls.phi["ambient"], ls.dx, axis=1)
    gy = np.gradient(ls.phi["ambient"], ls.dy, axis=0)
    gmag = np.hypot(gx, gy)
    gmag_safe = np.where(gmag > 1e-12, gmag, 1.0)
    nx, ny = -gx / gmag_safe, -gy / gmag_safe
    V = rate_um_s * np.maximum(rate_fn(nx, ny), 0.0)
    t_total = thickness_um / rate_um_s
    return advance_front(ls, receding="ambient", growing=material,
                          V=V, t_total=t_total)


def etch_isotropic(ls, material, depth_um, rate_um_s=1.0):
    """Isotropic etch of `material` back into `ambient` by `depth_um`:
    constant normal speed everywhere `material` is exposed to `ambient`.

    Deliberately no `mask` parameter. A first version zeroed the speed
    field by raw x-position for "masked" columns -- that produces a
    sharp vertical step at the mask edge with NO lateral undercut at
    all (confirmed directly: a masked/open boundary etched to a clean
    right-angle corner, undercut measured as exactly 0 regardless of
    depth), because it treats masking as a property of a column's
    material susceptibility rather than of physical access. A mask only
    produces undercut when it is a real BARRIER the etchant must go
    around -- i.e. actual geometry (an existing solid material, such as
    a hard-mask cap already occupying that region), which this module
    already supports with no special masking logic needed: put a real
    material there and etch `material` isotropically: the etch front
    naturally wraps around the cap's edge once the open area etches
    below it. `test_m35_s2_topology.py`'s undercut gate is built this
    way. True first-class masks (that erode/cast shadows themselves)
    are S4 scope (section 5 of the plan)."""
    t_total = depth_um / rate_um_s
    return advance_front(ls, receding=material, growing="ambient",
                          V=rate_um_s, t_total=t_total)


def planarize(ls, y_cmp_um):
    """M35-S4: CMP -- polish everything shallower than `y_cmp_um` (cm
    convention: y increases downward, so "shallower" is smaller Y) down
    to bare ambient, leaving everything at or below `y_cmp_um` untouched.

    Trivial by construction (section 5 of the plan): CMP has no
    front-propagation physics at all, it is a one-shot ownership
    rewrite -- force ambient wherever Y is above the cut line, then
    re-derive every material's signed distance via `_project_from_owner`
    exactly as every other topology op in this module does."""
    y_cmp = y_cmp_um * 1.0e-4   # um -> cm, matching this module's cm convention
    idx_amb = ls.materials.index("ambient")
    owner = ls.material_map()
    owner = np.where(ls.Y < y_cmp, idx_amb, owner)
    return _project_from_owner(ls, owner)


def etch_directional(ls, material, depth_um, direction=(0.0, -1.0), rate_um_s=1.0):
    """Directional (anisotropic) etch of `material` back into `ambient`:
    normal speed = rate * max(n_hat . direction, 0), n_hat the local
    outward normal of `material`'s own interface (central differences).
    A wall whose normal is perpendicular to `direction` (e.g. a vertical
    wall under a straight-down beam) gets speed 0 and is not etched --
    a direct consequence of this formula, not asserted separately.
    No `mask`/shadowing parameter, for the same reason as
    `etch_isotropic`: a real blocking material produces real shadowing
    with no special-cased argument."""
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    phi = ls.phi[material]
    gx = np.gradient(phi, ls.dx, axis=1)
    gy = np.gradient(phi, ls.dy, axis=0)
    gmag = np.hypot(gx, gy)
    gmag_safe = np.where(gmag > 1e-12, gmag, 1.0)
    nx, ny = gx / gmag_safe, gy / gmag_safe
    cos_theta = nx * direction[0] + ny * direction[1]
    V = rate_um_s * np.maximum(cos_theta, 0.0)
    t_total = depth_um / rate_um_s
    return advance_front(ls, receding=material, growing="ambient",
                          V=V, t_total=t_total)
