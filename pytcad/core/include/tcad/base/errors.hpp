// The C++ exception hierarchy, and the rule that governs it.
//
// The PYTHON class is the authority.  Each type below is translated (in
// bindings/module.cpp) into a class that already exists in the Python
// tree -- pytcad.errors.DegenerateMeshError,
// pytcad.linsolve.LinearSolveError -- rather than into a new C++-minted
// one.  That is what lets an existing, unmodified
// `pytest.raises(DegenerateMeshError)` catch the accelerated path.
//
// Message text is part of the contract, not decoration:
// tests/test_m21_phase3.py uses match="degenerate" and
// match="non-manifold|shared by", so a kernel that raises must
// reproduce the Python f-string verbatim.
#pragma once

#include <stdexcept>
#include <string>

namespace tcad {

/// Base for every error the engine raises. Never thrown directly.
struct Error : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// A mesh violates a structural invariant (degenerate element, or a
/// non-manifold edge/face).  -> pytcad.errors.DegenerateMeshError
struct DegenerateMesh : Error {
    using Error::Error;
};

/// Singular matrix, non-finite input, or iterative non-convergence in a
/// linear solve.  -> pytcad.linsolve.LinearSolveError
struct LinearSolveFailure : Error {
    using Error::Error;
};

/// A nonlinear (Newton) solve did not converge.  Carries diagnostics so
/// a caller can LOG what happened without ever being handed the bad
/// iterate -- a failed solve must never return half-state.
struct ConvergenceFailure : Error {
    ConvergenceFailure(const std::string& what, int iterations, double residual)
        : Error(what), iterations(iterations), residual(residual) {}
    int iterations;
    double residual;
};

/// Caller passed something structurally impossible (bad shape, negative
/// count).  -> ValueError
struct InvalidArgument : Error {
    using Error::Error;
};

/// A connectivity array names a node that does not exist.  -> IndexError
///
/// The reference path gets this for free: numpy fancy-indexing an
/// out-of-range element raises IndexError.  A C++ kernel that merely
/// dereferenced it would read out of bounds instead, so every kernel
/// taking connectivity validates the index range ONCE up front (a
/// single O(n) pass, not a check per access) and raises this.  The
/// CLASS matches the reference; the message deliberately does not try
/// to reproduce numpy's wording.
struct IndexOutOfRange : Error {
    using Error::Error;
};

}  // namespace tcad
