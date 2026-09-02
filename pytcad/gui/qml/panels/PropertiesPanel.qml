import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

Rectangle {
    color: Theme.panel
    border.color: Theme.border
    property var propertiesModel

    // Educational glossary: what each derived quantity MEANS physically.
    // Presentation-layer knowledge only -- the values themselves always
    // come from sweep_derived/process_derived via the controller.
    readonly property var glossary: ({
        "Vth": "Threshold voltage, max-gm method: fit the tangent at peak " +
               "transconductance dId/dVg and find where it crosses Id = 0.",
        "Vth (max-gm)": "Threshold voltage: the tangent at peak " +
               "transconductance crosses Id = 0 here.",
        "Ion": "On-current: the largest current on the swept curve.",
        "Ioff": "Off-current: the smallest current magnitude on the curve.",
        "Ion/Ioff": "On/off ratio -- switching quality of a transistor. " +
                    "10^6+ is considered strong switching.",
        "Imax": "Maximum current over the sweep.",
        "Imin": "Minimum current over the sweep.",
        "max gm": "Peak transconductance dId/dVg -- how strongly the gate " +
                  "controls the channel current.",
        "junction_depth_um": "Depth where net doping crosses zero: the " +
                             "metallurgical p-n junction.",
        "sheet_resistance_ohm_sq": "Resistance of a square of this layer " +
                                   "(Ω/□): Rs = 1/(q ∫ μ·N dx).",
        "oxide_thickness_um": "SiO2 thickness from Deal-Grove oxidation.",
        "silicon_consumed_um": "Silicon eaten by oxidation (about 44% of " +
                               "the oxide thickness)."
    })

    function tooltipFor(key) {
        if (!key) return ""
        if (glossary.hasOwnProperty(key)) return glossary[key]
        // rows are prefixed/suffixed by context ("Sweep Imax (gate)",
        // "peak_concentration_cm3_B"), so match by substring
        for (var k in glossary)
            if (key.indexOf(k) >= 0) return glossary[k]
        if (/^peak_concentration_cm3_/.test(key))
            return "Peak concentration of this implanted species (cm^-3)."
        if (/^peak_depth_um_/.test(key))
            return "Depth of this species' projected range Rp (um)."
        if (/^implanted_dose_cm2_/.test(key))
            return "Total implanted dose actually stored in the wafer (cm^-2), from integrating the profile."
        return ""
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader { Layout.fillWidth: true; title: "Properties" }

        ListView {
            id: rows
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: propertiesModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                width: rows.width
                height: 30
                background: Rectangle {
                    color: hovered ? Theme.panelAlt : "transparent"
                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                }
                contentItem: RowLayout {
                    spacing: Theme.pad
                    Label {
                        text: model.key
                        color: Theme.textDim
                        elide: Text.ElideRight
                        Layout.preferredWidth: rows.width * 0.45
                        font.pixelSize: Theme.fsBody
                    }
                    Label {
                        text: model.value
                        color: Theme.text
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        font.pixelSize: Theme.fsBody
                    }
                }
                ToolTip.visible: hovered && tooltipFor(model.key) !== ""
                ToolTip.delay: 350
                ToolTip.text: tooltipFor(model.key)
                ToolTip.timeout: 6000
            }
        }
    }
}
