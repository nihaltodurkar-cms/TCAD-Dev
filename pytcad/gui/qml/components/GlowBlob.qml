import QtQuick
import QtQuick.Shapes

// A soft radial "glow" using QtQuick.Shapes' native RadialGradient --
// a real smooth gradient fill (vector rasterization, not a layer
// effect), not a live backdrop blur and not the earlier v3.1 flat
// disc / v3.2-draft concentric-rings approximation (which showed
// visible ring banding on a real display -- confirmed by looking at
// it, not assumed). QtQuick has no cheap LIVE blur of arbitrary sibling
// content (see Main.qml's own note on why a MultiEffect blur was
// reverted after it made dock content invisible on a real,
// non-offscreen display), but a radial-gradient FILL needs no blur at
// all -- it is smooth by construction.
//
// `color`'s own alpha channel is the blob's PEAK (center) alpha; it
// fades to fully transparent at the item's edge.
Shape {
    id: root
    property color color: "violet"
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
        fillColor: "transparent"
        strokeColor: "transparent"
        strokeWidth: -1
        fillGradient: RadialGradient {
            centerX: root.width / 2
            centerY: root.height / 2
            centerRadius: root.width / 2
            focalX: centerX
            focalY: centerY
            focalRadius: 0
            GradientStop { position: 0.0; color: Qt.rgba(root.color.r, root.color.g, root.color.b, root.color.a) }
            GradientStop { position: 0.45; color: Qt.rgba(root.color.r, root.color.g, root.color.b, root.color.a * 0.55) }
            GradientStop { position: 1.0; color: Qt.rgba(root.color.r, root.color.g, root.color.b, 0.0) }
        }
        startX: 0
        startY: 0
        PathLine { x: root.width; y: 0 }
        PathLine { x: root.width; y: root.height }
        PathLine { x: 0; y: root.height }
        PathLine { x: 0; y: 0 }
    }
}
