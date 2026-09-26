#include "pyjson.hpp"

namespace tcad::desktop {

std::string replace_nonfinite_tokens(std::string_view text) {
    static constexpr std::string_view kTokens[] = {"-Infinity", "Infinity", "NaN"};
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
        bool replaced = false;
        for (std::string_view tok : kTokens) {
            if (text.substr(i, tok.size()) == tok) {
                out += "null";
                i += tok.size();
                replaced = true;
                break;
            }
        }
        if (!replaced) {
            out += c;
            ++i;
        }
    }
    return out;
}

nlohmann::ordered_json parse_python_json(std::string_view text) {
    try {
        return nlohmann::ordered_json::parse(replace_nonfinite_tokens(text));
    } catch (const nlohmann::json::exception& e) {
        throw PyJsonError(e.what());
    }
}

}  // namespace tcad::desktop
