// Device3D equilibrium Poisson: residual F and the Jacobian's stencil +
// diagonal COO, before boundary conditions.
//
// Compiled mirror of pytcad/device3d.py::_poisson_eq_stencil_py, which
// stays as the ORACLE (tests/test_device3d_poisson_eq_accel_parity.py,
// np.array_equal on F and on rows/cols/vals in order). Operation order
// follows numpy's exactly -- e.g. div_x at an interior node is
// (0.0 + Fx[i]) - Fx[i-1], because the reference builds it as zeros,
// `+= Fx` then `-= Fx`. No transcendental: n, p, C and dn/dpsi arrive
// already computed in numpy (the M31 P4 convention). Compiled with
// -ffp-contract=off.
//
// Every output entry is written once, straight to its final offset in
// pre-sized buffers -- the M47 "reserve from the start" lesson (a chain
// of per-block vectors joined with insert() lost to np.concatenate).
#pragma once

#include <cstdint>
#include <vector>

namespace tcad::device3d {

struct PoissonEq {
    std::vector<double> F;              // (N,) C order over (Nz, Ny, Nx)
    std::vector<std::int64_t> rows;     // 4*(Ex+Ey+Ez) + N
    std::vector<std::int64_t> cols;
    std::vector<double> vals;
};

/// Arrays are flat, C order. Node fields (psi, n, p, C, dnp, dV) have
/// Nz*Ny*Nx entries; edge fields et_x/et_y/et_z have (Nz,Ny,Nx-1) /
/// (Nz,Ny-1,Nx) / (Nz-1,Ny,Nx); hx/hy/hz are the Nx-1/Ny-1/Nz-1
/// spacings and dVx/dVy/dVz the Nx/Ny/Nz control-volume widths.
/// Then, as the reference does: append the G gate (Robin) diagonal
/// entries, drop every entry whose row is one of the K contact nodes
/// (sorted, unique; order of the rest preserved), and append an
/// identity row (1.0) for each contact node.
PoissonEq poisson_eq_stencil(std::int64_t Nz, std::int64_t Ny, std::int64_t Nx,
                             const double* psi, const double* n, const double* p,
                             const double* C, const double* dnp, const double* dV,
                             const double* et_x, const double* et_y, const double* et_z,
                             const double* hx, const double* hy, const double* hz,
                             const double* dVx, const double* dVy, const double* dVz,
                             const std::int64_t* gate_rows, const double* gate_vals,
                             std::int64_t G, const std::int64_t* contact, std::int64_t K);

}  // namespace tcad::device3d
