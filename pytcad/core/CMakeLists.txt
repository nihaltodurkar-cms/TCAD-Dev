# libtcad -- the C++ numerical engine behind pytcad.
#
# Two build modes, both required (see M31-CPP-ARCHITECTURE-PLAN.md P0):
#
#   (a) in-place dev build -- the default during migration.  Nothing is
#       installed; the extension is written straight into ../pytcad/ so
#       the repo's existing `sys.path.insert(...)` + `import pytcad`
#       convention finds `pytcad._core` with packaging uninvolved and
#       every existing test file works untouched:
#
#         cmake -S core -B build/dev -G Ninja \
#               -DCMAKE_BUILD_TYPE=RelWithDebInfo -DTCAD_INPLACE_OUTPUT=ON \
#               -DPython_EXECUTABLE="$(conda run -n TCAD which python)"
#         cmake --build build/dev
#
#       On Windows, where the Python env may have no compiler at all:
#       put the compiler in a SEPARATE conda env (e.g. `tcad-cpp`,
#       `conda create -n tcad-cpp -c conda-forge gxx cmake ninja
#       binutils`), never inside the Python env itself -- installing a
#       compiler directly into an env that already has PySide6/Qt has
#       silently broken it here once (a transitive dependency channel-
#       switch on `libhwloc`, see CLAUDE.md's "What is compiled so
#       far" section). Point CMAKE_CXX_COMPILER/CMAKE_AR/CMAKE_RANLIB
#       at that separate env's binaries, keep -DPython_EXECUTABLE
#       pointed at the Python env. This is why `_core` statically
#       links its MinGW runtime below -- the compiler env's DLLs must
#       not need to be on the Python env's PATH at import time.
#
#   (b) wheel / editable install -- driven by scikit-build-core from
#       ../pyproject.toml, which sets cmake.source-dir to this directory.
#
# The extension is ALWAYS optional: pytcad/_accel.py soft-imports it and
# falls back to the pure-Python reference path, so a checkout with no
# compiler still passes the full suite (gate G-F).
cmake_minimum_required(VERSION 3.26)
project(tcad LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

option(TCAD_INPLACE_OUTPUT "Write the extension into ../pytcad/ for in-place dev use" OFF)
option(TCAD_BUILD_TESTS    "Build the Catch2 C++ unit tests"                          OFF)

# PETSc (M31 P3b) is OPTIONAL, and AUTO is the honest default: found ->
# used, absent -> the extension still builds and pytcad falls back to the
# petsc4py backend, or to method="direct"/"gmres" if that is absent too.
# This is gate G-F applied one level down -- the existing `accelerated`
# CI job builds from a plain pip environment that has no PETSc at all and
# must stay green.  Set OFF to force the fallback even where PETSc
# exists (useful for reproducing that CI job locally); ON to fail the
# configure loudly if it cannot be found.
set(TCAD_WITH_PETSC "AUTO" CACHE STRING "Link the PETSc solver backend: AUTO, ON or OFF")
set_property(CACHE TCAD_WITH_PETSC PROPERTY STRINGS AUTO ON OFF)

find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module)

# nanobind ships its own CMake config; ask the interpreter where it is
# rather than vendoring a submodule (P0: minimize bootstrap surface).
execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_VARIABLE NB_CMAKE_DIR OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
list(APPEND CMAKE_PREFIX_PATH "${NB_CMAKE_DIR}")
find_package(nanobind CONFIG REQUIRED)

# OpenMP is OPTIONAL by design: absent (e.g. clang-cl), unrecognized
# `#pragma omp` is a silent no-op and the kernels stay serial -- which is
# also the DEFAULT thread count (see include/tcad/runtime/threads.hpp for
# why: bit-identity under np.array_equal goldens, and not fighting
# workbench/batch.py's per-worker OPENBLAS_NUM_THREADS=1 pin).
find_package(OpenMP COMPONENTS CXX)

# PETSc ships a pkg-config file and nothing else machine-readable, so
# that is what we ask.  Deliberately NOT a find_package with a bundled
# FindPETSc.cmake: PETSc's own build writes lib/pkgconfig/petsc.pc with
# the exact include/link line for THAT installation (which BLAS, which
# MPI, 32- or 64-bit indices), and second-guessing it is how mismatched
# PETSc builds get linked together.
if(NOT TCAD_WITH_PETSC STREQUAL "OFF")
  find_package(PkgConfig QUIET)
  if(PkgConfig_FOUND)
    pkg_check_modules(PETSC IMPORTED_TARGET petsc)
  endif()
  if(NOT PETSC_FOUND AND TCAD_WITH_PETSC STREQUAL "ON")
    message(FATAL_ERROR
      "TCAD_WITH_PETSC=ON but pkg-config could not find petsc. Install it "
      "(conda-forge: `conda install -c conda-forge petsc`) and point "
      "PKG_CONFIG_PATH at <prefix>/lib/pkgconfig, or set "
      "TCAD_WITH_PETSC=OFF to build the petsc4py-only fallback.")
  endif()
endif()

add_library(tcad_core OBJECT
  src/runtime/threads.cpp
  src/mesh/stencil.cpp
  src/solver/petsc_ksp.cpp
  src/process/indicators.cpp
  src/process/diffuse.cpp
  src/nonlocal/paths.cpp
  src/thermal/grid.cpp
  src/dg/grid.cpp
  src/unstructured3d/kernels.cpp
)
target_include_directories(tcad_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
# M34-S4 / M43 / M42-S3: the path tracer, thermal-grid, and
# density-gradient Lambda-row assemblies are all gated bit-for-bit
# against a pure-Python oracle, so no multiply-add may be fused in any
# of them -- stated explicitly rather than relied on as a default of
# the target architecture.
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  set_source_files_properties(src/nonlocal/paths.cpp src/thermal/grid.cpp
                              src/dg/grid.cpp src/unstructured3d/kernels.cpp
                              PROPERTIES
    COMPILE_OPTIONS "-ffp-contract=off")
endif()
if(OpenMP_CXX_FOUND)
  target_link_libraries(tcad_core PUBLIC OpenMP::OpenMP_CXX)
  target_compile_definitions(tcad_core PUBLIC TCAD_HAVE_OPENMP=1)
endif()
# petsc_ksp.cpp is in the build EITHER WAY -- with PETSc it is the real
# backend, without it it is a have_petsc()==false stub that throws a
# message naming both recovery routes.  One source list, no conditional
# compilation of whole files, so the no-PETSc configuration is exercised
# by the same code the PETSc one is.
if(PETSC_FOUND)
  target_link_libraries(tcad_core PUBLIC PkgConfig::PETSC)
  target_compile_definitions(tcad_core PUBLIC TCAD_HAVE_PETSC=1)
  message(STATUS "PETSc ${PETSC_VERSION} found -- compiled solver backend enabled")
else()
  message(STATUS "PETSc not found -- building without the compiled solver "
                 "backend (pytcad falls back to petsc4py)")
endif()

# ONE extension module, with the libs linked in as OBJECT targets --
# never several .so files: cross-.so C++ exception translation and
# duplicated static state are a known footgun, and no consumer wants a
# subset of the engine.
nanobind_add_module(_core STABLE_ABI NB_STATIC
  bindings/module.cpp
  bindings/mesh_bindings.cpp
  bindings/solver_bindings.cpp
  bindings/process_bindings.cpp
  bindings/nonlocal_bindings.cpp
  bindings/thermal_bindings.cpp
  bindings/dg_bindings.cpp
  bindings/unstructured3d_bindings.cpp
)
target_link_libraries(_core PRIVATE tcad_core)
# The compiler toolchain lives in a SEPARATE, dedicated conda env
# (never installed into the Python env itself -- that collided with
# PySide6's own dependencies once already, see M43-SELFHEATING-2D3D-
# PLAN.md's phase 3 section), so _core.pyd must not depend on that
# env's runtime DLLs (libstdc++-6.dll/libgcc_s_seh-1.dll/
# libwinpthread-1.dll/libgomp-1.dll) being present at import time.
# Static-link the MinGW runtime instead -- zero external DLL
# dependency beyond what Python/Windows already provide.
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU" AND MINGW)
  target_link_options(_core PRIVATE
    -static-libgcc -static-libstdc++
    -Wl,-Bstatic,--whole-archive -lwinpthread -lgomp -Wl,--no-whole-archive,-Bdynamic)
endif()

if(TCAD_INPLACE_OUTPUT)
  set_target_properties(_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../pytcad")
endif()

# scikit-build-core installs into the wheel's pytcad/ package dir.
install(TARGETS _core LIBRARY DESTINATION pytcad)

if(TCAD_BUILD_TESTS)
  # Catch2 unit tests land with the first kernels (P2). Until then the
  # option exists but has nothing to build -- fail loudly rather than
  # silently doing nothing, so a CI job that sets it notices.
  message(FATAL_ERROR "TCAD_BUILD_TESTS=ON but core/tests/ does not exist yet (added in M31 P2)")
endif()
