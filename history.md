# PROJECT HISTORY -- handoff for the next session

Read this + `CLAUDE.md` + `ARCHITECTURE.md` + `SENTAURUS-PARITY-PLAN.md`
before doing anything.

**What this file is.** A compacted record of what was built, what broke,
and what is still open -- kept at the level a new session needs to avoid
re-deriving decisions or re-making mistakes. It is deliberately NOT a
per-session diary; it was one, for 4,065 lines, and the duplication was
costing more than it carried. The full narrative of every session
remains in `git log` and in the per-milestone plan documents.

**Where the detail lives.** Each milestone below names its plan document.
Those documents are the authority on gates, formulas and honest limits;
this file only carries what a reader needs *before* opening one.

> **Caveat, 2026-09-09:** 13 plan documents (`M14`-`M22`,
> `3D-VISUALIZATION-PLAN.md`, `GUI-IMPROVEMENT-PLAN.md`,
> `M21-PHASE3-MESHING-PLAN.md`, and a session transcript) are currently
> **deleted from the working tree** and exist only in `HEAD`. Until they
> are restored (`git checkout -- <path>`), the milestone entries below
> are the only in-tree record for those milestones. Restore them before
> relying on a "see the plan doc" pointer.

---

## AIM

Evolve PyTCAD into a Semiconductor Workbench: an open, modular,
understandable learning+research TCAD environment (DEVSIM/Silvaco/
Sentaurus class). REAL physics only -- every educational surface backed
by actual computation. Never fake, never mock, never weaken tests.

---

## CURRENT STATE (2026-09-11)

**Suite, run both ways per CLAUDE.md:**

| run | result |
|---|---|
| fast, compiled kernels (`PYTCAD_ACCEL=1`) | 1674 passed, 5 skipped, 1 xfailed, 39 warnings |
| fast, pure Python (`PYTCAD_ACCEL=0`) | 1666 passed, 13 skipped, 1 xfailed, 39 warnings |

(+21 for M33-S5's gate file (`tests/test_m33_s5_3d_and_unstructured_
interface.py`, `M33-S5-PLAN.md`), landed after the 1653/1645 figures
below. Those were +16 for M33-S4's gate file
(`tests/test_m33_s4_2d_interface.py`, `M33-S4-PLAN.md`), landed after
the 1637/1629 figures below that. Those were +13 for M38 Phase 4's gate
files (`M38-PHASE4-PLAN.md`), landed after the 1624/1616 figures below
that. Those were: the 2026-09-09 figures were 1444/1436 and the
pre-M38 figures were 1548/1556; +33 for M38's gate file, then +19 for
P5-1 Phase A-2's minus 5 from narrowing Phase D's parameterization.
Everything before that: M32's 19 gates, P4b's 25, 6 benchmark/harness
gates, P5-0's 18 and P5-1's 45 across phases B/C/D.)

**The slow battery and `test_accel_parity.py` were finally re-run on
2026-09-10**, both ways, for the first time since P4 -- and the
`PYTCAD_ACCEL=0` half found a real skip-guard bug (see the 2026-09-10
entry below and the first GOTCHAS item). After the fix:

| slow battery | result |
|---|---|
| `PYTCAD_ACCEL=1` | 26 passed, 0 failed |
| `PYTCAD_ACCEL=0` | 20 passed, 6 skipped (the compiled-path throughput floors) |

`tests/test_accel_parity.py` on its own: 55 passed.

The 8-test gap between the two fast runs is exactly the PETSc
backend-vs-backend gates, which need both backends present.

**The single xfail is M14 G-A** (Lombardi phonon constants `B_n`/`B_p`,
blocked on a paywalled 1988 paper -- see the M14 entry). There are no
failures anywhere.

**Working tree is UNCOMMITTED.** Nothing has been pushed. It also
carries ONE openly-failing test on purpose -- see the M34-S1 entry
immediately below (M12-S2 dirty-tree precedent: fine to leave dirty
with a red gate and a precise handoff note, not fine to hide it).

### 2026-09-11 -- M34-S1 ATTEMPTED, STOPPED, NOT SIGNED OFF: nonlocal path BTBT in Device1D

Full record: `pytcad/M34-S1-PLAN.md` section 8 (read that section
first if resuming). Do NOT treat this as landed or read past this
paragraph as evidence it is close to landing -- the explicit
instruction that ended this work was "stop, document, do not sign off
M34-S1, and carry the 0.74% FD-Jacobian failure as the explicit
blocker."

Attempted the nonlocal (path-integral) Kane BTBT model from M34's
Tier-3 scope, scoped to Device1D homojunctions only (S1). Grounded in
a verified, actually-read (not paraphrased) open-access reference:
Esseni et al., Semicond. Sci. Technol. 32, 083005 (2017),
doi:10.1088/1361-6641/aa6fca, section 2.1. `Models(btbt_nonlocal=
False)` (default) is bit-identical to the plain solver (all six
`tests/goldens/m13/*.npz` md5-identical throughout this work);
`Models(btbt_nonlocal=True)` is wired end-to-end in `pytcad/device.py`
and `pytcad/btbt.py`, converges on a real reverse-biased diode, and
produces a genuine, non-negligible physical effect (confirmed
directly, pinned as a regression test).

Real bugs found and fixed along the way (not hypothetical, each
confirmed by measurement): (1) a mistranscribed exponent constant in
the first-principles uniform-field closed form (`sqrt(2)` should have
been `2`), found by re-reading the primary source's equation image at
high resolution rather than trusting an earlier text-only fetch; (2) a
double-counted factor of elementary charge in the nonlocal prefactor,
found via an independent from-scratch re-derivation; (3) two
"kappa-floor" bugs (one in the Jacobian, one in the value computation
itself) where a real device's long near-flat mesh regions put many
interior nodes within float precision of a WKB turning point, driving
`1/kappa^2` to blow up or underflow -- fixed with a physically-
motivated floor that excludes near-turning-point edges from the
quadrature/derivative entirely.

**NOT resolved, and the reason this is not signed off:** the nonlocal
model's own uniform-field limit converges to exactly `pi` times (not
equal to) the first-principles closed form it should reduce to -- a
plausible but UNPROVEN small-k_perp-expansion artifact, carried as a
documented caveat, not divided out. More importantly, an adversarial
FD-Jacobian probe (run because CLAUDE.md requires FD-Jacobian-first,
not because it was scripted) shows a 0.74% worst-case mismatch against
this project's usual 5e-5 house tolerance -- pinned into
`tests/test_m34_s1_nonlocal_btbt.py::test_g4_fd_jacobian`, which is
LEFT OPENLY FAILING ON PURPOSE (not xfail'd -- this is an internal gap
to fix, not an external blocker like M14 G-A's paywall). Leading
hypothesis (unproven): the same kappa-floor fix may be silently
dropping a small FD-visible sensitivity near the floor. See the plan
doc's section 8 "Other NOT-yet-ruled-out candidates" for what else has
NOT been checked.

Next session resuming this: read `M34-S1-PLAN.md` section 8 in full
before touching `device.py` again; do not loosen the 5e-5 tolerance to
make the red test pass.

### 2026-09-11 -- M33-S5 LANDED: chi-aware band alignment ported to Device3D and unstructured_dd.py -- M33 FULLY DONE

Plan: `pytcad/M33-S5-PLAN.md` (written before implementation, per the
amendment mechanism). `M33-INTERFACE-PLAN.md` section 8 named this
port "the single biggest remaining piece of M33" once S4 landed; this
slice closes it, so M33 (S1-S5) is now fully landed.

Scope: **Device3D (structured)** and **`unstructured_dd.py`'s
standalone `solve_bias`** (the 2D unstructured coupled DD core).
`unstructured_dd3d.py` was deliberately excluded -- it has no
`materials_per_node`/`dlnnie` heterojunction mechanism of any kind to
extend, so adding one would be new-feature work, not a port of an
existing one.

**Device3D matched S4's derivation exactly, one more axis.**
`chi_arr`/`band_shift` built on the `(Nz,Ny,Nx)` grid, referenced to
node `(0,0,0)`; `ds_x`/`ds_y`/`ds_z` added with the SAME sign to all
six SG deltas (unlike `dlnnie`'s opposite carrier signs);
`_bc_contact_values`/`_bulk_psi_guess`/both GateBC Robin terms get
`-band_shift`. A pre-existing gap was also closed in passing:
Device3D never checked `Models.thermionic` at all (silently ignoring
it) -- it now refuses with `NotImplementedError`, matching the
Device1D/2D convention. 16 gates (mirroring S4's own G1-G7 shapes)
all green on first run; `tests/goldens/m13/*.npz` (all six files,
including the one Device3D golden `resistor3d_eq.npz`) came back
md5-IDENTICAL to the pre-edit baseline.

**`unstructured_dd.py` gained a new `band_offset` kwarg** ("nie"
default / "affinity"), since this module has no `Models` object to
hang the flag on. `_residual_jacobian` gained a `ds` parameter (verified
directly against a synthetic 4-node/3-edge probe before touching the
Newton loop: `Jn`/`Jp` responded correctly to a nonzero `ds`); contact
`psi0` and the cold-start guess get `-band_shift`, same reasoning as
every other core. Bit-identity off-path confirmed (default/explicit
`"nie"` bit-identical to each other and to the pre-existing call
signature; homojunction bit-identical between gauges) and by an
FD-Jacobian on the interface edges.

**One genuine, investigated (not assumed) physics finding changed two
of the originally-planned empirical gates.** The naive port of
Device2D/3D's own "isotype junction current is maximised at zero
chi-offset" gate FAILED here -- not a near-miss, the terminal current
agreed across a chi sweep from 3.85 to 6.05 eV to every printed digit.
Root cause, found by direct investigation rather than guessed:
`unstructured_dd.py` has no separate equilibrium-only residual (no
analytic `n = nie*exp(psi_c)` carrier slaving the way Device1D/2D/3D's
`_residual_jacobian_poisson` provides) -- `solve_bias` always solves
the fully-coupled system with `n`, `p` as free unknowns, even at
`bias={}`. For a UNIFORMLY doped isotype junction, `n=C, p~0` satisfies
Poisson pointwise for ANY psi, and the SG Bernoulli identity
`B(x)-B(-x)=x` then makes `Jn` EXACTLY LINEAR in `psi+band_shift` when
`n` is uniform; since the contact fix makes that shifted variable equal
the gauge-free value at BOTH contacts, the terminal current is
PROVABLY gauge-invariant for this geometry -- an exact identity, not a
numerical coincidence. Confirmed directly that Device2D's own isotype
gate avoids this because its `solve_equilibrium` slaves carriers
analytically (a real interface spike in `n`, measured: range 0.45-1.59
vs. this module's flat 1.0 for the nominally same setup) before
`solve_bias` ever runs. The isotype gate now asserts this bit-identity
directly (the correct gate for this module's actual mathematics); the
"pn direction is physical" gate was dropped rather than kept with a
fudged tolerance, since the measured effect there was at Newton's own
convergence floor -- "chi genuinely moves psi" (`>1e-3`, real) remains
this module's G2 evidence that the term is live.

Suite green both ways: `PYTCAD_ACCEL=1` 1674 passed/5 skipped/1
xfailed (573.87s), `PYTCAD_ACCEL=0` 1666 passed/13 skipped/1 xfailed
(572.54s), 39 warnings and zero failures in both -- the pre-S5
baselines (1653/1645) plus exactly these 21 gates.

**M33 (S1-S5) is now fully landed.** No open piece remains on this
milestone line; M34 is next.

### 2026-09-10/11 -- M33-S4 LANDED: chi-aware band alignment ported to Device2D

Plan: `pytcad/M33-S4-PLAN.md` (written before implementation, per the
amendment mechanism). `M33-INTERFACE-PLAN.md` section 8 named the
2D/3D port "the single biggest remaining piece of M33"; this slice does
Device2D only (structured path) -- Device3D and `unstructured_dd.py`
are deferred to a follow-up S5, the same "one dimensionality at a time"
precedent M18/M19/S1 already used.

**Straight port of S1's `band_shift` derivation, node-wise on the
`(Ny, Nx)` grid** (`s = ln(Nc/nie) + chi/VT`, referenced to node
`(0,0)`): `__init__` builds `chi_arr`/`band_shift`;
`_bc_contact_values`/`_bulk_psi_guess` subtract it from `psi0`/the
neutral guess; `_residual_jacobian_poisson`'s carrier slaving and BOTH
GateBC Robin terms (equilibrium's and the bias Jacobian's -- S1 had no
gate-BC analogue, so this is genuinely new territory) use
`psi + band_shift`; the SG edge deltas in `_residual_jacobian` gain
`ds_x`/`ds_y` with the SAME sign on both carriers (unlike `dlnnie`'s
opposite signs), constant under the Newton update so no Jacobian
column changes. Two refusals added, matching S1/S2's shape:
`Models.thermionic` on Device2D, and `band_offset="affinity"` with
`self.fd`.

**Physics reproduces the validated 1D shape.** Isotype (no p-n
built-in) junction current maximised at zero chi offset and falling
for BOTH signs (0.5135 A/cm at dchi=0 vs 0.4999 at +-0.20eV) -- the
sign-symmetric signature a symmetric-nie gauge cannot produce, same as
1D's 6.42e3/4.34e3/3.11e3 A/cm^2 finding. p-n junction current falls
monotonically as chi rises on the far side, ~1% per 0.1eV, matching 1D's
own magnitude and explanation (a rigid one-side shift is mostly
absorbed by the built-in potential re-equilibrating).

**Reconstruct-and-compare: all six `tests/goldens/m13/*.npz` files
came back md5-IDENTICAL** to the pre-edit baseline recorded in the
plan. Nothing moved, because `band_shift` is identically `np.zeros` on
the default `"nie"` gauge -- every new term an exact `+0.0`.

**One finding, deliberately not fixed here.** Device1D's own
`solve_equilibrium` stores its FINAL `self.n`/`self.p` as
`nie*exp(psi)` with no `band_shift`, even though the SAME method's
Newton loop uses `psi_c = psi + band_shift` mid-iteration -- an
asymmetry confirmed by reading `device.py` directly while porting the
pattern to 2D. Untested by any M33 gate (G1/G2 read `psi`/`J` via
`solve_bias`, never the raw equilibrium snapshot), so no gated
behavior is wrong -- but Device1D's post-`solve_equilibrium()` `.n`/
`.p` under `band_offset="affinity"` on a heterojunction are not what
the milestone's own derivation says they should be. This Device2D
port uses the mathematically correct form for its own equivalent
assignment rather than replicating the 1D asymmetry; fixing 1D's own
copy is a separate one-line change needing its own sign-off (frozen
core) and is not folded into this slice. See `M33-S4-PLAN.md` section 4.

16 new gates in `tests/test_m33_s4_2d_interface.py` (G1 equilibrium
detailed balance per carrier/both edge axes; G2 chi moves the solution,
both junction types; G3 FD-Jacobian on the interface edges
SPECIFICALLY, not a random sample; G4 bit-identity off-path; G5 the
new GateBC-Robin-term check S1 had no analogue for; G6/G7 the two
refusals). Suite green both ways: `PYTCAD_ACCEL=1` 1653 passed/5
skipped/1 xfailed, `PYTCAD_ACCEL=0` 1645 passed/13 skipped/1 xfailed,
39 warnings and zero failures in both -- the pre-S4 baselines
(1637/1629) plus exactly these 16 gates. `ARCHITECTURE.md`'s M33 entry
and 4c.3 status line updated (S1-S4 landed, S5 open).

### 2026-09-10 -- M38 PHASE 4 LANDED: compact-model GUI panel + deck statement

Plan: `pytcad/M38-PHASE4-PLAN.md` (written before implementation --
M38 Phases 1-3 named this phase but left it unscoped). Closes the last
open item on M38's own list.

Three pieces, no frozen-core edit:

* **`gui/services/compact_runner.py`**, a new JobRunner subprocess
  module (same `RESULT_PATH=`/`.tmp.json` contract as
  `process_runner.py`, not the npz/ResultStore one -- a fitted
  parameter set is not sweep/mesh data). Builds a REAL `Device1D` p-n
  diode or `Device2D` n-MOSFET directly from scalar geometry, sweeps
  it, and fits `workbench.compact.extract_diode`/`extract_mosfet1`
  against the result -- the same construction
  `tests/test_m38_compact_model.py`'s own G1-TCAD/G2-TCAD gates use.
* **`gui/controllers/compact_model_controller.py`** +
  **`gui/qml/panels/CompactModelPanel.qml`**, a new "Compact Model" tab
  (14th in `Main.qml`'s `workbenchTabs`) that drives the runner end to
  end and displays the extracted parameters plus the emitted SPICE
  `.MODEL` card.
* **`workbench/workflow.py`** gained a PARSE-ONLY `EXTRACT
  model=diode|mosfet1 scale=<value>` deck statement, stored on
  `DeckRun.extract`. Deliberately NOT wired into
  `batch.py`/`study_manifest.py` execution -- that needs its own
  reference-curve convention and is a separate, larger decision, named
  as such in the plan so nobody assumes a deck with an EXTRACT line
  drives batch extraction yet.

Two findings from the hard-debug pass:

1. **`build_mosfet`'s own default junction sharpness doesn't reproduce
   a clean Id-Vg/Id-Vd family.** The runner's first cut used
   `build_mosfet`'s own `sigma_y=sigma_lat=Lg/4` default and
   `extract_mosfet1` refused the result outright (`G2-REFUSE`, an
   apparent ~9.7 V overdrive). `test_m38_compact_model.py`'s own
   validated fixture uses much sharper junctions
   (`sigma_y=sigma_lat=0.05e-4` cm, `nx=48, ny=28`); the runner's
   defaults now match that fixture exactly rather than guessing.
2. **`Property(object, notify=...)` returning a Python dict/None
   handed QML a stale, effectively-empty value on every read**,
   confirmed by instrumenting the binding directly
   (`typeof r === "object"`, `!r === false`, `r.kind === undefined` --
   even on the evaluation after a real, successful extraction). Root
   cause not fully isolated (a PySide6 QVariant-marshalling quirk on
   this environment, not reproduced against a minimal case); worked
   around by exposing the manifest as a JSON-encoded `Property(str)`
   (`resultJson`) and parsing it QML-side with `JSON.parse`, which
   is unaffected. See `M38-PHASE4-PLAN.md` section 4 -- a future
   `Property(object)` returning a Python dict on this stack should be
   treated as suspect until proven otherwise.

Also caught by the full-suite run (not by this phase's own new
tests): `gui/tests/test_shell_icons.py`'s `EXPECTED_TAB_COUNT` is a
hardcoded literal every new sidebar tab must bump (13 -> 14).

13 new gates (3 `gui/tests/test_compact_runner.py`, 3
`gui/tests/test_compact_model_panel.py`, 7
`tests/test_m38_phase4_deck.py`). Suite green both ways: `PYTCAD_ACCEL=0`
1629 passed/13 skipped/1 xfailed, `PYTCAD_ACCEL=1` 1637 passed/5
skipped/1 xfailed, 39 warnings and zero failures in both -- the
pre-Phase-4 baselines (1616/1624) plus exactly these 13 gates.
`ARCHITECTURE.md`'s M38 entry and 4c.3 status line updated to LANDED
(all 4 phases).

### 2026-09-10 -- M33 S1/S2/S3 LANDED: heterojunction affinity + thermionic emission

Plan, every number, and the handoff list: `pytcad/M33-INTERFACE-PLAN.md`
(section 7 results, section 8 what is left).

**M33 turned out to be smaller than the roadmap says AND to contain
something bigger than its own scope.** Two of its three items were
already done -- M14 landed S_n/S_p surface recombination AND D_it -- so
only the heterojunction item remained. Investigating that found this:

**Device1D's heterojunction transport ignored electron affinity
entirely.** Verified by measurement, not by reading: two devices
identical except for a STEP in chi at the junction gave
`max|dpsi| = 0.000e+00` and `J/J_ref = 1.000000` for steps of -0.20,
-0.50 and +0.50 eV. Exactly zero, bit-for-bit, for a half-eV
conduction-band step. Cause: transport is parameterised by `nie` alone,
and `ni = sqrt(Nc*Nv)*exp(-Eg/2kT)` contains no chi. `chi_arr` was
built in `__init__` and read by exactly one function --
`band_diagram()`, a post-processing accessor. `device2d.py`,
`device3d.py` and `unstructured_dd.py` never mention chi at all.
Consequences: the offset actually solved was a SYMMETRIC dEg split (the
real AlGaAs/GaAs split is ~62:38); `device.py`'s own comment claiming
"chi/Eg enter the currents through position-dependent nie" was false
for chi; and `test_hemt_band_step_at_interface` gated a 0.20 eV step
measured THROUGH `band_diagram()`, i.e. a quantity the solver never
used. That test had already been caught once as a false negative
(wrong diff axis, fixed 2026-08-28); this deeper problem survived it.

TE was therefore built on a prerequisite, not in parallel: thermionic
emission's entire content is the flux limit imposed by dEc.

**S1 -- the affinity gauge collapses to ONE per-node shift.**
`s = ln(Nc/nie) + chi/VT`, giving `n = nie*exp(psi+s)`,
`p = nie*exp(-(psi+s))` -- the legacy gauge with `psi -> psi+s` in the
carrier law and `psi` alone in the Poisson flux. So `n*p = nie^2`
identically (mass action is gauge-free, nothing downstream changes),
and BOTH carriers take the SAME sign of correction, unlike M11-S3's
opposite `ln(nie)` factors -- a rigid band shift moves Ec and Ev
together, a gap change moves them apart. Derived two independent ways
which agree because `ln_gn + ln_gp == Eg/kT` identically. `s` is
referenced to node 0, so it is identically zero for a homojunction and
the legacy path is bit-identical BY CONSTRUCTION (`+ 0.0` exactly),
not by tolerance. Behind `Models(band_offset="nie"|"affinity")`,
default legacy.

**S2 -- thermionic emission**, `Models(thermionic=True)`, requiring the
affinity gauge. Flux derived FROM detailed balance, not quoted, which
is what fixes the Nc factor; a single emission velocity is used because
the two-velocity form is only detailed-balanced when A*1 == A*2.
Written into the SAME five slots the SG flux uses, so the whole
Jacobian assembly below -- including the M15 impact coupling -- is
untouched. TE -> DD as the velocity grows (0.976 -> 1.0032) and cuts
current at the real velocity, more so as the barrier deepens.

**Physics confirmed in two independent configurations.** Forward-biased
p-n diode: J falls monotonically with chi on the n-side, ~1% per
0.1 eV -- small and CORRECT, because a rigid shift of both edges on one
side is largely absorbed by the built-in potential re-equilibrating.
Isotype n-N junction (no p-n built-in to absorb it): J is MAXIMISED at
zero offset and falls for BOTH signs, 6.42e3 -> 4.34e3 and 3.11e3, a
factor ~2. That sign-symmetric shape is the signature of a real band
barrier and is what the legacy gauge cannot produce at all.

**Reconstruct-and-compare: all six m13 goldens md5-IDENTICAL** to the
baseline recorded in the plan before the first edit, after S1 and again
after S2, with all 33 m13 tests green including the three hardcoded
digests. Nothing moved, because on the default path every new term is
an exact `+ 0.0`.

Four things worth carrying forward:

1. **An adversarial probe caught a VACUOUS gate of my own.** G1 first
   normalised the equilibrium residual by the device's own forward
   current. Injecting a deliberate sign error into the hole delta moved
   zero-bias |Jp| from 3.2e-10 to 1.354e-01 -- NINE ORDERS -- but the
   forward current rose to 1.1e+03 too, so the RATIO came out 1.75e-07,
   BETTER than the correct code. The gate now uses an absolute floor
   justified by measuring the legacy homojunction's Newton floor
   (1.09e-9). Normalising by a quantity the bug also corrupts is a
   general trap, not a one-off.
2. **A silent, syntactically-valid regression.** Inserting a refusal at
   the wrong indent CLOSED the affinity branch, left `s = ...` as dead
   code after a `raise`, and rebound the `else` -- so `band_shift`
   became all-zeros and S1 reverted entirely, while still importing
   cleanly. Caught on the next test run (every chi giving an identical
   J), not by any import or lint.
3. **A latent defect in my own S1**: `_ii_compute_gs_frozen` recomputes
   the SG deltas independently of `_residual_jacobian`, so it needed
   the same shift or `affinity + impact` would have driven impact
   ionization off nie-gauge currents. Fixed. If you add an edge term,
   grep for OTHER places that rebuild the same quantity.
4. **`emission_velocity` is good to a factor ~2 on silicon, knowingly.**
   It derives m_DOS from the material's own Nc; a tabulated Richardson
   A* gives 1.92x more, because A* is set by the Richardson mass and
   Si's six-valley band separates the two (Nc -> 1.09 m0, A*=252 ->
   2.1 m0). Both are pinned by a gate. The A* table is also keyed on
   short names ("Si") that never match `Semiconductor.name`
   ("Silicon"), so `richardson_a_star(mat.name, ...)` KeyErrors on
   every real material object -- latent today because every caller
   passes the literal string.

Suite green both ways after all three slices: `PYTCAD_ACCEL=0` 1616
passed/13 skipped/1 xfailed, `PYTCAD_ACCEL=1` 1624 passed/5 skipped/1
xfailed, 39 warnings and zero failures in both -- the pre-M33 baselines
(1592/1600) plus exactly M33's 24 gates. All six m13 goldens re-checked
md5-identical in that same run.

**NOT DONE, and not claimed:** 2D/3D stay in the legacy gauge (a
straight port of `band_shift`, and the single biggest remaining piece);
G-7, the absolute published benchmark, was never attempted -- section 5
flagged it as the milestone's real risk before starting and that
judgement stands, so all seven green gates are limit/consistency gates
and none pins an absolute current against literature.

### 2026-09-10 -- M31 P5-1 PHASE A-2: all 8 reachable solver-selection cells measured

Plan and every number: `pytcad/M31-P5-1-SOLVER-SELECTION-PLAN.md`,
"Phase A-2". Phase E had blocked E-auto on exactly one thing: Phase A
produced evidence for THREE `(dim, unstructured, coupled)` cells, so
`linsolve.select_auto` refused every other one by name. Phase A-2
measured the rest. `_AUTO_EVIDENCE` went from 3 entries to 8 -- every
cell a caller can actually reach through `auto`.

**No default moved.** `NewtonOptions.linsolve` still defaults to
`"direct"`; adding entries changes only what `auto` RESOLVES TO, so no
existing caller's behaviour moves and no golden can shift.
`test_a2_no_default_moved` is the gate that makes "Phase A-2 did not
quietly take E-auto" checkable. E-auto remains a separate proposal.

**The headline is that Phase A's own summary was wrong.** Three cells
suggested "3D favours iterative, 1D/2D favour direct". With eight, the
discriminator is COUPLING, not dimension:
  * SCALAR (one-unknown-per-node Poisson) systems favour iterative once
    big enough to amortise setup -- INCLUDING IN 2D. U2DP measures 12x
    at 11,341 DOF. B3 and B8 both being COUPLED is what made 2D look
    uniformly direct.
  * COUPLED psi/n/p systems favour direct in 1D and 2D and iterative
    only in 3D. B2 is the extreme: six of seven iterative configs do
    not converge on a 1D coupled Jacobian at all, and the survivor is
    ~300x slower than direct. B3 stays direct even at 72,912 DOF.
  * SIZE cuts across both. U3DP is 4.0x FASTER with petsc at 2,488 DOF
    and 24x SLOWER at 963 -- the first `min_dof` in either phase set by
    a measured CROSSOVER rather than by "smallest size tried".
A naive "use petsc in 3D" rule would have been wrong for small 3D
meshes and would have missed a 12x win in 2D. Same lesson as the M22
MPI-Schwarz split-axis picker, in a new place.

Largest new win: **S3D (3D structured coupled bias, `device3d.py:1015`)
44.56s -> 1.60s at 27,783 DOF, 27.9x**, and the ABSOLUTE saving grows
with size (1.3s at 6,591 DOF, 43s at 27,783) -- not the
share-rises-because-the-rest-got-faster trap that closed M31 P5.

**One entry was decided by dependency, not by the stopwatch.** For
(3, False, True) `gmres/block_jacobi` (1.60s) and `petsc` (1.67s) tie
within noise. The entry says `gmres`: petsc is an OPTIONAL dependency
`select_auto` cannot see, so on a checkout without it every Newton
iterate would pay a failed attempt PLUS a direct solve. `gmres` with
NewtonOptions' defaults is pure scipy and is exactly the measured
configuration (`_build_preconditioner` routes a non-None `block_size`
to node block-Jacobi before ILU/AMG, confirmed by reading it). U2DP is
the contrast -- petsc there is 4x better than the best scipy option,
not tied, so it earns its dependency.

**Three methodology defects found and fixed before any number was
recorded** (the reason these numbers are trustworthy and the first
run's were not):
1. **Forcing `block_size=3` onto a SCALAR cell measures a
   preconditioner no caller can build.**
   `_build_block_jacobi_preconditioner` only refuses when
   `n % block_size != 0`, so a scalar system whose node count divides
   by 3 gets 3x3 "node blocks" carved from three UNRELATED rows --
   silently. `device.py`'s own `NewtonOptions.block_size` comment says
   this. Phase A-2 therefore builds each case with REAL
   `NewtonOptions` and lets the core decide what to pass; the patch
   only RECORDS. Phase A's forcing methodology is left untouched since
   its numbers are published. Validation that it worked: on U3DP the
   three scipy "preconditioner variants" report IDENTICAL times,
   because the scalar call site passes neither `block_size` nor
   `precond` and they collapse to one call.
2. **`Device1D`/`Device2D.solve_bias`'s DIRECT branch calls `spsolve`
   outright**, not `linsolve.solve_linear` -- so a sweep patched only
   at `solve_linear` recorded ZERO calls and reported the baseline as
   FREE. `instrument.py` already carried this same patch list with the
   same warning. `device3d.py` by contrast DOES route direct through
   `solve_linear`; the cores genuinely differ.
3. **A wrong claim in Phase A's own harness comment, disproved by
   measurement.** `CASE_MODULES` said B9's `solve_bias3d` "calls its
   own equilibrium sub-solve first". It does not --
   `solve_poisson_equilibrium3d` is a separate PUBLIC entry point and
   `solve_bias3d` cold-starts from an analytic Boltzmann guess. Caught
   by the new `IterRecord.dof` field: B9's whole sweep came back
   `dof=[2889]` with no 963-row scalar solve anywhere. Without it,
   Phase A-2 would have recorded B9's COUPLED numbers as evidence for
   a cell they never touched. The scalar 3D cell needed its own
   fixture (`U3DP`).

**Seven stale comments across five core files** claimed "Phase A never
measured this, so auto always resolves to direct" -- every one false
the moment its entry landed. All updated. `device.py`'s now also
records that its deliberately-missing Phase C fallback stays safe ONLY
because dim=1 measured as direct, and that a future re-measurement
must add the fallback first. Phase D's
`test_unmeasured_combinations_refuse_to_direct` narrowed from 7
combinations to the 2 that remain genuinely unreachable
(`Device1D`/`Device2D.solve_equilibrium` hardcode `method="direct"` and
never read `opts.linsolve`, so no selection rule can reach them).
Phase D's bit-identity gate still passes -- now on evidence rather than
on absence, and it would have FAILED had 2D come out iterative, which
is why it was left in place rather than rewritten.

New gate file `tests/test_m31_p51_phase_a2.py` (19 gates). Suite green
both ways at the time it landed: `PYTCAD_ACCEL=0` 1592 passed/13
skipped/1 xfailed, `PYTCAD_ACCEL=1` 1600 passed/5 skipped/1 xfailed,
39 warnings and zero failures in both. (The CURRENT STATE table above
carries the later post-M33 totals.)

### 2026-09-10 -- THE OWED SLOW BATTERY, RUN BOTH WAYS, FOUND A REAL BUG

`tests/test_accel_parity.py` and the `-m slow` battery had not been run
since P4. Run both ways at last: `PYTCAD_ACCEL=1` 26 passed,
`PYTCAD_ACCEL=0` **6 failed**. The 6 were the absolute throughput
floors, and the cause was a SKIP GUARD TESTING THE WRONG THING -- see
the new entry at the top of GOTCHAS. Fixed with a `needs_active_accel`
mark; `ACCEL=0` now 6 skipped, `ACCEL=1` still 6 passed.

### 2026-09-10 -- M38 PHASES 1-3 LANDED (TCAD-to-SPICE extraction)

Plan and every measured number: `pytcad/M38-COMPACT-MODEL-PLAN.md`
(section 5 for results, 5b for the two real findings). Chosen as the
next milestone because `ARCHITECTURE.md` 4c.3's own cheapest-payoff
ordering reads `M32 -> M38 -> M33 -> M34` and M32 had just landed --
and because every ingredient already existed: `circuit.py`'s `Diode`
and `MOSFET1` are the models fitted INTO, `circuit.Circuit` is the
simulator the loop closes through, `calibration.py` supplied the
Nelder-Mead/finite-penalty shape, and `mosfet.build_mosfet` /
`Device1D.iv_sweep` supplied the reference curves.

**NO FROZEN-CORE EDIT.** Two new files only: `workbench/compact.py`
(616 lines) and `tests/test_m38_compact_model.py` (33 gates). In
particular `pytcad/mosfet.py` has an `id_vg_sweep` but no
`id_vd_sweep`; rather than amend a `pytcad/*.py` file under the M11-S3
mechanism for a bare `solve_bias` loop, the Id-Vd family driver lives
in the test and drives `Device2D` from outside, the pattern
`transient.py`/`continuation.py` established.

What it does: fits `circuit.Diode`'s (Is, N) and `circuit.MOSFET1`'s
(Vt0, kp*W_L, lambda) to a simulated I-V, emits a real SPICE `.MODEL`
card, reads it back, and re-simulates through `circuit.Circuit`'s own
MNA solver -- TCAD -> parameters -> netlist text -> parameters ->
circuit simulation -> back to the originating curve, with no external
SPICE and no network.

Headline measured numbers:

* **Real `Device1D` pn diode**: ideality **N = 1.0031**, log-space
  residual 1.57e-3. Independently corroborated -- `test_validation.py`
  already gates the SAME fixture's POINTWISE ideality to within 2% of
  1.0 above 0.3 V.
* **Real 2D `Device2D` MOSFET**: level-1 fit at **2.90% relative RMS**
  across 19 points spanning triode and saturation, with
  **Vt0 = 0.16883 V** against **0.16730 V** from the closed-form
  long-channel `Vfb + 2*phi_f + Qdep/Cox` built out of
  `moscap.flatband_voltage` and `materials.SILICON` -- **0.91%**, and
  the two share no code.

Two real findings from the hard-debug pass, both now permanent gates:

1. **`circuit.Circuit` shunts every node to ground through 1e-12 S**
   (its floating-node guard). Any terminal current below ~`1e-12 * V`
   amperes is dominated by it: a 1e-4 cm^2 diode at 0.25 V passes
   2.5e-14 A against 2.5e-13 A of guard leakage, a **10x** error that
   first read as a broken fit. The closed-loop gate now asserts a
   PREDICTION -- the only permitted discrepancy is exactly
   `MNA_LEAKAGE_G * V / I` -- so an error from any other cause still
   fails it even where the guard is large. `mna_resolvable()` exposes
   the floor at the API and one gate demonstrates it live.
2. **A pointwise-derivative ELR tangent is not noise-robust.** Taking
   the threshold tangent at the single `argmax(np.gradient(...))` point
   moved the extracted Vt0 by **0.6 V** under 5% multiplicative noise
   -- far enough to trip the extractor's own strong-inversion refusal
   on data it can actually handle. Now a least-squares fit over every
   point within 80% of peak gm: exact on a noiseless level-1 curve
   (gm is constant, so the plateau is the whole curve), and 2.6% / 2.0%
   / 2.7% on Vt0 / kp*W_L / lambda at 5% noise.

Honest limits, written into the plan and the module docstring BEFORE
implementation rather than discovered: `MOSFET1` has no subthreshold
conduction at all (Id is EXACTLY 0 below threshold), so the fit is
strong-inversion-only, REFUSES a window that crosses threshold, and
reports linear-space relative error -- never a log-space figure that
would imply subthreshold agreement the model cannot have. It also has
no body effect. And the three layers disagree on units (A/cm^2 vs A/cm
vs A), so every extractor takes its scaling factor as a REQUIRED
argument with no default.

Deliberately NOT claimed: any speedup from replacing `DeviceStamp`'s
two full `Device1D.solve_bias` calls per Newton iteration with a cheap
analytic element. It is real, but section 36 forbids a number that did
not come from a benchmark run; it earns a `benchmarks/cases.py` row or
it is not quoted.

Suite green BOTH ways after the change: `PYTCAD_ACCEL=0` 1581 passed /
10 skipped / 1 xfailed, `PYTCAD_ACCEL=1` 1589 passed / 2 skipped /
1 xfailed, 39 warnings and zero failures in both -- the pre-M38
baselines (1548/1556) plus exactly M38's 33 gates, warning count
unchanged.

### 2026-09-10 -- M31 P5-0 LANDED; P5 proper planned, not approved

**P5-0 landed** (`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 11 is the full
record, including the amendment record). Two Python-side changes to the
four unstructured Newton loops, no C++, no physics change:

* `dirichlet.stamp_dirichlet_rows` replaces the `J.tolil()` +
  LIL-row-assignment stamping -- **byte-identical** (indptr, indices AND
  data), **44.8x** faster on the step itself (115.4 ms -> 2.6 ms per
  Newton iteration at B8 full size).
* the update goes through `linsolve.solve_linear`, so
  `NewtonOptions.linsolve` -- and M22's Krylov methods and P3a/P3b's
  PETSc stack -- **reach these cores at all**. They called `spsolve`
  directly before and silently ignored the option.
* a second substitution rode along in the 3D loops (a gate's Robin
  coupling accumulated into a diagonal instead of stamped entry by entry
  through LIL) and is gated separately, including the shared-node
  wrap-around case.

Measured same-session A/B, full size: **B8 5.15 s -> 3.61 s (1.43x)**,
B9 7.96 s -> 7.56 s (1.05x -- its remainder was only 7%, the direct
solve is 91% of it). B8's non-assembly, non-solve remainder went 35% ->
2.7%. **All ten goldens byte-identical**, m13 digests unchanged; 18 new
gates in `tests/test_m31_p50_unstructured_linsolve.py`.

Two things worth carrying forward:

1. **P5-0 weakens the case for P5 proper rather than clearing the way.**
   The linear solve is now 92% of B8 full and 98% of B9 full; the C++
   assembler would be porting ~5%. The next experiment is
   `opts.linsolve="petsc"` on these cores -- now possible, and
   Python-side.
2. Routing through `solve_linear` broke M32's instrumentation (the cores
   `from .linsolve import solve_linear`, so patching
   `pytcad.linsolve.solve_linear` misses them). **The existing M32 gate
   caught it** -- `test_case_runs_and_reports_a_real_measurement`
   asserts `linsolve_calls > 0` -- before any number was quoted.

### 2026-09-10 -- M31 P5 planned, and its prerequisites landed

Written, not started, NOT APPROVED: `pytcad/M31-P5-ASSEMBLY-NEWTON-PLAN.md`.
Scope proposed there is the UNSTRUCTURED path only
(`unstructured_poisson.py`, `unstructured_dd.py`, `unstructured_dd3d.py`);
the structured cores stay Python. It needs the section-3 scope sign-off
and the section-8 amendment record before any core edit.

Landed this session (none of it touches the frozen core):

* **B8 and B9** -- 2D and 3D unstructured DD benchmark cases. Before
  them the code P5 targets had no dashboard row, so section 36 forbade
  any claim about it.
* **The profile P5 was waiting for**, and it is not encouraging for the
  C++ case: assembly is 3.5% of B8 full and **1.5%** of B9 full, and its
  share FALLS with problem size; the linear solve is 62-91%. The
  unstructured cores call `spsolve` directly and cannot reach P3a/P3b's
  PETSc stack at all. That created a new Python-side sub-phase (P5-0)
  which addresses ~90% of the runtime with no C++.
* **A tracemalloc defect in M32's harness**: the memory trace ran over
  the whole measured region, inflating wall time 1.19x on B3 but 4.05x
  on B8 -- worst exactly on the code P5 would be judged by. Timing and
  memory repeats are now separate. **Every M32 number published before
  2026-09-10 was inflated**; `BASELINE.md`/`FULL.md` are regenerated.
  Also fixed: `unstructured_dd3d` was missing from the `spsolve` patch
  list, and the unstructured module-level assemblers were not
  instrumented at all.
* **The impossible golden rule is gone.** "Goldens committed before the
  edit" cannot be satisfied (`.gitignore` excludes `*.npz`) and should
  not be -- a golden pins one machine's summation order. CLAUDE.md now
  specifies reconstruct-and-compare as four numbered steps; this file
  and ARCHITECTURE.md match, and `.gitignore` records why
  `tests/goldens/**` stays ignored.

**Environment (load-bearing, not a preference).** Run everything through
`conda run -n TCAD`. This machine's `base` anaconda env has an
ABI-mismatched Qt6 (`undefined symbol: _ZN14QObjectPrivateC2E16QtPrivate_6_11_0`)
that fails EVERY `gui/tests/*` QML test with "Main.qml failed to load",
independent of any code change -- confirmed by `git stash` reproducing
it on unmodified code. It fabricates ~90 GUI failures and has cost a
session already.

Cap workers at `-n 6` (not `-n auto`) and set `OPENBLAS_NUM_THREADS=1`:
numpy's BLAS otherwise spawns a thread pool PER xdist worker.

---

## OPEN ITEMS

0. **M31 P5-1 (linear-solver / preconditioner selection) is the
   recommended next milestone**, ahead of P5 proper --
   `pytcad/M31-P5-1-SOLVER-SELECTION-PLAN.md` -- **ALL FIVE PHASES (A-E)
   LANDED 2026-09-10.** Phase A's real per-solve numbers
   (not single-Jacobian extrapolations) moved the milestone's center of
   gravity: **B4 (3D structured equilibrium, Poisson-only) is the
   largest result in the whole study -- 179s direct -> 1.5-2.2s
   iterative, 82x-119x, every one of 9 Newton iterates converging with
   ZERO fallbacks needed.** B9 (3D unstructured) confirms the original
   10.6x petsc finding independently under a full Newton sequence. But
   **B8 (2D unstructured) turned out to have NO measured win**: the
   single-Jacobian sweep that motivated this milestone favored "ILU"
   (3-4 Krylov iterations), but the WHOLE-SOLVE number shows
   preconditioner SETUP cost (93% of every call, isolated and timed
   directly -- and it is `pyamg`'s AMG hierarchy construction on this
   machine, not literal `spilu`, since `_build_preconditioner` tries
   AMG first when installed) makes it slower than direct (8.41s vs
   3.43s) -- direct stays for B8, measured rather than assumed. A real
   methodology bug was caught and fixed along the way:
   scipy's `gmres`+`restart` treats `maxiter` as restart-cycle count
   (an effective ~100x larger budget than the same `maxiter` gives
   `bicgstab`/`petsc`), which had made two B8 configs look like near-
   total failures when they were actually iteration-starved; corrected
   in the plan and permanently documented in
   `benchmarks/preconditioners.py` (the new Phase A sweep script) so it
   isn't repeated. **Phase B landed same day**: `NewtonOptions` gained
   `precond`/`block_size` fields (defaults reproduce the old hardcoding
   exactly), threaded into the five coupled call sites that hardcoded
   `block_size=3` (`device.py`, `device2d.py`, `device3d.py`,
   `unstructured_dd.py`, `unstructured_dd3d.py`); both fields validated
   at construction (`ValueError` on an unknown `precond` or a
   nonsensical `block_size`, mirroring `Models.driving_force`'s
   existing refuse-don't-ignore pattern). Reconstruct-and-compare
   confirmed bit-identity: all 6 `tests/goldens/m13/*.npz` files came
   back md5-identical after the edit, including `frozen_meshes.npz`,
   which an over-eager `rm -f` deleted before regenerating (a real
   process mistake, not part of the plan) and had to be rebuilt from
   the `graded_mesh()`/`np.linspace()` conventions documented in
   `test_m13_goldens.py`'s own docstring -- the rebuild reproduced the
   original file byte-for-byte. New gate file
   `tests/test_m31_p51_phase_b.py` (22 gates). Suite green both ways
   (`PYTCAD_ACCEL=0`: 1503 passed/10 skipped/1 xfailed;
   `PYTCAD_ACCEL=1`: 1533 passed/2 skipped/1 xfailed; 39 warnings both,
   zero failures). **Phase C landed same day**: all four unstructured
   loops (`unstructured_poisson.solve_poisson_equilibrium`,
   `unstructured_dd.solve_bias`, and both loops in
   `unstructured_dd3d.py`) gained the identical try/except fallback
   shape the structured cores already used, plus a `linsolve_fallbacks`
   count in each returned dict (zero by default). Confirmed with
   `tests/test_m31_p51_phase_c.py` (6 gates): a 100%-forced fallback
   produces a result `np.array_equal` to the all-direct solve, for all
   four loops, and the fallback count is nonzero when it happens.
   **A real regression caught before it stuck**: Phase B's own test
   file originally forwarded a mismatched `block_size=7` to a genuinely
   REQUESTED iterative method, which made scipy's `gmres` actually
   grind through real (failing) iterations -- ballooning the combined
   P5-0/P5-1 test files from ~15s to over 600s. Fixed by having the spy
   record the request but always execute via `method="direct"`; full
   suite re-timed clean (`PYTCAD_ACCEL=0`: 1531/10/1 in 345.6s;
   `PYTCAD_ACCEL=1`: 1539/2/1 in 346.4s, 39 warnings both, zero
   failures -- matching the pre-Phase-C timing shape, not the
   regression). **Phases D and E landed same day, completing the
   plan.** `linsolve.select_auto(dim, unstructured, coupled, dof)`
   resolves `NewtonOptions.linsolve="auto"` from a 3-entry evidence
   table keyed on exactly what Phase A measured (B4 -> petsc >=4,913
   DOF, B9 -> petsc >=2,889 DOF, B8 -> direct, explicitly MEASURED not
   merely absent); every other `(dim, unstructured, coupled)` --
   notably ALL of 1D, every 2D/3D STRUCTURED coupled-bias
   configuration, and both scalar unstructured equilibrium paths --
   refuses to direct with a reason naming the absence (Gate D-3). Wired
   into all 9 call sites that dispatch on `opts.linsolve`; two
   (`Device1D`/`Device2D`'s `solve_equilibrium`) left untouched because
   they already hardcode `method="direct"` and never read
   `opts.linsolve` at all. `tests/test_m31_p51_phase_d.py` (17 gates)
   includes two real end-to-end checks beyond the lookup table: `auto`
   on a 5,832-DOF `Device3D` resolves to petsc and agrees with direct
   to `<=1e-14`; `auto` on a full-size B9-shaped 3D unstructured mesh
   resolves to petsc and agrees with direct to `<=1e-12`. Reconstruct-
   and-compare: all 6 `tests/goldens/m13/*.npz` md5-identical again --
   the default stays `"direct"` everywhere (**Phase E landed as
   E-opt-in**, requiring no new code beyond documenting the "auto"
   contract on `NewtonOptions.linsolve` itself; **E-auto -- changing
   the default -- was deliberately NOT taken**, per the plan's own
   written guardrail that it needs separate sign-off and more measured
   evidence than three cells currently cover).
1. **M31 P5** (the C++ assembler) has its own plan doc,
   `pytcad/M31-P5-ASSEMBLY-NEWTON-PLAN.md` -- **CLOSED 2026-09-10: P5-0
   landed, P5a-P5e STOPPED, not started** (below). The scope sign-off
   in its section 3 was never reached -- section 9's own pre-committed
   exit criterion fired first. The headline: the phase's own profile
   (section 6) said the assembler is 1.5-3.5% of a full-size
   unstructured solve. P5-0
   has since landed (section 11); after it the linear solve was 92-98%
   of these runtimes, which is what P5-1 above attacked -- P5-1 is now
   COMPLETE (all 5 phases), and **the decision is made: P5 STOPS after
   P5-0, per section 9's own pre-committed exit criterion, invoked
   2026-09-10 (section 12, measured through
   `benchmarks/p5_redecision.py` and the real M32 harness, not by
   hand)**. B8 full (auto picks direct, unchanged): assembly 5.45% of
   3.43s, no case. B9 full (auto picks petsc, 11x): assembly's SHARE
   rose to 16.3% of a 0.665s total (from 1.5% of 7.32s) while its
   ABSOLUTE cost stayed at ~109ms -- exactly the "percentage rises
   because the rest got faster" trap both plans warned against, now
   measured rather than predicted, and the absolute number (at most
   ~109ms saveable, realistically less) does not clear the bar against
   two engines' ongoing maintenance cost. P5a-P5e (the C++ assembler)
   are NOT started; `cases.py`'s `_b4`/`_b8`/`_b9` gained an optional
   `opts=` parameter for this measurement (default `None` reproduces
   the dashboard row exactly, confirmed unchanged by
   `tests/test_m32_benchmarks.py`). A related, out-of-scope finding: B4
   (structured 3D, not a P5-1 target) shows the same dynamic even more
   sharply -- assembly 29.5% of a 0.505s `auto`-resolved total -- worth
   a separate proposal if a structured C++ assembler is ever considered,
   not smuggled into this now-closed decision.

   **P5's closure propagated to `ARCHITECTURE.md`** (2026-09-10): the
   4c.3 spine STATUS line, the C++-gated milestone list (M36/M39
   flagged for re-scoping against the Python+PETSc stack P5-0/P5-1
   actually built, since the C++ assembler they depended on will not
   exist), and the adjoint-readiness section (M47 re-anchored to P4b's
   Python-path fix rather than a P5 acceptance gate that will never be
   evaluated) were all updated so a future reader does not plan against
   a P5 that stopped.

2. **P2/P3b/P4's hand-taken headline numbers -- RE-MEASURED 2026-09-10**
   through `benchmarks/p2_p3b_p4_remeasure.py` (M32-BENCHMARK-PLAN.md
   section 7's first open item, "doubly owed" after the tracemalloc
   fix), reusing `test_accel_parity.py`'s own fixture builders so this
   measures the exact thing the throughput-floor gates protect. Every
   number held up or exceeded the original: P2's 3 kernels (41x/25x/539x
   -> 43x/26x/560x), P3b's timing comparison (3.30ms/3.38ms ->
   3.31ms/3.38ms, same 399 iterations, confirms "no speedup expected"
   exactly), P4's 3 indicator kernels (835x/874x/123x ->
   1081x/939x/221x -- `indicator_log_density_tri` notably higher).
   `M31-CPP-ARCHITECTURE-PLAN.md`'s P2/P3b/P4 sections updated with both
   figures side by side. P4's two diffusion-loop kernels
   (`process.diffuse_numeric`, `ted.diffuse_with_defects`) needed a
   second script since wall-clock time for a timestep loop isn't a
   throughput rate -- **also RE-MEASURED 2026-09-10**,
   `benchmarks/p4_diffusion_remeasure.py`, same n=4000/t_s=1800s shape
   as the original claim, reusing `test_accel_parity.py`'s
   `_diffusion_case` implant profile. Speedup held up across two
   repeats: 3.3-3.7x (orig 3.3x) for `diffuse_numeric`, 4.4-4.5x (orig
   4.1x) for `diffuse_with_defects`. Absolute seconds are not claimed
   comparable to the original run (13.6-14.2s vs. the original's 24.6s)
   since the original's exact TED/OED enhancement parameters were never
   recorded -- only the speedup ratio is checkable against the prior
   claim, and it is. `tests/goldens/m14/` (an empty, untracked,
   unreferenced directory -- confirmed via grep across `tests/` and
   `pytcad/`) was also removed the same session as a small cleanup item.
3. **M14 G-A** -- blocked on external material, not effort. Two sessions
   searched (COMSOL docs, Sentaurus/Silvaco manuals, Prophet, TU Wien,
   CERN, ResearchGate, academia.edu, web.archive.org); Unpaywall
   confirms DOI 10.1109/43.9186 has zero open-access copies. Needs
   either institutional access to Lombardi 1988 or a Sentaurus/Silvaco
   manual PDF. Switching to the Darwish (1997) model that DEVSIM uses is
   a real option but a bigger decision than filling in a constant.
4. **The 13 deleted plan documents** (see the caveat at the top).
   **`Architecture_Master_Plan.md` joined them on 2026-09-10**, and
   `AGENTS.md` was renamed to `CLAUDE.md` the same day -- both at the
   user's direction. The master plan is cited by section number in
   CLAUDE.md, ARCHITECTURE.md, `M32-BENCHMARK-PLAN.md`, the P5 plan and
   several test/benchmark modules; those citations were LEFT IN PLACE
   because the sections are still the reasoning behind live gates.
   CLAUDE.md's header says where to read one
   (`git show a117d03:Architecture_Master_Plan.md`). Treat a citation as
   a pointer into git history, not a broken link.
5. **M32-M40** are PROPOSED in `ARCHITECTURE.md` 4c.2, not decided --
   nothing is committed until each has its own plan doc and gates.
   EXCEPT M32 (landed) and **M38, now LANDED for all 4 phases**
   (`pytcad/M38-COMPACT-MODEL-PLAN.md` for Phases 1-3,
   `pytcad/M38-PHASE4-PLAN.md` for Phase 4, landed 2026-09-10 -- a
   compact-model GUI panel plus a parse-only `EXTRACT` deck statement,
   see that day's entry above). Still not done: BSIM-class models,
   temperature or geometry scaling, AC/C-V parameter extraction, PMOS
   in the GUI panel, and EXTRACT-driven batch/study execution.
6. **E-auto is now the obvious next proposal, and its blocker is
   gone.** M31 P5-1 Phase A-2 (2026-09-10) measured every one of the
   eight `select_auto` cells a caller can reach, which is exactly what
   Phase E said it was waiting for. Making `linsolve="auto"` the
   DEFAULT is still NOT taken and still needs its own sign-off: it is a
   behaviour change for every existing caller including the GUI and
   `examples/`, and the cells where `auto` now resolves to something
   other than direct (B4, S3D, B9, U2DP, U3DP) would stop being
   bit-identical to today. The prize is real -- B4 179s -> 1.5s, S3D
   44.6s -> 1.6s -- and no caller reaches it today without typing an
   option they will not discover.
7. **Housekeeping still owed:** the working tree remains fully
   UNCOMMITTED, and the slow battery plus `tests/test_accel_parity.py`
   have not been re-run since P4.
8. **M33 is now FULLY LANDED (S1-S5).** `M33-S5-PLAN.md`: the
   chi-aware band-alignment gauge ported to Device3D and
   `unstructured_dd.py`, 21 gates, suite green both ways, all
   `tests/goldens/m13/*.npz` md5-identical off-path (see the
   2026-09-11 entry above). No open piece remains on this milestone
   line; M34 is next per ARCHITECTURE.md 4c.3.

---

## HARD RULES (never break)

- `pytcad/pytcad` numerical core: changes ONLY under the M11-S3-style
  amendment mechanism (sign-off recorded in the plan file, golden
  baseline recorded before the edit and proved recoverable afterwards
  -- reconstruct-and-compare, see CLAUDE.md's hard rules; goldens are
  machine-specific and are never committed -- FD-Jacobian-first,
  bit-identity off-path).
- Layering: QML -> controllers -> services -> QProcess subprocess -> npz
  -> ResultStore -> canvas. Controllers/visualization never import
  `pytcad`.
- `DeviceSpec` stays the wire format. Subprocess isolation per run kept.
- Every slice: suite green with pre-existing tests UNCHANGED, adversarial
  probe pass BEFORE commit, optional deps stay optional.
- Gate-bearing milestones block their dependents until ALL gates are
  green. "Mostly green" is a hidden failure.
- A failing test is never commented out or skipped. A visible
  `pytest.xfail` with the reason in the body is the honest version of
  "not yet, and here is why."

## HOW WE WORK

Plan -> user approves -> TDD (tests red first) -> implement -> hard debug
(fuzz/probe the new code adversarially, fix, regression tests) -> commit
(user pushes). Honesty over polish: report blockers, document limits.

---

## GOTCHAS LEARNED THE HARD WAY

Consolidated from every session. These each cost real debugging time.

### Verification discipline

- **A skip guard must test the LEVER, not the CAPABILITY.**
  `tests/test_accel_parity.py` guarded the whole module on
  `_accel.HAVE_ACCEL` -- "is the compiled extension BUILT" -- which is
  an import-time constant. The actual lever is `_accel.use_accel()`,
  the per-call reader of `PYTCAD_ACCEL`. On a machine where the
  extension IS built, `PYTCAD_ACCEL=0 pytest -m slow` therefore timed
  the PURE-PYTHON path against absolute throughput floors calibrated
  on the C++ kernels, and "failed" by exactly the known Python-vs-C++
  ratio: `test_indicator_throughput_floor[curvature]` measured
  2.54e5 tri/s against its 5.0e7 floor, and 0.27M tri/s is the Python
  reference rate that test's OWN DOCSTRING records for that kernel.
  6 failures, one cause. Found 2026-09-10 the first time the slow
  battery was run both ways since P4 -- it had never been run under
  `PYTCAD_ACCEL=0` at all. Fixed with a separate `needs_active_accel`
  mark on the two absolute-floor tests (the parity tests proper set
  `PYTCAD_ACCEL` themselves via monkeypatch and are correctly guarded
  by the module-level mark). The mark short-circuits on `HAVE_ACCEL`
  first, because `use_accel()` deliberately RAISES when
  `PYTCAD_ACCEL=1` with no extension and that would become a
  collection error. Verified: `ACCEL=0` 6 skipped (was 6 failed),
  `ACCEL=1` 6 passed (unchanged).

- **A "COMPLETE, all gates green" status claim is not evidence.** It was
  wrong for M15 in an inherited tree, and M16/M20/M22-Schur all sat at
  "LANDED-PENDING-VERIFICATION" -- code and gates written, never once
  executed -- until a later session actually ran them and found real
  defects. Measure before trusting a status block, especially your own.
- **A formula that "reduces to the existing code at the default value"
  is not automatically a valid generalization.** If the reduction works
  by multiplying an already-satisfied residual by a constant, the
  parameter has no effect at ANY value. The tell is that it looks
  elegant (no branching needed). Always sweep a new parameter across
  several orders of magnitude and confirm the SOLUTION moves -- this
  caught the same class of bug twice in one session (D_it and S_n/S_p).
- **A test can be structurally incapable of failing.** T5's HEMT band
  step diffed `chi` along the axis it was constant on (always exactly
  0.0); M14's FD-Jacobian probes sampled random columns and never hit
  the handful of boundary columns where the bug was; a `if bv_solver is
  not None:` guard meant "BV not found" passed silently. Ask what the
  assertion would do if the physics were wrong.
- **Random full-matrix FD-Jacobian sampling misses boundary rows.**
  Probe the specific columns a change touches.

### Numerics

- **NaN fails every comparison**, so a `< MIN or > MAX` range guard lets
  it through silently. Check `np.isfinite` explicitly wherever a bound
  check is meant to reject bad input.
- **A lagged fixed-point loop that sources its next iterate from a
  quantity the current iterate already modified** can produce a RIGID,
  non-damping oscillation -- immune to under-relaxation at every damping
  factor -- and the capped result looks like ordinary finite data. When
  a warm-started outer loop won't converge under any damping, check
  whether its own just-updated state is feeding back into computing its
  next update before blaming the tolerance.
- **scipy's gmres default restart (20) can stall COMPLETELY** -- zero
  residual progress in 500 iterations -- on a stiff coupled Jacobian.
  Silent unless you check iteration counts.
- **`spilu` can raise "Factor is exactly singular" on a non-singular
  matrix**, purely because the default `drop_tol` is too aggressive for
  rows spanning many orders of magnitude (this codebase's scaled
  psi/n/p unknowns). A fallback tolerance chain is cheaper than
  re-diagnosing it each time.
- **`spsolve(A_csr, b)` and `spsolve(A_csr.tocsc(), b)` differ at
  ~1e-16.** SuperLU solves CSR natively via a format flag. Any
  bit-identity claim must not reformat the caller's matrix.
- The complete Fermi integral's Boltzmann-limit deviation is
  `e^eta/2^{3/2}` (exact Taylor series) -- set limit gates from the
  published math, not from round numbers.
- `mpmath`'s `mp.quad` on `[0, inf)` under-resolves the `t~eta` knee of
  the Fermi integral (5e-5 off at eta=40). Subdivide `[1, eta+20, inf]`.
  Audit your audit: scipy AND mpmath were both checked against the
  published Sommerfeld series.

### Arrays and shapes

- **A `meshgrid(indexing='ij')` array handed to something that reshapes
  to a different axis order is silent data corruption**, not a crash.
  numpy's flat `.reshape` only checks element count. With a doping array
  holding two distinct values the corruption is invisible under
  `print()` or `np.unique()` -- ~49% of nodes had the wrong value for
  their position and it only showed as spatial nonsense.
- `np.array(sorted({}), dtype=int)` has shape `(0,)`, not `(0, 2)`.
- numpy's `dtype=int` is C `long`: int64 on Linux, **int32 on Windows**.
  Pin any C boundary to int64 explicitly.

### Tooling

- **The bash tool's cwd RESETS between calls.** Always `cd` or pass
  absolute paths -- the single most common cause of lost work here.
- **`str.replace` patches SILENTLY no-op on stale strings.** Assert the
  replacement applied.
- **Writing a doc in two parts to the SAME path truncates it** -- the
  second write replaces the whole file.
- `np.polynomial.legendre.leggauss` is module-level (not
  `Legendre.leggauss`) in numpy 2.5.
- `familySweep.configureFamily`'s FIRST arg is the stepped contact NAME
  (a string), not a bool.
- `ViewportPanel.setViewMode` takes INTERNAL mode names ("series",
  "bands"), not display names ("Curves", "Bands").
- Qt's offscreen platform never incubates ListView/Repeater delegates
  without a real event loop -- call the controller method the delegate's
  signal handler would invoke.
- xhtml2pdf: `white-space:pre-wrap` on `<pre>` collapses newlines;
  `&sup6;` is not a real HTML entity and U+2076 is missing from the
  embedded font -- use `<sup>6</sup>`.

---

## MILESTONE LOG

Reverse chronological. Each entry: what landed, what broke and why, and
the honest limits.

### M31 -- C++ numerical engine (2026-09-09)

Plan: `pytcad/M31-CPP-ARCHITECTURE-PLAN.md`. Re-architecture toward C++
(numerical engine) + Python (API/workflows) + Qt (GUI) by progressive
extraction, **not** a rewrite. **P0, P1, P2, P2b, P3a, P3b and P4 have
landed; P5 is next.**

**The measurement that ordered the phases -- do not skip this.** The
premise "the numerics are Python, so port them for speed" is only partly
true here:

- Structured 3D assembly is **not** the bottleneck. A 24^3 equilibrium
  solve spends **98% of wall time in `_superlu.gssv`**; assembly is
  0.011 s of 0.494 s. Porting `device*.py`'s assembly buys ~2%.
- The direct-LU wall (3.0 s @ 8k nodes -> 51.8 s @ 27k -> 64k never
  completing) is **algorithmic, not linguistic**: the existing
  pure-Python node-block-Jacobi GMRES already does 68,921 nodes
  (206,763 unknowns) in 4.71 s.
- The genuine blocker was **unstructured mesh geometry**, at ~3.5k
  tets/s.

That is why P2 went first and P5 is last.

**The rule the whole migration rests on.** The extension is optional,
permanently. `pytcad/_accel.py` soft-imports `pytcad._core`; every
accelerated function keeps its pure-Python body as `_<name>_py`. Deleting
the `.so` must leave the full suite green (gate G-F). This is both the
undo button at every commit and what keeps an ORACLE alive to diff
against -- a port that deletes what it replaced cannot be checked.

**Gates every kernel clears:** G-A reference preservation
(`np.array_equal`, never `allclose`), G-B blast-radius (m13/m14 goldens
+ SHA-256 digests unmoved), G-C differential fuzz (identical exception
type AND message), G-D thread invariance, G-E absolute throughput floors,
G-F no-compiler fallback.

**P2 -- mesh/geom kernels.** `build_unstructured_stencil` 77k -> 3.16M
tri/s (41x); `build_unstructured_stencil3d` 48k -> 1.20M tet/s (25x);
`build_edge_flux_geometry3d` 3.7k -> 1.99M tet/s (**539x**). A
998,250-tet mesh builds its edge-flux geometry in 0.71 s against ~285 s
extrapolated. Bit-identity is achievable because the numpy primitives
involved were MEASURED to be plain scalar arithmetic at these sizes (no
BLAS dispatch) before any C++ was written -- see
`core/include/tcad/geom/simplex.hpp`'s preamble.

P1 removed `np.linalg.solve` from the geometry path for the same reason:
it routes to LAPACK `dgesv`, whose result depends on the BLAS build, so
C++ could not reproduce it. An unblocked `dgetf2` replication matched
numpy on only 72.6% of 20k random 3x3 systems. Replaced with a
fixed-order Cramer's rule, verified numerically neutral over 200k random
tetrahedra (worst equidistance violation 4.182e-10 vs 4.184e-10).

P1 also fixed a real latent bug: `DegenerateMeshError` was declared
**twice as two unrelated classes**, so an `except` on the 2D name
silently failed to catch the 3D module's error.

**P2b -- the winding-sensitivity defect.** P2 surfaced, and deliberately
did not fix, a defect in the REFERENCE: `_cot` divided by a *signed*
cross product while `tri_area` took `abs()`, so a clockwise-wound
non-obtuse triangle contributed NEGATIVE dual areas and the partition
identity failed by exactly 2x. Fixed on both paths at once (one line
each: `abs(cross)` / `std::fabs(cross)`).

The fix is right rather than a clamp because the angle at a vertex is
*undirected* -- it lies in (0, pi), so its sine is positive by
definition and the cotangent's sign belongs entirely to the dot product.
The signed cross was importing orientation into a quantity that has none.
`fabs` on a positive double is the identity, so counter-clockwise input
(every gmsh mesh, every golden) is bit-for-bit unchanged.

One subtlety that had to be got right in the gate: all six vertex
orderings agree, but only a REVERSAL is bit-exact. `_triangle_area2` is a
difference of two products; a reversal negates it exactly, a cyclic
rotation recomputes it from different coordinate differences and lands a
ulp away. That is unrelated to the defect. The test compares reversals
with `array_equal` and rotations at `rel=1e-14`.

**P3a/P3b -- `method="petsc"`.** P3a added it via petsc4py; P3b moved the
same KSP/PC configuration into `core/src/solver/petsc_ksp.cpp`. Both
backends are kept forever and reported in `info["backend"]`. They are
**bit-identical** (`np.array_equal`, not a tolerance) on random SPD
systems, on a real 399-iteration interleaved psi/n/p device Jacobian, and
with a nonzero initial guess -- achievable only because both call the
same `libpetsc.so`, which is why the acceptance test (true-residual
recomputation) and CSR canonicalization deliberately stayed in Python.

**P3b bought no speed** -- 3.30 ms vs 3.38 ms warm. The justification is
entirely architectural (a single engine is what makes distributed
`Mat`/`DMPlex` reachable in P7) and the plan says so rather than
implying a win.

P3a's `x0` was **silently ignored**: it seeded the solution vector but
never called `KSPSetInitialGuessNonzero`, and PETSc zeroes that vector at
the top of `KSPSolve`. Found and fixed on both paths.

PETSc is optional INSIDE the extension (`TCAD_WITH_PETSC=AUTO|ON|OFF`,
found via pkg-config), so a pip-only build still compiles and falls back
to petsc4py. conda-forge's PETSc is 32-bit `PetscInt` -- a real ceiling,
reported by `_accel.status()`.

**P4 -- process/particle kernels.** Five kernels in
`core/src/process/`: three per-triangle AMR indicators
(`indicator_curvature_tri` 0.27 -> 227 Mtri/s, `debye_ratio_tri` 0.28 ->
242, `indicator_log_density_tri` 0.80 -> 99) and the two 1D explicit
diffusion time loops (`process.diffuse_numeric` 3.3x,
`ted.diffuse_with_defects` 4.1x).

Those are two different kinds of win. The indicators were the P2 shape
exactly (per-triangle Python loop calling `np.linalg.norm` on
two-element vectors). The diffusion loops were never doing too much
arithmetic -- they paid ~10 numpy dispatches per timestep against a step
count the explicit stability bound drives into the tens of thousands --
so removing the interpreter round trip is all there was to get.

**Bit-identity was made structural.** Every transcendental acting on a
whole array stays in numpy and only its RESULT crosses the boundary:
`np.log(n)` rather than `n`, the nodal Debye lengths rather than the
doping. numpy's `log` and C++'s are independent implementations and the
gate is `np.array_equal`. The one exception -- the TED supersaturation's
scalar `exp`, which would otherwise mean materializing one double per
timestep -- was MEASURED: over 400k arguments spanning the range the
decay reaches, `std::exp` and `np.exp` agreed bit-for-bit on every one,
through both numpy's array and 0-d scalar paths.

Python's builtin `max`/`min` reduce with `if item > current`, so with a
NaN operand the FIRST value wins; `std::max` and `std::fmax` do not both
behave that way. `py_max`/`py_min` in `indicators.cpp` reproduce the
reference's rule so a NaN propagates identically.

**Two candidates the phase line named were EXCLUDED by measurement, not
scope.** (a) **MC implant** is already vectorized over ions -- throughput
is flat at 61-81k ion/s from 500 to 100k, i.e. array-bound not
dispatch-bound -- *and* it could not be gated: bit-identity would need
numpy's PCG64 stream, ziggurat `standard_exponential` and bounded-uniform
algorithm replicated exactly, and a Monte-Carlo kernel whose stream
differs cannot be compared with `np.array_equal` at all. It would be the
first kernel here with no oracle. If ever wanted, draw the random arrays
in numpy and consume them in C++. (b) **`implant_2d`'s lateral
smoothing** is a BLAS `dgemv` after the fix below; C++ cannot reproduce
it bit-identically and has no reason to try.

**A defect found in a module P4 was not porting.** `process2d.implant_2d`
rebuilt the same dense `(Nx, Nx)` Gaussian kernel -- and the same
`(Nx, Nx)` `exp` -- once per depth row, making the call O(Ny*Nx^2) in
transcendentals where it is O(Nx^2). Hoisting it: **939 ms -> 15 ms at
400x600 (62x)**, verified bit-identical against a transcription of the
pre-hoist body.

Also in P4: `tcad::IndexOutOfRange` -> Python `IndexError`, the fourth
mapped exception (the reference gets this free from numpy fancy-indexing;
a kernel dereferencing a raw pointer would read out of bounds, so every
kernel taking connectivity validates the index range in one O(n) pass).
And a CI gap closed that predated the work: the G-E throughput floors are
marked `slow`, and the `python-only` job's slow battery skips the whole
parity file (no extension to measure), so they were running NOWHERE.

**Note on the slow battery's warning count** (11 -> 10 across P4): not a
behaviour change. Deselecting only the three new floor tests gives back
exactly `22 passed, 11 warnings`. pytest de-duplicates warnings per xdist
WORKER, so adding tests reshuffles the `-n 6` distribution.

### M30 -- workbench system features (2026-09-07)

Plan: `pytcad/M30-WORKBENCH-PLAN.md`. **COMPLETE -- all 12 phases**,
through Phase 12 (SSH remote execution + GUI wiring).

Part I (this addendum's four independently-gated phases) covered
workbench system features: splits, calibration, batch, deck-build-import.
None of it touches the numerical core. Two of ARCHITECTURE.md's five M30
bullets (2D contour/cut plots, transient plots) were already shipped by
`GUI-IMPROVEMENT-PLAN.md`/`M17-TRANSIENT-PLAN.md` and are explicitly not
part of this work.

This is the session that identified the broken `base` Qt6 env (see
CURRENT STATE) after a false "97 tests failed" scare.

### GUI reskin, QML cleanup, workflow-friction and performance passes (2026-09-04)

A run of GUI-side slices: visual reskin (slices 0-2), a workflow-friction
pass, a QML architecture cleanup (which itself surfaced two real bugs,
fixed), and a performance audit + optimization pass. Also M12-S2 GUI
exposure (TAT wired into the catalog) and tests added for panels merged
from a parallel development branch.

### GUI phases 3-4 + the code-review passes (2026-08-29/30)

Plan: `GUI-IMPROVEMENT-PLAN.md`. Phase 3 (lab controller, provenance,
continuation traces) and Phase 4 (runtime validation, state indicators):
`lab_controller.py`, `gui_state_validator.py`, `PhysicsLabPanel.qml`,
`StatusIndicator`/`ValidationBanner`/`ValidatedTextField`. Project
persistence schema bumped to v5 (model config was silently reset to
catalog defaults on reload).

Two `/code-review` passes on the uncommitted diffs found 16 real bugs
between them (not style nits), all fixed. The ones worth remembering:

- `solver_runner.build_material_grid()` built the per-node grid in
  `(Nx,Ny[,Nz])` order but Device2D/Device3D require row-major
  `(Ny,Nx)`/`(Nz,Ny,Nx)` -- **silently transposed heterostructure
  material boxes on any non-square mesh.** Same class as the meshgrid
  gotcha.
- `Models.S_n/S_p/driving_force` were declared, documented as
  controlling real physics, and read NOWHERE in the solver core -- a
  pure silent no-op, unlike `impact`/`incomplete_ion` which already
  raised. Now guarded in `Models.__post_init__`.
- `GuiStateValidator._check_input_values`/`_check_result_consistency`
  were bare `pass` bodies whose own docstring claimed real NaN/Inf
  checking -- a faked implementation. Removed outright (along with the
  timer that called them) rather than left as a placeholder; validation
  is genuinely event-driven.
- Two `ListView`s bound `model:`/`visible:` to plain `Slot()` calls with
  no NOTIFY signal -- QML evaluates that once and freezes it, so the
  tables never refreshed across repeated Runs.
- The Phase 3b "continuation stages" table read an npz key that **no
  real solve path ever wrote** -- only its own unit test fabricated it
  via `np.savez`.
- `fd_density()` raised on ANY `eta > FERMI_ETA_MAX`, including a
  transient overshoot during early Newton iterations that would still
  have converged -- aborting the whole solve. Clamped for the in-loop
  evaluation only, with an explicit post-convergence check on the
  UNCLAMPED eta so genuinely invalid converged states still raise.

Numeric QML fields (contact/gate voltage, tox, doping, every process-step
parameter) let `parseFloat("")`/`parseFloat("abc")` through to the solver
as NaN -- found by the end-to-end smoke test, fixed with a shared
finite-number guard.

### 3D device authoring, phase 1 (2026-08-31)

Closed the narrower half of the "3D device authoring absent from GUI"
gap named in `ARCHITECTURE.md` 4b: `Region`/`ContactDef`/`DomainDevice`
and `RegionSpec`/`BoundarySpec`/`MeshModel`/`StructureModel` now accept
an optional z-extent, additively.

The exploration finding that shaped the scope: the SOLVE and VISUALIZE
halves of the pipeline (`solver_runner`'s mesh/doping/device/contact
builders, and `viewer3d.py`) were **already fully
dimensionality-generic** before this work -- the entire gap was in the
AUTHORING half.

### M18 -- small-signal AC (2026-08-31 .. 2026-09-05)

Phase 1 (Device1D), Phase 3 (Device2D n-terminal AC / Y-parameters incl.
gate ports), Phase 3b (full 4-terminal `mosfet_2d` Y-parameter matrix +
fT), Phase 4 (GUI exposure).

`pytcad/ac.py` drives `Device1D` from OUTSIDE `device.py` through its own
`_residual_jacobian` -- the external-driver pattern M15/M16/M17
established. No new `Models` flag: AC is a different equation formulation
layered on the converged DC point, not a physics term to toggle.

Physics: `J_ac(w) = J0 + j*w_s*Cmat`, where `Cmat` is verified
BIT-IDENTICAL (not re-derived) to `transient.py`'s already-FD-gated
backward-Euler storage term at `dt_s=1.0` -- `d/dt -> j*w` replacing
`1/dt` is the only conceptual step. One complex linear solve, no Newton
loop (the system is genuinely linear at fixed state).

### M22 phase 3 -- MPI Schwarz, GPU and AMG (2026-09-02 .. 2026-09-04)

Plan: `M22-LINSOLVE-PLAN.md` section 9. Landed as MPI Schwarz domain
decomposition, **not** the distributed-sparse-matrix design the plan
originally sketched. All three accelerations are opt-in and
size-and-hardware-gated inside `solver_runner.run_job()`; a machine
without a GPU, pyamg or mpi4py sees byte-identical behaviour.

- **Equilibrium AMG**: `Device3D.solve_equilibrium` now honours
  `opts.linsolve` (it previously hardcoded "direct", silently ignoring
  the option). bicgstab+pyamg cuts equilibrium wall time 8x-44x on large
  3D meshes (bjt_3d 43.4 s -> 1.0 s) but is WORSE on small ones
  (mosfet_3d 2.1 s -> 21.4 s) -- gated at >20,000 nodes, the measured
  switch point.
- **GPU bias solve**: `linsolve`'s `"gpu_direct"` (CuPy/cuSOLVER).
- **MPI Schwarz**: later generalized past an x-only split, and a real
  correctness bug in it was found and fixed (2026-09-04), as was a
  gate-axis fix verified on `mosfet_3d`/`moscap_3d`.

Earlier M22: phase 1 (Krylov + ILU behind spsolve) and phase 2 (Schur-
complement preconditioner, `solve_linear(precond="schur")`). The Schur
work sat LANDED-PENDING-VERIFICATION for two days and passed cleanly on
its first actual run -- unlike M16.

### M21 phase 3 -- unstructured 2D FV (2026-08-31)

Plan: `M21-PHASE3-MESHING-PLAN.md` (scoped at 45-62 h, HIGH RISK because
it touches Device2D's frozen core). Delivered in four slices:

- **3a, geometry foundation**: `gmsh_mesh.build_diode_mesh()` (two OCC
  rectangles `fragment()`-ed so they share nodes exactly at the material
  interface, sized against `debye_length`), `unstructured_assembly.py`'s
  unique edge list + mixed Voronoi/barycentric dual-cell areas.
- **3b, Poisson-only equilibrium**: TPFA transmissibility via triangle
  circumcenters (`dual_facet_length/primal_edge_length`, scale-invariant
  -- confirmed, not assumed). MEASURED that TPFA's Delaunay requirement
  is only approximately met: 1.39% of triangles on the real diode mesh
  are obtuse, yet every transmissibility still comes out positive. That
  measurement is the actual grounding for using the method here.
- **3c, coupled bias solve**: Scharfetter-Gummel + SRH, interleaved
  `[psi, n, p]`. Key de-risking finding, re-derived rather than trusted:
  3b's per-edge `trans` factor serves the SG current term too with NO new
  geometry, because `dVy*D/hx = D*trans` algebraically.
- **3d, integration**: `Device2D(unstructured=True)` -- genuinely a thin
  dispatch wrapper, zero new Jacobian entries.

Earlier M21: phase 1 (1D h-refinement, 17 gates) and phase 2 (2D/3D).

Phase 1 caught two design errors BY the gates: (a) folding h/L_D into the
Doerfler error mass made it dominate selection and produced a
near-uniform "adaptive" mesh that LOST to a uniform one at equal node
count -- h/L_D is now a separate absolute constraint; (b) the default
grading ratio 1.2 is UNREACHABLE by bisection (a bisected cell abuts an
unbisected one at exactly 2), so the repair loop silently returned a mesh
that failed the request -- ratio 2.0 is the default and ratio<2 now
raises.

Phase 2's hard-debug pass found six real bugs, including a stale import
that had been breaking PHASE 1 unconditionally (10 of 17 phase-1 tests
were already failing and nothing had re-run them), a `tol` convergence
check that was dead code in both 2D and 3D drivers, and the headline
`meshgrid` axis-order corruption in the tests' own fixtures (see
GOTCHAS).

### M19 -- self-heating, phase 1 (2026-08-31)

`pytcad/thermal.py`. Architecture decided BEFORE implementation:
`Device1D`'s entire nondimensionalization is built once at `__init__`
from a scalar `T`, so a genuinely coupled 4th unknown would mean
rearchitecting the whole scaling framework -- disproportionate to what
the milestone's gates require. Chose the standard "isothermal DD + outer
Gummel thermal loop" instead; `device.py`/`moscap.py` untouched.

### M20 -- density gradient (2026-08-29 .. 2026-08-31)

Plan: `M20-DENSITY-GRADIENT-PLAN.md`. Ancona-Stafford quantum
correction, equilibrium-only, default-off bit-identical. **Now closed**
via a coupled-Newton reformulation; the road there is worth keeping:

- Gate-writing cross-check caught three real defects in `dg.py` before
  any run: a double-kT bug (`dos` is already in m^-2), an inverted
  `E_band` sign that put the inversion well in the BULK, and a
  far-boundary Hamiltonian diagonal never assigned (`main[-1] = main[-1]`
  on `np.empty` garbage -> nondeterministic `eigsh`).
- The **lagged** outer loop sourced each pass's target `Lambda` from the
  DG-CORRECTED density instead of the classical one, closing a 1-node
  self-reference. This produced a RIGID period-2 oscillation immune to
  every damping factor from 1.0 to 0.02 over 400 passes -- and a 188 nm
  centroid against a ~4 nm reference. Sourcing from the classical density
  converges in 4 passes with no damping.
- That exposed a second, separate problem: at gamma=1 the converged
  answer sat exactly at the clamp and INVERTED the required direction. A
  gamma sweep showed a hard BIFURCATION, not a calibration curve. Three
  hypotheses (boundary-condition mismatch, sub-physical mesh resolution,
  units) were tested and ruled out before concluding this was the known
  weakness of a lagged Gummel scheme -- which is why production tools
  solve the quantum potential COUPLED into the same Newton system.
- Fixed by doing exactly that: `(psi, Lambda_n, Lambda_p)` solved
  simultaneously, 3 unknowns/node, interleaved like `device.py`'s own
  convention.

### M17 -- transient simulation (2026-08-30/31)

Plan: `M17-TRANSIENT-PLAN.md`. Phase 1 (1D), Phase 2 (2D), Phase 3 (GUI).
`transient.py`/`transient2d.py` drive the device cores from outside;
`device.py`/`device2d.py` untouched. Backward-Euler/theta scheme with
adaptive dt and three `Waveform` primitives.

Two findings worth keeping:

- **The charge-conservation sign convention differs between 1D and 2D,
  genuinely.** 1D: `d(stored_charge)/dt == I_right - I_left`. 2D:
  `== -(I_left + I_right)`. Not a repeat of the same bug --
  `Device2D.terminal_current()`'s convention is "positive = INTO the
  device" independently at every contact, while 1D's `Jn+Jp` edge array
  is one continuous current sampled at two points.
- **The 2D `stored_charge()` had to be redefined as a delta** relative to
  the initial snapshot: on a symmetric Na=Nd diode the absolute
  `sum((n-p)*dA)` is near-zero by cancellation, so what remained was
  float64 roundoff, not the signal. A units bug was ruled out first.
- Usage lesson: the default adaptive-dt growth coarsens past a short
  decay timescale within a few steps, and backward Euler's `1/(1+dt/tau)`
  under-damps relative to `exp(-dt/tau)` once dt ~ tau. A caller
  measuring a specific timescale must pass an explicit `dt_max`.

Honest gap: G2's stored charge was NOT matched to a textbook
`Qs ~= I_F*tau_p` formula (off by a factor of several and sign-ambiguous;
this is voltage-driven switching, not the constant-reverse-current
assumption those formulas make). Descoped to the two independently
verifiable claims rather than forcing a tolerance.

### M16 -- band-to-band tunneling (2026-08-29, verified 2026-08-31)

Plan: `M16-BTBT-PLAN.md`. Local Kane model, `G = A F^2 exp(-B/F)`, Si
constants from Hurkx, Klaassen & Knuvers (1992) Table I. Live-coupled
generation in `_residual_jacobian`, placed AFTER both continuity `=`
assignments and BEFORE Dirichlet stamping (the M15 D1 invariant).

Landed unverified; when the gates were finally RUN two days later, all
failures root-caused to the TEST code, not the physics -- e.g. a
plateau check that sorted ascending by V then asserted J increases going
from the largest reverse bias to the smallest, backwards from the
intended trend.

**Provenance caveat that still stands:** the A/B constants were pinned
from model knowledge, not a fetched primary source (the authoring
session's web search was unavailable). If the pin fails review, fix the
constants deliberately -- never silently.

### 3D visualization (2026-08-29/30)

Plan: `3D-VISUALIZATION-PLAN.md`. PyVista/VTK in a SEPARATE top-level
window (VTK's Qt integration is a QWidget, not a QML item). Phases 1-2
(grid + isosurfaces) and Phase 5 (exploded multi-layer structural view).
Field node ordering (pytcad's `(Nz, Ny, Nx)` C-order) was verified
NUMERICALLY against VTK's point order, not assumed.

**A real bug found by actually building the thing:** `gui/app.py`
bootstrapped with `QGuiApplication`, but `QWidget` construction
hard-requires a real `QApplication` and ABORTS THE WHOLE PROCESS
otherwise. Phase 1 as landed would have crashed the entire application
the first time a user clicked "View in 3D" -- invisible to its own tests,
which all monkeypatched the window out before it could be constructed.
Switching to `QApplication` is a strict superset and also unlocked real
headless testing of the widget tree.

### M14 -- surface mobility (2026-08-28 .. 2026-08-31)

Plan: `M14-SURFACE-MOBILITY-PLAN.md`. G-B (D_it) and G-C (S_n/S_p)
landed; **G-A remains the suite's only xfail** (see OPEN ITEMS).

- **D_it**: a first pass "corrected" the plan's `Q_it = q*D_it*phi_s` to
  `q^2*D_it*phi_s` from a half-remembered heuristic, got user sign-off,
  implemented it -- then found it numerically to be a complete no-op
  (~1e-21x the scale of the existing term). Re-derived from first
  principles: D_it [cm^-2 eV^-1] times a shift of `dphi_s` VOLTS is a
  `dphi_s`-eV energy shift numerically, giving ONE factor of q. The
  plan's original text was right; the "correction" was wrong.
- **S_n/S_p**: the first wiring used `F_n[node] = (n[node]-n0)*(1+S)`,
  chosen because it reduces to Dirichlet at S=0 with no branching -- a
  mathematical no-op (see GOTCHAS). Redone as a genuine Robin flux
  balance from steady-state particle conservation in the boundary
  half-box, which does NOT reduce to Dirichlet at S=0 (S=0 there means
  zero current, a materially different BC).
- A later hard-debug pass found `fd=True` + `S_n/S_p != 0` gave 1.2e-3
  boundary FD-Jacobian error, 25x over gate: M13's Fermi-Dirac chain-rule
  correction to the SG edge-current Jacobian was applied to interior rows
  but never extended to the new boundary Robin rows.
- Device2D's S_n/S_p was reverted to `NotImplementedError` rather than
  shipped broken, then landed properly in a later session.

### M15 -- impact ionization (2026-08-26 .. 2026-08-28)

Plan: `M15-IONIZATION-PLAN.md`. The longest-running debugging arc in the
project and the source of several standing conventions.

An early "M15 COMPLETE, all gates green" claim was **false**. A hard-debug
pass found impact ionization was contributing EXACTLY ZERO at every bias,
via six defects:

1. **D1**: the generation term was added to the continuity rows and then
   OVERWRITTEN by `=` when those rows were assigned 30 lines later. This
   is the origin of the standing "generation goes after the continuity
   assignments, before Dirichlet stamping" invariant.
2. **D2**: the frozen-field snapshot was taken AFTER contact stamping,
   contradicting its own comment (a 2 MV/cm contact-cell artifact,
   harmless only while D1 discarded the source). D1+D2 must land
   together.
3. **D3**: the staged-generation ladder never reached 1.0x (guarded by
   `stage_factor < 1.0`, so the final rung reused 0.5x).
4. **D4**: toggling `Models.impact=False` after an on-solve left the
   frozen source applied.
5. **D5**: Device2D/Device3D SILENTLY IGNORED `Models(impact=True)` --
   now `NotImplementedError`, matching the `field_mobility` precedent.
6. **D6**: impact+fd used the wrong SG scheme (missing M13's nu-factor
   edge deltas), 13 orders of magnitude too much generation.

**Root cause of the spurious avalanche branch (confirmed):** the analytic
II Jacobian rows destabilize Newton itself -- the first `du` is
BIT-IDENTICAL between impact on/off at the same state, so the linear
algebra was fine; the instability is iteration dynamics through sign(J)
kinks. Fixed with a lagged-source / frozen-generation architecture (the
M12-TAT precedent): generation frozen per bias solve on the warm-start
state before contact stamping, no II Jacobian rows, an outer fixed-point
loop closing the feedback.

Closing R1b took three attempts (full coupled Jacobian alone: weaker
multiplication, a continuation-methodology gap; arc-length sweep: the
bordered corrector bypassed the strength ladder; finally: threading the
same ladder into the corrector plus backtracking it never had). A
cross-check against the original van Overstraeten-de Man 1970 paper found
a genuine literature bug along the way -- hole ionization's field-switch
point wrongly shared electrons' 5e5 V/cm instead of its own published
4e5 V/cm. The residual G-C/G-D gaps turned out to be the textbook local
field `M = 1/(1-I)` formula's own neglect of space-charge feedback, and
N=1e17's fold sitting 35% outside the 1970 fit's calibrated range --
neither fixable by more solver work. Closed by user-directed scope
decisions, recorded in the tests themselves.

### M13 -- Fermi-Dirac statistics (2026-08-26)

Plan: `M13-FERMI-DIRAC-PLAN.md`. Physical Nc/Nv FD statistics, the
nu-factor modified Scharfetter-Gummel scheme (exact equilibrium detailed
balance for both carriers including heterointerfaces), incomplete
ionization, ported through 1D/2D/3D.

- A genuine latent defect: deep-tail `f_half` carried ~2.5e-4 RELATIVE
  error (a fixed-node quadrature grid cannot resolve a feature at
  `t~exp(eta)`). `eta<=-10` now uses the exact Taylor series.
- Later, a tabulated fast path (cubic Hermite over **log F**, not F --
  `F_{1/2}` spans ~4e-18 upward, so an absolute-error interpolant would
  be worthless in the tail, and absolute error in log F IS relative error
  in F). Measured 150x-1260x: 4000 evaluations 214.7 ms -> 0.17 ms; an
  fd `solve_bias` 11.41 s -> 0.07 s. The exact quadrature survives as
  `f_half_exact`, gated against, and `PYTCAD_FERMI_EXACT=1` bypasses the
  table.
- GOTCHA that cost a debug cycle: the full-residual Poisson assembly in
  `device2d`/`device3d` REUSES the dx/dy edge differences, which under fd
  carry modified SG deltas -- Poisson fluxes must be recomputed from PURE
  potential differences.

### M11 -- heterostructures (2026-08-26)

S4 (Device2D per-node material lists, harmonic-mean edge eps, per-node fd
DOS grids so fd composes with heterojunctions) and S5 (structure-model
materials lossless end-to-end, HBT and HEMT templates).

A debug cycle found the `et_x` eps factors missing from the 3D Poisson
fluxes -- caught by the 3D->2D dimensional-reduction gate. Another found
Device2D/Device3D bias convergence dividing relative updates by RAW
densities, pinning the criterion to roundoff at deep-minority barrier
nodes (limit cycle ~8.5e-7); both cores now use a density floor.

### Earlier / cross-cutting

- **graded_mesh grading bug (2026-08-27)**: the docstring promised
  adjacent cells never differ by more than `ratio`; measured up to
  11.06x, because the forward-walk construction clamped every step onto
  the next focus point and onto L, leaving a STUB final cell -- always
  the ohmic contact cell, 2.5-5.5x SMALLER than `h_min`. Consequence was
  measured, not theoretical: an explicit diffusion step is limited by
  h^2, so a 4-anneal-step process flow went from 15.2 s to 0.19 s once
  fixed (~78x). Replaced with an arc-length construction plus a log-space
  gradient limiter whose scale-invariant rescale makes the fixed point
  satisfy the bound EXACTLY (fuzzed 2000 geometries: 0 violations).
  **Goldens were preserved, not regenerated**: the M13 `.npz` goldens
  rebuilt their meshes by CALLING `graded_mesh`, silently coupling
  solver-bit-identity gates to the mesh generator -- decoupled by
  freezing the exact pre-fix meshes into
  `tests/goldens/m13/frozen_meshes.npz`.
- **GUI scenegraph crash (2026-08-27)**: `__cxa_deleted_virtual` abort in
  `QQuickPaintedItem::updatePaintNode`, ~1-in-3 to 1-in-5 full-suite
  runs. Every test calling `create_engine()` built a `QQuickWindow` and
  never tore it down; Python's GC destroyed it outside Qt's safe close
  protocol. Fixed with a per-test + session teardown sweep that
  `.destroy()`s (not `.close()`s -- `Main.qml`'s `onClosing` can veto a
  close on unsaved changes) every top-level window.
- **Test suite parallelized (2026-08-28)**: pytest-xdist, after fixing
  four hardcoded shared `/tmp` paths that raced across workers.
- **Roadmap extension (2026-09-09)**: `ARCHITECTURE.md` gained sections
  4c (post-M31 roadmap M31-M40, recording the measurement that ordered
  M31's phases so it is never re-derived), 4d (the dimensional debt and
  the road to full 3D) and 4e (how this is meant to beat
  Sentaurus/Atlas, and where it deliberately concedes). 4c.2's M32-M40
  are PROPOSED, not decided.
