#include "plot_geometry.hpp"

#include <algorithm>

namespace tcad::desktop::plot {

namespace {

// Liang-Barsky: the part of segment a->b inside the rectangle, as
// parameters [t0, t1]; false when none of it is.
bool clip_segment(const Pt& a, const Pt& b, double x0, double y0, double x1, double y1, double& t0, double& t1) {
    t0 = 0.0;
    t1 = 1.0;
    const double dx = b.x - a.x, dy = b.y - a.y;
    const double p[4] = {-dx, dx, -dy, dy};
    const double q[4] = {a.x - x0, x1 - a.x, a.y - y0, y1 - a.y};
    for (int i = 0; i < 4; ++i) {
        if (p[i] == 0.0) {
            if (q[i] < 0.0) return false;  // parallel and outside
            continue;
        }
        const double r = q[i] / p[i];
        if (p[i] < 0.0) t0 = std::max(t0, r);
        else t1 = std::min(t1, r);
        if (t0 > t1) return false;
    }
    return true;
}

Pt lerp(const Pt& a, const Pt& b, double t) { return {a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t}; }

}  // namespace

bool segment_hits_rect(const Pt& a, const Pt& b, double x0, double y0, double x1, double y1) {
    double t0, t1;
    return clip_segment(a, b, x0, y0, x1, y1, t0, t1);
}

std::vector<std::vector<Pt>> clip_polyline(const std::vector<Pt>& pts, double x0, double y0, double x1, double y1) {
    std::vector<std::vector<Pt>> out;
    std::vector<Pt> cur;
    auto flush = [&] {
        if (cur.size() >= 2) out.push_back(std::move(cur));
        cur.clear();
    };
    for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
        double t0, t1;
        if (!clip_segment(pts[i], pts[i + 1], x0, y0, x1, y1, t0, t1)) {
            flush();
            continue;
        }
        const Pt a = t0 > 0.0 ? lerp(pts[i], pts[i + 1], t0) : pts[i];
        const Pt b = t1 < 1.0 ? lerp(pts[i], pts[i + 1], t1) : pts[i + 1];
        if (cur.empty() || t0 > 0.0) {  // a new piece starts where the edge enters
            flush();
            cur.push_back(a);
        }
        cur.push_back(b);
        if (t1 < 1.0) flush();  // it leaves before its end
    }
    flush();
    return out;
}

std::vector<Pt> decimate_columns(const std::vector<Pt>& pts) {
    std::vector<Pt> out;
    out.reserve(std::min<std::size_t>(pts.size(), 4096));
    std::size_t i = 0;
    while (i < pts.size()) {
        const double col = std::floor(pts[i].x);
        std::size_t j = i, imin = i, imax = i;
        while (j < pts.size() && std::floor(pts[j].x) == col) {
            if (pts[j].y < pts[imin].y) imin = j;
            if (pts[j].y > pts[imax].y) imax = j;
            ++j;
        }
        const std::size_t last = j - 1;
        std::size_t keep[4] = {i, std::min(imin, imax), std::max(imin, imax), last};
        for (std::size_t k = 0; k < 4; ++k)
            if (k == 0 || keep[k] != keep[k - 1]) out.push_back(pts[keep[k]]);
        i = j;
    }
    return out;
}

DenseDrawing dense_columns(const std::vector<Pt>& pts, double bar_px) {
    DenseDrawing out;
    std::vector<Pt> cur;
    auto end_line = [&] {
        if (cur.size() >= 2) out.lines.push_back(std::move(cur));
        cur.clear();
    };
    bool have_prev = false;
    Pt prev_last{0, 0};
    std::size_t i = 0;
    while (i < pts.size()) {
        const double col = std::floor(pts[i].x);
        std::size_t j = i;
        double lo = pts[i].y, hi = pts[i].y;
        while (j < pts.size() && std::floor(pts[j].x) == col) {
            lo = std::min(lo, pts[j].y);
            hi = std::max(hi, pts[j].y);
            ++j;
        }
        const Pt& last = pts[j - 1];
        std::size_t imin = i, imax = i;
        for (std::size_t k = i; k < j; ++k) {
            if (pts[k].y < pts[imin].y) imin = k;
            if (pts[k].y > pts[imax].y) imax = k;
        }
        if (j - i >= 3 && hi - lo > bar_px) {
            // The edge into this column: from the adjacent column it spans at
            // most two pixels across, so the bar's vertical reach covers it;
            // from further away it is a real line, stroked on its own.
            const bool adjacent = have_prev && std::floor(prev_last.x) >= col - 1;
            if (adjacent) {
                lo = std::min(lo, prev_last.y);
                hi = std::max(hi, prev_last.y);
            }
            out.bars.push_back({col, lo, hi});
            end_line();         // the line stops at the previous column's last point...
            if (have_prev && !adjacent) out.lines.push_back({prev_last, pts[i]});
            cur.push_back(last);  // ...and resumes from this bar's last point
        } else {  // a short column: first, min, max (in order), last -- as decimate_columns
            if (cur.empty() && have_prev) cur.push_back(prev_last);
            const std::size_t keep[4] = {i, std::min(imin, imax), std::max(imin, imax), j - 1};
            for (std::size_t k = 0; k < 4; ++k)
                if (k == 0 || keep[k] != keep[k - 1]) cur.push_back(pts[keep[k]]);
        }
        prev_last = last;
        have_prev = true;
        i = j;
    }
    end_line();
    return out;
}

std::vector<HoverHit> nearest_samples(const std::vector<HoverSeries>& series, double cx, double max_score) {
    double best = std::numeric_limits<double>::infinity();
    std::vector<HoverHit> hits;
    for (std::size_t s = 0; s < series.size(); ++s) {
        const auto& hs = series[s];
        if (!hs.tx || !hs.ty || !(hs.span_x > 0) || !(hs.span_y > 0)) continue;
        const auto& tx = *hs.tx;
        const auto& ty = *hs.ty;
        const std::size_t n = std::min(tx.size(), ty.size());
        for (std::size_t i = 0; i < n; ++i) {
            const double score = std::abs(tx[i] - cx) / hs.span_x + std::abs(ty[i] - hs.cy) / hs.span_y;
            if (!(score <= best)) continue;  // NaN (a gap) never scores
            if (score < best) {
                best = score;
                hits.clear();
            }
            hits.push_back({s, i, score});
        }
    }
    if (!(best <= max_score)) hits.clear();
    return hits;
}

}  // namespace tcad::desktop::plot
