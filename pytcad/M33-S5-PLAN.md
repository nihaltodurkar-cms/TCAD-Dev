# M33-S5 -- chi-aware band alignment, ported to Device3D and unstructured_dd.py

Parent: `M33-INTERFACE-PLAN.md` section 8 / `M33-S4-PLAN.md` section 4
named this as the last remaining piece of M33 once Device2D (S4) landed.

Scope of THIS slice: **Device3D (structured path)** and
**`unstructured_dd.py`'s standalone `solve_bias`** (the 2D unstructured
coupled DD core -- NOT `unstructured_dd3d.py`, which is explicitly
homojunction-only with no `materials_per_node`/`dlnnie` mechanism to
extend at all; adding a heterojunction path there would be a new
feature, not a port of an existing one, and is out of scope here).

## 0. What is being ported, and to where

### Device3D (structured)

Exactly S4's derivation, one more axis:

    s = ln(Nc/nie) + chi/VT     (per node, shape (Nz,Ny,Nx))
    band_shift = s - s.flat[0]   (referenced to node 0; a homojunction
                                   gives band_shift == 0 IDENTICALLY)

Touch points, all gated on `Models.band_offset` (already shared by
Device1D/Device2D, no change needed to `Models` itself):

  * `__init__`: build `self.chi_arr`/`self.band_shift`, shape
    `(Nz,Ny,Nx)`; refuse `band_offset="affinity"` with `self.fd`
    (same FD-composition refusal as S1/S4); refuse `Models.thermionic`
    outright (Device3D does not check this flag at all today --
    checked directly, absence confirmed by reading the refusal block
    in `__init__` -- so this ALSO closes a pre-existing silent-ignore
    gap, not just mirrors S4).
  * `_bc_contact_values`: subtract `band_shift[k,j,i]` from `psi0`.
  * `_bulk_psi_guess` (non-FD branch): subtract `band_shift`.
  * `_residual_jacobian_poisson` (equilibrium): carriers slaved to
    `psi + band_shift`; the GateBC Robin term's `psi_b_local` gets the
    matching `-band_shift[k,j,i]` (3D's GateBC already has this
    LOCAL-reference term per its own module docstring -- Device2D's
    equivalent term was missing until an earlier session added it;
    Device3D was "built in correctly from the start" per its own
    docstring, so this is genuinely the same fix pattern, just already
    present here for the base term -- only the `-band_shift` addition
    is new).
  * `_residual_jacobian` (bias): SG edge deltas gain
    `ds_x = band_shift[:,:,1:] - band_shift[:,:,:-1]`,
    `ds_y = band_shift[:,1:,:] - band_shift[:,:-1,:]`,
    `ds_z = band_shift[1:,:,:] - band_shift[:-1,:,:]`, added with the
    SAME sign to both `dx`/`dxp`, `dy`/`dyp`, `dz`/`dzp` (unlike
    `dlnnie`'s opposite carrier signs). Constant under Newton, so no
    Jacobian column changes -- same argument S1/S4 make. The bias
    Jacobian's own GateBC Robin term gets the matching
    `-band_shift[bc.k,bc.j,bc.i]` fix.
  * `solve_equilibrium`'s final `self.n`/`self.p` assignment (non-FD
    branch): uses `psi_c = psi + band_shift`, matching S4's Device2D
    choice (the mathematically correct form for new code), NOT
    replicating Device1D's own known final-assignment asymmetry
    (recorded in `M33-S4-PLAN.md` section 1/4, still unfixed, still
    out of scope here).

### unstructured_dd.py (2D unstructured, coupled bias solve)

This module has NO `Models` object -- `solve_bias` takes plain kwargs
(`doping_mobility`, `materials_per_node`, `srh`, `auger`, ...) and
already implements the LEGACY symmetric `dlnnie` heterojunction term
via `materials_per_node` (its own module docstring, "M21-follow-up").
The port here is the same shape as S1/S4's core idea, adapted to this
module's per-edge (not per-node-grid) assembly:

  * New kwarg `band_offset="nie"` (default) or `"affinity"`, mirroring
    Device1D/2D/3D's `Models.band_offset` naming so the convention
    reads the same across every core even though this module has no
    `Models` object to hang it on.
  * When `"affinity"`: per-node `nc_node = array([m.Nc(T) for m in
    mats])` (mirroring the existing `nie_node` construction one line
    above it), `s = log(nc_node/nie_node) + chi_node/VT`,
    `band_shift = s - s[0]` (referenced to node 0 of the mesh's own
    node ordering -- arbitrary but consistent, same as S1/S4's node
    (0,)/(0,0)/(0,0,0) choice; a homojunction still gives `band_shift
    == 0` identically since a uniform material gives a uniform `s`).
  * `_residual_jacobian` gains a new parameter `ds` (per-INTERIOR-EDGE,
    same sign both carriers -- unlike `dlnnie`'s opposite signs):
    `delta_n = psi[j]-psi[i]+dz+ds`, `delta_p = psi[j]-psi[i]-dz+ds`.
    `None`/all-zero reproduces the existing `dlnnie`-only current
    exactly -- this is the module's own "None reduces to the original"
    convention, applied to the new term.
  * Contact `psi0` (from `_ohmic_values`, called on `contact_idx`):
    subtract `band_shift[contact_idx]` -- same reasoning as every
    other core's `_bc_contact_values`.
  * Cold-start guess (`init is None` branch): subtract `band_shift`
    from the `arcsinh` guess -- same reasoning as `_bulk_psi_guess`.
    The `init`-supplied warm-start branch is untouched (external state,
    already in the shifted-or-not convention the caller chose).
  * No FD, no thermionic in this module at all (never implemented,
    nothing to refuse specifically for this port) -- an unrecognized
    `band_offset` value raises `ValueError`, matching the convention
    every other core uses for an invalid `Models` field.
  * `Device2D(unstructured=True)`'s own wrapper (`_init_unstructured`)
    already refuses ANY heterostructure material list outright
    (`device2d.py` line ~362-367) before ever reaching
    `unstructured_dd.py` -- so this new gauge is reachable only by
    calling `unstructured_dd.solve_bias` directly (exactly how
    `materials_per_node`'s existing legacy-gauge heterojunction support
    is reached today; `test_unstructured_dd_mobility_het.py` is the
    precedent). No change to the wrapper's own refusal.

`unstructured_dd3d.py` is explicitly OUT of scope (see section 0
preamble) -- it has no heterojunction mechanism of any kind to extend.

## 1. Amendment request (REQUIRED BEFORE ANY CORE EDIT)

Touches `pytcad/device3d.py`'s `__init__`, `_bc_contact_values`,
`_bulk_psi_guess`, `_residual_jacobian_poisson`, `_residual_jacobian`,
`solve_equilibrium`; and `pytcad/unstructured_dd.py`'s
`_residual_jacobian` and `solve_bias`. Both frozen core. Per
CLAUDE.md: explicit sign-off, FD-Jacobian-first, bit-identical
off-path, reconstruct-and-compare on every golden the change could
touch.

SIGN-OFF: **GIVEN 2026-09-11** by the user, selecting "M33 2D/3D
affinity port (Recommended)" as the explicit next task
(AskUserQuestion), on the scope above (Device3D structured path +
unstructured_dd.py's standalone solve_bias; unstructured_dd3d.py
excluded).

### Golden baseline, recorded BEFORE the edit (step 1 of 4)

    f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
    36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
    f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
    ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
    a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
    7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz

`resistor3d_eq.npz` is the one
Device3D golden and the one this change could plausibly move (it uses
`band_offset` default `"nie"`); the rest are recorded because
CLAUDE.md's protocol says every golden the change COULD touch, not
just the one that seems likely. Identical to the S4 baseline in
`M33-S4-PLAN.md` section 2 -- confirms nothing else moved the tree
between S4 landing and this slice starting.

## 2. Gates

Mirroring S4's own gate list, narrowed/extended for 3D and for the
unstructured module's different assembly:

  G-1  EQUILIBRIUM DETAILED BALANCE, PER CARRIER SEPARATELY, on a 3D
       heterojunction (a chi step along one axis) and on an
       unstructured-mesh heterojunction. Absolute floor (S1/S4's own
       finding that a ratio-normalised gate is vacuous), measured
       empirically before being hardcoded, same as S4.
  G-2  chi ACTUALLY MOVES THE SOLUTION -- monotonic in the step sign,
       on an isotype (no built-in p-n) structure, for BOTH Device3D
       and unstructured_dd.py.
  G-3  FD-JACOBIAN ON THE INTERFACE EDGES SPECIFICALLY, for BOTH
       modules (Device3D: all three axis directions crossing the
       material change; unstructured_dd.py: the interior edges
       crossing the region boundary).
  G-4  BIT-IDENTITY OFF-PATH: `band_offset="nie"`/default reproduces
       the existing goldens exactly; a homojunction is bit-identical
       between the two gauges, for BOTH modules.
  G-5  GateBC Robin term composes correctly with a chi step under the
       gate on Device3D (S4's own G-5 precedent; unstructured_dd.py
       has no gate BC at all, so no G-5 equivalent there).
  G-6  `Models.thermionic` on Device3D refuses (NotImplementedError) --
       closes the pre-existing silent-ignore gap noted in section 0.
  G-7  `band_offset="affinity"` with `self.fd` refuses on Device3D
       (matching S1/S4). unstructured_dd.py has no FD support at all,
       so instead: an unrecognized `band_offset` string raises
       `ValueError` on unstructured_dd.py.

No published-value benchmark attempted, same judgement S1/S4 already
made -- none of G-1..G-7 needs an external source, and neither 3D nor
the unstructured mesh adds anything that would make one newly
reachable.

## 3. Results

LANDED 2026-09-11. `tests/test_m33_s5_3d_and_unstructured_interface.py`,
21 gates (16 Device3D + 5 unstructured_dd.py, after two gates were
redesigned during implementation -- see below), all green.

**Device3D matched section 0's prediction exactly** -- one more axis
than S4, no surprises. `chi_arr`/`band_shift` built on the `(Nz,Ny,Nx)`
grid; `ds_x`/`ds_y`/`ds_z` added with the SAME sign to all six SG
deltas; `_bc_contact_values`/`_bulk_psi_guess`/both GateBC Robin terms
get `-band_shift`; the pre-existing thermionic silent-ignore gap
(Device3D never checked the flag) is now closed. Every new term is an
exact `+0.0`/`-0.0` on the default `"nie"` gauge -- bit-identical by
construction, confirmed by all 16 Device3D gates (G1-G7, mirroring
S4's own shapes one axis further) passing on first run, and by
`tests/goldens/m13/*.npz` (all six files, including the one Device3D
golden `resistor3d_eq.npz`) coming back md5-IDENTICAL to section 1's
baseline.

**unstructured_dd.py's port also matched the derivation exactly at the
mechanical level** -- new `band_offset` kwarg, `ds` edge term in
`_residual_jacobian` (verified directly with a synthetic 4-node/3-edge
probe: `Jn`/`Jp` responded correctly to a nonzero `ds`), contact
`psi0`/cold-start guess get `-band_shift`. Bit-identity off-path
confirmed (G4: default/explicit `"nie"` bit-identical to each other and
to the pre-existing call signature; homojunction bit-identical between
gauges) and by FD-Jacobian on the interface edges (G3, after fixing a
test bug -- see below).

**One genuine physics finding, investigated rather than assumed, that
changed two of the originally-planned empirical gates.** The naive
port of Device2D/3D's own "isotype junction current is maximised at
zero chi-offset" empirical gate (G2) FAILED here -- not with a
plausible-looking near-miss, but with the terminal current agreeing
across a chi sweep from 3.85 to 6.05 eV to every printed digit.
Direct investigation (synthetic probes, not guesswork) found the root
cause: `unstructured_dd.py` has NO separate equilibrium-only residual
the way Device1D/2D/3D's `_residual_jacobian_poisson` provides (no
analytic `n = nie*exp(psi_c)` carrier slaving) -- `solve_bias` always
solves the fully-coupled system with `n`, `p` as free unknowns, even
at `bias={}`. For a UNIFORMLY doped isotype junction (same C, same nie
both materials -- no depletion anywhere from doping alone), `n=C, p~0`
satisfies Poisson pointwise for ANY psi, and the SG Bernoulli identity
`B(x)-B(-x)=x` then makes `Jn` EXACTLY LINEAR in `psi+band_shift` when
`n` is uniform. Because the contact fix sets
`psi0_contact = psi0_original - band_shift[contact]`, the shifted
variable at BOTH contacts equals the ORIGINAL gauge-free value -- so
the terminal current, which this linear relation makes depend on
nothing but that variable's boundary values, is PROVABLY independent
of `band_offset` for this specific (uniform, undepleted) geometry.
Confirmed directly that Device2D's own isotype gate does NOT hit this
degeneracy because its `solve_equilibrium` slaves carriers analytically
(producing a real interface spike in `n`, measured directly: range
0.45-1.59 vs. this module's flat 1.0 for the same nominal setup)
BEFORE `solve_bias` ever runs; `unstructured_dd.py`'s own `solve_bias`,
even warm-started from its OWN `bias={}` "cold" solve via `init=`,
converges to the flat `n=C` fixed point instead, both for the isotype
case and (checked separately) for a real p-n junction at the length
scales tried, where the effect proved numerically negligible rather
than exactly zero. `test_g2_u_isotype_terminal_current_is_analytically_
gauge_invariant` now asserts this bit-identity as the correct gate for
this module's actual mathematics (not a workaround); the
"pn_direction_is_physical" empirical gate was dropped rather than kept
with a fudged tolerance, since the measured effect there was at
Newton's own convergence floor, not a real signal -- `test_g2_u_
affinity_step_moves_the_solution` (psi genuinely moves, `>1e-3`) is
this module's real G2 evidence that the term is live. G3 also had one
test-only bug found and fixed: its interface-edge detector originally
keyed off `dlnnie` (always exactly zero here, since both materials
share the same nie) instead of `ds` -- fixed to key off `ds`.

Suite green both ways: `PYTCAD_ACCEL=1` 1674 passed/5 skipped/1
xfailed (573.87s), `PYTCAD_ACCEL=0` 1666 passed/13 skipped/1 xfailed
(572.54s), 39 warnings and zero failures in both -- the pre-S5
baselines (1653/1645) plus exactly these 21 gates.

**M33 is now fully landed** (S1-S5): Device1D, Device2D, Device3D, and
`unstructured_dd.py` all support the chi-aware affinity gauge.
`unstructured_dd3d.py` remains explicitly out of scope (see section 0
preamble) -- it has no heterojunction mechanism at all to extend, so
adding one there would be new-feature work, not a port. Device1D's own
`solve_equilibrium` final-assignment asymmetry (flagged in
`M33-S4-PLAN.md` section 4) remains unfixed, unrelated to this slice.
