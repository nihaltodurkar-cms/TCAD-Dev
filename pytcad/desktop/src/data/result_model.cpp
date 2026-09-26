#include "result_model.hpp"

#include "pyjson.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <functional>
#include <limits>
#include <numeric>
#include <optional>
#include <string_view>
#include <utility>

namespace tcad::desktop {
namespace {

using Json = nlohmann::ordered_json;

constexpr const char* kAxisNames[3] = {"x", "y", "z"};
constexpr std::string_view kGeomStructured = "structured_rectilinear";
constexpr std::string_view kGeomPointCloud = "point_cloud";
constexpr std::string_view kSnapshotPrefix = "sweep__snapshot__field__";

// The file under validation plus its label, so every failure reads
// "<label>: <message>" like the Python validator's "<path>: <message>".
struct Ctx {
    const NpzFile& f;
    const std::string& label;

    [[noreturn]] void fail(const std::string& msg) const { throw ResultSchemaError(label + ": " + msg); }
    void require(const std::string& key, const std::string& why) const {
        if (!f.contains(key)) fail("missing required key '" + key + "' (" + why + ")");
    }
    const NpyArray& numeric(const std::string& key) const {
        const NpyArray& a = f.at(key);
        if (!a.is_numeric()) fail("'" + key + "' must be numeric");
        return a;
    }
};

// Python reprs, so messages match solver_backend.py's f-strings.
std::string py_tuple(const std::vector<std::size_t>& s) {
    std::string o = "(";
    for (std::size_t i = 0; i < s.size(); ++i) o += (i ? ", " : "") + std::to_string(s[i]);
    return o + (s.size() == 1 ? ",)" : ")");
}

template <class T>
std::string py_int_list(const std::vector<T>& v) {
    std::string o = "[";
    for (std::size_t i = 0; i < v.size(); ++i) o += (i ? ", " : "") + std::to_string(v[i]);
    return o + "]";
}

std::string py_str_list(const std::vector<std::string>& v) {
    std::string o = "[";
    for (std::size_t i = 0; i < v.size(); ++i) o += (i ? ", '" : "'") + v[i] + "'";
    return o + "]";
}

// key[len(prefix):-len(suffix)], with Python's empty result when they overlap.
std::string middle(const std::string& key, std::size_t prefix, std::size_t suffix) {
    return key.size() >= prefix + suffix ? key.substr(prefix, key.size() - prefix - suffix) : std::string();
}

int as_int(const Ctx& c, const std::string& key) {
    if (!c.f.contains(key)) c.fail("missing required key '" + key + "'");
    const NpyArray& a = c.f.at(key);
    if (!a.is_numeric() || a.count() != 1) c.fail("'" + key + "' must be a scalar integer");
    const double v = a.scalar();
    if (v != std::floor(v)) c.fail("'" + key + "' must be a scalar integer");
    return static_cast<int>(v);
}

// json.loads(str(np.asarray(d[key]).reshape(()))) -- for a one-element
// string array. Anything else is refused as not JSON (Python refuses
// every such case too, with a JSON or type message).
Json parse_stamp(const Ctx& c, const std::string& key) {
    const NpyArray& a = c.f.at(key);
    if (a.kind != 'U' || a.count() != 1) c.fail(key + " is not valid JSON (not a single string)");
    try {
        return parse_python_json(a.string_scalar());
    } catch (const PyJsonError& e) {
        c.fail(key + " is not valid JSON (" + e.what() + ")");
    }
}

void check_block_meta(const Ctx& c, const std::string& key) {
    const Json j = parse_stamp(c, key);
    if (!j.is_object() || !j.contains("dimensionality") || !is_python_int(j["dimensionality"]))
        c.fail(key + " must be a JSON object with an integer 'dimensionality'");
}

std::vector<std::string> keys_with_prefix(const std::vector<std::string>& keys, std::string_view p) {
    std::vector<std::string> out;
    for (const auto& k : keys)
        if (k.starts_with(p)) out.push_back(k);
    return out;
}

// A sweep/transient style series block: every `required` key present,
// every <channel_prefix><name> series the shape of `axis_key`, and a
// JSON meta with an integer dimensionality. `check_axis` runs the
// block-specific test on the axis array first.
void check_series_block(const Ctx& c, const std::vector<std::string>& keys, const std::string& block,
                        const std::vector<std::string>& required, const std::string& axis_key,
                        const std::function<void(const NpyArray&)>& check_axis,
                        const std::string& meta_key) {
    for (const auto& r : required) c.require(r, "an incomplete " + block + " block is invalid");
    const NpyArray& axis = c.numeric(axis_key);
    check_axis(axis);
    const std::string prefix = block + "__current__";
    const auto channels = keys_with_prefix(keys, prefix);
    if (channels.empty()) c.fail(block + " block has no " + prefix + "<channel> series");
    for (const auto& ch : channels) {
        const NpyArray& v = c.numeric(ch);
        if (v.shape != axis.shape)
            c.fail(ch + " length " + std::to_string(v.count()) + " does not match " + axis_key + " length " +
                   std::to_string(axis.count()));
    }
    check_block_meta(c, meta_key);
}

// A list of numbers stored either numerically or as text -- the store's
// sweep__snapshot__voltages / mesh__shape parsing: numpy's str() of an
// array ("[0.  0.1]", no commas) is split on whitespace, anything else
// is JSON.
std::optional<std::vector<double>> number_list(const NpyArray& a) {
    if (a.is_numeric()) return a.to_doubles();
    if (a.kind != 'U' || a.count() != 1) return std::nullopt;
    const std::string s = a.string_scalar();
    std::vector<double> out;
    if (s.starts_with("[") && s.find(',') == std::string::npos) {
        const std::size_t b = s.find_first_not_of("[]");
        const std::size_t e = s.find_last_not_of("[]");
        const std::string inner = b == std::string::npos ? std::string() : s.substr(b, e - b + 1);
        std::size_t i = 0;
        while (i < inner.size()) {
            i = inner.find_first_not_of(" \t\n\r", i);
            if (i == std::string::npos) break;
            std::size_t j = inner.find_first_of(" \t\n\r", i);
            if (j == std::string::npos) j = inner.size();
            double v = 0.0;
            const auto r = std::from_chars(inner.data() + i, inner.data() + j, v);
            if (r.ec != std::errc() || r.ptr != inner.data() + j) return std::nullopt;
            out.push_back(v);
            i = j;
        }
        return out;
    }
    Json j;
    try {
        j = parse_python_json(s);
    } catch (const PyJsonError&) {
        return std::nullopt;
    }
    if (j.is_number()) return std::vector<double>{j.get<double>()};
    if (!j.is_array()) return std::nullopt;
    for (const auto& v : j) {
        if (!v.is_number()) return std::nullopt;
        out.push_back(v.get<double>());
    }
    return out;
}

// A name or unit stamp: one string element, str() of it in the store.
std::string text(const Ctx& c, const std::string& key) {
    const NpyArray& a = c.f.at(key);
    if (a.kind != 'U' || a.count() != 1) c.fail(key + " must be a string");
    return a.string_scalar();
}

// meta.get(field, fallback) for a string field of a block's JSON meta.
std::string meta_string(const Ctx& c, const Json& meta, const std::string& key, const char* field,
                        const std::string& fallback) {
    if (!meta.is_object() || !meta.contains(field)) return fallback;
    const Json& v = meta[field];
    if (!v.is_string()) c.fail(key + " '" + field + "' must be a string");
    return v.get<std::string>();
}

// Every <prefix><name> series, in archive order (the store's dict order).
std::vector<Channel> channels_with_prefix(const Ctx& c, const std::string& prefix) {
    std::vector<Channel> out;
    for (const auto& key : c.f.names())
        if (key.starts_with(prefix)) out.push_back({key.substr(prefix.size()), c.numeric(key).to_doubles()});
    return out;
}

// A JSON list of numbers; null reads as NaN when `null_is_gap`.
std::vector<double> json_numbers(const Ctx& c, const Json& v, const std::string& where, bool null_is_gap) {
    if (!v.is_array()) c.fail(where + " must be a JSON list");
    std::vector<double> out;
    out.reserve(v.size());
    for (const auto& x : v) {
        if (x.is_number()) out.push_back(x.get<double>());
        else if (null_is_gap && x.is_null()) out.push_back(std::numeric_limits<double>::quiet_NaN());
        else c.fail(where + " must hold only numbers" + (null_is_gap ? " or null" : ""));
    }
    return out;
}

// Python's bool() of a json.loads value.
bool py_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number_float()) return v.get<double>() != 0.0;  // NaN is truthy, as in Python
    if (v.is_number()) return v.get<long long>() != 0;
    if (v.is_string()) return !v.get_ref<const std::string&>().empty();
    return !v.empty();
}

}  // namespace

ResultModel ResultModel::from_npz(const NpzFile& npz, const std::string& label) {
    ResultModel m;
    m.npz_ = &npz;
    m.label_ = label;
    const Ctx c{npz, label};
    if (npz.names().empty()) c.fail("not an npz result archive");
    // Python walks sorted(files); UTF-8 byte order is code-point order.
    std::vector<std::string> keys = npz.names();
    std::sort(keys.begin(), keys.end());

    // -- schema stamp (optional => the current version, as in Python) ------
    if (npz.contains("result__schema")) {
        m.schema_ = as_int(c, "result__schema");
        if (std::find(kKnownSchemaVersions.begin(), kKnownSchemaVersions.end(), m.schema_) ==
            kKnownSchemaVersions.end())
            c.fail("result schema version " + std::to_string(m.schema_) + " unsupported (this build reads " +
                   py_int_list(std::vector<int>(kKnownSchemaVersions.begin(), kKnownSchemaVersions.end())) +
                   "); re-run the solver");
    } else {
        m.schema_ = kKnownSchemaVersions.back();
    }

    // -- dimensionality + axes ----------------------------------------------
    c.require("solved_bias", "always required");
    m.dim_ = as_int(c, "dimensionality");
    if (m.dim_ < 1 || m.dim_ > 3) c.fail("dimensionality must be 1, 2 or 3, got " + std::to_string(m.dim_));
    const auto dim = static_cast<std::size_t>(m.dim_);
    std::vector<std::size_t> axis_sizes;
    std::vector<std::string> axis_names;
    for (std::size_t a = 0; a < dim; ++a) {
        const std::string key = std::string("axis_") + kAxisNames[a];
        c.require(key, "a " + std::to_string(dim) + "D result needs it");
        const NpyArray& arr = npz.at(key);
        if (!arr.is_numeric() || arr.shape.size() != 1 || arr.count() == 0)
            c.fail("'" + key + "' must be a non-empty 1D array of node positions");
        m.axes_[a] = arr.to_doubles();
        axis_sizes.push_back(arr.count());
        axis_names.emplace_back(kAxisNames[a]);
    }
    const std::size_t n_nodes =
        std::accumulate(axis_sizes.begin(), axis_sizes.end(), std::size_t{1}, std::multiplies<>());
    if (n_nodes > kMaxNodes)  // the viewer's limit, not the grammar's (deliberately stricter)
        c.fail("the mesh has " + std::to_string(n_nodes) + " nodes; the viewer opens at most " +
               std::to_string(kMaxNodes));
    // Field arrays are (Nx) / (Ny,Nx) / (Nz,Ny,Nx): x fastest.
    const std::vector<std::size_t> field_shape(axis_sizes.rbegin(), axis_sizes.rend());

    // -- scalar fields need units and honest shapes -------------------------
    for (const auto& key : keys) {
        if (!key.starts_with("field__")) continue;
        const std::string name = key.substr(7);
        c.require("unit__" + name, "field__" + name + " has no declared unit");
        const NpyArray& arr = npz.at(key);
        if (arr.shape != field_shape)
            c.fail("field__" + name + " shape " + py_tuple(arr.shape) + " does not match the " +
                   std::to_string(dim) + "D mesh axes " + py_tuple(field_shape));
        if (!arr.is_numeric()) c.fail("field__" + name + " must be numeric");
        m.scalars_.push_back(name);
    }

    // -- vector fields: components per axis + shared unit --------------------
    std::vector<std::pair<std::string, std::vector<std::string>>> groups;  // first-seen order
    for (const auto& key : keys) {
        if (!key.starts_with("vector__")) continue;
        const std::string rest = key.substr(8);
        const std::size_t cut = rest.rfind("__");
        if (cut == std::string::npos) c.fail("malformed vector key '" + key + "'");
        const std::string name = rest.substr(0, cut), comp = rest.substr(cut + 2);
        auto it = std::find_if(groups.begin(), groups.end(), [&](const auto& g) { return g.first == name; });
        if (it == groups.end()) {
            groups.push_back({name, {}});
            it = std::prev(groups.end());
        }
        it->second.push_back(comp);
    }
    for (const auto& [name, comps] : groups) {
        c.require("unit__" + name, "vector__" + name + "__* has no unit");
        std::vector<std::string> sorted = comps;
        std::sort(sorted.begin(), sorted.end());
        if (sorted != axis_names)
            c.fail("vector__" + name + "__ components " + py_str_list(sorted) + " do not match the " +
                   std::to_string(dim) + "D axes " + py_str_list(axis_names));
        for (const auto& comp : comps) {
            const NpyArray& arr = npz.at("vector__" + name + "__" + comp);
            if (arr.shape != field_shape)
                c.fail("vector__" + name + "__" + comp + " shape " + py_tuple(arr.shape) +
                       " does not match the mesh axes");
            if (!arr.is_numeric()) c.fail("vector__" + name + "__" + comp + " must be numeric");
        }
        m.vectors_.push_back(name);
    }
    std::sort(m.vectors_.begin(), m.vectors_.end());

    // -- v2: geometry kind, mesh shape, flat node coordinates ---------------
    // Checked whenever ANY geometry key is present, as in Python.
    if (npz.contains("geom__kind")) {
        const NpyArray& a = npz.at("geom__kind");
        const std::string kind = (a.kind == 'U' && a.count() == 1) ? a.string_scalar() : "<non-string>";
        if (kind != kGeomStructured && kind != kGeomPointCloud)
            c.fail("unknown geom__kind '" + kind + "' (known: structured_rectilinear, point_cloud)");
        if (kind == kGeomPointCloud)
            c.fail("geom__kind 'point_cloud' is reserved by schema 2 but not readable by this build; "
                   "structured results only");
    }
    if (npz.contains("geom__kind") || npz.contains("mesh__shape") || npz.contains("nodes__count") ||
        npz.contains("nodes__coords")) {
        std::optional<long long> n_from_shape;
        if (npz.contains("mesh__shape")) {
            std::vector<long long> shape;
            for (double v : c.numeric("mesh__shape").to_doubles()) shape.push_back(static_cast<long long>(v));
            std::vector<long long> got = shape, want(axis_sizes.begin(), axis_sizes.end());
            std::sort(got.begin(), got.end());
            std::sort(want.begin(), want.end());
            if (got != want)
                c.fail("mesh__shape " + py_int_list(shape) + " does not match the axes " + py_int_list(axis_sizes));
            n_from_shape = std::accumulate(shape.begin(), shape.end(), 1LL, std::multiplies<>());
        }
        std::optional<long long> count = n_from_shape;
        if (npz.contains("nodes__count")) {
            const long long declared = as_int(c, "nodes__count");
            const long long expected = n_from_shape ? *n_from_shape : static_cast<long long>(n_nodes);
            if (declared != expected)
                c.fail("nodes__count " + std::to_string(declared) + " disagrees with the " + std::to_string(dim) +
                       "D mesh (" + std::to_string(expected) + " nodes)");
            count = declared;
        }
        if (npz.contains("nodes__coords")) {
            const NpyArray& coords = npz.at("nodes__coords");
            if (coords.shape.size() != 2 || coords.shape[1] != dim)
                c.fail("nodes__coords shape " + py_tuple(coords.shape) + " must be (N, " + std::to_string(dim) + ")");
            if (count && static_cast<long long>(coords.shape[0]) != *count)
                c.fail("nodes__coords has " + std::to_string(coords.shape[0]) + " rows but the mesh declares " +
                       std::to_string(*count) + " nodes");
        }
    }

    // -- v2: run record + convergence trace are parseable JSON --------------
    if (npz.contains("record__meta") && !parse_stamp(c, "record__meta").is_object())
        c.fail("record__meta must be a JSON object");
    if (npz.contains("converge__trace") && !parse_stamp(c, "converge__trace").is_array())
        c.fail("converge__trace must be a JSON list");

    // -- terminals come in value/unit pairs (both directions) ---------------
    for (const auto& key : keys) {
        if (!key.starts_with("terminal__")) continue;
        if (key.ends_with("__value")) {
            const std::string name = middle(key, 10, 7);
            c.require("terminal__" + name + "__unit", "terminal__" + name + "__value has no unit");
            m.terminals_.push_back(name);
        } else if (key.ends_with("__unit")) {
            const std::string name = middle(key, 10, 6);
            c.require("terminal__" + name + "__value", "orphan terminal__" + name + "__unit has no value");
        }
    }

    // -- sweep / transient / ac blocks: all-or-nothing ----------------------
    if (!keys_with_prefix(keys, "sweep__").empty()) {
        check_series_block(
            c, keys, "sweep", {"sweep__voltage", "sweep__converged", "unit__sweep_current", "sweep__meta"},
            "sweep__voltage",
            [&](const NpyArray& voltage) {
                const NpyArray& conv = npz.at("sweep__converged");
                if (conv.shape != voltage.shape || conv.shape.size() != 1)
                    c.fail("sweep__converged " + py_tuple(conv.shape) +
                           " must be a 1D bool array matching sweep__voltage " + py_tuple(voltage.shape));
            },
            "sweep__meta");
    }
    if (!keys_with_prefix(keys, "transient__").empty()) {
        check_series_block(
            c, keys, "transient", {"transient__times", "unit__transient_current", "transient__meta"},
            "transient__times",
            [&](const NpyArray& times) {
                if (times.shape.size() != 1 || times.count() == 0)
                    c.fail("transient__times must be a non-empty 1D array");
            },
            "transient__meta");
    }
    if (!keys_with_prefix(keys, "ac__").empty()) {
        for (const char* r : {"ac__freqs", "ac__C", "ac__G", "ac__port", "unit__ac_capacitance",
                              "unit__ac_conductance"})
            c.require(r, "an incomplete ac block is invalid");
        const NpyArray& freqs = c.numeric("ac__freqs");
        if (freqs.shape.size() != 1 || freqs.count() == 0) c.fail("ac__freqs must be a non-empty 1D array");
        for (const char* key : {"ac__C", "ac__G"}) {
            const NpyArray& v = c.numeric(key);
            if (v.shape != freqs.shape)
                c.fail(std::string(key) + " length " + std::to_string(v.count()) + " does not match ac__freqs length " +
                       std::to_string(freqs.count()));
        }
    }
    return m;
}

std::array<std::size_t, 3> ResultModel::node_counts() const {
    std::array<std::size_t, 3> n{1, 1, 1};
    for (int a = 0; a < dim_; ++a) n[static_cast<std::size_t>(a)] = axes_[static_cast<std::size_t>(a)].size();
    return n;
}

ScalarField ResultModel::scalar(const std::string& name) const {
    if (std::find(scalars_.begin(), scalars_.end(), name) == scalars_.end())
        throw ResultSchemaError(label_ + ": no scalar field '" + name + "'");
    ScalarField f;
    f.name = name;
    f.unit = npz_->at("unit__" + name).string_scalar();
    f.values = npz_->at("field__" + name).to_doubles();
    return f;
}

VectorField ResultModel::vector(const std::string& name) const {
    if (std::find(vectors_.begin(), vectors_.end(), name) == vectors_.end())
        throw ResultSchemaError(label_ + ": no vector field '" + name + "'");
    VectorField f;
    f.name = name;
    f.unit = npz_->at("unit__" + name).string_scalar();
    for (int a = 0; a < dim_; ++a) f.components.push_back(npz_->at("vector__" + name + "__" + kAxisNames[a]).to_doubles());
    return f;
}

Terminal ResultModel::terminal(const std::string& name) const {
    if (std::find(terminals_.begin(), terminals_.end(), name) == terminals_.end())
        throw ResultSchemaError(label_ + ": no terminal current '" + name + "'");
    const NpyArray& v = npz_->at("terminal__" + name + "__value");
    if (!v.is_numeric() || v.count() != 1)
        throw ResultSchemaError(label_ + ": terminal__" + name + "__value must be a numeric scalar");
    return Terminal{name, v.scalar(), npz_->at("terminal__" + name + "__unit").string_scalar()};
}

std::optional<nlohmann::ordered_json> ResultModel::json_meta(const std::string& key) const {
    if (!npz_->contains(key)) return std::nullopt;
    const Ctx c{*npz_, label_};
    return parse_stamp(c, key);
}

bool ResultModel::solved_bias() const {
    const NpyArray& a = npz_->at("solved_bias");  // required at open
    if (a.kind == 'U') return !a.string_scalar().empty();  // Python: a non-empty str is truthy
    return a.is_numeric() && a.count() == 1 && a.scalar() != 0.0;
}

std::optional<nlohmann::ordered_json> ResultModel::record() const { return json_meta("record__meta"); }

std::string ResultModel::geometry_kind() const {
    if (!npz_->contains("geom__kind")) return {};
    const NpyArray& a = npz_->at("geom__kind");
    return a.kind == 'U' && a.count() == 1 ? a.string_scalar() : std::string();
}

std::size_t ResultModel::sweep_points() const {
    return npz_->contains("sweep__voltage") ? npz_->at("sweep__voltage").count() : 0;
}

std::size_t ResultModel::transient_points() const {
    return npz_->contains("transient__times") ? npz_->at("transient__times").count() : 0;
}

std::size_t ResultModel::ac_points() const { return npz_->contains("ac__freqs") ? npz_->at("ac__freqs").count() : 0; }

std::optional<nlohmann::ordered_json> ResultModel::region_materials() const {
    return json_meta("region_materials__meta");
}

std::optional<nlohmann::ordered_json> ResultModel::structure_regions() const {
    return json_meta("structure_regions__meta");
}

bool ResultModel::has_sweep() const { return npz_->contains("sweep__voltage"); }
bool ResultModel::has_transient() const { return npz_->contains("transient__times"); }
bool ResultModel::has_ac() const { return npz_->contains("ac__freqs"); }

SweepSeries ResultModel::sweep() const {
    const Ctx c{*npz_, label_};
    if (!has_sweep()) c.fail("no sweep series in this result");
    SweepSeries s;
    s.meta = parse_stamp(c, "sweep__meta");
    s.contact = meta_string(c, s.meta, "sweep__meta", "contact", "");
    s.quantity = meta_string(c, s.meta, "sweep__meta", "quantity", "current");
    s.voltages = c.numeric("sweep__voltage").to_doubles();
    const NpyArray& conv = npz_->at("sweep__converged");
    if (!conv.is_numeric()) c.fail("sweep__converged must be numeric (bool or 0/1), not text");
    for (double v : conv.to_doubles()) s.converged.push_back(v != 0.0 ? 1 : 0);  // bool(NaN) is True
    s.channels = channels_with_prefix(c, "sweep__current__");
    // The store NaNs every unconverged point here, at the boundary.
    for (auto& ch : s.channels)
        for (std::size_t i = 0; i < ch.values.size() && i < s.converged.size(); ++i)
            if (!s.converged[i]) ch.values[i] = std::numeric_limits<double>::quiet_NaN();
    s.unit = text(c, "unit__sweep_current");
    return s;
}

TransientSeries ResultModel::transient() const {
    const Ctx c{*npz_, label_};
    if (!has_transient()) c.fail("no transient series in this result");
    TransientSeries t;
    t.meta = parse_stamp(c, "transient__meta");
    t.contact = meta_string(c, t.meta, "transient__meta", "contact", "");
    t.times = c.numeric("transient__times").to_doubles();
    t.channels = channels_with_prefix(c, "transient__current__");
    t.unit = text(c, "unit__transient_current");
    return t;
}

AcSeries ResultModel::ac() const {
    const Ctx c{*npz_, label_};
    if (!has_ac()) c.fail("no AC sweep in this result");
    AcSeries a;
    a.port = text(c, "ac__port");
    a.freqs = c.numeric("ac__freqs").to_doubles();
    a.C = c.numeric("ac__C").to_doubles();
    a.G = c.numeric("ac__G").to_doubles();
    a.unit_c = text(c, "unit__ac_capacitance");
    a.unit_g = text(c, "unit__ac_conductance");
    return a;
}

std::optional<std::vector<TraceStep>> ResultModel::trace() const {
    if (!npz_->contains("record__meta")) return std::nullopt;  // run_record() is None
    std::vector<TraceStep> out;
    if (!npz_->contains("converge__trace")) return out;
    const Ctx c{*npz_, label_};
    const Json raw = parse_stamp(c, "converge__trace");  // a list: checked at open
    for (std::size_t i = 0; i < raw.size(); ++i) {
        const Json& item = raw[i];
        const std::string where = "converge__trace[" + std::to_string(i) + "]";
        if (!item.is_object()) c.fail(where + " must be a JSON object");  // the store's d.get fails
        TraceStep st;
        st.stage = meta_string(c, item, where, "stage", "?");
        if (item.contains("iterations")) st.iterations = json_numbers(c, item["iterations"], where + " iterations", false);
        if (item.contains("metrics")) {
            const Json& m = item["metrics"];
            if (!m.is_object()) c.fail(where + " metrics must be a JSON object");
            for (auto it = m.begin(); it != m.end(); ++it)
                st.metrics.push_back({it.key(), json_numbers(c, it.value(), where + " metric '" + it.key() + "'", true)});
        }
        st.converged = item.contains("converged") ? py_truthy(item["converged"]) : true;
        out.push_back(std::move(st));
    }
    return out;
}

bool ResultModel::has_sweep_snapshots() const { return npz_->contains("sweep__snapshot__voltages"); }

SweepSnapshots ResultModel::sweep_snapshots() const {
    const Ctx c{*npz_, label_};
    if (!has_sweep_snapshots()) c.fail("no sweep snapshots in this result");
    SweepSnapshots s;
    auto voltages = number_list(npz_->at("sweep__snapshot__voltages"));
    if (!voltages) c.fail("sweep__snapshot__voltages is not a list of numbers");
    s.voltages = std::move(*voltages);

    if (!npz_->contains("mesh__shape")) c.fail("sweep snapshots need mesh__shape");
    const auto shape = number_list(npz_->at("mesh__shape"));
    if (!shape) c.fail("mesh__shape is not a list of integers");
    for (double v : *shape) {
        if (v < 0 || v != std::floor(v)) c.fail("mesh__shape is not a list of integers");
        s.shape.push_back(static_cast<std::size_t>(v));
    }
    const std::size_t expected =
        std::accumulate(s.shape.begin(), s.shape.end(), std::size_t{1}, std::multiplies<>());

    // The store: name = key[len(prefix):].rsplit("__", 1)[0], then every
    // key under "<prefix><name>__" is an index, read and reshaped.
    std::vector<std::string> keys = keys_with_prefix(npz_->names(), kSnapshotPrefix);
    for (const auto& key : keys) {
        const std::string rest = key.substr(kSnapshotPrefix.size());
        const std::size_t cut = rest.rfind("__");
        s.field_names.push_back(cut == std::string::npos ? rest : rest.substr(0, cut));
    }
    std::sort(s.field_names.begin(), s.field_names.end());
    s.field_names.erase(std::unique(s.field_names.begin(), s.field_names.end()), s.field_names.end());
    if (s.field_names.empty()) c.fail("no field data for sweep snapshots");

    for (const auto& name : s.field_names) {
        const std::string under = std::string(kSnapshotPrefix) + name + "__";
        for (const auto& key : keys) {
            if (!key.starts_with(under)) continue;
            const std::string tail = key.substr(key.rfind("__") + 2);
            long long idx = 0;
            const auto r = std::from_chars(tail.data(), tail.data() + tail.size(), idx);
            if (r.ec != std::errc() || r.ptr != tail.data() + tail.size())
                c.fail("snapshot key '" + key + "' has no integer index");
            const std::string canonical = under + std::to_string(idx);
            if (!npz_->contains(canonical)) c.fail("missing snapshot array '" + canonical + "'");
            const NpyArray& arr = npz_->at(canonical);
            if (!arr.is_numeric()) c.fail("snapshot array '" + canonical + "' must be numeric");
            if (arr.count() != expected)
                c.fail("snapshot array '" + canonical + "' has " + std::to_string(arr.count()) +
                       " values, which cannot be reshaped to mesh__shape " + py_tuple(s.shape));
        }
    }
    return s;
}

std::vector<double> ResultModel::snapshot_field(const SweepSnapshots& s, const std::string& field,
                                                std::size_t index) const {
    if (std::find(s.field_names.begin(), s.field_names.end(), field) == s.field_names.end())
        throw ResultSchemaError(label_ + ": no snapshot for field '" + field + "'");
    if (index >= s.count())
        throw ResultSchemaError(label_ + ": snapshot index " + std::to_string(index) + " out of range [0, " +
                                std::to_string(s.count()) + ")");
    const std::string key = std::string(kSnapshotPrefix) + field + "__" + std::to_string(index);
    if (!npz_->contains(key)) throw ResultSchemaError(label_ + ": missing snapshot array '" + key + "'");
    return npz_->at(key).to_doubles();
}

}  // namespace tcad::desktop
