// Process- and adaptivity-side kernels (M31 P4).
//
// WHAT IS HERE AND WHY EACH ONE IS
// --------------------------------
// P2 ported the mesh geometry because it was the measured blocker.  The
// same rule chose this file's contents; the measurements are in
// M31-CPP-ARCHITECTURE-PLAN.md's P4 section, and two candidates named in
// the phase table were EXCLUDED by those same measurements rather than
// silently skipped (Monte-Carlo implant, and the lateral smoothing in
// process2d.implant_2d -- see there).
//
// THE ARITHMETIC THAT STAYS IN PYTHON, AND WHY
// --------------------------------------------
// Every transcendental that acts on a whole array stays on the numpy
// side and its RESULT is passed down: `np.log(n)` for the log-density
// indicator, `mesh.debye_length(...)` for the Debye ratio, the peak
// `scale` for the curvature indicator.  This is the same split P3b used
// for the solver, and for the same reason: it makes bit-identity
// STRUCTURAL instead of a claim about two libm implementations agreeing.
//
// The one transcendental that did NOT stay in Python is the TED
// supersaturation's scalar `exp`, because keeping it there would have
// meant materializing one double per timestep (millions, for a fine
// grid) purely to hand it back.  That exception is MEASURED, not
// assumed: over 400k arguments spanning the range this model reaches,
// std::exp and np.exp agreed bit-for-bit on every one, via both numpy's
// array path and its 0-d scalar path (which is what
// ted.ted_supersaturation actually calls).
//
// FLOATING-POINT ORDER
// --------------------
// Every reduction below reproduces the reference's association order
// and, where Python's builtin `max`/`min` are involved, its exact
// replacement rule (`if item > current`) -- so a NaN propagates the same
// way rather than the same way "in practice".  See the notes at each
// kernel.  All of these are serial: they are O(n) passes over a few
// arrays, the reference's own order is not reassociable, and none of
// them was the thing that made the profile slow.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace tcad::process {

// ----------------------------------------------------------------------
//  Per-triangle AMR indicators (pytcad/adapt_unstructured.py)
// ----------------------------------------------------------------------
// All three reduce over a triangle's three edges (a,b), (b,c), (c,a) in
// that order and write one value per triangle.  `nodes_xyz` is the
// (n_nodes, 3) c-contiguous node array the rest of the engine already
// uses; only x and y are read, matching the reference's `[:, :2]`.

/// indicator_curvature_tri: max over the 3 edges of |edge| * |dpsi|,
/// divided by the caller-supplied peak scale.
///
/// `scale` is computed in Python (`max(float(np.max(np.abs(psi))),
/// 1e-300)`) rather than here, so an empty psi raises numpy's own
/// ValueError from the reference's own line.
std::vector<double> indicator_curvature_tri(const double* nodes_xyz, std::int64_t n_nodes,
                                            const std::int64_t* tris, std::int64_t n_tris,
                                            const double* psi, double scale);

/// indicator_log_density_tri: max over the 3 edges of
/// max(|d ln n|, |d ln p|).  Takes the LOGS, already computed by numpy.
std::vector<double> indicator_log_density_tri(std::int64_t n_nodes,
                                              const std::int64_t* tris, std::int64_t n_tris,
                                              const double* ln_n, const double* ln_p);

/// debye_ratio_tri: (longest edge) / max(min nodal Debye length, 1e-300).
/// Takes the nodal Debye lengths, already computed by numpy.
std::vector<double> debye_ratio_tri(const double* nodes_xyz, std::int64_t n_nodes,
                                    const std::int64_t* tris, std::int64_t n_tris,
                                    const double* ld_node);

// ----------------------------------------------------------------------
//  1D explicit diffusion time loops
// ----------------------------------------------------------------------
// Both kernels take the grid metrics the reference precomputes once
// (`h` = np.diff(x), `dV` = the dual-cell widths) rather than x itself,
// so the two paths cannot disagree about the mesh before the loop even
// starts.  `C` is updated IN PLACE on a buffer the binding owns; the
// caller's array is never touched.
//
// `n_steps` is the ALREADY-RESOLVED count (the reference raises it to
// satisfy its own stability bound before the loop), and `dt` the
// already-divided step.  Deciding the step count is policy and stays in
// Python where it can be read.

/// process.diffuse_numeric's loop: constant D.
void diffuse1d_const(double* C, std::int64_t n,
                     const double* h, const double* dV,
                     double D, double dt, std::int64_t n_steps, bool reflecting);

/// ted.diffuse_with_defects' loop: D varies per node (extrinsic
/// enhancement) and per step (TED decay + a constant OED boost).
///
/// `ted_S0 == 0.0` skips the exponential entirely, exactly as the
/// reference does -- which is also what makes `ted_tau_s` allowed to be
/// meaningless in that case, since the reference permits None there.
void diffuse1d_enhanced(double* C, std::int64_t n,
                        const double* h, const double* dV,
                        double Di, const double* extrinsic,
                        double ted_S0, double ted_tau_s, double oed_boost,
                        double dt, std::int64_t n_steps, bool reflecting);

}  // namespace tcad::process
