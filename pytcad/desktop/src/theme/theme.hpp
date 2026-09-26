// Applies the theme tokens (tokens.hpp) to Qt: the Fusion style and one
// QPalette for the whole app, which ADS's default stylesheet also reads
// (it styles through palette(...) roles). The controller resolves the
// user's choice -- System, Light or Dark -- to a scheme, follows the OS
// live when the choice is System, and tells views (VTK colours) through
// schemeChanged.
#pragma once

#include "tokens.hpp"

#include <QColor>
#include <QObject>
#include <QPalette>
#include <QString>

#include <optional>

namespace tcad::desktop::theme {

enum class Choice { System, Light, Dark };

QColor qcolor(T t, Scheme s);
QPalette palette(Scheme s);

// A stylesheet (ADS's default one) with every palette(<role>) reference
// replaced by that role's token colour for `s`: explicit colours, so what
// ADS paints never depends on when its widgets were polished (S3c found
// dock panels keeping a stock grey through palette(light)). An unknown
// role is left as it was.
QString themedStyleSheet(const QString& qss, Scheme s);

QString toString(Choice c);                              // "system" / "light" / "dark"
std::optional<Choice> choiceFromString(const QString& s);  // the inverse; nullopt if unknown

class ThemeController : public QObject {
    Q_OBJECT

public:
    explicit ThemeController(QObject* parent = nullptr);

    // Applies at once (and on every OS scheme change while System).
    void setChoice(Choice c);
    Choice choice() const { return choice_; }
    Scheme scheme() const { return scheme_; }

signals:
    void schemeChanged(tcad::desktop::theme::Scheme scheme);

private:
    void apply();

    Choice choice_ = Choice::System;
    Scheme scheme_ = Scheme::Dark;
};

}  // namespace tcad::desktop::theme
