"""NATIVE-DESKTOP-PLAN.md P1 S3c theme gates for the native app, for ONE
black-and-white scheme (the user's decision, 2026-09-26).

1. Drift: every native theme token that mirrors a gui/qml/Theme.qml colour
   equals it exactly. A QML rename or recolour therefore fails here, not
   silently.
2. Black and white: every native token is a grey (r == g == b) except the
   status colours, which carry meaning. Data colours (plot series, region
   palette, colour maps) are not theme tokens and keep their colours.
3. No hard-coded colours in the native sources outside src/theme/ and the
   colour-map module (colour maps encode values, not UI). This was the
   QML GUI's Phase 3/4 review finding; here it is a gate. The patterns
   are checked against known-bad snippets first, so a pattern that
   matches nothing cannot pass vacuously.

What the running window paints (palette, VTK background, ADS panels, the
plot) is in the shell e2e test (desktop/tests/test_shell.cpp).
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

# Theme.qml colours: `[readonly] property color <name>: "#rrggbb"` (the
# opaque tokens a native token can mirror; Qt.rgba overlays are QML-only).
_PROP = re.compile(r"(?:readonly\s+)?property\s+color\s+(\w+)\s*:\s*\"(#[0-9a-fA-F]{6})\"")


def _qml_colours():
    return {m.group(1): m.group(2).lower() for m in _PROP.finditer(open(THEME_QML, encoding="utf-8").read())}


def _tokens():
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["theme_dump"])],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


needs_build = pytest.mark.skipif(not os.path.isfile(MANIFEST),
                                 reason="native desktop app not built (powershell -File desktop\build.ps1)")


@needs_build
def test_native_tokens_mirror_theme_qml():
    tokens = _tokens()
    qml = _qml_colours()
    assert {"background", "text", "accent", "chromeBg", "panel"} <= set(qml),         "the Theme.qml parser found too little -- fix the parser, not the gate"
    mirrored = 0
    for t in tokens:
        if not t["qml"]:
            continue
        assert t["qml"] in qml, f"native token {t['name']} mirrors Theme.qml '{t['qml']}', which is gone or not opaque"
        assert t["hex"].lower() == qml[t["qml"]], f"{t['name']} {t['hex']} != Theme.qml {t['qml']} {qml[t['qml']]}"
        mirrored += 1
    assert mirrored >= 15


@needs_build
def test_native_tokens_are_black_and_white():
    tokens = {t["name"]: t for t in _tokens()}
    assert {t for t in tokens if tokens[t]["status"]} == {"warning", "error", "ok"}
    coloured = [f"{n}={t['hex']}" for n, t in tokens.items()
                if not t["status"] and len(set(_hex_rgb(t["hex"]))) != 1]
    assert not coloured, f"tokens with a hue (only status colours may have one): {coloured}"
    assert tokens["base"]["hex"] == "#ffffff" and tokens["text"]["hex"] == "#000000"


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
