// The Display panel (NATIVE-DESKTOP-PLAN.md 15.17, S5e): how the current
// field is drawn -- colour map (Auto = the field kind's default, or an
// override), log scale, contours, mesh lines, and the colour range (Auto,
// or Manual min/max, optionally Locked across field switches).
//
// It edits the FieldView and follows it (displayChanged), so the toolbar's
// Log action and this panel never disagree. Contours and mesh lines are
// 2D overlays and are disabled for a 3D result (3D display modes are S6).
#pragma once

#include <QWidget>

class QCheckBox;
class QComboBox;
class QLineEdit;
class QRadioButton;

namespace tcad::desktop {

class FieldView;

class DisplayPanel : public QWidget {
    Q_OBJECT

public:
    explicit DisplayPanel(FieldView* view, QWidget* parent = nullptr);

    // Re-read the view (called on displayChanged).
    void sync();

private:
    void applyRange();

    FieldView* view_;
    QComboBox* cmap_ = nullptr;
    QCheckBox* log_ = nullptr;
    QCheckBox* contours_ = nullptr;
    QCheckBox* mesh_ = nullptr;
    QRadioButton* auto_ = nullptr;
    QRadioButton* manual_ = nullptr;
    QLineEdit* min_ = nullptr;
    QLineEdit* max_ = nullptr;
    QCheckBox* lock_ = nullptr;
};

}  // namespace tcad::desktop
