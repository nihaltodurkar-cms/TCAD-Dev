"""M35-S4: silicidation (metal + silicon -> silicide) as a moving-
boundary problem, structurally mirroring `oxidize_levelset.py`'s
already-debugged architecture (persistent per-material phi arrays,
cheap argmin ownership with the product as "whichever cell nothing
else claims", periodic single-material reinit by accumulated travel
distance -- see that module's docstring for why this architecture,
rather than chaining `levelset2d.advance_front`, is what actually works
for a boundary whose growth rate is re-evaluated every macro-step).

See pytcad/M35-3D-PROCESS-PLAN.md section 5 for the scope and the
landing record for the physics/design decisions below.

PHYSICS
-------
Silicidation is structurally the SAME linear-parabolic moving-boundary
problem as Deal-Grove oxidation (dx/dt = B/(2x+A), x = total silicide
thickness) but with two consuming reactants instead of one reactant +
one gas supply:

* Metal recedes from above, silicon recedes from below, silicide grows
  in between (exactly S3's silicon/sio2/ambient stack, relabeled:
  metal plays ambient's role -- it shrinks from the open side -- and
  silicon plays its own S3 role unchanged).
* There is no separate gas phase and no lateral diffusion medium
  analogous to S3's laterally-diffusing oxidant cloud (the actual
  mechanism behind bird's beak) -- consumption at a silicidation front
  is local to each column. So unlike S3, this module does NOT solve a
  2D diffusion PDE at all: `dx/dt=B/(2x+A)` is evaluated PER COLUMN
  from that column's own current silicide thickness (a per-column
  1D reduction, not an approximation introduced here -- it is the
  ordinary linear-parabolic silicidation literature's own model, which
  has no lateral term to begin with).
* The newly grown silicide thickness in a time step is entirely
  accounted for by material consumed from the two reactants (there is
  no third "supply" source the way an oxidizing gas supplies material
  to oxidation) -- so `si_consumption_frac + metal_consumption_frac`
  must equal 1.0 exactly (checked, not assumed), and the two recession
  speeds are `dx/dt` split in that ratio.

HONEST LIMITS
-------------
* No built-in named silicide (NiSi/CoSi2/TiSi2). A web-search
  literature pass (dated in the S4 landing record) for a verifiable
  numeric (B, A) rate-constant table came back with only contradictory
  secondary-source activation-energy snippets (no two sources agreed,
  and no verified open-access prefactor was found at all) -- the same
  class of blocker as M14's G-A (paywalled primary source). `(B, A)`
  and the consumption split are therefore REQUIRED caller arguments,
  not looked up from a table the way `oxidize_levelset` uses
  `process.deal_grove_coefficients`. This is a real diffusion-limited
  moving-boundary solver, explicitly NOT calibrated to any specific
  real silicide.
* Purely column-local (1D) reaction: no lateral silicide spreading
  analogous to bird's beak is modeled, because none of the standard
  linear-parabolic silicidation literature includes one either (see
  above) -- this is not a simplification introduced here.
* No nucleation delay, no multi-phase sequence (e.g. Ni2Si -> NiSi ->
  NiSi2): a single product phase with one fixed (B, A), matching the
  same level of idealization S3's oxidation model uses for a single
  oxide phase.
* Same numerical-stability architecture as S3 (persistent phi arrays,
  not chained `advance_front` calls), so the same reinit/CFL
  bookkeeping is duplicated here rather than factored out, for the
  same reason S3 itself gives for not reusing `advance_front`: this
  loop took real debugging effort to get right once already, and
  premature factoring risks reintroducing one of those bugs for no
  test-coverage gain.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt

from .process2d import _UM_TO_CM, _CM_TO_UM
from .levelset2d import advect_upwind, cfl_dt, _project_from_owner


def silicide_levelset(ls, B_um2_hr, A_um, t_hours,
                       si_consumption_frac=0.5, metal_consumption_frac=0.5,
                       metal="metal", silicon="silicon", product="silicide",
                       steps=20):
    """Grow `product` (default "silicide") for `t_hours` at a caller-
    supplied linear-parabolic rate `dx/dt = B_um2_hr/(2x+A_um)`,
    consuming `silicon` and `metal` in the ratio
    `si_consumption_frac : metal_consumption_frac` (must sum to 1.0).
    Requires `metal`, `silicon`, `product` in `ls.materials`.
    """
    if abs((si_consumption_frac + metal_consumption_frac) - 1.0) > 1e-9:
        raise ValueError(
            f"si_consumption_frac + metal_consumption_frac must equal 1.0, "
            f"got {si_consumption_frac} + {metal_consumption_frac} = "
            f"{si_consumption_frac + metal_consumption_frac}"
        )
    for name in (metal, silicon, product):
        if name not in ls.materials:
            raise ValueError(f"silicide_levelset requires {name!r} in ls.materials")

    idx_si = ls.materials.index(silicon)
    idx_metal = ls.materials.index(metal)
    idx_product = ls.materials.index(product)
    static_names = [m for m in ls.materials if m not in (silicon, metal, product)]
    static_idx = [ls.materials.index(m) for m in static_names]
    static_phi = [ls.phi[m] for m in static_names]

    phi_si = ls.phi[silicon].copy()
    phi_metal = ls.phi[metal].copy()
    dx, dy = ls.dx, ls.dy
    dy_um = dy * _CM_TO_UM

    def ownership():
        stack = np.stack([phi_si, phi_metal] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_metal] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_product)   # leftover = product

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
    accum_metal = 0.0
    cfl = 0.4

    for _ in range(steps):
        mat_idx = ownership()
        product_mask = mat_idx == idx_product
        x_local_um = product_mask.sum(axis=0) * dy_um       # per-column thickness
        dxdt_um_per_hr = B_um2_hr / (2.0 * x_local_um + A_um)   # (Nx,)

        V_si_col = si_consumption_frac * dxdt_um_per_hr * _UM_TO_CM      # cm/hr
        V_metal_col = metal_consumption_frac * dxdt_um_per_hr * _UM_TO_CM
        V_si = np.broadcast_to(V_si_col[None, :], phi_si.shape)
        V_metal = np.broadcast_to(V_metal_col[None, :], phi_metal.shape)

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_si, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind(phi_si, -V_si, dx, dy, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si))
        if accum_si >= reinit_thresh:
            phi_si = reinit_single(phi_si)
            accum_si = 0.0

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt(V_metal, dx, dy, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_metal = advect_upwind(phi_metal, -V_metal, dx, dy, dt_sub)
            t += dt_sub
        accum_metal += dt * float(np.max(V_metal))
        if accum_metal >= reinit_thresh:
            phi_metal = reinit_single(phi_metal)
            accum_metal = 0.0

    final_owner = ownership()
    final = ls.copy()
    final.phi[silicon] = phi_si
    final.phi[metal] = phi_metal
    return _project_from_owner(final, final_owner)
