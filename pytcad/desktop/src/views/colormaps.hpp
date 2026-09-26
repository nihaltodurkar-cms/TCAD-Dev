// Colour maps for field data (NATIVE-DESKTOP-PLAN.md 15.17, S5b). These
// colours encode VALUES, not UI state, so they live here rather than in
// src/theme/, and the no-hard-coded-colours gate exempts this module and
// its generated tables (colormap_tables.hpp) by name.
//
// The tables are matplotlib's own (entry i = cmap(i / 255)). The views do
// NOT hand VTK raw values with a table range [lo, hi]: VTK computes
// (v - lo) * (256 / (hi - lo)), matplotlib (v - lo) / (hi - lo) * 256, and
// at exact bin edges on extreme ranges the last bit differs, so the two
// picked adjacent entries (measured, S5b). Instead the views pass
// lut_input(v, lo, hi) -- matplotlib's Normalize, operation for
// operation -- to a table over [0, 1], where VTK's scale is exactly 256:
// the same entry as matplotlib everywhere, bin edges included. VTK's
// colours are 8-bit (vtkLookupTable stores bytes), equal to matplotlib's
// rounded to 8 bits -- test_desktop_colormaps.py.
#pragma once

#include <optional>
#include <string_view>

class vtkLookupTable;

namespace tcad::desktop {

enum class ColorMap { Viridis, Plasma, Inferno, RdBuR };

// matplotlib's name ("viridis", "plasma", "inferno", "RdBu_r").
std::string_view colorMapName(ColorMap m);
std::optional<ColorMap> colorMapFromName(std::string_view name);

// Fill `lut` with the 256-entry table of `m` (opaque), over [0, 1].
void fill_lut(vtkLookupTable* lut, ColorMap m);

// matplotlib's Normalize(lo, hi)(v): (v - lo) / (hi - lo), and 0 when the
// range is empty (hi <= lo: matplotlib's constant-field behaviour). Out-of-
// range results are clamped to the end colours by the table, as
// matplotlib's under/over colours default to the ends.
inline double lut_input(double v, double lo, double hi) { return hi > lo ? (v - lo) / (hi - lo) : 0.0; }

}  // namespace tcad::desktop
