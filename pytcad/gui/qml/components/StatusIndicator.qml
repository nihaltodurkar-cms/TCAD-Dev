import QtQuick
import QtQuick.Controls
import ".."

// GUI-IMPROVEMENT-PLAN Phase 4: StatusIndicator - shows the current
// GUI state at a glance with color-coded indicators.
//
// Usage:
//   StatusIndicator {
//       busy: appController.busy
//       hasResult: appController.hasResult
//       isDirty: appController.isDirty
//   }

Item {
    id: root
    property bool busy: false
    property bool hasResult: false
    property bool isDirty: false
    property bool hasError: false

    width: 40
    height: 12
    
    Row {
        spacing: 4
        anchors.centerIn: parent
        
        // Busy indicator, with a soft glow halo behind the pulsing dot
        Item {
            width: 8; height: 8
            Rectangle {
                id: glow
                anchors.centerIn: parent
                width: 16; height: 16; radius: 8
                visible: root.busy
                color: "transparent"
                border.width: 4
                border.color: Theme.running
                scale: 0.5
                opacity: 0.5
                ParallelAnimation {
                    running: root.busy
                    loops: Animation.Infinite
                    SequentialAnimation {
                        NumberAnimation { target: glow; property: "scale"; from: 0.5; to: 1.6; duration: 1100; easing.type: Easing.OutCubic }
                        PropertyAction { target: glow; property: "scale"; value: 0.5 }
                    }
                    SequentialAnimation {
                        NumberAnimation { target: glow; property: "opacity"; from: 0.5; to: 0.0; duration: 1100; easing.type: Easing.OutCubic }
                        PropertyAction { target: glow; property: "opacity"; value: 0.5 }
                    }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: 4
                color: root.busy ? Theme.running : "transparent"
                border.color: root.busy ? Theme.running : "transparent"

                // Pulsing animation when busy
                SequentialAnimation on opacity {
                    running: root.busy
                    loops: Animation.Infinite
                    NumberAnimation {
                        to: 0.25
                        duration: 800
                        easing.type: Easing.InOutSine
                    }
                    NumberAnimation {
                        to: 1.0
                        duration: 800
                        easing.type: Easing.InOutSine
                    }
                }
            }
        }

        // Result indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.hasResult ? Theme.ok : Theme.textFaint
            border.color: root.hasResult ? Theme.ok : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.animMed } }
        }

        // Dirty indicator
        // v2.1 correction (DESIGN.md section 3.3): unsaved changes is a
        // caution/attention state, not "running" -- was Theme.running
        // (amber), now the dedicated Theme.warning token (same hex).
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.isDirty ? Theme.warning : "transparent"
            border.color: root.isDirty ? Theme.warning : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.animMed } }
        }

        // Error indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.hasError ? Theme.error : "transparent"
            border.color: root.hasError ? Theme.error : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.animMed } }
        }
    }
}
