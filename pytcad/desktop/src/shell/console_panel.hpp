// The Console dock (NATIVE-DESKTOP-PLAN.md 17.11, P3-S4): every line a run
// prints, stage lines in bold, stderr in the dim text colour, the app's own
// notes in italics and a failure in the error colour.
//
// Bounded (17.7 point 11): the last kMaxLines lines are kept and the number
// of earlier ones dropped is shown. Lines are batched and inserted every
// kFlushMs, so a flood costs one document edit per batch, not per line.
#pragma once

#include <QPlainTextEdit>
#include <QString>
#include <QStringList>
#include <QTimer>
#include <QWidget>

#include <vector>

class QLabel;
class QPushButton;

namespace tcad::desktop {

class ConsolePanel : public QWidget {
    Q_OBJECT

public:
    enum class Style { Plain, Stage, Stderr, Note, Error };
    static constexpr int kMaxLines = 50000;
    static constexpr int kFlushMs = 50;

    explicit ConsolePanel(QWidget* parent = nullptr);

    // A multi-line text is split into lines, each with `style`.
    void append(const QString& text, Style style = Style::Plain);
    void clear();
    // Insert what is batched now (tests; the timer does it otherwise).
    void flush();

    // The lines kept (after a flush), and how many earlier ones were dropped.
    QStringList lines() const;
    int lineCount() const;
    qint64 droppedLines() const;
    QPlainTextEdit* textView() const { return text_; }

private:
    void updateDropped();

    QPlainTextEdit* text_ = nullptr;
    QLabel* dropped_label_ = nullptr;
    QPushButton* clear_ = nullptr;
    QTimer timer_;
    std::vector<std::pair<QString, Style>> pending_;
    qint64 total_ = 0;          // lines ever appended since the last clear
};

}  // namespace tcad::desktop
