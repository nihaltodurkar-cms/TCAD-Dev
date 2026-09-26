// The result info panel (NATIVE-DESKTOP-PLAN.md section 15.13, S3d): what
// the open result file is, in two columns -- property, value -- grouped
// as File, Mesh, Fields, Vectors, Terminals, Run and Blocks.
//
// Everything comes from ResultModel, whose values the contract gate holds
// equal to the Python side (gui/tests/test_desktop_contracts.py). The
// applied bias voltages are NOT shown: the result grammar does not carry
// them (only whether a bias solve ran).
#pragma once

#include <QTreeWidget>

namespace tcad::desktop {

class ResultModel;

class InfoPanel : public QTreeWidget {
    Q_OBJECT

public:
    explicit InfoPanel(QWidget* parent = nullptr);

    // Fills the panel for `model` (nullptr clears it).
    void showResult(const ResultModel* model, const QString& path);
    // The value shown for `property` under `group` ("" if none) -- for tests.
    QString value(const QString& group, const QString& property) const;
};

}  // namespace tcad::desktop
