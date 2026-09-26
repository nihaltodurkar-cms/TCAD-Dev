#include "telemetry_panel.hpp"

#include "views/plot/curve_modes.hpp"
#include "views/plot/plot_view.hpp"

#include <QLabel>
#include <QLocale>
#include <QVBoxLayout>

#include <cmath>

namespace tcad::desktop {
namespace {

QString sci(double v, int digits = 3) {
    return std::isfinite(v) ? QLocale::c().toString(v, 'e', digits) : QStringLiteral("n/a");
}

QString volts(double v) {
    // 6 significant digits: a ramp's float steps read 0.3 V, not 0.30000000000000004 V
    return std::isfinite(v) ? QLocale::c().toString(v, 'g', 6) + " V"
                            : QStringLiteral("n/a");
}

}  // namespace

TelemetryPanel::TelemetryPanel(QWidget* parent) : QWidget(parent) {
    setObjectName("TelemetryPanel");
    auto* col = new QVBoxLayout(this);
    col->setContentsMargins(4, 4, 4, 4);
    auto label = [this, col](const char* name) {
        auto* l = new QLabel(this);
        l->setObjectName(QString::fromLatin1(name));
        l->setWordWrap(true);
        l->setTextInteractionFlags(Qt::TextSelectableByMouse);
        col->addWidget(l);
        return l;
    };
    status_ = label("TelemetryStatus");
    elapsed_ = label("TelemetryElapsed");
    stage_ = label("TelemetryStage");
    iteration_ = label("TelemetryIteration");
    sweep_ = label("TelemetrySweep");
    transient_ = label("TelemetryTransient");
    note_ = label("TelemetryNote");
    plot_ = new plot::PlotView(this);
    plot_->setObjectName("TelemetryPlot");
    plot_->setMinimumHeight(160);
    col->addWidget(plot_, 1);
    plot_timer_.setSingleShot(true);
    plot_timer_.setInterval(kPlotMs);
    connect(&plot_timer_, &QTimer::timeout, this, &TelemetryPanel::refreshPlot);
    elapsed_timer_.setInterval(500);
    connect(&elapsed_timer_, &QTimer::timeout, this, &TelemetryPanel::updateElapsed);
    updateLabels();
    refreshPlot();
}

void TelemetryPanel::begin(const QString& what, const QString& stage_level_reason) {
    model_.reset();
    what_ = what;
    stage_level_reason_ = stage_level_reason;
    running_ = true;
    ever_ran_ = true;
    clock_.start();
    elapsed_timer_.start();
    updateLabels();
    refreshPlot();
}

void TelemetryPanel::apply(const nlohmann::ordered_json& record) {
    // No "after the run ended" guard: a canceled run's output is dropped by
    // the JobRunner, and a finished or failed run's records all arrive before
    // its end (a mutation removing such a guard changed nothing, P3-S5).
    model_.apply(record);
    updateLabels();
    if (!plot_timer_.isActive()) plot_timer_.start();
}

void TelemetryPanel::end(const QString& outcome) {
    if (!running_) return;
    running_ = false;
    elapsed_timer_.stop();
    status_->setText(tr("%1: %2").arg(outcome, what_));
    updateElapsed();
    updateLabels();
    refreshPlot();
}

QString TelemetryPanel::emptyText() const {
    if (!stage_level_reason_.isEmpty())
        return tr("Stage-level progress only:\n%1 reports no Newton iterations").arg(stage_level_reason_);
    if (!running_ && ever_ran_ && model_.stages() > 0)
        return tr("Stage-level progress only:\nthis run reported no Newton iterations");
    return running_ ? tr("Waiting for Newton iterations...") : tr("No run yet");
}

void TelemetryPanel::refreshPlot() {
    plot_timer_.stop();
    plot::PlotModel m = plot::convergenceModel(model_.trace(), emptyText());
    if (!m.series.empty()) m.title = tr("Newton residuals, live");
    plot_->setModel(std::move(m));
}

void TelemetryPanel::updateElapsed() {
    if (!ever_ran_) {
        elapsed_->clear();
        return;
    }
    elapsed_->setText(tr("Elapsed: %1 s").arg(QLocale::c().toString(clock_.elapsed() / 1000.0, 'f', 1)));
}

void TelemetryPanel::updateLabels() {
    if (running_) status_->setText(tr("Running: %1").arg(what_));
    else if (!ever_ran_) status_->setText(tr("No run yet: start one from the Run dock."));
    if (running_) updateElapsed();
    const TelemetryModel& m = model_;
    stage_->setText(m.stage().empty() ? QString() : tr("Stage: %1").arg(QString::fromStdString(m.stage())));
    stage_->setVisible(!m.stage().empty());
    iteration_->setText(m.lastIteration() < 0
                            ? QString()
                            : tr("Newton: iteration %1 of stage %2 (%3 in all)")
                                  .arg(m.lastIteration())
                                  .arg(QString::fromStdString(m.lastNewtonStage()))
                                  .arg(m.newtonRecords()));
    iteration_->setVisible(m.lastIteration() >= 0);
    if (const auto& s = m.sweep()) {
        // The record's index is 0-based (the trace's stage names, sweep:0, ...).
        QString t = tr("Sweep: point %1 of %2").arg(s->index + 1).arg(s->count);
        if (!s->contact.empty()) t += tr(", %1 = %2").arg(QString::fromStdString(s->contact), volts(s->value));
        sweep_->setText(t);
    }
    sweep_->setVisible(m.sweep().has_value());
    if (const auto& t = m.transient()) {
        QString text = tr("Transient: step %1, t = %2 s, dt = %3 s").arg(m.transientSteps()).arg(sci(t->time), sci(t->dt));
        if (t->iters >= 0) text += tr(", %1 iterations").arg(t->iters);
        transient_->setText(text);
    }
    transient_->setVisible(m.transient().has_value());
    QStringList notes;
    if (!stage_level_reason_.isEmpty())
        notes << tr("Stage-level progress only: %1 reports no Newton iterations.").arg(stage_level_reason_);
    else if (!running_ && ever_ran_ && m.stages() > 0 && m.newtonRecords() == 0)
        notes << tr("Stage-level progress only: this run reported no Newton iterations.");
    if (m.dropped() > 0)
        notes << tr("%1 progress records were dropped (at most 50 a second): the live plot misses them; "
                    "the result's Convergence mode has every iteration.")
                     .arg(m.dropped());
    if (const auto& e = m.error())
        notes << tr("Error: %1: %2").arg(QString::fromStdString(e->error), QString::fromStdString(e->message));
    note_->setText(notes.join('\n'));
    note_->setVisible(!notes.isEmpty());
}

QString TelemetryPanel::statusText() const { return status_->text(); }
QString TelemetryPanel::stageText() const { return stage_->text(); }
QString TelemetryPanel::iterationText() const { return iteration_->text(); }
QString TelemetryPanel::sweepText() const { return sweep_->text(); }
QString TelemetryPanel::transientText() const { return transient_->text(); }
QString TelemetryPanel::noteText() const { return note_->text(); }
QString TelemetryPanel::elapsedText() const { return elapsed_->text(); }

}  // namespace tcad::desktop
