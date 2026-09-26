#include "bench.hpp"

#include "shell/main_window.hpp"
#include "views/field/field_view.hpp"

#include <DockManager.h>
#include <DockWidget.h>

#include <QApplication>
#include <QElapsedTimer>
#include <vtkCamera.h>
#include <vtkPolyData.h>
#include <vtkRenderWindow.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkRenderer.h>

#include <algorithm>
#include <chrono>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace tcad::desktop {
namespace {

double to_epoch_s(const FILETIME& ft) {
    ULARGE_INTEGER u;
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    return static_cast<double>(u.QuadPart) / 1e7 - 11644473600.0;  // 1601 -> 1970
}

nlohmann::ordered_json stats(std::vector<double> ms) {
    std::sort(ms.begin(), ms.end());
    auto pct = [&](double p) {
        if (ms.empty()) return 0.0;
        const auto i = static_cast<std::size_t>(p * static_cast<double>(ms.size() - 1) + 0.5);
        return ms[std::min(i, ms.size() - 1)];
    };
    return {{"n", ms.size()}, {"p50_ms", pct(0.50)}, {"p95_ms", pct(0.95)}, {"max_ms", ms.empty() ? 0.0 : ms.back()}};
}

template <class F>
std::vector<double> time_frames(int n, F&& step) {
    std::vector<double> ms;
    ms.reserve(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) {
        const auto t0 = std::chrono::steady_clock::now();
        step(i);
        const auto t1 = std::chrono::steady_clock::now();
        ms.push_back(std::chrono::duration<double, std::milli>(t1 - t0).count());
        QApplication::processEvents();  // keep the window live; not timed
    }
    return ms;
}

std::string gl_renderer(vtkRenderWindow* w) {
    std::istringstream caps(w->ReportCapabilities());
    std::string line;
    while (std::getline(caps, line))
        if (line.rfind("OpenGL renderer string:", 0) == 0) return line.substr(24);
    return "unknown";
}

}  // namespace

double now_epoch_s() {
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    return to_epoch_s(ft);
}

double process_start_epoch_s() {
    FILETIME creation, exit_t, kernel, user;
    if (!GetProcessTimes(GetCurrentProcess(), &creation, &exit_t, &kernel, &user)) return 0.0;
    return to_epoch_s(creation);
}

void wait_for_gl(FieldView* view, int timeout_ms) {
    QElapsedTimer t;
    t.start();
    while (!view->isValid()) {
        if (t.elapsed() > timeout_ms)
            throw std::runtime_error("no OpenGL context after " + std::to_string(timeout_ms) +
                                     " ms: the viewer needs a real GL surface (QT_QPA_PLATFORM=offscreen "
                                     "is not supported)");
        QApplication::processEvents();
    }
}

nlohmann::ordered_json run_benchmark(MainWindow& window, const BenchOptions& o) {
    nlohmann::ordered_json out;
    FieldView* view = window.fieldView();
    view->setMinimumSize(o.width, o.height);
    view->setMaximumSize(o.width, o.height);
    window.show();
    wait_for_gl(view);

    QElapsedTimer t;
    t.start();
    window.openResult(o.result_path);
    const double open_ms = static_cast<double>(t.nsecsElapsed()) / 1e6;
    view->renderNow();
    const double first_frame_s = now_epoch_s();

    const ResultModel* m = window.result();
    const auto nodes = m->node_counts();
    out["file"] = o.result_path.toStdString();
    out["dimensionality"] = m->dimensionality();
    out["nodes"] = {nodes[0], nodes[1], nodes[2]};
    out["field"] = view->field();
    const int* px = view->renderWindow()->GetSize();
    out["viewport_device_px"] = {px[0], px[1]};
    out["device_pixel_ratio"] = view->devicePixelRatioF();
    out["gl_renderer"] = gl_renderer(view->renderWindow());
    out["open_result_ms"] = open_ms;
    if (o.process_start_s > 0.0) out["cold_start_to_first_frame_ms"] = (first_frame_s - o.process_start_s) * 1e3;
    if (m->dimensionality() < 2) {
        out["note"] = "1D result: no FieldView frames to time (curves are PlotView, P2)";
        return out;
    }

    vtkCamera* cam = view->renderer()->GetActiveCamera();
    const bool three_d = view->is3D();

    view->renderNow();  // warm-up
    out["pan"] = stats(time_frames(o.frames, [&](int i) {
        const double step = (three_d ? 0.002 * cam->GetDistance() : 0.004 * cam->GetParallelScale()) *
                            ((i / 30) % 2 ? -1.0 : 1.0);
        double f[3], p[3];
        cam->GetFocalPoint(f);
        cam->GetPosition(p);
        cam->SetFocalPoint(f[0] + step, f[1], f[2]);
        cam->SetPosition(p[0] + step, p[1], p[2]);
        view->renderNow();
    }));
    out["zoom"] = stats(time_frames(o.frames, [&](int i) {
        cam->Zoom((i / 30) % 2 ? 1.0 / 0.99 : 0.99);
        view->renderNow();
    }));
    if (three_d) {
        out["orbit"] = stats(time_frames(o.frames, [&](int) {
            cam->Azimuth(1.5);
            cam->OrthogonalizeViewUp();
            view->renderNow();
        }));
    }

    const auto& names = m->scalar_names();
    const std::string start_field = view->field();
    std::vector<double> ph_decode, ph_fill, ph_range, ph_update, ph_render;
    out["field_switch"] = stats(time_frames(std::max<int>(24, static_cast<int>(names.size()) * 6), [&](int i) {
        if (names.size() > 1) {
            view->setField(names[static_cast<std::size_t>(i) % names.size()]);
        } else {
            view->setLogScale(!view->logScale());
        }
        const SwitchTimings& st = view->lastSwitchTimings();
        ph_decode.push_back(st.decode_ms);
        ph_fill.push_back(st.fill_ms);
        ph_range.push_back(st.range_ms);
        ph_update.push_back(st.update_ms);
        ph_render.push_back(st.render_ms);
    }));
    out["field_switch_phases"] = {{"decode", stats(ph_decode)}, {"fill", stats(ph_fill)},
                                  {"range", stats(ph_range)}, {"pipeline_update", stats(ph_update)},
                                  {"render", stats(ph_render)}};
    view->setField(start_field);

    // Correctness probe: the view centre is the device centre after a
    // reset, so a hover there must land on a real node.
    view->resetView();
    QString centre;
    out["hover_centre_hit"] = view->readoutAt(0.5 * o.width, 0.5 * o.height, &centre);
    out["hover_centre"] = centre.toStdString();

    std::mt19937 rng(12345);
    std::uniform_real_distribution<double> ux(0.0, o.width), uy(0.0, o.height);
    QString text;
    int hits = 0;
    std::vector<double> per_hover, ph_pick, ph_snap;
    t.restart();
    for (int i = 0; i < o.hover_samples; ++i) {
        const auto h0 = std::chrono::steady_clock::now();
        hits += view->readoutAt(ux(rng), uy(rng), &text) ? 1 : 0;
        per_hover.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - h0).count());
        ph_pick.push_back(view->lastHoverTimings().pick_ms);
        ph_snap.push_back(view->lastHoverTimings().snap_ms);
    }
    const double hover_total_ms = static_cast<double>(t.nsecsElapsed()) / 1e6;
    out["hover_lookup_ms"] = hover_total_ms / o.hover_samples;
    out["hover_lookup"] = stats(per_hover);
    out["hover_phases"] = {{"pick", stats(ph_pick)}, {"snap_format", stats(ph_snap)}};

    // Section 15.17 rows (2D): the overlays, toggled on and off. "On"
    // includes computing the contours at matplotlib's levels.
    if (!three_d) {
        std::vector<double> on_ms, c_fill, c_levels, c_filter, c_render;
        for (int i = 0; i < 10; ++i) {
            view->setContours(false);
            QApplication::processEvents();
            const auto t0 = std::chrono::steady_clock::now();
            view->setContours(true);  // levels + contour filter + render
            on_ms.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
            const ContourTimings& ct = view->lastContourTimings();
            c_fill.push_back(ct.fill_ms);
            c_levels.push_back(ct.levels_ms);
            c_filter.push_back(ct.filter_ms);
            c_render.push_back(ct.render_ms);
        }
        out["contours_on"] = stats(on_ms);
        out["contours_on_phases"] = {{"fill", stats(c_fill)}, {"levels", stats(c_levels)},
                                     {"filter", stats(c_filter)}, {"render", stats(c_render)}};
        view->setContours(false);
        out["mesh_lines_toggle"] = stats(time_frames(20, [&](int i) { view->setMeshLines(i % 2 == 0); }));
        view->setMeshLines(false);
    }

    // Section 15.4 / 15.19 rows (S6, 3D): each frame is the state change
    // AND its render, as the user waits for both.
    if (three_d) {
        const auto n = m->node_counts();
        std::vector<double> layer_ms;
        auto time_one = [](auto&& f) {
            const auto t0 = std::chrono::steady_clock::now();
            f();
            return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        };
        view->setViewPreset(ViewPreset::Iso);
        view->setSlice(2, true, n[2] / 2);  // switches the surface to Context (interior layer)
        out["slice_drag"] = stats(time_frames(o.frames, [&](int i) {
            const std::size_t span = n[2] > 1 ? 2 * (n[2] - 1) : 1;
            const std::size_t t = static_cast<std::size_t>(i) % span;
            view->setSlice(2, true, t < n[2] ? t : span - t);  // sweep back and forth, one plane per frame
        }));
        view->setSlice(2, false, 0);

        view->setIsosurface(true);
        const auto r = view->dataRange();
        out["iso_level"] = stats(time_frames(12, [&](int i) {
            view->setIsoLevel(r[0] + (0.15 + 0.06 * i) * (r[1] - r[0]));
        }));
        out["iso_triangles"] = view->isoPoly()->GetNumberOfCells();
        view->setIsosurface(false);

        view->setVolume(true);
        view->renderNow();  // uploads the volume once; the orbit then re-renders it
        // Still quality (every frame as a render at rest), and as a mouse
        // drag renders it: the interactor's drag rate, which lets the GPU
        // mapper coarsen its sampling (level of detail).
        out["volume_orbit"] = stats(time_frames(o.frames, [&](int) {
            cam->Azimuth(1.5);
            cam->OrthogonalizeViewUp();
            view->renderNow();
        }));
        view->renderWindow()->SetDesiredUpdateRate(FieldView::kDragFps);
        out["volume_orbit_drag"] = stats(time_frames(o.frames, [&](int) {
            cam->Azimuth(1.5);
            cam->OrthogonalizeViewUp();
            view->renderNow();
        }));
        view->renderWindow()->SetDesiredUpdateRate(view->renderWindow()->GetInteractor()->GetStillUpdateRate());
        view->setVolume(false);
        view->setColorMap(std::nullopt);

        if (const SweepSnapshots* s = view->snapshots()) {
            view->setField(s->field_names.front());
            out["playback_step"] = stats(time_frames(std::max<int>(20, static_cast<int>(s->count()) * 4), [&](int i) {
                view->setSnapshot(static_cast<std::size_t>(i) % s->count());
            }));
            out["playback_step_phase_snapshot_ms"] = view->lastLayerTimings().snapshot_ms;
            view->setSnapshot(std::nullopt);
            view->setField(start_field);
        }

        if (!m->vector_names().empty()) {
            layer_ms.clear();
            for (int i = 0; i < 3; ++i) {
                view->setGlyphs(false);
                layer_ms.push_back(time_one([&] { view->setGlyphs(true); }));
            }
            out["glyph_rebuild"] = stats(layer_ms);
            out["glyph_arrows"] = view->glyphSources()->GetNumberOfPoints();
            view->setGlyphs(false);
            layer_ms.clear();
            for (int i = 0; i < 5; ++i) {
                view->setStreamlines(false);
                layer_ms.push_back(time_one([&] { view->setStreamlines(true); }));
            }
            out["streamline_rebuild"] = stats(layer_ms);
            out["streamline_points"] = view->streamlinePoly()->GetNumberOfPoints();
            view->setStreamlines(false);
        }

        layer_ms.clear();
        for (int i = 0; i < 10; ++i) {
            NodeBox b = view->fullBox();
            if (i % 2 == 0)
                for (std::size_t a = 0; a < 3; ++a) b.lo[a] = n[a] / 3;
            layer_ms.push_back(time_one([&] { view->setCrop(b); }));
        }
        out["crop_change"] = stats(layer_ms);
        view->setCrop(view->fullBox());

        if (view->explodedAvailable()) {
            layer_ms.clear();
            for (int i = 0; i < 5; ++i) {
                view->setExploded(false);
                layer_ms.push_back(time_one([&] { view->setExploded(true); }));
            }
            out["exploded_toggle"] = stats(layer_ms);
            view->setExploded(false);
        }
        view->setSurfaceMode(SurfaceMode::Field);
        view->setViewPreset(ViewPreset::Iso);
    }

    // Section 15.4 / 15.13 rows: docking with a live GL view. Each frame
    // includes the event processing that shows the change, since that is
    // what the user waits for.
    ads::CDockManager* docks = window.dockManager();
    out["dock_float_redock"] = stats(time_frames(20, [&](int) {
        window.fieldsDock()->setFloating();
        QApplication::processEvents();
        docks->addDockWidget(ads::LeftDockWidgetArea, window.fieldsDock());
        QApplication::processEvents();
    }));
    window.resetLayout();
    QApplication::processEvents();
    const QByteArray layout_default = docks->saveState();
    docks->addDockWidget(ads::RightDockWidgetArea, window.fieldsDock());
    QApplication::processEvents();
    const QByteArray layout_moved = docks->saveState();
    std::vector<double> lr_state, lr_events;
    const int gl_before = view->glInitializations();
    out["layout_restore"] = stats(time_frames(20, [&](int i) {
        const auto t0 = std::chrono::steady_clock::now();
        docks->restoreState(i % 2 ? layout_default : layout_moved);
        const auto t1 = std::chrono::steady_clock::now();
        QApplication::processEvents();  // the resize, relayout and repaint that follow
        const auto t2 = std::chrono::steady_clock::now();
        lr_state.push_back(std::chrono::duration<double, std::milli>(t1 - t0).count());
        lr_events.push_back(std::chrono::duration<double, std::milli>(t2 - t1).count());
    }));
    out["layout_restore_phases"] = {{"restore_state", stats(lr_state)}, {"events_and_repaint", stats(lr_events)}};
    out["layout_restore_gl_reinits"] = view->glInitializations() - gl_before;  // over 20 restores
    // The app's own path with a result loaded: "Reset layout" rebuilds the
    // default arrangement with addDockWidget (restoreState runs only at
    // startup, before a result is open -- section 15.18).
    const int gl_before_reset = view->glInitializations();
    std::vector<double> reset_ms;
    for (int i = 0; i < 10; ++i) {
        docks->addDockWidget(ads::RightDockWidgetArea, window.fieldsDock());  // move away...
        QApplication::processEvents();
        const auto t0 = std::chrono::steady_clock::now();
        window.resetLayout();  // ...and back, as the user's Reset layout does
        QApplication::processEvents();
        reset_ms.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    }
    out["reset_layout"] = stats(reset_ms);
    out["reset_layout_gl_reinits"] = view->glInitializations() - gl_before_reset;
    window.resetLayout();
    out["hover_hit_fraction"] = static_cast<double>(hits) / o.hover_samples;
    out["hover_example"] = text.toStdString();
    return out;
}

}  // namespace tcad::desktop
