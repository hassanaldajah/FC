// FC: the hexagon, drawn on the GPU with Qt Quick.
// True liquid glass: the desktop behind is blurred and saturated, a light
// translucent fill sits on top, every pane has a bright top-left edge and a
// soft dark bottom-right edge, and one large shadow floats the cluster.
import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

Item {
    id: root
    width: 400
    height: 424
    focus: true

    readonly property real cx: width / 2
    readonly property real cy: 226
    readonly property real rOut: 175
    readonly property real rIn: 62
    readonly property real gap: 6                // equal gap between every pane
    readonly property real corner: 4             // crisp, slightly softened corners everywhere
    readonly property real rFrame: rOut + 11     // glass frame around the panes
    readonly property bool calm: backend.reducedMotion
    readonly property int sideCount: 8           // an octagon with a flat top: eight tool panes
    readonly property real stepDeg: 360 / sideCount
    // clockwise from the top pane: the order keys and focus move in
    readonly property var ring: [0, 1, 2, 3, 4, 5, 6, 7]

    property int hover: -1          // pane under the mouse or keyboard, -2 = centre
    property int focusIdx: -1       // keyboard focus (-2 = centre, -10.. = buttons)
    property bool focusVisible: false
    property real mx: 0             // mouse over the hexagon, -1 .. 1 (eased)
    property real my: 0
    Behavior on mx { enabled: !root.calm; SpringAnimation { spring: 2.2; damping: 0.9; epsilon: 0.0005 } }
    Behavior on my { enabled: !root.calm; SpringAnimation { spring: 2.2; damping: 0.9; epsilon: 0.0005 } }

    // ---------------------------------------------------------------- geometry
    function cornerPt(k, r) {
        var a = (stepDeg * k - 90 - stepDeg / 2) * Math.PI / 180
        return Qt.point(cx + r * Math.cos(a), cy + r * Math.sin(a))
    }
    function midAngle(k) { return (stepDeg * k - 90) * Math.PI / 180 }
    function mix(a, b, t) {         // blend two colours, alpha included
        return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, a.a + (b.a - a.a) * t)
    }
    function polyPoints(r) { var p = []; for (var k = 0; k < sideCount; k++) p.push(cornerPt(k, r)); return p }
    // move every edge of a convex polygon inwards by d (exact, so gaps are equal)
    function inset(pts, d) {
        var n = pts.length, c = Qt.point(0, 0)
        for (var i = 0; i < n; i++) { c.x += pts[i].x / n; c.y += pts[i].y / n }
        var lines = []
        for (i = 0; i < n; i++) {
            var a = pts[i], b = pts[(i + 1) % n]
            var ex = b.x - a.x, ey = b.y - a.y, len = Math.hypot(ex, ey)
            var nx = -ey / len, ny = ex / len
            if ((c.x - a.x) * nx + (c.y - a.y) * ny < 0) { nx = -nx; ny = -ny }
            lines.push({ x: a.x + nx * d, y: a.y + ny * d, dx: ex, dy: ey })
        }
        var out = []
        for (i = 0; i < n; i++) {
            var l1 = lines[(i + n - 1) % n], l2 = lines[i]
            var den = l1.dx * l2.dy - l1.dy * l2.dx
            var t = ((l2.x - l1.x) * l2.dy - (l2.y - l1.y) * l2.dx) / den
            out.push(Qt.point(l1.x + l1.dx * t, l1.y + l1.dy * t))
        }
        return out
    }
    function wedge(k) {
        return inset([cornerPt(k, rIn), cornerPt(k, rOut), cornerPt(k + 1, rOut), cornerPt(k + 1, rIn)], gap / 2)
    }
    function hubPoints() { return inset(polyPoints(rIn), gap / 2) }
    // rounded-corner outline as an SVG path, plus the straight edges between corners
    function cornerCut(pts, i, rad) {
        var n = pts.length, p = pts[i], a = pts[(i + n - 1) % n], b = pts[(i + 1) % n]
        var la = Math.hypot(a.x - p.x, a.y - p.y), lb = Math.hypot(b.x - p.x, b.y - p.y)
        var ra = Math.min(rad / la, 0.45), rb = Math.min(rad / lb, 0.45)
        return { from: Qt.point(p.x + (a.x - p.x) * ra, p.y + (a.y - p.y) * ra),
                 to: Qt.point(p.x + (b.x - p.x) * rb, p.y + (b.y - p.y) * rb), p: p }
    }
    function rounded(pts, rad) {
        var d = ""
        for (var i = 0; i < pts.length; i++) {
            var c = cornerCut(pts, i, rad)
            d += (i === 0 ? "M " : "L ") + c.from.x + " " + c.from.y + " Q " + c.p.x + " " + c.p.y + " " + c.to.x + " " + c.to.y + " "
        }
        return d + "Z"
    }
    // edges that face the light (top-left) or face away from it (bottom-right)
    function edges(pts, rad, lit) {
        var n = pts.length, d = "", cxm = 0, cym = 0
        for (var j = 0; j < n; j++) { cxm += pts[j].x / n; cym += pts[j].y / n }
        for (var i = 0; i < n; i++) {
            var c1 = cornerCut(pts, i, rad), c2 = cornerCut(pts, (i + 1) % n, rad)
            var mxe = (c1.to.x + c2.from.x) / 2 - cxm, mye = (c1.to.y + c2.from.y) / 2 - cym
            var facing = (-mxe - mye)            // > 0: towards the top-left light
            if ((lit && facing > 0) || (!lit && facing < 0))
                d += "M " + c1.to.x + " " + c1.to.y + " L " + c2.from.x + " " + c2.from.y + " "
        }
        return d === "" ? "M 0 0" : d
    }
    function indexAt(x, y) {
        var dx = x - cx, dy = y - cy, d = Math.hypot(dx, dy)
        if (d < rIn) return -2
        if (d > rFrame) return -1
        var ang = (Math.atan2(dy, dx) * 180 / Math.PI + 90 + stepDeg / 2 + 360) % 360
        var k = Math.floor(ang / stepDeg)
        return k < backend.options.length ? k : -1
    }

    // ---------------------------------------------------------------- open / close
    Connections {
        target: backend
        function onOpenRequested() {
            root.hover = -1
            stage.opacity = 1
            if (backend.firstOpen && !root.calm) {
                intro.restart()
                for (var j = 0; j < sides.count; j++) sides.itemAt(j).bloomIn(j, 180, 60)
            } else {
                hub.introT = 1
                for (var i = 0; i < sides.count; i++) sides.itemAt(i).bloomIn(i, 0, 25)
            }
            hub.pulse()
            backend.opened()
        }
        function onCloseRequested(kind) {
            root.hover = -1
            for (var i = 0; i < sides.count; i++) sides.itemAt(i).bloomOut()
            closeTimer.kind = kind
            closeTimer.interval = root.calm ? 10 : 210
            closeTimer.restart()
        }
        function onOptionsReplaced() { for (var i = 0; i < sides.count; i++) sides.itemAt(i).appearFrom(i) }
    }
    Timer {
        id: closeTimer
        property string kind: "min"
        onTriggered: { stage.opacity = 0; backend.closeDone(kind) }
    }

    // the opening: centre pops in, a wave of light, then a sheen across the glass
    property real waveT: 0
    property real sweepT: 0
    SequentialAnimation {
        id: intro
        ScriptAction { script: { hub.introT = 0; root.waveT = 0; root.sweepT = 0 } }
        ParallelAnimation {
            NumberAnimation { target: hub; property: "introT"; from: 0; to: 1; duration: 820; easing.type: Easing.OutQuint }
            SequentialAnimation {
                PauseAnimation { duration: 140 }
                NumberAnimation { target: root; property: "waveT"; from: 0; to: 1; duration: 950; easing.type: Easing.OutQuart }
            }
            SequentialAnimation {
                PauseAnimation { duration: 760 }
                NumberAnimation { target: root; property: "sweepT"; from: 0; to: 1; duration: 950; easing.type: Easing.InOutSine }
            }
        }
    }

    // one large, soft, low shadow under the whole cluster
    Item {
        id: shadowSrc
        anchors.fill: parent
        visible: false
        layer.enabled: true
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { fillColor: "black"; strokeColor: "transparent"; PathSvg { path: root.rounded(root.polyPoints(root.rFrame), root.corner) } }
        }
    }
    MultiEffect {
        width: parent.width
        height: parent.height
        y: 18
        source: shadowSrc
        opacity: 0.32 * stage.opacity
        blurEnabled: true
        blur: 1.0
        blurMax: 40
    }

    Item {
        id: stage
        anchors.fill: parent
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: root.calm ? 0 : 140 } }
        transform: [
            Rotation { origin.x: root.cx; origin.y: root.cy; axis { x: 1; y: 0; z: 0 } angle: root.calm ? 0 : -5 * root.my },
            Rotation { origin.x: root.cx; origin.y: root.cy; axis { x: 0; y: 1; z: 0 } angle: root.calm ? 0 : 5 * root.mx }
        ]

        // ------------------------------------------------ frosted, saturated desktop behind
        Item {
            id: desk
            anchors.fill: parent
            visible: false
            Image { x: -backend.winX; y: -backend.winY; source: backend.shotUrl; cache: false; smooth: true }
        }
        Item {
            id: glassMask
            anchors.fill: parent
            visible: false
            layer.enabled: true
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath { fillColor: "white"; strokeColor: "transparent"; PathSvg { path: root.rounded(root.polyPoints(root.rFrame), root.corner) } }
            }
        }
        MultiEffect {
            anchors.fill: parent
            source: desk
            visible: backend.shotUrl !== ""
            blurEnabled: true
            blur: 1.0
            autoPaddingEnabled: false  // keep the mask exactly on the panes
            blurMax: 10                // light frosting: what is behind stays recognisable
            saturation: 0.3
            maskEnabled: true
            maskSource: glassMask
        }

        // ------------------------------------------------ the glass frame around the panes
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {                                   // dark tray so the frame reads on any wallpaper
                strokeColor: "transparent"
                fillColor: Qt.rgba(0.04, 0.06, 0.12, 0.10)
                PathSvg { path: root.rounded(root.polyPoints(root.rFrame), root.corner) }
            }
            ShapePath {                                   // bright outer rim
                fillColor: "transparent"
                strokeColor: Qt.rgba(1, 1, 1, 0.55)
                strokeWidth: 1.5
                PathSvg { path: root.rounded(root.polyPoints(root.rFrame - 0.75), root.corner) }
            }
            ShapePath {                                   // the logo's colours, running round the glass edge
                strokeColor: "transparent"
                fillRule: ShapePath.OddEvenFill
                fillGradient: LinearGradient {
                    x1: root.cx - root.rFrame; y1: root.cy + root.rFrame
                    x2: root.cx + root.rFrame; y2: root.cy - root.rFrame
                    GradientStop { position: 0.0; color: Qt.rgba(0.95, 0.35, 0.95, 0.85) }
                    GradientStop { position: 0.5; color: Qt.rgba(0.35, 0.85, 1.0, 0.80) }
                    GradientStop { position: 1.0; color: Qt.rgba(0.25, 0.9, 0.55, 0.85) }
                }
                PathSvg { path: root.rounded(root.polyPoints(root.rFrame), root.corner) + " " + root.rounded(root.polyPoints(root.rFrame - 2.2), root.corner) }
            }
            ShapePath {                                   // soft inner line, gives the rim depth
                fillColor: "transparent"
                strokeColor: Qt.rgba(1, 1, 1, 0.14)
                strokeWidth: 1
                PathSvg { path: root.rounded(root.polyPoints(root.rFrame - 4), root.corner) }
            }
        }

        // ------------------------------------------------ the eight panes
        Repeater {
            id: sides
            model: root.sideCount
            delegate: Item {
                id: side
                required property int index
                property bool active: index < backend.options.length
                property var opt: active ? backend.options[index]
                                         : ({ "label": "", "icon": "", "group": false, "color": "#8e8e93" })
                property color tint: opt.color
                property real pop: (root.hover === index && active) ? 1 : 0
                Behavior on pop { enabled: !root.calm; SpringAnimation { spring: 4.2; damping: 0.62; epsilon: 0.0008 } }
                property real bloom: 0                 // 0 = folded into the centre, 1 = in place
                property real appear: 1
                function bloomIn(i, delay, stagger) {
                    bloomAnim.stop(); collapseAnim.stop()
                    if (root.calm) { bloom = 1; return }
                    var order = root.ring.indexOf(index)          // clockwise from the top-left
                    bloom = 0; bloomPause.duration = delay + Math.max(0, order) * stagger; bloomAnim.start()
                }
                function bloomOut() {
                    bloomAnim.stop()
                    if (root.calm) { bloom = 0; return }
                    collapseAnim.start()
                }
                function appearFrom(i) {
                    appearAnim.stop()
                    if (root.calm) { appear = 1; return }
                    appear = 0; appearPause.duration = i * 25; appearAnim.start()
                }
                SequentialAnimation {
                    id: bloomAnim
                    PauseAnimation { id: bloomPause; duration: 0 }
                    // smooth glide into place, no bounce
                    NumberAnimation { target: side; property: "bloom"; to: 1; duration: 560; easing.type: Easing.OutQuint }
                }
                NumberAnimation { id: collapseAnim; target: side; property: "bloom"; to: 0; duration: 180; easing.type: Easing.InCubic }
                SequentialAnimation {
                    id: appearAnim
                    PauseAnimation { id: appearPause; duration: 0 }
                    NumberAnimation { target: side; property: "appear"; to: 1; duration: 300; easing.type: Easing.OutCubic }
                }

                readonly property real m: root.midAngle(index)
                readonly property point centroid: Qt.point(root.cx + (root.rOut + root.rIn) / 2 * Math.cos(m),
                                                           root.cy + (root.rOut + root.rIn) / 2 * Math.sin(m))
                readonly property var pts: root.wedge(index)
                anchors.fill: parent
                z: pop > 0.01 ? 2 : 1
                opacity: Math.max(0.004, Math.min(1, bloom * 1.4))   // never 0: drawn (invisibly) during warm-up
                transform: [
                    // bloom: grow out of the centre of the cluster
                    Scale { origin.x: root.cx; origin.y: root.cy; xScale: 0.35 + 0.65 * side.bloom; yScale: xScale },
                    // hover: lift towards the viewer, a little bigger, slightly outwards
                    Rotation {
                        origin.x: side.centroid.x; origin.y: side.centroid.y
                        axis { x: -Math.sin(side.m); y: Math.cos(side.m); z: 0 }
                        angle: root.calm ? 0 : 10 * side.pop
                    },
                    Scale { origin.x: side.centroid.x; origin.y: side.centroid.y; xScale: 1 + 0.06 * side.pop; yScale: xScale },
                    Translate { x: 7 * side.pop * Math.cos(side.m); y: 7 * side.pop * Math.sin(side.m) - 2 * side.pop }
                ]

                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    // dark base under the glass: keeps white text readable on any wallpaper
                    ShapePath {
                        strokeColor: "transparent"
                        fillColor: Qt.rgba(0.04, 0.06, 0.12, side.active ? 0.10 + 0.12 * side.pop : 0.06)
                        PathSvg { path: root.rounded(side.pts, root.corner) }
                    }
                    // light translucent glass (10-18%)
                    ShapePath {
                        strokeColor: "transparent"
                        fillGradient: LinearGradient {
                            x1: side.centroid.x - 60; y1: side.centroid.y - 60; x2: side.centroid.x + 60; y2: side.centroid.y + 60
                            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, side.active ? 0.10 + 0.06 * side.pop : 0.05) }
                            GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, side.active ? 0.04 + 0.06 * side.pop : 0.02) }
                        }
                        PathSvg { path: root.rounded(side.pts, root.corner) }
                    }
                    // all glass; the pane takes its icon's colour only on hover
                    ShapePath {
                        strokeColor: "transparent"
                        fillColor: Qt.rgba(side.tint.r, side.tint.g, side.tint.b, side.active ? 0.34 * side.pop : 0)
                        PathSvg { path: root.rounded(side.pts, root.corner) }
                    }
                    // 1px bright edge facing the light, faint dark edge facing away
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(1, 1, 1, side.active ? 0.62 + 0.3 * side.pop : 0.25)
                        strokeWidth: 1
                        capStyle: ShapePath.RoundCap
                        PathSvg { path: root.edges(side.pts, root.corner, true) }
                    }
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(0, 0, 0, 0.30)
                        strokeWidth: 1
                        capStyle: ShapePath.RoundCap
                        PathSvg { path: root.edges(side.pts, root.corner, false) }
                    }
                    // hairline around the whole pane so the corners read clearly
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(1, 1, 1, side.active ? 0.14 : 0.06)
                        strokeWidth: 1
                        PathSvg { path: root.rounded(side.pts, root.corner) }
                    }
                    // keyboard focus ring
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: (root.focusVisible && root.focusIdx === side.index) ? "#ffffff" : "transparent"
                        strokeWidth: 2
                        PathSvg { path: root.rounded(root.inset(side.pts, -3), root.corner + 2) }
                    }
                }

                // icon + label
                Column {
                    visible: side.active
                    spacing: 3
                    opacity: Math.max(0.004, side.appear)   // never 0: the label halo is built during warm-up, not mid-animation
                    readonly property real rr: (root.rIn + root.rOut) / 2 - 4 + (1 - side.appear) * 12
                    x: Math.round(root.cx + rr * Math.cos(side.m) - width / 2)     // whole pixels keep the edges crisp
                    y: Math.round(root.cy + rr * Math.sin(side.m) - height / 2)
                    scale: 1 + 0.08 * side.pop
                    transformOrigin: Item.Center
                    Rectangle {                     // crisp graphite tile, filled with colour on hover
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 34; height: 34
                        radius: 7
                        antialiasing: true
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: root.mix(Qt.rgba(0.24, 0.25, 0.29, 0.96), Qt.lighter(side.tint, 1.18), side.pop) }
                            GradientStop { position: 1.0; color: root.mix(Qt.rgba(0.12, 0.13, 0.16, 0.96), side.tint, side.pop) }
                        }
                        border.color: Qt.rgba(1, 1, 1, 0.55 + 0.30 * side.pop)
                        border.width: 1
                        Rectangle {                 // thin bright line along the top edge: a sharp bevel
                            x: 7; y: 1; width: parent.width - 14; height: 1
                            color: Qt.rgba(1, 1, 1, 0.45)
                        }
                        Image {
                            anchors.centerIn: parent
                            source: side.opt.icon
                            sourceSize.width: 48; sourceSize.height: 48      // drawn at 2x and scaled down: sharp lines
                            width: 22; height: 22
                            smooth: true
                            mipmap: true
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 84
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: side.opt.label + (side.opt.group ? " ›" : "")
                        font.family: "Segoe UI Variable Display"
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        color: "white"
                        // soft dark halo so labels read on bright wallpapers through the clear glass;
                        // the text never changes while hovering, so the halo is drawn only once
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            shadowEnabled: true
                            shadowColor: "black"
                            shadowBlur: 0.55
                            shadowOpacity: 0.9
                            shadowVerticalOffset: 1
                            shadowHorizontalOffset: 0
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ light that follows the cursor
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            opacity: root.calm ? 0.5 : 0.5 + 0.5 * Math.min(1, Math.hypot(root.mx, root.my) * 2)
            ShapePath {
                strokeColor: "transparent"
                fillGradient: RadialGradient {
                    centerX: root.cx + root.mx * root.rOut * 0.8
                    centerY: root.cy + root.my * root.rOut * 0.8
                    centerRadius: root.rOut * 0.8
                    focalX: centerX; focalY: centerY
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.14) }
                    GradientStop { position: 0.6; color: Qt.rgba(1, 1, 1, 0.03) }
                    GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.0) }
                }
                PathSvg { path: root.rounded(root.polyPoints(root.rOut), root.corner) }
            }
        }

        // ------------------------------------------------ opening wave and sheen
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            // kept faintly drawn (never fully hidden) so its first frame costs nothing
            opacity: root.waveT > 0 && root.waveT < 1 ? 1 - root.waveT : 0.004
            transform: Scale { origin.x: root.cx; origin.y: root.cy; xScale: 0.4 + 0.75 * root.waveT; yScale: xScale }
            ShapePath {
                fillColor: "transparent"
                strokeColor: Qt.rgba(1, 1, 1, 0.75)
                strokeWidth: 2
                PathSvg { path: root.rounded(root.polyPoints(root.rOut), root.corner) }
            }
        }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            opacity: root.sweepT > 0 && root.sweepT < 1 ? 1 : 0.004
            ShapePath {
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: root.cx - root.rOut - 120 + root.sweepT * (2 * root.rOut + 240)
                    y1: root.cy - root.rOut
                    x2: x1 + 140
                    y2: root.cy + root.rOut * 0.4
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0) }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.22) }
                    GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0) }
                }
                PathSvg { path: root.rounded(root.polyPoints(root.rOut), root.corner) }
            }
        }

        // ------------------------------------------------ centre drop zone
        Item {
            id: hub
            anchors.fill: parent
            property real glow: root.hover === -2 ? 1 : 0
            property real breathe: 0
            property real dropScale: backend.dropActive ? 1.05 : 1.0
            property real introT: 1
            Behavior on glow { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Behavior on dropScale { enabled: !root.calm; SpringAnimation { spring: 4; damping: 0.55 } }
            function pulse() { if (!root.calm) breatheAnim.restart() }
            SequentialAnimation on breathe {
                id: breatheAnim
                loops: Animation.Infinite
                running: !root.calm
                NumberAnimation { from: 0; to: 1; duration: 1800; easing.type: Easing.InOutSine }
                NumberAnimation { from: 1; to: 0; duration: 1800; easing.type: Easing.InOutSine }
            }
            opacity: Math.min(1, hub.introT * 1.5)
            transform: [
                Rotation { origin.x: root.cx; origin.y: root.cy; angle: (1 - hub.introT) * -25 },
                Scale { origin.x: root.cx; origin.y: root.cy; xScale: hub.dropScale * (0.3 + 0.7 * hub.introT); yScale: xScale }
            ]

            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillColor: Qt.rgba(0.04, 0.06, 0.12, 0.22)
                    PathSvg { path: root.rounded(root.hubPoints(), root.corner) }
                }
                ShapePath {
                    strokeColor: Qt.rgba(1, 1, 1, backend.dropActive ? 0.95 : 0.40 + 0.25 * hub.glow)
                    strokeWidth: backend.dropActive ? 1.8 : 1
                    fillColor: Qt.rgba(1, 1, 1, 0.12 + 0.08 * hub.glow + (backend.dropActive ? 0.12 : 0))
                    PathSvg { path: root.rounded(root.hubPoints(), root.corner) }
                }
                // faint dashed inner ring that breathes: "drop here"
                ShapePath {
                    fillColor: "transparent"
                    strokeColor: Qt.rgba(1, 1, 1, backend.dropActive ? 0.9 : 0.22 + 0.28 * hub.breathe)
                    strokeWidth: 1
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [3, 3]
                    PathSvg { path: root.rounded(root.inset(root.hubPoints(), 7), root.corner - 3) }
                }
                ShapePath {
                    fillColor: "transparent"
                    strokeColor: (root.focusVisible && root.focusIdx === -2) ? "#ffffff" : "transparent"
                    strokeWidth: 2
                    PathSvg { path: root.rounded(root.inset(root.hubPoints(), -3), root.corner + 2) }
                }
            }
            // the FC letters from the logo (no tile), lifted off the hub by a soft shadow
            Image {
                id: badge
                source: backend.logoUrl
                width: Math.max(26, Math.min(46, 72 - words.height))     // smaller when the text under it is long
                height: width * 539 / 533
                x: root.cx - width / 2
                // letters and the text under them are centred as one group in the hub
                y: root.cy - (height + 4 + words.height) / 2
                Behavior on y { enabled: !root.calm; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                smooth: true
                mipmap: true
                sourceSize.width: 240
                scale: 1 + 0.025 * hub.breathe + 0.07 * hub.glow + (backend.dropActive ? 0.08 : 0)
                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#000000"
                    shadowOpacity: 0.6
                    shadowBlur: 0.9
                    shadowVerticalOffset: 4
                }
            }
            Column {
                id: words
                x: root.cx - width / 2
                y: badge.y + badge.height + 4
                width: 80
                spacing: 0
                Text {
                    width: parent.width
                    visible: backend.dropActive || !backend.atHome
                    horizontalAlignment: Text.AlignHCenter
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    text: backend.dropActive ? "Release to convert" : backend.title
                    font.family: "Segoe UI Variable Display"
                    font.pixelSize: backend.dropActive ? 11 : 12
                    font.weight: Font.Bold
                    color: "white"
                    elide: Text.ElideRight
                    maximumLineCount: 2
                }
                Text {
                    width: parent.width
                    visible: !backend.dropActive
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: backend.flash !== "" ? backend.flash : (backend.canGoBack ? "‹ Back" : "Drop files here")
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    color: Qt.rgba(1, 1, 1, 0.86)
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
            }
        }
    }

    // ---------------------------------------------------------------- window controls (on hover)
    HoverHandler {
        id: windowHover
        onHoveredChanged: if (hovered) backend.refreshGlass()   // what is behind may have changed
    }
    Row {
        id: controls
        x: root.cx + 72
        y: root.cy - root.rFrame - 30
        spacing: 8
        opacity: (windowHover.hovered || (root.focusVisible && root.focusIdx <= -10)) ? stage.opacity : 0
        Behavior on opacity { NumberAnimation { duration: root.calm ? 0 : 160 } }
        Repeater {
            model: [{ "icon": backend.iconDir + "minus.svg", "act": "min" },
                    { "icon": backend.iconDir + "x.svg", "act": "quit" }]
            delegate: Item {
                id: btn
                required property var modelData
                required property int index
                width: 28; height: 28
                property bool over: area.containsMouse
                property bool keyFocus: root.focusVisible && root.focusIdx === -10 - index
                Rectangle {
                    anchors.fill: parent
                    radius: 14
                    color: btn.over ? (btn.modelData.act === "quit" ? Qt.rgba(0.85, 0.16, 0.22, 0.95) : Qt.rgba(1, 1, 1, 0.28))
                                    : Qt.rgba(0.04, 0.06, 0.12, 0.6)
                    border.color: btn.keyFocus ? "#ffffff" : Qt.rgba(1, 1, 1, 0.45)
                    border.width: btn.keyFocus ? 2 : 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                    scale: area.pressed ? 0.9 : (btn.over ? 1.08 : 1)
                    Behavior on scale { enabled: !root.calm; SpringAnimation { spring: 5; damping: 0.45 } }
                }
                Image {
                    anchors.centerIn: parent
                    source: btn.modelData.icon
                    sourceSize.width: 15; sourceSize.height: 15
                    width: 15; height: 15
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.control(btn.modelData.act)
                }
            }
        }
    }
    function control(act) {
        if (act === "quit") backend.quit()
        else if (act === "min") backend.minimize()
        else backend.help()
    }

    // ---------------------------------------------------------------- mouse
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        z: -1
        property point pressAt
        property bool moved: false
        onPositionChanged: function (e) {
            root.focusVisible = false
            root.mx = Math.max(-1, Math.min(1, (e.x - root.cx) / root.rOut))
            root.my = Math.max(-1, Math.min(1, (e.y - root.cy) / root.rOut))
            if (pressed && root.indexAt(pressAt.x, pressAt.y) === -2) {
                if (!moved && Math.hypot(e.x - pressAt.x, e.y - pressAt.y) > 5) { moved = true; backend.startMove() }
                return
            }
            root.hover = root.indexAt(e.x, e.y)
        }
        onExited: { root.hover = -1; root.mx = 0; root.my = 0 }
        onPressed: function (e) { pressAt = Qt.point(e.x, e.y); moved = false }
        onReleased: function (e) {
            var k = root.indexAt(e.x, e.y)
            if (moved) return
            if (k === -2) backend.back()
            else if (k >= 0) backend.pick(k)
        }
        onWheel: function (w) { root.step(w.angleDelta.y > 0 ? -1 : 1) }
        cursorShape: root.hover >= 0 ? Qt.PointingHandCursor : (root.hover === -2 ? Qt.SizeAllCursor : Qt.ArrowCursor)
    }
    DropArea {
        anchors.fill: parent
        onEntered: function (d) { if (d.hasUrls) backend.setDropActive(true) }
        onExited: backend.setDropActive(false)
        onDropped: function (d) { backend.setDropActive(false); backend.dropUrls(d.urls) }
    }

    // ---------------------------------------------------------------- keyboard
    // arrows move clockwise around the panes; Tab also reaches the centre and buttons
    function step(dir) {
        var n = backend.options.length
        if (!n) return
        var order = ring.filter(function (k) { return k < n })
        var at = order.indexOf(root.focusIdx)
        var next = order[((at < 0 ? (dir > 0 ? -1 : 0) : at) + dir + order.length) % order.length]
        root.focusIdx = next
        root.hover = next
        root.focusVisible = true
    }
    function tabStop(dir) {
        var n = backend.options.length
        var stops = ring.filter(function (k) { return k < n }).concat([-2, -10, -11])
        var at = stops.indexOf(root.focusIdx)
        root.focusIdx = stops[((at < 0 ? -1 : at) + dir + stops.length) % stops.length]
        root.hover = (root.focusIdx >= 0 || root.focusIdx === -2) ? root.focusIdx : -1
        root.focusVisible = true
    }
    function activate() {
        if (root.focusIdx >= 0) backend.pick(root.focusIdx)
        else if (root.focusIdx === -2) backend.back()
        else if (root.focusIdx === -10) control("min")
        else if (root.focusIdx === -11) control("quit")
    }
    Keys.onPressed: function (e) {
        if (e.key === Qt.Key_Right || e.key === Qt.Key_Down) { step(1); e.accepted = true }
        else if (e.key === Qt.Key_Left || e.key === Qt.Key_Up) { step(-1); e.accepted = true }
        else if (e.key === Qt.Key_Tab) { tabStop(1); e.accepted = true }
        else if (e.key === Qt.Key_Backtab) { tabStop(-1); e.accepted = true }
        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) { activate(); e.accepted = true }
        else if (e.key === Qt.Key_Escape) backend.escape()
        else if (e.key === Qt.Key_Backspace) backend.back()
        else if (e.key === Qt.Key_F1) backend.help()
        else if (e.key >= Qt.Key_1 && e.key <= Qt.Key_8) {
            var k = ring[e.key - Qt.Key_1]
            if (k < backend.options.length) backend.pick(k)
        }
    }
}
