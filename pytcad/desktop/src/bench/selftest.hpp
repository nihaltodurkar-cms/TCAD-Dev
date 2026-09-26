// Correctness self-test for FieldView's fast paths (NATIVE-DESKTOP-PLAN.md
// section 15.11, "Correctness gates"), run on the REAL window:
//
//   tcad_desktop --selftest <a.npz> [<b.npz> ...]
//
// Files are opened in order into ONE window, so a second file checks
// that nothing (geometry, node ids, pick locator) survives from the
// first. For each file:
//   1. every displayed point sits exactly on the grid node its carried
//      node index names;
//   2. for every field, linear and log, the displayed scalars are
//      bit-identical to an independent reference (a fresh decode,
//      gathered and transformed here), and the colour range equals
//      P0's method (vtkDataArray::GetRange over every node);
//   3. 3D only: over seeded hover pixels, the locator pick agrees with
//      an analytic ray-box oracle on hit/miss and readout. P0's
//      brute-force vtkCellPicker is compared too; it may differ only
//      where the oracle sides with the locator (its pick tolerance can
//      hit just outside the silhouette).
// Prints JSON; the exit code is 0 only when every check passed.
#pragma once

#include <nlohmann/json.hpp>

#include <QStringList>

namespace tcad::desktop {

class MainWindow;

struct SelftestOptions {
    QStringList result_paths;
    int hover_samples = 1000;
    int width = 1200;
    int height = 800;
};

// Returns {"ok": bool, "files": [...]}.
nlohmann::ordered_json run_selftest(MainWindow& window, const SelftestOptions& options);

// Soak (NATIVE-DESKTOP-PLAN.md 15.23, S8d): `cycles` times, open every
// file in turn into the one window, switch its fields, and exercise every
// layer it has (2D overlays; 3D crop, slices, isosurface, volume, glyphs,
// streamlines, exploded view, playback). Reports the process's private
// memory and working set after each cycle and the GL re-inits; "ok" is
// false only on a GL re-init (the memory bound is the caller's gate).
nlohmann::ordered_json run_soak(MainWindow& window, const QStringList& files, int cycles, int width, int height);

}  // namespace tcad::desktop
