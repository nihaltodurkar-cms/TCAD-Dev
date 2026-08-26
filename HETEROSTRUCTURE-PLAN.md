# Heterostructure Regions -- Milestone Plan (M11 proposal)

Status: S1-S4 SHIPPED (materials layer; DeviceSpec.region_materials
wire format with parse-time validation; 1D heterojunction core --
eps(x) harmonic-mean flux-form Poisson, Anderson band offsets via
CARRIER-SPECIFIC ln(nie) SG deltas, per-material recombination;
acceptance: FD-Jacobian across Si/GaAs < 5e-5, detailed balance
exact, homojunction bit-identical).  S4 SHIPPED 2026-08-26: the same
physics on Device2D's box integration -- per-node material lists,
harmonic-mean edge eps normalized so uniform devices stay
bit-identical, carrier-specific ln(nie) deltas per axis, grouped
per-material parameters; gates in tests/test_m11s4_2d_hetero.py
(homojunction array_equal bit-identity; FD-Jacobian across Si/GaAs
<= 5e-5; machine-precision zero equilibrium current, both carriers;
dimensional reduction to the validated 1D heterojunction solution;
fd+hetero composition Jacobian).  S5 SHIPPED 2026-08-26: per-region
materials ride the whole authored path (Region.material ->
RegionSpec.material -> region_materials emitted by to_device_spec for
every non-silicon region; the M11-S4 data-loss guard is GONE -- the
round-trip is lossless), and the HBT / HEMT parametric templates build
on top: AlGaAs/GaAs layered stacks (wide-gap emitter/base/collector;
buffer/channel/barrier + Schottky gate) that solve end-to-end through
the backend pipeline.  GUI: region editor gains a Material combobox
fed from the library (setRegionMaterial with undo; canonical keys).
Gates in gui/tests/test_m11s5_templates.py.  The M11 milestone is now
COMPLETE except devsim-backend hetero support (explicitly optional/
last per the plan).  Key lesson (section 4 mechanism proved
necessary): a shared band-offset delta passed the FD-Jacobian but
broke hole detailed balance -- only a carrier-specific equilibrium
check catches that class.

Read alongside ARCHITECTURE.md sections 3/4/6 and history.md.

------------------------------------------------------------------------
1. CURRENT STATE (verified against the tree)
------------------------------------------------------------------------
- `pytcad.Semiconductor` (materials.py): one parameter set exists --
  SILICON.  Mobility/lifetime/Auger/BGN parameters all live here; the
  Newton assemblies consume `self.mat.*` everywhere.
- Device1D/2D/3D take ONE `material: Semiconductor` per DEVICE.  There
  is no epsilon(x), no band-edge x-dependence, no interface anywhere in
  the cores.  This is THE change heterostructures require -- everything
  else is plumbing.
- workbench `MaterialLibrary` (core/materials.py): registry with
  equations/references/applicability; currently backs the catalog UI.
- `DomainDevice.material` is device-wide; per-region `Region.material`
  exists but `validate()` rejects anything non-SILICON *honestly*
  ("registered but not solvable").  Adapters propagate the same refusal.
- StructureModel/UI: material field is read-only "Silicon".
- devsim backend: SetSiliconParameters hardcoded.

------------------------------------------------------------------------
2. PHYSICS SCOPE -- what becomes true
------------------------------------------------------------------------
P-A  Position-dependent permittivity eps(x): Poisson flux coefficients
     become position-dependent; box/FV assembly needs the standard
     harmonic-mean permittivity on each edge (same trick as D_n already
     uses).  Lowest-risk entry point.
P-B  Position-dependent band edges: E_c(x) = -psi - chi(x),
     E_g(x), Nc/Nv(x), ni_eff(x) -- carrier densities become
     position-dependent Boltzmann factors.  Continuity equations gain
     band-offset terms; SG currents must be formulated against
     (+psi - phi_n) with chi(x) inside, or the equivalent density-
     gradient form.  This touches every hand-derived Jacobian.
P-C  Interface conditions: default = continuous displacement
     (eps*E) and thermionic-emission current across the band offset
     (the standard DD-level treatment).  Quantum/tunneling explicitly
     OUT (matches the existing honesty list).
P-D  Alignment convention: Anderson electron-affinity rule
     (dE_c = -d_chi), documented as an assumption with its known
     failure modes (no interface dipoles, no strain).
P-E  Mesh constraint: material interfaces MUST lie on mesh lines
     (tensor-product meshes stay; no cut cells).

------------------------------------------------------------------------
3. STAGED SLICES (each ships suite-green, in dependency order)
------------------------------------------------------------------------
S1  MATERIALS LAYER ONLY (no solver changes)
    - Grow the library: Ge, GaAs, In0.53Ga0.47As, Al_xGa1-xAs (mole
      fraction as a parameter-family factory), each as a full
      Semiconductor set with provenance comments and honest ranges.
    - DomainDevice.validate(): heterogeneous per-region materials become
      LEGAL in the domain layer; adapters and solvers keep refusing with
      an upgraded message ("requires the heterostructure backend,
      milestone M11-S3").
    - UI: Region editor gains a material dropdown fed from the library.
    Tests: round-trip, registry completeness, adapter refusals.

S2  WIRE FORMAT
    - DeviceSpec carries per-region materials losslessly (region-tagged
      material list keyed to mesh spans / region rectangles).
    - pytcad backend validates: all-silicon jobs unchanged; mixed
      material jobs fail fast with the S3 message.
    Tests: JSON round-trip both directions; golden equality for every
    existing project/example file.

S3  1D HETEROJUNCTION CORE  <-- the milestone's center of mass
    - Device1D gains per-node material arrays: eps(x), chi(x), Eg(x),
      Nc/Nv/ni(x), mu/lifetime parameter sets selected per node.
    - Poisson: harmonic-mean eps edges.  Continuity: band-offset-aware
      SG currents.  Jacobian: extended analytically, verified by the
      existing finite-difference Jacobian test extended to interfaces.
    - GATES before merge (project rule):
        a) homojunction regression: all-same-material results
           bit-identical to today's solver;
        b) analytic isotype heterojunction equilibrium vs the
           Anderson-model closed form;
        c) one PUBLISHED benchmark (e.g., AlGaAs/GaAs HBT-style
           band diagram or anisotype-junction I-V literature values)
           with quantitative error reporting;
        d) adversarial probe pass (interface placement off-node must
           fail loudly; degenerate offset limits).
    - Catalog: heterojunction interface model registered with equations
      and references (thermionic emission, Anderson rule).
S4  2D BOX-INTEGRATION equivalent (same math, face-normal eps).
S5  TEMPLATES + UI: HBT / HEMT parametric templates; Structure panel
    per-region material editing unlocked; Physics Lab shows interface
    provenance.  devsim backend hetero support optional/last.

------------------------------------------------------------------------
4. RULE AMENDMENT REQUIRED (explicit)
------------------------------------------------------------------------
history.md's "numerical core: NO changes except exposing values" was
written for the workbench-refactor era.  S3 deliberately amends it for
this milestone only: core changes are allowed INSIDE Device1D's
assembly, gated by (a)-(d) above and reviewed per-commit.  Device2D/3D
stay frozen until their own slices.  Without signing off on this
amendment, do not start S3.

------------------------------------------------------------------------
5. RISKS
------------------------------------------------------------------------
R1  Newton conditioning at large band offsets (classic failure);
    mitigations: offset-ramped continuation, damped updates -- same
    toolset the existing solver already uses.
R2  Parameter-set quality for non-Si materials varies in literature;
    every set ships with references AND an applicability/uncertainty
    note in the catalog (honesty rule).
R3  Scope creep toward quantum/tunneling: stays OUT (existing §6 list).
R4  The 25 mV ni-table cross-engine gotcha becomes material-dependent;
    cross-backend gates must compare per-material, not globally.

------------------------------------------------------------------------
6. EFFORT SHAPE
------------------------------------------------------------------------
S1 ~ small (library data + validation flips + UI dropdown).
S2 ~ small (wire format + tests).
S3 ~ large (the real milestone; expect the finite-difference-Jacobian
     extension and benchmark hunting to dominate).
S4 medium once S3 lands.  S5 medium.

Recommended entry: S1 immediately; S2 next session; S3 planned as its
own dedicated effort after user sign-off on section 4.

------------------------------------------------------------------------
7. S3 DESIGN NOTES (from the code audit -- implement directly)
------------------------------------------------------------------------
Injection points verified in pytcad/device.py:

- Constructor (:133): `material` may accept a LIST of Semiconductor
  instances (one per node).  All downstream fields become arrays:
  nie_s already is one; eps, mu, tau need per-node computation by
  grouping nodes per material (Caughey-Thomas/lifetime calls are
  already array-wise over Ntot -- pass each material's params on its
  node subset).

- Epsilon heterogeneity WITHOUT breaking scaling: keep global Ns/LD
  from the REFERENCE material (max eps_r); introduce scaled
  eps_tilde_i = eps_i/eps_ref and rewrite the Poisson residual as the
  conservative flux form
      F_i = [eps~_{i+1/2}(psi_{i+1}-psi_i)/h - eps~_{i-1/2}(psi_i-
            psi_{i-1})/h] / dV_i - rho_i,
  with harmonic-mean eps~ on edges.  For eps~=1 everywhere this
  reduces ALGEBRAICALLY to today's F -- the homojunction bit-identical
  regression (gate a) is then structural, not empirical.  Jacobian
  additions are the direct derivatives of the two flux coefficients.

- THE CRITICAL SUBTLETY (identified, unsolved tonight): carrier
  densities are Boltzmann against ni(x), which now VARIES.  The
  current SG form Jn = an*(n1*Bp - n0*Bm) is slot-key consistent only
  for spatially constant normalization.  Correct treatment needs the
  Slotboom/position-dependent-density form with explicit band-offset
  factors at abrupt interfaces, e.g. edge factor
      exp(-(chi_{i+1}-chi_i)/VT) * (NC_{i+1}/NC_i)
  inside the electron current, and the mirror for holes.  Getting the
  discretization AND its Jacobian right is the heart of S3; budget a
  dedicated session with the finite-difference Jacobian test extended
  across an interface as the first red test.

- Contact values (_contact_values): already per-node C/nie_s -> correct
  per-material ohmic contacts for free once nie_s is per-node.

- band_diagram(): gains chi(x)/Eg(x) arrays trivially.

Recommended first red test for the next session: extend
test_jacobian_matches_finite_differences to a two-material grid
(Si/GaAs split at mid-device) -- everything else follows from making
that green without breaking the homojunction goldens.
