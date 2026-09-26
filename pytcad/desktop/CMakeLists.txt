# PyTCAD native desktop application (NATIVE-DESKTOP-PLAN.md).
#
# A SEPARATE CMake project from core/ on purpose: core/ builds the
# MinGW `_core` extension for the tcad-dev Python; this builds MSVC
# executables against Qt 6 + VTK from the separate `tcad-gui` conda env.
# The two never link each other -- the app talks to the solver through
# the job-file/.npz process boundary only (plan section 3).
#
# Build with desktop/build.ps1 (sets up MSVC, finds tcad-gui). By hand:
#   (in an MSVC x64 developer shell)
#   cmake -S desktop -B build/desktop -G Ninja -DCMAKE_BUILD_TYPE=Release
#         -DCMAKE_PREFIX_PATH=<tcad-gui>/Library
#   cmake --build build/desktop
cmake_minimum_required(VERSION 3.24)
project(tcad_desktop VERSION 0.1.0 LANGUAGES CXX)

if(NOT MSVC)
  message(FATAL_ERROR "tcad_desktop is built with MSVC: Qt and VTK from conda-forge are "
                      "MSVC-ABI (NATIVE-DESKTOP-PLAN.md section 7.1). Use desktop/build.ps1.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(/W4 /permissive- /utf-8 /EHsc)
add_compile_definitions(NOMINMAX UNICODE _UNICODE)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets OpenGLWidgets Test)
find_package(nlohmann_json 3 REQUIRED)
# Qt Advanced Docking System (LGPL-2.1, section 7.3): conda-forge
# qt6-advanced-docking-system 5.1.1, built against qt6-main 6.11 -- the
# two are pinned together in build.ps1 / README (section 15.9).
find_package(qtadvanceddocking-qt6 5.1 REQUIRED)
find_package(ZLIB)
find_package(VTK 9 REQUIRED COMPONENTS
  CommonCore CommonDataModel CommonColor
  FiltersCore FiltersGeometry
  FiltersExtraction FiltersFlowPaths FiltersModeling FiltersSources
  RenderingCore RenderingOpenGL2 RenderingAnnotation RenderingFreeType
  RenderingVolume RenderingVolumeOpenGL2
  InteractionStyle GUISupportQt)

# -- Qt-free data layer: .npz reader, result model, DeviceSpec document ----
add_library(tcad_desktop_data STATIC
  src/data/npz.cpp
  src/data/pyjson.cpp
  src/data/contour_levels.cpp
  src/data/result_model.cpp
  src/document/device_spec_document.cpp)
target_include_directories(tcad_desktop_data PUBLIC src)
target_link_libraries(tcad_desktop_data PUBLIC nlohmann_json::nlohmann_json)
if(ZLIB_FOUND)
  target_link_libraries(tcad_desktop_data PRIVATE ZLIB::ZLIB)
  target_compile_definitions(tcad_desktop_data PRIVATE TCAD_HAVE_ZLIB=1)
endif()

# -- contract tools driven by the Python suite (gui/tests/test_desktop_contracts.py)
add_executable(tcad_npz_dump src/tools/npz_dump.cpp)
target_link_libraries(tcad_npz_dump PRIVATE tcad_desktop_data Qt6::Core psapi)
add_executable(tcad_theme_dump src/tools/theme_dump.cpp)
target_include_directories(tcad_theme_dump PRIVATE src)
target_link_libraries(tcad_theme_dump PRIVATE tcad_desktop_data)
add_executable(tcad_spec_roundtrip src/tools/spec_roundtrip.cpp)
target_link_libraries(tcad_spec_roundtrip PRIVATE tcad_desktop_data)

# -- the application ----------------------------------------------------------
set(CMAKE_AUTOMOC ON)
# The client for the Python backend service (P1 S4): Qt Core only.
add_library(tcad_desktop_backend STATIC
  src/backend/backend_client.cpp src/backend/backend_client.hpp)
target_include_directories(tcad_desktop_backend PUBLIC src)
target_link_libraries(tcad_desktop_backend PUBLIC Qt6::Core nlohmann_json::nlohmann_json)

# The shell and views as a library (P1 S3): the app, and the shell e2e
# tests (tcad_desktop_shell_tests), link ONE copy of this code.
add_library(tcad_desktop_ui STATIC
  src/shell/main_window.cpp src/shell/main_window.hpp
  src/shell/app_settings.cpp src/shell/app_settings.hpp
  src/shell/info_panel.cpp src/shell/info_panel.hpp
  src/shell/display_panel.cpp src/shell/display_panel.hpp
  src/shell/view3d_panel.cpp src/shell/view3d_panel.hpp
  src/shell/playback_panel.cpp src/shell/playback_panel.hpp
  src/views/field/field_view.cpp src/views/field/field_view.hpp
  src/views/field/field_view_3d.cpp
  src/views/colormaps.cpp src/views/colormaps.hpp
  src/theme/theme.cpp src/theme/theme.hpp src/theme/tokens.hpp
  src/bench/bench.cpp
  src/bench/selftest.cpp
  src/bench/bench_backend.cpp)
target_include_directories(tcad_desktop_ui PUBLIC src)
target_link_libraries(tcad_desktop_ui PUBLIC
  tcad_desktop_data tcad_desktop_backend Qt6::Widgets Qt6::OpenGLWidgets ads::qtadvanceddocking-qt6
  ${VTK_LIBRARIES} psapi)
vtk_module_autoinit(TARGETS tcad_desktop_ui MODULES ${VTK_LIBRARIES})

add_executable(tcad_desktop src/app/main.cpp)
target_link_libraries(tcad_desktop PRIVATE tcad_desktop_ui)
vtk_module_autoinit(TARGETS tcad_desktop MODULES ${VTK_LIBRARIES})

# -- unit tests -----------------------------------------------------------------
enable_testing()
add_executable(tcad_desktop_unit_tests tests/test_data.cpp)
target_link_libraries(tcad_desktop_unit_tests PRIVATE tcad_desktop_data Qt6::Test)
add_test(NAME tcad_desktop_unit_tests COMMAND tcad_desktop_unit_tests)

# Shell end-to-end tests (section 15.13, S3b/S3f): the REAL MainWindow in
# a real window, driven with QTest. Needs a GL surface and test data, so
# it is run by gui/tests/test_desktop_shell.py, not by ctest.
# Backend client tests (section 15.15, S4): the real service plus fake
# ones; run by gui/tests/test_desktop_backend.py.
add_executable(tcad_desktop_backend_tests tests/test_backend.cpp)
target_link_libraries(tcad_desktop_backend_tests PRIVATE tcad_desktop_backend tcad_desktop_data Qt6::Test)

add_executable(tcad_desktop_shell_tests tests/test_shell.cpp)
target_link_libraries(tcad_desktop_shell_tests PRIVATE tcad_desktop_ui Qt6::Test)
vtk_module_autoinit(TARGETS tcad_desktop_shell_tests MODULES ${VTK_LIBRARIES})

# -- runtime manifest: where the Qt/VTK DLLs live, for the Python contract
#    tests and the dev launcher (no DLLs are copied in dev builds) ----------
# VTK's DLL directory: conda-forge puts every VTK DLL, and a copy of every
# Qt DLL, in <env>/Library/bin (Qt6::Core's own location, lib/qt6/bin,
# has no VTK).
get_target_property(_vtk_dll VTK::CommonCore IMPORTED_LOCATION_RELEASE)
if(NOT _vtk_dll)
  get_target_property(_vtk_dll VTK::CommonCore IMPORTED_LOCATION)
endif()
get_filename_component(TCAD_RUNTIME_BIN "${_vtk_dll}" DIRECTORY)
file(TO_NATIVE_PATH "${TCAD_RUNTIME_BIN}" TCAD_RUNTIME_BIN_NATIVE)
string(REPLACE "\\" "\\\\" TCAD_RUNTIME_BIN_JSON "${TCAD_RUNTIME_BIN_NATIVE}")
# The backend service's interpreter (the tcad-dev env; build.ps1 finds it)
# and its root (pytcad/, backend_service's parent) -- read by
# resolveBackendConfig() in dev builds (section 15.15).
set(TCAD_BACKEND_PYTHON "" CACHE FILEPATH "Python interpreter that runs backend_service")
file(TO_NATIVE_PATH "${TCAD_BACKEND_PYTHON}" _py_native)
string(REPLACE "\\" "\\\\" TCAD_BACKEND_PYTHON_JSON "${_py_native}")
get_filename_component(_backend_root "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
file(TO_NATIVE_PATH "${_backend_root}" _root_native)
string(REPLACE "\\" "\\\\" TCAD_BACKEND_ROOT_JSON "${_root_native}")
configure_file(desktop_runtime.json.in "${CMAKE_BINARY_DIR}/desktop_runtime.json" @ONLY)
configure_file(tcad_desktop.cmd.in "${CMAKE_BINARY_DIR}/tcad_desktop.cmd" @ONLY)
