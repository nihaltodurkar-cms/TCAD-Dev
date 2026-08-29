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
        
        // Busy indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.busy ? Theme.running : "transparent"
            border.color: root.busy ? Theme.running : "transparent"
            
            // Pulsing animation when busy
            SequentialAnimation on opacity {
                running: root.busy
                loops: Animation.Infinite
                NumberAnimation {
                    to: 0.2
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
        
        // Result indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.hasResult ? Theme.ok : Theme.textFaint
            border.color: root.hasResult ? Theme.ok : "transparent"
        }
        
        // Dirty indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.isDirty ? Theme.running : "transparent"
            border.color: root.isDirty ? Theme.running : "transparent"
        }
        
        // Error indicator
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.hasError ? Theme.error : "transparent"
            border.color: root.hasError ? Theme.error : "transparent"
        }
    }
}
