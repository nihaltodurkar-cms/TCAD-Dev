#include "device_spec_document.hpp"

#include <fstream>
#include <sstream>
#include <stdexcept>

namespace tcad::desktop {
namespace {

// UTF-8, never path.string(): that converts to the ANSI code page and
// throws for a character outside it (see NpzFile::open).
std::string utf8(const std::filesystem::path& p) {
    const std::u8string u8 = p.u8string();
    return std::string(reinterpret_cast<const char*>(u8.data()), u8.size());
}

}  // namespace

DeviceSpecDocument DeviceSpecDocument::parse(const std::string& text) {
    DeviceSpecDocument d;
    // allow_exceptions=true, ignore_comments=false: a malformed job is an
    // error, never a partially-read document.
    d.doc_ = Json::parse(text);
    if (!d.doc_.is_object() || !d.doc_.contains("mesh") || !d.doc_.contains("doping"))
        throw std::runtime_error("not a DeviceSpec: needs top-level 'mesh' and 'doping'");
    return d;
}

DeviceSpecDocument DeviceSpecDocument::load(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error(utf8(path) + ": cannot open");
    std::stringstream ss;
    ss << in.rdbuf();
    return parse(ss.str());
}

std::string DeviceSpecDocument::dump(int indent) const { return doc_.dump(indent); }

void DeviceSpecDocument::save(const std::filesystem::path& path) const {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error(utf8(path) + ": cannot write");
    out << doc_.dump();
}

int DeviceSpecDocument::dimensionality() const { return doc_.at("mesh").at("dimensionality").get<int>(); }

std::vector<double> DeviceSpecDocument::mesh_axis(int axis) const {
    static const char* kNames[3] = {"x", "y", "z"};
    if (axis < 0 || axis > 2) throw std::out_of_range("axis must be 0, 1 or 2");
    const auto& axes = doc_.at("mesh").at("axes");
    if (!axes.contains(kNames[axis])) return {};
    return axes.at(kNames[axis]).get<std::vector<double>>();
}

std::vector<std::string> DeviceSpecDocument::contact_names() const {
    std::vector<std::string> names;
    if (!doc_.contains("contacts")) return names;
    for (const auto& c : doc_.at("contacts")) names.push_back(c.at("name").get<std::string>());
    return names;
}

std::string DeviceSpecDocument::backend() const {
    if (!doc_.contains("backend") || doc_.at("backend").is_null()) return "pytcad";
    return doc_.at("backend").get<std::string>();
}

}  // namespace tcad::desktop
