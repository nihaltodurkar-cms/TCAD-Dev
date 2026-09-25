#include "tcad/device3d/poisson_eq.hpp"

namespace tcad::device3d {

PoissonEq poisson_eq_stencil(std::int64_t Nz, std::int64_t Ny, std::int64_t Nx,
                             const double* psi, const double* n, const double* p,
                             const double* C, const double* dnp, const double* dV,
                             const double* et_x, const double* et_y, const double* et_z,
                             const double* hx, const double* hy, const double* hz,
                             const double* dVx, const double* dVy, const double* dVz,
                             const std::int64_t* gate_rows, const double* gate_vals,
                             std::int64_t G, const std::int64_t* contact, std::int64_t K) {
    const std::int64_t NxNy = Nx * Ny;
    const std::int64_t N = Nz * NxNy;
    const std::int64_t Ex = Nx > 1 ? Nz * Ny * (Nx - 1) : 0;
    const std::int64_t Ey = Ny > 1 ? Nz * (Ny - 1) * Nx : 0;
    const std::int64_t Ez = Nz > 1 ? (Nz - 1) * NxNy : 0;
    const std::int64_t M = 4 * (Ex + Ey + Ez) + N;
    const std::int64_t cap = M + G + K;   // before contact compaction

    PoissonEq out;
    out.F.resize(static_cast<std::size_t>(N));
    out.rows.resize(static_cast<std::size_t>(cap));
    out.cols.resize(static_cast<std::size_t>(cap));
    out.vals.resize(static_cast<std::size_t>(cap));
    std::int64_t* R = out.rows.data();
    std::int64_t* Cc = out.cols.data();
    double* V = out.vals.data();

    // Edge fluxes, e.g. Fx = et_x * (psi[i+1] - psi[i]) / hx[i].
    auto fx = [&](std::int64_t k, std::int64_t j, std::int64_t i) {
        const std::int64_t e = (k * Ny + j) * (Nx - 1) + i;
        const std::int64_t a = k * NxNy + j * Nx + i;
        return et_x[e] * (psi[a + 1] - psi[a]) / hx[i];
    };
    auto fy = [&](std::int64_t k, std::int64_t j, std::int64_t i) {
        const std::int64_t e = (k * (Ny - 1) + j) * Nx + i;
        const std::int64_t a = k * NxNy + j * Nx + i;
        return et_y[e] * (psi[a + Nx] - psi[a]) / hy[j];
    };
    auto fz = [&](std::int64_t k, std::int64_t j, std::int64_t i) {
        const std::int64_t a = k * NxNy + j * Nx + i;
        return et_z[a] * (psi[a + NxNy] - psi[a]) / hz[k];
    };

    for (std::int64_t k = 0; k < Nz; ++k) {
        for (std::int64_t j = 0; j < Ny; ++j) {
            for (std::int64_t i = 0; i < Nx; ++i) {
                const std::int64_t a = k * NxNy + j * Nx + i;
                double dx = 0.0, dy = 0.0, dz = 0.0;
                if (i < Nx - 1) dx = 0.0 + fx(k, j, i);
                if (i > 0) dx = dx - fx(k, j, i - 1);
                if (j < Ny - 1) dy = 0.0 + fy(k, j, i);
                if (j > 0) dy = dy - fy(k, j - 1, i);
                if (k < Nz - 1) dz = 0.0 + fz(k, j, i);
                if (k > 0) dz = dz - fz(k - 1, j, i);
                out.F[a] = dVy[j] * dVz[k] * dx + dVx[i] * dVz[k] * dy +
                           dVx[i] * dVy[j] * dz - dV[a] * (n[a] - p[a] - C[a]);
            }
        }
    }

    // x edges: 4 segments [kL,kL,-w] [kR,kR,-w] [kL,kR,+w] [kR,kL,+w]
    for (std::int64_t k = 0; k < Nz; ++k)
        for (std::int64_t j = 0; j < Ny; ++j)
            for (std::int64_t i = 0; i + 1 < Nx; ++i) {
                const std::int64_t e = (k * Ny + j) * (Nx - 1) + i;
                const std::int64_t L = k * NxNy + j * Nx + i, Rn = L + 1;
                const double w = dVy[j] * dVz[k] / hx[i] * et_x[e];
                R[e] = L;           Cc[e] = L;           V[e] = -w;
                R[Ex + e] = Rn;     Cc[Ex + e] = Rn;     V[Ex + e] = -w;
                R[2 * Ex + e] = L;  Cc[2 * Ex + e] = Rn; V[2 * Ex + e] = w;
                R[3 * Ex + e] = Rn; Cc[3 * Ex + e] = L;  V[3 * Ex + e] = w;
            }
    const std::int64_t by = 4 * Ex;
    for (std::int64_t k = 0; k < Nz; ++k)
        for (std::int64_t j = 0; j + 1 < Ny; ++j)
            for (std::int64_t i = 0; i < Nx; ++i) {
                const std::int64_t e = (k * (Ny - 1) + j) * Nx + i;
                const std::int64_t S = k * NxNy + j * Nx + i, Nn = S + Nx;
                const double w = dVx[i] * dVz[k] / hy[j] * et_y[e];
                R[by + e] = S;           Cc[by + e] = S;           V[by + e] = -w;
                R[by + Ey + e] = Nn;     Cc[by + Ey + e] = Nn;     V[by + Ey + e] = -w;
                R[by + 2 * Ey + e] = S;  Cc[by + 2 * Ey + e] = Nn; V[by + 2 * Ey + e] = w;
                R[by + 3 * Ey + e] = Nn; Cc[by + 3 * Ey + e] = S;  V[by + 3 * Ey + e] = w;
            }
    const std::int64_t bz = 4 * (Ex + Ey);
    for (std::int64_t e = 0; e < Ez; ++e) {
        const std::int64_t k = e / NxNy, j = (e / Nx) % Ny, i = e % Nx;
        const std::int64_t D = e, U = e + NxNy;
        const double w = dVx[i] * dVy[j] / hz[k] * et_z[e];
        R[bz + e] = D;           Cc[bz + e] = D;           V[bz + e] = -w;
        R[bz + Ez + e] = U;      Cc[bz + Ez + e] = U;      V[bz + Ez + e] = -w;
        R[bz + 2 * Ez + e] = D;  Cc[bz + 2 * Ez + e] = U;  V[bz + 2 * Ez + e] = w;
        R[bz + 3 * Ez + e] = U;  Cc[bz + 3 * Ez + e] = D;  V[bz + 3 * Ez + e] = w;
    }
    const std::int64_t bd = 4 * (Ex + Ey + Ez);
    for (std::int64_t a = 0; a < N; ++a) {
        R[bd + a] = a;
        Cc[bd + a] = a;
        V[bd + a] = -dV[a] * dnp[a];
    }

    // gate (Robin) diagonal entries, appended in the reference's order
    for (std::int64_t g = 0; g < G; ++g) {
        R[M + g] = gate_rows[g];
        Cc[M + g] = gate_rows[g];
        V[M + g] = gate_vals[g];
    }
    std::int64_t len = M + G;
    if (K > 0) {
        // keep = ~np.isin(rows, contact): stable in-place compaction
        std::vector<char> is_contact(static_cast<std::size_t>(N), 0);
        for (std::int64_t c = 0; c < K; ++c) is_contact[contact[c]] = 1;
        std::int64_t w = 0;
        for (std::int64_t e = 0; e < len; ++e) {
            if (is_contact[R[e]]) continue;
            R[w] = R[e]; Cc[w] = Cc[e]; V[w] = V[e]; ++w;
        }
        for (std::int64_t c = 0; c < K; ++c, ++w) {
            R[w] = contact[c]; Cc[w] = contact[c]; V[w] = 1.0;
        }
        len = w;
    }
    out.rows.resize(static_cast<std::size_t>(len));
    out.cols.resize(static_cast<std::size_t>(len));
    out.vals.resize(static_cast<std::size_t>(len));
    return out;
}

}  // namespace tcad::device3d
