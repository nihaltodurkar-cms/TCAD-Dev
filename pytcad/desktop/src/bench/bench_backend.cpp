#include "bench_backend.hpp"

#include "backend/backend_client.hpp"
#include "data/npz.hpp"
#include "data/result_model.hpp"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFile>

#include <algorithm>
#include <stdexcept>
#include <vector>

namespace tcad::desktop {
namespace {

nlohmann::ordered_json stats(std::vector<double> ms) {
    std::sort(ms.begin(), ms.end());
    auto pct = [&](double p) {
        if (ms.empty()) return 0.0;
        const auto i = static_cast<std::size_t>(p * static_cast<double>(ms.size() - 1) + 0.5);
        return ms[std::min(i, ms.size() - 1)];
    };
    return {{"n", ms.size()}, {"p50_ms", pct(0.5)}, {"p95_ms", pct(0.95)}, {"max_ms", ms.empty() ? 0.0 : ms.back()}};
}

BackendReply* await(BackendReply* r, int ms) {
    QElapsedTimer t;
    t.start();
    while (!r->isFinished() && t.elapsed() < ms) QCoreApplication::processEvents(QEventLoop::AllEvents, 5);
    if (!r->isFinished()) throw std::runtime_error("backend call did not finish: " + r->method().toStdString());
    if (!r->ok()) throw std::runtime_error(r->method().toStdString() + ": " + r->errorMessage().toStdString());
    return r;
}

}  // namespace

nlohmann::ordered_json run_backend_benchmark(const BackendBenchOptions& o) {
    nlohmann::ordered_json out;
    BackendClient client(resolveBackendConfig());
    QElapsedTimer t;
    t.start();
    await(client.call("system.ping"), 120000);
    out["cold_start_to_first_reply_ms"] = static_cast<double>(t.nsecsElapsed()) / 1e6;
    out["backend_python"] = client.backendPrefix().toStdString();
    // Section 6's "backend RPC round trip (small call) <= 5 ms" (S8i): 200
    // sequential pings, each timed from call() to its finished reply.
    {
        std::vector<double> rtt;
        for (int i = 0; i < 200; ++i) rtt.push_back(await(client.call("system.ping"), 10000)->elapsedMs());
        out["ping_round_trip"] = stats(rtt);
    }
    if (o.warm) {
        BackendReply* w = await(client.call("system.warmup"), 120000);
        out["warmup_call_ms"] = w->elapsedMs();
        out["warmup_import_ms"] = w->result()["import_ms"].get<double>();
    }

    const std::string source = o.result_path.toStdString();
    for (const char* method : {"analysis.recombination_map", "analysis.band_map"}) {
        std::vector<double> e2e, load, compute, write, read, transport;
        std::size_t fields = 0, bytes = 0;
        for (int i = 0; i < o.repeats; ++i) {
            BackendReply* r = await(client.call(method, {{"result", source}}, 300000), 300000);
            e2e.push_back(r->elapsedMs());
            if (i == 0 && !out.contains("first_map_call_ms")) out["first_map_call_ms"] = r->elapsedMs();
            const auto& tm = r->result()["timings"];
            load.push_back(tm["load_ms"].get<double>());
            compute.push_back(tm["compute_ms"].get<double>());
            write.push_back(tm["write_ms"].get<double>());
            const QString path = QString::fromStdString(r->result()["path"].get<std::string>());
            QElapsedTimer rt;
            rt.start();
            const NpzFile npz = NpzFile::open(path.toStdWString());
            const ResultModel m = ResultModel::from_npz(npz, path.toStdString());
            for (const auto& name : m.scalar_names()) bytes += m.scalar(name).values.size() * sizeof(double);
            read.push_back(static_cast<double>(rt.nsecsElapsed()) / 1e6);
            transport.push_back(write.back() + read.back());
            fields = m.scalar_names().size();
            QFile::remove(path);
        }
        out[method] = {{"fields", fields},
                       {"field_mb", static_cast<double>(bytes) / static_cast<double>(o.repeats) / 1e6},
                       {"end_to_end", stats(e2e)},
                       {"service_load", stats(load)},
                       {"service_compute", stats(compute)},
                       {"service_write", stats(write)},
                       {"cpp_read", stats(read)},
                       {"transport_write_plus_read", stats(transport)}};
    }
    client.shutdown();
    return out;
}

}  // namespace tcad::desktop
