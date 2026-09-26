// Applies the theme tokens (tokens.hpp) to Qt: the Fusion style and one
// QPalette for the whole app, which ADS's default stylesheet also reads
// (it styles through palette(...) roles). There is ONE scheme, black and
// white (user decision, 2026-09-26): no System/Light/Dark choice, and the
// OS colour scheme is not followed.
#pragma once

#include "tokens.hpp"

#include <QColor>
#include <QPalette>
#include <QString>

namespace tcad::desktop::theme {

QColor qcolor(T t);
QPalette palette();
// Plot data colours (tokens.hpp): data, not theme.
QColor seriesColour(std::size_t index);  // wraps around the palette
QColor dataColour(DataColour c);

// A stylesheet (ADS's default one) with every palette(<role>) reference
// replaced by that role's token colour: explicit colours, so what ADS
// paints never depends on when its widgets were polished (S3c found dock
// panels keeping a stock grey through palette(light)). An unknown role is
// left as it was.
QString themedStyleSheet(const QString& qss);

// The Fusion style and palette() on the running QApplication (no-op
// without one). Idempotent.
void apply();

}  // namespace tcad::desktop::theme
