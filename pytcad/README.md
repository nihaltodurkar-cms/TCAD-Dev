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
                 assisted tunneling (M12)
  moscap.py      MOS capacitor, quasi-static C-V
  mesh2d.py      tensor-product 2D mesh + Debye-length adequacy check
  device2d.py    2D drift-diffusion: box-integration Poisson + continuity
  mosfet.py      2D MOSFET builder + Id-Vg sweep
  mesh3d.py      tensor-product 3D mesh + Debye-length adequacy check
  device3d.py    3D drift-diffusion: box-integration Poisson + continuity
examples/        p-n diode, full process flow, MOS C-V, 2D MOSFET Id-Vg,
                 3D-reduces-to-2D validation
tests/           analytic-limit validation + published-value physics
                 benchmarks (part of the 527-test suite, zero warnings)
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
| Boltzmann statistics | doping ≳ 10¹⁹ cm⁻³ (degeneracy) — the code warns you |
| Full dopant ionisation | cryogenic temperature; deep dopants |
| Classical (no quantisation) | thin-oxide inversion layers: real charge centroid sits ~1 nm deep, so $C_{max}$ is overestimated by 10–20% |
| Local mobility model | quasi-ballistic transport in sub-30 nm channels |
| No impact ionisation / tunnelling | avalanche breakdown, band-to-band tunnelling (GIDL), direct gate leakage below ~2 nm oxide |
| Isothermal, steady state | self-heating, transient / AC analysis |

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

**Mobility gotcha:** the argument is the *total* ionised impurity concentration $N_A + N_D$, not the net doping $|N_D - N_A|$. Using the net value badly overestimates mobility in compensated regions. `Device1D` takes `Ntotal` separately for exactly this reason.

---

## 4. Validation

All tests pass as part of the project-wide 527-test suite (zero
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
pytest tests/ ../gui/tests/            # 527 passed, zero warnings
```

Requires `numpy`, `scipy`, `matplotlib` (examples only).

---

## 6. Honest limits of *this* code

- **The 1D core** has no short-channel-effect modeling beyond drift-diffusion, no LOCOS/STI, and no unstructured mesh. A real $I_d$–$V_g$ MOSFET sweep with a gate-controlled channel *is* now available — see the "2D MOSFET (new)" subsection below.
- **Implant tables are approximate** LSS moments for *amorphous* Si, good to ~5–10%. They contain **no channelling**, which in crystalline Si can put a tail 1–2 decades deeper. Pass `Rp`/`dRp` from SRIM for anything real.
- **Diffusion is intrinsic and constant-$D$.** No extrinsic (charged-defect) enhancement above $n_i(T)$, no transient enhanced diffusion from implant damage, no oxidation-enhanced diffusion, no dopant–defect pair kinetics. These dominate real junction formation below ~1000 °C.
- **Deal–Grove under-predicts thin dry oxides.** The $x_i \approx 25$ nm initial thickness is a fudge factor, not physics.
- **No quantum corrections, no poly depletion, no $D_{it}$** in the MOS module.
- **Quasi-static C-V only.** A 1 MHz measurement gives the high-frequency curve, where $C$ stays near $C_{min}$ in inversion because minority carriers cannot follow.

### 2D MOSFET (new)

There is now a 2D extension (`mesh2d.py`'s `Mesh2D`, `device2d.py`'s `Device2D`, and `mosfet.py`'s `build_mosfet`/`id_vg_sweep`) that solves full drift-diffusion on a tensor-product mesh and produces a real $I_d$–$V_g$ transfer curve with gate-controlled subthreshold switching — see `examples/04_mosfet_idvg.py`. It reuses the same Scharfetter–Gummel/Newton/scaling machinery described above, extended to a 2D box-integration Poisson/continuity assembly. For exactly what's in scope versus deferred (no $I_d$–$V_d$ family sweep, no 2D process simulation, structured rectangular mesh only — no unstructured/triangular mesh, no Canali velocity-saturation mobility in 2D), the original internal design notes for this sub-project are not included in this repository checkout.

### 3D Solver (new)

There is now a true 3D extension (`mesh3d.py`'s `Mesh3D`, `device3d.py`'s `Device3D`) that solves full 3D drift-diffusion on a tensor-product Cartesian mesh (independent, non-uniform spacing per axis). It generalizes the same box-integration/edge-scatter assembly used in 1D and 2D: each mesh edge (now three families — x, y, z) scatters a Scharfetter–Gummel flux to its two endpoint nodes, giving a 7-point stencil per equation (block-heptadiagonal Jacobian for the coupled $\psi$/$n$/$p$ Newton system) and implicit zero-flux Neumann boundaries wherever an edge is simply absent. Boundary conditions are geometry-agnostic: `add_contact`/`add_gate` take arbitrary node-index arrays, not device-specific shapes. `GateBC` carries a `normal_axis` (`'x'`/`'y'`/`'z'`) so a gate face can sit on any of the three axes — needed for future wrapped-gate devices (FinFET, GAA) — though only `normal_axis='z'` is exercised by this sub-project's own tests.

**Validation.** The primary correctness gate is dimensional reduction: a z-invariant 3D structure must reproduce the already-validated 2D solver exactly. `tests/test_validation_3d.py` checks this at equilibrium and forward bias, and `examples/05_3d_reduces_to_2d.py` makes it visual — extruding a p-n junction in z, solving both 2D and 3D, and plotting the difference. Measured on this repo: max $|\psi_{3D}-\psi_{2D}|$ = 1.11e-16 V, max $|J_{3D}-J_{2D}|$ = 3.98e-10 A/cm² — both at floating-point noise level, not just within the tests' (looser) 1e-6 V / 1e-3 relative tolerances. The analytic Newton Jacobian is independently checked against finite differences (worst relative error < 1e-3 across 30 random sampled columns via sparse column-slice extraction — never `J.toarray()` on the full matrix), and terminal-current extraction (residual-based, not edge-walking) conserves charge to <1e-6 relative error on a two-terminal 3D resistor.

**Current limitations, stated honestly.** No device-specific 3D geometry yet — FinFET, GAA nanowire, and GAA nanosheet are deferred to future sub-projects; this one only validates the generic 3D core. No 3D process simulation (implant/diffusion/oxidation remain 1D-only). Direct sparse solve only (`scipy.sparse.linalg.spsolve`), no iterative/preconditioned solver, no GPU. This has a real, measured cost: benchmarking a uniformly-doped cubic resistor showed solve time growing from 3.0s at N=8,000 nodes to 51.8s at N=27,000 (an 18x jump for 3.4x more nodes — clearly superlinear LU fill-in), and N=64,000 did not complete a single solve within 30 minutes, with the unattended sweep's memory reaching ~19 GB before being killed. **In practice this solver is only usable up to roughly N≈27,000 nodes (≈81,000 DOF) on 30 GB-class hardware; do not attempt 40³+ meshes without an iterative solver.** No claim of parity with commercial 3D TCAD tools is made or intended. The full design rationale, explicit out-of-scope list, and sub-project roadmap (FinFET, GAA nanowire, GAA nanosheet) live in this sub-project's internal design notes, not included in this repository checkout.

### Desktop GUI (new)

There is a PySide6 / Qt Quick desktop frontend in `../gui/` that solves
devices in a background process and visualizes the result, without the
GUI ever blocking or the numerical engine changing by a single line. It
covers: a Structure + Mesh workbench, a Process Workbench, single- and
family (batch) voltage sweeps with curve plotting and derived readouts,
a MOS C–V mode, a Physics Lab panel (every catalog model as a checkbox
with its equation and reference), Bands/Recombination viewport modes
with an all-models-off comparison overlay, deck-driven sessions, a
versioned result schema with per-run provenance, and a second solver
backend (DEVSIM, optional). See `../gui/README.md` and
`../docs/user-guide/` for details.

## 7. Where to read more

- **Selberherr, *Analysis and Simulation of Semiconductor Devices* (1984)** — still the reference for the discretised equations, scaling, and Scharfetter–Gummel. Computational.
- **Scharfetter & Gummel, *IEEE Trans. Electron Devices* 16, 64 (1969)** — the original exponential-fitting scheme, ~10 pages. Computational.
- **Vasileska, Goodnick & Klimeck, *Computational Electronics* (2010)** — bridges drift-diffusion, hydrodynamic, and Monte Carlo. Computational.
- **Plummer, Deal & Griffin, *Silicon VLSI Technology*** — the process side: implantation, diffusion, oxidation, with the models actually used in fabs. Experimental/empirical.
- **Deal & Grove, *J. Appl. Phys.* 36, 3770 (1965)** — the oxidation model, and honest about its thin-oxide failure. Experimental + theory.
- **Sze & Ng, *Physics of Semiconductor Devices*** — the analytic limits every one of these tests checks against. Theory.
