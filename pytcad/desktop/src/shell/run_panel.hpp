// The Run dock (NATIVE-DESKTOP-PLAN.md 17.11, P3-S4): which device, which
// run, which backend and engine; Run and Stop. The pipeline itself is the
// RunController's; this panel only turns the form into RunSettings.
//
// Numbers are typed as text and read in the C locale, so 1e-11 and 1e17
// work; an empty or non-finite value is refused, named, before anything is
// sent. The contact lists come from the loaded device; a project's armed
// sweep fills the Sweep form and selects it.
#pragma once

#include "run/run_controller.hpp"

#include <QWidget>

class QComboBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QStackedWidget;
class QToolButton;

namespace tcad::desktop {

class RunPanel : public QWidget {
    Q_OBJECT

public:
    explicit RunPanel(RunController* controller, QWidget* parent = nullptr);

    // Load a device as the form would (tests, and a device opened elsewhere).
    void loadExample(const QString& name);
    void loadFile(DeviceSource source, const QString& path);
    void setKind(RunKind kind);
    RunKind kind() const;
    // Read the form and start the run; false (and inputRejected) when a value
    // cannot be read, or the controller is busy.
    bool requestRun();
    // Read the family's values and ask for it (familyRequested); false,
    // with inputRejected, when a value cannot be read.
    bool requestFamily();
    void setBatchBusy(bool busy);
    void setBatchStatus(const QString& text);
    QPushButton* runFamilyButton() const { return run_family_; }
    QPushButton* runComparisonButton() const { return run_comparison_; }
    QPushButton* stopBatchButton() const { return stop_batch_; }
    QLabel* batchStatus() const { return batch_status_; }

    QComboBox* sourceCombo() const { return source_; }
    QComboBox* exampleCombo() const { return example_; }
    QComboBox* kindCombo() const { return kind_; }
    QComboBox* backendCombo() const { return backend_; }
    QComboBox* engineCombo() const { return engine_; }
    QPushButton* runButton() const { return run_; }
    QPushButton* stopButton() const { return stop_; }
    QLabel* deviceLabel() const { return device_; }
    // A form field by its object name (e.g. "SweepStep"), for tests.
    QLineEdit* field(const QString& name) const;
    QComboBox* combo(const QString& name) const;

signals:
    void inputRejected(const QString& title, const QString& detail);
    // P3-S6: the Family and comparison group.
    void familyRequested(const QString& stepped, double start, double stop, double step);
    void comparisonRequested();
    void batchStopRequested();

protected:
    // Shown (its tab brought to the front): list the examples. A background
    // tab starts no Python.
    void showEvent(QShowEvent* event) override;

private:
    void onSourceChanged();
    void browse();
    void onDeviceLoaded();
    void onDeviceFailed(const QString& title, const QString& detail);
    void onOptions(const JsonPayload& backends, const JsonPayload& engines);
    void onKindChanged();
    void setBusy(bool busy);
    void updateEnabled();  // from busy, the run kind and the device source
    void ensureExamples();  // examples.list, once
    QWidget* buildForms();
    QWidget* buildBatchGroup();
    static void fillOptions(QComboBox* combo, const nlohmann::json& options, const QString& keep);

    RunController* ctl_;
    QComboBox* source_ = nullptr;
    QComboBox* example_ = nullptr;
    QLineEdit* path_ = nullptr;
    QToolButton* browse_ = nullptr;
    QLabel* device_ = nullptr;
    QComboBox* kind_ = nullptr;
    QStackedWidget* forms_ = nullptr;
    QComboBox* backend_ = nullptr;
    QComboBox* engine_ = nullptr;
    QPushButton* run_ = nullptr;
    QPushButton* stop_ = nullptr;
    QPushButton* run_family_ = nullptr;
    QPushButton* run_comparison_ = nullptr;
    QPushButton* stop_batch_ = nullptr;
    QLabel* batch_status_ = nullptr;
    bool transient_armed_ = false;  // what the engine options were last asked for
    bool examples_requested_ = false;
    QString requested_;             // the example last asked for ("" before any)
};

}  // namespace tcad::desktop
