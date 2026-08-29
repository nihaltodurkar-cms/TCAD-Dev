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
            objectName: "regionDopingField"
            Layout.fillWidth: true
            enabled: !regionData || regionData.dopingProfile === "uniform"
            text: regionData ? regionData.doping.toExponential(3) : ""
            onEditingFinished: if (regionId) controller.setRegionDoping(regionId, parseFloat(text))
        }
    }

    // Per-region doping PROFILE, beyond uniform: "uniform" (the flat
    // ND/NA field above, unaffected) or "gaussian_erfc" -- reuses
    // mosfet_doping()'s own Gaussian-in-depth x erfc-lateral-rolloff
    // shape (pytcad/mosfet.py _sd_profile) as a region option, straggle
    // measured from THIS region's own y_min (see rasterize_doping).
    RowLayout {
        Label { text: "Profile"; color: Theme.textDim; Layout.preferredWidth: 90 }
        ComboBox {
            id: profileBox
            objectName: "regionProfileBox"
            Layout.fillWidth: true
            model: ["uniform", "gaussian_erfc"]
            currentIndex: regionData && regionData.dopingProfile === "gaussian_erfc" ? 1 : 0
            onActivated: if (regionId) controller.setRegionDopingProfile(
                regionId, model[currentIndex],
                peakField.text ? parseFloat(peakField.text) : 0.0,
                sigmaYField.text ? parseFloat(sigmaYField.text) : 0.0,
                sigmaLatField.text ? parseFloat(sigmaLatField.text) : 0.0,
                edgeXField.text ? parseFloat(edgeXField.text) : 0.0,
                highSideBox.currentText)
        }
    }

    ColumnLayout {
        visible: profileBox.currentIndex === 1
        Layout.fillWidth: true

        RowLayout {
            Label { text: "Peak [cm^-3]"; color: Theme.textDim; Layout.preferredWidth: 90 }
            TextField {
                id: peakField
                objectName: "regionProfilePeakField"
                Layout.fillWidth: true
                text: regionData && regionData.profilePeak !== null && regionData.profilePeak !== undefined
                      ? regionData.profilePeak.toExponential(3) : ""
                onEditingFinished: if (regionId) controller.setRegionDopingProfile(
                    regionId, "gaussian_erfc", parseFloat(text),
                    sigmaYField.text ? parseFloat(sigmaYField.text) : 0.0,
                    sigmaLatField.text ? parseFloat(sigmaLatField.text) : 0.0,
                    edgeXField.text ? parseFloat(edgeXField.text) : 0.0,
                    highSideBox.currentText)
            }
        }
        RowLayout {
            Label { text: "sigma_y [cm]"; color: Theme.textDim; Layout.preferredWidth: 90 }
            TextField {
                id: sigmaYField
                objectName: "regionProfileSigmaYField"
                Layout.fillWidth: true
                text: regionData && regionData.profileSigmaY !== null && regionData.profileSigmaY !== undefined
                      ? regionData.profileSigmaY.toExponential(3) : ""
                onEditingFinished: if (regionId) controller.setRegionDopingProfile(
                    regionId, "gaussian_erfc",
                    peakField.text ? parseFloat(peakField.text) : 0.0,
                    parseFloat(text),
                    sigmaLatField.text ? parseFloat(sigmaLatField.text) : 0.0,
                    edgeXField.text ? parseFloat(edgeXField.text) : 0.0,
                    highSideBox.currentText)
            }
        }
        RowLayout {
            Label { text: "sigma_lat [cm]"; color: Theme.textDim; Layout.preferredWidth: 90 }
            TextField {
                id: sigmaLatField
                objectName: "regionProfileSigmaLatField"
                Layout.fillWidth: true
                text: regionData && regionData.profileSigmaLat !== null && regionData.profileSigmaLat !== undefined
                      ? regionData.profileSigmaLat.toExponential(3) : ""
                onEditingFinished: if (regionId) controller.setRegionDopingProfile(
                    regionId, "gaussian_erfc",
                    peakField.text ? parseFloat(peakField.text) : 0.0,
                    sigmaYField.text ? parseFloat(sigmaYField.text) : 0.0,
                    parseFloat(text),
                    edgeXField.text ? parseFloat(edgeXField.text) : 0.0,
                    highSideBox.currentText)
            }
        }
        RowLayout {
            Label { text: "edge_x [cm]"; color: Theme.textDim; Layout.preferredWidth: 90 }
            TextField {
                id: edgeXField
                objectName: "regionProfileEdgeXField"
                Layout.fillWidth: true
                text: regionData && regionData.profileEdgeX !== null && regionData.profileEdgeX !== undefined
                      ? regionData.profileEdgeX.toExponential(3) : ""
                onEditingFinished: if (regionId) controller.setRegionDopingProfile(
                    regionId, "gaussian_erfc",
                    peakField.text ? parseFloat(peakField.text) : 0.0,
                    sigmaYField.text ? parseFloat(sigmaYField.text) : 0.0,
                    sigmaLatField.text ? parseFloat(sigmaLatField.text) : 0.0,
                    parseFloat(text), highSideBox.currentText)
            }
        }
        RowLayout {
            Label { text: "Full-strength side"; color: Theme.textDim; Layout.preferredWidth: 90 }
            ComboBox {
                id: highSideBox
                objectName: "regionProfileHighSideBox"
                Layout.fillWidth: true
                model: ["left", "right"]
                currentIndex: regionData && regionData.profileHighSide === "right" ? 1 : 0
                onActivated: if (regionId) controller.setRegionDopingProfile(
                    regionId, "gaussian_erfc",
                    peakField.text ? parseFloat(peakField.text) : 0.0,
                    sigmaYField.text ? parseFloat(sigmaYField.text) : 0.0,
                    sigmaLatField.text ? parseFloat(sigmaLatField.text) : 0.0,
                    edgeXField.text ? parseFloat(edgeXField.text) : 0.0,
                    model[currentIndex])
            }
        }
    }
}
