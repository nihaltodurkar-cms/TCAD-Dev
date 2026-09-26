// Backend round-trip benchmark (NATIVE-DESKTOP-PLAN.md 15.15, S4e):
//
//   tcad_desktop --bench-backend <result.npz> [--repeats N]
//
// Measures, through the real BackendClient and service:
//   - cold start: process start + imports + handshake + the first ping;
//   - per map kind (recombination R: one field; bands: four), per call:
//       end-to-end latency (call -> reply),
//       the service's own load / compute / write times,
//       the C++ read-back (NpzFile::open + ResultModel::from_npz + every
//       field decoded);
//   - transport = service write + C++ read: the section 15.3 gate
//     (<= 150 ms for a one-field map of a 1M-node result).
#pragma once

#include <nlohmann/json.hpp>

#include <QString>

namespace tcad::desktop {

struct BackendBenchOptions {
    QString result_path;
    int repeats = 5;
    bool warm = false;  // system.warmup before the first map call (decision 4)
};

nlohmann::ordered_json run_backend_benchmark(const BackendBenchOptions& options);

}  // namespace tcad::desktop
