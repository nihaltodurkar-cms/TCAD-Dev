// JSON text as Python's json.loads reads it.
//
// The result grammar's JSON stamps (record__meta, sweep__meta,
// region_materials__meta, ...) are written by Python's json.dumps, which
// emits the bare tokens NaN, Infinity and -Infinity for non-finite
// floats, and are validated by json.loads, which accepts them. nlohmann
// (strict RFC 8259) rejects them, so a file Python accepts would be
// refused here. parse_python_json turns those three tokens -- outside
// string literals only -- into marker strings, runs nlohmann's strict
// parse, and turns the markers back into the float values json.loads
// gives (NaN, +inf, -inf). The values are preserved since P2-S1: a
// convergence trace's residual can be Infinity, and the plot must show
// it, not a gap. A token used as an object key is refused, as in Python.
#pragma once

#include <nlohmann/json.hpp>

#include <stdexcept>
#include <string>
#include <string_view>

namespace tcad::desktop {

struct PyJsonError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Throws PyJsonError (with nlohmann's reason) on invalid JSON.
nlohmann::ordered_json parse_python_json(std::string_view text);

// The token replacement alone, exposed for the unit tests: each token
// becomes the JSON string "<marker><token>" (`marker` as JSON-escaped
// text); `replaced`, when given, receives how many tokens were replaced.
std::string replace_nonfinite_tokens(std::string_view text, std::string_view marker,
                                     std::size_t* replaced = nullptr);

// Python's isinstance(v, int) on a json.loads value: true for integers
// AND booleans (bool is an int subclass), false for floats.
inline bool is_python_int(const nlohmann::ordered_json& v) {
    return v.is_number_integer() || v.is_boolean();
}

}  // namespace tcad::desktop
