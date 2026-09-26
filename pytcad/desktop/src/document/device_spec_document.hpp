// The job-input wire format (gui/services/device_spec.py's DeviceSpec,
// serialized by DeviceSpec.to_dict()/to_json()) as a C++ document.
//
// P0 contract (NATIVE-DESKTOP-PLAN.md section 4.1): the document is
// LOSSLESS -- every key, including ones this build has no typed
// accessor for, survives load -> save unchanged in value and order, so
// a C++-written job is exactly what Python would have written. Typed
// accessors cover only what the shell needs so far; editors add more
// in P4, each with its own round-trip test.
#pragma once

#include <nlohmann/json.hpp>

#include <filesystem>
#include <string>
#include <vector>

namespace tcad::desktop {

class DeviceSpecDocument {
public:
    using Json = nlohmann::ordered_json;

    static DeviceSpecDocument load(const std::filesystem::path& path);
    static DeviceSpecDocument parse(const std::string& text);
    void save(const std::filesystem::path& path) const;
    std::string dump(int indent = -1) const;

    const Json& json() const { return doc_; }

    int dimensionality() const;
    // Mesh axis node positions [cm]; axis 0/1/2 = x/y/z.
    std::vector<double> mesh_axis(int axis) const;
    std::vector<std::string> contact_names() const;
    std::string backend() const;  // "pytcad" when absent, as in from_dict()

private:
    Json doc_;
};

}  // namespace tcad::desktop
