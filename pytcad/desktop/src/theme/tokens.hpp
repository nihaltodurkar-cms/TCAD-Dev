// The native app's colour tokens (NATIVE-DESKTOP-PLAN.md sections 5.5
// and 15.13, S3c) -- the ONE place a UI colour is written. Qt-free, so the
// drift gate's tool (tcad_theme_dump) needs no window.
//
// ONE scheme, black and white (user decision, 2026-09-26: "no modes, just
// black and white"; data keeps its colours): white surfaces, black text,
// grey borders, a black accent. The only chromatic tokens are the status
// colours (warning, error, ok), which carry meaning; every other token is
// a grey (r == g == b), which gui/tests/test_desktop_theme.py enforces.
//
// Each token names the gui/qml/Theme.qml property it mirrors (`qml`), so
// the two apps look alike, and must equal it exactly. Overlay and context
// have no QML twin.
//
// Colour MAPS (viridis, ...) and the plot/region palettes below are data,
// not theme: they keep their colours.
#pragma once

#include <array>
#include <cstddef>
#include <string_view>

namespace tcad::desktop::theme {

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
    Context,   // 3D: the translucent device surface behind interior layers
    Count
};

struct Entry {
    T id;
    std::string_view name;
    std::string_view hex;
    std::string_view qml;  // the Theme.qml property mirrored exactly ("" for none)
    bool status;           // a status colour: the only tokens allowed a hue
};

inline constexpr std::array<Entry, static_cast<std::size_t>(T::Count)> kTable{{
    {T::Background, "background", "#ffffff", "background", false},
    {T::Window, "window", "#f2f2f2", "chromeBg", false},
    {T::Base, "base", "#ffffff", "panel", false},
    {T::AlternateBase, "alternateBase", "#f5f5f5", "panelAlt", false},
    {T::Border, "border", "#d4d4d4", "border", false},
    {T::BorderStrong, "borderStrong", "#9e9e9e", "borderStrong", false},
    {T::Text, "text", "#000000", "text", false},
    {T::TextDim, "textDim", "#555555", "textDim", false},
    {T::TextFaint, "textFaint", "#8c8c8c", "textFaint", false},
    {T::Focus, "focus", "#000000", "focus", false},
    {T::Accent, "accent", "#000000", "accent", false},
    {T::AccentSoft, "accentSoft", "#e8e8e8", "accentSoft", false},
    {T::Selection, "selection", "#d9d9d9", "selection", false},
    {T::Warning, "warning", "#b57f14", "warning", true},
    {T::Error, "error", "#c0392b", "error", true},
    {T::Ok, "ok", "#2e8b44", "ok", true},
    {T::OnAccent, "onAccent", "#ffffff", "textOnAccent", false},
    {T::Overlay, "overlay", "#ffffff", "", false},
    {T::Context, "context", "#c8c8c8", "", false},
}};

// The table is indexed by T: its order must match the enum.
constexpr bool table_in_enum_order() {
    for (std::size_t i = 0; i < kTable.size(); ++i)
        if (static_cast<std::size_t>(kTable[i].id) != i) return false;
    return true;
}
static_assert(table_in_enum_order(), "theme::kTable must list tokens in enum T order");

constexpr std::string_view hex(T t) { return kTable[static_cast<std::size_t>(t)].hex; }

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
        if (!is_rrggbb(e.hex)) return false;
    return true;
}
static_assert(table_well_formed(), "every theme::kTable colour must be #rrggbb");

// "#rrggbb" -> 0..1 components (the form every kTable entry uses).
constexpr Rgb rgb(T t) {
    const std::string_view h = hex(t);
    auto byte = [&](std::size_t i) { return (hex_digit(h[i]) * 16 + hex_digit(h[i + 1])) / 255.0; };
    return {byte(1), byte(3), byte(5)};
}

// 3D exploded view (NATIVE-DESKTOP-PLAN.md section 15.19): one colour per
// region, in viewer3d.py's order (the CSS colours it names). Data colours.
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

// PlotView's data colours (NATIVE-DESKTOP-PLAN.md 16.1, finding 7): the QML
// canvas's hard-coded ones, as tokens. Data colours, like the region
// palette. The series palette is
// MplCanvasItem._series_color's, in its order.
inline constexpr std::array<std::string_view, 7> kSeriesPalette{{
    "#4a90d9", "#61bd6d", "#d9a441", "#e05c56", "#9b59b6", "#1abc9c", "#e67e22"}};
enum class DataColour {
    Comparison,        // the dashed comparison sweep (QML's purple)
    Rejected,          // convergence: the rejected-step marker
    StageEquilibrium,  // convergence: the equilibrium stage
    StageBias,         // convergence: the bias stage
    StageOther,        // convergence: any other stage (sweep:<i>, ...)
};
constexpr std::string_view dataHex(DataColour c) {
    switch (c) {
        case DataColour::Comparison: return "#9b59b6";
        case DataColour::Rejected: return "#e74c3c";
        case DataColour::StageEquilibrium: return "#61bd6d";
        case DataColour::StageBias: return "#d9a441";
        case DataColour::StageOther: return "#4a90d9";
    }
    return "#4a90d9";
}
constexpr bool series_palette_well_formed() {
    for (std::string_view h : kSeriesPalette)
        if (!is_rrggbb(h)) return false;
    for (auto c : {DataColour::Comparison, DataColour::Rejected, DataColour::StageEquilibrium,
                   DataColour::StageBias, DataColour::StageOther})
        if (!is_rrggbb(dataHex(c))) return false;
    return true;
}
static_assert(series_palette_well_formed(), "every plot data colour must be #rrggbb");

}  // namespace tcad::desktop::theme
