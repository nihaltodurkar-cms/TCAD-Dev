"""M35-S3: oxidation as a genuine moving-boundary problem on the S1/S2
level set -- a real embedded 2D oxidant-diffusion solve, replacing
process2d.oxidize_2d's column-independent Deal-Grove plus ad hoc
lateral-suppression kernel.

See pytcad/M35-3D-PROCESS-PLAN.md section 4 for the physics and
section 13 for the landing record, including the exact derivation of
the parameter choices below and the numerical-stability story below.

PHYSICS
-------
Deal-Grove: dx/dt = B/(2x+A), from the standard 3-resistance flux
F = C*/(1/h + x/D + 1/ks), dx/dt = F/N1, so B = 2DC*/N1,
A = 2D(1/ks+1/h). process.deal_grove_coefficients only gives the
combinations B and A (a fitted 1D result), not D, h, ks, C*, N1
individually -- an inherent degeneracy. This module resolves it with
an explicit, documented choice, not a measurement:

* D = 1.0 [um^2/hr] (arbitrary internal scale -- only ratios matter).
* h = ks = 4.0/A [um/hr] (SYMMETRIC-RESISTANCE ASSUMPTION: B and A
  cannot separately calibrate the gas-side mass-transfer rate from the
  Si-side reaction rate from a 1D fit alone; splitting the surface
  resistance evenly between the two is the simplest defensible choice).
* Cgas = B/2, with N1 folded into the concentration scale, so `ks*C`
  and `h*(Cgas-C)` come out directly in oxide-thickness um/hr with no
  separate N1 conversion.

Substituting back: Cgas/(1/h+x/D+1/ks) = (B/2)/(x+A/2) = B/(2x+A) --
exact, for ANY h=ks split, confirming these choices reduce correctly.

GROWTH-RATE SCALING (the mechanism that makes bird's beak emergent,
not hand-tuned): the SiO2-forming reaction happens only at the buried
Si/SiO2 interface; the gas surface only supplies oxidant. In 1D steady
state flux continuity makes flux_si = flux_gas = F pointwise, so this
module scales EACH flux independently by process.silicon_consumed's
0.44 / process2d.oxidize_2d's 0.56 split (Si consumption / outward
growth) rather than deriving one from the other or using a raw
unscaled flux. In 1D that reduces exactly to Deal-Grove
(0.44F+0.56F=F). In 2D the two rates can differ locally -- oxidant
absorbed under an OPEN mask edge can diffuse laterally through a
contiguous pad-oxide layer and still react further under the mask than
a purely local model would allow, which is the actual bird's-beak
mechanism, not `process2d.oxidize_2d`'s `masked_rate_fraction` kernel.

NUMERICAL STABILITY: why this module does NOT reuse S2's
`advance_front` for its own time-stepping loop
------------------------------------------------------------------
S2's deposit/etch calls use ONE constant velocity for the WHOLE call,
so `advance_front`'s own "reinitialize once, at the end" design is
correct there. Oxidation is different: the flux (and hence the normal
speed) changes as the interface moves, so the diffusion PDE must be
RE-SOLVED periodically against the CURRENT geometry, meaning many
small time increments are chained together, each far smaller than one
grid cell (that is the entire point of taking many steps). Two things
were tried and both failed, confirmed directly before landing on the
fix below:

1. Calling `advance_front` once per small increment with its default
   `reinit=True`: every call's own mandatory boundary-ownership
   distance snap (`project`) discards that increment's sub-cell
   progress, so the front never moves across repeated calls at all --
   the exact S1 "front never moves" pathology, recurring here because
   THIS caller, not `advance_front` itself, is the one chaining many
   small steps.
2. Calling `advance_front` with `reinit=False` (added for this
   purpose) and doing a full multi-material `project()` only every
   few steps: better, but empirically UNSTABLE -- the achieved
   thickness snapped to different, non-monotonic quantized values
   depending on the exact step-count/reinit-interval ratio (checked
   directly across a dozen combinations; error ranged from 1% to over
   90% with no discernible pattern in the "more reinits = better"
   direction). Root cause: `advance_front`'s two per-step calls both
   grow the SAME "sio2" material from opposite sides, but only touch
   its phi at freshly-crossed cells; over many steps without a full
   reinit, sio2's phi becomes internally inconsistent between the two
   directions, corrupting the OWNERSHIP MAP the next step's PDE solve
   and exposure test depend on -- not just a placement-precision issue.

The fix: this module tracks `phi_silicon` and `phi_ambient` as its OWN
persistent, continuously-evolving arrays for the ENTIRE call (bypassing
`advance_front` and `project` entirely inside the loop). Ownership at
each step is a CHEAP argmin against these two plus any static
(non-moving) materials -- sio2 is not tracked as its own phi at all
during the loop, it is simply "whichever cell nothing else claims" (the
partition is complete by construction, so this is exact, not an
approximation). Each of `phi_silicon`/`phi_ambient` gets its own
INDEPENDENT periodic single-material reinitialization based on
ACCUMULATED TRAVEL DISTANCE (not step count), exactly mirroring the
pattern `advance_front` already uses internally for a masked/
heterogeneous-rate erosion (S2's undercut gate) -- because that pattern
is what actually works, generalized here to span the whole call instead
of one `advance_front` invocation. Only at the very end is a real,
consistent multi-material `LevelSet2D` (with a proper "sio2" phi)
constructed, via ONE call to `project`.

HONEST LIMITS
-------------
* No stress term (not even "stress-lite") -- section 4 caps S3's
  stress scope at "may include, and nothing more"; omitting it
  entirely stays inside that cap.
* Masks are static geometry: they neither erode nor cast a directional
  shadow (that is S4's "masks as first-class objects").
* The h=ks split is a stated assumption, not a fit -- see above.
* Quasi-steady diffusion (the standard Deal-Grove assumption: the
  oxide's own diffusion time constant is far shorter than the growth
  timescale, so the concentration field is re-solved as an elliptic
  problem at each explicit time step rather than integrated as its own
  transient).
* The initial thin-oxide seed (`xi`, matching `process.oxide_thickness`'s
  own dry-growth fudge) is applied ONCE, before the loop, not
  re-checked every step for newly-exposed bare silicon -- no test in
  this slice exercises a mask that exposes fresh bare silicon mid-run
  (the bird's-beak gate's pad oxide already covers the whole domain
  from the start), so that generalization is deferred rather than
  built and left unexercised.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
from scipy.ndimage import distance_transform_edt, binary_dilation

from . import process
from .ted import segregation_partition
from .process2d import _UM_TO_CM, _CM_TO_UM
from .levelset2d import advect_upwind, cfl_dt, deposit_conformal, _project_from_owner


def _effective_params(T_C, ambient):
    """(D, ks, h, Cgas) in um/hr -- see module docstring for the
    symmetric-resistance derivation."""
    BA, B = process.deal_grove_coefficients(T_C, ambient)
    A = B / BA
    D = 1.0
    ks = h = 4.0 / A
    Cgas = B / 2.0
    return D, ks, h, Cgas


def _xi_um(ambient):
    return process._DEAL_GROVE[ambient]["xi"]


def _seed_thin_oxide(ls, ambient, rate_um_hr=1.0):
    """Wherever silicon is bare-exposed directly to ambient (no oxide
    cell between them), grow a thin `xi` layer -- the same fudge
    process.oxide_thickness itself uses for dry growth (0 for wet, a
    no-op). Reuses S2's deposit_conformal unchanged. Called once,
    before oxidize_levelset's own loop (see the module's honest-limits
    note on why this is not re-checked every step)."""
    xi = _xi_um(ambient)
    if xi <= 0:
        return ls
    idx_si = ls.materials.index("silicon")
    idx_amb = ls.materials.index("ambient")
    mat_idx = ls.material_map()
    si_mask = mat_idx == idx_si
    amb_mask = mat_idx == idx_amb
    bare = si_mask & binary_dilation(amb_mask)
    if not np.any(bare):
        return ls
    thickness_cm = xi * _UM_TO_CM
    return deposit_conformal(ls, "sio2", thickness_um=thickness_cm,
                              rate_um_s=rate_um_hr * _UM_TO_CM)


def _solve_oxidant_diffusion(oxide, mat_idx, idx_sio2, idx_si, idx_amb,
                              dx_um, dy_um, T_C, ambient):
    """Solve the steady-state oxidant-diffusion flux balance over the
    boolean `oxide` mask. Returns (C, flux_si, flux_gas): (Ny,Nx)
    arrays. flux_si/flux_gas are placed at the SILICON/AMBIENT cell
    (not the oxide cell) on each face -- the actual cell that a caller
    driving `advect_upwind` on THAT material's own phi needs a nonzero
    velocity at (confirmed directly as a real bug: placing it on the
    oxide side left the eroding material's own cells always seeing
    V=0, so nothing ever moved, regardless of macro-stepping).

    Finite-volume flux balance per oxide cell: sum of face fluxes = 0.
    Diffusive D*(C[i,j]-C_nbr)/spacing for oxide-oxide faces (weighted
    by the perpendicular face length); Robin h*(C[i,j]-Cgas) for faces
    touching ambient; reactive ks*C[i,j] for faces touching silicon;
    ZERO flux for a face touching any other material (an impermeable
    mask, e.g. "si3n4") -- this Neumann treatment is what makes
    bird's-beak lateral leakage an emergent property of the solve
    rather than a hand-tuned constant.
    """
    D, ks, h, Cgas = _effective_params(T_C, ambient)
    Ny, Nx = oxide.shape
    C = np.zeros((Ny, Nx))
    flux_si = np.zeros((Ny, Nx))
    flux_gas = np.zeros((Ny, Nx))

    if not np.any(oxide):
        return C, flux_si, flux_gas

    lin_idx = -np.ones((Ny, Nx), dtype=np.int64)
    oy, ox = np.where(oxide)
    n = oy.size
    lin_idx[oy, ox] = np.arange(n)

    rows, cols, vals = [], [], []
    rhs = np.zeros(n)
    directions = [(-1, 0, dy_um, dx_um), (1, 0, dy_um, dx_um),
                  (0, -1, dx_um, dy_um), (0, 1, dx_um, dy_um)]

    for k in range(n):
        i, j = oy[k], ox[k]
        diag = 0.0
        for di, dj, spacing, face_len in directions:
            ii, jj = i + di, j + dj
            if ii < 0 or ii >= Ny or jj < 0 or jj >= Nx:
                continue
            nbr_mat = mat_idx[ii, jj]
            if nbr_mat == idx_sio2:
                w = D / spacing * face_len
                diag += w
                rows.append(k); cols.append(lin_idx[ii, jj]); vals.append(-w)
            elif nbr_mat == idx_amb:
                w = h * face_len
                diag += w
                rhs[k] += w * Cgas
            elif nbr_mat == idx_si:
                w = ks * face_len
                diag += w
            # any other material: impermeable, no contribution
        rows.append(k); cols.append(k); vals.append(diag if diag > 0 else 1.0)
        if diag <= 0:
            rhs[k] = 0.0

    M = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    C_flat = spsolve(M, rhs)
    C[oy, ox] = C_flat

    for di, dj, spacing, face_len in directions:
        shifted_i = oy + di
        shifted_j = ox + dj
        valid = (shifted_i >= 0) & (shifted_i < Ny) & (shifted_j >= 0) & (shifted_j < Nx)
        nbr_mat = np.full(oy.shape, -1)
        nbr_mat[valid] = mat_idx[shifted_i[valid], shifted_j[valid]]
        at_si = nbr_mat == idx_si
        at_amb = nbr_mat == idx_amb
        flux_si[shifted_i[at_si], shifted_j[at_si]] += ks * C_flat[at_si]
        flux_gas[shifted_i[at_amb], shifted_j[at_amb]] += h * (Cgas - C_flat[at_amb])

    return C, flux_si, flux_gas


def solve_oxidant_diffusion(ls, T_C, ambient="dry"):
    """Convenience wrapper of `_solve_oxidant_diffusion` for a real,
    fully-consistent `LevelSet2D` (used to inspect/debug a single
    snapshot; `oxidize_levelset`'s own loop calls the cheaper internal
    form directly, since it does not keep a full LevelSet2D around
    between steps -- see the module docstring)."""
    idx_sio2 = ls.materials.index("sio2")
    idx_si = ls.materials.index("silicon")
    idx_amb = ls.materials.index("ambient")
    mat_idx = ls.material_map()
    oxide = mat_idx == idx_sio2
    return _solve_oxidant_diffusion(oxide, mat_idx, idx_sio2, idx_si, idx_amb,
                                     ls.dx * _CM_TO_UM, ls.dy * _CM_TO_UM,
                                     T_C, ambient)


def oxidize_levelset(ls, T_C, t_hours, ambient="dry", steps=20):
    """Grow oxide for `t_hours` at `T_C` via the real 2D diffusion
    solve, re-solved every macro-step, driving `phi_silicon`/
    `phi_ambient` as persistent, continuously-evolving arrays for the
    whole call (see the module docstring for why -- reusing
    `advance_front` per macro-step here was tried and is unstable).
    Requires "silicon", "sio2", "ambient" in `ls.materials`.
    """
    for name in ("silicon", "sio2", "ambient"):
        if name not in ls.materials:
            raise ValueError(f"oxidize_levelset requires {name!r} in ls.materials")

    seeded = _seed_thin_oxide(ls, ambient)
    idx_si = seeded.materials.index("silicon")
    idx_amb = seeded.materials.index("ambient")
    idx_sio2 = seeded.materials.index("sio2")
    static_names = [m for m in seeded.materials if m not in ("silicon", "sio2", "ambient")]
    static_idx = [seeded.materials.index(m) for m in static_names]
    static_phi = [seeded.phi[m] for m in static_names]   # never modified

    phi_si = seeded.phi["silicon"].copy()
    phi_amb = seeded.phi["ambient"].copy()
    dx, dy = seeded.dx, seeded.dy               # cm (LevelSet2D's own grid units)
    dx_um, dy_um = dx * _CM_TO_UM, dy * _CM_TO_UM

    def ownership():
        stack = np.stack([phi_si, phi_amb] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_amb] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_sio2)   # leftover = sio2

    def reinit_single(phi):
        inside = phi < 0
        if not np.any(inside) or np.all(inside):
            return phi
        d_in = distance_transform_edt(inside, sampling=(dy, dx))
        d_out = distance_transform_edt(~inside, sampling=(dy, dx))
        return np.where(inside, -d_in, d_out)

    dt = t_hours / steps
    reinit_thresh = min(dx, dy)
    accum_si = 0.0
    accum_amb = 0.0
    cfl = 0.4

    D, ks, h, Cgas = _effective_params(T_C, ambient)
    for _ in range(steps):
        mat_idx = ownership()
        oxide = mat_idx == idx_sio2
        if np.any(oxide):
            _, flux_si_um, flux_gas_um = _solve_oxidant_diffusion(
                oxide, mat_idx, idx_sio2, idx_si, idx_amb, dx_um, dy_um, T_C, ambient)
        else:
            # Bootstrap for xi=0 (wet ambient): no oxide cell exists
            # anywhere yet, so there is nothing for the PDE to solve
            # over and flux would come back all-zero forever, silently
            # freezing growth at zero permanently (confirmed directly).
            # This is exactly Deal-Grove's own x->0 limit: apply the
            # bare two-resistances-in-series flux directly at the
            # shared Si/ambient boundary (silicon cells adjacent to
            # ambient) until real growth creates a genuine oxide cell,
            # at which point the general PDE path above takes over.
            bare_flux_um = Cgas / (1.0 / h + 1.0 / ks)
            bare = (mat_idx == idx_si) & binary_dilation(mat_idx == idx_amb)
            flux_si_um = np.where(bare, bare_flux_um, 0.0)
            flux_gas_um = np.where(binary_dilation(mat_idx == idx_si) & (mat_idx == idx_amb),
                                    bare_flux_um, 0.0)
        V_si = 0.44 * flux_si_um * _UM_TO_CM     # cm/hr
        V_gas = 0.56 * flux_gas_um * _UM_TO_CM

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_si, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind(phi_si, -V_si, dx, dy, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si)) if np.any(V_si) else 0.0
        if accum_si >= reinit_thresh:
            phi_si = reinit_single(phi_si)
            accum_si = 0.0

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_gas, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_amb = advect_upwind(phi_amb, -V_gas, dx, dy, dt_sub)
            t += dt_sub
        accum_amb += dt * float(np.max(V_gas)) if np.any(V_gas) else 0.0
        if accum_amb >= reinit_thresh:
            phi_amb = reinit_single(phi_amb)
            accum_amb = 0.0

    # NOT `project(final)`: that calls `ls.material_map()`, a blind
    # argmin across ALL materials' CURRENT phi -- but sio2's own phi
    # was never touched during the loop (still the stale seed
    # placeholder), so within the real oxide region, wherever
    # phi_silicon/phi_ambient happen to be smaller than that stale
    # placeholder, a blind argmin misassigns the cell back to silicon
    # or ambient instead of sio2. Confirmed directly as the actual
    # cause of a huge (46%, not just an O(dx) snap) reduction-identity
    # error: `ownership()`'s own leftover-is-sio2 logic must drive the
    # final snap, not a naive argmin against a value that was never
    # kept meaningful.
    final_owner = ownership()
    final = seeded.copy()
    final.phi["silicon"] = phi_si
    final.phi["ambient"] = phi_amb
    return _project_from_owner(final, final_owner)


def oxidize_levelset_with_dopant(ls, Cdop, species_m, T_C, t_hours, ambient="dry", steps=20):
    """M35-S3b: like `oxidize_levelset`, but also transports a dopant
    field `Cdop` (cm^-3, same (Ny,Nx) grid as `ls`) across the moving
    Si/SiO2 boundary. See M35-3D-PROCESS-PLAN.md section 4b.

    A separate entry point rather than an optional parameter on
    `oxidize_levelset`: that function's return type (a single
    LevelSet2D) is exactly what its own S3 tests already call it as,
    and changing the return shape based on an optional argument would
    be a real API smell for zero benefit. Some structural duplication
    of the per-step loop is accepted deliberately -- that loop took
    real debugging effort to get right in S3 (see its own docstring),
    and refactoring it while also adding dopant tracking risks
    reintroducing one of those bugs for no test coverage gain.

    Physics: `ted.segregation_partition` already solves the right
    equations (dose conservation + equilibrium ratio C_si=m*C_ox) for
    a slab with GIVEN si/ox sub-thicknesses -- reused as-is, not
    reimplemented. This function's own contribution is applying it
    INCREMENTALLY, once per grid cell (or contiguous run of cells) the
    front actually sweeps through in a step, rather than once at a
    fixed final slab (`ted.py`'s own honesty clause flags exactly this
    gap): each macro-step, compare silicon ownership before and after
    that step's advection; for every column where one or more cells
    flipped from silicon to sio2, treat those cells PLUS the next
    (deeper, still-silicon) cell as one slab of total areal dose
    `Q = (sum of the converted cells' dose + the next cell's dose)`,
    and re-partition it via `segregation_partition(Q, species_m,
    thickness_si_cm=dy, thickness_ox_cm=dy*n_converted)`. This
    conserves dose EXACTLY by construction (segregation_partition's own
    conservation equation) -- the test gate confirms that, it does not
    discover it.
    """
    for name in ("silicon", "sio2", "ambient"):
        if name not in ls.materials:
            raise ValueError(f"oxidize_levelset_with_dopant requires {name!r} in ls.materials")

    seeded = _seed_thin_oxide(ls, ambient)
    Cdop = np.asarray(Cdop, dtype=float).copy()
    idx_si = seeded.materials.index("silicon")
    idx_amb = seeded.materials.index("ambient")
    idx_sio2 = seeded.materials.index("sio2")
    static_names = [m for m in seeded.materials if m not in ("silicon", "sio2", "ambient")]
    static_idx = [seeded.materials.index(m) for m in static_names]
    static_phi = [seeded.phi[m] for m in static_names]

    phi_si = seeded.phi["silicon"].copy()
    phi_amb = seeded.phi["ambient"].copy()
    dx, dy = seeded.dx, seeded.dy
    dx_um, dy_um = dx * _CM_TO_UM, dy * _CM_TO_UM
    Ny, Nx = phi_si.shape

    def ownership(phi_si_, phi_amb_):
        stack = np.stack([phi_si_, phi_amb_] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_amb] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_sio2)

    def reinit_single(phi):
        inside = phi < 0
        if not np.any(inside) or np.all(inside):
            return phi
        d_in = distance_transform_edt(inside, sampling=(dy, dx))
        d_out = distance_transform_edt(~inside, sampling=(dy, dx))
        return np.where(inside, -d_in, d_out)

    dt = t_hours / steps
    reinit_thresh = min(dx, dy)
    accum_si = 0.0
    accum_amb = 0.0
    cfl = 0.4
    D, ks, h, Cgas = _effective_params(T_C, ambient)

    for _ in range(steps):
        owner_before = ownership(phi_si, phi_amb)
        oxide = owner_before == idx_sio2
        if np.any(oxide):
            _, flux_si_um, flux_gas_um = _solve_oxidant_diffusion(
                oxide, owner_before, idx_sio2, idx_si, idx_amb, dx_um, dy_um, T_C, ambient)
        else:
            bare_flux_um = Cgas / (1.0 / h + 1.0 / ks)
            bare = (owner_before == idx_si) & binary_dilation(owner_before == idx_amb)
            flux_si_um = np.where(bare, bare_flux_um, 0.0)
            flux_gas_um = np.where(
                binary_dilation(owner_before == idx_si) & (owner_before == idx_amb),
                bare_flux_um, 0.0)
        V_si = 0.44 * flux_si_um * _UM_TO_CM
        V_gas = 0.56 * flux_gas_um * _UM_TO_CM

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_si, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind(phi_si, -V_si, dx, dy, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si)) if np.any(V_si) else 0.0
        if accum_si >= reinit_thresh:
            phi_si = reinit_single(phi_si)
            accum_si = 0.0

        owner_after_si = ownership(phi_si, phi_amb)   # phi_amb not yet advanced this step
        transitioned = (owner_before == idx_si) & (owner_after_si == idx_sio2)
        if np.any(transitioned):
            for col in np.where(np.any(transitioned, axis=0))[0]:
                rows = np.sort(np.where(transitioned[:, col])[0])
                nxt = rows[-1] + 1
                if nxt >= Ny:
                    continue   # no deeper neighbor to push into; leave as-is (edge case)
                Q = (Cdop[rows, col].sum() + Cdop[nxt, col]) * dy
                C_si_new, C_ox_new = segregation_partition(
                    Q, species_m, thickness_si_cm=dy, thickness_ox_cm=dy * rows.size)
                Cdop[rows, col] = C_ox_new
                Cdop[nxt, col] = C_si_new

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_gas, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_amb = advect_upwind(phi_amb, -V_gas, dx, dy, dt_sub)
            t += dt_sub
        accum_amb += dt * float(np.max(V_gas)) if np.any(V_gas) else 0.0
        if accum_amb >= reinit_thresh:
            phi_amb = reinit_single(phi_amb)
            accum_amb = 0.0

    final_owner = ownership(phi_si, phi_amb)
    final = seeded.copy()
    final.phi["silicon"] = phi_si
    final.phi["ambient"] = phi_amb
    final_ls = _project_from_owner(final, final_owner)
    return final_ls, Cdop
