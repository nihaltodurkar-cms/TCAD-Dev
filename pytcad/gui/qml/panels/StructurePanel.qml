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

    function _regionData(id) {
        for (var i = 0; i < controller.regionListModel.rowCount(); i++) {
            var idx = controller.regionListModel.index(i, 0)
            if (controller.regionListModel.data(idx, Qt.UserRole + 1) === id) {
                return {
                    name: controller.regionListModel.data(idx, Qt.UserRole + 2),
                    bounds: controller.regionListModel.data(idx, Qt.UserRole + 3),
                    doping: controller.regionListModel.data(idx, Qt.UserRole + 4),
                    material: controller.regionListModel.data(idx, Qt.UserRole + 6),
                    dopingProfile: controller.regionListModel.data(idx, Qt.UserRole + 7),
                    profilePeak: controller.regionListModel.data(idx, Qt.UserRole + 8),
                    profileSigmaY: controller.regionListModel.data(idx, Qt.UserRole + 9),
                    profileSigmaLat: controller.regionListModel.data(idx, Qt.UserRole + 10),
                    profileEdgeX: controller.regionListModel.data(idx, Qt.UserRole + 11),
                    profileHighSide: controller.regionListModel.data(idx, Qt.UserRole + 12),
                }
            }
        }
        return null
    }

    function _contactData(id) {
        for (var i = 0; i < controller.contactListModel.rowCount(); i++) {
            var idx = controller.contactListModel.index(i, 0)
            if (controller.contactListModel.data(idx, Qt.UserRole + 1) === id) {
                return {
                    name: controller.contactListModel.data(idx, Qt.UserRole + 2),
                    edge: controller.contactListModel.data(idx, Qt.UserRole + 3),
                    voltage: controller.contactListModel.data(idx, Qt.UserRole + 4),
                }
            }
        }
        return null
    }

    function _gateData(id) {
        for (var i = 0; i < controller.gateListModel.rowCount(); i++) {
            var idx = controller.gateListModel.index(i, 0)
            if (controller.gateListModel.data(idx, Qt.UserRole + 1) === id) {
                return {
                    name: controller.gateListModel.data(idx, Qt.UserRole + 2),
                    tox: controller.gateListModel.data(idx, Qt.UserRole + 3),
                    vfbMode: controller.gateListModel.data(idx, Qt.UserRole + 4),
                    vfbValue: controller.gateListModel.data(idx, Qt.UserRole + 5),
                    voltage: controller.gateListModel.data(idx, Qt.UserRole + 6),
                }
            }
        }
        return null
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
