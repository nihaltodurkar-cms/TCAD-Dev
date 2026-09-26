#include "colormaps.hpp"

#include "colormap_tables.hpp"

#include <vtkLookupTable.h>

namespace tcad::desktop {

// The enum indexes the generated table list: pin the order.
static_assert(colormaps::kAll.size() == 4);
static_assert(colormaps::kAll[static_cast<std::size_t>(ColorMap::Viridis)].name == "viridis");
static_assert(colormaps::kAll[static_cast<std::size_t>(ColorMap::Plasma)].name == "plasma");
static_assert(colormaps::kAll[static_cast<std::size_t>(ColorMap::Inferno)].name == "inferno");
static_assert(colormaps::kAll[static_cast<std::size_t>(ColorMap::RdBuR)].name == "RdBu_r");

namespace {

const colormaps::Named& entry(ColorMap m) { return colormaps::kAll[static_cast<std::size_t>(m)]; }

}  // namespace

std::string_view colorMapName(ColorMap m) { return entry(m).name; }

std::optional<ColorMap> colorMapFromName(std::string_view name) {
    for (std::size_t i = 0; i < colormaps::kAll.size(); ++i)
        if (colormaps::kAll[i].name == name) return static_cast<ColorMap>(i);
    return std::nullopt;
}

void fill_lut(vtkLookupTable* lut, ColorMap m) {
    const colormaps::Table& t = *entry(m).table;
    lut->SetNumberOfTableValues(static_cast<vtkIdType>(t.size()));
    for (std::size_t i = 0; i < t.size(); ++i)
        lut->SetTableValue(static_cast<vtkIdType>(i), t[i][0], t[i][1], t[i][2], 1.0);
    lut->SetTableRange(0.0, 1.0);  // views pass lut_input(): see the header
    lut->Build();
}

}  // namespace tcad::desktop
