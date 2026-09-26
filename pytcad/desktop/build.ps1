# One-command build of the native desktop app (NATIVE-DESKTOP-PLAN.md P0).
#
#   powershell -ExecutionPolicy Bypass -File desktop\build.ps1 [-Config Release] [-Test]
#
# Needs: Visual Studio with the C++ x64 tools (found via vswhere), and
# the separate `tcad-gui` conda env -- never tcad-dev:
#   conda create -n tcad-gui -c conda-forge --override-channels python=3.13
#         "qt6-main>=6.11,<6.12" "qt6-advanced-docking-system=5.1.1" vtk-base
#         vtk-io-ffmpeg cmake ninja nlohmann_json
# (Qt and ADS are pinned together: each conda-forge ADS build targets one
# Qt minor version -- NATIVE-DESKTOP-PLAN.md section 15.9.)
# (vtk-io-ffmpeg: conda-forge splits that module out of vtk-base, but
# vtk-base's CMake targets still reference its .lib.)
# Output: pytcad\build\desktop\.
param(
    [ValidateSet("Release", "RelWithDebInfo", "Debug")] [string] $Config = "Release",
    [switch] $Test
)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$build = Join-Path (Split-Path -Parent $src) "build\desktop"

# 1. MSVC developer environment (x64).
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found: install Visual Studio with the C++ workload" }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "No Visual Studio install with the MSVC x64 tools" }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
$env:PATH = (Split-Path -Parent $vswhere) + ";" + $env:PATH  # vcvars calls vswhere itself
foreach ($line in (cmd /c "`"$vcvars`" >nul && set")) {
    if ($line -match '^([^=]+)=(.*)$') {
        try { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") } catch { }
    }
}
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) { throw "vcvars64 did not put cl.exe on PATH" }

# 2. The tcad-gui env's Qt/VTK/CMake.
$gui = (conda env list --json | ConvertFrom-Json).envs |
    Where-Object { (Split-Path $_ -Leaf) -eq "tcad-gui" } | Select-Object -First 1
if (-not $gui) { throw "conda env 'tcad-gui' not found (NATIVE-DESKTOP-PLAN.md section 7.2)" }
$lib = Join-Path $gui "Library"
$cmake = Join-Path $lib "bin\cmake.exe"
$ninja = Join-Path $lib "bin\ninja.exe"

# 2b. The backend service's interpreter: the tcad-dev env (the solver's
#     own), recorded in desktop_runtime.json for dev builds (section 15.15).
$dev = (conda env list --json | ConvertFrom-Json).envs |
    Where-Object { (Split-Path $_ -Leaf) -eq "tcad-dev" } | Select-Object -First 1
$devpy = if ($dev) { Join-Path $dev "python.exe" } else { "" }
if (-not $devpy) { Write-Warning "conda env 'tcad-dev' not found: the backend needs TCAD_BACKEND_PYTHON" }

# 3. Configure + build.
& $cmake -S $src -B $build -G Ninja "-DCMAKE_BUILD_TYPE=$Config" "-DCMAKE_PREFIX_PATH=$lib" "-DCMAKE_MAKE_PROGRAM=$ninja" "-DTCAD_BACKEND_PYTHON=$devpy"
if ($LASTEXITCODE) { throw "CMake configure failed" }
& $cmake --build $build
if ($LASTEXITCODE) { throw "Build failed" }

# 4. Optional C++ unit tests (Qt DLLs from tcad-gui on PATH, as the launcher does).
if ($Test) {
    $env:PATH = (Join-Path $lib "bin") + ";" + $env:PATH
    & (Join-Path $lib "bin\ctest.exe") --test-dir $build --output-on-failure
    if ($LASTEXITCODE) { throw "C++ unit tests failed" }
}
Write-Host "Built into $build  (run: $build\tcad_desktop.cmd [result.npz])"
