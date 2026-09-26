#include "run_panel.hpp"

#include <QApplication>
#include <QComboBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>
#include <QPushButton>
#include <QStackedWidget>
#include <QStandardItemModel>
#include <QToolButton>
#include <QVBoxLayout>

#include <cmath>
#include <optional>

namespace tcad::desktop {
namespace {

// QML's defaults (SweepPanel.qml, TransientPanel.qml, ACPanel.qml).
struct FieldDef {
    const char* name;
    const char* label;
    const char* value;
    const char* tip;
};

constexpr FieldDef kSweep[] = {{"SweepStart", "Start [V]", "0.0", ""},
                               {"SweepStop", "Stop [V]", "1.0", ""},
                               {"SweepStep", "Step [V]", "0.1", ""}};
constexpr FieldDef kTransient[] = {{"TransientV0", "v0 [V]", "0.0", ""},
                                   {"TransientV1", "v1 [V]", "0.0", ""},
                                   {"TransientT0", "t0 [s]", "0.0", "step/ramp/pulse start time"},
                                   {"TransientT1", "t1 [s]", "0.0", "ramp end time, or pulse width"},
                                   {"TransientTEnd", "t_end [s]", "1e-9", ""},
                                   {"TransientDt0", "dt0 [s]", "1e-11", "first time step"}};
constexpr FieldDef kAc[] = {{"AcFStart", "f start [Hz]", "1.0", ""},
                            {"AcFStop", "f stop [Hz]", "1e9", ""},
                            {"AcPoints", "Points", "40", "log-spaced"}};
constexpr FieldDef kFamily[] = {{"FamilyStart", "Start [V]", "0.0", "the stepped contact's first value"},
                                {"FamilyStop", "Stop [V]", "0.2", ""},
                                {"FamilyStep", "Step [V]", "0.1", ""}};
constexpr FieldDef kCv[] = {{"CvNsub", "Nsub [cm^-3]", "-1e17", "Substrate doping, negative for p-type"},
                            {"CvTox", "tox [nm]", "5.0", ""},
                            {"CvVStart", "Vg start [V]", "-2.0", ""},
                            {"CvVStop", "Vg stop [V]", "2.0", ""},
                            {"CvVStep", "Vg step [V]", "0.05", ""}};

QLineEdit* addField(QFormLayout* form, const FieldDef& f, QWidget* parent) {
    auto* e = new QLineEdit(QString::fromLatin1(f.value), parent);
    e->setObjectName(QString::fromLatin1(f.name));
    if (*f.tip) e->setToolTip(QString::fromLatin1(f.tip));
    e->setAccessibleName(QString::fromLatin1(f.label));
    form->addRow(QString::fromLatin1(f.label), e);
    return e;
}

QComboBox* addCombo(QFormLayout* form, const char* name, const QString& label, QWidget* parent) {
    auto* c = new QComboBox(parent);
    c->setObjectName(QString::fromLatin1(name));
    c->setAccessibleName(label);
    form->addRow(label, c);
    return c;
}

}  // namespace

RunPanel::RunPanel(RunController* controller, QWidget* parent) : QWidget(parent), ctl_(controller) {
    setObjectName("RunPanel");
    auto* col = new QVBoxLayout(this);
    auto* top = new QFormLayout;
    source_ = new QComboBox(this);
    source_->setObjectName("RunSource");
    source_->addItem(tr("Example"), static_cast<int>(DeviceSource::Example));
    source_->addItem(tr("Device file"), static_cast<int>(DeviceSource::SpecFile));
    source_->addItem(tr("Project"), static_cast<int>(DeviceSource::Project));
    top->addRow(tr("Device"), source_);
    example_ = new QComboBox(this);
    example_->setObjectName("RunExample");
    example_->setAccessibleName(tr("Example"));
    top->addRow(tr("Example"), example_);
    auto* path_row = new QHBoxLayout;
    path_ = new QLineEdit(this);
    path_->setObjectName("RunPath");
    path_->setPlaceholderText(tr("a DeviceSpec .json or a project file"));
    browse_ = new QToolButton(this);
    browse_->setObjectName("RunBrowse");
    browse_->setText(tr("..."));
    path_row->addWidget(path_, 1);
    path_row->addWidget(browse_);
    top->addRow(tr("File"), path_row);
    device_ = new QLabel(tr("No device loaded"), this);
    device_->setObjectName("RunDevice");
    device_->setWordWrap(true);
    top->addRow(device_);
    kind_ = new QComboBox(this);
    kind_->setObjectName("RunKind");
    for (RunKind k : {RunKind::Equilibrium, RunKind::Bias, RunKind::Sweep, RunKind::Transient, RunKind::AC, RunKind::CV})
        kind_->addItem(runKindName(k), static_cast<int>(k));
    kind_->setCurrentIndex(1);  // Bias: what QML's Run does with nothing armed
    top->addRow(tr("Run"), kind_);
    col->addLayout(top);
    col->addWidget(buildForms());
    auto* opts = new QFormLayout;
    backend_ = new QComboBox(this);
    backend_->setObjectName("RunBackend");
    engine_ = new QComboBox(this);
    engine_->setObjectName("RunEngine");
    fillOptions(backend_, nlohmann::json::array({{{"id", "pytcad"}, {"label", "pytcad"}, {"enabled", true}, {"reason", ""}}}),
                "pytcad");
    fillOptions(engine_, nlohmann::json::array({{{"id", "auto"}, {"label", "Auto"}, {"enabled", true}, {"reason", ""}}}),
                "auto");
    opts->addRow(tr("Backend"), backend_);
    opts->addRow(tr("Engine"), engine_);
    col->addLayout(opts);
    auto* buttons = new QHBoxLayout;
    run_ = new QPushButton(tr("Run"), this);
    run_->setObjectName("RunButton");
    stop_ = new QPushButton(tr("Stop"), this);
    stop_->setObjectName("StopButton");
    stop_->setEnabled(false);
    buttons->addWidget(run_);
    buttons->addWidget(stop_);
    col->addLayout(buttons);
    col->addWidget(buildBatchGroup());
    col->addStretch(1);

    connect(source_, &QComboBox::activated, this, &RunPanel::onSourceChanged);
    connect(example_, &QComboBox::activated, this, [this] { loadExample(example_->currentText()); });
    connect(path_, &QLineEdit::returnPressed, this, [this] {
        loadFile(static_cast<DeviceSource>(source_->currentData().toInt()), path_->text().trimmed());
    });
    connect(browse_, &QToolButton::clicked, this, &RunPanel::browse);
    connect(kind_, &QComboBox::currentIndexChanged, this, &RunPanel::onKindChanged);
    connect(run_, &QPushButton::clicked, this, &RunPanel::requestRun);
    connect(stop_, &QPushButton::clicked, ctl_, &RunController::stop);
    connect(ctl_, &RunController::examplesListed, this, [this](const QStringList& names) {
        example_->clear();
        example_->addItems(names);
        // The example already asked for stays chosen; with none, the diode
        // is loaded (QML's Run has no default device; one is offered here).
        const QString want = requested_.isEmpty() ? QString("diode_1d") : requested_;
        const int i = example_->findText(want);
        example_->setCurrentIndex(i >= 0 ? i : 0);
        const bool example = static_cast<DeviceSource>(source_->currentData().toInt()) == DeviceSource::Example;
        if (requested_.isEmpty() && example && example_->count() > 0 && !ctl_->busy())
            loadExample(example_->currentText());
    });
    // No Python before it is needed (the shell's rule since S4 of P1): the
    // examples are listed when this panel is first shown (its tab brought to
    // the front) or focus first enters it.
    connect(qApp, &QApplication::focusChanged, this, [this](QWidget*, QWidget* now) {
        if (now && isAncestorOf(now)) ensureExamples();
    });
    connect(ctl_, &RunController::deviceLoaded, this, &RunPanel::onDeviceLoaded);
    connect(ctl_, &RunController::deviceFailed, this, &RunPanel::onDeviceFailed);
    connect(ctl_, &RunController::optionsChanged, this, &RunPanel::onOptions);
    connect(ctl_, &RunController::busyChanged, this, &RunPanel::setBusy);
    // Not onSourceChanged(): it would list the examples, starting Python
    // with the window.
    forms_->setCurrentIndex(kind_->currentIndex());
    updateEnabled();
}

QWidget* RunPanel::buildForms() {
    forms_ = new QStackedWidget(this);
    forms_->setObjectName("RunForms");
    auto page = [this](const QString& note) {
        auto* w = new QWidget(forms_);
        auto* form = new QFormLayout(w);
        form->setContentsMargins(0, 0, 0, 0);
        if (!note.isEmpty()) {
            auto* l = new QLabel(note, w);
            l->setWordWrap(true);
            form->addRow(l);
        }
        forms_->addWidget(w);
        return form;
    };
    page(tr("Solves the equilibrium only: no bias is applied."));
    page(tr("Solves at the device's own contact voltages."));
    QFormLayout* sweep = page({});
    addCombo(sweep, "SweepContact", tr("Contact"), this);
    for (const auto& f : kSweep) addField(sweep, f, this);
    QFormLayout* tr_form = page({});
    addCombo(tr_form, "TransientContact", tr("Contact"), this);
    QComboBox* wave = addCombo(tr_form, "TransientWaveform", tr("Waveform"), this);
    wave->addItems({"step", "ramp", "pulse", "constant"});
    for (const auto& f : kTransient) addField(tr_form, f, this);
    QFormLayout* ac = page({});
    addCombo(ac, "AcContact", tr("Contact"), this);
    for (const auto& f : kAc) addField(ac, f, this);
    QFormLayout* cv = page(tr("A MOS capacitor's quasi-static C-V: no device needed."));
    for (const auto& f : kCv) addField(cv, f, this);
    return forms_;
}

// P3-S6: a family (the last run's sweep at each value of a stepped contact)
// and the models-off comparison, run into the plot's overlays.
QWidget* RunPanel::buildBatchGroup() {
    auto* box = new QGroupBox(tr("Family and comparison"), this);
    box->setObjectName("BatchGroup");
    box->setToolTip(tr("Re-solve the last run's sweep: at each value of another contact (a family), "
                       "or with every model off (a comparison). The curves are drawn over its result."));
    auto* form = new QFormLayout(box);
    QComboBox* stepped = addCombo(form, "FamilyContact", tr("Stepped"), box);
    stepped->setToolTip(tr("The contact held at each value in turn"));
    for (const auto& f : kFamily) addField(form, f, box);
    auto* row = new QHBoxLayout;
    run_family_ = new QPushButton(tr("Run family"), box);
    run_family_->setObjectName("RunFamilyButton");
    run_comparison_ = new QPushButton(tr("Run comparison"), box);
    run_comparison_->setObjectName("RunComparisonButton");
    run_comparison_->setToolTip(tr("Re-solve the last sweep with every model off"));
    stop_batch_ = new QPushButton(tr("Stop"), box);
    stop_batch_->setObjectName("StopBatchButton");
    stop_batch_->setEnabled(false);
    row->addWidget(run_family_);
    row->addWidget(run_comparison_);
    row->addWidget(stop_batch_);
    form->addRow(row);
    batch_status_ = new QLabel(box);
    batch_status_->setObjectName("BatchStatus");
    batch_status_->setWordWrap(true);
    form->addRow(batch_status_);
    connect(run_family_, &QPushButton::clicked, this, &RunPanel::requestFamily);
    connect(run_comparison_, &QPushButton::clicked, this, &RunPanel::comparisonRequested);
    connect(stop_batch_, &QPushButton::clicked, this, &RunPanel::batchStopRequested);
    return box;
}

bool RunPanel::requestFamily() {
    double v[3];
    const char* names[] = {"FamilyStart", "FamilyStop", "FamilyStep"};
    for (int i = 0; i < 3; ++i) {
        QLineEdit* e = field(QString::fromLatin1(names[i]));
        bool ok = false;
        v[i] = QLocale::c().toDouble(e->text().trimmed(), &ok);
        if (!ok || !std::isfinite(v[i])) {
            emit inputRejected(tr("Invalid family configuration"), tr("%1 must be a finite number.").arg(e->accessibleName()));
            return false;
        }
    }
    emit familyRequested(combo("FamilyContact")->currentText(), v[0], v[1], v[2]);
    return true;
}

void RunPanel::setBatchBusy(bool busy) {
    run_family_->setEnabled(!busy);
    run_comparison_->setEnabled(!busy);
    stop_batch_->setEnabled(busy);
}

void RunPanel::setBatchStatus(const QString& text) { batch_status_->setText(text); }

QLineEdit* RunPanel::field(const QString& name) const { return findChild<QLineEdit*>(name); }
QComboBox* RunPanel::combo(const QString& name) const { return findChild<QComboBox*>(name); }

RunKind RunPanel::kind() const { return static_cast<RunKind>(kind_->currentData().toInt()); }

void RunPanel::setKind(RunKind k) { kind_->setCurrentIndex(kind_->findData(static_cast<int>(k))); }

void RunPanel::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    ensureExamples();
}

void RunPanel::ensureExamples() {
    if (examples_requested_) return;
    examples_requested_ = true;
    ctl_->requestExamples();
}

void RunPanel::loadExample(const QString& name) {
    requested_ = name;
    ensureExamples();
    const int i = example_->findText(name);
    if (i >= 0) example_->setCurrentIndex(i);
    source_->setCurrentIndex(source_->findData(static_cast<int>(DeviceSource::Example)));
    device_->setText(tr("Loading %1...").arg(name));
    ctl_->loadDevice(DeviceSource::Example, name);
}

void RunPanel::loadFile(DeviceSource source, const QString& path) {
    if (path.isEmpty()) return;
    source_->setCurrentIndex(source_->findData(static_cast<int>(source)));
    path_->setText(path);
    device_->setText(tr("Loading %1...").arg(path));
    ctl_->loadDevice(source, path);
}

void RunPanel::updateEnabled() {
    const bool busy = ctl_->busy();
    const bool cv = kind() == RunKind::CV;
    const bool example = static_cast<DeviceSource>(source_->currentData().toInt()) == DeviceSource::Example;
    run_->setEnabled(!busy);
    stop_->setEnabled(busy);
    kind_->setEnabled(!busy);
    forms_->setEnabled(!busy);
    source_->setEnabled(!busy && !cv);  // C-V needs no device
    example_->setEnabled(!busy && !cv && example);
    path_->setEnabled(!busy && !cv && !example);
    browse_->setEnabled(!busy && !cv && !example);
    backend_->setEnabled(!busy && !cv);
    engine_->setEnabled(!busy && !cv);
}

void RunPanel::onSourceChanged() {
    updateEnabled();
    const bool example = static_cast<DeviceSource>(source_->currentData().toInt()) == DeviceSource::Example;
    if (!example) return;
    if (example_->count() > 0)
        loadExample(example_->currentText());
    else
        ensureExamples();  // the listing loads the default example
}

void RunPanel::browse() {
    const auto source = static_cast<DeviceSource>(source_->currentData().toInt());
    const QString path = QFileDialog::getOpenFileName(
        this, source == DeviceSource::Project ? tr("Open project") : tr("Open device spec"), QString(),
        tr("JSON files (*.json);;All files (*)"));
    if (!path.isEmpty()) loadFile(source, path);
}

void RunPanel::onDeviceLoaded() {
    const auto& d = ctl_->device();
    if (!d) return;
    device_->setText(d->label);
    for (const char* name : {"SweepContact", "TransientContact", "AcContact", "FamilyContact"}) {
        QComboBox* c = combo(QString::fromLatin1(name));
        const QString keep = c->currentText();
        c->clear();
        c->addItems(d->contacts);
        if (const int i = c->findText(keep); i >= 0) c->setCurrentIndex(i);
    }
    // A project's armed sweep: shown in the form, and selected.
    if (d->project_sweep.is_object()) {
        const auto& s = d->project_sweep;
        const auto num = [](const nlohmann::json& v) {
            // The shortest text that reads back as the same double: 0.2, not 0.20000000000000001.
            return v.is_number() ? QLocale::c().toString(v.get<double>(), 'g', QLocale::FloatingPointShortest)
                                 : QString();
        };
        if (const int i = combo("SweepContact")->findText(QString::fromStdString(s.value("contact", std::string())));
            i >= 0)
            combo("SweepContact")->setCurrentIndex(i);
        field("SweepStart")->setText(num(s.value("start", nlohmann::json())));
        field("SweepStop")->setText(num(s.value("stop", nlohmann::json())));
        field("SweepStep")->setText(num(s.value("step", nlohmann::json())));
        setKind(RunKind::Sweep);
    }
    transient_armed_ = kind() == RunKind::Transient;
    ctl_->requestOptions(transient_armed_);
}

void RunPanel::onDeviceFailed(const QString& title, const QString& detail) {
    device_->setText(title + ": " + detail);
    emit inputRejected(title, detail);
}

void RunPanel::fillOptions(QComboBox* combo, const nlohmann::json& options, const QString& keep) {
    combo->clear();
    auto* model = qobject_cast<QStandardItemModel*>(combo->model());
    int keep_at = -1, first_enabled = -1;
    for (const auto& o : options) {
        if (!o.is_object()) continue;
        const QString id = QString::fromStdString(o.value("id", std::string()));
        combo->addItem(QString::fromStdString(o.value("label", std::string())), id);
        const int i = combo->count() - 1;
        const bool enabled = o.value("enabled", false);
        const QString reason = QString::fromStdString(o.value("reason", std::string()));
        if (model) model->item(i)->setEnabled(enabled);
        if (!reason.isEmpty()) combo->setItemData(i, reason, Qt::ToolTipRole);
        if (enabled && first_enabled < 0) first_enabled = i;
        if (enabled && id == keep) keep_at = i;
    }
    combo->setCurrentIndex(keep_at >= 0 ? keep_at : std::max(first_enabled, 0));
}

void RunPanel::onOptions(const JsonPayload& backends, const JsonPayload& engines) {
    fillOptions(backend_, backends.value, backend_->currentData().toString());
    fillOptions(engine_, engines.value, engine_->currentData().toString());
}

void RunPanel::onKindChanged() {
    forms_->setCurrentIndex(kind_->currentIndex());
    updateEnabled();
    // The engine list depends on an armed transient (mpi_schwarz is refused).
    const bool armed = kind() == RunKind::Transient;
    if (armed != transient_armed_ && ctl_->device()) {
        transient_armed_ = armed;
        ctl_->requestOptions(armed);
    }
}

void RunPanel::setBusy(bool) { updateEnabled(); }

bool RunPanel::requestRun() {
    if (ctl_->busy()) return false;
    std::optional<QString> bad;
    auto number = [&](const char* name) -> double {
        QLineEdit* e = field(QString::fromLatin1(name));
        bool ok = false;
        const double v = QLocale::c().toDouble(e->text().trimmed(), &ok);
        if ((!ok || !std::isfinite(v)) && !bad) bad = e->accessibleName();
        return v;
    };
    RunSettings s;
    s.kind = kind();
    s.backend = backend_->currentData().toString();
    s.engine = engine_->currentData().toString();
    const auto contact = [this](const char* name) { return combo(QString::fromLatin1(name))->currentText().toStdString(); };
    switch (s.kind) {
        case RunKind::Sweep:
            s.sweep = {{"contact", contact("SweepContact")},
                       {"start", number("SweepStart")},
                       {"stop", number("SweepStop")},
                       {"step", number("SweepStep")}};
            break;
        case RunKind::Transient:
            s.transient = {{"contact", contact("TransientContact")},
                           {"waveform",
                            {{"kind", combo("TransientWaveform")->currentText().toStdString()},
                             {"v0", number("TransientV0")},
                             {"v1", number("TransientV1")},
                             {"t0", number("TransientT0")},
                             {"t1", number("TransientT1")}}},
                           {"t_end", number("TransientTEnd")},
                           {"dt0", number("TransientDt0")}};
            break;
        case RunKind::AC: {
            bool ok = false;
            const int n = field("AcPoints")->text().trimmed().toInt(&ok);
            if (!ok && !bad) bad = field("AcPoints")->accessibleName();
            s.ac = {{"contact", contact("AcContact")},
                    {"f_start", number("AcFStart")},
                    {"f_stop", number("AcFStop")},
                    {"n_points", n}};
            break;
        }
        case RunKind::CV:
            s.cv = {{"nsub_cm3", number("CvNsub")},
                    {"tox_nm", number("CvTox")},
                    {"vstart", number("CvVStart")},
                    {"vstop", number("CvVStop")},
                    {"vstep", number("CvVStep")}};
            break;
        default:
            break;
    }
    if (bad) {
        // QML's arm-time wording: "Invalid sweep configuration", "Invalid AC configuration".
        const QString what = s.kind == RunKind::AC || s.kind == RunKind::CV ? runKindName(s.kind)
                                                                            : runKindName(s.kind).toLower();
        emit inputRejected(tr("Invalid %1 configuration").arg(what),
                           tr("%1 must be a finite number.").arg(*bad));
        return false;
    }
    return ctl_->run(s);
}

}  // namespace tcad::desktop
