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

add_library(tcad_core OBJECT
  src/runtime/threads.cpp
  src/mesh/stencil.cpp
)
target_include_directories(tcad_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
if(OpenMP_CXX_FOUND)
  target_link_libraries(tcad_core PUBLIC OpenMP::OpenMP_CXX)
  target_compile_definitions(tcad_core PUBLIC TCAD_HAVE_OPENMP=1)
endif()

# ONE extension module, with the libs linked in as OBJECT targets --
# never several .so files: cross-.so C++ exception translation and
# duplicated static state are a known footgun, and no consumer wants a
# subset of the engine.
nanobind_add_module(_core STABLE_ABI NB_STATIC
  bindings/module.cpp
  bindings/mesh_bindings.cpp
)
target_link_libraries(_core PRIVATE tcad_core)

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
