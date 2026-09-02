import QtQuick
import QtQuick.Controls
import ".."

// GUI-IMPROVEMENT-PLAN Phase 4: ValidatedTextField - a TextField with
// built-in NaN/Inf/empty validation that reports problems to the
// GuiStateValidator and shows visual feedback.
//
// Usage:
//   ValidatedTextField {
//       id: myField
//       fieldName: "substrate_doping"
//       text: "1e15"
//       validator: DoubleValidator {}
//   }

TextField {
    id: root
    property string fieldName: ""
    property bool required: false

    // GUI-IMPROVEMENT-PLAN Phase 4: validation state
    property bool hasError: false
    property string errorMessage: ""

    color: Theme.text
    font.pixelSize: Theme.fsBody
    selectionColor: Theme.selection

    // Visual feedback: a hairline border that eases from neutral to
    // focused (accent) to invalid (error) rather than snapping colour.
    background: Rectangle {
        implicitWidth: 120
        implicitHeight: 24
        radius: Theme.radiusSm
        color: Theme.sunken
        border.width: root.activeFocus || root.hasError ? 2 : 1
        border.color: root.hasError ? Theme.error
                      : root.activeFocus ? Theme.focus
                      : Theme.border
        Behavior on border.color { ColorAnimation { duration: Theme.animFast } }
        Behavior on border.width { NumberAnimation { duration: Theme.animFast } }
    }

    // Small shake to draw the eye when a value is rejected on commit.
    // Applied as a translation on top of layout position, so it never
    // fights the binding that actually places this field.
    transform: Translate { id: shakeOffset; x: 0 }
    SequentialAnimation {
        id: shake
        loops: 1
        NumberAnimation { target: shakeOffset; property: "x"; to: -4; duration: 40 }
        NumberAnimation { target: shakeOffset; property: "x"; to: 4; duration: 40 }
        NumberAnimation { target: shakeOffset; property: "x"; to: 0; duration: 40 }
    }
    onHasErrorChanged: if (hasError) shake.start()

    // Guard against NaN/Inf from parseFloat("") / parseFloat("abc")
    onTextChanged: {
        if (root.fieldName && text !== "") {
            var value = parseFloat(text)
            if (isNaN(value) || !isFinite(value)) {
                root.hasError = true
                root.errorMessage = "Invalid number"
                if (stateValidator) {
                    stateValidator.checkValue(root.fieldName, value)
                }
            } else {
                root.hasError = false
                root.errorMessage = ""
            }
        } else if (root.required && text === "") {
            root.hasError = true
            root.errorMessage = "Required field"
            if (stateValidator) {
                stateValidator.checkValue(root.fieldName, text)
            }
        } else {
            root.hasError = false
            root.errorMessage = ""
        }
    }
    
    // Clear error when text is edited
    onEditingFinished: {
        if (text === "" && root.required) {
            root.hasError = true
            root.errorMessage = "Required field"
        } else {
            root.hasError = false
            root.errorMessage = ""
        }
    }
}
