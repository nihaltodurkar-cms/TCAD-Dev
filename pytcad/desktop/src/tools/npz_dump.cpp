// tcad_npz_dump: prints what the C++ reader sees in an .npz, as JSON,
// for the Python-side conformance gate (gui/tests/test_desktop_contracts.py).
//
//   tcad_npz_dump <file.npz>        -> {"ok": true, "arrays": [...], "result": {...}}
//                                      ("result": what ResultModel reports -- scalars,
//                                      vectors, terminals, region metadata, snapshots,
//                                      and "series": the sweep/transient/AC/trace blocks)
//   tcad_npz_dump --schema-versions -> [1, 2, 3]
//   tcad_npz_dump --open-only [--max-bytes N] <file.npz>
//                                   -> {"ok", "arrays", "array_bytes", "peak_mb_before",
//                                      "peak_mb_after"}: the reader's memory bound (15.23, S8a)
//
// Exit code 0 on success, 2 when the reader rejects the file (the JSON
// then carries {"ok": false, "error": "..."}).
#include "data/line_cut.hpp"
#include "data/npz.hpp"
#include "data/pyjson.hpp"
#include "data/result_model.hpp"

#include <QByteArray>
#include <QCryptographicHash>
#include <nlohmann/json.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <iterator>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#include <optional>
#include <typeinfo>
#include <string>
#include <utility>

using tcad::desktop::NpzError;
using tcad::desktop::NpzFile;
using tcad::desktop::ResultModel;
using Json = nlohmann::ordered_json;

namespace {

std::string sha256(const void* data, std::size_t n) {
    return QCryptographicHash::hash(
               QByteArrayView(static_cast<const char*>(data), static_cast<qsizetype>(n)),
               QCryptographicHash::Sha256)
        .toHex()
        .toStdString();
}

std::string f64_sha256(const std::vector<double>& v) { return sha256(v.data(), v.size() * sizeof(double)); }

// Exact JSON for a float list: finite values as numbers (printed
// round-trippably), non-finite ones as "nan" / "inf" / "-inf".
Json enc(const std::vector<double>& v) {
    Json out = Json::array();
    for (double x : v) {
        if (std::isfinite(x)) out.push_back(x);
        else out.push_back(std::isnan(x) ? "nan" : x > 0 ? "inf" : "-inf");
    }
    return out;
}

Json enc(const std::vector<tcad::desktop::Channel>& chans) {
    Json out = Json::array();
    for (const auto& ch : chans) out.push_back(Json::array({ch.name, enc(ch.values)}));
    return out;
}

// The curve blocks (P2-S1), each as the contract test builds it from the
// store, or "<block>_error" when its accessor fails (the store also fails
// only on access).
Json series_view(const ResultModel& m) {
    Json r = {{"sweep", nullptr}, {"transient", nullptr}, {"ac", nullptr}, {"trace", nullptr}};
    auto guarded = [&](const char* key, auto&& read) {
        try {
            read();
        } catch (const NpzError& e) {
            r[key] = nullptr;
            r[std::string(key) + "_error"] = e.what();
        }
    };
    if (m.has_sweep())
        guarded("sweep", [&] {
            const auto s = m.sweep();
            Json conv = Json::array();
            for (auto c : s.converged) conv.push_back(c != 0);
            r["sweep"] = {{"contact", s.contact}, {"quantity", s.quantity}, {"meta", s.meta}, {"unit", s.unit},
                          {"voltages", enc(s.voltages)}, {"converged", conv}, {"channels", enc(s.channels)}};
        });
    if (m.has_transient())
        guarded("transient", [&] {
            const auto t = m.transient();
            r["transient"] = {{"contact", t.contact}, {"meta", t.meta}, {"unit", t.unit},
                              {"times", enc(t.times)}, {"channels", enc(t.channels)}};
        });
    if (m.has_ac())
        guarded("ac", [&] {
            const auto a = m.ac();
            r["ac"] = {{"port", a.port}, {"freqs", enc(a.freqs)}, {"C", enc(a.C)}, {"G", enc(a.G)},
                       {"unit_c", a.unit_c}, {"unit_g", a.unit_g}};
        });
    guarded("trace", [&] {
        const auto steps = m.trace();
        if (!steps) return;
        Json list = Json::array();
        for (const auto& st : *steps)
            list.push_back({{"stage", st.stage}, {"iterations", enc(st.iterations)},
                            {"converged", st.converged}, {"metrics", enc(st.metrics)}});
        r["trace"] = list;
    });
    return r;
}

// What the model reports, in the shape the contract test builds from
// NpzResultStore. The lazily-read blocks (region metadata, snapshots)
// report "<key>_error" instead of failing the whole dump, because the
// store also opens such files and fails only on access.
Json result_view(const ResultModel& m) {
    Json r = {{"dimensionality", m.dimensionality()},
              {"schema", m.schema_version()},
              {"scalars", m.scalar_names()}};
    static const char* kAxis[3] = {"x", "y", "z"};
    Json vectors = Json::array();
    for (const auto& name : m.vector_names()) {
        const auto v = m.vector(name);
        Json comps = Json::object();
        for (std::size_t a = 0; a < v.components.size(); ++a) comps[kAxis[a]] = f64_sha256(v.components[a]);
        vectors.push_back({{"name", name}, {"unit", v.unit}, {"components", comps}});
    }
    r["vectors"] = vectors;
    Json terminals = Json::array();
    for (const auto& name : m.terminal_names()) {
        const auto t = m.terminal(name);
        terminals.push_back({{"name", t.name}, {"value", t.value}, {"unit", t.unit}});
    }
    r["terminals"] = terminals;
    const std::pair<const char*, std::optional<Json> (ResultModel::*)() const> metas[] = {
        {"region_materials", &ResultModel::region_materials},
        {"structure_regions", &ResultModel::structure_regions}};
    for (const auto& [key, getter] : metas) {
        try {
            const auto j = (m.*getter)();
            r[key] = j ? *j : Json(nullptr);
        } catch (const NpzError& e) {
            r[key] = nullptr;
            r[std::string(key) + "_error"] = e.what();
        }
    }
    // What the info panel shows (S3d).
    const auto record = m.record();
    r["info"] = {{"solved_bias", m.solved_bias()},
                 {"record", record ? *record : Json(nullptr)},
                 {"geometry_kind", m.geometry_kind()},
                 {"sweep_points", m.sweep_points()},
                 {"transient_points", m.transient_points()},
                 {"ac_points", m.ac_points()}};
    r["series"] = series_view(m);
    r["snapshots"] = nullptr;
    if (m.has_sweep_snapshots()) {
        try {
            const auto s = m.sweep_snapshots();
            Json fields = Json::object();
            for (const auto& name : s.field_names) {
                Json shas = Json::array();
                for (std::size_t i = 0; i < s.count(); ++i) shas.push_back(f64_sha256(m.snapshot_field(s, name, i)));
                fields[name] = shas;
            }
            r["snapshots"] = {{"voltages", s.voltages}, {"field_names", s.field_names},
                              {"shape", s.shape}, {"fields", fields}};
        } catch (const NpzError& e) {
            r["snapshots_error"] = e.what();
        }
    }
    return r;
}

}  // namespace

double peak_mb() {
    PROCESS_MEMORY_COUNTERS pmc{};
    pmc.cb = sizeof pmc;
    return GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof pmc) ? static_cast<double>(pmc.PeakWorkingSetSize) / 1048576.0
                                                                       : -1.0;
}

int main(int argc, char** argv) {
    if (argc >= 3 && std::string(argv[1]) == "--open-only") {
        std::uint64_t limit = NpzFile::default_limit();
        int file_arg = 2;
        if (argc == 5 && std::string(argv[2]) == "--max-bytes") {
            limit = std::strtoull(argv[3], nullptr, 10);
            file_arg = 4;
        }
        const double before = peak_mb();
        try {
            const NpzFile f = NpzFile::open(argv[file_arg], limit);
            std::cout << Json{{"ok", true}, {"arrays", f.names().size()}, {"array_bytes", f.array_bytes()},
                              {"peak_mb_before", before}, {"peak_mb_after", peak_mb()}}.dump(-1, ' ', false, Json::error_handler_t::replace)
                      << "\n";
            return 0;
        } catch (const NpzError& e) {
            std::cout << Json{{"ok", false}, {"error", e.what()}, {"peak_mb_before", before}, {"peak_mb_after", peak_mb()}}.dump(-1, ' ', false, Json::error_handler_t::replace)
                      << "\n";
            return 2;
        }
    }
    // --line-cut: the line-cut contract (P2-S4). stdin is one Python-JSON
    // object {"x", "y", "values" (C order (Ny, Nx)), "orientation",
    // "position"}; NaN tokens allowed. Prints {"coord", "values",
    // "actual", "index"} or {"error"}.
    if (argc == 2 && std::string(argv[1]) == "--line-cut") {
        std::string in((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
        Json out;
        try {
            const auto req = tcad::desktop::parse_python_json(in);
            const auto cut = tcad::desktop::line_cut(
                req.at("x").get<std::vector<double>>(), req.at("y").get<std::vector<double>>(),
                req.at("values").get<std::vector<double>>(),
                tcad::desktop::cut_orientation_from_string(req.at("orientation").get<std::string>()),
                req.at("position").get<double>());
            Json vals = Json::array();
            for (double v : cut.values) vals.push_back(std::isnan(v) ? Json("nan") : Json(v));
            out = {{"coord", cut.coord}, {"values", vals}, {"actual", cut.actual}, {"index", cut.index}};
        } catch (const std::exception& e) {
            out = {{"error", e.what()}};
        }
        std::cout << out.dump(-1, ' ', false, Json::error_handler_t::replace) << "\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--schema-versions") {
        Json v = Json::array();
        for (int s : ResultModel::kKnownSchemaVersions) v.push_back(s);
        std::cout << v.dump(-1, ' ', false, Json::error_handler_t::replace) << "\n";
        return 0;
    }
    if (argc != 2) {
        std::cerr << "usage: tcad_npz_dump <file.npz> | --schema-versions\n";
        return 1;
    }
    Json out;
    try {
        const NpzFile f = NpzFile::open(argv[1]);
        out["ok"] = true;
        Json arrays = Json::array();
        for (const auto& name : f.names()) {
            const auto& a = f.at(name);
            Json j;
            j["name"] = name;
            j["descr"] = a.descr;
            j["fortran_order"] = a.fortran_order;
            j["shape"] = a.shape;
            j["raw_sha256"] = sha256(a.data.data(), a.data.size());
            if (a.is_numeric()) {
                const auto v = a.to_doubles();
                j["c_order_f64_sha256"] = sha256(v.data(), v.size() * sizeof(double));
            } else {
                j["strings"] = a.to_strings();
            }
            arrays.push_back(j);
        }
        out["arrays"] = arrays;
        try {
            const ResultModel m = ResultModel::from_npz(f, argv[1]);
            out["result"] = result_view(m);
        } catch (const NpzError& e) {
            out["result_error"] = e.what();
        }
    } catch (const NpzError& e) {
        std::cout << Json{{"ok", false}, {"error", e.what()}}.dump(-1, ' ', false, Json::error_handler_t::replace) << "\n";
        return 2;
    } catch (const std::exception& e) {
        // Anything but a named NpzError is a reader defect: reported, with a
        // distinct exit code, so the fuzz gate (15.23, S8c) names it.
        std::cout << Json{{"ok", false}, {"uncaught", typeid(e).name()}, {"error", e.what()}}.dump(-1, ' ', false, Json::error_handler_t::replace) << "\n";
        return 4;
    }
    std::cout << out.dump(-1, ' ', false, Json::error_handler_t::replace) << "\n";
    return 0;
}
