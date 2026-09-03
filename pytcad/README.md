# PyTCAD — numerical core

This is the numerical-core package: process simulation and self-
consistent drift-diffusion device simulation in 1D, 2D and 3D. The
project-level README one directory up covers the Semiconductor
Workbench layer, the desktop GUI, the full validation philosophy, and
the illustrated user guide in `docs/user-guide/`.

A compact, readable, **validated** TCAD toolkit in Python — process simulation and self-consistent drift-diffusion device simulation in 1D, 2D (with a real MOSFET), and 3D — structured the way commercial TCAD is structured (Sentaurus Process → Sentaurus Device, Silvaco Athena → Atlas).

Roughly 3,000 lines for the numerical core below (1D + 2D + 3D, including heterojunction materials and trap-assisted tunneling). No black boxes: every model states its equation, its provenance (theory / measurement / empirical fit), and where it breaks.

```
pytcad/ (this package)
  constants.py   physical constants, thermal voltage
  materials.py   ni(T), mobility, lifetimes, bandgap narrowing, recombination;
                 Si, Ge, GaAs heterostructure parameter sets
  mesh.py        non-uniform meshing + Debye-length adequacy check
  process.py     implantation, diffusion, Deal-Grove oxidation
  device.py      drift-diffusion: Poisson + both continuity equations;
                 per-node heterojunction materials (M11); Hurkx trap-
                 assisted tunneling (M12); impact ionization (M15);
                 local Kane/Hurkx BTBT (M16); density-gradient quantum
                 correction in equilibrium (M20, coupled-Newton); surface
                 recombination velocity S_n/S_p (M14)
  transient.py   time-dependent drift-diffusion (M17): backward-Euler/
                 theta-scheme, step/ramp/pulse waveforms, driving
                 Device1D through its own residual/Jacobian externally
                 (continuation.py's pattern) -- device.py never touched
  ac.py          small-signal AC analysis for Device1D (M18): complex
                 admittance Y(f)/C(f)/G(f) from the converged DC
                 Jacobian + a capacitive block, same external-driver
                 pattern as transient.py; 1D only, library-only (no GUI)
  thermal.py     steady-state 1D self-heating (M19): isothermal DD +
                 outer Gummel loop against a nonlinear lattice heat
                 equation; device.py untouched
  btbt.py        BTBT coefficients A, B (Hurkx Table I silicon), pure module
  moscap.py      MOS capacitor, quasi-static C-V, interface traps (M14);
                 density-gradient quantum correction (M20, coupled-Newton,
                 hard-wall Si/SiO2 interface BC)
  dg.py          M20 analysis layer: DG quantum potential, Airy triangular-
                 well reference, Schrödinger-Poisson inversion-layer solver
  linsolve.py    direct/GMRES/BiCGStAB + ILU, node-block-Jacobi and Schur
                 preconditioners (M22)
  fermi.py       complete Fermi-Dirac integrals F_{1/2}/F_{-1/2},
                 inverse, FD ni, tabulated fast path (M13, COMPLETE:
                 wired through device.py/device2d.py/device3d.py/
                 moscap.py)
  mesh2d.py      tensor-product 2D mesh + Debye-length adequacy check
  device2d.py    2D drift-diffusion: box-integration Poisson + continuity;
                 Lombardi CVT surface mobility (M14); S_n/S_p surface
                 recombination velocity for arbitrary contact shapes (M14);
                 unstructured=True (M21 phase 3d): a gmsh triangle mesh,
                 thin wrapper around unstructured_poisson.py/
                 unstructured_dd.py, homojunction-only
  transient2d.py time-dependent drift-diffusion for Device2D (M17),
                 same external-driver pattern as transient.py
  mosfet.py      2D MOSFET builder + Id-Vg sweep (structured mesh only)
  mesh3d.py      tensor-product 3D mesh + Debye-length adequacy check
  device3d.py    3D drift-diffusion: box-integration Poisson + continuity
  gmsh_mesh.py, region_resolver.py, unstructured_assembly.py,
  unstructured_poisson.py, unstructured_dd.py
                 M21 phase 3: unstructured (gmsh triangle) 2D meshing --
                 region/contact resolution, dual-cell + TPFA flux
                 geometry, Poisson-equilibrium and coupled SG bias
                 solves; standalone, directly tested, and wired into
                 Device2D(unstructured=True) above
examples/        p-n diode, full process flow, MOS C-V, 2D MOSFET Id-Vg,
                 3D-reduces-to-2D validation
tests/           analytic-limit validation + published-value physics
                 benchmarks + headless GUI tests -- fast suite
                 (`-m "not slow"`) currently 1028 passed, 1 xfailed,
                 0 known failures -- the M20 Schrödinger-Poisson
                 reference solver's once-flaky eigensolver test is now
                 fixed (see M20-DENSITY-GRADIENT-PLAN.md section 7.6)
../workbench/    domain layer: materials library (Si, Ge, GaAs, InGaAs,
                 AlGaAs), model catalog, solver backends, tunneling and
                 impact-ionization physics, deck front end
../gui/          PySide6/QML desktop app
```

---

## 1. The device equations

We solve the steady-state van Roosbroeck system self-consistently:

$$\frac{d}{dx}\left(\varepsilon \frac{d\psi}{dx}\right) = -q\left(p - n + N_D^+ - N_A^-\right)$$

$$\frac{dJ_n}{dx} = +qR, \qquad \frac{dJ_p}{dx} = -qR$$

with the drift-diffusion constitutive relations and the Einstein relation $D = \mu k_BT/q$:

$$J_n = q\mu_n n E + qD_n \frac{dn}{dx}, \qquad J_p = q\mu_p p E - qD_p \frac{dp}{dx}$$

| Symbol | Meaning | Units |
|---|---|---|
| $\psi$ | electrostatic potential | V |
| $n, p$ | electron / hole density | cm⁻³ |
| $J_n, J_p$ | current densities | A/cm² |
| $R$ | net recombination rate | cm⁻³s⁻¹ |
| $N_D^+, N_A^-$ | ionised donor / acceptor density | cm⁻³ |
| $\varepsilon$ | permittivity | F/cm |
| $V_T = k_BT/q$ | thermal voltage (25.852 mV at 300 K) | V |

### Assumptions, and where each one fails

| Assumption | Fails when |
|---|---|
| Boltzmann statistics (default; `Models(fd=True)` available) | doping ≳ 10¹⁹ cm⁻³ (degeneracy) — the code warns you unless FD is enabled |
| Full dopant ionisation | cryogenic temperature; deep dopants |
| Classical (no quantisation; `MOSCapacitor(dg=True)` / `Models(dg=True)` available, equilibrium) | thin-oxide inversion layers: real charge centroid sits ~1 nm deep, so $C_{max}$ is overestimated by 10–20% |
| Local mobility model | quasi-ballistic transport in sub-30 nm channels |
| Local impact-ionisation / BTBT models (`Models(impact=True)`, `Models(btbt=True)` available, 1D) | avalanche breakdown needs voltage continuation; nonlocal tunneling paths (GIDL at large reverse bias), direct gate leakage below ~2 nm oxide |
| Isothermal by default | steady-state 1D self-heating (M19, `pytcad.thermal`) is available as an isothermal-DD + outer Gummel thermal loop, not a monolithic coupled solve; 2D and transient self-heating are not built |
| Steady-state solve is the default | time-domain (M17, `transient.py`/`transient2d.py`) is available for 1D/2D; small-signal AC (M18, `pytcad.ac`) is available for 1D, library-only (no GUI exposure yet) |

---

## 2. Numerics — why it's built this way

**Scharfetter–Gummel currents.** The interface current is

$$J_{n,i+1/2} = \frac{qD_n}{h}\Big[n_{i+1}B(\delta) - n_i B(-\delta)\Big], \qquad \delta = \frac{\psi_{i+1}-\psi_i}{V_T}, \qquad B(x)=\frac{x}{e^x-1}$$

This integrates the drift-diffusion equation *exactly* under the assumption that $J$ and $E$ are constant across one cell. It is the single most important numerical ingredient. **Common mistake:** central-differencing the drift term. That scheme oscillates and produces negative carrier densities as soon as the potential drop across a cell exceeds $\sim 2V_T$ (52 mV) — which is true essentially everywhere inside a depletion region. Correctness here is not a refinement; it is the difference between a working solver and one that diverges.

**Scaling.** Newton on raw variables is hopeless ($\psi \sim 1$, $n \sim 10^{20}$, $R \sim 10^{25}$). We use de Mari-style scaling with one deviation: concentrations are scaled by the **peak doping**, not by $n_i$. Scaling by $n_i$ makes the majority density $\sim 10^7$ in scaled units, and the Poisson residual then loses ~8 significant digits to cancellation — the residual stalls at $10^{-3}$ and never converges to tolerance. Scaling by $N_{peak}$ keeps every majority term at order unity.

$$\psi \to \psi/V_T,\quad n,p \to n/N_{peak},\quad x \to x/L_D,\quad L_D = \sqrt{\varepsilon V_T/(qN_{peak})}$$

**Newton with an analytic Jacobian.** Fully coupled, block-tridiagonal, sparse, with damping on $\Delta\psi$ and multiplicative clamping on $n,p$ so densities stay positive. `test_jacobian_matches_finite_differences` checks every derivative against finite differences — if you extend the physics, run that test first.

**Convergence is judged on the update, not the residual.** The Poisson residual subtracts terms of order $1/h^2$ and hits a floating-point noise floor well above any sensible tolerance. Watching $|F|$ instead of $|\Delta u|$ makes a converged solve look like a failure.

**Meshing.** `mesh.check_mesh` reports the worst $h/L_D$; keep it below ~1. A uniform mesh fine enough for the junction is wastefully fine in the bulk, and a uniform mesh coarse enough for the bulk silently gets the built-in field wrong.

---

## 3. Physical models

| Model | Form | Provenance |
|---|---|---|
| $n_i(T)$ | $\sqrt{N_cN_v}\,e^{-E_g/2k_BT}$, Varshni $E_g(T)$ | theory + measured band parameters |
| Mobility vs doping | Caughey–Thomas: $\mu_{min} + \frac{\mu_{max}-\mu_{min}}{1+(N/N_{ref})^\alpha}$ | **empirical fit** |
| Velocity saturation | Canali: $\mu_0/[1+(\mu_0E/v_{sat})^\beta]^{1/\beta}$ | **empirical fit**, applied lagged |
| SRH | $\dfrac{np-n_{ie}^2}{\tau_p(n+n_{ie})+\tau_n(p+n_{ie})}$ | theory (mid-gap traps); $\tau$ from **fit** |
| Auger | $(C_nn+C_pp)(np-n_{ie}^2)$ | measured $C_n, C_p$ |
| Bandgap narrowing | Slotboom: $\Delta E_g = E_0[\ln(N/N_0)+\sqrt{\ln^2(N/N_0)+\tfrac12}]$ | **empirical fit** to BJT data |
| Deal–Grove | $x^2 + Ax = B(t+\tau)$ | theory; $A,B$ Arrhenius **fits** |
| Fermi-Dirac statistics | $n = N_c F_{1/2}(\eta)$ with nu-factor generalized SG (`Models(fd=True)`); incomplete ionization (`Models(incomplete_ion=True)`) | theory; gated vs independent roots and published freeze-out curves |
| Impact ionization | $G = [\alpha_n(E)\lvert J_n\rvert + \alpha_p(E)\lvert J_p\rvert]/q$, van Overstraeten–de Man (`Models(impact=True)`, 1D) | measured coefficients; lagged-source coupling |
| Band-to-band tunneling | $G = AF^2e^{-B/F}$ local Kane/Hurkx (`Models(btbt=True)`, 1D) | Hurkx Table I Si coefficients |
| Surface mobility | Lombardi CVT $1/\mu = 1/\mu_{CT}+1/\mu_{ph}+1/\mu_{SR}$ (`Models(surface_mobility=True)`, 2D) | Lombardi 1988; simplified phonon term, uncalibrated -- blocked on a paywalled source (M14 G-A) |
| Surface recombination velocity | Robin BC $J_n\cdot\hat n = qS_n(n-n_0)$ (mirrored for holes), any ohmic contact (`Models(S_n=...)`/`S_p=...`, Device1D and Device2D, arbitrary 2D contact shape) | theory; M14 |
| Density gradient | $\Lambda = -\frac{\gamma\hbar^2}{2m^\ast q}\frac{(\sqrt n)''}{\sqrt n}$, $n \to n\,e^{-\Lambda/V_T}$ (`Models(dg=True)` / `MOSCapacitor(dg=True)`, equilibrium) | Ancona–Stafford 1999; gated vs own S–P solve + Airy analytics |

**Mobility gotcha:** the argument is the *total* ionised impurity concentration $N_A + N_D$, not the net doping $|N_D - N_A|$. Using the net value badly overestimates mobility in compensated regions. `Device1D` takes `Ntotal` separately for exactly this reason.

---

## 4. Validation

All tests pass as part of the project-wide fast suite (1028 passed,
1 xfailed, 0 known failures -- the once-flaky M20 eigensolver test is
now fixed, see M20-DENSITY-GRADIENT-PLAN.md section 7.6 -- zero new
warnings); every result is classified as literature benchmark,
analytical validation, model parameterization, or numerical
regression — see the project README. Selected results for an abrupt 10¹⁷/10¹⁷ Si junction, 2 µm long, 300 K:

| Quantity | PyTCAD | Analytic | |
|---|---|---|---|
| Built-in potential | 0.8302 V | 0.8300 V | $V_T\ln(N_AN_D/n_i^2)$ |
| $J$ at 0.5 V forward | 1.280×10⁻² A/cm² | 1.321×10⁻² A/cm² | short-base ideal diode |
| Ideality factor (0.3–0.75 V) | 1.003 | 1 | |
| Current continuity $\sigma(J_n{+}J_p)/\bar J$ | < 10⁻⁸ | 0 | |
| Mesh refinement (2× finer) | < 3% change | — | |

MOS-C, 5 nm oxide, n⁺poly on p-Si 10¹⁷:

| | PyTCAD | Depletion approx. |
|---|---|---|
| $C_{max}$ | 0.672 µF/cm² | $C_{ox}$ = 0.691 |
| $C_{min}$ | 0.096 µF/cm² | 0.087 |
| $V$ at $C_{min}$ | −0.04 V | $V_{th}$ = +0.09 V |

The reverse-leakage test is worth reading: the current does **not** saturate. It grows as roughly $(V_{bi}+V)^{1.16}$, because the width over which *both* carriers drop below $n_i$ — and hence $R \to -n_i/(\tau_n+\tau_p)$ — widens faster than the depletion width itself at moderate bias. The solver reproduces this and $J = q\int(-R)\,dx$ closes to 3%.

---

## 5. Usage

```python
import numpy as np
from pytcad import Device1D, Models, process
from pytcad.mesh import graded_mesh, check_mesh

# --- structure: abrupt p-n junction, 2 um, junction at 1 um
x   = graded_mesh(2e-4, [1e-4], h_min=1e-8, h_max=1e-6)   # cm
dop = np.where(x < 1e-4, -1e17, 1e17)                     # cm^-3, + is n-type
check_mesh(x, dop)

dev = Device1D(x, dop, T=300.0, models=Models(bgn=True, auger=True))
J   = dev.iv_sweep(np.arange(0, 0.75, 0.05))              # A/cm^2

Ec, Ev, EFn, EFp = dev.band_diagram()
n, p, E = dev.n_cm3, dev.p_cm3, dev.E_field
```

Process flow, feeding the device solver:

```python
C   = process.implant(x, "P", energy_keV=50, dose=3e14)
C   = process.diffuse_numeric(x, C, "P", T_C=950, t_s=1800)
xj  = process.junction_depth(x, C - 1e16)
tox = process.oxide_thickness(900.0, 1.0, ambient="dry")   # um
dev = Device1D(x, C - 1e16, Ntotal=C + 1e16)
```

MOS capacitor:

```python
from pytcad import MOSCapacitor
mos = MOSCapacitor(Nsub=-1e17, tox_cm=5e-7, gate="n+poly", Qf=1e12)
phis, Qg, C = mos.cv_sweep(np.linspace(-2, 2, 201))
print(mos.analytic_landmarks())     # phi_F, W_max, C_ox, C_min, V_th, V_FB
```

Run everything:

```bash
python examples/01_pn_diode.py         # -> pn_diode.png
python examples/02_process_flow.py     # -> process_flow.png
python examples/03_mos_cv.py           # -> mos_cv.png
python examples/04_mosfet_idvg.py      # -> mosfet_idvg.png
python examples/05_3d_reduces_to_2d.py # -> 3d_reduces_to_2d.png
pytest tests/ gui/tests/               # full suite, serial
pytest tests/ gui/tests/ -n 6 -m "not slow" -q   # fast dev loop (parallel)
```

Everything -- library, GUI, tests, and optional deps (gmsh, devsim,
mpmath) -- is in one file: `pip install -r requirements.txt` (verified
on Linux and Windows, see the file's own header). Cap parallel workers
at `-n 6` and set `OPENBLAS_NUM_THREADS=1` -- see AGENTS.md's Commands
section for why.

---

## 6. Honest limits of *this* code

- **The 1D core** has no short-channel-effect modeling beyond drift-diffusion, no LOCOS/STI. A real $I_d$–$V_g$ MOSFET sweep with a gate-controlled channel *is* now available — see the "2D MOSFET (new)" subsection below. Unstructured (gmsh triangle) 2D meshing now exists (M21 phase 3, `Device2D(unstructured=True)`) but is homojunction-only (no Caughey-Thomas mobility, no FD statistics, no heterojunctions) and library-only -- no GUI path to build or edit an unstructured mesh.
- **Implant tables are approximate** LSS moments for *amorphous* Si, good to ~5–10%. They contain **no channelling**, which in crystalline Si can put a tail 1–2 decades deeper. Pass `Rp`/`dRp` from SRIM for anything real.
- **Diffusion is intrinsic and constant-$D$.** No extrinsic (charged-defect) enhancement above $n_i(T)$, no transient enhanced diffusion from implant damage, no oxidation-enhanced diffusion, no dopant–defect pair kinetics. These dominate real junction formation below ~1000 °C.
- **Deal–Grove under-predicts thin dry oxides.** The $x_i \approx 25$ nm initial thickness is a fudge factor, not physics.
- **Quantum corrections: density-gradient only, equilibrium-only.** `MOSCapacitor(dg=True)` and `Device1D(Models(dg=True))` add the Ancona–Stafford density-gradient correction (inversion centroid off the interface, $C_{max}$ lowered), gated against the code's own Schrödinger–Poisson solve (`pytcad/dg.py`) and the literature ~1 nm centroid. DG transport in `solve_bias`, 2D/3D, and dg+FD/dg+incomplete-ion compositions are refused (M20 scope). $\gamma=1$ is the uncalibrated Bohm value. No poly depletion beyond the $D_{it}$ (M14) and DG (M20) terms in the MOS module.
- **Quasi-static C-V only.** A 1 MHz measurement gives the high-frequency curve, where $C$ stays near $C_{min}$ in inversion because minority carriers cannot follow.

### 2D MOSFET (new)

There is now a 2D extension (`mesh2d.py`'s `Mesh2D`, `device2d.py`'s `Device2D`, and `mosfet.py`'s `build_mosfet`/`id_vg_sweep`) that solves full drift-diffusion on a tensor-product mesh and produces a real $I_d$–$V_g$ transfer curve with gate-controlled subthreshold switching — see `examples/04_mosfet_idvg.py`. It reuses the same Scharfetter–Gummel/Newton/scaling machinery described above, extended to a 2D box-integration Poisson/continuity assembly. For exactly what's in scope versus deferred (no $I_d$–$V_d$ family sweep, no 2D process simulation, structured rectangular mesh only — no unstructured/triangular mesh, no Canali velocity-saturation mobility in 2D), the original internal design notes for this sub-project are not included in this repository checkout.

### 3D Solver (new)

There is now a true 3D extension (`mesh3d.py`'s `Mesh3D`, `device3d.py`'s `Device3D`) that solves full 3D drift-diffusion on a tensor-product Cartesian mesh (independent, non-uniform spacing per axis). It generalizes the same box-integration/edge-scatter assembly used in 1D and 2D: each mesh edge (now three families — x, y, z) scatters a Scharfetter–Gummel flux to its two endpoint nodes, giving a 7-point stencil per equation (block-heptadiagonal Jacobian for the coupled $\psi$/$n$/$p$ Newton system) and implicit zero-flux Neumann boundaries wherever an edge is simply absent. Boundary conditions are geometry-agnostic: `add_contact`/`add_gate` take arbitrary node-index arrays, not device-specific shapes. `GateBC` carries a `normal_axis` (`'x'`/`'y'`/`'z'`) so a gate face can sit on any of the three axes — needed for future wrapped-gate devices (FinFET, GAA) — though only `normal_axis='z'` is exercised by this sub-project's own tests.

**Validation.** The primary correctness gate is dimensional reduction: a z-invariant 3D structure must reproduce the already-validated 2D solver exactly. `tests/test_validation_3d.py` checks this at equilibrium and forward bias, and `examples/05_3d_reduces_to_2d.py` makes it visual — extruding a p-n junction in z, solving both 2D and 3D, and plotting the difference. Measured on this repo: max $|\psi_{3D}-\psi_{2D}|$ = 1.11e-16 V, max $|J_{3D}-J_{2D}|$ = 3.98e-10 A/cm² — both at floating-point noise level, not just within the tests' (looser) 1e-6 V / 1e-3 relative tolerances. The analytic Newton Jacobian is independently checked against finite differences (worst relative error < 1e-3 across 30 random sampled columns via sparse column-slice extraction — never `J.toarray()` on the full matrix), and terminal-current extraction (residual-based, not edge-walking) conserves charge to <1e-6 relative error on a two-terminal 3D resistor.

**Current limitations, stated honestly.** No device-specific 3D geometry yet — FinFET, GAA nanowire, and GAA nanosheet are deferred to future sub-projects; this one only validates the generic 3D core. No 3D process simulation (implant/diffusion/oxidation remain 1D-only). `scipy.sparse.linalg.spsolve` (`NewtonOptions.linsolve="direct"`, the default) is still what every pre-2026-09-02 benchmark below describes, and the superlinear LU fill-in it shows on a large 3D structured grid is real and unavoidable for a direct solve on this mesh topology. Since then, `Device3D.solve_equilibrium`/`solve_bias` also accept `linsolve="bicgstab"`/`"gmres"` (AMG-preconditioned via the optional `pyamg` dependency) and `linsolve="gpu_direct"` (cuSOLVER via the optional `cupy` dependency) — measured 8x-44x faster for a large 3D equilibrium solve and 2.8x faster for a large 3D bias solve respectively, *but* measurably WORSE than plain `"direct"` below roughly 20,000-50,000 nodes (preconditioner/GPU setup cost that only pays for itself once direct factorization is already expensive) — neither is a universal replacement for `"direct"`, which is why it stays the default. `gui/services/solver_runner.py` picks between them automatically for GUI-driven 3D jobs based on mesh size and what's installed; called directly through the pytcad API, `"direct"` remains what you get unless you ask otherwise. MPI-parallel domain decomposition (4-rank overlapping Schwarz, `gui/services/mpi_schwarz_runner.py`) exists only at the GUI layer, not as a `Device3D` capability — it drives several ordinary `Device3D` instances, one per rank, over an already-split mesh, and now covers voltage sweeps as well as equilibrium + a single bias point (transients are still excluded, since `Device3D` has no transient module to parallelize). It also now picks whichever of x/y/z is actually safe to split along, not only x. It is NOT safe for every geometry: a device whose doping varies along the candidate axis converges far slower or not at all, and a device with a gate contact whose own `normal_axis` matches the candidate axis can converge to a silently WRONG answer even when the doping check alone would call that axis safe (a real bug found and fixed) — `run_job()` checks both the doping array and every registered gate's normal_axis, and refuses the MPI path whenever either is unsafe. See M22-LINSOLVE-PLAN.md sections 9-13 for the full measurement record on all three engines.

Historical benchmark (unchanged, still accurate for the `"direct"` path this whole limitations paragraph is otherwise about): a uniformly-doped cubic resistor's solve time grew from 3.0s at N=8,000 nodes to 51.8s at N=27,000 (an 18x jump for 3.4x more nodes), and N=64,000 did not complete a single solve within 30 minutes, with the unattended sweep's memory reaching ~19 GB before being killed. **In practice `"direct"` alone is only usable up to roughly N≈27,000 nodes (≈81,000 DOF) on 30 GB-class hardware; larger meshes need one of the alternatives above (or, for the GUI's own examples, its automatic gating already picks one).** No claim of parity with commercial 3D TCAD tools is made or intended. The full design rationale, explicit out-of-scope list, and sub-project roadmap (FinFET, GAA nanowire, GAA nanosheet) live in this sub-project's internal design notes, not included in this repository checkout.

### Transient simulation (new)

M17 adds time-dependent drift-diffusion for both `Device1D`
(`transient.py`) and `Device2D` (`transient2d.py`): backward-Euler/
theta-scheme time-stepping, three per-contact waveform primitives
(step, ramp, pulse), and adaptive time-stepping. Both drive the device
through its own residual/Jacobian from the outside, the same pattern
`continuation.py` uses for bias continuation -- `device.py`/
`device2d.py` were never touched. Gated against real physics:
dielectric relaxation decaying with $\tau=\varepsilon/\sigma$, and a
forward-to-reverse diode switch showing a measurable charge-storage
delay. Honest limits: gate-contact voltages are not waveform-driven;
only a scalar current-vs-time series is stored, not per-step field
snapshots; one quantitative diode-turn-off charge estimate was
investigated and left an honest partial result. See
`M17-TRANSIENT-PLAN.md`.

### Small-signal AC analysis (new)

M18 adds frequency-domain small-signal analysis for `Device1D`
(`ac.py`): the complex admittance `Y(f) = J_ac(w)^-1` reuses the
converged DC Jacobian plus a capacitive block that is bit-identical to
`transient.py`'s own backward-Euler storage term with `d/dt -> jw`
substituted in -- `device.py` untouched. Gated against a finite-
difference `dI/dV`/`dQ/dV` from independent `solve_bias` calls (the
low-frequency limit), a freshly-derived analytic abrupt-junction
depletion capacitance, and a qualitative high-frequency roll-off
check. One-port only (drive one contact, the other AC-grounded) --
no general multi-terminal Y-parameter matrix. 1D only; library-only,
no GUI exposure. See `M18-AC-PLAN.md`.

### Self-heating (new)

M19 adds steady-state 1D self-heating (`thermal.py`): an isothermal
Device1D electrical solve coupled to a nonlinear steady lattice-
temperature equation (`kappa_th(T)` is genuinely temperature-
dependent) through an outer Gummel loop -- a deliberate architecture
choice (`Device1D`'s entire scaling framework is built from a single
scalar `T`; a monolithic per-node coupled temperature unknown would be
a much larger rewrite than the acceptance gates need), not a shortcut.
Gated against a closed-form parabolic temperature profile (uniform
heat source, constant `kappa`), an FD-Jacobian check on the nonlinear
heat equation, and a measured electrothermal feedback direction on a
diode (current *increases* with self-heating at fixed bias -- the
correct PN-junction physics, not the MOSFET-style "roll-off" the
milestone's own shorthand name suggested). Thermal runaway is real
above a measured bias/thermal-resistance threshold and raises
`RuntimeError` rather than returning nonsense. 1D steady-state only;
no 2D, no transient coupling, no Seebeck/Peltier. See
`M19-SELFHEATING-PLAN.md`.

### Unstructured (gmsh) 2D meshing (new)

M21 phase 3 adds general unstructured 2D meshing on top of `Device2D`:
`Device2D(mesh, doping, unstructured=True)` accepts a `gmsh_mesh.
GmshMesh` triangle mesh (nodes/triangles/region+contact Physical
Groups) and a `{region_name: doping_value}` dict, and solves through
the same `solve_equilibrium`/`solve_bias`/`terminal_current` API as a
structured device. Internally a thin wrapper (zero new Jacobian
entries, bit-identical to calling `unstructured_poisson.py`/
`unstructured_dd.py` directly) around a genuinely new box-integration
FV assembly on an arbitrary triangulation (dual-cell areas, per-edge
TPFA flux geometry, Scharfetter-Gummel current on non-axis-aligned
edges). Golden-parity gated against the structured solver (~5-6%
relative on terminal current -- reported honestly, not tightened).
Homojunction-only (uniform mobility, no Caughey-Thomas/FD/
incomplete-ionization/surface-mobility) -- any incompatible
`Models()` flag raises `NotImplementedError` rather than solving
silently wrong. No 3D, no adaptive refinement, no heterojunctions, no
GUI path to build or edit a mesh. See `M21-PHASE3-MESHING-PLAN.md`.

### Desktop GUI (new)

There is a PySide6 / Qt Quick desktop frontend in `../gui/` that solves
devices in a background process and visualizes the result, without the
GUI ever blocking or the numerical engine changing by a single line. It
covers: a Structure + Mesh workbench, a Process Workbench, single- and
family (batch) voltage sweeps with curve plotting and derived readouts,
a MOS C–V mode, a Physics Lab panel (every catalog model as a checkbox
with its equation and reference), Bands/Recombination viewport modes
with an all-models-off comparison overlay, deck-driven sessions, a
versioned result schema with per-run provenance, a second solver
backend (DEVSIM, optional), and a Transient tab (M17 phase 3) that arms
a per-contact waveform and plots current vs. time. See
`../gui/README.md` and `../docs/user-guide/` for details.

## 7. Where to read more

- **Selberherr, *Analysis and Simulation of Semiconductor Devices* (1984)** — still the reference for the discretised equations, scaling, and Scharfetter–Gummel. Computational.
- **Scharfetter & Gummel, *IEEE Trans. Electron Devices* 16, 64 (1969)** — the original exponential-fitting scheme, ~10 pages. Computational.
- **Vasileska, Goodnick & Klimeck, *Computational Electronics* (2010)** — bridges drift-diffusion, hydrodynamic, and Monte Carlo. Computational.
- **Plummer, Deal & Griffin, *Silicon VLSI Technology*** — the process side: implantation, diffusion, oxidation, with the models actually used in fabs. Experimental/empirical.
- **Deal & Grove, *J. Appl. Phys.* 36, 3770 (1965)** — the oxidation model, and honest about its thin-oxide failure. Experimental + theory.
- **Sze & Ng, *Physics of Semiconductor Devices*** — the analytic limits every one of these tests checks against. Theory.
