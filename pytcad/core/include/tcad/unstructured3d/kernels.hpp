// M47 Slice 1: unstructured (tetrahedral-mesh) 3D drift-diffusion
// interior-physics assembly -- pytcad/unstructured_dd3d.py's own
// _residual_jacobian_poisson3d/_residual_jacobian_dd3d, factored into
// named blocks (see that module's own _poisson_flux_geometry_coo /
// _poisson_equilibrium_diag_coo / _poisson_charge_coupling_coo /
// _srh_auger_coo / _sg_carrier_coo, the Python oracle these mirror
// 1:1). Geometry (unstructured_assembly3d.py -> mesh/stencil.cpp) is
// UNTOUCHED by this file -- this is interior-physics assembly only,
// consuming that geometry's already-computed edges/trans/node_vols.
//
// TRANSCENDENTALS NEVER CROSS THIS BOUNDARY (M47 design review item 1):
// exp() [equilibrium's Boltzmann n/p], bernoulli()/dbernoulli() [SG
// current] all stay in Python -- every array below that a transcendental
// would normally produce (n, p, flux, Bp, Bm, dBp, dBm) is passed in
// ALREADY COMPUTED. This kernel set is pure arithmetic end to end,
// exactly the property that makes np.array_equal bit-identity against
// the Python oracle a tractable claim (see thermal/kernels.hpp's own
// header comment for the same argument, one milestone earlier).
//
// COO/F EMISSION ORDER IS NOT ARBITRARY (M47 design review item 2):
// scipy sums duplicate (row,col) entries in insertion order once the
// assembled matrix is canonicalized downstream (.tocsc()/eliminate_csr).
// The two orchestrated entry points below (residual_jacobian_equilibrium,
// residual_jacobian_coupled) concatenate blocks in the EXACT order
// traced from the Python oracle -- equilibrium: flux geometry THEN
// diagonal charge term; coupled: SRH/Auger THEN Poisson charge-coupling
// THEN Poisson flux geometry THEN electron SG THEN hole SG. Reordering
// is a real (if tiny) floating-point change, not a style choice -- see
// M47-3D-ENGINE-PLAN.md's COO-ordering record.
//
// BINDING SHAPE (M47 design review item 2, resolved by measurement):
// only the two ORCHESTRATED functions are bound via nanobind -- a
// throwaway micro-benchmark (M47-3D-ENGINE-PLAN.md) found no measurable
// difference (<0.01% of real per-call assembly cost) between 4 separate
// bound calls and 1 bound orchestrator, so the lower-risk default (1
// bound call per solve mode, modular C++ functions underneath) was kept
// as the final choice. The modular functions below are still separate,
// independently testable C++ functions -- only the PYTHON-visible
// surface is collapsed to two entry points.
#pragma once

#include <cstdint>
#include <span>
#include <vector>

namespace tcad::unstructured3d {

/// One COO block: parallel rows/cols/vals, no assumption of dtype
/// shared indexing with any other block -- concatenation order across
/// blocks is the caller's responsibility (see file header).
struct Coo {
    std::vector<std::int64_t> rows;
    std::vector<std::int64_t> cols;
    std::vector<double> vals;
};

/// Full assembled result of one of the two orchestrated entry points --
/// mirrors thermal::GridResult's shape (F + one flat COO triple).
struct Result {
    std::vector<double> F;
    Coo J;
};

// ------------------------------------------------------------------
//  Shared block: Poisson interior-flux Jacobian stamp.
//
//  Identical formula in BOTH equilibrium and coupled regimes -- the
//  flux term does not care whether n/p are slaved to psi or are
//  independent Newton unknowns. `comp3 < 0` selects the equilibrium
//  (N-DOF, raw node-index) form; `comp3 >= 0` selects the coupled
//  (3N-DOF, row/col = 3*node + comp3) form -- comp3=0 for the psi
//  component, matching the Python oracle's own indexing convention.
// ------------------------------------------------------------------
Coo poisson_flux_geometry(std::span<const std::int64_t> edge_i,
                          std::span<const std::int64_t> edge_j,
                          std::span<const double> trans, int comp3);

// ------------------------------------------------------------------
//  Equilibrium-ONLY: the slaved-carrier diagonal chain-rule term
//  (d(n-p)/dpsi = n+p), emitted AFTER flux geometry. No coupled-path
//  equivalent -- see _poisson_charge_coupling below, a DIFFERENT
//  Jacobian shape for the same physical derivative.
// ------------------------------------------------------------------
Coo poisson_equilibrium_diag(std::span<const double> node_vols_s,
                             std::span<const double> n,
                             std::span<const double> p);

// ------------------------------------------------------------------
//  Coupled-ONLY: d(rho)/dn, d(rho)/dp as two OFF-diagonal entries into
//  the psi row's n/p columns, emitted BEFORE flux geometry (opposite
//  order from the equilibrium path's own diagonal term).
// ------------------------------------------------------------------
Coo poisson_charge_coupling(std::span<const double> node_vols_s);

// ------------------------------------------------------------------
//  SRH + Auger recombination, exactly materials.recombination's
//  Boltzmann form (np_eq=None path -- this module has no Fermi-Dirac
//  composition, by its own documented scope). n/p here are SCALED
//  (code units); nie_phys (PER NODE -- M47 Slice 3 heterojunctions;
//  a homojunction passes N copies of one value, which is arithmetically
//  identical to the former scalar), Ns, R0 do the physical/scaled conversion
//  internally, matching the Python call site
//  `recombination(n*Ns, p*Ns, nie_s*Ns, tau_n, tau_p, material,
//  auger=auger)` then `Rs=R/R0` etc. Returns the F1/F2 BASELINE
//  (direct-set values, not yet carrying the SG accumulation the
//  orchestrator adds on top) and the 4-entry (n,p)x(n,p) diagonal COO
//  block -- emitted FIRST in the coupled assembly (see file header).
//  auger_cn/auger_cp are the ONLY two fields of `material` this
//  computation reads (Semiconductor.Cn_auger/Cp_auger).
// ------------------------------------------------------------------
struct SrhResult {
    std::vector<double> F1_baseline;
    std::vector<double> F2_baseline;
    Coo diag;
};
SrhResult srh_auger(std::span<const double> n, std::span<const double> p,
                    std::span<const double> nie_phys, std::span<const double> tau_n,
                    std::span<const double> tau_p,
                    std::span<const double> node_vols_s, double Ns,
                    double R0, bool srh, bool auger, double auger_cn,
                    double auger_cp);

// ------------------------------------------------------------------
//  One carrier's SG current + its 8-entry i-row/j-row Jacobian block.
//  `comp` = 1 (electron) or 2 (hole), matching the oracle's own
//  3*node+comp indexing. Electron and hole have DIFFERENT flux
//  formulas (Bp/Bm play different roles, hole carries an overall sign
//  flip) -- NOT parameterizable by comp alone, so two thin wrapper
//  functions (sg_electron, sg_hole below) compute the carrier-specific
//  flux/derivative arrays and both call this SAME index/sign-pattern
//  builder for the COO block, mirroring the Python oracle's own
//  _sg_carrier_coo helper exactly.
// ------------------------------------------------------------------
Coo sg_carrier_jacobian(std::span<const std::int64_t> edge_i,
                        std::span<const std::int64_t> edge_j, int comp,
                        std::span<const double> dJ_dpsi_j,
                        std::span<const double> dJ_dself_i,
                        std::span<const double> dJ_dself_j);

struct SgResult {
    std::vector<double> J_edge;   // Jn_edge or Jp_edge, edges array order
    Coo jac;
};
// NOTE: `trans_bare` here is NOT `eps_trans` -- the oracle's own
// `trans = eps_trans * LD` recovery (the M26-fix "bare geometric
// trans_geom" the SG current needs; eps_trans alone is what POISSON's
// flux/geometry terms use). Passing eps_trans here by mistake was a
// real bug caught by parity testing (M47-3D-ENGINE-PLAN.md) -- kept
// as a named, distinct parameter so the two scaled quantities cannot
// be silently swapped again at a call site.
SgResult sg_electron(std::span<const std::int64_t> edge_i,
                     std::span<const std::int64_t> edge_j,
                     std::span<const double> trans_bare,
                     std::span<const double> D_n_s,
                     std::span<const double> n,   // full node array
                     std::span<const double> Bp, std::span<const double> Bm,
                     std::span<const double> dBp, std::span<const double> dBm);
SgResult sg_hole(std::span<const std::int64_t> edge_i,
                 std::span<const std::int64_t> edge_j,
                 std::span<const double> trans_bare,
                 std::span<const double> D_p_s,
                 std::span<const double> p,   // full node array
                 std::span<const double> Bp, std::span<const double> Bm,
                 std::span<const double> dBp, std::span<const double> dBm);

// ------------------------------------------------------------------
//  Orchestrated entry points -- the ONLY two functions bound to
//  Python (see file header, binding-shape decision).
// ------------------------------------------------------------------

/// N-DOF Poisson equilibrium. `n`, `p`, `flux` already computed in
/// Python (exp() never crosses this boundary).
Result residual_jacobian_equilibrium(
    std::span<const double> n, std::span<const double> p,
    std::span<const double> C_s, std::span<const double> node_vols_s,
    std::span<const std::int64_t> edge_i,
    std::span<const std::int64_t> edge_j,
    std::span<const double> trans, std::span<const double> flux);

/// 3N-DOF coupled drift-diffusion. `flux`, `Bp`, `Bm`, `dBp`, `dBm`
/// already computed in Python (exp()/bernoulli() never cross this
/// boundary). Returns Jn_edge/Jp_edge alongside F/J -- REQUIRED by the
/// caller for terminal-current extraction (M47 design review item 3),
/// not merely an internal intermediate.
struct CoupledResult {
    Result base;
    std::vector<double> Jn_edge;
    std::vector<double> Jp_edge;
};
CoupledResult residual_jacobian_coupled(
    std::span<const double> n, std::span<const double> p,
    std::span<const double> C_s, std::span<const double> node_vols_s,
    std::span<const std::int64_t> edge_i,
    std::span<const std::int64_t> edge_j,
    std::span<const double> eps_trans, std::span<const double> flux,
    std::span<const double> trans_bare,   // eps_trans*LD -- SG only, see sg_electron's own note
    std::span<const double> D_n_s, std::span<const double> D_p_s,
    std::span<const double> Bp, std::span<const double> Bm,
    std::span<const double> dBp, std::span<const double> dBm,
    std::span<const double> nie_phys, std::span<const double> tau_n,
    std::span<const double> tau_p, double Ns, double R0, bool srh,
    bool auger, double auger_cn, double auger_cp,
    // M47 Slice 3: the HOLE Scharfetter-Gummel Bernoulli arrays. On a
    // heterojunction the hole argument is psi_j-psi_i-dlnnie+ds, not
    // the electron's +dlnnie (opposite signs, CLAUDE.md gotcha), so the
    // two carriers need separate arrays; a homojunction passes the
    // electron arrays again, which reproduces the old single-set call.
    std::span<const double> Bp_h, std::span<const double> Bm_h,
    std::span<const double> dBp_h, std::span<const double> dBm_h);

}  // namespace tcad::unstructured3d
