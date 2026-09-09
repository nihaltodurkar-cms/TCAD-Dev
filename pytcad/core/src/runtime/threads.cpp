#include "tcad/runtime/threads.hpp"

#include <cstdlib>
#include <string>

namespace tcad::runtime {
namespace {

int parse_env(const char* name) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || *raw == '\0') return 0;
    try {
        const int v = std::stoi(std::string(raw));
        return v > 0 ? v : 0;
    } catch (...) {
        return 0;  // unparseable is treated as unset, never as an error
    }
}

int compute() {
    if (const int n = parse_env("PYTCAD_NUM_THREADS")) return n;
    if (const int n = parse_env("OMP_NUM_THREADS")) return n;
    return 1;  // the default, on purpose -- see the header
}

}  // namespace

int thread_count() {
    static const int n = compute();
    return n;
}

}  // namespace tcad::runtime
