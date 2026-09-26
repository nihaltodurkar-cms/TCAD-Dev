// A run's live state, folded from its PYTCAD_PROGRESS records
// (NATIVE-DESKTOP-PLAN.md section 4.3 grammar; P3-S5). Qt-free.
//
// The newton records become trace steps exactly as the stored convergence
// trace groups them -- one step per run of consecutive records with the
// same stage, each metric a channel in the order the record wrote it -- so
// convergenceModel() draws the live history the way the Convergence mode
// draws the finished result's (and, when no record was dropped, the same
// plot).
//
// A record that does not fit the grammar is counted in ignored() and
// changes nothing; a null number (non-finite in the run) is NaN.
#pragma once

#include "data/result_model.hpp"

#include <nlohmann/json.hpp>

#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace tcad::desktop {

class TelemetryModel {
public:
    struct SweepPoint {
        int index = 0, count = 0;            // index 0-based, as written (the trace's sweep:0, ...)
        std::string contact;                 // "" when relayed (MPI engine)
        double value = std::numeric_limits<double>::quiet_NaN();
    };
    struct TransientStep {
        double time = std::numeric_limits<double>::quiet_NaN();
        double dt = std::numeric_limits<double>::quiet_NaN();
        int iters = -1;                      // -1: not printed
    };
    struct Error {
        std::string error, message;
    };

    void reset() { *this = TelemetryModel(); }
    // Folds one record in; false (and ignored() + 1) when it does not fit.
    bool apply(const nlohmann::ordered_json& record);

    const std::string& stage() const { return stage_; }            // the last stage record's
    int stages() const { return stages_; }
    int newtonRecords() const { return newton_; }
    int lastIteration() const { return last_iter_; }               // -1 before any
    const std::string& lastNewtonStage() const { return last_newton_stage_; }
    const std::vector<TraceStep>& trace() const { return trace_; }
    const std::optional<SweepPoint>& sweep() const { return sweep_; }
    const std::optional<TransientStep>& transient() const { return transient_; }
    int transientSteps() const { return transient_steps_; }
    bool done() const { return done_; }
    int dropped() const { return dropped_; }                       // from the done record
    const std::optional<Error>& error() const { return error_; }
    double lastTime() const { return last_t_; }                    // the records' own clock [s]
    int ignored() const { return ignored_; }

private:
    std::string stage_;
    int stages_ = 0;
    int newton_ = 0;
    int last_iter_ = -1;
    std::string last_newton_stage_;
    std::vector<TraceStep> trace_;
    std::optional<SweepPoint> sweep_;
    std::optional<TransientStep> transient_;
    int transient_steps_ = 0;
    bool done_ = false;
    int dropped_ = 0;
    std::optional<Error> error_;
    double last_t_ = 0;
    int ignored_ = 0;
};

}  // namespace tcad::desktop
