// tcad_theme_dump: prints the native app's theme tokens (src/theme/
// tokens.hpp) as JSON, for the drift gate against gui/qml/Theme.qml
// (gui/tests/test_desktop_theme.py). Needs no window.
//
//   [{"name": ..., "hex": "#rrggbb", "qml": ..., "status": bool}, ...]
#include "data/contour_levels.hpp"
#include "data/grid_edges.hpp"
#include "theme/tokens.hpp"
#include "views/colormap_tables.hpp"

#include <nlohmann/json.hpp>

#include <cstdlib>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    // --edges <x0> <x1> ...: nearest-shading patch edges (S5c contract gate,
    // gui/tests/test_desktop_nearest_edges.py).
    if (argc >= 3 && std::string(argv[1]) == "--edges") {
        std::vector<double> x;
        for (int i = 2; i < argc; ++i) x.push_back(std::strtod(argv[i], nullptr));
        std::cout << nlohmann::json(tcad::desktop::nearest_edges(x)).dump() << "\n";
        return 0;
    }
    // --contour-levels <zmin> <zmax>: matplotlib's contour(levels=8) choice
    // (S5f contract gate, gui/tests/test_desktop_contour_levels.py).
    if (argc == 4 && std::string(argv[1]) == "--contour-levels") {
        const double zmin = std::strtod(argv[2], nullptr), zmax = std::strtod(argv[3], nullptr);
        std::cout << nlohmann::json(tcad::desktop::contour_levels(zmin, zmax)).dump() << "\n";
        return 0;
    }
    // --colormaps: the colour-map tables instead (S5b contract gate,
    // gui/tests/test_desktop_colormaps.py): {name: [[r, g, b] x 256]}.
    if (argc == 2 && std::string(argv[1]) == "--colormaps") {
        nlohmann::ordered_json maps = nlohmann::ordered_json::object();
        for (const auto& m : tcad::desktop::colormaps::kAll) maps[std::string(m.name)] = *m.table;
        std::cout << maps.dump() << "\n";
        return 0;
    }
    nlohmann::ordered_json out = nlohmann::ordered_json::array();
    for (const auto& e : tcad::desktop::theme::kTable)
        out.push_back({{"name", std::string(e.name)},
                       {"hex", std::string(e.hex)},
                       {"qml", std::string(e.qml)},
                       {"status", e.status}});
    std::cout << out.dump() << "\n";
    return 0;
}
