// The 3D panel (NATIVE-DESKTOP-PLAN.md 15.19, S6): how a 3D result is
// drawn -- surface mode and view presets, crop (clipping), slices at node
// planes, isosurface, volume presets, current-density glyphs and
// streamlines, and the exploded view of the result's regions.
//
// Like the Display panel it edits the FieldView and follows it
// (displayChanged). The whole panel is disabled for a 2D or 1D result; a
// control the result has no data for is disabled with a tooltip saying why.
#pragma once

#include <QWidget>

#include <array>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QPushButton;
class QSlider;
class QSpinBox;

namespace tcad::desktop {

class FieldView;

class View3DPanel : public QWidget {
    Q_OBJECT

public:
    explicit View3DPanel(FieldView* view, QWidget* parent = nullptr);

    // Re-read the view (called on displayChanged).
    void sync();

private:
    void applyCrop();

    FieldView* view_;
    QComboBox* surface_ = nullptr;
    std::array<QSpinBox*, 3> crop_lo_{}, crop_hi_{};
    std::array<QCheckBox*, 3> slice_on_{};
    std::array<QSlider*, 3> slice_at_{};
    std::array<QLabel*, 3> slice_label_{};
    QCheckBox* iso_ = nullptr;
    QDoubleSpinBox* iso_level_ = nullptr;
    QCheckBox* volume_ = nullptr;
    QComboBox* preset_ = nullptr;
    QComboBox* vector_ = nullptr;
    QCheckBox* glyphs_ = nullptr;
    QDoubleSpinBox* spacing_ = nullptr;
    QCheckBox* streamlines_ = nullptr;
    QLabel* vector_note_ = nullptr;
    QCheckBox* exploded_ = nullptr;
    QDoubleSpinBox* separation_ = nullptr;
};

}  // namespace tcad::desktop
