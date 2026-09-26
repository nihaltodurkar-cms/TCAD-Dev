#include "playback_panel.hpp"

#include "views/field/field_view.hpp"

#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSignalBlocker>
#include <QSlider>
#include <QTimer>

#include <algorithm>

namespace tcad::desktop {

PlaybackPanel::PlaybackPanel(FieldView* view, QWidget* parent) : QWidget(parent), view_(view) {
    setObjectName("PlaybackPanel");
    // Three short rows: the panel lives in the left column (main_window.cpp).
    auto* rows = new QVBoxLayout(this);
    auto* row = new QHBoxLayout;
    auto* row2 = new QHBoxLayout;
    back_ = new QPushButton(QStringLiteral("<<"), this);
    back_->setObjectName("PlaybackBack");
    play_ = new QPushButton(tr("Play"), this);
    play_->setObjectName("PlaybackPlay");
    forward_ = new QPushButton(QStringLiteral(">>"), this);
    forward_->setObjectName("PlaybackForward");
    slider_ = new QSlider(Qt::Horizontal, this);
    slider_->setObjectName("PlaybackSlider");
    label_ = new QLabel(this);
    label_->setObjectName("PlaybackLabel");
    result_ = new QPushButton(tr("Result"), this);
    result_->setObjectName("PlaybackResult");
    result_->setToolTip(tr("Show the result's own field instead of a sweep snapshot"));
    for (QWidget* w : std::initializer_list<QWidget*>{back_, play_, forward_, result_}) row->addWidget(w);
    row2->addWidget(slider_, 1);
    rows->addLayout(row);
    rows->addLayout(row2);
    rows->addWidget(label_);
    rows->addStretch(1);

    timer_ = new QTimer(this);
    timer_->setInterval(kFrameMs);
    connect(timer_, &QTimer::timeout, this, &PlaybackPanel::tick);
    connect(play_, &QPushButton::clicked, this, [this] { setPlaying(!playing()); });
    connect(back_, &QPushButton::clicked, this, [this] { step(-1); });
    connect(forward_, &QPushButton::clicked, this, [this] { step(+1); });
    connect(result_, &QPushButton::clicked, this, [this] {
        setPlaying(false);
        view_->setSnapshot(std::nullopt);
    });
    connect(slider_, &QSlider::valueChanged, this, [this](int k) {
        setPlaying(false);  // a scrub stops playback, as in viewer3d.py
        view_->setSnapshot(static_cast<std::size_t>(k));
    });
    connect(view_, &FieldView::displayChanged, this, &PlaybackPanel::sync);
    sync();
}

bool PlaybackPanel::playing() const { return timer_->isActive(); }

void PlaybackPanel::setPlaying(bool on) {
    if (on && !view_->snapshots()) on = false;
    if (on) timer_->start();
    else timer_->stop();
    play_->setText(on ? tr("Pause") : tr("Play"));
}

void PlaybackPanel::tick() {
    const SweepSnapshots* s = view_->snapshots();
    if (!s || s->count() == 0) {
        setPlaying(false);
        return;
    }
    const std::size_t next = view_->snapshot() ? (*view_->snapshot() + 1) % s->count() : 0;  // loops
    view_->setSnapshot(next);
}

void PlaybackPanel::step(int delta) {
    setPlaying(false);
    const SweepSnapshots* s = view_->snapshots();
    if (!s || s->count() == 0) return;
    const long long cur = view_->snapshot() ? static_cast<long long>(*view_->snapshot()) : (delta > 0 ? -1 : static_cast<long long>(s->count()));
    const long long next = std::clamp<long long>(cur + delta, 0, static_cast<long long>(s->count()) - 1);
    view_->setSnapshot(static_cast<std::size_t>(next));
}

void PlaybackPanel::sync() {
    const SweepSnapshots* s = view_->is3D() ? view_->snapshots() : nullptr;
    const bool have = s && s->count() > 0;
    setEnabled(have);
    setToolTip(have ? QString() : tr("Playback needs a 3D sweep result (sweep snapshots)"));
    if (!have) {
        if (playing()) setPlaying(false);
        label_->setText(tr("no sweep snapshots"));
        return;
    }
    const QSignalBlocker block(slider_);
    slider_->setRange(0, static_cast<int>(s->count()) - 1);
    const auto k = view_->snapshot();
    if (k) slider_->setValue(static_cast<int>(*k));
    if (!k) {
        label_->setText(tr("result (%1 snapshots)").arg(s->count()));
    } else if (!view_->showingSnapshot()) {
        label_->setText(tr("no snapshot of %1").arg(QString::fromStdString(view_->field())));
    } else {
        label_->setText(tr("%1 V  (%2 / %3)").arg(s->voltages[*k], 0, 'f', 3).arg(*k + 1).arg(s->count()));
    }
}

}  // namespace tcad::desktop
