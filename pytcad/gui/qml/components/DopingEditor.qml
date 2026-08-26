import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// For the currently-selected region: name, bounds, and signed net
// doping with a donor/acceptor label derived from its sign -- the
// backend only ever stores one signed number (design spec section 5).
ColumnLayout {
    property var controller
    property string regionId: ""
    property var regionData: null   // {name, bounds:[xmin,xmax,ymin,ymax], doping, material}

    Label { text: "Doping region"; color: Theme.textDim; font.pixelSize: 11 }

    RowLayout {
        Label { text: "Name"; color: Theme.textDim; Layout.preferredWidth: 90 }
        TextField {
            Layout.fillWidth: true
            text: regionData ? regionData.name : ""
            onEditingFinished: if (regionId) controller.renameRegion(regionId, text)
        }
    }

    // M11-S5: per-region material (MaterialLibrary keys; the resolved
    // key is what to_device_spec() emits into region_materials)
    RowLayout {
        Label { text: "Material"; color: Theme.textDim; Layout.preferredWidth: 90 }
        ComboBox {
            id: materialBox
            objectName: "regionMaterialBox"
            Layout.fillWidth: true
            model: controller ? controller.materialNames : []
            displayText: {
                var m = regionData ? regionData.material : ""
                if (!m) return "SILICON"
                for (var i = 0; i < model.length; i++)
                    if (model[i].toUpperCase() === m.toUpperCase())
                        return model[i]
                return m
            }
            onActivated: if (regionId)
                controller.setRegionMaterial(regionId,
                                             model[currentIndex])
        }
    }

    RowLayout {
        Label { text: "x [um]"; color: Theme.textDim; Layout.preferredWidth: 90 }
        SpinBox { id: xMinBox; from: -100000; to: 100000; value: regionData ? Math.round(regionData.bounds[0]*1e7) : 0 }
        Label { text: "to"; color: Theme.textDim }
        SpinBox { id: xMaxBox; from: -100000; to: 100000; value: regionData ? Math.round(regionData.bounds[1]*1e7) : 0 }
    }
    RowLayout {
        Label { text: "y [um]"; color: Theme.textDim; Layout.preferredWidth: 90 }
        SpinBox { id: yMinBox; from: -100000; to: 100000; value: regionData ? Math.round(regionData.bounds[2]*1e7) : 0 }
        Label { text: "to"; color: Theme.textDim }
        SpinBox { id: yMaxBox; from: -100000; to: 100000; value: regionData ? Math.round(regionData.bounds[3]*1e7) : 0 }
    }
    Button {
        text: "Apply bounds"
        onClicked: if (regionId) controller.setRegionBounds(
            regionId, xMinBox.value / 1e7, xMaxBox.value / 1e7,
            yMinBox.value / 1e7, yMaxBox.value / 1e7)
    }

    RowLayout {
        Label { text: regionData && regionData.doping >= 0 ? "ND [cm^-3]" : "NA [cm^-3]"
               color: Theme.textDim; Layout.preferredWidth: 90 }
        TextField {
            id: dopingField
            Layout.fillWidth: true
            text: regionData ? regionData.doping.toExponential(3) : ""
            onEditingFinished: if (regionId) controller.setRegionDoping(regionId, parseFloat(text))
        }
    }
}
