"""NATIVE-DESKTOP-PLAN.md P1 S3c theme gates for the native app.

1. Drift: every native theme token that mirrors a gui/qml/Theme.qml colour
   equals it, in both schemes. Opaque QML colours must match exactly.
   Translucent QML panels (chromeBg, panel, panelAlt) are matched on RGB,
   because a widget window has no wallpaper to blend with. That is the
   same "RGB unchanged" rule Theme.qml's own comment and
   test_theme_tokens.py pin. A QML rename or recolour therefore fails
   here, not silently.
2. No hard-coded colours in the native sources outside src/theme/ and the
   colour-map module (colour maps encode values, not UI). This was the
   QML GUI's Phase 3/4 review finding; here it is a gate. The patterns
   are checked against known-bad snippets first, so a pattern that
   matches nothing cannot pass vacuously.

The live switch (palette, VTK background and scalar-bar text read back
from the running window) is in the shell e2e test
(desktop/tests/test_shell.cpp).
"""
import json
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")
THEME_QML = os.path.join(ROOT, "gui", "qml", "Theme.qml")
SRC = os.path.join(ROOT, "desktop", "src")

# Theme.qml colours: `[readonly] property color <name>: dark ? <dark> : <light>`,
# each side either "#rrggbb" or Qt.rgba(<r>, <g>, <b>, <a>) whose channels are
# 0xNN / 255 or a 0..1 float. Continuation lines are joined first.
_PROP = re.compile(r"(?:readonly\s+)?property\s+color\s+(\w+)\s*:\s*dark\s*\?\s*(.+?)\s*:\s*"
                   r"(\"#[0-9a-fA-F]{6}\"|Qt\.rgba\([^)]*\))")
_RGBA = re.compile(r"Qt\.rgba\(([^,]+),([^,]+),([^,]+),([^)]+)\)")


def _channel(expr):
    expr = expr.strip()
    m = re.fullmatch(r"0x([0-9a-fA-F]{2})\s*/\s*255", expr)
    if m:
        return int(m.group(1), 16)
    return round(float(expr) * 255)


def _qml_rgb(value):
    """(r, g, b) of a Theme.qml colour expression, alpha dropped."""
    value = value.strip()
    if value.startswith('"#'):
        h = value.strip('"')[1:]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = _RGBA.fullmatch(value)
    assert m, f"unparsed Theme.qml colour: {value}"
    return tuple(_channel(m.group(i)) for i in (1, 2, 3))


def _qml_colours():
    text = open(THEME_QML, encoding="utf-8").read()
    # join a `dark ? A` line with its `: B` continuation
    text = re.sub(r"\)\s*\n\s*:", ") :", text)
    out = {}
    for m in _PROP.finditer(text):
        name, dark, light = m.group(1), m.group(2), m.group(3)
        out[name] = {"dark": dark, "light": light,
                     "opaque": dark.startswith('"#') and light.startswith('"#')}
    return out


def _hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


@pytest.mark.skipif(not os.path.isfile(MANIFEST),
                    reason="native desktop app not built (powershell -File desktop\\build.ps1)")
def test_native_tokens_mirror_theme_qml():
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["theme_dump"])],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    tokens = json.loads(out.stdout)
    qml = _qml_colours()
    assert {"background", "text", "accent", "chromeBg", "panel"} <= set(qml), \
        "the Theme.qml parser found too little -- fix the parser, not the gate"
    mirrored = 0
    for t in tokens:
        if not t["qml"]:
            continue
        assert t["qml"] in qml, f"native token {t['name']} mirrors Theme.qml '{t['qml']}', which no longer exists"
        q = qml[t["qml"]]
        if t["qml_rgb_only"]:
            assert not q["opaque"], f"{t['qml']} is opaque now: mirror it exactly (qml_rgb_only=false)"
        else:
            assert q["opaque"], f"{t['qml']} is translucent: mirror its RGB (qml_rgb_only=true)"
        for scheme in ("dark", "light"):
            assert _hex_rgb(t[scheme]) == _qml_rgb(q[scheme]), \
                f"{t['name']} ({scheme}) {t[scheme]} != Theme.qml {t['qml']} {q[scheme]}"
        mirrored += 1
    assert mirrored >= 15


# -- no hard-coded colours --------------------------------------------------------

EXEMPT = {os.path.join("views", "colormaps.cpp"), os.path.join("views", "colormaps.hpp"),
          os.path.join("views", "colormap_tables.hpp")}  # generated from matplotlib (S5b)
PATTERNS = {
    # anywhere in a line (a stylesheet string embeds it: "color: #ff0000");
    # the \b ends exclude preprocessor lines (#define: "#def" + "i")
    "hex colour literal": re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b"),
    "QColor from literals": re.compile(r"QColor\s*[({]\s*[0-9\"#]"),
    "setRgb": re.compile(r"\bsetRgbF?\s*\("),
    "named Qt colour": re.compile(r"\bQt::(white|black|red|green|blue|cyan|magenta|yellow|gray|darkGray|lightGray)\b"),
    "VTK colour from literals": re.compile(r"\b(SetBackground|SetColor|SetTableValue|AddRGBPoint)\s*\(\s*[-+.\d]"),
}
KNOWN_BAD = [
    'p.setColor(QPalette::Window, QColor(30, 32, 36));',   # main.cpp before S3c
    'p.setColor(QPalette::HighlightedText, Qt::white);',
    'renderer_->SetBackground(0.11, 0.12, 0.14);',            # field_view.cpp before S3c
    'label->setStyleSheet("color: #ff0000");',
    'c.setRgb(1, 2, 3);',
]


KNOWN_GOOD = [
    "#include <QColor>",
    "#define TCAD_HAVE_ZLIB 1",
    "#endif",
    "renderer_->SetBackground(bg.r, bg.g, bg.b);",
    "tp->SetColor(fg.r, fg.g, fg.b);",
]


def test_colour_patterns_catch_known_bad_code():
    for snippet in KNOWN_BAD:
        assert any(p.search(snippet) for p in PATTERNS.values()), f"no pattern flags: {snippet}"
    for snippet in KNOWN_GOOD:
        hits = [w for w, p in PATTERNS.items() if p.search(snippet)]
        assert not hits, f"{snippet!r} wrongly flagged as {hits}"


def test_no_hard_coded_colours_outside_the_theme():
    offenders = []
    for dirpath, _, files in os.walk(SRC):
        for f in files:
            if not f.endswith((".cpp", ".hpp")):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, SRC)
            if rel.startswith("theme" + os.sep) or rel in EXEMPT:
                continue
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    code = line.split("//", 1)[0]
                    for what, p in PATTERNS.items():
                        if p.search(code):
                            offenders.append(f"{rel}:{n}: {what}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
