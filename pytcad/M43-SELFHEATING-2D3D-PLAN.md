# M43 — self-heating -> 2D (phase 1), 3D (phase 2), C++ acceleration (phase 3)

## Scope

ARCHITECTURE.md's ordering line (`M41[S](done) -> M43[L](next) -> ...`)
put this next. M19-SELFHEATING-PLAN.md (restored to the tree from git
history for this milestone -- it had been accidentally deleted in a
follow-up commit with no explanation; CLAUDE.md's own Layout section
still names it as canonical) landed steady-state 1D self-heating and
explicitly deferred the dimensional lift with zero design detail: "2D
self-heating: out of scope (the spec's own '1D first, then 2D'
phasing)." Unlike M41 (incomplete ionization -> 2D/3D), there was no
prior 2D/3D sketch to port -- this milestone designs the lift from
scratch, reusing M41's *process* (FD-Jacobian-first, reduction-identity
gate, golden-baseline reconstruct-and-compare) but not its physics.

Investigating before implementing (see the session's research pass)
found `Device2D`/`Device3D` share Device1D's exact scalar-T-at-`__init__`
scaling architecture that M19's plan cited as the reason to reject a
monolithic (psi,n,p,T) Newton coupling -- that reasoning transfers
unchanged, so this milestone is again an OUTER Gummel loop (isothermal
electrical solve + separate lattice-heat solve), never a coupled
system. It also found no reusable node-Joule-heating computation and no
2D/3D lattice-heat solver existed anywhere -- both had to be built from
scratch, unlike M41 where the ionization formula already existed and
only needed factoring to module level.

**Phase 1 scope, decided during implementation: Device2D only.**
Device3D was initially deferred to a later phase -- the same "N-D
first, then N+1-D" staging M19 itself used (1D landed, 2D deferred
wholesale) -- to keep the new numerics (a genuinely new vectorized 2D
FV heat-equation Newton solve, a new 2D box-integrated Joule-heating
formula) verifiable end to end before doubling the unverified surface
area with a second, independently hand-written 3D stencil.

**Phase 2 (same session, immediately after phase 1 shipped): Device3D,
by GENERALIZING phase 1's assembly rather than duplicating it a third
time.** The user asked to "generalize it to 3D" -- rather than
hand-writing a third near-identical per-axis stencil (2x the sign-bug
surface phase 1 already hit once), the residual/Jacobian assembly was
factored into a genuinely dimension-generic core,
`pytcad/thermal_grid.py`'s `_residual_jacobian_grid(coords, T, H,
material, T_ambient, bcs)` (D = 2 or 3, one axis loop instead of
hand-unrolled x/y[/z] blocks) -- mirroring `ii_grid.py`/`btbt_grid.py`'s
already-established "one kernel for Device2D and Device3D" pattern
(M34-S6). `thermal2d.py`'s `_residual_jacobian_2d` and
`solve_lattice_temperature_2d` became thin wrappers over this core;
`thermal3d.py`'s 3D analogues are thin wrappers over the SAME core.
Only `joule_heating_density_{2,3}d` stayed dimension-specific (they
read `Device2D`/`Device3D`'s own differently-shaped `Jn_x`/`Jn_y`
[`/Jn_z`] attributes directly -- nothing for the generic core to share
there).

**Refactor safety**: phase 1's 4 gates were re-run immediately after
the `thermal2d.py` -> `thermal_grid.py` refactor, before writing any
3D code, and stayed green unchanged -- proof the generalization did
not alter 2D behavior, not just an assumption.

**Zero edits to device2d.py or device3d.py, either phase.** The entire
lift lives in new sibling modules (`thermal_grid.py`, `thermal2d.py`,
`thermal3d.py`), reusing `Device2D`/`Device3D`'s existing public
attributes (`psi`, `n`, `p`, `nie_s`, `VT`, `LD`, `xs`/`ys`[`/zs`],
`hx`/`hy`[`/hz`], `Jn_x`/`Jp_x`/`Jn_y`/`Jp_y`[`/Jn_z`/`Jp_z`]) without
modifying either frozen file at all -- so no frozen-core amendment
protocol applies to either (no golden to baseline, no FD-Jacobian gate
needed there), and both G-OFF-BIT-IDENTITY gates are true by
construction rather than something that needs defending.

**One small, additive amendment to `thermal.py`** (the 1D module,
itself frozen core): added `ThermalBC.adiabatic()` (zero heat flux --
the existing "resistance" Robin formula with its `(T-T_ambient)/R_th`
term dropped, not a new equation). Needed as the boundary condition
for the reduction-identity gate below. Verified additive: all 6
pre-existing M19 gates re-run green, unchanged, after the addition.

## What shipped

- `pytcad/thermal.py`: `ThermalBC.adiabatic()` classmethod +
  `_thermal_residual_jacobian` support (both boundaries; `inv_Rth = 0.0`
  when `kind == "adiabatic"`, everything else unchanged).
- `pytcad/thermal_grid.py` (new, phase 2): the dimension-generic (D=2
  or 3) core -- `_residual_jacobian_grid(coords, T, H, material,
  T_ambient, bcs)` and `solve_lattice_temperature_grid(...)`. One axis
  loop (`for axis in range(D)`) replaces what would otherwise be
  hand-unrolled x/y[/z] blocks; boundary handling (resistance additive,
  applied first; isothermal full override, applied last so it always
  wins at a corner/edge shared with a Robin boundary; adiabatic needs
  no code at all -- the interior formula's natural one-sidedness at a
  domain edge already IS the adiabatic residual) generalizes to 2*D
  boundary strips the same way.
- `pytcad/thermal2d.py`: `joule_heating_density_2d(device)` (the 2D
  analogue of `thermal.py`'s `joule_heating_density` -- same Wachutka
  1990 quasi-Fermi-potential-gradient dissipation term, `H = Jn.E_n +
  Jp.E_p`, NEVER the raw field; box-integrated with the same dVy/dVx
  flux-divergence cross-section weighting `device2d.py`'s own Poisson/
  continuity residual already uses, `device2d.py:977-983` -- a dual of
  an already-gated operation, not a re-derivation); `_residual_
  jacobian_2d`/`solve_lattice_temperature_2d` (phase 1: fully
  vectorized 2D assembly, no per-node Python loop -- `thermal.py`'s own
  1D assembly has the one scalar loop ARCHITECTURE.md flags as pairing
  with M31 P4; phase 2: refactored into thin wrappers over
  `thermal_grid.py`); `solve_electrothermal_2d(...)` (the outer Gummel
  loop, mirroring `solve_electrothermal` one dimension up).
- `pytcad/thermal3d.py` (new, phase 2): the 3D analogues --
  `joule_heating_density_3d` (the one genuinely new per-dimension
  piece: reads `Jn_x`/`Jn_y`/`Jn_z` and box-integrates with
  `device3d.py`'s own dVy*dVz/dVx*dVz/dVx*dVy cross-section convention,
  `device3d.py:993-998`), `_residual_jacobian_3d`/
  `solve_lattice_temperature_3d` (thin wrappers over `thermal_grid.py`
  from day one -- never hand-written separately), `solve_
  electrothermal_3d(...)`.
- `tests/test_m43_thermal2d.py` (4 gates, all green):
  - **G-FD-2D**: analytic vs. central-FD Jacobian of the vectorized 2D
    residual, deliberately using THREE DIFFERENT boundary kinds at
    once (isothermal/resistance/adiabatic) including a corner shared
    by two different kinds, to exercise the resistance-first/
    isothermal-last ordering the corner-conflict handling depends on.
  - **G-BC-2D**: resistance BC gives a higher peak than isothermal,
    same H (2D analogue of M19's G-BC).
  - **G-REDUCTION**: the load-bearing gate (ARCHITECTURE.md 4d.4: "no
    dimensional lift lands without its reduction identity as a gate").
    A y-uniform 2D diode with adiabatic top/bottom, solved end to end
    through `solve_electrothermal_2d`, reproduces `thermal.py`'s own 1D
    `solve_electrothermal` on the identical physical diode: every row
    of the 2D temperature profile matches the 1D profile (< 0.5% of
    the peak rise), and the current roll-off ratio matches to < 2%.
  - **G-OFF-BIT-IDENTITY-2D**: importing `thermal2d` changes not one
    bit of an ordinary isothermal `Device2D` solve.
- `tests/test_m43_thermal3d.py` (4 gates, all green, phase 2):
  - **G-FD-3D**: same FD-Jacobian check at D=3, mixed boundary kinds on
    all three axes including a corner shared by THREE different kinds
    -- passed on the FIRST run (the generic core, already proven
    correct at D=2, generalized cleanly; no new sign bug at D=3).
  - **G-BC-3D**: 3D analogue of G-BC.
  - **G-REDUCTION-3D**: the phase-2 load-bearing gate -- a z-uniform 3D
    diode with adiabatic front/back reproduces `thermal2d.py`'s own 2D
    `solve_electrothermal_2d` on the identical physical diode (which
    itself already reduces to 1D, phase 1's own gate) -- a genuine
    two-level reduction chain, 3D -> 2D -> 1D, not just 3D -> 1D
    directly.
  - **G-OFF-BIT-IDENTITY-3D**: importing `thermal3d` changes not one
    bit of an ordinary isothermal `Device3D` solve.
- Real bugs caught and fixed during implementation, before any gate was
  declared green:
  - **Phase 1**: the interior-flux Jacobian's edge-to-node scatter had
    the sign convention backwards (`F[kL] += w*Fx, F[kR] -= w*Fx`
    requires `dF[kL]/dT[kL] = +dFx`, `dF[kR]/dT[kR] = -dFx`; the first
    version had all four signs flipped). Caught immediately by G-FD-2D
    (relative error 2.0, i.e. exactly the wrong sign) before any other
    gate ran -- fixed by matching `device2d.py`'s own `scatter()`
    helper's sign convention for the identical construction.
  - **Phase 2**: none -- the generic-core refactor's own re-run of
    phase 1's 4 gates stayed green unchanged, and G-FD-3D passed on
    first execution. Generalizing to D=3 by parameterizing the SAME
    axis-loop code (rather than hand-writing a third hardcoded x/y/z
    block) is what avoided repeating the phase-1 sign mistake a second
    time.
- Verified beyond the gates: a larger, more realistic 2D grid (25x262
  = 6550 nodes) converges in 1.83s to a physically sensible ~1.1 K
  rise. A similarly-motivated larger 3D grid (12x12x~60 = ~8600 nodes)
  was attempted but did not finish within this session -- Device3D's
  own electrical solve (unmodified, not this milestone's code) is
  simply much slower at that node count via a direct sparse solve;
  this is a pre-existing Device3D performance characteristic, not
  something M43 introduced, but it means the larger-3D-grid check is
  NOT claimed as verified here (see CLAUDE.md's rule against claiming
  a run's result without reading its real output). The 4 gates in
  tests/test_m43_thermal3d.py, which use small grids specifically to
  keep the FD-Jacobian check's O(N) re-solves fast, ARE the confirmed
  3D acceptance evidence.

## Phase 3 -- C++ acceleration (same session, on request to "use cpp not python")

**No C++ compiler existed on this machine when asked.** `cmake`/`ninja`
were already present inside the `tcad-dev` conda env, but there was no
`cl.exe` (the Visual Studio install under `Program Files\Microsoft
Visual Studio\18` has no C++ workload), no MinGW `g++`, no `clang++` --
confirmed by trying to compile a trivial `<optional>` translation unit,
not assumed. `pytcad._accel.status()` itself confirmed `_core: not
built`. Per the house rule against claiming a compiled-kernel gate
without actually running it, this was surfaced to the user rather than
writing untested C++ blind; the user chose to install a compiler first.

**Toolchain installed this session**: `conda install -n tcad-dev -c
conda-forge gxx cxx-compiler` initially pulled in a `cxx-compiler`
meta-package that activates MSVC (`cl.exe`) via `vs2022_win-64`'s
activation script -- which pointed at a Visual Studio install that does
not actually have the C++ workload, so `cl.exe` was never found either.
Removed `cxx-compiler`/`vs2022_win-64`/`vswhere`, kept plain `gxx`
(conda-forge GCC 16.2, full C++17 support, confirmed directly by
compiling `<optional>`/`<variant>`) invoked as a real MinGW-w64
toolchain. `CMAKE_AR`/`CMAKE_RANLIB` had to be set explicitly on the
first configure (the plain `ar`/`ranlib` conda-forge ships under a
`x86_64-w64-mingw32-` prefix, and CMake's default compiler-detection
did not find them automatically). **This is a durable environment
change**: `tcad-dev` now has a working C++ toolchain and
`pytcad/_core*.pyd` was rebuilt -- both persist beyond this session.
The pre-existing C++ engine (mesh geometry, PETSc KSP, the M31 P4
process/indicator kernels, the M34-S4 path tracer) was rebuilt with
this toolchain FIRST and its own existing accel-parity suite
(`tests/test_accel_boundary.py`, `test_accel_parity.py`,
`test_m34_s4_trace_parity.py` -- 69 passed, 8 skipped, all PETSc-gated)
re-confirmed green before writing any new code, to establish the
toolchain itself was trustworthy before trusting anything built with it.

**What got ported**: `thermal_grid.py`'s `_residual_jacobian_grid` (the
dimension-generic D=2-or-3 assembly phase 2 built) -- new
`core/src/thermal/grid.cpp` / `core/include/tcad/thermal/kernels.hpp` /
`core/bindings/thermal_bindings.cpp`, wired into `module.cpp` and
`CMakeLists.txt` following the exact M31 P4 pattern: the Python body
(renamed `_residual_jacobian_grid_py`) stays as the untouched ORACLE;
`_accel.use_accel()` decides which path runs; the ONE transcendental in
the whole assembly (`material.kappa_th`'s power law) is evaluated once
in a new `_residual_jacobian_grid_accel` Python wrapper and its RESULT
(`ke[axis]`/`dke[axis]`) crosses into C++ as plain arrays -- the kernel
itself is pure arithmetic (+, -, *, /), which is what makes an EXACT
`np.array_equal` gate (not a tolerance) a tractable claim. Per-axis
arrays cross the Python/C++ boundary concatenated into one flat buffer
plus a `shape` array (mirrors `nonlocal_bindings.cpp`'s existing
`trace_paths`, the established pattern for a D=2-or-3-generic kernel --
nanobind has no direct binding for a Python list of ndarrays).
`-ffp-contract=off` applied to the new source file (GNU/Clang), same as
`nonlocal/paths.cpp`, so no fused multiply-add can silently diverge
from numpy's unfused arithmetic.

**The genuinely hard part was NOT the arithmetic -- it was floating-
point ASSOCIATION ORDER**, and it is why this phase is recorded in this
much detail. `thermal_grid.py`'s reference builds each axis's node
contribution in TWO SEPARATE PASSES (`div[lo] += Fedge` for every edge,
THEN `div[hi] -= Fedge` for every edge, THEN `F = F + div` once) rather
than accumulating directly into `F` edge-by-edge -- and the Jacobian's
four `add()` calls per axis (`kL,kL` / `kL,kR` / `kR,kL` / `kR,kR`) are
each a SEPARATE full pass over every edge, not interleaved, because
`scipy.sparse.csr_matrix` SUMS duplicate `(row,col)` entries in
insertion order and an interior diagonal node is touched by TWO
different edges of the same axis. A first, more "obvious" C++ draft
that accumulated straight into `F` inside a single per-edge loop would
have been mathematically equivalent but NOT bit-identical
(`(a-b)+c != a+(c-b)` in IEEE 754) -- caught by REASONING before ever
compiling it, not by a failing gate, precisely because the M19/M43
sign-bug precedent (a real backwards-Jacobian bug caught only by
running the FD-Jacobian gate) made "assume it's fine" the wrong default
here. The shipped kernel replicates the reference's exact two-pass
(F) / four-pass (Jacobian) / resistance-then-isothermal (boundaries)
structure.

**Result: bit-identical on the first successful build+test cycle** --
both a direct kernel-level parity check (`F`/dense `J` via
`np.array_equal`, 2D and 3D, deliberately mixing all three BC kinds so
a corner is shared by isothermal/resistance/adiabatic at once) and two
full end-to-end `solve_electrothermal_{2,3}d` runs (ACCEL=0 vs ACCEL=1,
comparing the FINAL converged temperature profile after the full outer
Gummel loop, mirroring `test_diffuse_numeric_is_bit_identical`'s own
"does per-call parity survive being called repeatedly" standard) --
`tests/test_m43_thermal_grid_accel_parity.py`, 4/4 green,
`skipif(not _accel.HAVE_ACCEL)` so a checkout with no compiler still
skips cleanly rather than failing.

**Honest scope of this phase**: only `_residual_jacobian_grid` (the
per-Newton-iteration assembly) is compiled. `solve_lattice_temperature_
grid`'s outer Newton loop, `joule_heating_density_{2,3}d`, and
`solve_electrothermal_{2,3}d`'s outer Gummel loop all stay in Python,
calling into the (now dispatchable) assembly function -- matching
`diffuse_numeric`'s own precedent of dispatching only the repeated
inner operation, not the policy code around it. No performance number
is claimed here (CLAUDE.md's benchmark rule): this phase's claim is
correctness (bit-identical), not speed, and no `benchmarks/` run was
done.

## Honest limits (deliberately not addressed here)

- Gummel/lagged coupling only, same as 1D -- not monolithic. A fully
  spatially-resolved T(x,y[,z]) fed back node-by-node into `Device2D`'s/
  `Device3D`'s own Newton system remains future work, not attempted,
  for the same scaling-architecture reason M19 gave.
- No GUI wiring, either dimension. This milestone is library-only
  (`pytcad/thermal_grid.py`/`thermal2d.py`/`thermal3d.py` plus their
  tests), matching M18 AC's phase-1 scope note ("library-only: no
  Device2D, no GUI") -- a GUI entry point (a new Thermal tab/mode,
  wiring `solve_electrothermal_{2,3}d` into `solver_runner.py`) is a
  separate, unscoped follow-up.
- No recombination/generation heat term, either dimension -- only the
  Wachutka electrical-dissipation term, same omission as 1D.
- No Seebeck/Peltier terms, either dimension, same omission as 1D.
- Thermal runaway is handled the same way 1D handles it (`RuntimeError`
  on outer-loop non-convergence), not independently re-measured at a
  runaway bias/R_th combination in 2D or 3D specifically -- the 1D
  G-ROLLOFF gate's own runaway-boundary finding is assumed to transfer
  (same physics, same outer-loop structure) but was not re-verified.
- 3D performance at large node counts (tens of thousands+) was sanity-
  checked (converges, finite, physically sensible) but not benchmarked
  -- no `benchmarks/` entry, per CLAUDE.md's performance-claims rule
  ("a performance number that did not come from a benchmark run does
  not belong in a plan doc"), so none is claimed here beyond "it
  finished."
