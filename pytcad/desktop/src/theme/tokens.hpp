// The native app's colour tokens (NATIVE-DESKTOP-PLAN.md sections 5.5
// and 15.13, S3c), light and dark -- the ONE place a UI colour is
// written. Qt-free, so the drift gate's tool (tcad_theme_dump) needs no
// window.
//
// Each token names the gui/qml/Theme.qml property it mirrors (`qml`), so
// the two apps look alike. Tokens mirroring an opaque QML colour must
// equal it exactly. The window/base/alternate-base surfaces mirror the
// RGB of translucent QML panels (chromeBg, panel, panelAlt): a widget
// window has no wallpaper to blend over, so the native app uses the RGB
// and drops the alpha -- the same "RGB unchanged" rule Theme.qml's own
// test pins. onAccent (text on an accent fill) has no QML twin.
// gui/tests/test_desktop_theme.py enforces all of this.
//
// Colour MAPS (viridis, ...) are data, not theme: src/views/colormaps.
#pragma once

#include <array>
#include <cstddef>
#include <string_view>

namespace tcad::desktop::theme {

enum class Scheme { Light, Dark };

enum class T {
    Background,     // the view behind a field map; the app background
    Window,         // menus, toolbars, dock panels
    Base,           // list and input backgrounds
    AlternateBase,  // alternate rows
    Border,
    BorderStrong,
    Text,
    TextDim,
    TextFaint,  // disabled and placeholder text
    Focus,
    Accent,
    AccentSoft,
    Selection,
    Warning,
    Error,
    Ok,
    OnAccent,  // text on an accent fill
    Overlay,   // contour and mesh lines drawn over field maps (the QML view's white)
    Context,   // 3D: the translucent device surface behind interior layers (viewer3d.py's lightsteelblue)
    Count
};

struct Entry {
    T id;
    std::string_view name;
    std::string_view dark;
    std::string_view light;
    std::string_view qml;      // the Theme.qml property mirrored ("" for none)
    bool qml_rgb_only;         // true: mirrors a translucent QML colour's RGB
};

inline constexpr std::array<Entry, static_cast<std::size_t>(T::Count)> kTable{{
    {T::Background, "background", "#0a0b0e", "#eef1f4", "background", false},
    {T::Window, "window", "#16171d", "#f7f9fa", "chromeBg", true},
    {T::Base, "base", "#0d0e12", "#ffffff", "panel", true},
    {T::AlternateBase, "alternateBase", "#111217", "#eceff2", "panelAlt", true},
    {T::Border, "border", "#1f2026", "#c9d0d8", "border", false},
    {T::BorderStrong, "borderStrong", "#2c2d36", "#a8b2bc", "borderStrong", false},
    {T::Text, "text", "#e4e4e7", "#1a2129", "text", false},
    {T::TextDim, "textDim", "#a1a1aa", "#5a6572", "textDim", false},
    {T::TextFaint, "textFaint", "#71717a", "#8894a0", "textFaint", false},
    {T::Focus, "focus", "#8b5cf6", "#7c3aed", "focus", false},
    {T::Accent, "accent", "#8b5cf6", "#7c3aed", "accent", false},
    {T::AccentSoft, "accentSoft", "#241f38", "#ede9fe", "accentSoft", false},
    {T::Selection, "selection", "#3a2f57", "#ede9fe", "selection", false},
    {T::Warning, "warning", "#d9a441", "#b57f14", "warning", false},
    {T::Error, "error", "#e05c56", "#c0392b", "error", false},
    {T::Ok, "ok", "#61bd6d", "#2e8b44", "ok", false},
    {T::OnAccent, "onAccent", "#ffffff", "#ffffff", "", false},
    {T::Overlay, "overlay", "#ffffff", "#ffffff", "", false},
    {T::Context, "context", "#b0c4de", "#b0c4de", "", false},
}};

// The table is indexed by T: its order must match the enum.
constexpr bool table_in_enum_order() {
    for (std::size_t i = 0; i < kTable.size(); ++i)
        if (static_cast<std::size_t>(kTable[i].id) != i) return false;
    return true;
}
static_assert(table_in_enum_order(), "theme::kTable must list tokens in enum T order");

constexpr std::string_view hex(T t, Scheme s) {
    const Entry& e = kTable[static_cast<std::size_t>(t)];
    return s == Scheme::Dark ? e.dark : e.light;
}

struct Rgb {
    double r, g, b;  // 0..1
};

constexpr int hex_digit(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

constexpr bool is_rrggbb(std::string_view h) {
    if (h.size() != 7 || h[0] != '#') return false;
    for (std::size_t i = 1; i < 7; ++i)
        if (hex_digit(h[i]) < 0) return false;
    return true;
}
constexpr bool table_well_formed() {
    for (const Entry& e : kTable)
        if (!is_rrggbb(e.dark) || !is_rrggbb(e.light)) return false;
    return true;
}
static_assert(table_well_formed(), "every theme::kTable colour must be #rrggbb");

// "#rrggbb" -> 0..1 components (the form every kTable entry uses).
constexpr Rgb rgb(T t, Scheme s) {
    const std::string_view h = hex(t, s);
    auto byte = [&](std::size_t i) { return (hex_digit(h[i]) * 16 + hex_digit(h[i + 1])) / 255.0; };
    return {byte(1), byte(3), byte(5)};
}

// 3D exploded view (NATIVE-DESKTOP-PLAN.md section 15.19): one colour per
// region, in viewer3d.py's order (the CSS colours it names). Data colours,
// the same in both schemes.
inline constexpr std::array<std::string_view, 12> kRegionPalette{{
    "#f08080",  // lightcoral
    "#add8e6",  // lightblue
    "#90ee90",  // lightgreen
    "#ffffe0",  // lightyellow
    "#dda0dd",  // plum
    "#ffdab9",  // peachpuff
    "#e0ffff",  // lightcyan
    "#f5deb3",  // wheat
    "#e6e6fa",  // lavender
    "#ffe4e1",  // mistyrose
    "#f0fff0",  // honeydew
    "#b0e0e6",  // powderblue
}};
constexpr bool palette_well_formed() {
    for (std::string_view h : kRegionPalette)
        if (!is_rrggbb(h)) return false;
    return true;
}
static_assert(palette_well_formed(), "every theme::kRegionPalette colour must be #rrggbb");

constexpr Rgb regionRgb(std::size_t index) {
    const std::string_view h = kRegionPalette[index % kRegionPalette.size()];
    auto byte = [&](std::size_t i) { return (hex_digit(h[i]) * 16 + hex_digit(h[i + 1])) / 255.0; };
    return {byte(1), byte(3), byte(5)};
}

}  // namespace tcad::desktop::theme
