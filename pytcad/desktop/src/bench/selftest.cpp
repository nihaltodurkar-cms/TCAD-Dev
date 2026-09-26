#include "selftest.hpp"

#include "bench.hpp"
#include "data/contour_levels.hpp"
#include "shell/main_window.hpp"
#include "views/colormaps.hpp"
#include "views/field/field_view.hpp"

#include <QApplication>
#include <QImage>
#include <vtkActor.h>
#include <vtkCamera.h>
#include <vtkCellArray.h>
#include <vtkCellPicker.h>
#include <vtkColorTransferFunction.h>
#include <vtkPiecewiseFunction.h>
#include <vtkPointData.h>
#include <vtkCoordinate.h>
#include <vtkDoubleArray.h>
#include <vtkIdTypeArray.h>
#include <vtkLookupTable.h>
#include <vtkPoints.h>
#include <vtkPolyData.h>
#include <vtkRenderWindow.h>
#include <vtkRenderer.h>
#include <vtkScalarBarActor.h>
#include <vtkTextActor.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <functional>
#include <limits>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>

namespace tcad::desktop {
namespace {

using Json = nlohmann::ordered_json;

bool same_bits(double a, double b) { return std::memcmp(&a, &b, sizeof(double)) == 0; }

// A coordinate the geometry filter produced vs the value it came from:
// exact in double, or exact after the filter's float storage.
bool same_coord(double shown, double axis) {
    return same_bits(shown, axis) || same_bits(shown, static_cast<double>(static_cast<float>(axis)));
}

bool inMapViewport(const FieldView& v, double xd, double yd) {
    return v.renderer()->IsInViewport(static_cast<int>(xd), static_cast<int>(yd)) != 0;
}

// Check 1: each displayed element is the node its carried index names.
// Nearest shading (2D, and 3D since S6): cell k lies on node (i, j[, k])'s
// patch -- in 2D exactly [edge_i, edge_i+1] x [edge_j, edge_j+1]; in 3D a
// face of its voxel, so on every axis each bound is one of that node's two
// edges, and exactly one axis is flat (the face's plane).
Json check_node_ids(const FieldView& v, const ResultModel& m) {
    const auto n = m.node_counts();
    vtkPolyData* g = v.displayedGeometry();
    vtkIdTypeArray* ids = v.displayedNodeIds();
    const vtkIdType count = g->GetNumberOfCells();
    long long bad = 0, out_of_range = 0;
    const vtkIdType total = static_cast<vtkIdType>(n[0] * n[1] * n[2]);
    const bool three = m.dimensionality() == 3;
    for (vtkIdType k = 0; k < count; ++k) {
        const vtkIdType id = ids->GetValue(k);
        if (id < 0 || id >= total) {
            ++out_of_range;
            continue;
        }
        const auto u = static_cast<std::size_t>(id);
        const std::size_t node[3] = {u % n[0], (u / n[0]) % n[1], u / (n[0] * n[1])};
        double b[6];
        g->GetCellBounds(k, b);
        bool ok = true;
        int flat = 0;
        for (int a = 0; a < (three ? 3 : 2); ++a) {
            const double e0 = v.edgesUm(a)[node[a]], e1 = v.edgesUm(a)[node[a] + 1];
            if (!three) {
                ok = ok && same_coord(b[2 * a], e0) && same_coord(b[2 * a + 1], e1);
                continue;
            }
            const bool lo_ok = same_coord(b[2 * a], e0) || same_coord(b[2 * a], e1);
            const bool hi_ok = same_coord(b[2 * a + 1], e0) || same_coord(b[2 * a + 1], e1);
            ok = ok && lo_ok && hi_ok;
            flat += b[2 * a] == b[2 * a + 1] ? 1 : 0;
        }
        if (three) ok = ok && flat == 1;
        bad += ok ? 0 : 1;
    }
    return {{"displayed", count}, {"as", "cells"}, {"mismatched", bad}, {"ids_out_of_range", out_of_range},
            {"ok", bad == 0 && out_of_range == 0 && ids->GetNumberOfValues() == count && count > 0}};
}

// Check 2: the displayed scalars and the ranges, for one field and scale,
// against a reference built here from a fresh decode: the norm range is
// GetRange over every node's displayed value (symmetric for doping), the
// displayed scalar is lut_input(displayed value, norm range), and the
// bar's label range is P0's (widened by 0.5 for a constant field).
Json check_field(FieldView& v, const ResultModel& m, const std::string& name, bool log) {
    v.setAutoRange();
    v.setField(name);
    v.setLogScale(log);
    const std::vector<double> raw = m.scalar(name).values;  // fresh, independent of the view's copy
    vtkNew<vtkDoubleArray> all;
    all->SetNumberOfValues(static_cast<vtkIdType>(raw.size()));
    for (std::size_t i = 0; i < raw.size(); ++i) all->SetValue(static_cast<vtkIdType>(i), v.displayTransform(raw[i]));
    double want[2];
    all->GetRange(want);
    if (v.fieldKind() == FieldKind::Doping) {
        const double mm = std::max(std::abs(want[0]), std::abs(want[1]));
        want[0] = -mm;
        want[1] = mm;
    }
    const auto norm = v.normRange();
    const bool norm_ok = same_bits(norm[0], want[0]) && same_bits(norm[1], want[1]);

    vtkIdTypeArray* ids = v.displayedNodeIds();
    vtkDoubleArray* shown = v.displayedScalars();
    long long bad = 0;
    const bool sized = shown->GetNumberOfValues() == ids->GetNumberOfValues();
    for (vtkIdType k = 0; sized && k < ids->GetNumberOfValues(); ++k) {
        const double expect = lut_input(v.displayTransform(raw[static_cast<std::size_t>(ids->GetValue(k))]), want[0], want[1]);
        bad += same_bits(shown->GetValue(k), expect) ? 0 : 1;
    }
    double bar[2] = {want[0], want[1]};
    if (!(bar[1] > bar[0])) {
        bar[0] -= 0.5;
        bar[1] += 0.5;
    }
    const double* got = v.scalarRange();
    const bool bar_ok = same_bits(got[0], bar[0]) && same_bits(got[1], bar[1]);
    return {{"field", name}, {"log", log}, {"mismatched_values", bad}, {"sized", sized},
            {"norm_range", {norm[0], norm[1]}}, {"norm_reference", {want[0], want[1]}},
            {"ok", sized && bad == 0 && norm_ok && bar_ok}};
}

// The world point [um] where the ray through display pixel (xd, yd)
// first meets the drawn box -- the crop box's patch edges (nearest
// shading, S6) -- or false (also outside the map's viewport: the bar's
// column hides the map).
bool ray_box(const FieldView& v, double xd, double yd, double hit[3]) {
    if (!inMapViewport(v, xd, yd)) return false;
    vtkRenderer* ren = v.renderer();
    double a[4], b[4];
    ren->SetDisplayPoint(xd, yd, 0.0);
    ren->DisplayToWorld();
    ren->GetWorldPoint(a);
    ren->SetDisplayPoint(xd, yd, 1.0);
    ren->DisplayToWorld();
    ren->GetWorldPoint(b);
    if (a[3] == 0.0 || b[3] == 0.0) return false;
    double o[3], d[3];
    for (int i = 0; i < 3; ++i) {
        o[i] = a[i] / a[3];
        d[i] = b[i] / b[3] - o[i];
    }
    double t0 = 0.0, t1 = 1.0;
    for (int i = 0; i < 3; ++i) {
        const auto& e = v.edgesUm(i);
        const double lo = e[v.crop().lo[static_cast<std::size_t>(i)]], hi = e[v.crop().hi[static_cast<std::size_t>(i)] + 1];
        if (d[i] == 0.0) {
            if (o[i] < lo || o[i] > hi) return false;
            continue;
        }
        double ta = (lo - o[i]) / d[i], tb = (hi - o[i]) / d[i];
        if (ta > tb) std::swap(ta, tb);
        t0 = std::max(t0, ta);
        t1 = std::min(t1, tb);
        if (t0 > t1) return false;
    }
    for (int i = 0; i < 3; ++i) hit[i] = o[i] + t0 * d[i];
    return true;
}

// Check 3 (3D): locator pick vs brute-force pick vs the analytic oracle.
Json check_hover(FieldView& v, const SelftestOptions& o) {
    vtkRenderer* ren = v.renderer();
    vtkNew<vtkCellPicker> brute;  // P0's picker: same tolerance, no locator
    brute->SetTolerance(0.0005);
    brute->PickFromListOn();
    brute->AddPickList(v.fieldActor());
    const double dpr = v.devicePixelRatioF();
    const int* size = v.renderWindow()->GetSize();

    std::mt19937 rng(12345);
    std::uniform_real_distribution<double> ux(0.0, o.width), uy(0.0, o.height);
    // The gate is the oracle. P0's brute-force picker is reported too: its
    // 0.0005 tolerance can register a hit just outside the silhouette, so
    // a brute-force disagreement passes only when the oracle sides with
    // the locator.
    long long hits = 0, vs_brute = 0, vs_oracle = 0, brute_unexplained = 0;
    Json examples = Json::array();
    for (int i = 0; i < o.hover_samples; ++i) {
        const double x = ux(rng), y = uy(rng);
        QString fast;
        const bool fast_hit = v.readoutAt(x, y, &fast);
        const double xd = x * dpr, yd = size[1] - 1 - y * dpr;

        QString slow;
        const bool slow_hit = inMapViewport(v, xd, yd) && brute->Pick(xd, yd, 0.0, ren) && brute->GetCellId() >= 0;
        if (slow_hit) {  // P0's path: the pick position, snapped as the view snaps a patch pick
            double p[3];
            brute->GetPickPosition(p);
            slow = v.readoutForNode(v.voxelNode(p));
        }
        QString exact;
        double q[3];
        const bool exact_hit = ray_box(v, xd, yd, q);
        if (exact_hit) {
            // Nearest shading: the node whose voxel [edge_i, edge_i+1] holds
            // the hit, within the drawn (crop) box -- on a crop face the hit
            // lies ON an edge, a tie the nearest-node rule would break
            // toward the node outside.
            std::size_t node[3];
            for (int a = 0; a < 3; ++a) {
                const auto& e = v.edgesUm(a);
                const auto it = std::upper_bound(e.begin(), e.end(), q[a]);
                const std::size_t vi = it == e.begin() ? 0 : static_cast<std::size_t>(it - e.begin()) - 1;
                node[a] = std::clamp(vi, v.crop().lo[static_cast<std::size_t>(a)], v.crop().hi[static_cast<std::size_t>(a)]);
            }
            const auto nn = v.fullBox().hi;
            exact = v.readoutForNode((node[2] * (nn[1] + 1) + node[1]) * (nn[0] + 1) + node[0]);
        }

        hits += fast_hit ? 1 : 0;
        const bool b_bad = fast_hit != slow_hit || fast != slow;
        const bool o_bad = fast_hit != exact_hit || fast != exact;
        vs_brute += b_bad ? 1 : 0;
        vs_oracle += o_bad ? 1 : 0;
        brute_unexplained += (b_bad && o_bad) ? 1 : 0;
        if ((b_bad || o_bad) && examples.size() < 5)
            examples.push_back({{"px", {x, y}}, {"locator", fast.toStdString()},
                                {"brute_force", slow.toStdString()}, {"oracle", exact.toStdString()}});
    }
    return {{"samples", o.hover_samples}, {"hits", hits}, {"mismatch_vs_oracle", vs_oracle},
            {"mismatch_vs_brute_force", vs_brute}, {"brute_force_mismatch_unexplained", brute_unexplained},
            {"examples", examples}, {"ok", vs_oracle == 0 && brute_unexplained == 0 && hits > 0}};
}

// Display coordinates of a world point [um] in the map's renderer.
std::array<double, 2> project(const FieldView& v, double x, double y, double z = 0.0) {
    vtkRenderer* ren = v.renderer();
    ren->SetWorldPoint(x, y, z, 1.0);
    ren->WorldToDisplay();
    double d[3];
    ren->GetDisplayPoint(d);
    return {d[0], d[1]};
}

// Check 4 (HiDPI, S3e): the GL surface is the widget's logical size times
// the DPR, and (2D) hovering at the logical pixel where a node is drawn
// names that node.
Json check_scale(FieldView& v, const ResultModel& m) {
    const double dpr = v.devicePixelRatioF();
    const int* size = v.renderWindow()->GetSize();
    const int want_w = static_cast<int>(std::lround(v.width() * dpr));
    const int want_h = static_cast<int>(std::lround(v.height() * dpr));
    const bool size_ok = std::abs(size[0] - want_w) <= 1 && std::abs(size[1] - want_h) <= 1;
    Json out = {{"dpr", dpr}, {"logical", {v.width(), v.height()}}, {"render_size", {size[0], size[1]}},
                {"expected_render_size", {want_w, want_h}}, {"render_size_ok", size_ok}};
    if (m.dimensionality() != 2) {
        out["ok"] = size_ok;
        return out;
    }
    const auto n = m.node_counts();
    std::mt19937 rng(777);
    // interior nodes: a boundary node sits exactly on the on-device test,
    // where round-off in the projection decides it
    std::uniform_int_distribution<std::size_t> ix(1, n[0] - 2), iy(1, n[1] - 2);
    long long probes = 0, wrong = 0;
    Json examples = Json::array();
    for (int k = 0; k < 200; ++k) {
        const std::size_t i = ix(rng), j = iy(rng);
        const double p[3] = {v.axisUm(0)[i], v.axisUm(1)[j], 0.0};
        const auto d = project(v, p[0], p[1]);
        const double lx = d[0] / dpr, ly = (size[1] - 1 - d[1]) / dpr;
        if (lx < 0 || ly < 0 || lx >= v.width() || ly >= v.height() || !inMapViewport(v, d[0], d[1])) continue;
        ++probes;
        QString got;
        v.readoutAt(lx, ly, &got);
        const QString want = v.readoutForPoint(p);
        if (got != want) {
            ++wrong;
            if (examples.size() < 5)
                examples.push_back({{"node", {i, j}}, {"logical_px", {lx, ly}}, {"got", got.toStdString()},
                                    {"want", want.toStdString()}});
        }
    }
    out["node_probes"] = probes;
    out["node_mismatches"] = wrong;
    out["examples"] = examples;
    out["ok"] = size_ok && probes > 50 && wrong == 0;
    return out;
}

int brightness(QRgb c) { return qRed(c) + qGreen(c) + qBlue(c); }

long long countDiff(const QImage& a, const QImage& b) {
    if (a.size() != b.size()) return static_cast<long long>(a.width()) * a.height();
    long long n = 0;
    for (int y = 0; y < a.height(); ++y)
        for (int x = 0; x < a.width(); ++x) n += a.pixel(x, y) != b.pixel(x, y) ? 1 : 0;
    return n;
}

// "Turning the overlay off restores the frame": identical, up to render
// noise. Two renders of an unchanged scene can differ in a few pixels at
// patch edges that fall between device pixels (fractional DPR, sub-pixel
// patches -- measured, section 15.18); a leftover overlay would differ in
// thousands (contours) to tens of thousands (mesh lines), and would
// survive a re-render. So: at most 0.02% of the image may differ, and a
// frame over that gets ONE fresh render before judging (one run in seven
// at DPR 2 on the graded mesh left 216 of 864k pixels, gone on re-render).
// The count reported is the one judged.
bool restoredUpToNoise(FieldView& v, const QImage& base, long long* diff) {
    const long long limit = static_cast<long long>(base.width()) * base.height() / 5000;
    *diff = countDiff(v.grabFramebuffer(), base);
    if (*diff > limit) {
        v.renderNow();
        *diff = countDiff(v.grabFramebuffer(), base);
    }
    return *diff <= limit;
}

// Check 5a (2D, at Fit): the bar's own column. The map never draws there,
// even panned into it; the title lies right of the bar and its labels; a
// hover over the column reads nothing.
Json check_bar(FieldView& v) {
    Json out;
    v.resetView();
    const int* size = v.renderWindow()->GetSize();
    const int H = size[1];
    auto grab = [&v] { return v.grabFramebuffer(); };
    // the bar's column: pan the map toward it; its left margin stays background
    vtkRenderer* bren = v.barRenderer();
    double vp[4];
    bren->GetViewport(vp);
    const double col_left = vp[0] * size[0];
    vtkCamera* cam = v.renderer()->GetActiveCamera();
    double f[3], p[3];
    cam->GetFocalPoint(f);
    cam->GetPosition(p);
    const double shift = 0.6 * (v.edgesUm(0).back() - v.edgesUm(0).front());
    cam->SetFocalPoint(f[0] - shift, f[1], f[2]);  // the device slides right, toward the bar
    cam->SetPosition(p[0] - shift, p[1], p[2]);
    v.renderNow();
    const QImage panned = grab();
    double bg[3];
    bren->GetBackground(bg);
    const QRgb bgc = qRgb(static_cast<int>(std::lround(bg[0] * 255)), static_cast<int>(std::lround(bg[1] * 255)),
                          static_cast<int>(std::lround(bg[2] * 255)));
    long long foreign = 0, sampled = 0;
    for (int dx = 1; dx <= 3; ++dx)
        for (int y = H / 4; y < 3 * H / 4; y += 4) {
            ++sampled;
            foreign += (panned.pixel(static_cast<int>(col_left) + dx, H - 1 - y) & 0xFFFFFF) == (bgc & 0xFFFFFF) ? 0 : 1;
        }
    // and the map really reached the column's edge (else the probe proves nothing)
    const QRgb edge_left = panned.pixel(std::max(0, static_cast<int>(col_left) - 2), H / 2);
    const bool map_at_edge = (edge_left & 0xFFFFFF) != (bgc & 0xFFFFFF);
    v.resetView();
    out["bar_column_samples"] = sampled;
    out["bar_column_foreign_pixels"] = foreign;
    out["map_reaches_bar_edge"] = map_at_edge;

    // the title's box lies right of the bar actor's box
    double tb[4];
    v.barTitle()->GetBoundingBox(bren, tb);  // xmin, xmax, ymin, ymax -- RELATIVE to the anchor
    const int* anchor = v.barTitle()->GetPositionCoordinate()->GetComputedDisplayValue(bren);
    tb[0] += anchor[0];
    tb[1] += anchor[0];
    tb[2] += anchor[1];
    tb[3] += anchor[1];
    int* p2 = v.scalarBar()->GetPosition2Coordinate()->GetComputedDisplayValue(bren);
    const double bar_right = p2[0];
    out["title_box"] = {tb[0], tb[1], tb[2], tb[3]};
    out["bar_right"] = bar_right;
    const bool title_ok = tb[0] > bar_right && tb[1] <= vp[2] * size[0] + 1;

    // hover over the bar's column: nothing
    QString over_bar;
    const double dpr = v.devicePixelRatioF();
    const bool bar_hover = v.readoutAt((col_left + 0.5 * (vp[2] - vp[0]) * size[0]) / dpr, 0.5 * H / dpr, &over_bar);
    out["hover_over_bar_reads"] = bar_hover;

    out["title_ok"] = title_ok;
    out["ok"] = foreign == 0 && map_at_edge && title_ok && !bar_hover;
    return out;
}

// Check 5 (2D, S5 review revision 7): what is ON SCREEN.
//   orientation  y grows downward, x rightward
//   colour       a node's patch shows exactly the lookup table's colour of
//                its displayed value (nearest shading: nothing is blended)
//   mesh lines   on: the pixel on a node line is lighter; off: unchanged
//   contours     on: pixels at level crossings are lighter; off: unchanged
//   bar column   the map never draws there, even panned into it
//   title        the bar's title lies entirely right of the bar and labels
//   hover        over the bar's column there is no readout
Json check_pixels(FieldView& v, const ResultModel& m) {
    Json out;
    // A smooth field makes contour crossings everywhere; doping is
    // piecewise constant and has few.
    const auto& names = m.scalar_names();
    const std::string probe_field =
        std::find(names.begin(), names.end(), "potential") != names.end() ? std::string("potential") : names.front();
    v.setAutoRange();
    v.setField(probe_field);
    v.setLogScale(false);
    v.setContours(false);
    v.setMeshLines(false);
    v.resetView();
    // A fine mesh draws patches ~1 px wide at Fit: zoom in on the centre
    // until a central patch spans >= 16 device px, so probes can land
    // inside patches (the 1000 x 1000 grid needs this).
    // The node nearest the view's centre (the focal point) -- on a graded
    // mesh the middle INDEX can be far from the middle of the device.
    auto nearest = [](const std::vector<double>& ax, double x) {
        const auto it = std::lower_bound(ax.begin(), ax.end(), x);
        std::size_t i = static_cast<std::size_t>(it - ax.begin());
        if (i >= ax.size()) i = ax.size() - 1;
        return std::clamp<std::size_t>(i, 1, ax.size() - 2);
    };
    double focal[3];
    v.renderer()->GetActiveCamera()->GetFocalPoint(focal);
    const std::size_t ci = nearest(v.axisUm(0), focal[0]), cj = nearest(v.axisUm(1), focal[1]);
    {
        const auto lo = project(v, v.edgesUm(0)[ci], v.edgesUm(1)[cj]);
        const auto hi = project(v, v.edgesUm(0)[ci + 1], v.edgesUm(1)[cj + 1]);
        const double patch = std::min(std::abs(hi[0] - lo[0]), std::abs(hi[1] - lo[1]));
        out["fit_patch_px"] = patch;
        if (patch > 0 && patch < 16) {
            vtkCamera* c = v.renderer()->GetActiveCamera();
            c->Zoom(16.0 / patch);
            v.renderNow();
            const auto lo2 = project(v, v.edgesUm(0)[ci], v.edgesUm(1)[cj]);
            const auto hi2 = project(v, v.edgesUm(0)[ci + 1], v.edgesUm(1)[cj + 1]);
            out["zoomed_patch_px"] = {std::abs(hi2[0] - lo2[0]), std::abs(hi2[1] - lo2[1])};
            out["zoomed_centre_display"] = {lo2[0], lo2[1]};
        }
    }
    out["probe_field"] = probe_field;
    const int* size = v.renderWindow()->GetSize();
    const int H = size[1];
    auto grab = [&v] { return v.grabFramebuffer(); };
    auto pixel = [H](const QImage& img, double xd, double yd) {
        const int px = static_cast<int>(std::floor(xd)), py = H - 1 - static_cast<int>(std::floor(yd));
        return (px >= 0 && py >= 0 && px < img.width() && py < img.height()) ? img.pixel(px, py) : QRgb(0);
    };
    const auto n = m.node_counts();

    // orientation
    const auto a = project(v, v.axisUm(0).front(), v.axisUm(1).front());
    const auto b = project(v, v.axisUm(0).back(), v.axisUm(1).back());
    out["orientation_ok"] = a[1] > b[1] && a[0] < b[0];  // display y grows upward: y = min is higher

    // nodes whose patch spans >= 8 device px each way, inside the map viewport
    std::unordered_map<vtkIdType, vtkIdType> cell_of;  // node id -> displayed cell
    vtkIdTypeArray* ids = v.displayedNodeIds();
    for (vtkIdType k = 0; k < ids->GetNumberOfValues(); ++k) cell_of[ids->GetValue(k)] = k;
    std::vector<std::array<std::size_t, 2>> probes;
    std::mt19937 rng(4242);
    // near the centre: after a zoom-in that is all the view shows
    const std::size_t cx = ci, cy = cj, span = 60;
    std::uniform_int_distribution<std::size_t> ix(std::max<std::size_t>(1, cx > span ? cx - span : 1),
                                                   std::min(n[0] - 2, cx + span)),
        iy(std::max<std::size_t>(1, cy > span ? cy - span : 1), std::min(n[1] - 2, cy + span));
    for (int k = 0; k < 4000 && probes.size() < 150; ++k) {
        const std::size_t i = ix(rng), j = iy(rng);
        const auto lo = project(v, v.edgesUm(0)[i], v.edgesUm(1)[j]);
        const auto hi = project(v, v.edgesUm(0)[i + 1], v.edgesUm(1)[j + 1]);
        const auto c = project(v, v.axisUm(0)[i], v.axisUm(1)[j]);
        if (std::abs(hi[0] - lo[0]) >= 8 && std::abs(hi[1] - lo[1]) >= 8 && inMapViewport(v, c[0], c[1]) &&
            inMapViewport(v, lo[0], lo[1]) && inMapViewport(v, hi[0], hi[1]))
            probes.push_back({i, j});
    }
    // colour: the pixel at the node (off the patch edges) is the table's colour
    const QImage base = grab();
    long long colour_bad = 0;
    Json colour_examples = Json::array();
    for (const auto& [i, j] : probes) {
        const vtkIdType node = static_cast<vtkIdType>(j * n[0] + i);
        double rgb[3];
        v.lookupTable()->GetColor(v.displayedScalars()->GetValue(cell_of[node]), rgb);
        const int want[3] = {static_cast<int>(std::lround(rgb[0] * 255)), static_cast<int>(std::lround(rgb[1] * 255)),
                             static_cast<int>(std::lround(rgb[2] * 255))};
        // At the node, and a quarter of the way toward each x/y neighbour:
        // nearest shading puts all five in the node's own flat patch, so a
        // blend (smooth shading) or a misplaced edge shows up here.
        const double x = v.axisUm(0)[i], y = v.axisUm(1)[j];
        const double qx0 = 0.25 * (v.axisUm(0)[i - 1] - x), qx1 = 0.25 * (v.axisUm(0)[i + 1] - x);
        const double qy0 = 0.25 * (v.axisUm(1)[j - 1] - y), qy1 = 0.25 * (v.axisUm(1)[j + 1] - y);
        const std::array<std::array<double, 2>, 5> points{{{x, y}, {x + qx0, y}, {x + qx1, y}, {x, y + qy0}, {x, y + qy1}}};
        for (const auto& pt : points) {
            const auto c = project(v, pt[0], pt[1]);
            const QRgb got = pixel(base, c[0], c[1]);
            const int diff =
                std::max({std::abs(qRed(got) - want[0]), std::abs(qGreen(got) - want[1]), std::abs(qBlue(got) - want[2])});
            if (diff > 1) {
                ++colour_bad;
                if (colour_examples.size() < 5)
                    colour_examples.push_back({{"node", {i, j}}, {"at_um", {pt[0], pt[1]}},
                                               {"pixel", {qRed(got), qGreen(got), qBlue(got)}}, {"lut", {want[0], want[1], want[2]}}});
            }
        }
    }
    out["colour_probes"] = probes.size();
    out["colour_mismatches"] = colour_bad;
    out["colour_examples"] = colour_examples;

    // mesh lines: at a node's own coordinates (on both of its lines)
    auto lighter_near = [&](const QImage& on, const QImage& off, double xd, double yd) {
        int best = -1000;
        for (int dx = -1; dx <= 1; ++dx)
            for (int dy = -1; dy <= 1; ++dy)
                best = std::max(best, brightness(pixel(on, xd + dx, yd + dy)) - brightness(pixel(off, xd + dx, yd + dy)));
        return best > 0;
    };
    v.setMeshLines(true);
    const QImage mesh = grab();
    long long mesh_lighter = 0, mesh_counted = 0;
    for (const auto& [i, j] : probes) {
        const auto c = project(v, v.axisUm(0)[i], v.axisUm(1)[j]);
        if (brightness(pixel(base, c[0], c[1])) >= 3 * 250) continue;  // already white: cannot lighten
        ++mesh_counted;
        mesh_lighter += lighter_near(mesh, base, c[0], c[1]) ? 1 : 0;
    }
    v.setMeshLines(false);
    long long mesh_residue = 0;
    const bool mesh_off_restores = restoredUpToNoise(v, base, &mesh_residue);
    out["mesh_probes"] = mesh_counted;
    out["mesh_lighter"] = mesh_lighter;
    out["mesh_off_restores"] = mesh_off_restores;
    out["mesh_off_diff_pixels"] = mesh_residue;

    // Contours off restores the frame: checked on this (zoomed) view, where
    // patches span several pixels (up to render noise, restoredUpToNoise).
    v.setContours(true);
    v.setContours(false);
    long long contour_residue = 0;
    const bool contours_off_restores = restoredUpToNoise(v, base, &contour_residue);

    // Contour crossings, at Fit (more crossings in view). With a fine mesh a
    // patch is under a pixel wide there, and which patch colours a pixel is
    // NOT repeatable frame to frame on this GPU (the 1000 x 1000 grid: a few
    // hundred of ~900k pixels change between two renders of an unchanged
    // scene). So a crossing counts as lighter only against BOTH of two
    // overlay-off renders.
    v.resetView();
    const QImage base_fit = grab();
    v.renderNow();
    const QImage base_fit_2 = grab();
    out["fit_render_repeatable"] = base_fit_2 == base_fit;  // nothing changed in between
    out["fit_render_noise_pixels"] = countDiff(base_fit, base_fit_2);
    v.setContours(true);
    const QImage cont = grab();
    auto lighter_than_both = [&](double xd, double yd) {
        int best = -1000;
        for (int dx = -1; dx <= 1; ++dx)
            for (int dy = -1; dy <= 1; ++dy) {
                const int on = brightness(pixel(cont, xd + dx, yd + dy));
                const int off = std::max(brightness(pixel(base_fit, xd + dx, yd + dy)), brightness(pixel(base_fit_2, xd + dx, yd + dy)));
                best = std::max(best, on - off);
            }
        return best > 0;
    };
    const auto& levels = v.contourLevels();
    const std::vector<double> raw = m.scalar(v.field()).values;
    // Every crossing of a level between x-neighbours, over the whole grid,
    // that lands visibly inside the map (up to 60).
    long long cross_counted = 0, cross_lighter = 0;
    for (std::size_t j = 1; j + 1 < n[1] && cross_counted < 60; ++j) {
        for (std::size_t i = 0; i + 1 < n[0] && cross_counted < 60; ++i) {
            const double v0 = v.displayTransform(raw[j * n[0] + i]), v1 = v.displayTransform(raw[j * n[0] + i + 1]);
            for (double L : levels) {
                if (!((v0 < L && L < v1) || (v1 < L && L < v0))) continue;
                const double x = v.axisUm(0)[i] + (L - v0) / (v1 - v0) * (v.axisUm(0)[i + 1] - v.axisUm(0)[i]);
                const auto c = project(v, x, v.axisUm(1)[j]);
                if (!inMapViewport(v, c[0] - 2, c[1] - 2) || !inMapViewport(v, c[0] + 2, c[1] + 2) ||
                    brightness(pixel(base_fit, c[0], c[1])) >= 3 * 250)
                    continue;
                ++cross_counted;
                cross_lighter += lighter_than_both(c[0], c[1]) ? 1 : 0;
                break;
            }
        }
    }
    v.setContours(false);
    out["contour_levels"] = levels;
    out["contour_probes"] = cross_counted;
    out["contour_lighter"] = cross_lighter;
    out["contours_off_restores"] = contours_off_restores;
    out["contours_off_diff_pixels"] = contour_residue;

    const bool ok = out["orientation_ok"].get<bool>() && probes.size() >= 20 && colour_bad == 0 &&
                    mesh_counted >= 10 && mesh_lighter * 10 >= mesh_counted * 9 && mesh_off_restores &&
                    cross_counted >= 10 && cross_lighter * 10 >= cross_counted * 8 && contours_off_restores;
    out["ok"] = ok;
    return out;
}

// ---- S6 (section 15.19): the 3D layers ----------------------------------

// Pixel colour at world point p equals the LUT colour of `lut_value`
// (within 1/255 per channel) -- `img` rendered with lighting off.
struct PixelProbe {
    long long probes = 0, bad = 0;
    Json examples = Json::array();
};

// Zoom the camera (looking along +z) until node (ci, cj)'s patch spans
// >= 16 device px, as check_pixels does in 2D.
void zoomToPatches(FieldView& v, std::size_t ci, std::size_t cj, double z) {
    const auto lo = project(v, v.edgesUm(0)[ci], v.edgesUm(1)[cj], z);
    const auto hi = project(v, v.edgesUm(0)[ci + 1], v.edgesUm(1)[cj + 1], z);
    const double patch = std::min(std::abs(hi[0] - lo[0]), std::abs(hi[1] - lo[1]));
    if (patch > 0 && patch < 16) {
        v.renderer()->GetActiveCamera()->Zoom(16.0 / patch);
        v.renderer()->ResetCameraClippingRange();
        v.renderNow();
    }
}

// Colour probes on a plane of nodes seen along +z: plane z_um, the node
// index k along z whose values it shows, and the cell->value lookup.
PixelProbe probePlane(FieldView& v, const ResultModel& m, double z_um, std::size_t k,
                      const std::function<double(std::size_t)>& displayed_of_node) {
    PixelProbe r;
    const auto n = m.node_counts();
    const QImage img = v.grabFramebuffer();
    const int H = v.renderWindow()->GetSize()[1];
    for (std::size_t j = 1; j + 1 < n[1]; ++j)
        for (std::size_t i = 1; i + 1 < n[0]; ++i) {
            const auto lo = project(v, v.edgesUm(0)[i], v.edgesUm(1)[j], z_um);
            const auto hi = project(v, v.edgesUm(0)[i + 1], v.edgesUm(1)[j + 1], z_um);
            const auto c = project(v, v.axisUm(0)[i], v.axisUm(1)[j], z_um);
            if (std::abs(hi[0] - lo[0]) < 8 || std::abs(hi[1] - lo[1]) < 8 || !inMapViewport(v, c[0], c[1]) ||
                !inMapViewport(v, lo[0], lo[1]) || !inMapViewport(v, hi[0], hi[1]))
                continue;
            const int px = static_cast<int>(std::floor(c[0])), py = H - 1 - static_cast<int>(std::floor(c[1]));
            if (px < 0 || py < 0 || px >= img.width() || py >= img.height()) continue;
            const std::size_t node = (k * n[1] + j) * n[0] + i;
            double rgb[3];
            v.lookupTable()->GetColor(lut_input(displayed_of_node(node), v.normRange()[0], v.normRange()[1]), rgb);
            const QRgb got = img.pixel(px, py);
            const int want[3] = {static_cast<int>(std::lround(rgb[0] * 255)), static_cast<int>(std::lround(rgb[1] * 255)),
                                 static_cast<int>(std::lround(rgb[2] * 255))};
            const int diff = std::max({std::abs(qRed(got) - want[0]), std::abs(qGreen(got) - want[1]), std::abs(qBlue(got) - want[2])});
            ++r.probes;
            if (diff > 1) {
                ++r.bad;
                if (r.examples.size() < 4)
                    r.examples.push_back({{"node", {i, j, k}}, {"pixel", {qRed(got), qGreen(got), qBlue(got)}},
                                          {"lut", {want[0], want[1], want[2]}}});
            }
        }
    return r;
}

Json check_3d(FieldView& v, const ResultModel& m, const SelftestOptions& o) {
    Json out;
    const auto n = m.node_counts();
    const auto& names = m.scalar_names();
    const std::string field =
        std::find(names.begin(), names.end(), "potential") != names.end() ? std::string("potential") : names.front();
    v.setAutoRange();
    v.setField(field);
    v.setLogScale(false);
    const std::vector<double> raw = m.scalar(field).values;
    auto displayed = [&](std::size_t node) { return v.displayTransform(raw[node]); };
    bool ok = true;

    // (a) the z-min face, viewed along +z, lighting off: node-exact colours
    v.setSurfaceMode(SurfaceMode::Field);
    v.setViewPreset(ViewPreset::PlusZ);
    zoomToPatches(v, n[0] / 2, n[1] / 2, v.edgesUm(2).front());
    {
        const PixelProbe r = probePlane(v, m, v.edgesUm(2).front(), 0, displayed);
        out["face_probes"] = r.probes;
        out["face_mismatches"] = r.bad;
        out["face_examples"] = r.examples;
        ok = ok && r.probes >= 20 && r.bad == 0;
    }

    // (b) slices: geometry of each axis' slice, and the z-slice's colours
    Json slices = Json::array();
    for (int a = 0; a < 3; ++a) {
        const std::size_t k = std::max<std::size_t>(1, n[static_cast<std::size_t>(a)] / 3);
        v.setSlice(a, true, k);
        vtkPolyData* pd = v.slicePoly(a);
        vtkIdTypeArray* ids = v.sliceNodeIds(a);
        long long bad = 0;
        const vtkIdType cells = pd->GetNumberOfCells();
        for (vtkIdType c = 0; c < cells; ++c) {
            const auto u = static_cast<std::size_t>(ids->GetValue(c));
            const std::size_t node[3] = {u % n[0], (u / n[0]) % n[1], u / (n[0] * n[1])};
            double b[6];
            pd->GetCellBounds(c, b);
            bool cell_ok = node[a] == k && same_coord(b[2 * a], v.axisUm(a)[k]) && same_coord(b[2 * a + 1], v.axisUm(a)[k]);
            for (int q = 0; q < 3; ++q)
                if (q != a)
                    cell_ok = cell_ok && same_coord(b[2 * q], v.edgesUm(q)[node[q]]) &&
                              same_coord(b[2 * q + 1], v.edgesUm(q)[node[q] + 1]);
            bad += cell_ok ? 0 : 1;
        }
        const std::size_t want_cells = (n[0] * n[1] * n[2]) / n[static_cast<std::size_t>(a)];
        slices.push_back({{"axis", a}, {"index", k}, {"cells", cells}, {"mismatched", bad}});
        ok = ok && bad == 0 && static_cast<std::size_t>(cells) == want_cells;
        v.setSlice(a, false, k);
    }
    out["slices"] = slices;
    {
        const std::size_t k = std::max<std::size_t>(1, n[2] / 3);
        v.setSlice(2, true, k);
        v.setSurfaceMode(SurfaceMode::Hidden);
        v.setViewPreset(ViewPreset::PlusZ);
        zoomToPatches(v, n[0] / 2, n[1] / 2, v.axisUm(2)[k]);
        const PixelProbe r = probePlane(v, m, v.axisUm(2)[k], k, displayed);
        out["slice_probes"] = r.probes;
        out["slice_mismatches"] = r.bad;
        out["slice_examples"] = r.examples;
        ok = ok && r.probes >= 20 && r.bad == 0;
        v.setSlice(2, false, k);
        v.setSurfaceMode(SurfaceMode::Field);
    }

    // (c) isosurface: every vertex on ONE grid edge whose end values
    // bracket the level, at the linear interpolation (flying edges keeps
    // points in float: the fractional index carries ~1e-7 relative error).
    {
        const auto r = v.dataRange();
        const double level = r[0] + 0.37 * (r[1] - r[0]);
        v.setIsosurface(true);
        v.setIsoLevel(level);
        vtkPolyData* iso = v.isoPoly();
        const vtkIdType np = iso->GetNumberOfPoints();
        long long bad = 0;
        auto locate = [&](int a, double x, std::size_t* i, double* f) {
            const auto& ax = v.axisUm(a);
            const auto it = std::lower_bound(ax.begin(), ax.end(), x);
            if (it != ax.end() && *it == x) {
                *i = static_cast<std::size_t>(it - ax.begin());
                *f = 0.0;
                return true;  // on a node plane
            }
            if (it == ax.begin() || it == ax.end()) return false;
            *i = static_cast<std::size_t>(it - ax.begin()) - 1;
            *f = (x - ax[*i]) / (ax[*i + 1] - ax[*i]);
            return false;
        };
        for (vtkIdType q = 0; q < np; ++q) {
            double p[3];
            iso->GetPoint(q, p);
            std::size_t idx[3];
            double frac[3];
            int on = 0, free_axis = -1;
            for (int a = 0; a < 3; ++a) {
                if (locate(a, p[a], &idx[a], &frac[a])) ++on;
                else free_axis = a;
            }
            bool v_ok;
            if (on == 3) {
                v_ok = std::abs(displayed((idx[2] * n[1] + idx[1]) * n[0] + idx[0]) - level) <= 1e-12 * std::max(1.0, std::abs(level));
            } else if (on == 2) {
                std::size_t i0[3] = {idx[0], idx[1], idx[2]}, i1[3] = {idx[0], idx[1], idx[2]};
                i1[free_axis] += 1;
                const double v0 = displayed((i0[2] * n[1] + i0[1]) * n[0] + i0[0]);
                const double v1 = displayed((i1[2] * n[1] + i1[1]) * n[0] + i1[0]);
                const double interp = v0 + frac[free_axis] * (v1 - v0);
                const bool brackets = (v0 - level) * (v1 - level) <= 0.0;
                v_ok = brackets && std::abs(interp - level) <= 1e-5 * std::abs(v1 - v0) + 1e-12 * std::max(1.0, std::abs(level));
            } else {
                v_ok = false;  // off the grid's edges: remapped along the wrong axis
            }
            bad += v_ok ? 0 : 1;
        }
        out["iso"] = {{"level", level}, {"vertices", np}, {"mismatched", bad}};
        ok = ok && np > 0 && bad == 0;
        v.setIsosurface(false);
    }

    // (d) volume: transfer functions, and pixels change only inside the
    // device's projected silhouette
    {
        v.setSurfaceMode(SurfaceMode::Hidden);
        v.setViewPreset(ViewPreset::Iso);
        v.setVolumePreset(VolumePreset::LogHigh);  // recolours the bar: grab 'off' after it
        const QImage off = v.grabFramebuffer();
        v.setVolume(true);
        const QImage on = v.grabFramebuffer();
        vtkVolumeProperty* prop = v.volumeProp()->GetProperty();
        vtkColorTransferFunction* ctf = prop->GetRGBTransferFunction();
        vtkPiecewiseFunction* otf = prop->GetScalarOpacity();
        long long tf_bad = 0;
        const vtkIdType nt = v.lookupTable()->GetNumberOfTableValues();
        for (vtkIdType q = 0; q < nt; ++q) {
            double want[4], got[6];
            v.lookupTable()->GetTableValue(q, want);
            ctf->GetNodeValue(static_cast<int>(q), got);  // x, r, g, b, midpoint, sharpness
            tf_bad += (same_bits(got[1], want[0]) && same_bits(got[2], want[1]) && same_bits(got[3], want[2])) ? 0 : 1;
        }
        const double op = volumePresetSpec(VolumePreset::LogHigh).opacity;
        const bool op_ok = otf->GetValue(0.0) == op && otf->GetValue(0.5) == op && otf->GetValue(1.0) == op &&
                           v.colorMap() == ColorMap::Plasma;
        // the silhouette: the display bounding box of the node box's 8 corners
        double xmin = 1e300, xmax = -1e300, ymin = 1e300, ymax = -1e300;
        for (int c = 0; c < 8; ++c) {
            const auto d = project(v, c & 1 ? v.axisUm(0).back() : v.axisUm(0).front(),
                                   c & 2 ? v.axisUm(1).back() : v.axisUm(1).front(),
                                   c & 4 ? v.axisUm(2).back() : v.axisUm(2).front());
            xmin = std::min(xmin, d[0]);
            xmax = std::max(xmax, d[0]);
            ymin = std::min(ymin, d[1]);
            ymax = std::max(ymax, d[1]);
        }
        const int H = v.renderWindow()->GetSize()[1];
        long long inside = 0, outside = 0;
        for (int y = 0; y < on.height(); ++y)
            for (int x = 0; x < on.width(); ++x) {
                if (on.pixel(x, y) == off.pixel(x, y)) continue;
                const double yd = H - 1 - y;
                if (!inMapViewport(v, x, yd)) continue;  // the bar's column
                const bool in = x >= xmin - 2 && x <= xmax + 2 && yd >= ymin - 2 && yd <= ymax + 2;
                (in ? inside : outside) += 1;
            }
        out["volume"] = {{"colour_nodes", ctf->GetSize()}, {"colour_mismatches", tf_bad}, {"opacity_ok", op_ok},
                         {"changed_inside", inside}, {"changed_outside", outside}};
        ok = ok && tf_bad == 0 && ctf->GetSize() == nt && op_ok && inside > 0 && outside == 0;
        v.setVolume(false);
        v.setColorMap(std::nullopt);
        v.setSurfaceMode(SurfaceMode::Field);
    }

    // (e) glyphs and (f) streamlines, when the result has a vector field
    if (!m.vector_names().empty()) {
        const VectorField vf = m.vector(v.vectorField());
        v.setGlyphs(true);
        vtkPolyData* src = v.glyphSources();
        auto* J = vtkDoubleArray::SafeDownCast(src->GetPointData()->GetArray("J"));
        auto* node_ids = vtkIdTypeArray::SafeDownCast(src->GetPointData()->GetArray("tcad_node_id"));
        long long bad = 0;
        Json glyph_examples = Json::array();
        double max_mag = 0.0;
        for (std::size_t q = 0; q < vf.components[0].size(); ++q)
            max_mag = std::max(max_mag, std::sqrt(vf.components[0][q] * vf.components[0][q] + vf.components[1][q] * vf.components[1][q] +
                                                  vf.components[2][q] * vf.components[2][q]));
        const vtkIdType ns = src->GetNumberOfPoints();
        for (vtkIdType q = 0; J && node_ids && q < ns; ++q) {
            const auto u = static_cast<std::size_t>(node_ids->GetValue(q));
            const std::size_t node[3] = {u % n[0], (u / n[0]) % n[1], u / (n[0] * n[1])};
            double p[3], j3[3];
            src->GetPoint(q, p);
            J->GetTuple(q, j3);
            bool g_ok = same_coord(p[0], v.axisUm(0)[node[0]]) && same_coord(p[1], v.axisUm(1)[node[1]]) &&
                        same_coord(p[2], v.axisUm(2)[node[2]]);
            for (int c = 0; c < 3; ++c) g_ok = g_ok && same_bits(j3[c], vf.components[static_cast<std::size_t>(c)][u]);
            bad += g_ok ? 0 : 1;
            if (!g_ok && glyph_examples.size() < 3)
                glyph_examples.push_back({{"node", {node[0], node[1], node[2]}}, {"point", {p[0], p[1], p[2]}},
                                          {"node_um", {v.axisUm(0)[node[0]], v.axisUm(1)[node[1]], v.axisUm(2)[node[2]]}},
                                          {"J", {j3[0], j3[1], j3[2]}},
                                          {"J_node", {vf.components[0][u], vf.components[1][u], vf.components[2][u]}}});
        }
        const double want_len = std::max(v.glyphSpacing(), 0.02) * v.diagonalUm();
        const double got_len = v.glyphScaleFactor() * max_mag;
        const bool len_ok = std::abs(got_len - want_len) <= 1e-12 * want_len;
        out["glyphs"] = {{"sources", ns}, {"mismatched", bad}, {"longest_arrow_um", got_len}, {"spacing_um", want_len},
                         {"polys", v.glyphPoly()->GetNumberOfCells()}, {"examples", glyph_examples}};
        ok = ok && J && node_ids && ns > 0 && bad == 0 && len_ok && v.glyphPoly()->GetNumberOfCells() > 0;
        v.setGlyphs(false);

        v.setStreamlines(true);
        vtkPolyData* sl = v.streamlinePoly();
        const vtkIdType sp = sl->GetNumberOfPoints();
        long long outside = 0, segs = 0, aligned = 0;
        double worst = 1.0;
        const double tol = 1e-9 * v.diagonalUm();
        for (vtkIdType q = 0; q < sp; ++q) {
            double p[3];
            sl->GetPoint(q, p);
            for (int a = 0; a < 3; ++a)
                if (p[a] < v.axisUm(a).front() - tol || p[a] > v.axisUm(a).back() + tol) {
                    ++outside;
                    break;
                }
        }
        auto* SJ = sl->GetPointData()->GetArray("J");
        vtkCellArray* lines = sl->GetLines();
        vtkIdType npts = 0;
        const vtkIdType* pts = nullptr;
        for (lines->InitTraversal(); SJ && lines->GetNextCell(npts, pts);)
            for (vtkIdType q = 0; q + 1 < npts; ++q) {
                // A chord of a curved line is parallel to the MEAN of its
                // ends' unit tangents (exact on a circular arc), not to
                // either end's.
                double a[3], b[3], ja[3], jb[3], j3[3];
                sl->GetPoint(pts[q], a);
                sl->GetPoint(pts[q + 1], b);
                SJ->GetTuple(pts[q], ja);
                SJ->GetTuple(pts[q + 1], jb);
                const double la = std::sqrt(ja[0] * ja[0] + ja[1] * ja[1] + ja[2] * ja[2]);
                const double lb = std::sqrt(jb[0] * jb[0] + jb[1] * jb[1] + jb[2] * jb[2]);
                if (la == 0.0 || lb == 0.0) continue;
                for (int c = 0; c < 3; ++c) j3[c] = ja[c] / la + jb[c] / lb;
                const double d[3] = {b[0] - a[0], b[1] - a[1], b[2] - a[2]};
                const double dl = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
                const double jl = std::sqrt(j3[0] * j3[0] + j3[1] * j3[1] + j3[2] * j3[2]);
                if (dl <= tol || jl == 0.0) continue;
                const double c = std::abs(d[0] * j3[0] + d[1] * j3[1] + d[2] * j3[2]) / (dl * jl);
                ++segs;
                aligned += c > 0.99 ? 1 : 0;
                worst = std::min(worst, c);
            }
        out["streamlines"] = {{"points", sp}, {"outside_device", outside}, {"segments", segs},
                              {"aligned_0_99", aligned}, {"worst_cos", worst}};
        ok = ok && sp > 0 && outside == 0 && segs > 0 && aligned * 100 >= segs * 99;
        v.setStreamlines(false);
    }

    // (g) exploded view: each region's bounds are its nodes' patch box,
    // offset along z by (list index) x separation
    if (v.explodedAvailable()) {
        v.setExploded(true);
        Json regions = Json::array();
        const double tol = 1e-9 * v.diagonalUm();
        long long bad = 0;
        for (const auto& r : v.explodedRegions()) {
            double b[6];
            r.actor->GetBounds(b);
            bool r_ok = std::abs(r.offset_um - static_cast<double>(r.list_index) * v.explodedSeparation()) <= tol;
            for (int a = 0; a < 3; ++a) {
                const double shift = a == 2 ? r.offset_um : 0.0;
                r_ok = r_ok && std::abs(b[2 * a] - (v.edgesUm(a)[r.nodes.lo[static_cast<std::size_t>(a)]] + shift)) <= tol &&
                       std::abs(b[2 * a + 1] - (v.edgesUm(a)[r.nodes.hi[static_cast<std::size_t>(a)] + 1] + shift)) <= tol;
            }
            bad += r_ok ? 0 : 1;
            regions.push_back({{"name", r.name}, {"offset_um", r.offset_um}, {"ok", r_ok}});
        }
        out["exploded"] = regions;
        ok = ok && !v.explodedRegions().empty() && bad == 0;
        v.setExploded(false);
    }

    // (h) playback: each snapshot's displayed values, against a reference
    // built here from a fresh decode, over the union range
    if (const SweepSnapshots* s = v.snapshots()) {
        const std::string sf = s->field_names.front();
        v.setField(sf);
        v.setLogScale(false);
        const SweepSnapshots mine = m.sweep_snapshots();
        vtkNew<vtkDoubleArray> all;
        for (std::size_t k = 0; k < mine.count(); ++k)
            for (double x : m.snapshot_field(mine, sf, k)) all->InsertNextValue(v.displayTransform(x));
        double want[2];
        all->GetRange(want);
        if (v.fieldKind() == FieldKind::Doping) {
            const double mm = std::max(std::abs(want[0]), std::abs(want[1]));
            want[0] = -mm;
            want[1] = mm;
        }
        long long bad = 0;
        Json frames = Json::array();
        for (std::size_t k = 0; k < mine.count(); ++k) {
            v.setSnapshot(k);
            const std::vector<double> snap = m.snapshot_field(mine, sf, k);
            vtkIdTypeArray* ids = v.displayedNodeIds();
            vtkDoubleArray* shown = v.displayedScalars();
            long long fb = 0;
            for (vtkIdType q = 0; q < ids->GetNumberOfValues(); ++q) {
                const double e = lut_input(v.displayTransform(snap[static_cast<std::size_t>(ids->GetValue(q))]), want[0], want[1]);
                fb += same_bits(shown->GetValue(q), e) ? 0 : 1;
            }
            const bool range_ok = same_bits(v.normRange()[0], want[0]) && same_bits(v.normRange()[1], want[1]);
            frames.push_back({{"index", k}, {"voltage", s->voltages[k]}, {"mismatched", fb}, {"range_ok", range_ok}});
            bad += fb + (range_ok ? 0 : 1);
        }
        v.setSnapshot(std::nullopt);
        out["playback"] = {{"field", sf}, {"frames", frames}, {"mismatched", bad}};
        ok = ok && bad == 0 && mine.count() > 0;
        v.setField(field);
    }

    // (i) the hover oracle again, on a crop box
    {
        NodeBox box;
        for (std::size_t a = 0; a < 3; ++a) {
            box.lo[a] = n[a] / 4;
            box.hi[a] = std::max(box.lo[a], (3 * n[a]) / 4);
        }
        v.setCrop(box);
        v.setViewPreset(ViewPreset::Iso);
        out["hover_cropped"] = check_hover(v, o);
        ok = ok && out["hover_cropped"]["ok"].get<bool>();
        v.setCrop(v.fullBox());
        v.setViewPreset(ViewPreset::Iso);
    }
    out["ok"] = ok;
    return out;
}

}  // namespace

nlohmann::ordered_json run_selftest(MainWindow& window, const SelftestOptions& o) {
    FieldView* view = window.fieldView();
    view->setMinimumSize(o.width, o.height);
    view->setMaximumSize(o.width, o.height);
    window.show();
    wait_for_gl(view);

    bool all_ok = true;
    Json files = Json::array();
    for (const QString& path : o.result_paths) {
        window.openResult(path);
        QApplication::processEvents();
        const ResultModel& m = *window.result();
        Json f = {{"file", path.toStdString()}, {"dimensionality", m.dimensionality()}};
        if (m.dimensionality() < 2) {
            f["note"] = "1D: no FieldView";
            files.push_back(f);
            continue;
        }
        bool ok = true;
        f["node_ids"] = check_node_ids(*view, m);
        ok = ok && f["node_ids"]["ok"].get<bool>();
        Json fields = Json::array();
        for (const auto& name : m.scalar_names()) {
            for (bool log : {false, true}) {
                fields.push_back(check_field(*view, m, name, log));
                ok = ok && fields.back()["ok"].get<bool>();
            }
        }
        f["fields"] = fields;
        view->setLogScale(false);
        view->setField(m.scalar_names().front());
        view->resetView();
        f["scale"] = check_scale(*view, m);
        ok = ok && f["scale"]["ok"].get<bool>();
        if (m.dimensionality() == 3) {
            f["hover"] = check_hover(*view, o);
            ok = ok && f["hover"]["ok"].get<bool>();
            f["layers"] = check_3d(*view, m, o);  // S6
            ok = ok && f["layers"]["ok"].get<bool>();
        } else {
            f["bar"] = check_bar(*view);
            ok = ok && f["bar"]["ok"].get<bool>();
            f["pixels"] = check_pixels(*view, m);
            ok = ok && f["pixels"]["ok"].get<bool>();
        }
        f["ok"] = ok;
        all_ok = all_ok && ok;
        files.push_back(f);
    }
    return {{"ok", all_ok}, {"files", files}};
}

namespace {

std::array<double, 2> memory_mb() {
    PROCESS_MEMORY_COUNTERS_EX pmc{};
    pmc.cb = sizeof pmc;
    if (!GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof pmc))
        return {-1.0, -1.0};
    return {static_cast<double>(pmc.PrivateUsage) / 1048576.0, static_cast<double>(pmc.WorkingSetSize) / 1048576.0};
}

void exercise(FieldView& v, const ResultModel& m) {
    const auto& names = m.scalar_names();
    for (std::size_t i = 0; i < names.size() && i < 4; ++i) {
        v.setField(names[i]);
        v.setLogScale(i % 2 == 1);
    }
    v.setLogScale(false);
    if (!v.is3D()) {
        v.setContours(true);
        v.setMeshLines(true);
        v.setContours(false);
        v.setMeshLines(false);
        return;
    }
    const auto n = m.node_counts();
    NodeBox half = v.fullBox();
    for (std::size_t a = 0; a < 3; ++a) half.lo[a] = n[a] / 3;
    v.setCrop(half);
    v.setCrop(v.fullBox());
    v.setSlice(2, true, n[2] / 2);
    v.setSlice(2, false, n[2] / 2);
    v.setIsosurface(true);
    v.setIsosurface(false);
    v.setVolume(true);
    v.setVolume(false);
    v.setColorMap(std::nullopt);
    if (!m.vector_names().empty()) {
        v.setGlyphs(true);
        v.setGlyphs(false);
        v.setStreamlines(true);
        v.setStreamlines(false);
    }
    if (v.explodedAvailable()) {
        v.setExploded(true);
        v.setExploded(false);
    }
    if (const SweepSnapshots* s = v.snapshots()) {
        v.setField(s->field_names.front());
        for (std::size_t k = 0; k < s->count(); ++k) v.setSnapshot(k);
        v.setSnapshot(std::nullopt);
    }
    v.setSurfaceMode(SurfaceMode::Field);
}

}  // namespace

nlohmann::ordered_json run_soak(MainWindow& window, const QStringList& files, int cycles, int width, int height) {
    FieldView* view = window.fieldView();
    view->setMinimumSize(width, height);
    view->setMaximumSize(width, height);
    window.show();
    wait_for_gl(view);
    const int gl_before = view->glInitializations();
    Json priv = Json::array(), ws = Json::array(), secs = Json::array();
    for (int c = 0; c < cycles; ++c) {
        const auto t0 = std::chrono::steady_clock::now();
        for (const QString& f : files) {
            window.openResult(f);
            QApplication::processEvents();
            exercise(*view, *window.result());
            QApplication::processEvents();
        }
        const auto mem = memory_mb();
        priv.push_back(mem[0]);
        ws.push_back(mem[1]);
        secs.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count());
    }
    const int reinits = view->glInitializations() - gl_before;
    return {{"cycles", cycles}, {"files", files.size()}, {"private_mb", priv}, {"working_set_mb", ws},
            {"cycle_s", secs}, {"gl_reinits", reinits}, {"ok", reinits == 0}};
}

}  // namespace tcad::desktop
