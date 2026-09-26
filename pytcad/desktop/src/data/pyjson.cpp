#include "pyjson.hpp"

#include <limits>

namespace tcad::desktop {
namespace {

using Json = nlohmann::ordered_json;

constexpr std::string_view kTokens[] = {"-Infinity", "Infinity", "NaN"};

// How many times `marker` (decoded) occurs as a whole string value built
// from a token, and whether one is an object key.
struct MarkerCount {
    std::size_t values = 0;
    bool as_key = false;
};

bool is_marker(const std::string& s, const std::string& marker) {
    if (!s.starts_with(marker)) return false;
    const std::string_view rest = std::string_view(s).substr(marker.size());
    for (std::string_view tok : kTokens)
        if (rest == tok) return true;
    return false;
}

void count_markers(const Json& j, const std::string& marker, MarkerCount& n) {
    if (j.is_string()) {
        if (is_marker(j.get_ref<const std::string&>(), marker)) ++n.values;
    } else if (j.is_object()) {
        for (auto it = j.begin(); it != j.end(); ++it) {
            if (is_marker(it.key(), marker)) n.as_key = true;
            count_markers(it.value(), marker, n);
        }
    } else if (j.is_array()) {
        for (const auto& v : j) count_markers(v, marker, n);
    }
}

void restore_markers(Json& j, const std::string& marker) {
    if (j.is_string()) {
        const std::string& s = j.get_ref<const std::string&>();
        if (!is_marker(s, marker)) return;
        const std::string_view tok = std::string_view(s).substr(marker.size());
        const double inf = std::numeric_limits<double>::infinity();
        j = tok == "NaN" ? std::numeric_limits<double>::quiet_NaN() : tok == "Infinity" ? inf : -inf;
    } else if (j.is_structured()) {
        for (auto& v : j) restore_markers(v, marker);
    }
}

}  // namespace

std::string replace_nonfinite_tokens(std::string_view text, std::string_view marker, std::size_t* replaced) {
    if (replaced) *replaced = 0;
    std::string out;
    out.reserve(text.size());
    bool in_string = false;
    for (std::size_t i = 0; i < text.size();) {
        const char c = text[i];
        if (in_string) {
            out += c;
            if (c == '\\' && i + 1 < text.size()) {
                out += text[i + 1];  // an escaped char never ends the string
                i += 2;
                continue;
            }
            if (c == '"') in_string = false;
            ++i;
            continue;
        }
        if (c == '"') {
            in_string = true;
            out += c;
            ++i;
            continue;
        }
        bool matched = false;
        for (std::string_view tok : kTokens) {
            if (text.substr(i, tok.size()) == tok) {
                out += '"';
                out += marker;
                out += tok;
                out += '"';
                i += tok.size();
                matched = true;
                if (replaced) ++*replaced;
                break;
            }
        }
        if (!matched) {
            out += c;
            ++i;
        }
    }
    return out;
}

nlohmann::ordered_json parse_python_json(std::string_view text) {
    // The marker starts with a NUL, which JSON text can only carry escaped,
    // and json.dumps never escapes ASCII letters; a string that still spells
    // it (escaped on purpose) shows up as one marker too many, and the next
    // marker is tried.
    for (int k = 0; k < 64; ++k) {
        const std::string core = "pyjson" + std::to_string(k) + ":";
        const std::string escaped = "\\u0000" + core;
        const std::string decoded = std::string(1, '\0') + core;
        std::size_t made = 0;
        const std::string sub = replace_nonfinite_tokens(text, escaped, &made);
        Json j;
        try {
            j = Json::parse(sub);
        } catch (const nlohmann::json::exception& e) {
            throw PyJsonError(e.what());
        }
        if (made == 0) return j;
        MarkerCount n;
        count_markers(j, decoded, n);
        if (n.values > made) continue;  // a genuine string spells the marker
        if (n.as_key) throw PyJsonError("NaN/Infinity cannot be an object key");
        restore_markers(j, decoded);
        return j;
    }
    throw PyJsonError("cannot tell NaN/Infinity tokens from strings that spell the internal marker");
}

}  // namespace tcad::desktop
