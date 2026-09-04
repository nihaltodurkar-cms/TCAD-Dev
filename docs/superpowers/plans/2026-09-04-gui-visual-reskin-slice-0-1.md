# PyTCAD GUI Visual Reskin — Slice 0+1 (Design System + Shell) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the PyTCAD desktop GUI a "Modern Dev Tool" visual identity (near-black surfaces, floating cards, a violet→blue gradient accent, a real vector icon set) and fix the "everything feels small" complaint (maximized launch, a wider workbench dock), without touching any controller, service, or numerical-core code.

**Architecture:** Two additive layers land first — `Theme.qml` v2 tokens (all existing token names stay valid; new tokens are added alongside) and a new `Icons.qml` singleton providing vector icons as inline SVG data URIs. `Main.qml` (the app shell) then consumes both to reskin the toolbar, sidebar tabs, viewport, and docks. No `objectName`, no exposed `Property`, and no controller API changes anywhere — this is a QML/Theme-layer change only, so the existing `gui/tests` suite is the primary regression gate.

**Tech Stack:** PySide6 6.11 (QtQuick/QtQuick.Controls/QtQml), pytest, headless `QT_QPA_PLATFORM=offscreen` test runs (existing `gui/tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-09-04-gui-visual-reskin-design.md`

## Global Constraints

- Numerical core (`pytcad/pytcad/*.py`), controllers, and services are not touched by this plan at all — it only edits `gui/qml/*.qml` and adds `gui/tests/test_theme_tokens.py` / `gui/tests/test_icons.py`.
- Every existing `objectName` and every `@Property(QObject)` controller API stays exactly as it is today. Verified per-task by running the existing `gui/tests` suite, not assumed.
- No new Python dependencies. Icons are inline SVG data URIs built in QML/JS — confirmed the installed PySide6 6.11.2 has the QtSvg image plugin available (`from PySide6 import QtSvg` succeeds in this environment), so `Image { source: "data:image/svg+xml,..." }` will decode.
- `Theme.qml`'s existing token names (`background`, `panel`, `accent`, `pad`, etc.) are never renamed or removed — only retuned in value or added to. Anything in the codebase that already binds `Theme.xxx` picks up the new look automatically without being edited.
- After every task: run `cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q` and confirm the reported pass count is >= the pre-task count with zero new failures (record the exact before/after numbers in the task's verification step, don't eyeball it).
- This machine has a real display (`DISPLAY=:0`, confirmed in this session) — live-app verification (`QT_QPA_PLATFORM= ... python3 -m gui.app`, i.e. NOT forcing offscreen) is possible and required before Task 3 and the final task are marked done, not just the headless suite.
- Panel-*content* restyling (Mesh statistics grid, Structure/Process/Sweep panels, etc. — spec section 8) is explicitly OUT of scope for this plan. It is Slice 2+ and gets its own follow-up plan once this one lands (per the spec's own rollout section and this project's practice of one plan per subsystem).

---

## Task 1: Theme.qml v2 — design-system tokens

**Files:**
- Modify: `pytcad/gui/qml/Theme.qml` (full-file replacement — it's 83 lines)
- Test: `pytcad/gui/tests/test_theme_tokens.py` (new)

**Interfaces:**
- Consumes: nothing new (Theme.qml has no dependencies).
- Produces: new `Theme` singleton properties consumed by later tasks —
  `Theme.cardBg: color`, `Theme.cardBorder: color`, `Theme.cardShadow: color`,
  `Theme.accentGradientStart: color` (= `"#8b5cf6"`, identical in both
  themes), `Theme.accentGradientEnd: color` (= `"#3b82f6"`, identical in
  both themes), `Theme.radiusCard: int` (= `10`). All pre-existing token
  names (`background`, `panel`, `panelAlt`, `panelRaised`, `sunken`,
  `border`, `borderStrong`, `text`, `textDim`, `textFaint`, `focus`,
  `accent`, `accentSoft`, `running`, `error`, `ok`, `selection`, `mono`,
  `family`, `animFast/Med/Slow`, `easeOut`, `easeInOut`, `hoverOverlay`,
  `pressOverlay`, `shadow`, `accentGlow`, `dark`, `toggle()`, `pad*`,
  `radius*`, `fs*`) keep their names; several dark-mode values change
  (see Step 3) since retuning the base palette is the whole point of
  this task, but no consumer needs to change because of that — they all
  read the token, not a literal color.

- [ ] **Step 1: Write the failing test**

Create `pytcad/gui/tests/test_theme_tokens.py`:

```python
"""Headless checks for Theme.qml v2's design-system tokens.

Loads the Theme singleton through a standalone QQmlComponent (not the
full Main.qml window) so this stays a cheap, independent regression
gate: if a future edit drops a token or breaks dark/light retuning,
this fails on its own, without booting the whole app.
"""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)

PROBE_QML = """
import QtQuick
QtObject {
    property bool setDark: true
    onSetDarkChanged: Theme.dark = setDark
    property color background: Theme.background
    property color panel: Theme.panel
    property color cardBg: Theme.cardBg
    property color cardBorder: Theme.cardBorder
    property color accent: Theme.accent
    property color accentGradientStart: Theme.accentGradientStart
    property color accentGradientEnd: Theme.accentGradientEnd
    property int radiusCard: Theme.radiusCard
}
"""


def _make_probe(qml_engine):
    component = QQmlComponent(qml_engine)
    component.setData(
        PROBE_QML.encode("utf-8"),
        QUrl.fromLocalFile(os.path.join(QML_DIR, "_theme_probe.qml")),
    )
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    return obj


def test_theme_v2_tokens_dark_and_light():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)

    probe.setProperty("setDark", True)
    dark_bg = QColor(probe.property("background")).name()
    dark_card = QColor(probe.property("cardBg")).name()
    dark_accent = QColor(probe.property("accent")).name()
    grad_start_dark = QColor(probe.property("accentGradientStart")).name()
    grad_end_dark = QColor(probe.property("accentGradientEnd")).name()
    assert dark_bg == "#0a0b0e"
    assert dark_card == "#16171d"
    assert dark_accent == "#8b5cf6"
    assert probe.property("radiusCard") == 10

    probe.setProperty("setDark", False)
    light_bg = QColor(probe.property("background")).name()
    light_card = QColor(probe.property("cardBg")).name()
    light_accent = QColor(probe.property("accent")).name()
    grad_start_light = QColor(probe.property("accentGradientStart")).name()
    grad_end_light = QColor(probe.property("accentGradientEnd")).name()
    assert light_bg != dark_bg
    assert light_card == "#ffffff"
    assert light_accent == "#7c3aed"

    # The brand gradient is identical in both themes by design (spec
    # section 4/5) -- this is the regression gate for that requirement.
    assert grad_start_dark == grad_start_light == "#8b5cf6"
    assert grad_end_dark == grad_end_light == "#3b82f6"
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd pytcad && python3 -m pytest gui/tests/test_theme_tokens.py -v
```

Expected: FAIL — `Theme.qml` doesn't have `cardBg`/`accentGradientStart`/
etc. yet, so the probe's color properties resolve to invalid colors
(`QColor().name()` is `"#000000"` for an unset/invalid color, which
will not equal `"#0a0b0e"`/`"#16171d"`/etc.).

- [ ] **Step 3: Replace Theme.qml with the v2 token set**

Replace the entire contents of `pytcad/gui/qml/Theme.qml` with:

```qml
pragma Singleton
import QtQuick

// PyTCAD design system -- "Modern Dev Tool" identity (v2, 2026-09-04
// reskin). Near-black surfaces carry structure; a violet -> blue
// gradient is the one accent used for active/selected state and the
// primary action (Run). All v1 token names remain valid so nothing
// else in the codebase breaks while panels migrate to the new
// cardBg/cardBorder/cardShadow surfaces panel-by-panel (see
// docs/superpowers/specs/2026-09-04-gui-visual-reskin-design.md).
QtObject {
    id: theme

    property bool dark: true

    readonly property int fsTiny:   10
    readonly property int fsSmall:  11
    readonly property int fsBody:   12
    readonly property int fsHeader: 13
    readonly property int fsTitle:  15

    // vertical rhythm
    readonly property int padXs: 4
    readonly property int padSm: 6
    readonly property int pad: 8          // legacy name = base unit
    readonly property int padLg: 12
    readonly property int padXl: 16
    readonly property int radiusSm: 3     // legacy name below
    readonly property int radius: 3
    readonly property int radiusLg: 6
    readonly property int radiusCard: 10  // v2: floating-card corner radius

    // ---- surfaces ------------------------------------------------------
    readonly property color background:  dark ? "#0a0b0e" : "#eef1f4"
    readonly property color panel:       dark ? "#0d0e12" : "#ffffff"
    readonly property color panelAlt:    dark ? "#111217" : "#eceff2"
    readonly property color panelRaised: dark ? "#16171d" : "#f7f9fa"
    readonly property color sunken:      dark ? "#050608" : "#e2e6ea"

    // ---- v2: floating-card surfaces -------------------------------------
    readonly property color cardBg:      dark ? "#16171d" : "#ffffff"
    readonly property color cardBorder:  dark ? "#24252c" : "#dde3e9"
    readonly property color cardShadow:  dark ? Qt.rgba(0, 0, 0, 0.4) : Qt.rgba(0, 0, 0, 0.12)

    // ---- lines & text ---------------------------------------------------
    readonly property color border:       dark ? "#1f2026" : "#c9d0d8"
    readonly property color borderStrong: dark ? "#2c2d36" : "#a8b2bc"
    readonly property color text:         dark ? "#e4e4e7" : "#1a2129"
    readonly property color textDim:      dark ? "#a1a1aa" : "#5a6572"
    readonly property color textFaint:    dark ? "#71717a" : "#8894a0"
    readonly property color focus:        dark ? "#8b5cf6" : "#7c3aed"

    // ---- state colours --------------------------------------------------
    readonly property color accent:       dark ? "#8b5cf6" : "#7c3aed"
    readonly property color accentSoft:   dark ? "#241f38" : "#ede9fe"
    readonly property color running:      dark ? "#d9a441" : "#b57f14"
    property color error:                 dark ? "#e05c56" : "#c0392b"
    readonly property color ok:           dark ? "#61bd6d" : "#2e8b44"

    // ---- v2: brand gradient -- identical in both themes, since the
    // accent IS the brand, not a theme-dependent surface.
    readonly property color accentGradientStart: "#8b5cf6"
    readonly property color accentGradientEnd:   "#3b82f6"

    // selection highlight inside lists
    readonly property color selection:    dark ? "#3a2f57" : "#ede9fe"

    // ---- type ------------------------------------------------------------
    readonly property string mono: '"DejaVu Sans Mono", "Consolas", monospace'
    readonly property string family: '"Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif'

    // ---- motion ----------------------------------------------------------
    readonly property int animFast: 110
    readonly property int animMed:  200
    readonly property int animSlow: 360
    readonly property int easeOut:  Easing.OutCubic
    readonly property int easeInOut: Easing.InOutQuad

    // ---- depth & glow ------------------------------------------------------
    readonly property color hoverOverlay: dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.045)
    readonly property color pressOverlay: dark ? Qt.rgba(1, 1, 1, 0.11) : Qt.rgba(0, 0, 0, 0.08)
    readonly property color shadow:       dark ? Qt.rgba(0, 0, 0, 0.55) : Qt.rgba(0, 0, 0, 0.18)
    readonly property color accentGlow:   dark ? Qt.rgba(0.545, 0.361, 0.965, 0.35)
                                                : Qt.rgba(0.486, 0.227, 0.929, 0.22)

    function toggle() { theme.dark = !theme.dark }
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd pytcad && python3 -m pytest gui/tests/test_theme_tokens.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full fast GUI suite and confirm no regressions**

```bash
cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q
```

Record the pass count. Expected: same pass count as before this task
started, plus the 1 new test, zero new failures. (Nothing in
`gui/tests` reads a literal color value from Theme's retuned dark
palette — confirmed by grepping for hex-color assertions before
starting this plan — so this should be a clean pass.)

- [ ] **Step 6: Commit**

```bash
git add pytcad/gui/qml/Theme.qml pytcad/gui/tests/test_theme_tokens.py
git commit -m "$(cat <<'EOF'
GUI reskin slice 0: Theme.qml v2 design-system tokens

Retunes the dark palette to a near-black "Modern Dev Tool" base and
adds card-surface (cardBg/cardBorder/cardShadow) and brand-gradient
(accentGradientStart/End, violet->blue, identical in both themes)
tokens. All v1 token names stay valid -- existing QML keeps rendering
unchanged in shape, picking up the new colors automatically since it
reads Theme.* tokens rather than literal hex values.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```

---

## Task 2: Icons.qml — vector icon set

**Files:**
- Create: `pytcad/gui/qml/Icons.qml`
- Modify: `pytcad/gui/qml/qmldir`
- Test: `pytcad/gui/tests/test_icons.py` (new)

**Interfaces:**
- Consumes: nothing (standalone singleton, like Theme).
- Produces: `Icons.svg(name: string, color: string|color) -> string`
  (a `data:image/svg+xml,...` URI, or `""` for an unknown name) and
  `Icons.names: array<string>` (every registered icon name), both
  consumed by Task 4's Main.qml edits. `color` accepts EITHER a plain
  hex string (`"#8b5cf6"`) OR a live QML `color` value (e.g.
  `Theme.text`) -- Task 4 needs both call shapes.

- [ ] **Step 1: Write the failing test**

Create `pytcad/gui/tests/test_icons.py`:

```python
"""Headless checks for Icons.qml's vector icon set (v2 reskin).

Same standalone-QQmlComponent technique as test_theme_tokens.py.
"""
import os
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)

# Every icon name Main.qml's sidebar tabs and toolbar buttons use (Task
# 4/5 of the reskin plan) -- listed explicitly here, not read back from
# Icons.qml's own `names` property, so a future typo in Main.qml is
# caught by THIS list even before Main.qml is edited to use it.
EXPECTED_NAMES = [
    "project", "structure", "mesh", "process", "sweeps", "probeStation",
    "telemetry", "bands", "transient", "physicsLab", "builder",
    "run", "stop", "undo", "redo", "sun", "moon",
]

PROBE_QML = """
import QtQuick
QtObject {
    readonly property string uriProject: Icons.svg("project", "#8b5cf6")
    readonly property string uriStructure: Icons.svg("structure", "#8b5cf6")
    readonly property string uriMesh: Icons.svg("mesh", "#8b5cf6")
    readonly property string uriProcess: Icons.svg("process", "#8b5cf6")
    readonly property string uriSweeps: Icons.svg("sweeps", "#8b5cf6")
    readonly property string uriProbeStation: Icons.svg("probeStation", "#8b5cf6")
    readonly property string uriTelemetry: Icons.svg("telemetry", "#8b5cf6")
    readonly property string uriBands: Icons.svg("bands", "#8b5cf6")
    readonly property string uriTransient: Icons.svg("transient", "#8b5cf6")
    readonly property string uriPhysicsLab: Icons.svg("physicsLab", "#8b5cf6")
    readonly property string uriBuilder: Icons.svg("builder", "#8b5cf6")
    readonly property string uriRun: Icons.svg("run", "#8b5cf6")
    readonly property string uriStop: Icons.svg("stop", "#8b5cf6")
    readonly property string uriUndo: Icons.svg("undo", "#8b5cf6")
    readonly property string uriRedo: Icons.svg("redo", "#8b5cf6")
    readonly property string uriSun: Icons.svg("sun", "#8b5cf6")
    readonly property string uriMoon: Icons.svg("moon", "#8b5cf6")
    readonly property string uriUnknown: Icons.svg("doesNotExist", "#8b5cf6")
    // A real QML `color` value, not a string -- exercises the
    // object-vs-string branch inside Icons.svg().
    readonly property string uriFromColorObject: Icons.svg("run", Theme.accent)
    property var iconNames: Icons.names
}
"""

NAME_TO_PROPERTY = {
    "project": "uriProject", "structure": "uriStructure", "mesh": "uriMesh",
    "process": "uriProcess", "sweeps": "uriSweeps",
    "probeStation": "uriProbeStation", "telemetry": "uriTelemetry",
    "bands": "uriBands", "transient": "uriTransient",
    "physicsLab": "uriPhysicsLab", "builder": "uriBuilder",
    "run": "uriRun", "stop": "uriStop", "undo": "uriUndo",
    "redo": "uriRedo", "sun": "uriSun", "moon": "uriMoon",
}


def _make_probe(qml_engine):
    component = QQmlComponent(qml_engine)
    component.setData(
        PROBE_QML.encode("utf-8"),
        QUrl.fromLocalFile(os.path.join(QML_DIR, "_icons_probe.qml")),
    )
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    return obj


def test_every_expected_icon_resolves_to_a_valid_svg_data_uri():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)

    for name in EXPECTED_NAMES:
        prop = NAME_TO_PROPERTY[name]
        uri = probe.property(prop)
        assert uri.startswith("data:image/svg+xml,"), (name, uri)
        payload = unquote(uri[len("data:image/svg+xml,"):])
        assert payload.count("<svg") == 1, (name, payload)
        # The '#' in "#8b5cf6" must survive the encoding round-trip --
        # an unescaped '#' inside a data: URI is a URL fragment
        # delimiter and would silently truncate the SVG.
        assert "#8b5cf6" in payload, (name, payload)


def test_unknown_icon_name_returns_empty_string():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    assert probe.property("uriUnknown") == ""


def test_color_object_argument_produces_valid_css_not_raw_argb_hex():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    uri = probe.property("uriFromColorObject")
    payload = unquote(uri[len("data:image/svg+xml,"):])
    # Qt's QML `color.toString()` yields "#AARRGGBB" (8 hex digits),
    # which is NOT valid SVG/CSS color syntax (CSS 8-digit hex is
    # RRGGBBAA, a different byte order) -- Icons.svg() must convert a
    # color OBJECT to an rgba(...) string instead of stringifying it
    # directly, or every icon colored from a Theme.* binding (not a
    # literal hex string) would silently render blank.
    assert "rgba(" in payload
    assert "#ff" not in payload.lower()


def test_names_list_covers_every_expected_icon():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    names = list(probe.property("iconNames"))
    assert set(EXPECTED_NAMES) <= set(names)
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd pytcad && python3 -m pytest gui/tests/test_icons.py -v
```

Expected: FAIL/ERROR — `Icons` is not a known QML type yet (no
`Icons.qml`, no `qmldir` entry), so `QQmlComponent.create()` returns
`None` and the probe's own assertion (`assert obj is not None,
component.errorString()`) fails with a "module not installed" /
"Icons is not defined" style error.

- [ ] **Step 3: Create Icons.qml**

Create `pytcad/gui/qml/Icons.qml`:

```qml
pragma Singleton
import QtQuick

// PyTCAD vector icon set (v2 reskin) -- replaces the plain Unicode
// glyphs used through v0.1-v0.6 (see gui/README.md) with small
// colorable SVG icons, so active/hover/dim state can drive icon color
// through the same Theme tokens everything else uses.
//
// Icons.svg(name, color) returns a "data:image/svg+xml,..." URI ready
// for an Image element's `source`. Two things the implementation must
// get right, both covered by gui/tests/test_icons.py:
//
// 1. The WHOLE svg string is passed through encodeURIComponent, not
//    just interpolated -- a literal '#' in a hex color (e.g.
//    "#8b5cf6") is a URL FRAGMENT delimiter, and an unescaped '#'
//    inside a data: URI silently truncates everything after it,
//    rendering a blank/partial icon.
// 2. `color` may be a real QML `color` value (e.g. Theme.accent), not
//    a string -- and Qt's `color.toString()` yields "#AARRGGBB" (8
//    hex digits, alpha-first), which is NOT valid SVG/CSS color
//    syntax. A color object is converted to "rgba(r,g,b,a)" instead
//    of being stringified directly.
QtObject {
    id: icons

    readonly property var _paths: ({
        project:      "<path d='M4 10 L12 4 L20 10 L20 20 L4 20 Z'/><path d='M9 20 V14 H15 V20'/>",
        structure:    "<rect x='4' y='4' width='7' height='7'/><rect x='13' y='4' width='7' height='7'/><rect x='4' y='13' width='7' height='7'/><rect x='13' y='13' width='7' height='7'/>",
        mesh:         "<path d='M3 6 H21 M3 12 H21 M3 18 H21 M7 3 V21 M12 3 V21 M17 3 V21'/>",
        process:      "<path d='M9 3 H15 V7 L18 12 V20 H6 V12 L9 7 Z'/>",
        sweeps:       "<path d='M3 15 Q7 6 11 15 T19 15'/>",
        probeStation: "<circle cx='12' cy='9' r='4'/><path d='M6 21 C6 16 18 16 18 21'/>",
        telemetry:    "<path d='M3 17 L8 10 L12 14 L21 5'/><path d='M15 5 H21 V11'/>",
        bands:        "<path d='M3 8 H21 M3 16 H21 M7 8 V16 M17 8 V16'/>",
        transient:    "<circle cx='12' cy='12' r='8'/><path d='M12 7 V12 L16 14'/>",
        physicsLab:   "<circle cx='12' cy='12' r='1.6' fill='currentColor' stroke='none'/><ellipse cx='12' cy='12' rx='9' ry='3.6'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(60 12 12)'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(120 12 12)'/>",
        builder:      "<path d='M14 3 L21 10 L10 21 L3 21 L3 14 Z'/>",
        run:          "<path d='M6 4 L20 12 L6 20 Z' fill='currentColor' stroke='none'/>",
        stop:         "<rect x='6' y='6' width='12' height='12' fill='currentColor' stroke='none'/>",
        undo:         "<path d='M8 8 H15 A5 5 0 1 1 11 18'/><path d='M8 8 L12 4 M8 8 L12 12'/>",
        redo:         "<path d='M16 8 H9 A5 5 0 1 0 13 18'/><path d='M16 8 L12 4 M16 8 L12 12'/>",
        sun:          "<circle cx='12' cy='12' r='4'/><path d='M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22 M4.9 4.9 L7 7 M17 17 L19.1 19.1 M19.1 4.9 L17 7 M7 17 L4.9 19.1'/>",
        moon:         "<path d='M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z' fill='currentColor' stroke='none'/>"
    })

    // Exported so gui/tests/test_icons.py can check coverage without
    // duplicating this key list.
    readonly property var names: Object.keys(_paths)

    function _toCss(c) {
        return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," +
               Math.round(c.b * 255) + "," + c.a.toFixed(3) + ")"
    }

    function svg(name, color) {
        var inner = icons._paths[name]
        if (inner === undefined) {
            console.warn("Icons.svg: unknown icon name '" + name + "'")
            return ""
        }
        var css = (typeof color === "string") ? color : icons._toCss(color)
        var colored = inner.split("currentColor").join(css)
        var doc = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' " +
                  "fill='none' stroke='" + css + "' stroke-width='1.8' " +
                  "stroke-linecap='round' stroke-linejoin='round'>" + colored + "</svg>"
        return "data:image/svg+xml," + encodeURIComponent(doc)
    }
}
```

- [ ] **Step 4: Register the singleton in qmldir**

Modify `pytcad/gui/qml/qmldir` — current full content is one line:

```
singleton Theme 1.0 Theme.qml
```

Replace with:

```
singleton Theme 1.0 Theme.qml
singleton Icons 1.0 Icons.qml
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd pytcad && python3 -m pytest gui/tests/test_icons.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 6: Run the full fast GUI suite and confirm no regressions**

```bash
cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q
```

Expected: previous pass count + 4 new tests (from this task) + 1 (from
Task 1) = previous + 5 total added since the start of this plan, zero
new failures.

- [ ] **Step 7: Commit**

```bash
git add pytcad/gui/qml/Icons.qml pytcad/gui/qml/qmldir pytcad/gui/tests/test_icons.py
git commit -m "$(cat <<'EOF'
GUI reskin slice 0: Icons.qml vector icon set

Adds a new Icons singleton (pragma Singleton, registered in qmldir)
providing 17 small vector icons as inline SVG data URIs, replacing the
plain Unicode glyphs used since v0.1. Icons.svg(name, color) accepts
either a literal hex string or a live Theme.* color value -- the
latter needed an explicit color/rgba() conversion since Qt's QML
`color.toString()` produces "#AARRGGBB", not valid SVG/CSS syntax.
Also guards against a real bug class: an unescaped '#' inside a
data: URI is a URL fragment delimiter and truncates the SVG, so the
whole document is run through encodeURIComponent rather than
interpolated raw. Not yet wired into Main.qml (Task 4).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```

---

## Task 3: Main.qml — launch maximized

**Files:**
- Modify: `pytcad/gui/qml/Main.qml:1-27` (imports + a new `Component.onCompleted`)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new consumed by later tasks (this task is
  independent of Tasks 4/5 and can land in any order relative to them,
  though doing it now keeps each task small).

- [ ] **Step 1: Add the `QtQuick.Window` import**

In `pytcad/gui/qml/Main.qml`, the current imports (lines 1-7) are:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects
import "panels"
import "components"
```

Add `import QtQuick.Window` so the `Window.Maximized` enum is available
explicitly rather than relying on it being pulled in transitively:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Window
import "panels"
import "components"
```

- [ ] **Step 2: Add the maximized-launch guard**

In `pytcad/gui/qml/Main.qml`, find:

```qml
    // dock collapse state (animated below)
    property bool propsCollapsed: false
    property bool consoleCollapsed: false

    Shortcut { sequence: "Ctrl+Z"; onActivated: if (appController.canUndo) appController.undo() }
```

Insert a `Component.onCompleted` block between the two:

```qml
    // dock collapse state (animated below)
    property bool propsCollapsed: false
    property bool consoleCollapsed: false

    // v2 reskin: launch filling the screen so panels (the Mesh panel
    // was named explicitly) aren't cramped by the fixed 1440x900
    // default -- the width/height/minimum* values above remain as the
    // fallback. Guarded against the offscreen QPA platform: Qt's
    // offscreen platform has no real screen to maximize against, and
    // gui/tests' headless runs (QT_QPA_PLATFORM=offscreen, set in
    // conftest.py) must keep getting the deterministic default size.
    Component.onCompleted: {
        if (Qt.platformName !== "offscreen")
            window.visibility = Window.Maximized
    }

    Shortcut { sequence: "Ctrl+Z"; onActivated: if (appController.canUndo) appController.undo() }
```

- [ ] **Step 3: Run the full fast GUI suite and confirm no regressions**

```bash
cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q
```

Expected: same pass count as after Task 2, zero new failures (the
`Component.onCompleted` guard means every headless test, which runs
under `QT_QPA_PLATFORM=offscreen`, takes the no-op branch).

- [ ] **Step 4: Manually verify the maximized launch on a real display**

This machine has a real display (`DISPLAY=:0`, confirmed at plan-writing
time) — the offscreen guard means the fast suite above cannot exercise
this behavior, so it must be checked by actually running the app:

```bash
cd pytcad && python3 -m gui.app
```

Expected: the PyTCAD window opens filling the screen (not the old
1440x900 fixed size). Close the window when confirmed. If it does NOT
open maximized, do not proceed to Step 5 — re-check that `DISPLAY` is
set in the shell running this command and that `Qt.platformName` is
actually not `"offscreen"` in this run (it should default to `"xcb"`
or `"wayland"` whenever `QT_QPA_PLATFORM` isn't set in the
environment).

- [ ] **Step 5: Commit**

```bash
git add pytcad/gui/qml/Main.qml
git commit -m "$(cat <<'EOF'
GUI reskin slice 1: launch maximized by default

Main.qml now opens filling the screen instead of the fixed 1440x900
default, addressing the "window feels small" complaint. Guarded to a
no-op under QT_QPA_PLATFORM=offscreen so gui/tests' headless runs are
unaffected -- verified both by the unchanged fast-suite pass count and
by actually running the live app on a real display.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```

---

## Task 4: Main.qml — sidebar tabs and toolbar get vector icons

**Files:**
- Modify: `pytcad/gui/qml/Main.qml` (sidebar `TabBar`/`Repeater`/delegate,
  and the `runButton`/`stopButton`/`undoButton`/`redoButton`/`themeButton`
  toolbar buttons)
- Test: `pytcad/gui/tests/test_shell_icons.py` (new)

**Interfaces:**
- Consumes: `Icons.svg(name, color)` from Task 2, `Theme.accentSoft`/
  `Theme.accentGradientStart`/`Theme.accentGradientEnd`/`Theme.focus`/
  `Theme.text`/`Theme.textFaint` from Task 1.
- Produces: every sidebar tab icon `Image` gets `objectName:
  "sidebarTabIcon"` so Step's test can find all of them; no other new
  identifiers.

- [ ] **Step 1: Write the failing test**

Create `pytcad/gui/tests/test_shell_icons.py`:

```python
"""Checks that Main.qml's sidebar tabs render a real icon per tab,
after the v2 reskin replaces the Unicode-glyph delegate with an
Image + Text delegate (gui/qml/Main.qml, workbenchTabs' Repeater).

Loads the real Main.qml through gui.app.create_engine() -- the same
pattern every other gui/tests file uses -- rather than a standalone
probe, since this is about the actual rendered tab bar, not an
isolated singleton.
"""
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine

EXPECTED_TAB_COUNT = 11


def test_every_sidebar_tab_has_a_non_empty_icon():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        icons = root.findChildren(QObject, "sidebarTabIcon")
        assert len(icons) == EXPECTED_TAB_COUNT, (
            f"expected {EXPECTED_TAB_COUNT} sidebar tab icons, found {len(icons)}"
        )
        for img in icons:
            source = img.property("source")
            assert source is not None
            assert str(source) != "", "a sidebar tab icon has an empty source"
    finally:
        close_engine(engine)
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd pytcad && python3 -m pytest gui/tests/test_shell_icons.py -v
```

Expected: FAIL — `findChildren(QObject, "sidebarTabIcon")` returns an
empty list, since no `Image` with that `objectName` exists in Main.qml
yet (the delegate is still a plain `Text`).

- [ ] **Step 3: Replace the sidebar tab model and delegate**

In `pytcad/gui/qml/Main.qml`, find the `TabBar` block (currently under
the `// ---- LEFT: tabbed workbench dock ----` comment):

```qml
                    TabBar {
                        id: workbenchTabs
                        objectName: "workbenchTabs"
                        Layout.fillWidth: true
                        contentHeight: 30

                        Repeater {
                            model: [
                                { "label": "Project",   "icon": "⌂" },
                                { "label": "Structure", "icon": "▤" },
                                { "label": "Mesh",      "icon": "▦" },
                                { "label": "Process",   "icon": "⚗" },
                                { "label": "Sweeps",    "icon": "∿" },
                                { "label": "Probe Station", "icon": "⎍" },
                                { "label": "Telemetry", "icon": "◈" },
                                { "label": "Bands", "icon": "≡" },
                                { "label": "Transient", "icon": "⏱" },
                                { "label": "Physics Lab", "icon": "⚛" },
                                { "label": "Builder",   "icon": "✎" }
                            ]
                            delegate: TabButton {
                                id: tabDelegate
                                required property var modelData
                                text: modelData.icon + " " + modelData.label
                                width: Math.max(implicitWidth, 44)
                                font.pixelSize: Theme.fsSmall
                                contentItem: Text {
                                    text: tabDelegate.text
                                    font: tabDelegate.font
                                    color: tabDelegate.checked ? Theme.accent
                                           : tabDelegate.activeFocus ? Theme.focus : Theme.text
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                }
                                background: Rectangle {
                                    color: tabDelegate.hovered && !tabDelegate.checked
                                           ? Theme.hoverOverlay : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                }
                            }
                        }

                        // Accent bar that glides beneath the active tab
                        // instead of snapping there, tying tab selection
                        // to a single continuous piece of motion.
                        Rectangle {
                            id: tabIndicator
                            height: 2
                            radius: 1
                            color: Theme.accent
                            y: workbenchTabs.height - height
                            x: workbenchTabs.currentItem ? workbenchTabs.currentItem.x : 0
                            width: workbenchTabs.currentItem ? workbenchTabs.currentItem.width : 0
                            Behavior on x { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
                            Behavior on width { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
                        }
                    }
```

Replace the whole block with:

```qml
                    TabBar {
                        id: workbenchTabs
                        objectName: "workbenchTabs"
                        Layout.fillWidth: true
                        contentHeight: 32

                        Repeater {
                            model: [
                                { "label": "Project",   "icon": "project" },
                                { "label": "Structure", "icon": "structure" },
                                { "label": "Mesh",      "icon": "mesh" },
                                { "label": "Process",   "icon": "process" },
                                { "label": "Sweeps",    "icon": "sweeps" },
                                { "label": "Probe Station", "icon": "probeStation" },
                                { "label": "Telemetry", "icon": "telemetry" },
                                { "label": "Bands", "icon": "bands" },
                                { "label": "Transient", "icon": "transient" },
                                { "label": "Physics Lab", "icon": "physicsLab" },
                                { "label": "Builder",   "icon": "builder" }
                            ]
                            delegate: TabButton {
                                id: tabDelegate
                                required property var modelData
                                width: Math.max(implicitWidth, 64)
                                font.pixelSize: Theme.fsSmall
                                readonly property color tabColor: tabDelegate.checked ? Theme.accentGradientEnd
                                                                   : tabDelegate.activeFocus ? Theme.focus : Theme.text
                                contentItem: Row {
                                    spacing: Theme.padXs
                                    anchors.centerIn: parent
                                    Image {
                                        objectName: "sidebarTabIcon"
                                        anchors.verticalCenter: parent.verticalCenter
                                        source: Icons.svg(tabDelegate.modelData.icon, tabDelegate.tabColor)
                                        sourceSize.width: 15
                                        sourceSize.height: 15
                                        width: 15
                                        height: 15
                                        smooth: true
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: tabDelegate.modelData.label
                                        font: tabDelegate.font
                                        color: tabDelegate.tabColor
                                        elide: Text.ElideRight
                                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                    }
                                }
                                background: Rectangle {
                                    radius: Theme.radiusLg
                                    color: tabDelegate.checked ? Theme.accentSoft
                                           : tabDelegate.hovered ? Theme.hoverOverlay : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                }
                            }
                        }

                        // Accent bar that glides beneath the active tab
                        // instead of snapping there, tying tab selection
                        // to a single continuous piece of motion. Now a
                        // real violet->blue gradient rather than a flat
                        // fill (QtQuick's Gradient has no arbitrary-angle
                        // mode, so this is a horizontal approximation of
                        // the approved mockup's 135deg buttons -- a
                        // deliberate simplification, not an oversight).
                        Rectangle {
                            id: tabIndicator
                            height: 2
                            radius: 1
                            y: workbenchTabs.height - height
                            x: workbenchTabs.currentItem ? workbenchTabs.currentItem.x : 0
                            width: workbenchTabs.currentItem ? workbenchTabs.currentItem.width : 0
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: Theme.accentGradientStart }
                                GradientStop { position: 1.0; color: Theme.accentGradientEnd }
                            }
                            Behavior on x { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
                            Behavior on width { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
                        }
                    }
```

- [ ] **Step 4: Run the new test and confirm it passes**

```bash
cd pytcad && python3 -m pytest gui/tests/test_shell_icons.py -v
```

Expected: PASS.

- [ ] **Step 5: Replace the toolbar buttons' glyph text with icons**

In `pytcad/gui/qml/Main.qml`, the `runButton` currently reads:

```qml
            Button {
                id: runButton
                display: AbstractButton.IconOnly
                text: "▶"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Solve the current device"
                enabled: !appController.busy
                onClicked: appController.run()
                background: Rectangle {
                    radius: Theme.radiusSm
                    color: !runButton.enabled ? "transparent"
                           : runButton.pressed ? Qt.darker(Theme.ok, 1.15)
                           : runButton.hovered ? Theme.ok : Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.85)
                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    scale: runButton.pressed ? 0.92 : 1.0
                    Behavior on scale { NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic } }
                }
                contentItem: Text {
                    text: runButton.text
                    color: runButton.enabled ? "#ffffff" : Theme.textFaint
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
```

Replace its `contentItem` (keep `text: "▶"` as-is — it's still useful
as the button's accessible name/tooltip fallback, just no longer
rendered):

```qml
                contentItem: Image {
                    source: Icons.svg("run", runButton.enabled ? "#ffffff" : Theme.textFaint)
                    sourceSize.width: 13
                    sourceSize.height: 13
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignHCenter
                    verticalAlignment: Image.AlignVCenter
                }
```

Similarly, `stopButton` currently has:

```qml
                contentItem: Text {
                    text: stopButton.text
                    color: stopButton.enabled ? "#ffffff" : Theme.textFaint
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
```

Replace with:

```qml
                contentItem: Image {
                    source: Icons.svg("stop", stopButton.enabled ? "#ffffff" : Theme.textFaint)
                    sourceSize.width: 12
                    sourceSize.height: 12
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignHCenter
                    verticalAlignment: Image.AlignVCenter
                }
```

`undoButton` currently has:

```qml
                contentItem: Text {
                    text: undoButton.text
                    color: undoButton.enabled ? Theme.text : Theme.textFaint
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
```

Replace with:

```qml
                contentItem: Image {
                    source: Icons.svg("undo", undoButton.enabled ? Theme.text : Theme.textFaint)
                    sourceSize.width: 14
                    sourceSize.height: 14
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignHCenter
                    verticalAlignment: Image.AlignVCenter
                }
```

`redoButton` currently has:

```qml
                contentItem: Text {
                    text: redoButton.text
                    color: redoButton.enabled ? Theme.text : Theme.textFaint
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
```

Replace with:

```qml
                contentItem: Image {
                    source: Icons.svg("redo", redoButton.enabled ? Theme.text : Theme.textFaint)
                    sourceSize.width: 14
                    sourceSize.height: 14
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignHCenter
                    verticalAlignment: Image.AlignVCenter
                }
```

Finally, `themeButton` currently has:

```qml
                contentItem: Text {
                    text: themeButton.text
                    color: Theme.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    rotation: 0
                    RotationAnimation on rotation {
                        id: spin
                        from: 0; to: 360
                        duration: Theme.animSlow
                        easing.type: Easing.OutCubic
                    }
                }
```

Replace with:

```qml
                contentItem: Image {
                    source: Icons.svg(Theme.dark ? "sun" : "moon", Theme.text)
                    sourceSize.width: 15
                    sourceSize.height: 15
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignHCenter
                    verticalAlignment: Image.AlignVCenter
                    rotation: 0
                    RotationAnimation on rotation {
                        id: spin
                        from: 0; to: 360
                        duration: Theme.animSlow
                        easing.type: Easing.OutCubic
                    }
                }
```

(Leave every `Button`'s own `text:`/`ToolTip.text:` property and
`onClicked` handler exactly as they are — only each button's
`contentItem` changes.)

- [ ] **Step 6: Run the full fast GUI suite and confirm no regressions**

```bash
cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q
```

Expected: previous pass count + 1 (this task's new test), zero new
failures.

- [ ] **Step 7: Manually verify on the live app**

```bash
cd pytcad && python3 -m gui.app
```

Confirm: every sidebar tab shows a small icon next to its label, the
active tab has a soft violet wash background, the gliding indicator
bar under the tabs is a violet-to-blue gradient, and the toolbar's
Run/Stop/Undo/Redo/theme-toggle buttons show icons instead of glyphs.
Close the window when confirmed.

- [ ] **Step 8: Commit**

```bash
git add pytcad/gui/qml/Main.qml pytcad/gui/tests/test_shell_icons.py
git commit -m "$(cat <<'EOF'
GUI reskin slice 1: sidebar tabs and toolbar get vector icons

Replaces the icon+label Unicode-glyph TabButton delegate with a real
Image+Text row (Icons.svg), gives the active tab a soft violet wash
background, and turns the gliding tab-indicator bar into a violet->blue
gradient. The five toolbar buttons (Run/Stop/Undo/Redo/theme-toggle)
swap their glyph Text contentItem for an Icons-backed Image, keeping
every button's text/ToolTip/onClicked untouched.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```

---

## Task 5: Main.qml — viewport as a floating card; wider, card-styled docks

**Files:**
- Modify: `pytcad/gui/qml/panels/ViewportPanel.qml:7-10`
- Modify: `pytcad/gui/qml/Main.qml` (the `topSplit` block: workbench dock,
  viewport, properties dock, and the console dock)
- Test: `pytcad/gui/tests/test_shell_layout.py` (new)

**Interfaces:**
- Consumes: `Theme.cardBg`/`Theme.cardBorder`/`Theme.radiusCard` from
  Task 1.
- Produces: nothing new consumed by later tasks (Slice 2's panel-content
  work reads `Theme.cardBg`/`cardBorder` directly, already available
  since Task 1).

- [ ] **Step 1: Write the failing test**

Create `pytcad/gui/tests/test_shell_layout.py`:

```python
"""Checks the v2 reskin's dock sizing and card-surface retoning in
Main.qml: the workbench dock is wider than the pre-reskin 310/240
default, and the workbench/properties/console docks plus the viewport
all use the new cardBg/cardBorder tokens instead of the old
panel/panelAlt/border ones.

Loads the real Main.qml through gui.app.create_engine(), like
test_shell_icons.py.
"""
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlProperty
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine

# Theme.qml v2's dark-mode values (Task 1) -- Main.qml's create_engine()
# starts with Theme.dark == true, its documented default.
CARD_BG = "#16171d"
CARD_BORDER = "#24252c"


def test_workbench_dock_is_wider_than_the_pre_reskin_default():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        dock = root.findChild(QObject, "workbenchDock")
        assert dock is not None
        preferred = QQmlProperty(dock, "SplitView.preferredWidth").read()
        minimum = QQmlProperty(dock, "SplitView.minimumWidth").read()
        assert preferred > 310, f"expected wider than 310, got {preferred}"
        assert minimum > 240, f"expected wider than 240, got {minimum}"
    finally:
        close_engine(engine)


def test_docks_and_viewport_use_card_surface_tokens():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        for name in ("workbenchDock", "propertiesDock", "consoleDock"):
            dock = root.findChild(QObject, name)
            assert dock is not None, name
            color = QColor(dock.property("color")).name()
            assert color == CARD_BG, f"{name}: expected {CARD_BG}, got {color}"

        viewport = root.findChild(QObject, "viewportPanel")
        assert viewport is not None
        v_color = QColor(viewport.property("color")).name()
        assert v_color == CARD_BG, f"viewportPanel: expected {CARD_BG}, got {v_color}"
    finally:
        close_engine(engine)
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd pytcad && python3 -m pytest gui/tests/test_shell_layout.py -v
```

Expected: FAIL — the dock is still 310/240, and the docks/viewport still
use the old `panel`/`panelAlt`/`background` colors (`#0d0e12`/`#111217`/
`#0a0b0e` from Task 1's retune, none of which equal `#16171d`).

- [ ] **Step 3: Retone ViewportPanel.qml's root Rectangle**

In `pytcad/gui/qml/panels/ViewportPanel.qml`, find:

```qml
Rectangle {
    id: root
    color: Theme.background
    border.color: Theme.border
    property var controller
```

Replace with:

```qml
Rectangle {
    id: root
    // v2 reskin: reads as a floating card (Main.qml insets it with a
    // margin against a darker Theme.background backdrop -- see the
    // "CENTER: viewport" block below) rather than flush chrome.
    color: Theme.cardBg
    border.color: Theme.cardBorder
    radius: Theme.radiusCard
    property var controller
```

(Nothing else in this file changes — its `ColumnLayout`'s own
`anchors.margins: Theme.pad` for internal content is untouched.)

- [ ] **Step 4: Widen and retone the workbench dock**

In `pytcad/gui/qml/Main.qml`, find:

```qml
            // ---- LEFT: tabbed workbench dock ---------------------------
            Rectangle {
                objectName: "workbenchDock"
                color: Theme.panel
                border.color: Theme.border
                SplitView.preferredWidth: 310
                SplitView.minimumWidth: 240
```

Replace with:

```qml
            // ---- LEFT: tabbed workbench dock ---------------------------
            Rectangle {
                objectName: "workbenchDock"
                color: Theme.cardBg
                border.color: Theme.cardBorder
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 280
```

- [ ] **Step 5: Wrap the viewport in a floating-card frame**

In `pytcad/gui/qml/Main.qml`, find:

```qml
            // ---- CENTER: viewport --------------------------------------
            ViewportPanel {
                id: viewport
                objectName: "viewportPanel"
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                controller: appController

                BusyOverlay {
                    anchors.fill: parent
                    running: appController.busy
                    stageText: appController.status
                }
            }
```

Replace with:

```qml
            // ---- CENTER: viewport, inset as a floating card over a
            // darker backdrop rather than flush chrome (v2 reskin). The
            // SplitView.* attached properties move to this wrapper since
            // a SplitView's direct children carry them.
            Rectangle {
                id: viewportFrame
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                color: Theme.background

                ViewportPanel {
                    id: viewport
                    objectName: "viewportPanel"
                    anchors.fill: parent
                    anchors.margins: Theme.padLg
                    controller: appController

                    BusyOverlay {
                        anchors.fill: parent
                        running: appController.busy
                        stageText: appController.status
                    }
                }
            }
```

- [ ] **Step 6: Retone the properties dock**

In `pytcad/gui/qml/Main.qml`, find:

```qml
            // ---- RIGHT: collapsible properties dock ---------------------
            Rectangle {
                objectName: "propertiesDock"
                color: Theme.panelAlt
                border.color: Theme.border
```

Replace with:

```qml
            // ---- RIGHT: collapsible properties dock ---------------------
            Rectangle {
                objectName: "propertiesDock"
                color: Theme.cardBg
                border.color: Theme.cardBorder
```

- [ ] **Step 7: Retone the console dock**

In `pytcad/gui/qml/Main.qml`, find:

```qml
        // ---- BOTTOM: collapsible console --------------------------------
        Rectangle {
            objectName: "consoleDock"
            color: Theme.panel
            border.color: Theme.border
```

Replace with:

```qml
        // ---- BOTTOM: collapsible console --------------------------------
        Rectangle {
            objectName: "consoleDock"
            color: Theme.cardBg
            border.color: Theme.cardBorder
```

(The console's own header strip, `consoleGrip`, keeps `color:
Theme.panelAlt` unchanged — a slightly different shade for the header
within the card reads as an intentional header, not a copy/paste gap.)

- [ ] **Step 8: Run the new test and confirm it passes**

```bash
cd pytcad && python3 -m pytest gui/tests/test_shell_layout.py -v
```

Expected: PASS.

- [ ] **Step 9: Run the full fast GUI suite and confirm no regressions**

```bash
cd pytcad && python3 -m pytest gui/tests/ -n 6 -m "not slow" -q
```

Expected: previous pass count + 2 (this task's new tests), zero new
failures. Pay particular attention to any test in
`test_structure_panels.py`, `test_sweep_panels.py`, or
`test_smoke_e2e.py` that navigates via `workbenchTabs` — they select
tabs by index (confirmed earlier in this plan's research, not by text
or pixel width), so the wider dock should not affect them, but this is
exactly the kind of change that plan's own "run the whole suite, not
just the subset that seems relevant" rule (AGENTS.md) exists for.

- [ ] **Step 10: Manually verify on the live app**

```bash
cd pytcad && python3 -m gui.app
```

Confirm: the viewport reads as a distinct floating panel with rounded
corners and a margin around it against a darker window background; the
left workbench dock is visibly wider and the Mesh tab's content no
longer looks cramped; all three docks (workbench, properties, console)
share the same card surface color. Close the window when confirmed.

- [ ] **Step 11: Commit**

```bash
git add pytcad/gui/qml/Main.qml pytcad/gui/qml/panels/ViewportPanel.qml pytcad/gui/tests/test_shell_layout.py
git commit -m "$(cat <<'EOF'
GUI reskin slice 1: viewport-as-card, wider and card-styled docks

ViewportPanel now reads as a floating card (Theme.cardBg/cardBorder,
rounded corners) inset with a margin against a darker Theme.background
backdrop, instead of flush chrome -- the single biggest visual change
in this reskin. The workbench dock widens from 310/240 to 360/280
(directly addresses the "Mesh panel feels small" complaint), and all
three docks (workbench/properties/console) adopt the same card surface
so the whole shell reads as one family.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```

---

## Task 6: Final verification and history.md handoff note

**Files:**
- Modify: `history.md` (append one addendum)

**Interfaces:** none — this task only verifies and documents.

- [ ] **Step 1: Run the full serial suite once (not just the fast parallel one)**

```bash
cd pytcad && python3 -m pytest tests/ gui/tests/ -q
```

Record the exact pass/fail/xfail counts. Expected: the same numbers
`history.md`'s most recent entry reports, plus the 7 new tests added
across Tasks 1, 2, 4, and 5 of this plan (1 + 4 + 1 + 2 — recount from
each task's own test file if this doesn't match, don't assume), zero
new failures, zero new warnings (this repo's suite invariant per
AGENTS.md: "N passed, zero warnings").

- [ ] **Step 2: Full live-app pass**

```bash
cd pytcad && python3 -m gui.app
```

Click through every sidebar tab (Project through Builder), toggle
dark/light with Ctrl+D, and run at least one solve (e.g. File -> Load
1D diode example, then Run) to confirm the reskinned chrome doesn't
break anything interactive, not just how it looks. Close when done.

- [ ] **Step 3: Append a history.md addendum**

Read the last ~40 lines of `history.md` first to match its existing
addendum heading style, then append a new one following that same
style, naming only files actually created/modified in this plan
(`pytcad/gui/qml/Theme.qml`, `pytcad/gui/qml/Icons.qml`,
`pytcad/gui/qml/qmldir`, `pytcad/gui/qml/Main.qml`,
`pytcad/gui/qml/panels/ViewportPanel.qml`, and the four new test files
from Tasks 1/2/4/5) plus the exact suite counts recorded in Step 1, and
noting explicitly that panel-content restyling (Mesh statistics grid,
Structure/Process/Sweep panels, etc.) is Slice 2, deliberately deferred
to a follow-up plan.

- [ ] **Step 4: Commit**

```bash
git add history.md
git commit -m "$(cat <<'EOF'
Record GUI visual reskin slice 0+1 landing in history.md

Design system (Theme.qml v2 + Icons.qml) and shell reskin (maximized
launch, vector sidebar/toolbar icons, viewport-as-card, wider
card-styled docks) are landed and suite-verified. Panel-content
restyling (Mesh stats grid first, per the design spec) is Slice 2, a
separate follow-up plan.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016e1uCN7Mfbz5DP23pQg8zb
EOF
)"
```
