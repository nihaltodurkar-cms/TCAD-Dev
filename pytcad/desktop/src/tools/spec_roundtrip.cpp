// tcad_spec_roundtrip: load a DeviceSpec job JSON into the C++ document
// and save it back, for the round-trip contract gate
// (gui/tests/test_desktop_contracts.py): Python DeviceSpec -> C++ ->
// Python DeviceSpec must compare equal.
//
//   tcad_spec_roundtrip <in.json> <out.json>
//
// Also prints the typed accessors' view as JSON, so the gate checks
// them against Python too.
#include "document/device_spec_document.hpp"

#include <exception>
#include <iostream>

using tcad::desktop::DeviceSpecDocument;

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: tcad_spec_roundtrip <in.json> <out.json>\n";
        return 1;
    }
    try {
        const auto doc = DeviceSpecDocument::load(argv[1]);
        doc.save(argv[2]);
        nlohmann::ordered_json view;
        view["dimensionality"] = doc.dimensionality();
        view["axis_sizes"] = {doc.mesh_axis(0).size(), doc.mesh_axis(1).size(), doc.mesh_axis(2).size()};
        view["contacts"] = doc.contact_names();
        view["backend"] = doc.backend();
        std::cout << view.dump() << "\n";
    } catch (const std::exception& e) {
        std::cout << nlohmann::json{{"error", e.what()}}.dump() << "\n";
        return 2;
    }
    return 0;
}
