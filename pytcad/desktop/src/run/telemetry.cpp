#include "telemetry.hpp"

#include <algorithm>
#include <cmath>

namespace tcad::desktop {
namespace {

using Json = nlohmann::ordered_json;
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

// A number, or NaN for null (the channel's non-finite value); nullopt when
// the value is neither.
std::optional<double> number(const Json& v) {
    if (v.is_null()) return kNaN;
    if (v.is_number()) return v.get<double>();
    return std::nullopt;
}

std::optional<std::string> text(const Json& r, const char* key) {
    if (!r.contains(key) || !r[key].is_string()) return std::nullopt;
    return r[key].get<std::string>();
}

}  // namespace

bool TelemetryModel::apply(const Json& r) {
    const auto reject = [this] {
        ++ignored_;
        return false;
    };
    if (!r.is_object() || !r.contains("v") || r["v"] != 1) return reject();
    const auto event = text(r, "event");
    if (!event) return reject();
    if (r.contains("t") && r["t"].is_number()) last_t_ = r["t"].get<double>();

    if (*event == "stage") {
        const auto s = text(r, "stage");
        if (!s) return reject();
        stage_ = *s;
        ++stages_;
    } else if (*event == "sweep_point") {
        if (!r.contains("index") || !r["index"].is_number_integer() || !r.contains("count") ||
            !r["count"].is_number_integer())
            return reject();
        SweepPoint p;
        p.index = r["index"].get<int>();
        p.count = r["count"].get<int>();
        if (const auto c = text(r, "contact")) p.contact = *c;
        if (r.contains("value")) {
            const auto v = number(r["value"]);
            if (!v) return reject();
            p.value = *v;
        }
        sweep_ = p;
        stage_ = "sweep";
    } else if (*event == "newton") {
        const auto s = text(r, "stage");
        if (!s || !r.contains("iter") || !r["iter"].is_number_integer() || !r.contains("residual") ||
            !r["residual"].is_object())
            return reject();
        std::vector<std::pair<std::string, double>> metrics;
        for (auto it = r["residual"].begin(); it != r["residual"].end(); ++it) {
            const auto v = number(it.value());
            if (!v) return reject();
            metrics.emplace_back(it.key(), *v);
        }
        // A new trace step when the stage changes (as the stored trace groups).
        if (trace_.empty() || trace_.back().stage != *s) {
            TraceStep step;
            step.stage = *s;
            trace_.push_back(std::move(step));
        }
        TraceStep& step = trace_.back();
        const std::size_t row = step.iterations.size();  // values so far in this step
        step.iterations.push_back(r["iter"].get<double>());
        for (const auto& [name, value] : metrics) {
            auto ch = std::find_if(step.metrics.begin(), step.metrics.end(),
                                   [&](const Channel& c) { return c.name == name; });
            if (ch == step.metrics.end()) {
                step.metrics.push_back({name, std::vector<double>(row, kNaN)});  // absent before: gaps
                ch = step.metrics.end() - 1;
            }
            ch->values.push_back(value);
        }
        for (Channel& c : step.metrics)  // a metric this record lacks: a gap
            if (c.values.size() < row + 1) c.values.push_back(kNaN);
        ++newton_;
        last_iter_ = r["iter"].get<int>();
        last_newton_stage_ = *s;
    } else if (*event == "transient_step") {
        TransientStep t;
        for (const char* key : {"time", "dt"}) {
            if (!r.contains(key)) return reject();
            const auto v = number(r[key]);
            if (!v) return reject();
            (std::string(key) == "time" ? t.time : t.dt) = *v;
        }
        if (r.contains("iters") && r["iters"].is_number_integer()) t.iters = r["iters"].get<int>();
        transient_ = t;
        ++transient_steps_;
    } else if (*event == "done") {
        done_ = true;
        if (r.contains("dropped") && r["dropped"].is_number_integer()) dropped_ = r["dropped"].get<int>();
    } else if (*event == "error") {
        Error e;
        e.error = text(r, "error").value_or("");
        e.message = text(r, "message").value_or("");
        error_ = e;
    } else {
        return reject();  // an event this app does not know (a newer runner)
    }
    return true;
}

}  // namespace tcad::desktop
