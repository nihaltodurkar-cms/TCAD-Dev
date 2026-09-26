#include "field_view.hpp"

#include "data/contour_levels.hpp"
#include "data/grid_edges.hpp"

#include <QMouseEvent>
#include <QResizeEvent>
#include <vtkCallbackCommand.h>
#include <vtkCamera.h>
#include <vtkCellArray.h>
#include <vtkCellData.h>
#include <vtkCoordinate.h>
#include <vtkDataSetSurfaceFilter.h>
#include <vtkIdTypeArray.h>
#include <vtkInteractorStyleTrackballCamera.h>
#include <vtkObjectFactory.h>
#include <vtkPointData.h>
#include <vtkPoints.h>
#include <vtkPolyDataAlgorithm.h>
#include <vtkProperty.h>
#include <vtkRectilinearGridGeometryFilter.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkTextProperty.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tcad::desktop {
namespace {

constexpr double kMinPositive = 1e-30;  // same floor as mpl_canvas_item._MIN_POSITIVE
constexpr const char* kNodeIdArray = "tcad_node_id";
constexpr double kBarColumnPx = 130.0;  // the scalar bar's viewport width, logical px

// Milliseconds since `t0`, and reset `t0` to now: consecutive phases.
double lap_ms(std::chrono::steady_clock::time_point& t0) {
    const auto t1 = std::chrono::steady_clock::now();
    const double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    t0 = t1;
    return ms;
}

// 2D maps: left-drag pans (the QML viewport's gesture), wheel and
// right-drag zoom; no rotation.
class PanZoom2DStyle : public vtkInteractorStyleTrackballCamera {
public:
    static PanZoom2DStyle* New();
    vtkTypeMacro(PanZoom2DStyle, vtkInteractorStyleTrackballCamera);

    void OnLeftButtonDown() override {
        FindPokedRenderer(Interactor->GetEventPosition()[0], Interactor->GetEventPosition()[1]);
        if (!CurrentRenderer) return;
        GrabFocus(EventCallbackCommand);
        StartPan();
    }
    void OnLeftButtonUp() override {
        if (State == VTKIS_PAN) {
            EndPan();
            if (Interactor) ReleaseFocus();
        }
    }
};
vtkStandardNewMacro(PanZoom2DStyle);

vtkSmartPointer<vtkDoubleArray> coordinates(const std::vector<double>& um) {
    auto a = vtkSmartPointer<vtkDoubleArray>::New();
    if (um.empty()) {
        a->InsertNextValue(0.0);
    } else {
        a->SetNumberOfValues(static_cast<vtkIdType>(um.size()));
        for (std::size_t i = 0; i < um.size(); ++i) a->SetValue(static_cast<vtkIdType>(i), um[i]);
    }
    return a;
}

ColorMap defaultMap(FieldKind k) {
    switch (k) {
        case FieldKind::Recombination: return ColorMap::Inferno;
        case FieldKind::Doping: return ColorMap::RdBuR;
        case FieldKind::Band:
        case FieldKind::Generic: break;
    }
    return ColorMap::Viridis;
}

double absLog(double v) { return std::log10(std::max(std::abs(v), kMinPositive)); }
double signedLog(double v) { return (v > 0 ? 1.0 : v < 0 ? -1.0 : 0.0) * std::log10(std::max(std::abs(v), 1.0)); }

}  // namespace

FieldKind fieldKindOf(const std::string& name) {
    if (name == "doping") return FieldKind::Doping;
    if (name == "Ec" || name == "Ev" || name == "EFn" || name == "EFp") return FieldKind::Band;
    if (name == "R") return FieldKind::Recombination;
    return FieldKind::Generic;
}

FieldView::FieldView(QWidget* parent) : QVTKOpenGLNativeWidget(parent) {
    setRenderWindow(window_);
    window_->AddRenderer(renderer_);
    window_->AddRenderer(bar_renderer_);
    bar_renderer_->InteractiveOff();  // wheel and drags over the bar reach the map (review rev. 4)
    fill_lut(lut_, ColorMap::Viridis);
    fill_lut(bar_lut_, ColorMap::Viridis);

    scalars_->SetName("values");
    node_values_->SetName("displayed");

    mapper_->SetLookupTable(lut_);
    mapper_->ScalarVisibilityOn();
    mapper_->SetScalarRange(0.0, 1.0);        // scalars are lut_input(): see colormaps.hpp
    mapper_->InterpolateScalarsBeforeMappingOn();  // 3D point data; 2D cell data is flat anyway
    actor_->SetMapper(mapper_);
    actor_->VisibilityOff();

    // The bar and its title in their own viewport (review revisions 4-5):
    // the bar actor fills the left of the column, the title runs vertically
    // in the right of it, as matplotlib places a colorbar label.
    bar_->SetLookupTable(bar_lut_);
    bar_->SetNumberOfLabels(5);
    bar_->SetTitle("");
    bar_->GetPositionCoordinate()->SetCoordinateSystemToNormalizedViewport();
    bar_->SetPosition(0.05, 0.05);
    bar_->SetPosition2(0.72, 0.9);
    bar_->GetLabelTextProperty()->SetFontSize(11);
    bar_->VisibilityOff();
    title_->GetTextProperty()->SetFontSize(12);
    title_->GetTextProperty()->SetJustificationToCentered();
    title_->GetTextProperty()->SetVerticalJustificationToCentered();
    title_->GetTextProperty()->SetOrientation(90.0);
    title_->GetPositionCoordinate()->SetCoordinateSystemToNormalizedViewport();
    title_->SetPosition(0.88, 0.5);
    title_->VisibilityOff();
    bar_renderer_->AddViewProp(bar_);
    bar_renderer_->AddViewProp(title_);

    // 2D overlays: contours on the node grid, lines through the nodes.
    contour_mapper_->SetInputData(contour_poly_);
    contour_mapper_->ScalarVisibilityOff();
    contour_actor_->SetMapper(contour_mapper_);
    contour_actor_->GetProperty()->SetOpacity(0.7);  // the QML view's alpha
    contour_actor_->GetProperty()->LightingOff();
    contour_actor_->VisibilityOff();
    mesh_mapper_->ScalarVisibilityOff();
    mesh_actor_->SetMapper(mesh_mapper_);
    mesh_actor_->GetProperty()->SetOpacity(0.35);
    mesh_actor_->GetProperty()->LightingOff();
    mesh_actor_->VisibilityOff();
    // P2-S4: the line cut's line -- a halo under a line, one geometry.
    cut_mapper_->ScalarVisibilityOff();
    for (vtkActor* a : {cut_halo_actor_.Get(), cut_actor_.Get()}) {
        a->SetMapper(cut_mapper_);
        a->GetProperty()->LightingOff();
        a->PickableOff();
        a->VisibilityOff();
    }

    renderer_->AddViewProp(actor_);
    renderer_->AddViewProp(mesh_actor_);
    renderer_->AddViewProp(contour_actor_);
    renderer_->AddViewProp(cut_halo_actor_);
    renderer_->AddViewProp(cut_actor_);
    setup3D();
    applyTheme();

    picker_->SetTolerance(0.0005);
    picker_->PickFromListOn();
    picker_->AddPickList(actor_);  // 3D: updatePickList() keeps the list in step with the layers
    setMouseTracking(true);
}

FieldView::~FieldView() = default;

void FieldView::applyTheme() {
    const theme::Rgb bg = theme::rgb(theme::T::Background), fg = theme::rgb(theme::T::Text);
    const theme::Rgb ov = theme::rgb(theme::T::Overlay);
    renderer_->SetBackground(bg.r, bg.g, bg.b);
    bar_renderer_->SetBackground(bg.r, bg.g, bg.b);
    for (vtkTextProperty* tp : {bar_->GetTitleTextProperty(), bar_->GetLabelTextProperty(), title_->GetTextProperty()})
        tp->SetColor(fg.r, fg.g, fg.b);
    contour_actor_->GetProperty()->SetColor(ov.r, ov.g, ov.b);
    mesh_actor_->GetProperty()->SetColor(ov.r, ov.g, ov.b);
    cut_actor_->GetProperty()->SetColor(ov.r, ov.g, ov.b);
    cut_halo_actor_->GetProperty()->SetColor(fg.r, fg.g, fg.b);
    // the 3D box sits on the background, not on the map: text-coloured (white vanished on white)
    outline_actor_->GetProperty()->SetColor(fg.r, fg.g, fg.b);
    for (vtkTextProperty* tp : {vbar_->GetLabelTextProperty(), vtitle_->GetTextProperty()}) tp->SetColor(fg.r, fg.g, fg.b);
    const theme::Rgb ctx = theme::rgb(theme::T::Context);
    if (surface_mode_ == SurfaceMode::Context) actor_->GetProperty()->SetColor(ctx.r, ctx.g, ctx.b);
    if (exploded_on_) rebuildExploded();
    renderNow();
}

bool FieldView::is3D() const { return model_ && model_->dimensionality() == 3; }

void FieldView::setResult(const ResultModel* model) {
    model_ = model;
    source_ = model;
    readout_.clear();
    snapshot_.reset();
    snapshots_.reset();
    snapshots_checked_ = false;
    snapshot_union_.clear();
    cut_.reset();  // a cut belongs to one result's mesh
    cut_actor_->VisibilityOff();
    cut_halo_actor_->VisibilityOff();
    if (!model_ || model_->dimensionality() < 2 || model_->scalar_names().empty()) {
        // 1D results are curves: PlotView, P2 (NATIVE-DESKTOP-PLAN.md section 9).
        for (vtkProp* p : std::initializer_list<vtkProp*>{actor_, bar_, title_, contour_actor_, mesh_actor_})
            p->VisibilityOff();
        reset3D();
        field_.clear();
        renderNow();
        return;
    }
    for (int a = 0; a < 3; ++a) {
        const auto& cm = model_->axis(a);
        auto& um = axes_um_[static_cast<std::size_t>(a)];
        um.resize(cm.size());
        std::transform(cm.begin(), cm.end(), um.begin(), [](double v) { return v * 1e4; });
    }
    const auto n = model_->node_counts();
    const auto nodes = static_cast<vtkIdType>(n[0] * n[1] * n[2]);
    grid_->SetDimensions(static_cast<int>(n[0]), static_cast<int>(n[1]), static_cast<int>(n[2]));
    grid_->SetXCoordinates(coordinates(axes_um_[0]));
    grid_->SetYCoordinates(coordinates(axes_um_[1]));
    grid_->SetZCoordinates(coordinates(axes_um_[2]));
    grid_->GetPointData()->Initialize();

    // Nearest shading, 2D and 3D: one cell per node on the patch-edge (dual)
    // grid, whose cell (i, j[, k]) IS node (i, j[, k]) -- so the node index
    // of every displayed patch rides through the geometry filter, and a
    // field switch only gathers (S2).
    vtkNew<vtkIdTypeArray> node_ids;
    node_ids->SetName(kNodeIdArray);
    node_ids->SetNumberOfValues(nodes);
    for (vtkIdType i = 0; i < nodes; ++i) node_ids->SetValue(i, i);
    const int dims = model_->dimensionality();
    for (int a = 0; a < 3; ++a) {
        auto& e = edges_um_[static_cast<std::size_t>(a)];
        if (a < dims) e = nearest_edges(axes_um_[static_cast<std::size_t>(a)]);
        else e.clear();
    }
    dual_grid_->SetDimensions(static_cast<int>(n[0] + 1), static_cast<int>(n[1] + 1), dims == 3 ? static_cast<int>(n[2] + 1) : 1);
    dual_grid_->SetXCoordinates(coordinates(edges_um_[0]));
    dual_grid_->SetYCoordinates(coordinates(edges_um_[1]));
    dual_grid_->SetZCoordinates(coordinates(edges_um_[2]));
    dual_grid_->GetCellData()->Initialize();
    dual_grid_->GetCellData()->AddArray(node_ids);
    actor_->GetProperty()->LightingOff();  // a field map's colours are data, not shading (3D too, S6)
    mapper_->SetScalarModeToUseCellData();
    picker_->RemoveAllLocators();
    if (is3D()) {
        vtkNew<vtkInteractorStyleTrackballCamera> style;
        window_->GetInteractor()->SetInteractorStyle(style);
        reset3D();
        rebuildSurface3D();
    } else {
        reset3D();
        vtkNew<vtkRectilinearGridGeometryFilter> extract;
        extract->SetInputData(dual_grid_);
        extract->Update();
        surface_ = vtkSmartPointer<vtkPolyData>::New();
        surface_->ShallowCopy(extract->GetOutput());
        surface_ids_ = vtkIdTypeArray::SafeDownCast(surface_->GetCellData()->GetArray(kNodeIdArray));
        if (!surface_ids_) throw std::runtime_error("geometry extraction dropped the node-index array");
        surface_->GetCellData()->SetScalars(scalars_);
        mapper_->SetInputData(surface_);
        vtkNew<PanZoom2DStyle> style;
        window_->GetInteractor()->SetInteractorStyle(style);
        buildMeshLines();  // 2D hover is analytic (display -> world), no pick
    }
    const auto& names = model_->scalar_names();
    if (std::find(names.begin(), names.end(), field_) == names.end()) field_ = names.front();
    if (!range_.locked) range_ = ColorRange{};
    actor_->VisibilityOn();
    bar_->VisibilityOn();
    title_->VisibilityOn();
    mesh_actor_->SetVisibility(!is3D() && mesh_lines_);
    source_ = model_;
    ++values_version_;
    rebuildScalars();
    iso_level_ = 0.5 * (data_range_[0] + data_range_[1]);
    rebuildContours();
    updateBarTitle();
    updateBars();
    updateViewports();
    resetCamera();
    renderNow();
    emit displayChanged();
}

void FieldView::setField(const std::string& name) {
    if (!model_ || (name == field_ && source_ == model_)) return;
    showField(model_, name);
}

void FieldView::setDerivedField(const ResultModel* source, const std::string& name) {
    if (!model_ || !source) return;
    bool same = source->dimensionality() == model_->dimensionality() && source->node_counts() == model_->node_counts();
    for (int a = 0; same && a < model_->dimensionality(); ++a) same = source->axis(a) == model_->axis(a);
    if (!same) throw std::invalid_argument("the derived map is on a different mesh from the open result");
    showField(source, name);
}

void FieldView::showField(const ResultModel* source, const std::string& name) {
    source_ = source;
    field_ = name;
    if (range_.manual && !range_.locked) range_ = ColorRange{};  // an unlocked manual range is per field
    ++values_version_;
    rebuildScalars();
    if (is3D()) {  // viewer3d.py re-centres the level on a field change
        iso_level_ = 0.5 * (data_range_[0] + data_range_[1]);
        rebuild3DValues();
    }
    rebuildContours();
    updateBarTitle();
    refresh();
    emit displayChanged();
}

void FieldView::setLogScale(bool on) {
    if (on == log_) return;
    log_ = on;
    if (!model_ || field_.empty()) return;
    ++values_version_;
    rebuildScalars();
    if (is3D()) {  // the level's units changed (log10 or not): re-centre it
        iso_level_ = 0.5 * (data_range_[0] + data_range_[1]);
        rebuild3DValues();
    }
    rebuildContours();
    updateBarTitle();
    refresh();
    emit displayChanged();
}

bool FieldView::logEffective() const {
    switch (fieldKind()) {
        case FieldKind::Band: return false;
        case FieldKind::Recombination: return true;
        case FieldKind::Doping:
        case FieldKind::Generic: break;
    }
    return log_;
}

double FieldView::displayTransform(double v) const {
    switch (fieldKind()) {
        case FieldKind::Band: return v;
        case FieldKind::Recombination: return absLog(v);
        case FieldKind::Doping: return log_ ? signedLog(v) : v;
        case FieldKind::Generic: break;
    }
    return log_ ? absLog(v) : v;
}

ColorMap FieldView::colorMap() const { return cmap_override_ ? *cmap_override_ : defaultMap(fieldKind()); }

void FieldView::setColorMap(std::optional<ColorMap> override_map) {
    cmap_override_ = override_map;
    if (!model_ || field_.empty()) return;
    rebuildScalars();  // refills the tables
    refresh();
    emit displayChanged();
}

void FieldView::setManualRange(double lo, double hi, bool locked) {
    range_ = ColorRange{true, lo, hi, locked};
    if (!model_ || field_.empty()) return;
    rebuildScalars();
    refresh();
    emit displayChanged();
}

void FieldView::setAutoRange() {
    range_ = ColorRange{};
    if (!model_ || field_.empty()) return;
    rebuildScalars();
    refresh();
    emit displayChanged();
}

void FieldView::setContours(bool on) {
    contours_ = on;
    if (!model_ || field_.empty()) return;
    rebuildContours();
    auto t0 = std::chrono::steady_clock::now();
    renderNow();
    contour_t_.render_ms = lap_ms(t0);
    emit displayChanged();
}

void FieldView::setMeshLines(bool on) {
    mesh_lines_ = on;
    mesh_actor_->SetVisibility(model_ && !is3D() && on);
    renderNow();
    emit displayChanged();
}

void FieldView::rebuildScalars() {
    auto t0 = std::chrono::steady_clock::now();
    raw_ = source_->scalar(field_);
    if (showingSnapshot()) loadSnapshotValues();  // S6 playback: the same field, at sweep point k
    switch_t_.decode_ms = lap_ms(t0);

    // The data's displayed min/max over EVERY node (a 3D surface shows only
    // some). NaN compares false, so it is skipped, as VTK's GetRange skips
    // it. |v|-log is not monotonic in v: take min/max of max(|v|, floor),
    // then log10 (monotonic), as P0/S2 did. The identity and the signed
    // log ARE monotonic in v: transform the min/max of v.
    const FieldKind kind = fieldKind();
    const bool abs_log = kind == FieldKind::Recombination || (kind == FieldKind::Generic && log_);
    double lo = std::numeric_limits<double>::infinity(), hi = -lo;
    for (const double v : raw_.values) {
        const double t = abs_log ? std::max(std::abs(v), kMinPositive) : v;
        if (t < lo) lo = t;
        if (t > hi) hi = t;
    }
    if (lo <= hi) {
        lo = abs_log ? std::log10(lo) : displayTransform(lo);
        hi = abs_log ? std::log10(hi) : displayTransform(hi);
        data_range_ = {lo, hi};
    } else {
        data_range_ = {0.0, 0.0};  // all NaN
    }
    // While a sweep snapshot is shown, the auto range spans every snapshot
    // of the field, so colours compare across frames (section 15.19, 8).
    if (showingSnapshot()) {
        const auto u = snapshotUnion();
        lo = u[0];
        hi = u[1];
    }
    if (kind == FieldKind::Doping && lo <= hi) {  // a diverging map centred on zero
        const double m = std::max(std::abs(lo), std::abs(hi));
        lo = -m;
        hi = m;
    }
    norm_ = range_.manual ? std::array<double, 2>{range_.lo, range_.hi} : std::array<double, 2>{lo, hi};
    switch_t_.range_ms = lap_ms(t0);

    // Gather the displayed elements' values, transformed and normalised.
    gather(surface_ids_, scalars_);
    if (is3D())
        for (auto& sl : slices_)
            if (sl.state.on) gather(sl.ids, sl.scalars);
    switch_t_.fill_ms = lap_ms(t0);

    fill_lut(lut_, colorMap());
    fill_lut(bar_lut_, colorMap());
    double bar[2] = {norm_[0], norm_[1]};
    if (!(bar[1] > bar[0])) {  // constant field: the labels need a span (P0)
        bar[0] -= 0.5;
        bar[1] += 0.5;
    }
    bar_lut_->SetTableRange(bar);
    if (is3D()) rebuild3DValues();
}

void FieldView::gather(vtkIdTypeArray* id_array, vtkDoubleArray* values) const {
    const vtkIdType shown = id_array->GetNumberOfValues();
    const vtkIdType* ids = shown ? id_array->GetPointer(0) : nullptr;
    const double* raw = raw_.values.data();
    values->SetNumberOfValues(shown);
    double* out = shown ? values->GetPointer(0) : nullptr;
    const double a = norm_[0], b = norm_[1];
    switch (fieldKind()) {
        case FieldKind::Recombination:
            for (vtkIdType k = 0; k < shown; ++k) out[k] = lut_input(absLog(raw[ids[k]]), a, b);
            break;
        case FieldKind::Doping:
            if (log_) {
                for (vtkIdType k = 0; k < shown; ++k) out[k] = lut_input(signedLog(raw[ids[k]]), a, b);
                break;
            }
            [[fallthrough]];
        case FieldKind::Band:
            for (vtkIdType k = 0; k < shown; ++k) out[k] = lut_input(raw[ids[k]], a, b);
            break;
        case FieldKind::Generic:
            if (log_)
                for (vtkIdType k = 0; k < shown; ++k) out[k] = lut_input(absLog(raw[ids[k]]), a, b);
            else
                for (vtkIdType k = 0; k < shown; ++k) out[k] = lut_input(raw[ids[k]], a, b);
            break;
    }
    values->Modified();
}

void FieldView::rebuildContours() {
    const bool on = contours_ && model_ && !is3D() && !field_.empty();
    contour_actor_->SetVisibility(on);
    contour_levels_.clear();
    if (!on) return;
    auto t0 = std::chrono::steady_clock::now();
    // matplotlib contours the DISPLAYED (transformed) node values, with
    // levels from their own min/max -- not from a manual colour range.
    const vtkIdType n = static_cast<vtkIdType>(raw_.values.size());
    node_values_->SetNumberOfValues(n);
    double* nv = node_values_->GetPointer(0);
    double zmin = std::numeric_limits<double>::infinity(), zmax = -zmin;
    for (vtkIdType i = 0; i < n; ++i) {
        nv[i] = displayTransform(raw_.values[static_cast<std::size_t>(i)]);
        if (nv[i] < zmin) zmin = nv[i];
        if (nv[i] > zmax) zmax = nv[i];
    }
    node_values_->Modified();
    contour_t_.fill_ms = lap_ms(t0);
    if (!(zmin <= zmax)) return;  // all NaN
    contour_levels_ = contour_levels(zmin, zmax, 8);
    contour_t_.levels_ms = lap_ms(t0);

    // Contour in INDEX space with the multithreaded flying-edges filter
    // (it needs a uniform grid), then map each point back along the true
    // axes. Marching squares interpolates linearly along cell edges, so a
    // point at fractional index i + f lies at x_i + f (x_i+1 - x_i): exactly
    // what contouring the rectilinear grid gives, ~155 ms -> a few ms at
    // 1M nodes (S5 profile; vtkContourFilter ran single-threaded per level).
    const auto nn = model_->node_counts();
    index_grid_->SetDimensions(static_cast<int>(nn[0]), static_cast<int>(nn[1]), 1);
    index_grid_->SetOrigin(0.0, 0.0, 0.0);
    index_grid_->SetSpacing(1.0, 1.0, 1.0);
    index_grid_->GetPointData()->SetScalars(node_values_);
    flying_edges_->SetInputData(index_grid_);
    flying_edges_->ComputeScalarsOff();
    flying_edges_->SetNumberOfContours(static_cast<int>(contour_levels_.size()));
    for (std::size_t i = 0; i < contour_levels_.size(); ++i)
        flying_edges_->SetValue(static_cast<int>(i), contour_levels_[i]);
    flying_edges_->Modified();
    flying_edges_->Update();
    vtkPolyData* in_index = flying_edges_->GetOutput();
    const vtkIdType np = in_index->GetNumberOfPoints();
    vtkNew<vtkPoints> pts;
    pts->SetDataTypeToDouble();
    pts->SetNumberOfPoints(np);
    const auto& ax = axes_um_[0];
    const auto& ay = axes_um_[1];
    auto along = [](const std::vector<double>& a, double fi) {
        const std::size_t last = a.size() - 1;
        if (last == 0) return a[0];
        std::size_t i = static_cast<std::size_t>(std::max(0.0, std::floor(fi)));
        if (i >= last) i = last - 1;
        const double f = fi - static_cast<double>(i);
        return a[i] + f * (a[i + 1] - a[i]);
    };
    for (vtkIdType k = 0; k < np; ++k) {
        double p[3];
        in_index->GetPoint(k, p);
        pts->SetPoint(k, along(ax, p[0]), along(ay, p[1]), 0.0);
    }
    contour_poly_->Initialize();
    contour_poly_->SetPoints(pts);
    contour_poly_->SetLines(in_index->GetLines());
    contour_poly_->Modified();
    contour_t_.filter_ms = lap_ms(t0);
}

void FieldView::buildMeshLines() {
    // A line through every node coordinate (the true, non-uniform axes),
    // spanning the patches -- the QML view's axvline/axhline overlay.
    vtkNew<vtkPoints> pts;
    vtkNew<vtkCellArray> lines;
    const auto& x = axes_um_[0];
    const auto& y = axes_um_[1];
    const double x0 = edges_um_[0].front(), x1 = edges_um_[0].back();
    const double y0 = edges_um_[1].front(), y1 = edges_um_[1].back();
    auto segment = [&](double ax, double ay, double bx, double by) {
        const vtkIdType i = pts->InsertNextPoint(ax, ay, 0.0);
        const vtkIdType j = pts->InsertNextPoint(bx, by, 0.0);
        const vtkIdType ids[2] = {i, j};
        lines->InsertNextCell(2, ids);
    };
    for (double xv : x) segment(xv, y0, xv, y1);
    for (double yv : y) segment(x0, yv, x1, yv);
    vtkNew<vtkPolyData> pd;
    pd->SetPoints(pts);
    pd->SetLines(lines);
    mesh_mapper_->SetInputData(pd);
    // Overlays sit a hair toward the camera (it looks along +z from -z).
    const double lift = -1e-3 * std::max(x1 - x0, y1 - y0);
    mesh_actor_->SetPosition(0.0, 0.0, lift);
    contour_actor_->SetPosition(0.0, 0.0, lift);
}

void FieldView::updateBarTitle() {
    const std::string unit = " [" + raw_.unit + "]";
    std::string text;
    switch (fieldKind()) {
        case FieldKind::Recombination: text = "log10 |" + field_ + "|" + unit; break;
        case FieldKind::Band: text = field_ + unit; break;
        case FieldKind::Doping: text = log_ ? "sign(N) log10 |" + field_ + "|" + unit : field_ + unit; break;
        case FieldKind::Generic: text = log_ ? "log10 |" + field_ + unit + "|" : field_ + unit; break;
    }
    title_->SetInput(text.c_str());
}

void FieldView::updateViewports() {
    const double device_w = std::max(1.0, width() * devicePixelRatioF());
    const double w = std::min(0.45, kBarColumnPx * devicePixelRatioF() / device_w);
    renderer_->SetViewport(0.0, 0.0, 1.0 - w, 1.0);
    bar_renderer_->SetViewport(1.0 - w, 0.0, 1.0, 1.0);
    const double dpr = devicePixelRatioF();
    // VTK draws lines thinner than 1 device px as 1 px (review rev. 6).
    contour_actor_->GetProperty()->SetLineWidth(static_cast<float>(std::max(1.0, 0.6 * dpr)));
    mesh_actor_->GetProperty()->SetLineWidth(static_cast<float>(std::max(1.0, 0.3 * dpr)));
    cut_halo_actor_->GetProperty()->SetLineWidth(static_cast<float>(std::max(3.0, 4.0 * dpr)));
    cut_actor_->GetProperty()->SetLineWidth(static_cast<float>(std::max(1.0, 1.5 * dpr)));
}

void FieldView::setCutLine(std::optional<CutLine> line) {
    cut_ = line;
    const bool show = cut_ && model_ && model_->dimensionality() == 2 && !edges_um_[0].empty() &&
                      !edges_um_[1].empty();
    if (show) {
        const double x0 = edges_um_[0].front(), x1 = edges_um_[0].back();
        const double y0 = edges_um_[1].front(), y1 = edges_um_[1].back();
        vtkNew<vtkPoints> pts;
        pts->SetDataTypeToDouble();  // exactly on the node, not float-rounded beside it
        if (cut_->orientation == CutOrientation::Horizontal) {
            pts->InsertNextPoint(x0, cut_->position_um, 0.0);
            pts->InsertNextPoint(x1, cut_->position_um, 0.0);
        } else {
            pts->InsertNextPoint(cut_->position_um, y0, 0.0);
            pts->InsertNextPoint(cut_->position_um, y1, 0.0);
        }
        vtkNew<vtkCellArray> lines;
        const vtkIdType ids[2] = {0, 1};
        lines->InsertNextCell(2, ids);
        vtkNew<vtkPolyData> pd;
        pd->SetPoints(pts);
        pd->SetLines(lines);
        cut_mapper_->SetInputData(pd);
        // Above the mesh lines and contours (the camera looks along +z from -z).
        const double lift = -2e-3 * std::max(x1 - x0, y1 - y0);
        cut_halo_actor_->SetPosition(0.0, 0.0, lift);
        cut_actor_->SetPosition(0.0, 0.0, 1.5 * lift);
    }
    cut_halo_actor_->SetVisibility(show);
    cut_actor_->SetVisibility(show);
    renderNow();
}

void FieldView::initializeGL() {
    ++gl_inits_;
    QVTKOpenGLNativeWidget::initializeGL();
}

void FieldView::resizeEvent(QResizeEvent* event) {
    QVTKOpenGLNativeWidget::resizeEvent(event);
    updateViewports();
}

void FieldView::refresh() {
    auto t0 = std::chrono::steady_clock::now();
    mapper_->Update();  // what Render() would run lazily; explicit so it is timed apart
    switch_t_.update_ms = lap_ms(t0);
    renderNow();
    switch_t_.render_ms = lap_ms(t0);
}

void FieldView::resetCamera() {
    vtkCamera* cam = renderer_->GetActiveCamera();
    // y increases into the substrate: look along +z with y pointing
    // DOWN, which keeps x pointing right (the Python viewport's
    // invert_yaxis(), without mirroring x).
    cam->SetFocalPoint(0.0, 0.0, 0.0);
    if (is3D()) {
        cam->ParallelProjectionOff();
        cam->SetPosition(0.8, -0.6, -1.0);
    } else {
        cam->ParallelProjectionOn();
        cam->SetPosition(0.0, 0.0, -1.0);
    }
    cam->SetViewUp(0.0, -1.0, 0.0);
    renderer_->ResetCamera();
    if (!is3D()) {
        // Fit the device's rectangle (its patches) to the MAP viewport, as
        // the Python viewport's fit() does -- the bar has its own.
        const auto& x = edges_um_[0];
        const auto& y = edges_um_[1];
        const double w = x.back() - x.front(), h = y.back() - y.front();
        const double aspect = renderer_->GetTiledAspectRatio();  // width / height of the map viewport
        const double half = 0.5 * std::max(h, w / (aspect > 0.0 ? aspect : 1.0));
        cam->SetFocalPoint(0.5 * (x.front() + x.back()), 0.5 * (y.front() + y.back()), 0.0);
        cam->SetPosition(0.5 * (x.front() + x.back()), 0.5 * (y.front() + y.back()), -1.0 * std::max(w, h));
        cam->SetParallelScale(1.04 * (half > 0.0 ? half : 1.0));
        renderer_->ResetCameraClippingRange();
    }
}

std::size_t FieldView::nearestNode(int axis, double coord_um) const {
    const auto& ax = axes_um_[static_cast<std::size_t>(axis)];
    const auto it = std::lower_bound(ax.begin(), ax.end(), coord_um);
    if (it == ax.begin()) return 0;
    if (it == ax.end()) return ax.size() - 1;
    const auto hi = static_cast<std::size_t>(it - ax.begin());
    return (coord_um - ax[hi - 1] <= ax[hi] - coord_um) ? hi - 1 : hi;
}

bool FieldView::readoutAt(double x_px, double y_px, QString* text) {
    text->clear();
    if (!model_ || field_.empty()) return false;
    const double dpr = devicePixelRatioF();
    const int* size = window_->GetSize();
    const double xd = x_px * dpr, yd = size[1] - 1 - y_px * dpr;  // VTK display origin: bottom-left
    // Over the bar's column the map is clipped: never name a hidden node.
    if (!renderer_->IsInViewport(static_cast<int>(xd), static_cast<int>(yd))) return false;
    auto t0 = std::chrono::steady_clock::now();
    hover_t_ = HoverTimings{};
    double p[3];
    if (is3D()) {
        // Locators of layers rebuilt since the last hover (slices, the
        // isosurface) are built on first use, not on every drag frame.
        for (auto& sl : slices_)
            if (sl.state.on && sl.locator_stale && sl.poly->GetNumberOfCells() > 0) {
                sl.locator->SetDataSet(sl.poly);
                sl.locator->BuildLocator();
                sl.locator_stale = false;
            }
        if (iso_on_ && iso_locator_stale_ && iso_poly_->GetNumberOfCells() > 0) {
            iso_locator_->SetDataSet(iso_poly_);
            iso_locator_->BuildLocator();
            iso_locator_stale_ = false;
        }
        const bool hit = picker_->Pick(xd, yd, 0.0, renderer_) && picker_->GetCellId() >= 0;
        hover_t_.pick_ms = lap_ms(t0);  // misses cost a full walk too: time them
        if (!hit) return false;
        // A patch face or a slice: the picker says WHAT is hit first; where
        // is then exact, since both are known planes -- the crop box's
        // faces, a node plane. (The pick position is not: within the
        // picker's sub-pixel tolerance of a shared patch edge it lands in
        // either patch -- S6.) The node is the voxel holding that point.
        vtkActor* hit_actor = picker_->GetActor();
        picker_->GetPickPosition(p);
        int fixed = hit_actor == actor_.GetPointer() ? -1 : -2;
        for (int a = 0; a < 3; ++a)
            if (hit_actor == slices_[static_cast<std::size_t>(a)].actor.GetPointer()) fixed = a;
        if (fixed >= -1) {
            const std::size_t k = fixed >= 0 ? slices_[static_cast<std::size_t>(fixed)].state.index : 0;
            double o[3], d[3];
            if (displayRay(xd, yd, o, d)) {
                if (fixed == -1) {
                    double q[3];
                    if (rayCropBox(o, d, q)) std::copy(q, q + 3, p);
                } else if (d[fixed] != 0.0) {
                    const double t = (axes_um_[static_cast<std::size_t>(fixed)][k] - o[fixed]) / d[fixed];
                    for (int a = 0; a < 3; ++a) p[a] = o[a] + t * d[a];
                }
            }
            *text = readoutForNode(voxelNode(p, fixed, k));
            hover_t_.snap_ms = lap_ms(t0);
            return true;
        }
        for (const auto& r : regions_)  // an exploded region: undo its offset
            if (hit_actor == r.actor) p[2] -= r.offset_um;
    } else {
        renderer_->SetDisplayPoint(xd, yd, 0.0);
        renderer_->DisplayToWorld();
        double w[4];
        renderer_->GetWorldPoint(w);
        if (w[3] == 0.0) return false;
        p[0] = w[0] / w[3];
        p[1] = w[1] / w[3];
        p[2] = 0.0;
        // on the device: within the patches (nearest shading draws them)
        for (int a = 0; a < 2; ++a) {
            const auto& e = edges_um_[static_cast<std::size_t>(a)];
            if (p[a] < e.front() || p[a] > e.back()) return false;
        }
    }
    hover_t_.pick_ms += lap_ms(t0);  // 2D: the whole display->world step; 3D: the GetPickPosition tail
    *text = readoutForPoint(p);
    hover_t_.snap_ms = lap_ms(t0);
    return true;
}

QString FieldView::readoutForNode(std::size_t node) const {
    const auto n = model_->node_counts();
    const std::size_t ix = node % n[0], iy = (node / n[0]) % n[1], iz = node / (n[0] * n[1]);
    const double v = raw_.values[node];
    if (is3D())
        return QString::asprintf("%s: %.3e %s @ x=%.2f, y=%.2f, z=%.2f um", field_.c_str(), v, raw_.unit.c_str(),
                                 axes_um_[0][ix], axes_um_[1][iy], axes_um_[2][iz]);
    return QString::asprintf("%s: %.3e %s @ x=%.2f, y=%.2f um", field_.c_str(), v, raw_.unit.c_str(),
                             axes_um_[0][ix], axes_um_[1][iy]);
}

bool FieldView::displayRay(double xd, double yd, double o[3], double d[3]) const {
    double a[4], b[4];
    renderer_->SetDisplayPoint(xd, yd, 0.0);
    renderer_->DisplayToWorld();
    renderer_->GetWorldPoint(a);
    renderer_->SetDisplayPoint(xd, yd, 1.0);
    renderer_->DisplayToWorld();
    renderer_->GetWorldPoint(b);
    if (a[3] == 0.0 || b[3] == 0.0) return false;
    for (int i = 0; i < 3; ++i) {
        o[i] = a[i] / a[3];
        d[i] = b[i] / b[3] - o[i];
    }
    return true;
}

bool FieldView::rayCropBox(const double o[3], const double d[3], double hit[3]) const {
    double t0 = 0.0, t1 = 1.0;
    for (std::size_t i = 0; i < 3; ++i) {
        const double lo = edges_um_[i][crop_.lo[i]], hi = edges_um_[i][crop_.hi[i] + 1];
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

std::size_t FieldView::voxelNode(const double p[3], int fixed_axis, std::size_t fixed_index) const {
    std::size_t node[3] = {0, 0, 0};
    for (int a = 0; a < 3; ++a) {
        const auto ua = static_cast<std::size_t>(a);
        if (a == fixed_axis) {
            node[a] = fixed_index;
            continue;
        }
        const auto& e = edges_um_[ua];
        const auto it = std::upper_bound(e.begin(), e.end(), p[a]);  // voxel i spans [e_i, e_i+1)
        const std::size_t i = it == e.begin() ? 0 : static_cast<std::size_t>(it - e.begin()) - 1;
        node[a] = std::clamp(i, crop_.lo[ua], crop_.hi[ua]);
    }
    return nodeIndex(node[0], node[1], node[2]);
}

QString FieldView::readoutForPoint(const double p[3]) const {
    const auto n = model_->node_counts();
    const std::size_t ix = nearestNode(0, p[0]), iy = nearestNode(1, p[1]);
    const std::size_t iz = is3D() ? nearestNode(2, p[2]) : 0;
    const double v = raw_.values[(iz * n[1] + iy) * n[0] + ix];
    if (is3D())
        return QString::asprintf("%s: %.3e %s @ x=%.2f, y=%.2f, z=%.2f um", field_.c_str(), v, raw_.unit.c_str(),
                                 axes_um_[0][ix], axes_um_[1][iy], axes_um_[2][iz]);
    return QString::asprintf("%s: %.3e %s @ x=%.2f, y=%.2f um", field_.c_str(), v, raw_.unit.c_str(),
                             axes_um_[0][ix], axes_um_[1][iy]);
}

void FieldView::resetView() {
    if (!model_ || field_.empty()) return;
    updateViewports();
    resetCamera();
    renderNow();
}

void FieldView::renderNow() {
    if (!isValid()) {  // no GL context yet: paint when the widget is first shown
        update();
        return;
    }
    updateViewports();
    window_->Render();
    window_->WaitForCompletion();
}

void FieldView::mouseMoveEvent(QMouseEvent* event) {
    QVTKOpenGLNativeWidget::mouseMoveEvent(event);
    if (event->buttons() != Qt::NoButton) return;  // dragging: the view is moving
    QString text;
    readoutAt(event->position().x(), event->position().y(), &text);
    if (text != readout_) {
        readout_ = text;
        emit readoutChanged(readout_);
    }
}

void FieldView::leaveEvent(QEvent* event) {
    QVTKOpenGLNativeWidget::leaveEvent(event);
    if (!readout_.isEmpty()) {
        readout_.clear();
        emit readoutChanged(readout_);
    }
}

}  // namespace tcad::desktop
