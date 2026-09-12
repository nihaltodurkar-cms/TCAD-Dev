# M41 — Incomplete dopant ionization in structured Device2D/Device3D

Written 2026-09-12. The user's instruction ("go straight to M41 and
implement it") is the frozen-core amendment sign-off for
`device.py`, `device2d.py` and `device3d.py`. House gates apply:
FD-Jacobian first, default-off bit-identity, reconstruct-and-compare
md5 on the goldens.

`ARCHITECTURE.md` 4d.3 M41: *"Currently refused at device3d.py:242.
Pure port; the 1D physics and its goldens are the gate. Smallest item
here."* 4d.4's rule governs: **no dimensional lift lands without its
reduction identity as a gate.**

## 0. Golden baseline (recorded BEFORE any edit)

Per CLAUDE.md's reconstruct-and-compare protocol:

```
f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz
```

None of these runs enable `incomplete_ion`, so **every one must be
unchanged**. `diode2d_eq.npz` and `resistor3d_eq.npz` are the two that
exercise the edited files at all; if either moves, the "additive,
default-off" claim is false and the change is a defect, not a
re-baseline.

## 1. The model (unchanged from M13 — this is a port, not new physics)

    N_D+ = N_D / (1 + g_D e^{eta_n + dE/kT}),   g_D = 2
    N_A- = N_A / (1 + g_A e^{eta_p + dE/kT}),   g_A = 4
    dE = 45 meV (shallow hydrogenic B/P/As), single species per node

and the Poisson charge term becomes `rho = n - p - C_ion` in place of
`rho = n - p - C`. `eta_n`/`eta_p` come from the slot densities through
`f_half_inv`, so the term is **independent of the `fd` flag** — exactly
as in 1D, and deliberately so (`device.py:969-972`: "the FD contact
solver handles incomplete ionization too, and reduces exactly to the
Boltzmann closed form, so any ionization-enabled run routes through it
(flag independence)").

## 2. Approach: one implementation, three devices

Device1D's `_ionized_C` and the neutrality root in `_fd_neutral_eta`
are the only existing implementations. Rather than copy a subtle
formula into two more files, both are **factored to module level in
`device.py`** and imported by `device2d.py`/`device3d.py`, matching how
`fd_density` / `fd_node_factors` / `fd_ohmic_values` are already shared:

- new `ionized_doping(nd, na, n, p, nc_s, nv_s, T)` -> `(cion,
  dcion_dn, dcion_dp)`; `Device1D._ionized_C` becomes a thin call.
  **Must be bit-identical** — a pure extract-method with the operation
  order preserved.
- `fd_ohmic_values(..., ion=None)` gains one optional argument. When
  given `(nd, na, ded_kt)` the neutrality root solves
  `n(e) - p(e) - (ND+(e) - NA-(e)) = 0` instead of `n - p - C`,
  mirroring `_fd_neutral_eta`'s own `g`. `ion=None` leaves every
  existing caller bit-identical.

## 3. Touch points

### `device.py`
1. `ionized_doping` extracted (above); `_ionized_C` delegates.
2. `fd_ohmic_values` gains `ion=None`.

### `device2d.py` / `device3d.py` (identical, 2D first)
1. Constructor: drop the `incomplete_ion` `NotImplementedError`; add
   `self.nd_arr` / `self.na_arr` (scaled, device-shaped); refuse
   `band_offset="affinity"` + `incomplete_ion`, matching Device1D's
   own refusal at `device.py:660` (the FD eta-space contact solver and
   the neutral-guess bisection each carry their own `ln(Nc/nie)`
   offset, and composing them with the affinity shift is underived).
2. `_ionized_C` method delegating to `ionized_doping`.
3. `_bulk_psi_guess`: take the eta-space branch when `fd OR ion` (the
   Boltzmann arcsinh guess is wrong under freeze-out, the same reason
   `device.py:1027` reads `if fd or ion:`); add the ionized term to the
   bisection's `g`.
4. `_bc_contact_values`: route through `fd_ohmic_values` when
   `fd OR ion`, passing `ion=`.
5. `_residual_jacobian_poisson` (equilibrium): `rho` uses `C_ion`, and
   `dnp` gains the slaved-density chain
   `dnp - dcden * dn/dpsi + dcdp * |dp/dpsi|`.
6. `_residual_jacobian` (coupled bias): `F_psi` uses `C_ion`; the
   Poisson row's two density columns become `-dV*(1 - dcden)` and
   `+dV*(1 + dcdp)`.

### Not touched, deliberately
`GateBC`'s `psi_b_local` keeps its Boltzmann `arcsinh(C/(2 nie))`
flat-band reference. It is already an approximation under `fd=True`
today; changing it would move existing FD results and is a separate,
separately-gated question.

Unstructured `Device2D(unstructured=True)` keeps refusing
`incomplete_ion` through its existing `unsupported` dict — no change.

## 4. Gates (`tests/test_m41_incomplete_ion_2d3d.py`)

| gate | what it proves |
|---|---|
| G1 | 2D FD-Jacobian probe with `incomplete_ion=True` (written FIRST) |
| G2 | 3D FD-Jacobian probe, same |
| G3 | 2D uniform device reproduces the independent self-consistent ionized fraction at 77/150/250/300 K to 1e-9, and lands in M13's published literature bands |
| G4 | 3D, same |
| G5 | transversely-uniform 2D reduces to Device1D's `incomplete_ion` equilibrium |
| G6 | 3D, same |
| G7 | freeze-out DIRECTION: the 2D ionized fraction at 77 K is far below 1, and below the 300 K one |
| G8 | `incomplete_ion=False` bit-identity in 2D and 3D (`np.array_equal`) |
| G9 | flag independence: `fd=False, incomplete_ion=True` runs and gives the same ionized fraction as `fd=True` at non-degenerate doping |
| G10 | affinity + `incomplete_ion` refused in both devices |

G3/G4 reuse `test_m13_solver.py`'s own `_fd_neutral_eta` reference
root-finder — an implementation independent of the solver, which is
what makes it a gate rather than a tautology.

## 5. Honest limits (inherited from M13, restated)

- Shallow hydrogenic B/P/As only, `dE = 45 meV`, `g_D = 2`, `g_A = 4`.
- **Single species per node**: the majority side carries all dopants,
  because the devices store net doping `C`, not separate `N_D`/`N_A`
  profiles. `nd_arr = max(C, 0)`, `na_arr = max(-C, 0)` — exactly 1D's
  convention (`device.py:761-762`).
- Invalid above the Mott transition (~4e18 cm^-3 for Si:P) and for
  deep levels; M13's own test file refuses to combine `incomplete_ion`
  with >= 1e19 doping.
- Structured grids only.
- No performance claim (no benchmark row added).
- `GateBC`'s flat-band reference keeps its Boltzmann
  `arcsinh(C/(2 nie))` form, so a MOS device under freeze-out has a
  gate reference computed from the FULL doping.  That was already the
  case under `fd=True` before this slice; it is named here rather than
  silently inherited, and fixing it is its own question.

## 6. Implementation record (2026-09-12)

Landed as planned, with three things worth recording.

**The extraction was the right call and cost nothing.** `device.py`
gained `ionized_dE_kt`, `ionized_eta_doping`, `ionized_doping` and one
optional `ion=` argument to `fd_ohmic_values`; `Device1D._ionized_C`
and the `incomplete_ion` branch of `_fd_neutral_eta` became two-line
calls.  `tests/test_m13_solver.py` stayed 29/29 green immediately
(including G5's FD-Jacobian probe and G7b/c's 1e-9 ionized-fraction
match at four temperatures) and all six golden md5s were unchanged, so
the refactor is numerically exact, not merely close.

**Two chain rules, not one -- and only one of them is reachable by a
convergence gate.** The equilibrium block slaves n and p to psi, so
d(rho)/dpsi picks up `(1-dcden) dn/dpsi + (1+dcdp) |dp/dpsi|`; the
coupled block treats n and p as independent unknowns, so Poisson's row
instead gains the two density columns `-dV(1-dcden)` and `+dV(1+dcdp)`.
Both were gated separately (G1/G1b/G2 for the coupled block, G2b/G2c/G2d
for the equilibrium one).  That separation earned its keep: a mutation
test confirmed that DROPPING the equilibrium chain entirely still
converges to the right answer and passes every convergence and
physics gate, while moving the FD probe to 0.52 against a 5e-5
threshold (baseline 6.4e-8).  Sign-flipping `d(C_ion)/dp` in the
coupled block moves G1 to 1.5e-2 (baseline 1.3e-8).  Neither would
have been caught by the reduction or literature-band gates alone.

**Gate results.** 21 tests in
`tests/test_m41_incomplete_ion_2d3d.py`, all green:
FD Jacobians (2D 1.34e-8, 3D 1.13e-8, Boltzmann; equilibrium 2D
6.41e-8, 3D, Boltzmann) against a 5e-5 threshold; the ionized fraction
matching the independent root at
77/150/250/300 K to <= 1e-9 in 2D and at 77/300 K in 3D; the freeze-out
direction (0.2857 at 77 K vs 0.9927 at 300 K); 2D and 3D transverse-uniform
reduction to Device1D at equilibrium (psi atol 1e-9) and at 0.3 V
forward bias including terminal current density (rel. 1e-6);
`incomplete_ion=False` bit-identity in both devices; and flag
independence between FD and Boltzmann statistics within the exact
Boltzmann-limit deviation `exp(eta_p)/2^(3/2) = 1.13e-4` (measured
2.7e-5).

**Suites.** Fast `PYTCAD_ACCEL=0`: 1751 passed, 13 skipped, 1 xfailed,
39 warnings.  Fast `PYTCAD_ACCEL=1`: 1759 passed, 5 skipped, 1 xfailed,
39 warnings.  Both account for all 1765 collected fast tests exactly
(verified with `--junitxml` against `--collect-only`: `errors="0"
failures="0"`), and both equal the pre-M41 baseline (1731 / 1739) plus
21 new tests minus the one retired refusal case.  Slow battery: 33
passed, 10 warnings -- unchanged.  Warning counts unchanged in every
mode.  **Goldens: all six md5s in section 0 re-checked after the edit
and byte-identical**, so step 3 of the reconstruct-and-compare protocol
had nothing to reconstruct -- no golden moved, which is the claim
"additive, default-off" has to make.

**One pre-existing gate updated, one deliberately not duplicated.**
`tests/test_sic_vmosfet.py`'s 3D refusal inventory dropped its
`incomplete_ion` row (the same way M34-S6 dropped `impact`).  The
unstructured refusal is NOT re-gated here -- 
`tests/test_m21_phase3.py::test_wrapper_refuses_unsupported_models_flags`
already names `incomplete_ion` in its list and builds the real GmshMesh
that path needs; it was re-run after this slice and still passes.
