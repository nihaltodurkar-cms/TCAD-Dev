# M33-S4 -- chi-aware band alignment, ported to Device2D

Parent: `M33-INTERFACE-PLAN.md` section 8 named this "the single biggest
remaining piece of M33" -- `device2d.py`/`device3d.py`/`unstructured_dd.py`
do not reference `chi` at all, so every 2D/3D heterostructure (including
the HBT/HEMT templates) still solves S1's pre-fix symmetric-nie split.
Section 8 also said the port is "a straight port of S1's `band_shift`
(one per-node array; the edge term is the same `+ ds` on both carriers)".

Scope of THIS slice: **Device2D (structured path) only.** Device3D and
`unstructured_dd.py` are deferred to a follow-up slice (S5), same "1D
first, then one dimensionality at a time" precedent M18/M19/S1 already
used -- porting all three at once would multiply the review surface for
no gate that needs it done together.

## 1. What is being ported

Exactly S1's derivation (`M33-INTERFACE-PLAN.md` section 7), applied
node-wise on the `(Ny, Nx)` grid instead of the 1D array:

    s = ln(Nc/nie) + chi/VT     (per node)
    band_shift = s - s.flat[0]   (referenced to node 0, so a
                                   homojunction gives band_shift == 0
                                   IDENTICALLY, everywhere)

Touch points, all gated on `Models.band_offset` (already a shared field
on `Models`, consumed by Device1D since S1 -- no change needed there):

  * `__init__`: build `self.chi_arr` and `self.band_shift` (shape
    `(Ny, Nx)`); refuse `band_offset="affinity"` with `self.fd` (the FD
    eta-space contact/neutral-guess machinery carries its own
    `ln(Nc/nie)` offset, not composed with the shift here -- same
    refusal S1 gave Device1D) and refuse `Models.thermionic` outright
    (TE interface flux is Device1D-only; S4 is the alignment fix alone).
  * `_bc_contact_values`: subtract `band_shift[j,i]` from `psi0` (n0/p0
    are gauge-free, only psi0's reference moves -- identical reasoning
    to Device1D's `_contact_values`).
  * `_bulk_psi_guess` (non-FD branch): subtract `band_shift`, so the
    neutral-bulk guess is in the same electrostatic-psi convention the
    Poisson flux is written in.
  * `_residual_jacobian_poisson` (equilibrium): carriers slaved to
    `psi + band_shift`, not `psi` alone; the GateBC Robin term's
    `psi_b_local` gets the same `-band_shift[j,i]` as the bulk guess.
  * `_residual_jacobian` (bias): the SG edge deltas gain
    `ds_x = band_shift[:, 1:] - band_shift[:, :-1]` /
    `ds_y = band_shift[1:, :] - band_shift[:-1, :]`, added to BOTH
    `dx`/`dxp` and `dy`/`dyp` with the SAME sign (unlike `dlnnie`'s
    opposite carrier signs -- a rigid band shift moves both carriers'
    reference together). `ds_x`/`ds_y` are constant under the Newton
    update exactly like `dlnnie_x`/`dlnnie_y`, so no Jacobian column
    changes -- same argument S1 makes for the 1D edge term. The
    bias-Jacobian's own GateBC Robin term gets the matching
    `psi_b_local` fix.

`self.n`/`self.p` stored after `solve_equilibrium` use `psi + band_shift`
too (the mathematically correct form per the derivation above) -- **note
for the record, not a fix made here**: Device1D's own
`solve_equilibrium` final assignment (`device.py` around the `self.n =
nie*exp(psi)` line after the main Newton loop) does NOT apply
`band_shift` there, an asymmetry with its own `psi_c` mid-loop use.
Untested by any M33 gate (G1/G2 check `psi`/`J` via `solve_bias`, not
the raw equilibrium snapshot) and out of scope for this slice -- flagged
here rather than silently carried into new code or silently "fixed"
without its own sign-off.

## 2. Amendment request (REQUIRED BEFORE ANY CORE EDIT)

This touches `pytcad/device2d.py`'s `_residual_jacobian`,
`_residual_jacobian_poisson`, `_bc_contact_values` and `_bulk_psi_guess`
-- frozen core. Per CLAUDE.md: explicit sign-off, FD-Jacobian-first,
bit-identical off-path, reconstruct-and-compare on every golden the
change could touch.

SIGN-OFF: **GIVEN 2026-09-10** by the user, selecting "M33 2D/3D
affinity port" as the explicit next task (AskUserQuestion), on the scope
above (Device2D structured path; Device3D/unstructured deferred to S5).

### Golden baseline, recorded BEFORE the edit (step 1 of 4)

    f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
    36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
    f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
    ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
    a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
    7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz

`diode2d_eq.npz` is the one this change could plausibly move (it is a
Device2D golden); the other five are recorded because CLAUDE.md's
protocol says every golden the change COULD touch, not just the one
that seems likely.

## 3. Gates

Mirroring S1's own gate list (`M33-INTERFACE-PLAN.md` section 4),
narrowed to what a 2D structured grid can express:

  G-1  EQUILIBRIUM DETAILED BALANCE, PER CARRIER SEPARATELY, on a 2D
       heterojunction (a lateral chi step). Absolute floor, not a
       ratio (S1's G1 found a ratio-normalised gate to be vacuous).
  G-2  chi ACTUALLY MOVES THE 2D SOLUTION -- monotonic in the step
       sign, on an isotype (no p-n built-in) structure so the effect
       is not absorbed by re-equilibration (S1's own G2 precedent).
  G-3  FD-JACOBIAN ON THE INTERFACE EDGES SPECIFICALLY (both x- and
       y-direction edges crossing the material change), not a random
       column sample.
  G-4  BIT-IDENTITY OFF-PATH: `band_offset="nie"` (the default)
       reproduces the existing `diode2d_eq` golden exactly, and a
       homojunction is bit-identical between the two gauges.
  G-5  GateBC Robin term composes correctly with a chi step under the
       gate (a heterojunction MOSFET-like structure) -- the
       `psi_b_local` fix does not silently break the existing
       gate-flux gates for a homojunction (S4-specific; S1 had no gate
       BC to worry about).
  G-6  `Models.thermionic` on Device2D refuses (NotImplementedError),
       matching the impact/btbt/dg refusal convention already in this
       file.
  G-7  `band_offset="affinity"` with `self.fd` refuses, matching S1's
       own refusal.

No G-7-equivalent published-value benchmark is attempted here, same
judgement S1 already made (`M33-INTERFACE-PLAN.md` section 5): none of
G-1..G-6 needs an external source, and 2D adds nothing that would make
one newly reachable.

## 4. Results

LANDED 2026-09-10/11. `tests/test_m33_s4_2d_interface.py`, 16 gates, all
green on first run.

**The port matched section 1's prediction exactly -- no surprises in
the derivation.** `chi_arr`/`band_shift` built node-wise on the
`(Ny, Nx)` grid; `ds_x`/`ds_y` added with the SAME sign to both
`dx`/`dxp` and `dy`/`dyp` (unlike `dlnnie_x`/`dlnnie_y`'s opposite
carrier signs); `_bc_contact_values`/`_bulk_psi_guess`/both GateBC Robin
terms all get `-band_shift` at the relevant node(s). Every new term is
an exact `+0.0`/`-0.0` on the default `"nie"` gauge, so the port is
bit-identical by construction, not by tolerance.

**Physics reproduces the validated 1D shape.** Isotype (no p-n
built-in) junction current: 0.4999 A/cm at dchi=-0.20eV, 0.5135 at
dchi=0 (max), 0.4999 at dchi=+0.20eV -- current maximised at zero offset
and falling for BOTH signs, the same sign-symmetric signature the 1D
G2 gate measures (6.42e3/4.34e3/3.11e3 A/cm^2 there). p-n junction
current falls monotonically as chi rises on the far side (2.43e-8 ->
2.27e-8 A/cm across chi=3.85->4.25 eV), matching 1D's own ~1%-per-0.1eV
finding -- a rigid shift on one side is mostly absorbed by the built-in
potential re-equilibrating, same as 1D.

**Reconstruct-and-compare: all six `tests/goldens/m13/*.npz` files came
back md5-IDENTICAL** to the section-2 baseline. Nothing moved (expected:
`band_shift` is identically `np.zeros` on the default gauge).

**G1's absolute floor, measured rather than assumed** (following S1's
own precedent that a ratio-normalised gate is vacuous): sweeping
dchi in [-0.30, +0.30] at equilibrium on the affinity gauge, the worst
`max(|Jn_x|, |Jn_y|, |Jp_x|, |Jp_y|)` (converted to physical A/cm via
`J0`) was 1.6e-10 -- Newton's own stopping floor, not a balance
violation. `EQ_CURRENT_FLOOR = 1e-7` sits ~600x above it.

**G5 (GateBC + affinity gauge) needed a genuinely new gate S1 had no
analogue for** -- Device1D has no gate contact, so the `psi_b_local`
fix (both the equilibrium and bias Jacobian's Robin term) was only
checked by this slice: a homojunction-under-a-gate regression
(bit-identical between gauges) plus an FD-Jacobian on the whole device
(gate rows included) with a real chi step under half the channel, both
green.

**Two refusals added**, matching Device1D's S1/S2 refusal shape:
`Models.thermionic` on Device2D (`NotImplementedError` -- TE interface
flux stays Device1D-only, a separate follow-up slice); `band_offset=
"affinity"` with `self.fd` (the FD contact/neutral-guess machinery
carries its own `ln(Nc/nie)` offset, not composed with the shift here).

**One thing found and deliberately NOT changed**, recorded rather than
silently carried forward or silently fixed: Device1D's own
`solve_equilibrium` stores its FINAL `self.n`/`self.p` as
`nie*exp(psi)` (no `band_shift`), even though the SAME method's Newton
loop uses `psi_c = psi + band_shift` to compute `n`/`p` mid-iteration --
an asymmetry, confirmed by reading `device.py` directly (see section 1
above). Untested by any M33 gate (G1/G2 read `psi`/`J` via `solve_bias`,
never the raw equilibrium snapshot), so it changes no gated behavior --
but it means Device1D's post-`solve_equilibrium()` `.n`/`.p` under
`band_offset="affinity"` on a heterojunction are NOT the values the
milestone's own derivation says they should be. This Device2D port
uses the mathematically correct `psi_c` form for its own equivalent
final assignment (harmless under the default gauge, since `band_shift`
is zero there) rather than replicating the 1D asymmetry into new code.
Fixing 1D's own asymmetry is a separate, one-line change that needs its
own sign-off (it touches the frozen core) and is deliberately not
folded into this slice.

Suite green both ways: `PYTCAD_ACCEL=1` 1653 passed/5 skipped/1
xfailed, `PYTCAD_ACCEL=0` 1645 passed/13 skipped/1 xfailed, 39 warnings
and zero failures in both -- the pre-S4 baselines (1637/1629) plus
exactly these 16 gates.

**NOT done, deliberately (per section 0's scope):** Device3D and
`unstructured_dd.py` remain in the legacy gauge -- S5, a follow-up
slice, same "one dimensionality at a time" precedent this slice itself
followed.
