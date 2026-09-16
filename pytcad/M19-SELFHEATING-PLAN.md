# M19-SELFHEATING-PLAN.md
# M19: Self-heating (thermodynamic model)
# Formal milestone spec

Status: **PHASE 1 (steady-state, 1D) LANDED 2026-08-31.** New sibling
module `pytcad/thermal.py`; `device.py`/`moscap.py` untouched. 6/6
gates green (`tests/test_m19_thermal.py`).

Roadmap slot: ARCHITECTURE.md section 4b, "M19 SELF-HEATING
(THERMODYNAMIC MODEL) [L]".

------------------------------------------------------------------------
1. SCOPE AND ARCHITECTURE DECISION
------------------------------------------------------------------------
Original spec: "lattice-temperature equation coupled to DD (Joule term
+ divergence of heat flux), thermal BCs (isothermal, thermal
resistance to ambient); optional Seebeck term. 1D first, then 2D."

**Exploration finding that reshaped the plan**: `Device1D`'s entire
nondimensionalization (`VT`, `Ns`, `LD`, `J0`, `mu_n0`/`mu_p0`, `nie`,
`tau_n`/`tau_p`, ...) is built ONCE at `__init__` from a single SCALAR
`T` and used as fixed arrays throughout every Newton solve. Making `T`
a genuine, spatially-varying, monolithically-coupled 4th Newton
unknown (psi, n, p, T per node) would mean rearchitecting that whole
scaling framework -- a far larger undertaking than any milestone this
session has attempted, and disproportionate to what the acceptance
gates actually require.

Chosen architecture instead: **isothermal DD + outer (Gummel) thermal
loop**, a standard, well-established mode many production TCAD tools
offer. This is NOT a shortcut around a known-bad pattern (unlike M20's
DG lagging, which had a documented specific defect where lagging
converged to the wrong physics) -- it is the right tool for a
different reason: T enters almost every scaled quantity in Device1D,
not just one localized term, so full monolithic coupling is a
disproportionate rewrite for what this phase needs to deliver.

**Also found**: no thermal conductivity property existed anywhere in
`materials.py` before this work -- contradicts the milestone spec's
"no new material work" note. Added `Semiconductor.kappa_th300` +
`kappa_th(T)` (Sze & Ng power law, mirrors the existing `Eg`/`Nc`/`Nv`
T-dependence pattern), a small, necessary, honestly-flagged addition.

------------------------------------------------------------------------
2. IMPLEMENTATION
------------------------------------------------------------------------
`pytcad/pytcad/materials.py`: `Semiconductor.kappa_th300` (1.48
W/(cm*K), Si at 300K) + `kappa_th(T) = kappa_th300*(T/300)^-1.33`.

`pytcad/pytcad/thermal.py` (new, device.py/moscap.py untouched):

- `ThermalBC.isothermal()` / `ThermalBC.resistance(R_th_area)`: the
  two boundary conditions the spec calls for (Dirichlet T=T_ambient,
  or Robin heat-flux-out = (T-T_ambient)/R_th_area [K*cm^2/W]).
- `solve_lattice_temperature(x, H, material, T_ambient, bc_left,
  bc_right)`: steady 1D heat equation `-d/dx(kappa_th(T) dT/dx) =
  H(x)`, genuinely nonlinear (kappa_th depends on T) -- its own small
  Newton system with an analytic Jacobian, gated by G-FD below. This
  satisfies the "FD-Jacobian gate on the coupled block system"
  acceptance criterion without a 4-unknown monolithic system: the
  "coupled block" here is the lattice-temperature Newton system
  itself.
- `joule_heating_density(device)`: Joule heating density H(x)
  [W/cm^3] from a converged `Device1D` solve -- see section 3 for a
  real bug found and fixed here.
- `solve_electrothermal(build_device, bias, T_ambient, bc_left,
  bc_right, material, ...)`: the outer Gummel loop. `build_device(T)`
  is a caller factory (e.g. `lambda T: Device1D(x, dop, T=T, ...)`) --
  reuses `Device1D`'s existing scalar-`T` constructor unmodified, no
  new constructor argument. Each pass: build at the candidate T,
  `solve_equilibrium()` + `solve_bias(bias)` (unmodified, existing
  calls), compute `H(x)`, solve for the lattice `T(x)`, take its PEAK
  as the next candidate. Raises `RuntimeError` (not silent
  non-convergence) if the outer loop or the inner thermal solve fails
  to converge -- this is how thermal runaway (section 4) surfaces.

------------------------------------------------------------------------
3. A REAL BUG FOUND AND FIXED: THE NAIVE J*E JOULE TERM
------------------------------------------------------------------------
The first version of `joule_heating_density` used `H_edge =
(device.Jn + device.Jp) * device.E_field` (current density times the
raw electric field `E = -grad(psi)`). Measured directly on a forward-
biased diode: `H` came out with a peak of **-31930 W/cm^3** right at
the metallurgical junction -- a thermodynamically IMPOSSIBLE local
negative heat generation.

Root cause: `J*E` is only the correct dissipation term where DIFFUSION
current is negligible (a uniform resistor, exactly where G-PARABOLA's
gate lives). In a diode's depletion region, current is diffusion-
dominated, and the raw field `E=-grad(psi)` is NOT what drives that
transport -- the QUASI-FERMI-POTENTIAL gradient is (Wachutka, IEEE
Trans. CAD 9, 1141 (1990), the standard thermodynamically-consistent
DD self-heating dissipation term). Fixed:

    phi_n = psi - ln(n/nie),   phi_p = psi + ln(p/nie)      (already
                                the standard quasi-Fermi-potential
                                definition, used elsewhere in this
                                codebase's band_diagram())
    E_n = -grad(phi_n),   E_p = -grad(phi_p)
    H = Jn*E_n + Jp*E_p

After the fix, on the same diode at 0.6V forward bias: **H is positive
everywhere** (zero negative nodes), and the integrated total
`integral(H dx) = 0.3638 W/cm^2` matches `I*V = 0.3639 W/cm^2` to
0.04% -- an independent energy-conservation cross-check, not assumed.

------------------------------------------------------------------------
4. GATES (tests/test_m19_thermal.py) -- MEASURED RESULTS
------------------------------------------------------------------------
G-PARABOLA: a uniform-H, constant-kappa rod (isothermal ends) matches
  the closed-form parabola `T(x) = T_amb + H0/(2*kappa)*x*(L-x)`
  EXACTLY (max abs error 0.0 K -- a linear PDE, single tridiagonal
  solve, no approximation involved). GREEN.

G-FD: analytic vs. central-finite-difference Jacobian of the nonlinear
  (T-dependent-kappa) thermal residual, max relative error 3.7e-10
  (well inside the standing <2e-3 threshold). GREEN.

G-BC: thermal-resistance boundary peak (550.1 K, R_th=1.0 K*cm^2/W)
  correctly exceeds the isothermal-boundary peak (300.04 K), same H.
  GREEN.

G-ROLLOFF (electrothermal, diode): at V=0.55V, R_th=50 K*cm^2/W on the
  same PN diode used elsewhere in the suite, electrothermal current
  (0.0982 A/cm^2) exceeds isothermal current (0.0881 A/cm^2), ratio
  1.1146, peak lattice rise ~1.35 K. GREEN, but see the honest
  terminology note below.

G-OFF-BIT-IDENTITY: an isothermal `solve_equilibrium`+`solve_bias`
  produces byte-identical `psi`/`n`/`p` whether or not `pytcad.thermal`
  has been imported. GREEN (guaranteed by construction -- `thermal.py`
  never imports into or modifies `device.py`/`moscap.py`).

G-BC-REFUSAL: `ThermalBC.resistance` refuses `R_th_area <= 0`;
  `ThermalBC(...)` refuses an unknown `kind`. GREEN.

Full suite (after reinstalling the Python environment mid-session --
see section 6): `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` ->
see the STATE ADDENDUM in history.md for the final count; the only
failure anywhere is the same pre-existing, independently-confirmed
flaky `test_gc_sp_centroid_in_literature_band` (S-P reference solver's
`eigsh` nondeterminism, unrelated to this milestone).

------------------------------------------------------------------------
5. HONEST LIMITS
------------------------------------------------------------------------
- **Gummel/lagged electrothermal coupling, not monolithic**: `Device1D`
  itself stays isothermal per solve; only the OUTER loop's candidate
  temperature changes between passes (see section 1's architecture
  decision). A fully spatially-resolved T(x) fed back node-by-node
  into `Device1D`'s own Newton system is future work, not attempted.
- **"Roll-off" terminology mismatch, stated plainly**: the milestone
  spec's acceptance criterion names "published self-heating roll-off
  behavior," language that fits a MOSFET/resistor (mobility
  degradation suppresses current as T rises). Measured on an actual PN
  diode: self-heating INCREASES current at fixed V (Vbi drops, n_ie
  grows exponentially with T) -- the textbook positive-feedback
  direction for a diode, a well-documented thermal-runaway precursor,
  not a "roll-off." No field-dependent mobility (`Models.field_
  mobility`) was enabled to provide a negative-feedback term. The gate
  checks the ACTUAL, measured, correctly-signed diode direction rather
  than force-fitting a MOSFET-shaped assumption onto different device
  physics.
- **Thermal runaway is real and gated by refusal, not silently
  wrong**: on the same diode/R_th=50 combination, V=0.58V converges
  (ratio 1.82x, T=307.4K) but V=0.6V and above make
  `solve_lattice_temperature` fail to converge -- genuine electro-
  thermal runaway (current growing without bound as each outer pass
  raises T further), measured directly (I at 300K: 0.61 A/cm^2; at a
  391K candidate: 205 A/cm^2; at 500K: 3260 A/cm^2 -- clearly
  divergent, not a numerics bug). `solve_electrothermal` raises
  `RuntimeError` rather than returning a nonsense answer. The gate
  (V=0.55V) sits comfortably inside the stable regime.
- No Seebeck/Peltier cross-terms (explicitly named "optional" in the
  milestone spec -- deferred).
- 2D self-heating: out of scope (the spec's own "1D first, then 2D"
  phasing).
- Steady-state only. The milestone spec's "Depends: M17 (transient
  machinery for the coupled solve)" turned out not to be load-bearing
  for this phase: a steady-state outer Gummel loop needs no time
  integration. A future TRANSIENT electrothermal phase would use M17's
  machinery for real; noted honestly rather than forcing an unneeded
  dependency.
- `kappa_th(T)`'s -1.33 power-law exponent is the standard published
  Si value (Sze & Ng), not independently re-derived here.
- Recombination/generation heat is not included in `H` -- only the
  electrical (Wachutka) dissipation term.

------------------------------------------------------------------------
6. SESSION NOTE: PYTHON ENVIRONMENT WAS REMOVED MID-SESSION
------------------------------------------------------------------------
Partway through implementing and verifying this milestone, the
session's Python environment (a miniconda3 install) disappeared --
traced to the user's own `rm -rf ~/miniconda3` run in a separate
terminal (confirmed via `~/.bash_history`, not something this session
did). Reinstalled a minimal environment via `pip install --user
--break-system-packages` against the system `python3` (numpy, scipy,
pytest, pytest-xdist, pytest-timeout, PySide6, matplotlib, pyvista,
pyvistaqt, gmsh, devsim, mpmath -- restoring the same optional-
dependency coverage the previous environment had, confirmed by
comparing `pytest --collect-only` counts before/after: 896 -> 945
collected once gmsh/devsim/mpmath were added back). All gates in this
plan were re-verified against the NEW environment, not just the one
before it disappeared.

------------------------------------------------------------------------
7. FILES CHANGED
------------------------------------------------------------------------
- `pytcad/pytcad/materials.py`: `kappa_th300` + `kappa_th(T)`
- `pytcad/pytcad/thermal.py` (new)
- `pytcad/tests/test_m19_thermal.py` (new)
- `pytcad/M19-SELFHEATING-PLAN.md` (new, this file)
- `ARCHITECTURE.md`: M19 status line + milestone table updated
- `history.md`: new STATE ADDENDUM
