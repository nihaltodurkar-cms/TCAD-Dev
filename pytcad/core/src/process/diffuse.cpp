// The 1D explicit diffusion time loops.
//
// These are transcriptions, not reimplementations. Each numpy statement
// in the reference becomes one loop here, in the same order, with the
// same association -- including the places where that costs a temporary
// (`flux` is materialized because the reference materializes it, and
// `dC` is applied only after the whole vector exists, because
// `C = C + dt * dC` is not an in-place update and a fused version would
// feed step k's new C[i-1] into step k's own C[i]).
//
// What made the Python version slow was never the arithmetic: at
// n = 400 it ran ~85 Mnode-updates/s, which is memory-bandwidth-absurd
// for three passes over a 3 KB array. It was ~10 numpy dispatches per
// timestep against a step count the stability bound drives into the
// tens of thousands. So there is no vectorization trick here and none is
// needed -- removing the per-step interpreter round trip is the whole
// change, which is also why these stay serial and stay exact.
#include "tcad/process/kernels.hpp"

#include <cmath>
#include <vector>

namespace tcad::process {
namespace {

/// The tail shared by both loops: turn `flux` into `dC` and apply it.
/// Split out because the two references differ ONLY in how they get
/// flux, and duplicating the boundary handling is how the two paths
/// would eventually drift apart.
inline void apply_flux(double* C, std::vector<double>& dC,
                       const double* flux, const double* dV,
                       std::int64_t n, double dt, bool reflecting) {
    // dC[1:-1] = -(flux[1:] - flux[:-1]) / dV[1:-1]
    for (std::int64_t i = 1; i < n - 1; ++i)
        dC[static_cast<std::size_t>(i)] = -(flux[i] - flux[i - 1]) / dV[i];
    // dC[0] = -flux[0] / dV[0] if reflecting else 0.0
    dC[0] = reflecting ? -flux[0] / dV[0] : 0.0;
    // dC[-1] = flux[-1] / dV[-1]   (assigned after dC[0], as in the
    // reference -- they are different elements for every n >= 2, which
    // the binding enforces)
    dC[static_cast<std::size_t>(n - 1)] = flux[n - 2] / dV[n - 1];

    for (std::int64_t i = 0; i < n; ++i)
        C[i] = C[i] + dt * dC[static_cast<std::size_t>(i)];

    if (!reflecting) C[0] = 0.0;
}

}  // namespace

void diffuse1d_const(double* C, std::int64_t n,
                     const double* h, const double* dV,
                     double D, double dt, std::int64_t n_steps, bool reflecting) {
    std::vector<double> flux(static_cast<std::size_t>(n - 1));
    std::vector<double> dC(static_cast<std::size_t>(n), 0.0);

    for (std::int64_t s = 0; s < n_steps; ++s) {
        // flux = -D * np.diff(C) / h  ->  ((-D) * (C[i+1]-C[i])) / h[i]
        for (std::int64_t i = 0; i < n - 1; ++i)
            flux[static_cast<std::size_t>(i)] = (-D * (C[i + 1] - C[i])) / h[i];
        apply_flux(C, dC, flux.data(), dV, n, dt, reflecting);
    }
}

void diffuse1d_enhanced(double* C, std::int64_t n,
                        const double* h, const double* dV,
                        double Di, const double* extrinsic,
                        double ted_S0, double ted_tau_s, double oed_boost,
                        double dt, std::int64_t n_steps, bool reflecting) {
    std::vector<double> D_node(static_cast<std::size_t>(n));
    std::vector<double> flux(static_cast<std::size_t>(n - 1));
    std::vector<double> dC(static_cast<std::size_t>(n), 0.0);

    double t = 0.0;
    for (std::int64_t s = 0; s < n_steps; ++s) {
        // S_ted = S0 * exp(-t / tau), skipped entirely when S0 == 0.0 --
        // the reference short-circuits there, which is what lets it
        // accept ted_tau_s=None in that case.
        const double S_ted = (ted_S0 != 0.0) ? ted_S0 * std::exp(-t / ted_tau_s) : 0.0;
        const double factor = (1.0 + S_ted) + oed_boost;

        // D_node = Di * extrinsic * factor -- numpy folds left to right.
        for (std::int64_t i = 0; i < n; ++i)
            D_node[static_cast<std::size_t>(i)] = (Di * extrinsic[i]) * factor;

        // D_face = 0.5 * (D_node[:-1] + D_node[1:]); flux as above.
        for (std::int64_t i = 0; i < n - 1; ++i) {
            const double D_face = 0.5 * (D_node[static_cast<std::size_t>(i)] +
                                         D_node[static_cast<std::size_t>(i + 1)]);
            flux[static_cast<std::size_t>(i)] = (-D_face * (C[i + 1] - C[i])) / h[i];
        }
        apply_flux(C, dC, flux.data(), dV, n, dt, reflecting);
        t += dt;
    }
}

}  // namespace tcad::process
