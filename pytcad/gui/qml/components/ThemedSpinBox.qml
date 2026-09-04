import QtQuick
import QtQuick.Controls
import ".."

// QML architecture cleanup: shared "sunken input" background styling
// for SpinBox, factored out of MeshEditor.qml's `MeshSpinBox` and
// DopingEditor.qml's `BoundsSpinBox` inline `component` blocks -- the
// same ~8-line Rectangle (radius, hover/focus border colour, sunken
// fill) was hand-rolled independently in both files. Mirrors
// ValidatedTextField.qml's existing background-styling pattern for
// TextField, minus its validation/hasError machinery: a SpinBox's
// range is already constrained by from/to, so there's nothing to
// validate here.
//
// Usage (a file-local range/width alias, same pattern as before):
//   component MeshSpinBox: ThemedSpinBox { from: 2; to: 2000 }
//   MeshSpinBox { id: nxBox; value: 80 }
SpinBox {
    id: control
    property int fieldWidth: 70

    background: Rectangle {
        implicitWidth: control.fieldWidth
        implicitHeight: 24
        radius: Theme.radiusSm
        color: control.hovered ? Qt.tint(Theme.sunken, Theme.hoverOverlay) : Theme.sunken
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.focus
                      : control.hovered ? Theme.borderStrong : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.animFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.animFast } }
    }
}
