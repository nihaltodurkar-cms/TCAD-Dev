import QtQuick
import QtQuick.Controls
import ".."

// QML architecture cleanup: shared "sunken input" background styling
// for ComboBox -- the same ~8-line Rectangle (radius, hover/focus
// border colour, sunken fill) as ThemedSpinBox.qml, previously
// hand-rolled independently in MeshEditor.qml (gradingBox),
// DopingEditor.qml (materialBox/profileBox/highSideBox), GateEditor.qml
// (modeBox), OxidizeEditor.qml (ambientBox), and ImplantEditor.qml
// (speciesBox). Sizing is left to each call site's own Layout.*
// properties (matching how every existing instance except one already
// sized itself), not baked in here.
ComboBox {
    id: control

    background: Rectangle {
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
