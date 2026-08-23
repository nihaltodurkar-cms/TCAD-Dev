# PyTCAD

A compact, readable, **validated** 1D TCAD toolkit in Python — process simulation and self-consistent drift-diffusion device simulation, structured the way commercial TCAD is structured (Sentaurus Process → Sentaurus Device, Silvaco Athena → Atlas).

Roughly 1,200 lines. No black boxes: every model states its equation, its provenance (theory / measurement / empirical fit), and where it breaks.

```
pytcad/
  constants.py   physical constants, thermal voltage
  materials.py   ni(T), mobility, lifetimes, bandgap narrowing, recombination
  mesh.py        non-uniform meshing + Debye-length adequacy check
  process.py     implantation, diffusion, Deal-Grove oxidation
  device.py      drift-diffusion: Poisson + both continuity equations
  moscap.py      MOS capacitor, quasi-static C-V
examples/        p-n diode, full process flow, MOS C-V
tests/           15 validation tests against analytic limits
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

All 15 tests pass. Selected results for an abrupt 10¹⁷/10¹⁷ Si junction, 2 µm long, 300 K:

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
python examples/01_pn_diode.py       # -> pn_diode.png
python examples/02_process_flow.py   # -> process_flow.png
python examples/03_mos_cv.py         # -> mos_cv.png
python tests/test_validation.py      # 15/15
```

Requires `numpy`, `scipy`, `matplotlib` (examples only).

---

## 6. Honest limits of *this* code

- **1D only.** No MOSFET $I_d$–$V_g$ with a real channel, no short-channel effects, no LOCOS/STI. 2D needs a triangular/rectangular mesh and a 2D box-integration assembly — the physics modules carry over unchanged.
- **Implant tables are approximate** LSS moments for *amorphous* Si, good to ~5–10%. They contain **no channelling**, which in crystalline Si can put a tail 1–2 decades deeper. Pass `Rp`/`dRp` from SRIM for anything real.
- **Diffusion is intrinsic and constant-$D$.** No extrinsic (charged-defect) enhancement above $n_i(T)$, no transient enhanced diffusion from implant damage, no oxidation-enhanced diffusion, no dopant–defect pair kinetics. These dominate real junction formation below ~1000 °C.
- **Deal–Grove under-predicts thin dry oxides.** The $x_i \approx 25$ nm initial thickness is a fudge factor, not physics.
- **No quantum corrections, no poly depletion, no $D_{it}$** in the MOS module.
- **Quasi-static C-V only.** A 1 MHz measurement gives the high-frequency curve, where $C$ stays near $C_{min}$ in inversion because minority carriers cannot follow.

## 7. Where to read more

- **Selberherr, *Analysis and Simulation of Semiconductor Devices* (1984)** — still the reference for the discretised equations, scaling, and Scharfetter–Gummel. Computational.
- **Scharfetter & Gummel, *IEEE Trans. Electron Devices* 16, 64 (1969)** — the original exponential-fitting scheme, ~10 pages. Computational.
- **Vasileska, Goodnick & Klimeck, *Computational Electronics* (2010)** — bridges drift-diffusion, hydrodynamic, and Monte Carlo. Computational.
- **Plummer, Deal & Griffin, *Silicon VLSI Technology*** — the process side: implantation, diffusion, oxidation, with the models actually used in fabs. Experimental/empirical.
- **Deal & Grove, *J. Appl. Phys.* 36, 3770 (1965)** — the oxidation model, and honest about its thin-oxide failure. Experimental + theory.
- **Sze & Ng, *Physics of Semiconductor Devices*** — the analytic limits every one of these tests checks against. Theory.
