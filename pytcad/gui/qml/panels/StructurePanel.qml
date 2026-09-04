import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import ".."

Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller
    property string selectedRegionId: ""
    property string selectedContactId: ""
    property string selectedGateId: ""

    // QML architecture cleanup: named role-offset maps, one per list
    // model, matching each Python ...ListModel's own Role class exactly
    // (gui/controllers/region_list_model.py / contact_list_model.py /
    // gate_list_model.py) -- replaces the same Qt.UserRole + N literals
    // previously repeated inline, unnamed, at every lookup call site
    // below. model.roleNames() (which WOULD give the same names
    // dynamically) is not callable from QML in this PySide6 build --
    // confirmed directly ("TypeError: ... is not a function") -- so
    // these stay explicit, cross-referenced constants instead.
    readonly property var _regionRoles: ({
        id: Qt.UserRole + 1, name: Qt.UserRole + 2, bounds: Qt.UserRole + 3,
        doping: Qt.UserRole + 4, material: Qt.UserRole + 6,
        dopingProfile: Qt.UserRole + 7, profilePeak: Qt.UserRole + 8,
        profileSigmaY: Qt.UserRole + 9, profileSigmaLat: Qt.UserRole + 10,
        profileEdgeX: Qt.UserRole + 11, profileHighSide: Qt.UserRole + 12
    })
    readonly property var _contactRoles: ({
        id: Qt.UserRole + 1, name: Qt.UserRole + 2,
        edge: Qt.UserRole + 3, voltage: Qt.UserRole + 4
    })
    readonly property var _gateRoles: ({
        id: Qt.UserRole + 1, name: Qt.UserRole + 2, tox: Qt.UserRole + 3,
        vfbMode: Qt.UserRole + 4, vfbValue: Qt.UserRole + 5, voltage: Qt.UserRole + 6
    })

    // Generic row-by-id lookup, replacing three near-identical
    // hand-rolled loops (one per model) that differed only in which
    // role map they read.
    function _lookupRow(model, roles, id) {
        for (var i = 0; i < model.rowCount(); i++) {
            var idx = model.index(i, 0)
            if (model.data(idx, roles.id) === id) {
                var result = {}
                for (var key in roles)
                    if (key !== "id") result[key] = model.data(idx, roles[key])
                return result
            }
        }
        return null
    }

    function _regionData(id) {
        return root._lookupRow(controller.regionListModel, root._regionRoles, id)
    }
    function _contactData(id) {
        return root._lookupRow(controller.contactListModel, root._contactRoles, id)
    }
    function _gateData(id) {
        return root._lookupRow(controller.gateListModel, root._gateRoles, id)
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: Theme.pad
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent ? parent.width : 0
            spacing: Theme.pad

            Label {
                // Material is read-only in v0.2 -- Device2D takes exactly
                // one material for the whole domain and SILICON is the
                // only Semiconductor instance pytcad defines (design
                // spec §3). Reads controller.structureMaterial (a plain
                // str property), NOT structureForQml.material -- a
                // non-QObject Python object's attributes aren't
                // readable from QML/JS at all.
                text: "Material: " + (root.controller ? root.controller.structureMaterial : "Silicon")
                      + " (read-only)"
                color: Theme.textDim
                font.pixelSize: 11
            }

            RegionList {
                Layout.fillWidth: true
                controller: root.controller
                selectedRegionId: root.selectedRegionId
                onRegionSelected: (id) => root.selectedRegionId = id
            }

            DopingEditor {
                Layout.fillWidth: true
                controller: root.controller
                regionId: root.selectedRegionId
                regionData: root.selectedRegionId ? root._regionData(root.selectedRegionId) : null
            }

            Label { text: "CONTACTS"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }

            ListView {
                id: contactList
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(90, count * 26)
                clip: true
                model: root.controller ? root.controller.contactListModel : null
                delegate: ItemDelegate {
                    width: ListView.view ? ListView.view.width : 0
                    height: 26
                    highlighted: model.contactId === root.selectedContactId
                    onClicked: root.selectedContactId = model.contactId
                    contentItem: Item {
                        anchors.fill: parent
                        Row {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 6
                            spacing: 8
                            Text {
                                text: model.name; color: Theme.text; font.pixelSize: 12
                                width: 70; height: 18; verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            Text {
                                text: "(" + model.edge + ")"; color: Theme.textDim; font.pixelSize: 10
                                width: 60; height: 18; verticalAlignment: Text.AlignVCenter
                            }
                            Text {
                                text: model.voltage.toFixed(2) + " V"; color: Theme.textDim; font.pixelSize: 10
                                width: 60; height: 18; verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    background: Rectangle {
                        color: highlighted ? Theme.accentSoft : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    }
                }
            }

            ContactEditor {
                Layout.fillWidth: true
                controller: root.controller
                contactId: root.selectedContactId
                contactData: root.selectedContactId ? root._contactData(root.selectedContactId) : null
            }

            Label { text: "GATES"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }

            ListView {
                id: gateList
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(60, count * 26)
                clip: true
                model: root.controller ? root.controller.gateListModel : null
                delegate: ItemDelegate {
                    width: ListView.view ? ListView.view.width : 0
                    height: 26
                    highlighted: model.gateId === root.selectedGateId
                    onClicked: root.selectedGateId = model.gateId
                    contentItem: Item {
                        anchors.fill: parent
                        Row {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 6
                            spacing: 8
                            Text {
                                text: model.name; color: Theme.text; font.pixelSize: 12
                                width: 70; height: 18; verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            Text {
                                text: model.vfbMode; color: Theme.textDim; font.pixelSize: 10
                                width: 60; height: 18; verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    background: Rectangle {
                        color: highlighted ? Theme.accentSoft : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    }
                }
            }

            GateEditor {
                Layout.fillWidth: true
                controller: root.controller
                gateId: root.selectedGateId
                gateData: root.selectedGateId ? root._gateData(root.selectedGateId) : null
            }

            ValidationPanel { controller: root.controller; Layout.fillWidth: true }
        }
    }
}
