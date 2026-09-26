#include "theme.hpp"

#include <QApplication>
#include <QRegularExpression>
#include <QStyle>
#include <QStyleFactory>

#include <utility>

namespace tcad::desktop::theme {

QColor qcolor(T t) {
    const std::string_view h = hex(t);
    return QColor(QString::fromLatin1(h.data(), static_cast<qsizetype>(h.size())));
}

QColor seriesColour(std::size_t index) {
    const std::string_view h = kSeriesPalette[index % kSeriesPalette.size()];
    return QColor(QString::fromLatin1(h.data(), static_cast<qsizetype>(h.size())));
}

QColor dataColour(DataColour c) {
    const std::string_view h = dataHex(c);
    return QColor(QString::fromLatin1(h.data(), static_cast<qsizetype>(h.size())));
}

QPalette palette() {
    QPalette p;
    auto set = [&](QPalette::ColorRole role, T t) { p.setColor(role, qcolor(t)); };
    set(QPalette::Window, T::Window);
    set(QPalette::WindowText, T::Text);
    set(QPalette::Base, T::Base);
    set(QPalette::AlternateBase, T::AlternateBase);
    set(QPalette::Text, T::Text);
    set(QPalette::PlaceholderText, T::TextFaint);
    set(QPalette::Button, T::Window);
    set(QPalette::ButtonText, T::Text);
    set(QPalette::ToolTipBase, T::Base);
    set(QPalette::ToolTipText, T::Text);
    set(QPalette::Highlight, T::Accent);
    set(QPalette::HighlightedText, T::OnAccent);
    set(QPalette::Link, T::Accent);
    set(QPalette::BrightText, T::Error);
    // Every role the ADS stylesheet reads (it paints dock panels with
    // palette(light) and splitter handles with palette(dark)) and Fusion
    // bevels with: an unset role falls back to a stock grey, which painted
    // a Fields panel #787878 once (found by S3c's screenshot).
    set(QPalette::Light, T::Base);
    set(QPalette::Midlight, T::AlternateBase);
    set(QPalette::Mid, T::Border);
    set(QPalette::Dark, T::BorderStrong);
    set(QPalette::Shadow, T::Background);
    for (auto role : {QPalette::Text, QPalette::ButtonText, QPalette::WindowText})
        p.setColor(QPalette::Disabled, role, qcolor(T::TextFaint));
    return p;
}

QString themedStyleSheet(const QString& qss) {
    // The same role -> token mapping palette() uses above.
    static const std::pair<const char*, T> kRoles[] = {
        {"window", T::Window},     {"window-text", T::Text},    {"foreground", T::Text},
        {"text", T::Text},         {"base", T::Base},           {"alternate-base", T::AlternateBase},
        {"button", T::Window},     {"button-text", T::Text},    {"light", T::Base},
        {"midlight", T::AlternateBase}, {"mid", T::Border},     {"dark", T::BorderStrong},
        {"shadow", T::Background}, {"highlight", T::Accent},    {"highlighted-text", T::OnAccent},
        {"link", T::Accent},       {"bright-text", T::Error},   {"placeholder-text", T::TextFaint}};
    static const QRegularExpression ref(QStringLiteral(R"(palette\(\s*([a-z-]+)\s*\))"));
    QString out;
    qsizetype last = 0;
    for (auto it = ref.globalMatch(qss); it.hasNext();) {
        const QRegularExpressionMatch m = it.next();
        out += qss.mid(last, m.capturedStart() - last);
        QString replacement = m.captured(0);
        for (const auto& [role, token] : kRoles)
            if (m.captured(1) == QLatin1String(role)) replacement = qcolor(token).name();
        out += replacement;
        last = m.capturedEnd();
    }
    out += qss.mid(last);
    return out;
}

void apply() {
    auto* app = qobject_cast<QApplication*>(QCoreApplication::instance());
    if (!app) return;
    if (app->style()->name().compare("fusion", Qt::CaseInsensitive) != 0) app->setStyle(QStyleFactory::create("Fusion"));
    app->setPalette(palette());
}

}  // namespace tcad::desktop::theme
