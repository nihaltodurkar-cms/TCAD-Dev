# M33 -- SURFACE / INTERFACE PHYSICS COMPLETION

STATUS: APPROVED 2026-09-10. **S1, S2 and S3 ALL LANDED** -- 24 gates
green, goldens byte-identical. 1D ONLY; 2D/3D remain in the legacy
gauge. See section 7 for results and section 8 for what is left.

Parent: `ARCHITECTURE.md` 4c.2 (M33) and the 4b.1 gap row
"[partial] Heterojunctions: 1D core done; 2D pending (M11-S4); no
thermionic-emission interface model".

---

## 1. What M33 was scoped as, and what is actually left

4c.2 lists three items. Two are ALREADY DONE and the roadmap has not
caught up:

| item | state |
|---|---|
| surface recombination velocity (S_n/S_p) | **DONE** -- M14 G-C, in `Device1D` AND `Device2D` (a genuine Robin flux-balance BC, not a Dirichlet rewrite) |
| D_it in the MOS module | **DONE** -- M14 G-B, `moscap.py` |
| thermionic-emission heterojunction interface | **NOT DONE** -- the real remaining item |

(The 4b.1 row's "2D pending (M11-S4)" is also stale: M11-S4 shipped.)

So M33 reduces to the heterointerface. And investigating that turned
up something bigger than the item itself.

## 2. THE FINDING: heterojunction transport ignores electron affinity

**Verified by measurement, not by reading.** Two `Device1D`
heterostructures identical except for a STEP in electron affinity at
the junction, solved to equilibrium and to 0.4 V bias:

| step in chi at the interface | max abs(dpsi) | J / J_ref |
|---|---|---|
| -0.20 eV | **0.000e+00** | 1.000000 |
| -0.50 eV | **0.000e+00** | 1.000000 |
| +0.50 eV | **0.000e+00** | 1.000000 |

Not "small". EXACTLY zero, bit-for-bit, for a half-electron-volt
conduction-band step.

The cause is structural, and confirmed by reading the code after the
measurement pointed at it:

* Transport is parameterised by `nie` alone. `_residual_jacobian`'s
  heterojunction terms are `dlnnie = log(nie_s[1:]/nie_s[:-1])`, and
  `materials.nie_effective` -> `Semiconductor.ni` is
  `sqrt(Nc*Nv)*exp(-Eg/2kT)`. That encodes **Nc, Nv and Eg. It does
  not contain chi.**
* `self.chi_arr` IS built (device.py, in `__init__`) and is then used
  in exactly ONE place: `band_diagram()`, which computes
  `Ec = -psi*VT - chi`. That is a post-processing accessor.
* `device2d.py`, `device3d.py` and `unstructured_dd.py` do not
  reference `chi` at all.

Three consequences, each checkable:

1. **The band offset actually solved is a SYMMETRIC split of dEg.** In
   the nie gauge each band effectively receives dEg/2. The physical
   (dEc, dEv) set by affinity is not represented. For AlGaAs/GaAs the
   real split is about 62:38, not 50:50; for a pair with equal Eg and
   different chi (a Type-II alignment) the real dEc is nonzero and the
   model's is zero.
2. **`device.py`'s own comment is wrong.** It states that "chi/Eg
   enter the currents through position-dependent nie (band offsets
   ride ln(nie) edge factors)". True for Eg. False for chi.
3. **`test_hemt_band_step_at_interface` gates a cosmetic quantity.**
   It measures a 0.20 eV band step through `band_diagram()` -- i.e.
   through the one function that reads `chi_arr` -- so it passes on a
   number the solver never used. This test has ALREADY been found
   once to be a false negative (it diffed along the wrong axis and was
   fixed 2026-08-28 to diff along axis=0); the deeper problem, that
   the quantity it measures does not enter the equations, survived
   that fix. This is the house failure mode "a test can be
   structurally incapable of failing", one layer down.

**Why this reshapes the milestone.** Thermionic emission is a
statement about a barrier: its entire content is the flux limit
imposed by dEc. Implementing TE on top of a solver that cannot
represent dEc would be calibrating a barrier height the equations do
not have. The affinity fix is therefore a PREREQUISITE, not a
parallel nice-to-have.

## 3. Proposed scope

**M33-S1 -- chi-aware band alignment (1D first).** Replace the
symmetric-nie edge factors with the physical band-edge formulation, so
that `dEc` and `dEv` are what the SG deltas actually see. Sketch, to
be FIXED BY THE DETAILED-BALANCE GATE rather than by this algebra:
today `delta_n = dpsi + dln(nie)` with
`dln(nie) = (dlnNc + dlnNv)/2 - dEg/(2 VT)`; the band-edge form wants
`delta_n = dpsi + dlnNc + dchi/VT` and correspondingly for holes with
the opposite sign convention M11-S3 established. The two agree only
when the affinity step happens to equal the symmetric split, which is
the bug.

Default-off is NOT available here the way it usually is: this changes
what a heterostructure MEANS. Proposed instead -- a `Models` flag
(`band_offset="nie"` legacy vs `"affinity"`), defaulting to the
legacy path so every existing result stays bit-identical, with the
new path opt-in until its gates are green and the templates are
re-validated. That keeps the amendment rule's bit-identity clause
satisfiable.

**M33-S2 -- thermionic-emission interface flux.** At an abrupt
interface edge, replace the SG drift-diffusion flux with an emission-
limited one, `Jn = q (v_n2 n2 - v_n1 n1 exp(-dEc/kT))`, emission
velocity `v = A* T^2 / (q Nc)` (equivalently `sqrt(kT/(2 pi m_DOS))`).
Reuses `schottky.RICHARDSON_A_STAR_TABLE`.

**M33-S3 -- fix the cosmetic gate and the wrong comment.**

Deliberately OUT of this slice: 2D/3D (1D first, the M18/M19
precedent), graded (non-abrupt) heterointerfaces, interface trap
states at a heterointerface, and M14's G-A (still blocked on a
paywalled source).

## 4. Gates

Written before implementation, per the house rule.

  G-1  EQUILIBRIUM DETAILED BALANCE, PER CARRIER SEPARATELY. The edge
       current vanishes to machine precision across a chi step, for
       electrons and holes INDEPENDENTLY. M11-S3's own record says a
       shared delta passes an FD-Jacobian check and still breaks hole
       detailed balance -- so a combined check is not sufficient.
  G-2  chi ACTUALLY MOVES THE SOLUTION. The probe in section 2, run
       as a test: a chi step must change psi and J, monotonically and
       by a physically sensible amount. This is the gate whose absence
       let the gap exist.
  G-3  FD-JACOBIAN ON THE INTERFACE ROWS SPECIFICALLY, not random
       columns (M14's lesson: random sampling missed the boundary rows
       where the bug was).
  G-4  BIT-IDENTITY OFF-PATH. Legacy `band_offset="nie"` reproduces
       every existing golden. Reconstruct-and-compare per CLAUDE.md:
       md5 before, regenerate, shim back, prove recoverable.
  G-5  TE REDUCES TO DD. As the emission velocity grows, the TE
       interface flux must converge to the SG result -- the limit that
       proves the new branch is a generalisation and not a
       replacement.
  G-6  TE IS FLUX-LIMITING. For a large dEc the TE current is BELOW
       the DD current, and the gap widens with dEc.
  G-7  PUBLISHED-VALUE BENCHMARK in `tests/test_model_benchmarks.py`
       FIRST, per the hard rule.

## 5. Risks, stated up front

* **G-7 is the milestone's real risk.** G-1 through G-6 are all
  self-contained limit/consistency gates needing no external source.
  An ABSOLUTE benchmark needs a published heterojunction I-V or a band
  offset with a citable number. M16's BTBT constants were pinned from
  model knowledge because the authoring session had no web search, and
  that provenance caveat still stands in the tree; M14 G-A has been
  xfail for weeks on a paywalled paper. **Before committing to G-7 I
  should confirm a reachable source exists** -- the 62:38 AlGaAs/GaAs
  conduction-band-offset rule is widely published and is the obvious
  candidate, but "widely published" is not the same as "I have it".
* Changing what a heterostructure means will move the HBT/HEMT
  template results. That is the point, but it means M11-S5's template
  gates need re-validating, not just re-running.
* `schottky.RICHARDSON_A_STAR_TABLE` is keyed on SHORT names ("Si",
  "GaAs") while `Semiconductor.name` holds full ones ("Silicon",
  "Gallium arsenide"). Every current caller passes the literal string,
  so nothing is broken today -- but `richardson_a_star(mat.name, "n")`
  KeyErrors on every real material object, and AlGaAs (the alloy the
  HEMT template uses) has no entry at all. M33-S2 needs either an
  `A_star` field on `Semiconductor` or a name-normalising lookup.

## 6. Amendment request (REQUIRED BEFORE ANY CORE EDIT)

This touches `pytcad/device.py`'s `_residual_jacobian`, which is
frozen. Per CLAUDE.md it needs: explicit sign-off recorded HERE,
FD-Jacobian-first, bit-identical off-path, and reconstruct-and-compare
on `tests/goldens/m13/*.npz`.

SIGN-OFF: **GIVEN 2026-09-10** by the user, on the scope in section 3
(S1 chi-aware alignment behind a flag, S2 thermionic emission, S3 fix
the cosmetic gate and the wrong comment), with the section-5 risks
stated and accepted -- in particular that G-7's absolute published
benchmark may not be reachable, in which case it is reported as such
rather than fabricated.

### Golden baseline, recorded BEFORE the edit (step 1 of 4)

CLAUDE.md's reconstruct-and-compare protocol. Every golden the change
could touch, md5 as of 2026-09-10, before any line of M33 was written:

```
f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz
```

Plus the three hardcoded hex digests in `tests/test_m13_solver.py`:
`TAT_EQ_DIGEST`, `TAT_FW_DIGEST`, `HETERO_FW_DIGEST`.

`hetero1d_eq.npz` and `HETERO_FW_DIGEST` are the two that matter most:
they are the heterojunction goldens, i.e. exactly the path S1 touches.
The DEFAULT stays `band_offset="nie"`, so the prediction is that all
six files and all three digests come back IDENTICAL. If any of them
moves, the flag is leaking and that is a defect, not a re-baseline.



## 7. Results

### S1 -- chi-aware band alignment: LANDED 2026-09-10

`tests/test_m33_interface.py`, 14 gates, all green.

**The implementation collapsed to something much smaller than section 3
predicted, and the collapse is the interesting part.** Section 3
proposed separate per-carrier corrections. Deriving them properly gives
ONE per-node shift:

    s = ln(Nc/nie) + chi/VT      ->   n = nie*exp(psi+s),  p = nie*exp(-(psi+s))

i.e. the affinity gauge is EXACTLY the legacy nie gauge with
`psi -> psi + s` wherever the carrier-potential law appears, and `psi`
alone in the Poisson flux. Three things follow:

* `n*p = nie^2` identically, so mass action is gauge-free and nothing
  downstream of the densities changes.
* **Both carriers take the SAME sign of correction** -- unlike M11-S3's
  `ln(nie)` factors, which are opposite. That is the physics: a rigid
  band shift moves Ec and Ev together; a gap change moves them apart.
* The per-carrier and unified derivations agree because
  `ln_gn + ln_gp == Eg/kT` identically. Both were done independently
  and cross-checked before any code was written.

`s` is referenced to node 0 (only differences are physical), which
makes it identically zero for a homojunction -- so the legacy path is
bit-identical BY CONSTRUCTION, every correction being `+ 0.0`, rather
than by tolerance.

Touch points, all gated on the flag: the SG edge deltas, the Boltzmann
ohmic contact `psi0`, the equilibrium neutral guess, and
`solve_equilibrium`'s carrier slaving. `fd`, `incomplete_ion` and `dg`
with `affinity` are REFUSED (`NotImplementedError`) -- their eta-space
contact solver and neutral-guess bisection carry their own
`ln(Nc/nie)` offsets and composing them was not derived or gated. That
is the M20 dg+fd precedent, not a shortcut.

#### Reconstruct-and-compare (steps 2-4)

All six `tests/goldens/m13/*.npz` came back **md5-identical** to the
section-6 baseline, and all 33 m13 tests pass including the three
hardcoded digests. Which moved: none. Why: the default is
`band_offset="nie"`, on which `band_shift` is exactly `np.zeros`, so
every new term is an exact `+ 0.0`. Step 3's "shim the old behaviour
back" is moot when nothing moved.

#### The physics, measured in two independent configurations

| forward-biased p-n diode, chi on the n-side | J [A/cm^2] |
|---|---|
| 3.85 | 2.749e-4 |
| 3.95 | 2.731e-4 |
| 4.05 (homojunction) | 2.705e-4 |
| 4.15 | 2.676e-4 |
| 4.25 | 2.650e-4 |

Monotonic: raising chi on the n-side lowers Ec there, raising the step
electrons must climb into the p-side. Only ~1% per 0.1 eV, and that is
CORRECT rather than a weak coupling -- a rigid shift of both edges on
one side is largely absorbed by the built-in potential
re-equilibrating at fixed bias.

| ISOTYPE n-N junction (no p-n built-in to absorb it) | J [A/cm^2] |
|---|---|
| dchi = -0.20 | 4.34e3 |
| dchi = 0 | **6.42e3** |
| dchi = +0.20 | 3.11e3 |

Current is MAXIMISED at zero offset and falls for BOTH signs, by a
factor ~2. That sign-symmetric shape is the signature of a genuine
band barrier and is what the legacy gauge cannot produce at all.

#### An adversarial finding that changed a gate

The first version of G1 normalised the equilibrium residual current by
the device's own forward current. Injecting a deliberate sign error
into the hole delta showed that gate to be VACUOUS: zero-bias |Jp| rose
from 3.2e-10 to **1.354e-01** (nine orders), but J(0.4V) rose to
1.1e+03 as well, so the RATIO came out 1.75e-07 -- better than the
correct code. The gate now asserts an ABSOLUTE floor of 1e-7 A/cm^2,
set from measurement: the same device as a homojunction in the LEGACY
gauge reports 1.09e-9, which is where `solve_bias`'s Newton stops, not
a balance violation. Discrimination is ~1000x.


### S2 -- thermionic-emission interface flux: LANDED 2026-09-10

`Models(thermionic=True)`, which REQUIRES `band_offset="affinity"`
(refused otherwise: TE's whole content is the flux limit imposed by
dEc, so running it in a gauge that cannot represent dEc would be
calibrating a barrier of zero).

**Form, derived from detailed balance rather than quoted.** On a
material-change edge the SG flux is replaced by

    Jn = K [ n2*g2 - n1*g1 ],  g1 = min(1, e^u),
    g2 = (Nc1/Nc2) min(1, e^-u),  u = delta_n - dln(Nc)  ( = -dEc/kT )

because `g1/g2 = (Nc2/Nc1) e^u = e^delta_n` identically, and `delta_n`
IS `d(ln n)` at equilibrium -- so the flux vanishes there for ANY
Nc1, Nc2. That is also why a SINGLE emission velocity is used rather
than one per side: the two-velocity form is only detailed-balanced
when A*1 == A*2, and this one is exact regardless. The velocity is the
harmonic mean of the two sides', matching `dn_edge`'s existing hmean
convention and making the model symmetric under reversing the mesh,
which a one-sided choice is not.

**Implementation note worth keeping.** The TE flux is written into the
SAME five slots the SG flux uses (`an`, `Bp`, `Bm`, `dBp`, `dBm`, and
the hole counterparts), so every downstream Jacobian expression --
including the M15 impact coupling -- works unchanged and no new branch
appears below that point. `K = v*LD/D0_REF` is the exact analogue of
`an = (D/D0_REF)/h`, derived from `J0 = q*D0_REF*Ns/LD`.

**Measured:**

| gate | result |
|---|---|
| G-5 TE -> DD as v grows | J_TE/J_DD = 0.976 -> 1.0029 -> 1.0032 for K x1e3/1e5/1e7 |
| G-6 TE is flux-limiting | J_TE < J_DD at the real emission velocity |
| deepens with barrier | J_TE/J_DD falls monotonically as dchi goes 0 -> 0.15 -> 0.30 |

The K -> inf limit lands ~0.3% ABOVE drift-diffusion, not exactly on
it, and that is correct rather than a tolerance fudge: `K -> inf` is an
IDEAL zero-resistance interface while the SG edge it replaces keeps a
finite drift-diffusion resistance. One edge out of a few hundred is
worth a few tenths of a percent.

**Emission velocity: an honest factor-of-two.** `emission_velocity()`
derives m_DOS from the material's OWN Nc (`N = 2(2 pi m kT/h^2)^{3/2}`)
so it needs no new constant and cannot drift from the Nc the solver
uses. It does NOT reproduce a tabulated Richardson A*, and that is
expected: measured 2.575e6 cm/s vs 4.950e6 from `richardson_a_star`,
a factor 1.92, because A* is governed by the RICHARDSON mass and
silicon's six-valley band separates it from the DOS mass (Nc implies
1.09 m0, A*=252 implies 2.1 m0, ratio 1.92). Both numbers are pinned by
a gate so the discrepancy is a known quantity. The A* table is also
keyed on SHORT names ("Si") while `Semiconductor.name` holds full ones,
so `richardson_a_star(mat.name, ...)` would KeyError on every real
material and alloys have no entry -- another reason the Nc route was
chosen.

**Refusals added:** `thermionic` without `affinity`; `thermionic` on a
homojunction (nothing to apply it to); `thermionic` with `impact` (the
frozen II source is built from drift-diffusion edge currents and does
not know about the interface flux).

**A latent defect found and fixed while doing this.** S1 had changed
the SG deltas in `_residual_jacobian` but NOT in
`_ii_compute_gs_frozen`, which recomputes them independently -- so
`affinity + impact` would have driven impact ionization off
nie-gauge edge currents. Now carries the same shift.

**A regression I caused and the gates caught immediately.** Inserting
the thermionic+impact refusal at the wrong indent CLOSED the affinity
branch, leaving `s = ...` as dead code after a `raise` and rebinding
the `else`. `band_shift` became all-zeros, silently reverting S1
entirely -- and it still imported cleanly. Two gates failed on the next
run with every chi giving an identical J. Recorded because the failure
mode (a semantically destroyed but syntactically valid block) is not
one a type checker or an import smoke test would find.

### S3 -- the cosmetic gate and the wrong comment: LANDED

* `device.py`'s "chi/Eg enter the currents through position-dependent
  nie" now says what is true: Eg yes, chi no, and where to get chi.
* `gui/tests/test_m11s5_templates.py::test_hemt_band_step_at_interface`
  now states exactly what it proves and what it does not: it checks the
  TEMPLATE's material assignment and the band-diagram accessor, NOT
  that the solver used the offset -- `Device2D` still does not
  reference `chi` anywhere. Left as a scoped gate rather than deleted
  or silently "fixed".

## 8. What is NOT done, for the next session

* **M33 is now FULLY LANDED (S1-S5) -- Device1D, Device2D, Device3D,
  and `unstructured_dd.py` all support the chi-aware affinity gauge.**
  Device2D: `M33-S4-PLAN.md` (LANDED 2026-09-10/11, 16 gates). Device3D
  and `unstructured_dd.py`: `M33-S5-PLAN.md` (LANDED 2026-09-11, 21
  gates -- suite green both ways throughout). `unstructured_dd3d.py`
  remains explicitly out of scope: it has no heterojunction mechanism
  of any kind (no `materials_per_node`/`dlnnie`) to extend, so adding
  one would be new-feature work, not a port of an existing one. S5 also
  found a genuine, investigated (not assumed) physics result:
  `unstructured_dd.py`'s coupled (non-equilibrium-slaved) Newton
  formulation makes the terminal current of a uniformly-doped isotype
  junction PROVABLY gauge-invariant (an exact SG-Bernoulli-identity
  argument, not a numerical coincidence) -- see `M33-S5-PLAN.md`
  section 3 for the derivation; this is why that module's own G2 gate
  differs in shape from Device1D/2D/3D's.
* **G-7, the absolute published benchmark, was NOT done** and nothing
  is claimed for it. Section 5 flagged it as the milestone's real risk
  and that judgement stands: G-1..G-6 are self-contained limit and
  consistency gates, all green, and none of them pins an absolute
  current against literature. The AlGaAs/GaAs 62:38 conduction-band
  rule remains the obvious candidate.
* `fd`, `incomplete_ion`, `dg` and `impact` all REFUSE to compose with
  the new flags rather than silently doing something unvalidated.
* Graded (non-abrupt) interfaces and interface trap states at a
  heterointerface are untouched.
