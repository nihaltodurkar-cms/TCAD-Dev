// Sweep playback (NATIVE-DESKTOP-PLAN.md 15.19, S6f): viewer3d.py's
// playback dock -- step back, play/pause (one frame per 300 ms, looping),
// step forward, a slider and the sweep voltage -- plus a Result button
// that goes back to the result's own field. Enabled only for a result
// with sweep snapshots (3D sweeps are their only producer).
#pragma once

#include <QWidget>

class QLabel;
class QPushButton;
class QSlider;
class QTimer;

namespace tcad::desktop {

class FieldView;

class PlaybackPanel : public QWidget {
    Q_OBJECT

public:
    explicit PlaybackPanel(FieldView* view, QWidget* parent = nullptr);

    void sync();
    bool playing() const;
    void setPlaying(bool on);
    void step(int delta);  // stops playback, as viewer3d.py's step buttons do
    static constexpr int kFrameMs = 300;  // viewer3d.py's timer interval

private:
    void tick();

    FieldView* view_;
    QPushButton* back_ = nullptr;
    QPushButton* play_ = nullptr;
    QPushButton* forward_ = nullptr;
    QPushButton* result_ = nullptr;
    QSlider* slider_ = nullptr;
    QLabel* label_ = nullptr;
    QTimer* timer_ = nullptr;
};

}  // namespace tcad::desktop
