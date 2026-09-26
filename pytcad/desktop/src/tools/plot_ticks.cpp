// tcad_plot_ticks: PlotView's axis maths (views/plot/axis_ticks.hpp) for
// the Python contract gate, gui/tests/test_desktop_plot_ticks.py.
//
//   tcad_plot_ticks < cases.json > results.json
//
// Input: a JSON list of cases, each one of
//   {"kind": "linear",    "vmin": a, "vmax": b, "n": nbins}
//       -> {"ticks": [...], "labels": [...], "offset": "..."}  (labels on view [a, b])
//   {"kind": "log",       "vmin": a, "vmax": b, "n": numticks}
//       -> {"major": [...], "major_labels": [...], "minor": [...], "minor_labels": [...]}
//          (labels as matplotlib's mathtext strings, "" when not labelled)
// Output: the list of results, in order.
#include "views/plot/axis_ticks.hpp"

#include <nlohmann/json.hpp>

#include <iostream>
#include <iterator>
#include <string>

using Json = nlohmann::json;
namespace plot = tcad::desktop::plot;

int main() {
    const std::string text((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
    Json cases;
    try {
        cases = Json::parse(text);
    } catch (const Json::exception& e) {
        std::cerr << "tcad_plot_ticks: bad JSON input: " << e.what() << "\n";
        return 1;
    }
    Json out = Json::array();
    for (const auto& c : cases) {
        const std::string kind = c.at("kind");
        const double a = c.at("vmin"), b = c.at("vmax");
        const int n = c.at("n");
        if (kind == "linear") {
            const auto ticks = plot::linear_ticks(a, b, n);
            const auto labels = plot::scalar_labels(ticks, a, b);
            out.push_back({{"ticks", ticks}, {"labels", labels.labels}, {"offset", labels.offset_text}});
        } else if (kind == "log") {
            const auto major = plot::log_major_ticks(a, b, n);
            const auto minor = plot::log_minor_ticks(a, b, n);
            Json ml = Json::array(), nl = Json::array();
            for (const auto& l : plot::log_labels(major, a, b)) ml.push_back(plot::mathtext(l));
            for (const auto& l : plot::log_labels(minor, a, b)) nl.push_back(plot::mathtext(l));
            out.push_back({{"major", major}, {"major_labels", ml}, {"minor", minor}, {"minor_labels", nl}});
        } else {
            std::cerr << "tcad_plot_ticks: unknown kind '" << kind << "'\n";
            return 1;
        }
    }
    std::cout << out.dump() << "\n";
    return 0;
}
