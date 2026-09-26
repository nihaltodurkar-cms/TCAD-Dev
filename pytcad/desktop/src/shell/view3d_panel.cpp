#include "view3d_panel.hpp"

#include "views/field/field_view.hpp"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QSlider>
#include <QSpinBox>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <memory>
#include <vector>

namespace tcad::desktop {
namespace {

const char* const kAxis[3] = {"X", "Y", "Z"};

}  // namespace

View3DPanel::View3DPanel(FieldView* view, QWidget* parent) : QWidget(parent), view_(view) {
    setObjectName("View3DPanel");
    auto* body = new QWidget;
    auto* col = new QVBoxLayout(body);

    // -- surface and views
    auto* look = new QGroupBox(tr("View"), body);
    auto* lf = new QFormLayout(look);
    surface_ = new QComboBox(look);
    surface_->setObjectName("SurfaceModeCombo");
    surface_->addItem(tr("Field"), static_cast<int>(SurfaceMode::Field));
    surface_->addItem(tr("Context (translucent)"), static_cast<int>(SurfaceMode::Context));
    surface_->addItem(tr("Hidden"), static_cast<int>(SurfaceMode::Hidden));
    lf->addRow(tr("Surface"), surface_);
    auto* presets = new QHBoxLayout;
    const std::array<std::pair<const char*, ViewPreset>, 4> kViews{
        {{"Iso", ViewPreset::Iso}, {"X", ViewPreset::PlusX}, {"Y", ViewPreset::PlusY}, {"Z", ViewPreset::PlusZ}}};
    for (const auto& [label, preset] : kViews) {
        auto* b = new QPushButton(QString::fromLatin1(label), look);
        b->setObjectName(QString("View%1").arg(QString::fromLatin1(label)));
        b->setToolTip(preset == ViewPreset::Iso ? tr("Oblique view") : tr("Look along +%1").arg(QString::fromLatin1(label)));
        connect(b, &QPushButton::clicked, view_, [this, p = preset] { view_->setViewPreset(p); });
        presets->addWidget(b);
    }
    lf->addRow(tr("Look"), presets);
    auto* central = new QPushButton(tr("Central z-plane"), look);
    central->setObjectName("CentralZPlane");
    central->setToolTip(tr("The QML viewport's 3D view: the z-slice at nz // 2, seen along z"));
    connect(central, &QPushButton::clicked, view_, &FieldView::showCentralZPlane);
    lf->addRow(central);
    col->addWidget(look);

    // -- crop
    auto* crop = new QGroupBox(tr("Crop (node indices)"), body);
    auto* cg = new QGridLayout(crop);
    for (int a = 0; a < 3; ++a) {
        crop_lo_[static_cast<std::size_t>(a)] = new QSpinBox(crop);
        crop_hi_[static_cast<std::size_t>(a)] = new QSpinBox(crop);
        crop_lo_[static_cast<std::size_t>(a)]->setObjectName(QString("Crop%1Min").arg(kAxis[a]));
        crop_hi_[static_cast<std::size_t>(a)]->setObjectName(QString("Crop%1Max").arg(kAxis[a]));
        cg->addWidget(new QLabel(QString::fromLatin1(kAxis[a]), crop), a, 0);
        cg->addWidget(crop_lo_[static_cast<std::size_t>(a)], a, 1);
        cg->addWidget(crop_hi_[static_cast<std::size_t>(a)], a, 2);
        connect(crop_lo_[static_cast<std::size_t>(a)], &QSpinBox::valueChanged, this, &View3DPanel::applyCrop);
        connect(crop_hi_[static_cast<std::size_t>(a)], &QSpinBox::valueChanged, this, &View3DPanel::applyCrop);
    }
    auto* reset_crop = new QPushButton(tr("Whole device"), crop);
    reset_crop->setObjectName("CropReset");
    connect(reset_crop, &QPushButton::clicked, view_, [this] { view_->setCrop(view_->fullBox()); });
    cg->addWidget(reset_crop, 3, 0, 1, 3);
    col->addWidget(crop);

    // -- slices
    auto* slices = new QGroupBox(tr("Slices (at node planes)"), body);
    auto* sg = new QGridLayout(slices);
    for (int a = 0; a < 3; ++a) {
        const auto ua = static_cast<std::size_t>(a);
        slice_on_[ua] = new QCheckBox(QString::fromLatin1(kAxis[a]), slices);
        slice_on_[ua]->setObjectName(QString("Slice%1").arg(kAxis[a]));
        slice_at_[ua] = new QSlider(Qt::Horizontal, slices);
        slice_at_[ua]->setObjectName(QString("Slice%1Index").arg(kAxis[a]));
        slice_label_[ua] = new QLabel(slices);
        slice_label_[ua]->setObjectName(QString("Slice%1Label").arg(kAxis[a]));
        sg->addWidget(slice_on_[ua], a, 0);
        sg->addWidget(slice_at_[ua], a, 1);
        sg->addWidget(slice_label_[ua], a, 2);
        connect(slice_on_[ua], &QCheckBox::toggled, view_, [this, a](bool on) {
            view_->setSlice(a, on, static_cast<std::size_t>(slice_at_[static_cast<std::size_t>(a)]->value()));
        });
        connect(slice_at_[ua], &QSlider::valueChanged, view_, [this, a](int k) {
            view_->setSlice(a, slice_on_[static_cast<std::size_t>(a)]->isChecked(), static_cast<std::size_t>(k));
        });
    }
    col->addWidget(slices);

    // -- isosurface and volume
    auto* scal = new QGroupBox(tr("Isosurface and volume"), body);
    auto* vf = new QFormLayout(scal);
    iso_ = new QCheckBox(tr("Isosurface"), scal);
    iso_->setObjectName("IsoCheck");
    iso_level_ = new QDoubleSpinBox(scal);
    iso_level_->setObjectName("IsoLevel");
    iso_level_->setDecimals(6);
    iso_level_->setToolTip(tr("In displayed units: log10 when the field is shown in log"));
    vf->addRow(iso_, iso_level_);
    volume_ = new QCheckBox(tr("Volume"), scal);
    volume_->setObjectName("VolumeCheck");
    preset_ = new QComboBox(scal);
    preset_->setObjectName("VolumePreset");
    for (VolumePreset p : {VolumePreset::Linear, VolumePreset::LogHigh, VolumePreset::LogLow, VolumePreset::Threshold})
        preset_->addItem(QString::fromLatin1(volumePresetName(p)), static_cast<int>(p));
    preset_->setToolTip(tr("viewer3d.py's presets: a colour map (applied to the whole view) and a constant opacity"));
    vf->addRow(volume_, preset_);
    connect(iso_, &QCheckBox::toggled, view_, &FieldView::setIsosurface);
    connect(iso_level_, &QDoubleSpinBox::valueChanged, view_, &FieldView::setIsoLevel);
    connect(volume_, &QCheckBox::toggled, view_, &FieldView::setVolume);
    connect(preset_, &QComboBox::currentIndexChanged, view_,
            [this](int i) { view_->setVolumePreset(static_cast<VolumePreset>(preset_->itemData(i).toInt())); });
    col->addWidget(scal);

    // -- vectors
    auto* vec = new QGroupBox(tr("Vector field"), body);
    auto* vl = new QFormLayout(vec);
    vector_ = new QComboBox(vec);
    vector_->setObjectName("VectorField");
    vl->addRow(tr("Field"), vector_);
    glyphs_ = new QCheckBox(tr("Arrows"), vec);
    glyphs_->setObjectName("GlyphCheck");
    spacing_ = new QDoubleSpinBox(vec);
    spacing_->setObjectName("GlyphSpacing");
    spacing_->setRange(0.0, 0.5);
    spacing_->setSingleStep(0.01);
    spacing_->setDecimals(3);
    spacing_->setToolTip(tr("Arrow spacing, as a fraction of the device diagonal (viewer3d.py's tolerance)"));
    vl->addRow(glyphs_, spacing_);
    streamlines_ = new QCheckBox(tr("Streamlines"), vec);
    streamlines_->setObjectName("StreamlineCheck");
    vl->addRow(streamlines_);
    vector_note_ = new QLabel(vec);
    vector_note_->setObjectName("VectorNote");
    vector_note_->setWordWrap(true);
    vl->addRow(vector_note_);
    connect(vector_, &QComboBox::currentTextChanged, view_,
            [this](const QString& name) { view_->setVectorField(name.toStdString()); });
    connect(glyphs_, &QCheckBox::toggled, view_, &FieldView::setGlyphs);
    connect(spacing_, &QDoubleSpinBox::valueChanged, view_, &FieldView::setGlyphSpacing);
    connect(streamlines_, &QCheckBox::toggled, view_, &FieldView::setStreamlines);
    col->addWidget(vec);

    // -- exploded view
    auto* ex = new QGroupBox(tr("Exploded view"), body);
    auto* el = new QFormLayout(ex);
    exploded_ = new QCheckBox(tr("Separate regions"), ex);
    exploded_->setObjectName("ExplodedCheck");
    separation_ = new QDoubleSpinBox(ex);
    separation_->setObjectName("ExplodedSeparation");
    separation_->setDecimals(6);
    separation_->setSuffix(tr(" um"));
    el->addRow(exploded_);
    el->addRow(tr("Separation"), separation_);
    connect(exploded_, &QCheckBox::toggled, view_, &FieldView::setExploded);
    connect(separation_, &QDoubleSpinBox::valueChanged, view_, &FieldView::setExplodedSeparation);
    col->addWidget(ex);
    col->addStretch(1);

    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setWidget(body);
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->addWidget(scroll);

    connect(surface_, &QComboBox::currentIndexChanged, view_,
            [this](int i) { view_->setSurfaceMode(static_cast<SurfaceMode>(surface_->itemData(i).toInt())); });
    connect(view_, &FieldView::displayChanged, this, &View3DPanel::sync);
    sync();
}

void View3DPanel::applyCrop() {
    NodeBox b;
    for (std::size_t a = 0; a < 3; ++a) {
        b.lo[a] = static_cast<std::size_t>(crop_lo_[a]->value());
        b.hi[a] = static_cast<std::size_t>(std::max(crop_lo_[a]->value(), crop_hi_[a]->value()));
    }
    view_->setCrop(b);
}

void View3DPanel::sync() {
    const bool three = view_->is3D() && !view_->field().empty();
    setEnabled(three);
    setToolTip(three ? QString() : tr("3D display modes apply to a 3D result"));
    if (!three) return;

    QList<QObject*> all{surface_, iso_, iso_level_, volume_, preset_, vector_, glyphs_, spacing_, streamlines_, exploded_, separation_};
    for (std::size_t a = 0; a < 3; ++a) all << crop_lo_[a] << crop_hi_[a] << slice_on_[a] << slice_at_[a];
    std::vector<std::unique_ptr<QSignalBlocker>> blocks;
    for (QObject* o : all) blocks.push_back(std::make_unique<QSignalBlocker>(o));

    surface_->setCurrentIndex(surface_->findData(static_cast<int>(view_->surfaceMode())));
    const NodeBox full = view_->fullBox(), crop = view_->crop();
    for (std::size_t a = 0; a < 3; ++a) {
        crop_lo_[a]->setRange(0, static_cast<int>(full.hi[a]));
        crop_hi_[a]->setRange(0, static_cast<int>(full.hi[a]));
        crop_lo_[a]->setValue(static_cast<int>(crop.lo[a]));
        crop_hi_[a]->setValue(static_cast<int>(crop.hi[a]));
        const SliceState s = view_->slice(static_cast<int>(a));
        slice_on_[a]->setChecked(s.on);
        slice_at_[a]->setRange(0, static_cast<int>(full.hi[a]));
        slice_at_[a]->setValue(static_cast<int>(s.index));
        slice_label_[a]->setText(QString("%1 um").arg(view_->axisUm(static_cast<int>(a))[s.index], 0, 'f', 3));
    }

    const auto r = view_->dataRange();
    iso_->setChecked(view_->isosurface());
    iso_level_->setRange(std::min(r[0], r[1]), std::max(r[0], r[1]));
    iso_level_->setSingleStep(r[1] > r[0] ? (r[1] - r[0]) / 100.0 : 0.01);
    iso_level_->setValue(view_->isoLevel());
    volume_->setChecked(view_->volume());
    preset_->setCurrentIndex(preset_->findData(static_cast<int>(view_->volumePreset())));

    vector_->clear();
    for (const auto& name : view_->result()->vector_names()) vector_->addItem(QString::fromStdString(name));
    vector_->setCurrentText(QString::fromStdString(view_->vectorField()));
    const bool has_vec = !view_->vectorField().empty();
    for (QWidget* w : std::initializer_list<QWidget*>{vector_, glyphs_, spacing_, streamlines_}) {
        w->setEnabled(has_vec);
        w->setToolTip(has_vec ? QString() : tr("The result has no vector field (current density needs a bias solve)"));
    }
    glyphs_->setChecked(view_->glyphs());
    spacing_->setValue(view_->glyphSpacing());
    streamlines_->setChecked(view_->streamlines());
    vector_note_->setText(view_->snapshots() ? tr("Arrows and streamlines show the solved result; sweep snapshots carry "
                                                  "no vector data.")
                                             : QString());

    QString why;
    const bool can_explode = view_->explodedAvailable(&why);
    exploded_->setEnabled(can_explode);
    exploded_->setToolTip(can_explode ? QString() : why);
    separation_->setEnabled(can_explode && view_->exploded());
    exploded_->setChecked(view_->exploded());
    const double diag = view_->diagonalUm();
    separation_->setRange(std::max(diag * 1e-4, 1e-9), diag * 5.0);  // viewer3d.py's range
    separation_->setSingleStep(0.015 * diag);
    separation_->setValue(view_->explodedSeparation());
}

}  // namespace tcad::desktop
