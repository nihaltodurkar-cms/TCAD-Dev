# M38 -- TCAD-to-SPICE COMPACT MODEL EXTRACTION

STATUS: Phases 1-3 LANDED 2026-09-10, all 33 gates green (see
section 5 for the measured numbers). Phase 4 (GUI /
deck statement) named but NOT in scope for this slice.

Parent roadmap: `ARCHITECTURE.md` section 4c.2 (M38) and 4c.3, whose
cheapest-payoff-first ordering reads `M32 -> M38 -> M33 -> M34`. M32
landed 2026-09-10, so this is the next item on that track.

---

## 1. Why this exists

M27 shipped the FORWARD direction: a real `Device1D` embedded in an MNA
circuit as a nonlinear element (`pytcad/circuit.py`'s `DeviceStamp`).
The INVERSE -- fit an analytic compact model to a simulated I-V and emit
a netlist a circuit designer can actually use -- does not exist anywhere
in the tree (`grep -i 'spice|netlist'` finds only `circuit.py`, its test,
and two prose mentions).

That inverse is what makes a TCAD result reach a circuit design flow at
all, and it is the one item on 4c.2's list whose every ingredient is
already built and gated:

| need | existing, landed code |
|---|---|
| the compact models to fit INTO | `pytcad/circuit.py`: `Diode` (Shockley), `MOSFET1` (level-1 Shichman-Hodges) |
| a simulator to round-trip through | `pytcad/circuit.py`: `Circuit.dc_operating_point` |
| reference I-V from real TCAD | `pytcad/device.py::Device1D.iv_sweep`; `pytcad/mosfet.py::build_mosfet` / `id_vg_sweep` |
| optimizer + RMS goal + finite-penalty pattern | `workbench/calibration.py`: `GoalFunction`, Nelder-Mead, `UNREACHABLE_PENALTY` |
| Vth / SS seed extraction | `pytcad/characterization.py` |

So this milestone is assembly of landed machinery, not new physics.

## 2. Scope, and what is deliberately NOT in it

IN: parameter extraction for two compact models (`Diode`, `MOSFET1`),
SPICE `.MODEL` card emission, a minimal reader so the round-trip is
genuine, and a closed-loop gate that re-simulates the extracted model
through `circuit.py` and compares back to the originating TCAD curve.

OUT (named, so nobody assumes otherwise):
  * BSIM-class models, temperature scaling, geometry scaling.
  * AC / C-V parameter extraction (M18 is library-only for 1D).
  * Any external SPICE binary or network access. The round trip closes
    entirely inside this repo, through `circuit.py`'s own MNA solver.
  * A performance claim. The obvious pitch is that an extracted
    element replaces `DeviceStamp`'s TWO full `Device1D.solve_bias`
    calls PER Newton iteration. That is real, but
    `Architecture_Master_Plan.md` section 36 forbids quoting a speedup
    that did not come from a benchmark run. Either it earns a
    `benchmarks/cases.py` row or the number is not quoted. This slice
    does not quote it.
  * Phase 4: a GUI panel and a `workbench/workflow.py` deck statement.

NO FROZEN-CORE EDIT. Everything lands in `workbench/compact.py` and
`tests/test_m38_compact_model.py`. In particular `pytcad/mosfet.py` has
an `id_vg_sweep` but no `id_vd_sweep`; rather than amend a `pytcad/*.py`
file under the M11-S3 mechanism for what is a bare `solve_bias` loop,
the Id-Vd family driver lives in the workbench module and drives
`Device2D` from OUTSIDE -- the pattern `transient.py` and
`continuation.py` already established.

NOT added to `tests/test_model_benchmarks.py`. That house rule covers a
new PHYSICS MODEL; this is parameter extraction from models that already
carry their own published-law gates (`tests/test_m27_circuit.py` checks
`Diode` against Shockley and `MOSFET1` against the square law by hand).
Stated here so the rule is consciously scoped, not silently skipped.

## 3. Honest limits, stated BEFORE implementation

These are properties of the target models, already disclosed in
`circuit.py`'s own honesty clause. They constrain what an extraction can
truthfully claim, so they are written down first rather than discovered:

1. **`MOSFET1` has no subthreshold conduction at all.** `MOSFET1.stamp`
   returns EXACTLY `Id = 0.0` for `vov <= 0`. A log-scale Id-Vg fit
   across threshold is therefore not merely inaccurate, it is
   ill-posed. The MOSFET extraction is defined on STRONG INVERSION
   ONLY, refuses a fit window containing sub-threshold points, and
   reports a LINEAR-space relative RMS over the fitted window. A
   log-space error figure is never reported for the MOSFET, because it
   would imply subthreshold agreement the model cannot have.
2. **`MOSFET1` has no body effect** (source doubles as body). Extraction
   is valid only at the Vbs the reference curve was taken at.
3. **Units do not match across the three layers and this is
   load-bearing.** `Device1D.current_density` returns A/cm^2;
   `Device2D.terminal_current` returns A/cm (per cm of width);
   `circuit.py` elements are in AMPERES. Every extractor therefore takes
   its scaling factor as a REQUIRED argument (no default) and records it
   on the result, mirroring `DeviceStamp`'s existing explicit
   `area_cm2=1e-4`. A silent default here would be exactly the class of
   bug this project's gotcha list is made of.
4. **A fit reports its own residual and never hides it.** Following
   `calibration.py`'s G-NOCONVERGE precedent, an extraction that cannot
   converge says so rather than returning a fabricated "best fit".

## 4. Gates

`tests/test_m38_compact_model.py`. Written red first.

### Phase 1 -- diode

  G1-SELF   Generate an I-V from a KNOWN `circuit.Diode` (Is, N given),
            extract, recover both parameters to < 1% relative. This is
            the gate that proves the fitter is capable of failing.
  G1-TCAD   Fit a real `Device1D` pn-diode `iv_sweep` over V in
            [0.35, 0.60] V. Assert the ideality factor lands in
            [0.9, 1.1]. Justification, not a round number:
            `tests/test_validation.py::test_ideal_diode_law` already
            gates this same fixture's local ideality to within 2% of
            1.0 for V > 0.3 V; a global fit over a window is a weaker
            statement than a pointwise one, so the band is widened to
            10% rather than tightened.
  G1-SCALE  The extracted `Is` scales exactly linearly with the
            supplied area factor, and `N` does not move. (Guards the
            section-3.3 unit boundary.)
  G1-REFUSE Reverse-bias-only input, a single point, or non-finite
            input RAISES rather than returning a fit.

### Phase 2 -- MOSFET level-1

  G2-SELF   Generate Id-Vg and Id-Vd families from a KNOWN `MOSFET1`
            through `Circuit.dc_operating_point`, extract, recover
            Vt0, kp*W_L and lambda to < 1% relative.
  G2-TCAD   Fit a real 2D `Device2D` MOSFET (`mosfet.build_mosfet`).
            Assert the fitted-window linear relative RMS is below the
            bound this document records once measured, and that Vt0
            agrees with `characterization.extract_vth_constant_current`
            on the same curve.
  G2-REFUSE A fit window containing sub-threshold points is REFUSED
            (section 3.1), not silently fitted.

### Phase 3 -- netlist and the closed loop

  G3-EMIT   `to_netlist` emits a syntactically real SPICE `.MODEL`
            card for each model kind.
  G3-ROUND  `from_netlist(to_netlist(p)) == p` to full float
            round-trip precision. A real reader exists precisely so
            this gate cannot be structurally incapable of failing.
  G3-CLOSED THE HEADLINE GATE. Take the Phase 1 TCAD fit, emit a
            netlist, read it back, build a `circuit.Circuit` from the
            recovered parameters, sweep its `VSource` through
            `dc_operating_point`, and compare the resulting current
            against the ORIGINAL TCAD curve within the tolerance
            Phase 1 measured. TCAD -> parameters -> text -> parameters
            -> circuit simulation -> back to the TCAD curve.

## 5. Measured results (2026-09-10, all figures from RUN gates)

`tests/test_m38_compact_model.py`: **33 passed** in 7.4 s, no warnings.

### Phase 1 -- diode

| gate | result |
|---|---|
| G1-SELF | Is 3.7e-13 / N 1.15 recovered to < 1e-2 rel, rms_log_error 1e-6 |
| G1-SELF (wrong seed) | seed 1e-8 / 1.6 against truth 1e-14 / 1.0 still converges to < 1% |
| G1-SCALE | Is exactly linear in the scale factor; N unchanged to 1e-6 |
| G1-TCAD | `Device1D` pn diode, V in [0.35, 0.60]: **N = 1.0031**, Is = 5.418e-15 A at 1e-4 cm^2 (J0 = 5.42e-11 A/cm^2), **rms_log_error = 1.57e-3** |

G1-TCAD's N is inside the 2%-of-unity band `test_validation.py`
independently gates the SAME fixture's pointwise ideality to, which is
the strongest available external confirmation of the fit.

### Phase 2 -- MOSFET level-1

Self-consistency recovers Vt0/kp*W_L/lambda to rel 1e-2 with
rel_rms_error 2.6e-13, for BOTH channel polarities, and the closed-form
ELR seed alone (refine=False) lands inside 5% before any optimization.

G2-TCAD, a real `Device2D` MOSFET (Lg = 1 um, tox = 10 nm, Na = 5e16,
19 fitted points across one Id-Vg and one Id-Vd curve):

| quantity | value |
|---|---|
| Vt0 | 0.168826 V |
| kp*W_L | 2.8246e-4 A/V^2 (W = 1 um) |
| lambda | 0.041353 /V |
| fitted-window relative RMS | **2.90%** |

Cross-check that shares NO code with the extractor: the textbook
long-channel threshold `Vfb + 2*phi_f + Qdep/Cox`, built from
`moscap.flatband_voltage` and `materials.SILICON`, gives **0.167299 V**
-- the extracted Vt0 agrees to **0.91%**. A level-1 model reproducing a
2D drift-diffusion device to 2.9% across triode and saturation, with a
threshold within 1% of closed-form MOS theory, is the honest headline of
this milestone.

### Phase 3 -- netlist and the closed loop

Round-trip is EXACT (`from_netlist(to_netlist(p)) == p`) for both model
kinds, including the SPICE VTO sign flip for a PMOS. The closed loop
reproduces the fitted curve to < 1e-4 relative wherever the guard in the
next section is negligible, and to < 1e-4 relative for the MOSFET across
both curves.

## 5b. Two real findings from the hard-debug pass

Both were found by RUNNING the thing, not by reading it, and both are
now permanent gates rather than comments:

1. **`circuit.Circuit` puts a 1e-12 S shunt to ground on EVERY node**
   (`G += np.eye(size) * 1.0e-12`, its floating-node guard). A terminal
   current below roughly `1e-12 * V` amperes is therefore dominated by
   that guard, not by the element: a 1e-4 cm^2 diode at 0.25 V passes
   2.5e-14 A against 2.5e-13 A of guard leakage -- a **10x** error that
   first looked like a broken fit. The closed-loop gate now asserts a
   PREDICTION rather than a tolerance: the only permitted discrepancy is
   exactly `MNA_LEAKAGE_G * V / I`, so an error from any other cause
   fails the gate even where the guard is large. `mna_resolvable()`
   exposes the floor at the API, and one gate demonstrates it live.
2. **The ELR tangent must be a windowed least-squares fit, not a
   pointwise derivative.** The first implementation took the tangent at
   the single `np.argmax(np.gradient(...))` point. Adversarially probed
   with 5% multiplicative noise, that argmax landed on the wrong point
   and moved the extracted threshold by 0.6 V -- far enough to trip the
   strong-inversion refusal on data the fit can actually handle. Now the
   tangent is least-squares fitted over every point within
   `ELR_PLATEAU_FRAC = 0.8` of peak gm. On a noiseless level-1 triode
   curve gm is exactly constant, so the plateau is the whole curve and
   the seed stays exact; with 5% noise the extraction recovers Vt0 to
   2.6%, kp*W_L to 2.0% and lambda to 2.7%.

Also found: `simulate_diode_iv` inherits two hard limits of
`circuit.py`, both now demonstrated by a gate rather than asserted in
prose -- the Newton step clamp applies to the source BRANCH CURRENT (so
a bias drawing >> `max_dv` amperes is unreachable; `max_dv` is now a
parameter), and `Diode.stamp` clips the voltage it LINEARIZES at to
1.5 V, above which no `max_dv` converges.

## 6. Adversarial probe pass

Before commit, per the standing workflow:
  * Sweep each extracted parameter across orders of magnitude and
    confirm the predicted curve MOVES. This project has twice shipped
    a parameter that looked elegant and was a numerical no-op (M14's
    D_it and S_n/S_p); the tell both times was that no branching was
    needed.
  * Start the optimizer from a deliberately wrong seed and confirm it
    either converges to the same answer or reports honest
    non-convergence -- never a silent bad fit.
  * Confirm the refusal paths (G1-REFUSE, G2-REFUSE) fire on the exact
    inputs they name, not merely on obviously malformed ones.
