import QtQuick
import QtQuick.Controls

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
    
    // Visual feedback for validation errors
    background: Rectangle {
        implicitWidth: 120
        implicitHeight: 24
        opacity: 0.2
        color: root.hasError ? "#ff0000" : "gray"
        radius: 2
        border.color: root.hasError ? "#ff0000" : "transparent"
    }
    
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
