#include "plot_panel.hpp"

#include <algorithm>

#include <QCheckBox>
#include <QComboBox>
#include <QFormLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QSignalBlocker>
#include <QSlider>

namespace tcad::desktop {

PlotPanel::PlotPanel(QWidget* parent) : QWidget(parent) {
    setObjectName("PlotPanel");
    auto* form = new QFormLayout(this);
    mode_ = new QLabel(this);
    mode_->setObjectName("PlotModeLabel");
    form->addRow(tr("View"), mode_);
    channel_ = new QComboBox(this);
    channel_->setObjectName("SweepChannelCombo");
    channel_->setToolTip(tr("The sweep channel drawn in Curves mode"));
    form->addRow(tr("Channel"), channel_);
    log_ = new QCheckBox(tr("Log y"), this);
    log_->setObjectName("PlotLogCheck");
    form->addRow(log_);
    cut_orientation_ = new QComboBox(this);
    cut_orientation_->setObjectName("CutOrientationCombo");
    cut_orientation_->addItem(tr("Horizontal (along x)"), true);
    cut_orientation_->addItem(tr("Vertical (along y)"), false);
    form->addRow(tr("Cut"), cut_orientation_);
    cut_slider_ = new QSlider(Qt::Horizontal, this);
    cut_slider_->setObjectName("CutPositionSlider");
    cut_slider_->setToolTip(tr("The row (horizontal) or column (vertical) of mesh nodes to cut along"));
    form->addRow(tr("At"), cut_slider_);
    cut_label_ = new QLabel(this);
    cut_label_->setObjectName("CutPositionLabel");
    form->addRow(cut_label_);
    add_comparison_ = new QPushButton(tr("Add comparison..."), this);
    add_comparison_->setObjectName("AddComparisonButton");
    add_comparison_->setToolTip(tr("Draw one sweep from another result file, dashed (replaces the current comparison)"));
    add_family_ = new QPushButton(tr("Add to family..."), this);
    add_family_->setObjectName("AddFamilyButton");
    add_family_->setToolTip(tr("Draw a sweep from another result file, one colour per file"));
    form->addRow(add_comparison_, add_family_);
    overlays_ = new QListWidget(this);
    overlays_->setObjectName("OverlayList");
    overlays_->setToolTip(tr("Double-click a label to edit it"));
    form->addRow(overlays_);
    remove_overlay_ = new QPushButton(tr("Remove"), this);
    remove_overlay_->setObjectName("RemoveOverlayButton");
    form->addRow(remove_overlay_);
    connect(add_comparison_, &QPushButton::clicked, this, &PlotPanel::addComparisonRequested);
    connect(add_family_, &QPushButton::clicked, this, &PlotPanel::addFamilyRequested);
    connect(remove_overlay_, &QPushButton::clicked, this, [this] {
        if (overlays_->currentRow() >= 0) emit removeOverlayRequested(overlays_->currentRow());
    });
    connect(overlays_, &QListWidget::itemChanged, this,
            [this](QListWidgetItem* it) { emit overlayLabelEdited(overlays_->row(it), it->text()); });
    connect(channel_, &QComboBox::activated, this, [this](int i) { emit channelChosen(channel_->itemText(i)); });
    connect(cut_orientation_, &QComboBox::activated, this,
            [this](int i) { emit cutOrientationChosen(cut_orientation_->itemData(i).toBool()); });
    connect(cut_slider_, &QSlider::valueChanged, this, &PlotPanel::cutIndexChosen);
    connect(log_, &QCheckBox::toggled, this, &PlotPanel::logToggled);
    setState({});
}

void PlotPanel::setState(const State& s) {
    const QSignalBlocker b1(channel_), b2(log_), b3(cut_orientation_), b4(cut_slider_), b5(overlays_);
    mode_->setText(s.mode);
    channel_->clear();
    channel_->addItems(s.channels);
    channel_->setCurrentIndex(static_cast<int>(s.channels.indexOf(s.channel)));
    channel_->setEnabled(s.channel_enabled && !s.channels.isEmpty());
    log_->setChecked(s.log);
    log_->setEnabled(s.log_enabled);
    const bool cut = s.cut_enabled && s.cut_nodes > 0;
    cut_orientation_->setCurrentIndex(s.cut_horizontal ? 0 : 1);
    cut_orientation_->setEnabled(cut);
    cut_slider_->setRange(0, std::max(0, s.cut_nodes - 1));
    cut_slider_->setValue(s.cut_index);
    cut_slider_->setEnabled(cut);
    cut_label_->setText(cut ? s.cut_position : QString());
    const int keep = overlays_->currentRow();
    overlays_->clear();
    for (const auto& o : s.overlays) {
        auto* it = new QListWidgetItem(o.label, overlays_);
        it->setFlags(it->flags() | Qt::ItemIsEditable);
        QFont f = it->font();
        f.setItalic(o.comparison);  // the dashed one
        it->setFont(f);
        QString tip = (o.comparison ? tr("Comparison (dashed): %1") : tr("Family: %1")).arg(o.path);
        if (!o.reason.isEmpty()) {
            it->setForeground(palette().color(QPalette::Disabled, QPalette::Text));
            tip += "\n" + tr("Not drawn: %1").arg(o.reason);
        }
        it->setToolTip(tip);
    }
    if (keep >= 0 && keep < overlays_->count()) overlays_->setCurrentRow(keep);
    add_comparison_->setEnabled(s.overlays_enabled);
    add_family_->setEnabled(s.overlays_enabled);
    overlays_->setEnabled(s.overlays_enabled);
    remove_overlay_->setEnabled(s.overlays_enabled && !s.overlays.empty());
}

}  // namespace tcad::desktop
