#include "console_panel.hpp"

#include "theme/theme.hpp"

#include <QFontDatabase>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QScrollBar>
#include <QTextBlock>
#include <QTextCharFormat>
#include <QTextCursor>
#include <QVBoxLayout>

#include <algorithm>

namespace tcad::desktop {

ConsolePanel::ConsolePanel(QWidget* parent) : QWidget(parent) {
    setObjectName("ConsolePanel");
    text_ = new QPlainTextEdit(this);
    text_->setObjectName("ConsoleText");
    text_->setReadOnly(true);
    text_->setLineWrapMode(QPlainTextEdit::NoWrap);
    text_->setMaximumBlockCount(kMaxLines);
    text_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
    text_->setAccessibleName(tr("Run console"));
    dropped_label_ = new QLabel(this);
    dropped_label_->setObjectName("ConsoleDropped");
    clear_ = new QPushButton(tr("Clear"), this);
    clear_->setObjectName("ConsoleClear");
    connect(clear_, &QPushButton::clicked, this, &ConsolePanel::clear);
    auto* bar = new QHBoxLayout;
    bar->setContentsMargins(0, 0, 0, 0);
    bar->addWidget(dropped_label_, 1);
    bar->addWidget(clear_);
    auto* col = new QVBoxLayout(this);
    col->setContentsMargins(4, 4, 4, 4);
    col->addLayout(bar);
    col->addWidget(text_, 1);
    timer_.setSingleShot(true);
    timer_.setInterval(kFlushMs);
    connect(&timer_, &QTimer::timeout, this, &ConsolePanel::flush);
    updateDropped();
}

void ConsolePanel::append(const QString& text, Style style) {
    QString body = text;
    while (body.endsWith('\n') || body.endsWith('\r')) body.chop(1);  // a traceback's last newline
    const QStringList parts = body.split('\n');
    for (QString part : parts) {
        if (part.endsWith('\r')) part.chop(1);
        pending_.emplace_back(std::move(part), style);
    }
    // More than the console keeps is waiting: only the newest can survive.
    if (pending_.size() > static_cast<std::size_t>(kMaxLines)) {
        const auto excess = static_cast<std::ptrdiff_t>(pending_.size() - kMaxLines);
        total_ += excess;
        pending_.erase(pending_.begin(), pending_.begin() + excess);
    }
    if (!timer_.isActive()) timer_.start();
}

void ConsolePanel::flush() {
    timer_.stop();
    if (pending_.empty()) return;
    QScrollBar* bar = text_->verticalScrollBar();
    const bool at_bottom = bar->value() >= bar->maximum() - 2;
    QTextCharFormat plain;
    plain.setForeground(theme::qcolor(theme::T::Text));
    QTextCharFormat stage = plain;
    stage.setFontWeight(QFont::Bold);
    QTextCharFormat dim;
    dim.setForeground(theme::qcolor(theme::T::TextDim));
    QTextCharFormat note = dim;
    note.setFontItalic(true);
    QTextCharFormat error;
    error.setForeground(theme::qcolor(theme::T::Error));
    QTextCursor c(text_->document());
    c.movePosition(QTextCursor::End);
    c.beginEditBlock();
    for (const auto& [line, style] : pending_) {
        if (total_ > 0 || c.position() > 0) c.insertBlock();
        const QTextCharFormat& f = style == Style::Stage    ? stage
                                   : style == Style::Stderr ? dim
                                   : style == Style::Note   ? note
                                   : style == Style::Error  ? error
                                                            : plain;
        c.insertText(line, f);
        ++total_;
    }
    c.endEditBlock();
    pending_.clear();
    if (at_bottom) bar->setValue(bar->maximum());
    updateDropped();
}

void ConsolePanel::clear() {
    timer_.stop();
    pending_.clear();
    text_->clear();
    total_ = 0;
    updateDropped();
}

QStringList ConsolePanel::lines() const {
    QStringList out;
    if (total_ == 0) return out;
    for (QTextBlock b = text_->document()->begin(); b.isValid(); b = b.next()) out << b.text();
    return out;
}

int ConsolePanel::lineCount() const { return total_ == 0 ? 0 : text_->document()->blockCount(); }

qint64 ConsolePanel::droppedLines() const { return std::max<qint64>(0, total_ - lineCount()); }

void ConsolePanel::updateDropped() {
    const qint64 n = droppedLines();
    dropped_label_->setText(n > 0 ? tr("%1 earlier lines dropped (the console keeps the last %2)").arg(n).arg(kMaxLines)
                                  : QString());
    dropped_label_->setVisible(n > 0);
}

}  // namespace tcad::desktop
