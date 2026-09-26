// Frame-time benchmark for the P0 exit gate (NATIVE-DESKTOP-PLAN.md
// section 6): drives the REAL MainWindow/FieldView on screen and times
// each interaction the way the Python baseline
// (desktop/bench/baseline_mpl.py) times MplCanvasItem.
//
// What a "frame" is here: the camera/scalar change plus
// vtkRenderWindow::Render() plus WaitForCompletion() (glFinish), i.e.
// CPU work and GPU completion. Qt's composite of the finished frame
// (one texture blit) is not included -- stated, not hidden.
#pragma once

#include <nlohmann/json.hpp>

#include <QString>

namespace tcad::desktop {

class MainWindow;

struct BenchOptions {
    QString result_path;
    int frames = 120;
    int hover_samples = 2000;
    int width = 1200;   // FieldView size in logical pixels, as the baseline's canvas
    int height = 800;
    double process_start_s = 0.0;  // seconds since epoch the process was created
};

nlohmann::ordered_json run_benchmark(MainWindow& window, const BenchOptions& options);

class FieldView;
// Process events until the view has a GL context. Throws after
// `timeout_ms` instead of spinning forever: under QT_QPA_PLATFORM=
// offscreen (no GL surface) the view never becomes valid (seen in S2).
void wait_for_gl(FieldView* view, int timeout_ms = 10000);

// Wall clock and process creation time, seconds since the Unix epoch.
double now_epoch_s();
double process_start_epoch_s();

}  // namespace tcad::desktop
