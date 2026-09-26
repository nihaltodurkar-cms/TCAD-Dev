// The Plot panel (NATIVE-DESKTOP-PLAN.md 16.2, P2-S3/S4): the curve modes'
// controls -- the sweep channel (Curves mode), log y (the modes with a log
// toggle), and the line cut's orientation and position (Line cut mode: a
// slider over the cut axis's NODES, so it snaps to them, labelled with the
// node actually used), and the overlays (P2-S5: a comparison and a family
// of sweeps from other result files, in Curves and C-V modes; labels are
// editable in the list). Tabbed with Display. It holds no state of its own: the main
// window sets what it shows (setState) and acts on its signals, so the
// toolbar's Log action and this panel never disagree.
#pragma once

#include <QStringList>
#include <QWidget>

#include <vector>

class QCheckBox;
class QComboBox;
class QLabel;
class QListWidget;
class QPushButton;
class QSlider;

namespace tcad::desktop {

class PlotPanel : public QWidget {
    Q_OBJECT

public:
    explicit PlotPanel(QWidget* parent = nullptr);

    struct State {
        QString mode;              // the view mode's name, for the header line
        QStringList channels;      // the sweep's channels; empty = no sweep
        QString channel;           // the selected one
        bool channel_enabled = false;
        bool log = false;
        bool log_enabled = false;
        bool cut_enabled = false;
        bool cut_horizontal = true;   // Horizontal: at a y, along x
        int cut_index = 0;            // node on the cut axis
        int cut_nodes = 0;            // nodes on the cut axis (0: no cut possible)
        QString cut_position;         // e.g. "y = 0.1234 um (node 3 of 41)"
        struct Overlay {
            QString label;
            bool comparison = false;  // else a family member
            QString reason;           // why it is not drawn now ("" = drawn)
            QString path;
        };
        bool overlays_enabled = false;
        std::vector<Overlay> overlays;
    };
    void setState(const State& s);

signals:
    void channelChosen(const QString& channel);
    void logToggled(bool on);
    void cutOrientationChosen(bool horizontal);
    void cutIndexChosen(int index);
    void addComparisonRequested();
    void addFamilyRequested();
    void removeOverlayRequested(int row);
    void overlayLabelEdited(int row, const QString& label);

private:
    QLabel* mode_ = nullptr;
    QComboBox* channel_ = nullptr;
    QCheckBox* log_ = nullptr;
    QComboBox* cut_orientation_ = nullptr;
    QSlider* cut_slider_ = nullptr;
    QLabel* cut_label_ = nullptr;
    QPushButton* add_comparison_ = nullptr;
    QPushButton* add_family_ = nullptr;
    QListWidget* overlays_ = nullptr;
    QPushButton* remove_overlay_ = nullptr;
};

}  // namespace tcad::desktop
