#include "display_panel.hpp"

#include "views/colormaps.hpp"
#include "views/field/field_view.hpp"

#include <QButtonGroup>
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleValidator>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLineEdit>
#include <QLocale>
#include <QRadioButton>
#include <QSignalBlocker>
#include <QVBoxLayout>

namespace tcad::desktop {

DisplayPanel::DisplayPanel(FieldView* view, QWidget* parent) : QWidget(parent), view_(view) {
    setObjectName("DisplayPanel");
    auto* form = new QFormLayout;

    cmap_ = new QComboBox(this);
    cmap_->setObjectName("ColorMapCombo");
    cmap_->addItem(tr("Auto (per field)"), QString());
    for (ColorMap m : {ColorMap::Viridis, ColorMap::Plasma, ColorMap::Inferno, ColorMap::RdBuR}) {
        const auto name = QString::fromUtf8(colorMapName(m).data(), static_cast<qsizetype>(colorMapName(m).size()));
        cmap_->addItem(name, name);
    }
    form->addRow(tr("Colour map"), cmap_);

    log_ = new QCheckBox(tr("Log scale"), this);
    log_->setObjectName("LogCheck");
    contours_ = new QCheckBox(tr("Contours"), this);
    contours_->setObjectName("ContoursCheck");
    mesh_ = new QCheckBox(tr("Mesh lines"), this);
    mesh_->setObjectName("MeshCheck");
    form->addRow(log_);
    form->addRow(contours_);
    form->addRow(mesh_);

    auto* range = new QGroupBox(tr("Colour range"), this);
    auto* rl = new QVBoxLayout(range);
    auto* modes = new QHBoxLayout;
    auto_ = new QRadioButton(tr("Auto"), range);
    auto_->setObjectName("RangeAuto");
    manual_ = new QRadioButton(tr("Manual"), range);
    manual_->setObjectName("RangeManual");
    auto* group = new QButtonGroup(this);
    group->addButton(auto_);
    group->addButton(manual_);
    auto_->setChecked(true);
    modes->addWidget(auto_);
    modes->addWidget(manual_);
    rl->addLayout(modes);
    auto* bounds = new QFormLayout;
    auto* validator = new QDoubleValidator(this);
    validator->setNotation(QDoubleValidator::ScientificNotation);
    validator->setLocale(QLocale::c());
    min_ = new QLineEdit(range);
    min_->setObjectName("RangeMin");
    min_->setValidator(validator);
    max_ = new QLineEdit(range);
    max_->setObjectName("RangeMax");
    max_->setValidator(validator);
    bounds->addRow(tr("Min"), min_);
    bounds->addRow(tr("Max"), max_);
    rl->addLayout(bounds);
    lock_ = new QCheckBox(tr("Lock across fields"), range);
    lock_->setObjectName("RangeLock");
    rl->addWidget(lock_);

    auto* outer = new QVBoxLayout(this);
    outer->addLayout(form);
    outer->addWidget(range);
    outer->addStretch(1);

    connect(cmap_, &QComboBox::currentIndexChanged, this, [this](int i) {
        const QString name = cmap_->itemData(i).toString();
        view_->setColorMap(name.isEmpty() ? std::nullopt : colorMapFromName(name.toStdString()));
    });
    connect(log_, &QCheckBox::toggled, view_, &FieldView::setLogScale);
    connect(contours_, &QCheckBox::toggled, view_, &FieldView::setContours);
    connect(mesh_, &QCheckBox::toggled, view_, &FieldView::setMeshLines);
    connect(auto_, &QRadioButton::toggled, this, [this](bool on) {
        if (on) view_->setAutoRange();
    });
    connect(manual_, &QRadioButton::toggled, this, [this](bool on) {
        if (on) applyRange();
    });
    connect(min_, &QLineEdit::editingFinished, this, &DisplayPanel::applyRange);
    connect(max_, &QLineEdit::editingFinished, this, &DisplayPanel::applyRange);
    connect(lock_, &QCheckBox::toggled, this, &DisplayPanel::applyRange);
    connect(view_, &FieldView::displayChanged, this, &DisplayPanel::sync);
    sync();
}

void DisplayPanel::applyRange() {
    if (!manual_->isChecked()) return;
    bool ok_lo = false, ok_hi = false;
    const double lo = QLocale::c().toDouble(min_->text(), &ok_lo);
    const double hi = QLocale::c().toDouble(max_->text(), &ok_hi);
    if (!ok_lo || !ok_hi) return;  // wait until both bounds are numbers
    view_->setManualRange(lo, hi, lock_->isChecked());
}

void DisplayPanel::sync() {
    const QSignalBlocker b1(cmap_), b2(log_), b3(contours_), b4(mesh_), b5(auto_), b6(manual_), b7(min_), b8(max_),
        b9(lock_);
    const auto override_map = view_->colorMapOverride();
    int index = 0;
    if (override_map) {
        const auto name = colorMapName(*override_map);
        index = cmap_->findData(QString::fromUtf8(name.data(), static_cast<qsizetype>(name.size())));
    }
    cmap_->setCurrentIndex(std::max(0, index));
    log_->setChecked(view_->logScale());
    contours_->setChecked(view_->contours());
    mesh_->setChecked(view_->meshLines());
    const bool map2d = !view_->is3D();
    contours_->setEnabled(map2d);
    mesh_->setEnabled(map2d);
    const ColorRange& r = view_->colorRange();
    (r.manual ? manual_ : auto_)->setChecked(true);
    const auto norm = view_->normRange();
    min_->setText(QLocale::c().toString(norm[0], 'g', 6));
    max_->setText(QLocale::c().toString(norm[1], 'g', 6));
    lock_->setChecked(r.locked);
}

}  // namespace tcad::desktop
