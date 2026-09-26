#include "curve_modes.hpp"

#include "data/result_model.hpp"
#include "theme/theme.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <exception>
#include <optional>
#include <set>
#include <utility>

namespace tcad::desktop::plot {
namespace {

QString q(const std::string& s) { return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size())); }

std::vector<double> to_um(const std::vector<double>& cm) {
    std::vector<double> um(cm.size());
    std::transform(cm.begin(), cm.end(), um.begin(), [](double v) { return v * 1e4; });
    return um;
}

bool has_scalar(const ResultModel& r, const char* name) {
    const auto& n = r.scalar_names();
    return std::find(n.begin(), n.end(), name) != n.end();
}

// QML's "(N point(s) did not converge)" title note.
QString unconverged_note(const SweepSeries& s) {
    const auto bad = std::count(s.converged.begin(), s.converged.end(), std::uint8_t{0});
    return bad ? QStringLiteral("  (%1 point(s) did not converge)").arg(bad) : QString();
}

PlotModel error_model(const QString& what, const std::exception& e) {
    return messageModel(QStringLiteral("Cannot read the %1:\n%2").arg(what, QString::fromUtf8(e.what())));
}

Series curve(QString label, std::vector<double> x, std::vector<double> y, QColor colour, QString unit,
             double width = 1.5) {
    Series s;
    s.label = std::move(label);
    s.x = std::move(x);
    s.y = std::move(y);
    s.colour = std::move(colour);
    s.unit = std::move(unit);
    s.line_width = width;
    return s;
}

}  // namespace

QString modeName(ViewMode m) {
    switch (m) {
        case ViewMode::FieldMap: return QStringLiteral("Field map");
        case ViewMode::Cut: return QStringLiteral("Line cut");
        case ViewMode::Field: return QStringLiteral("Field");
        case ViewMode::Curves: return QStringLiteral("Curves");
        case ViewMode::CV: return QStringLiteral("C-V");
        case ViewMode::Transient: return QStringLiteral("Transient");
        case ViewMode::AC: return QStringLiteral("AC");
        case ViewMode::Convergence: return QStringLiteral("Convergence");
        case ViewMode::Bands: return QStringLiteral("Bands");
        case ViewMode::Recombination: return QStringLiteral("Recombination");
    }
    return {};
}

QString modeKey(ViewMode m) {
    switch (m) {
        case ViewMode::FieldMap: return QStringLiteral("field_map");
        case ViewMode::Cut: return QStringLiteral("cut");
        case ViewMode::Field: return QStringLiteral("field");
        case ViewMode::Curves: return QStringLiteral("series");
        case ViewMode::CV: return QStringLiteral("cv");
        case ViewMode::Transient: return QStringLiteral("transient");
        case ViewMode::AC: return QStringLiteral("ac");
        case ViewMode::Convergence: return QStringLiteral("convergence");
        case ViewMode::Bands: return QStringLiteral("bands");
        case ViewMode::Recombination: return QStringLiteral("recombination");
    }
    return {};
}

bool isCurveMode(ViewMode m) { return m != ViewMode::FieldMap; }

bool showsMap(ViewMode m) { return m == ViewMode::FieldMap || m == ViewMode::Cut; }

bool hasLogToggle(ViewMode m) { return m == ViewMode::Field || m == ViewMode::Curves || m == ViewMode::Cut; }

QString derivedKind(ViewMode m) {
    if (m == ViewMode::Bands) return QStringLiteral("bands");
    if (m == ViewMode::Recombination) return QStringLiteral("recombination");
    return {};
}

std::vector<ViewMode> availableModes(const ResultModel& r) {
    std::vector<ViewMode> out;
    const bool one_d = r.dimensionality() == 1;
    out.push_back(one_d ? ViewMode::Field : ViewMode::FieldMap);
    // Line cuts are 2D only, as in QML (3D cuts are out of scope, 16.6).
    if (r.dimensionality() == 2 && !r.scalar_names().empty()) out.push_back(ViewMode::Cut);
    if (r.has_sweep()) {
        bool cv = false;
        try {
            cv = r.sweep().is_capacitance();
        } catch (const std::exception&) {
            // offered as Curves, which then names the error
        }
        out.push_back(cv ? ViewMode::CV : ViewMode::Curves);
    }
    if (r.has_transient()) out.push_back(ViewMode::Transient);
    if (r.has_ac()) out.push_back(ViewMode::AC);
    try {
        const auto t = r.trace();
        if (t && !t->empty()) out.push_back(ViewMode::Convergence);
    } catch (const std::exception&) {
        out.push_back(ViewMode::Convergence);  // it names the error
    }
    // Bands and R of a 2D/3D result are maps, in the Fields list (S5).
    if (one_d && has_scalar(r, "potential") && has_scalar(r, "electron_density") &&
        has_scalar(r, "hole_density")) {
        out.push_back(ViewMode::Bands);
        if (has_scalar(r, "doping")) out.push_back(ViewMode::Recombination);
    }
    return out;
}

ViewMode defaultMode(const ResultModel& r) {
    const auto modes = availableModes(r);
    if (std::find(modes.begin(), modes.end(), ViewMode::CV) != modes.end()) return ViewMode::CV;
    return modes.front();
}

std::vector<std::string> sweepChannels(const ResultModel& r) {
    std::vector<std::string> out;
    if (!r.has_sweep()) return out;
    try {
        for (const auto& c : r.sweep().channels) out.push_back(c.name);
    } catch (const std::exception&) {
    }
    return out;
}

PlotModel messageModel(const QString& text) {
    PlotModel m;
    m.empty_text = text;
    return m;
}

PlotModel nothingToPlot(PlotModel m) {
    if (m.series.empty()) return m;
    auto shown = [](double v, Scale s) { return std::isfinite(v) && (s == Scale::Linear || v != 0.0); };
    for (const Series& s : m.series) {
        const Scale ys = s.axis == YAxis::Right ? m.y2.scale : m.y.scale;
        for (std::size_t i = 0; i < std::min(s.x.size(), s.y.size()); ++i)
            if (shown(s.x[i], m.x.scale) && shown(s.y[i], ys)) return m;
    }
    const bool log = m.y.scale == Scale::Log || (m.has_y2 && m.y2.scale == Scale::Log);
    QString text = QStringLiteral("Nothing to plot: no finite value");
    if (log) text += QStringLiteral(" (a log axis cannot show zeros)");
    return messageModel(m.title.isEmpty() ? text : m.title.trimmed() + QStringLiteral("\n") + text);
}

// The 1D branch of _build_figure: ax.plot(x, field), no markers.
PlotModel fieldModel(const ResultModel& r, const std::string& field, bool log) {
    if (r.scalar_names().empty()) return messageModel(QStringLiteral("This result has no fields"));
    ScalarField f;
    try {
        f = r.scalar(field);
    } catch (const std::exception&) {
        return messageModel(QStringLiteral("'%1' is not available\nfor this view").arg(q(field)));
    }
    PlotModel m;
    const QString label = q(f.name), unit = q(f.unit);
    m.x = {QStringLiteral("x [um]"), Scale::Linear, {}};
    m.y = {log ? QStringLiteral("|%1| [%2]").arg(label, unit) : QStringLiteral("%1 [%2]").arg(label, unit),
           log ? Scale::Log : Scale::Linear, {}};
    m.x_unit = QStringLiteral("um");
    Series s = curve(label, to_um(r.axis(0)), std::move(f.values), theme::seriesColour(0), unit, 1.6);
    s.markers = Markers::Never;
    m.series.push_back(std::move(s));
    m.legend = false;
    return m;
}

// _draw_series, without the overlays (P2-S5).
QString overlayMismatch(const SweepSeries& primary, const SweepSeries& overlay, const std::string& channel) {
    if (overlay.contact != primary.contact)
        return QStringLiteral("its swept contact is '%1', the open result's is '%2'")
            .arg(q(overlay.contact), q(primary.contact));
    if (overlay.quantity != primary.quantity)
        return QStringLiteral("it is a %1 sweep, the open result is a %2 sweep")
            .arg(q(overlay.quantity), q(primary.quantity));
    if (overlay.unit != primary.unit)
        return QStringLiteral("its unit is '%1', the open result's is '%2'").arg(q(overlay.unit), q(primary.unit));
    const bool has = std::any_of(overlay.channels.begin(), overlay.channels.end(),
                                 [&](const Channel& c) { return c.name == channel; });
    if (!has) return QStringLiteral("it has no '%1' channel").arg(q(channel));
    return {};
}

namespace {

// QML's overlay styles (_draw_series): the family solid, lw 1.1, colours
// 1, 2, ...; the comparison dashed, lw 1.2, its purple. Markers at <= 40
// points, as the primary.
void add_overlays(PlotModel& m, const std::vector<OverlayCurve>& overlays, const std::string& channel,
                  const QString& unit) {
    auto values_of = [&](const OverlayCurve& o) -> const std::vector<double>* {
        for (const auto& c : o.sweep.channels)
            if (c.name == channel) return &c.values;
        return nullptr;
    };
    std::size_t k = 0;
    for (const auto& o : overlays) {
        if (o.kind != OverlayCurve::Kind::Family) continue;
        const std::size_t colour = 1 + k++;  // counted even when not drawn: colours stay put
        if (const auto* v = values_of(o))
            m.series.push_back(curve(o.label, o.sweep.voltages, *v, theme::seriesColour(colour), unit, 1.1));
    }
    for (const auto& o : overlays) {
        if (o.kind != OverlayCurve::Kind::Comparison) continue;
        if (const auto* v = values_of(o)) {
            Series s = curve(o.label, o.sweep.voltages, *v, theme::dataColour(theme::DataColour::Comparison), unit, 1.2);
            s.line = LineStyle::Dashed;
            m.series.push_back(std::move(s));
        }
    }
    m.legend = m.series.size() > 1;
}

}  // namespace

PlotModel seriesModel(const ResultModel& r, const std::string& channel, bool log,
                      const std::vector<OverlayCurve>& overlays) {
    SweepSeries sw;
    try {
        sw = r.sweep();
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("sweep"), e);
    }
    const auto it = std::find_if(sw.channels.begin(), sw.channels.end(),
                                 [&](const Channel& c) { return c.name == channel; });
    if (it == sw.channels.end())
        return messageModel(QStringLiteral("'%1' is not available\nfor this sweep").arg(q(channel)));
    PlotModel m;
    const QString ch = q(channel), unit = q(sw.unit), contact = q(sw.contact);
    m.title = QStringLiteral("%1 sweep%2").arg(contact, unconverged_note(sw));
    m.x = {QStringLiteral("%1 bias [V]").arg(contact), Scale::Linear, {}};
    m.y = {log ? QStringLiteral("|%1| [%2]").arg(ch, unit) : QStringLiteral("%1 [%2]").arg(ch, unit),
           log ? Scale::Log : Scale::Linear, {}};
    m.x_unit = QStringLiteral("V");
    m.series.push_back(curve(ch, sw.voltages, it->values, theme::seriesColour(0), unit));
    m.legend = false;
    add_overlays(m, overlays, channel, unit);  // P2-S5; the legend comes with them
    return m;
}

// _draw_cv: the first channel.
PlotModel cvModel(const ResultModel& r, bool log, const std::vector<OverlayCurve>& overlays) {
    SweepSeries sw;
    try {
        sw = r.sweep();
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("C-V sweep"), e);
    }
    if (sw.channels.empty())
        return messageModel(QStringLiteral("No C-V sweep yet\n(run one in the Voltage sweep panel's C-V section)"));
    PlotModel m;
    const QString unit = q(sw.unit);
    m.title = QStringLiteral("C-V sweep%1").arg(unconverged_note(sw));
    m.x = {QStringLiteral("Vg [V]"), Scale::Linear, {}};
    m.y = {QStringLiteral("C [%1]").arg(unit), log ? Scale::Log : Scale::Linear, {}};
    m.x_unit = QStringLiteral("V");
    m.series.push_back(curve(QStringLiteral("C"), sw.voltages, sw.channels.front().values, theme::seriesColour(0), unit));
    m.legend = false;
    add_overlays(m, overlays, sw.channels.front().name, unit);  // P2-S5: overlays are new in C-V
    return m;
}

// _draw_transient: every channel, sorted by name, one colour each.
PlotModel transientModel(const ResultModel& r, bool log) {
    TransientSeries tr;
    try {
        tr = r.transient();
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("transient"), e);
    }
    if (tr.channels.empty()) return messageModel(QStringLiteral("No transient run yet\n(arm and run one in the Transient panel)"));
    std::sort(tr.channels.begin(), tr.channels.end(), [](const Channel& a, const Channel& b) { return a.name < b.name; });
    PlotModel m;
    const QString unit = q(tr.unit);
    m.title = QStringLiteral("%1 transient").arg(q(tr.contact));
    m.x = {QStringLiteral("t [s]"), Scale::Linear, {}};
    m.y = {QStringLiteral("current [%1]").arg(unit), log ? Scale::Log : Scale::Linear, {}};
    m.x_unit = QStringLiteral("s");
    for (std::size_t k = 0; k < tr.channels.size(); ++k)
        m.series.push_back(curve(q(tr.channels[k].name), tr.times, tr.channels[k].values, theme::seriesColour(k), unit, 1.3));
    return m;
}

// _draw_ac: C on the left, G on a right axis, log frequency. Both hover
// (decision 5; QML hovered C only).
PlotModel acModel(const ResultModel& r) {
    AcSeries ac;
    try {
        ac = r.ac();
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("AC sweep"), e);
    }
    if (ac.freqs.empty()) return messageModel(QStringLiteral("No AC sweep yet\n(arm one in the AC panel and Run)"));
    PlotModel m;
    const QColor c_colour = theme::seriesColour(0), g_colour = theme::seriesColour(1);
    m.title = QStringLiteral("%1 AC sweep").arg(q(ac.port));
    m.x = {QStringLiteral("frequency [Hz]"), Scale::Log, {}};
    m.y = {QStringLiteral("C [%1]").arg(q(ac.unit_c)), Scale::Linear, c_colour};
    m.y2 = {QStringLiteral("G [%1]").arg(q(ac.unit_g)), Scale::Linear, g_colour};
    m.has_y2 = true;
    m.x_unit = QStringLiteral("Hz");
    m.series.push_back(curve(QStringLiteral("C"), ac.freqs, ac.C, c_colour, q(ac.unit_c)));
    Series g = curve(QStringLiteral("G"), ac.freqs, ac.G, g_colour, q(ac.unit_g));
    g.axis = YAxis::Right;
    m.series.push_back(std::move(g));
    m.legend = false;  // the axes carry the curves' colours, as in QML
    return m;
}

// _draw_convergence: per step and metric a '.'-marked line on a log axis,
// coloured by stage, styled by metric index, on a cumulative iteration
// axis; a red cross on the last value of a rejected step. Legend entries
// once per "stage:metric" (and "rejected"), as QML.
PlotModel convergenceModel(const ResultModel& r) {
    std::optional<std::vector<TraceStep>> trace;
    try {
        trace = r.trace();
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("convergence record"), e);
    }
    if (!trace || trace->empty())
        return messageModel(QStringLiteral("No convergence record\n(solve a device with schema-v2 results)"));
    return convergenceModel(*trace, QStringLiteral("No convergence record\n(its steps carry no metrics)"));
}

PlotModel convergenceModel(const std::vector<TraceStep>& trace_steps, const QString& empty_text) {
    const std::vector<TraceStep>* trace = &trace_steps;
    constexpr LineStyle kStyles[] = {LineStyle::Solid, LineStyle::Dashed, LineStyle::Dotted, LineStyle::DashDot};
    PlotModel m;
    m.x = {QStringLiteral("cumulative Newton iteration"), Scale::Linear, {}};
    m.y = {QStringLiteral("residual (all tracked metrics)"), Scale::Log, {}};
    m.x_unit = QStringLiteral("iteration");
    std::set<QString> seen;
    bool rejected_label = std::any_of(trace->begin(), trace->end(), [](const TraceStep& s) { return !s.converged; });
    double offset = 0;
    for (const TraceStep& step : *trace) {
        const QString stage = q(step.stage);
        const QString base = stage.section(':', 0, 0);
        const QColor colour = theme::dataColour(base == "equilibrium" ? theme::DataColour::StageEquilibrium
                                                : base == "bias"      ? theme::DataColour::StageBias
                                                                      : theme::DataColour::StageOther);
        const std::size_t n = step.metrics.empty() ? 0 : step.metrics.front().values.size();
        for (std::size_t i = 0; i < step.metrics.size(); ++i) {
            const Channel& metric = step.metrics[i];
            const QString key = metric.name.empty() ? base : base + ':' + q(metric.name);
            std::vector<double> xs(metric.values.size());
            for (std::size_t j = 0; j < xs.size(); ++j) xs[j] = offset + static_cast<double>(j);
            Series s = curve(key, std::move(xs), metric.values, colour, QString(), 1.0);
            s.line = kStyles[i % 4];
            s.markers = Markers::Always;
            s.shape = MarkerShape::Dot;
            s.in_legend = seen.insert(key).second;
            m.series.push_back(std::move(s));
        }
        if (!step.converged && !step.metrics.empty() && !step.metrics.front().values.empty()) {
            const auto& first = step.metrics.front().values;
            Series x = curve(QStringLiteral("rejected"), {offset + static_cast<double>(first.size() - 1)},
                             {first.back()}, theme::dataColour(theme::DataColour::Rejected), QString(), 2.0);
            x.line = LineStyle::None;
            x.markers = Markers::Always;
            x.shape = MarkerShape::Cross;
            x.in_legend = rejected_label;
            rejected_label = false;  // only labelled once
            m.series.push_back(std::move(x));
        }
        offset += static_cast<double>(n);
    }
    if (m.series.empty()) return messageModel(empty_text);
    return m;
}

PlotModel cutModel(const ResultModel& source, const std::string& field, CutOrientation orientation,
                   std::size_t index, bool log) {
    if (source.dimensionality() != 2)
        return messageModel(QStringLiteral("Cannot cut this field:\nline cuts need a 2D field"));
    ScalarField f;
    try {
        f = source.scalar(field);
    } catch (const std::exception& e) {
        return messageModel(QStringLiteral("Cannot cut this field:\n%1").arg(QString::fromUtf8(e.what())));
    }
    const bool horizontal = orientation == CutOrientation::Horizontal;
    const auto& cut_axis = source.axis(horizontal ? 1 : 0);
    if (cut_axis.empty()) return messageModel(QStringLiteral("Cannot cut this field:\nempty axis"));
    const double position = cut_axis[std::min(index, cut_axis.size() - 1)];
    LineCut c;
    try {
        c = line_cut(source.axis(0), source.axis(1), f.values, orientation, position);
    } catch (const std::exception& e) {
        return messageModel(QStringLiteral("Cannot cut this field:\n%1").arg(QString::fromUtf8(e.what())));
    }
    PlotModel m;
    const QString name = q(f.name), unit = q(f.unit);
    const QString along = horizontal ? QStringLiteral("x") : QStringLiteral("y");
    const QString at = horizontal ? QStringLiteral("y") : QStringLiteral("x");
    m.title = QStringLiteral("cut at %1=%2 um (nearest node)").arg(at, QString::number(c.actual * 1e4, 'g', 4));
    m.x = {QStringLiteral("%1 [um]").arg(along), Scale::Linear, {}};
    m.y = {log ? QStringLiteral("|%1| [%2]").arg(name, unit) : QStringLiteral("%1 [%2]").arg(name, unit),
           log ? Scale::Log : Scale::Linear, {}};
    m.x_unit = QStringLiteral("um");
    m.series.push_back(curve(name, to_um(c.coord), std::move(c.values), theme::seriesColour(0), unit));
    m.legend = false;
    return m;
}

// The 1D branch of _draw_bands.
PlotModel bandsModel(const ResultModel* derived) {
    if (!derived) return messageModel(QStringLiteral("Computing the bands with the backend..."));
    PlotModel m;
    m.x = {QStringLiteral("depth [um]"), Scale::Linear, {}};
    m.y = {QStringLiteral("energy [eV]"), Scale::Linear, {}};
    m.x_unit = QStringLiteral("um");
    const auto x = to_um(derived->axis(0));
    const char* names[] = {"Ec", "Ev", "EFn", "EFp"};
    try {
        for (std::size_t k = 0; k < 4; ++k) {
            Series s = curve(QString::fromLatin1(names[k]), x, derived->scalar(names[k]).values,
                             theme::seriesColour(k), QStringLiteral("eV"));
            s.line = k < 2 ? LineStyle::Solid : LineStyle::Dashed;
            s.markers = Markers::Never;  // ax.plot(x, arr, style): no markers
            s.line_width = 1.5;
            m.series.push_back(std::move(s));
        }
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("band map"), e);
    }
    return m;
}

// The 1D branch of _draw_recombination: log y. R is passed signed; the
// log axis shows |R| (decision 8) and the readout the signed value.
PlotModel recombinationModel(const ResultModel* derived) {
    if (!derived) return messageModel(QStringLiteral("Computing recombination with the backend..."));
    PlotModel m;
    m.x = {QStringLiteral("depth [um]"), Scale::Linear, {}};
    m.y = {QStringLiteral("|R| [cm^-3 s^-1]"), Scale::Log, {}};
    m.x_unit = QStringLiteral("um");
    try {
        ScalarField R = derived->scalar("R");
        Series s = curve(QStringLiteral("R"), to_um(derived->axis(0)), std::move(R.values), theme::seriesColour(3),
                         QStringLiteral("cm^-3 s^-1"), 1.6);
        s.markers = Markers::Never;
        m.series.push_back(std::move(s));
    } catch (const std::exception& e) {
        return error_model(QStringLiteral("recombination map"), e);
    }
    m.legend = false;
    return m;
}

}  // namespace tcad::desktop::plot
