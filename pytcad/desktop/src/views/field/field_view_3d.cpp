// FieldView's 3D layers (NATIVE-DESKTOP-PLAN.md section 15.19, P1 S6):
// the nearest-shaded surface and its crop, slices, isosurface, volume,
// current-density glyphs and streamlines, the exploded view, sweep
// playback and the view presets. The 2D map and everything shared (the
// gather, the colour tables, the bar) are in field_view.cpp.
#include "field_view.hpp"

#include "theme/tokens.hpp"

#include <vtkArrowSource.h>
#include <vtkCamera.h>
#include <vtkCellArray.h>
#include <vtkCellData.h>
#include <vtkColorTransferFunction.h>
#include <vtkFloatArray.h>
#include <vtkGlyph3D.h>
#include <vtkMinimalStandardRandomSequence.h>
#include <vtkPiecewiseFunction.h>
#include <vtkPointData.h>
#include <vtkPointSource.h>
#include <vtkPoints.h>
#include <vtkProperty.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkStreamTracer.h>
#include <vtkTextProperty.h>
#include <vtkTubeFilter.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_map>

namespace tcad::desktop {
namespace {

constexpr const char* kNodeIdArray = "tcad_node_id";  // as field_view.cpp
constexpr const char* kVectorArray = "J";
constexpr double kMinPositive = 1e-30;

double lap_ms(std::chrono::steady_clock::time_point& t0) {
    const auto t1 = std::chrono::steady_clock::now();
    const double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    t0 = t1;
    return ms;
}

vtkSmartPointer<vtkDoubleArray> coords(const std::vector<double>& um, std::size_t lo, std::size_t hi) {
    auto a = vtkSmartPointer<vtkDoubleArray>::New();
    a->SetNumberOfValues(static_cast<vtkIdType>(hi - lo + 1));
    for (std::size_t i = lo; i <= hi; ++i) a->SetValue(static_cast<vtkIdType>(i - lo), um[i]);
    return a;
}

// Linear position along a (possibly graded) axis at fractional index fi:
// what contouring the rectilinear grid gives (field_view.cpp's rule, 2D).
double along(const std::vector<double>& a, std::size_t lo, double fi) {
    const std::size_t last = a.size() - 1;
    double g = static_cast<double>(lo) + fi;
    if (last == 0) return a[0];
    std::size_t i = static_cast<std::size_t>(std::max(0.0, std::floor(g)));
    if (i >= last) i = last - 1;
    const double f = g - static_cast<double>(i);
    return a[i] + f * (a[i + 1] - a[i]);
}

}  // namespace

VolumePresetSpec volumePresetSpec(VolumePreset p) {
    switch (p) {  // viewer3d.py's TRANSFER_FUNCTION_PRESETS, as written
        case VolumePreset::Linear: return {ColorMap::Viridis, 0.3};
        case VolumePreset::LogHigh: return {ColorMap::Plasma, 0.25};
        case VolumePreset::LogLow: return {ColorMap::Viridis, 0.35};
        case VolumePreset::Threshold: return {ColorMap::RdBuR, 0.5};
    }
    return {ColorMap::Viridis, 0.3};
}

const char* volumePresetName(VolumePreset p) {
    switch (p) {
        case VolumePreset::Linear: return "linear";
        case VolumePreset::LogHigh: return "log-high";
        case VolumePreset::LogLow: return "log-low";
        case VolumePreset::Threshold: return "threshold";
    }
    return "linear";
}

std::optional<VolumePreset> volumePresetFromName(const std::string& name) {
    for (VolumePreset p : {VolumePreset::Linear, VolumePreset::LogHigh, VolumePreset::LogLow, VolumePreset::Threshold})
        if (name == volumePresetName(p)) return p;
    return std::nullopt;
}

// ---------------------------------------------------------------- setup ----

void FieldView::setup3D() {
    outline_actor_->SetMapper(outline_mapper_);
    outline_actor_->GetProperty()->LightingOff();
    outline_actor_->PickableOff();
    outline_actor_->VisibilityOff();
    renderer_->AddViewProp(outline_actor_);

    for (auto& sl : slices_) {
        sl.ids->SetName(kNodeIdArray);
        sl.scalars->SetName("values");
        sl.poly->GetCellData()->AddArray(sl.ids);
        sl.poly->GetCellData()->SetScalars(sl.scalars);
        sl.mapper->SetInputData(sl.poly);
        sl.mapper->SetLookupTable(lut_);
        sl.mapper->SetScalarRange(0.0, 1.0);
        sl.mapper->SetScalarModeToUseCellData();
        sl.mapper->ScalarVisibilityOn();
        sl.actor->SetMapper(sl.mapper);
        sl.actor->GetProperty()->LightingOff();  // colours are data
        sl.actor->VisibilityOff();
        renderer_->AddViewProp(sl.actor);
    }

    iso_filter_->ComputeNormalsOff();  // index-space normals would be wrong on a graded mesh;
    iso_filter_->ComputeGradientsOff();  // without normals VTK shades each facet flat
    iso_filter_->ComputeScalarsOff();
    iso_filter_->SetInputData(iso_image_);
    iso_mapper_->SetInputData(iso_poly_);
    iso_mapper_->ScalarVisibilityOff();
    iso_actor_->SetMapper(iso_mapper_);
    iso_actor_->VisibilityOff();
    renderer_->AddViewProp(iso_actor_);

    volume_mapper_->SetInputData(volume_grid_);
    volume_property_->ShadeOff();  // PyVista's add_volume default
    volume_property_->SetInterpolationTypeToLinear();
    // Level of detail while dragging: the interactor asks
    // for kDragFps during a drag, and the GPU mapper coarsens its ray
    // sampling to fit that frame time; at rest (the still rate) it renders
    // at full quality. Section 15.4's orbit budget is 33 ms = 30 fps.
    volume_mapper_->SetInteractiveAdjustSampleDistances(1);
    if (vtkRenderWindowInteractor* it = window_->GetInteractor()) it->SetDesiredUpdateRate(kDragFps);
    volume_->SetMapper(volume_mapper_);
    volume_->SetProperty(volume_property_);
    volume_->PickableOff();
    volume_->VisibilityOff();
    renderer_->AddViewProp(volume_);

    fill_lut(vector_lut_, ColorMap::Plasma);  // viewer3d.py colours glyphs/streamlines by |J| in plasma
    vector_lut_->SetVectorModeToMagnitude();
    glyph_mapper_->SetInputData(glyph_poly_);
    glyph_mapper_->SetLookupTable(vector_lut_);
    glyph_mapper_->UseLookupTableScalarRangeOn();
    glyph_actor_->SetMapper(glyph_mapper_);
    glyph_actor_->PickableOff();
    glyph_actor_->VisibilityOff();
    renderer_->AddViewProp(glyph_actor_);
    stream_mapper_->SetLookupTable(vector_lut_);
    stream_mapper_->UseLookupTableScalarRangeOn();
    stream_actor_->SetMapper(stream_mapper_);
    stream_actor_->PickableOff();
    stream_actor_->VisibilityOff();
    renderer_->AddViewProp(stream_actor_);

    vbar_->SetLookupTable(vector_lut_);
    vbar_->SetNumberOfLabels(4);
    vbar_->SetTitle("");
    vbar_->GetPositionCoordinate()->SetCoordinateSystemToNormalizedViewport();
    vbar_->SetPosition(0.05, 0.05);
    vbar_->SetPosition2(0.72, 0.4);
    vbar_->GetLabelTextProperty()->SetFontSize(11);
    vbar_->VisibilityOff();
    vtitle_->GetTextProperty()->SetFontSize(12);
    vtitle_->GetTextProperty()->SetJustificationToCentered();
    vtitle_->GetTextProperty()->SetVerticalJustificationToCentered();
    vtitle_->GetTextProperty()->SetOrientation(90.0);
    vtitle_->GetPositionCoordinate()->SetCoordinateSystemToNormalizedViewport();
    vtitle_->SetPosition(0.88, 0.25);
    vtitle_->VisibilityOff();
    bar_renderer_->AddViewProp(vbar_);
    bar_renderer_->AddViewProp(vtitle_);

    crop_filter_->SetInputData(dual_grid_);
    surface_filter_->SetInputConnection(crop_filter_->GetOutputPort());
}

std::size_t FieldView::nodeIndex(std::size_t i, std::size_t j, std::size_t k) const {
    const auto n = model_->node_counts();
    return (k * n[1] + j) * n[0] + i;
}

NodeBox FieldView::fullBox() const {
    NodeBox b;
    if (!model_) return b;
    const auto n = model_->node_counts();
    for (int a = 0; a < 3; ++a) b.hi[static_cast<std::size_t>(a)] = n[static_cast<std::size_t>(a)] - 1;
    return b;
}

std::array<std::size_t, 3> FieldView::cropSize() const {
    return {crop_.hi[0] - crop_.lo[0] + 1, crop_.hi[1] - crop_.lo[1] + 1, crop_.hi[2] - crop_.lo[2] + 1};
}

double FieldView::diagonalUm() const {
    double d2 = 0.0;
    for (const auto& a : axes_um_)
        if (!a.empty()) d2 += (a.back() - a.front()) * (a.back() - a.front());
    return std::sqrt(d2);
}

void FieldView::reset3D() {
    for (auto& sl : slices_) {
        sl.state = SliceState{};
        sl.actor->VisibilityOff();
        sl.poly->Initialize();
        sl.poly->GetCellData()->AddArray(sl.ids);
        sl.poly->GetCellData()->SetScalars(sl.scalars);
        sl.ids->SetNumberOfValues(0);
        sl.locator_stale = true;
    }
    iso_on_ = volume_on_ = glyphs_on_ = streamlines_on_ = exploded_on_ = false;
    iso_actor_->VisibilityOff();
    iso_poly_->Initialize();
    iso_version_ = -1;
    volume_->VisibilityOff();
    glyph_actor_->VisibilityOff();
    stream_actor_->VisibilityOff();
    vbar_->VisibilityOff();
    vtitle_->VisibilityOff();
    for (auto& a : region_actors_) renderer_->RemoveViewProp(a);
    region_actors_.clear();
    regions_.clear();
    surface_mode_ = SurfaceMode::Field;
    interior_seen_ = false;
    actor_->GetProperty()->SetOpacity(1.0);
    mapper_->ScalarVisibilityOn();
    crop_values_version_ = -1;
    layer_t_ = {};
    const bool three = is3D();
    outline_actor_->SetVisibility(three);
    vector_name_.clear();
    if (!three) return;
    crop_ = fullBox();
    const auto n = model_->node_counts();
    for (int a = 0; a < 3; ++a) slices_[static_cast<std::size_t>(a)].state.index = n[static_cast<std::size_t>(a)] / 2;
    if (!model_->vector_names().empty()) vector_name_ = model_->vector_names().front();
    exploded_sep_um_ = 0.15 * diagonalUm();  // viewer3d.py: 0.15 x the device diagonal
}

// ---------------------------------------------------- surface and crop ----

void FieldView::rebuildSurface3D() {
    auto t0 = std::chrono::steady_clock::now();
    crop_filter_->SetVOI(static_cast<int>(crop_.lo[0]), static_cast<int>(crop_.hi[0] + 1),
                         static_cast<int>(crop_.lo[1]), static_cast<int>(crop_.hi[1] + 1),
                         static_cast<int>(crop_.lo[2]), static_cast<int>(crop_.hi[2] + 1));
    crop_filter_->Modified();
    surface_filter_->Update();
    surface_ = vtkSmartPointer<vtkPolyData>::New();
    surface_->ShallowCopy(surface_filter_->GetOutput());
    surface_ids_ = vtkIdTypeArray::SafeDownCast(surface_->GetCellData()->GetArray(kNodeIdArray));
    if (!surface_ids_) throw std::runtime_error("3D surface extraction dropped the node-index array");
    surface_->GetCellData()->SetScalars(scalars_);
    mapper_->SetInputData(surface_);
    locator_->SetDataSet(surface_);
    locator_->BuildLocator();
    rebuildOutline();
    updatePickList();
    layer_t_.crop_ms = lap_ms(t0);
}

void FieldView::rebuildOutline() {
    // The crop box's patch edges: 12 lines in the overlay colour.
    const double x0 = edges_um_[0][crop_.lo[0]], x1 = edges_um_[0][crop_.hi[0] + 1];
    const double y0 = edges_um_[1][crop_.lo[1]], y1 = edges_um_[1][crop_.hi[1] + 1];
    const double z0 = edges_um_[2][crop_.lo[2]], z1 = edges_um_[2][crop_.hi[2] + 1];
    vtkNew<vtkPoints> pts;
    for (int c = 0; c < 8; ++c) pts->InsertNextPoint(c & 1 ? x1 : x0, c & 2 ? y1 : y0, c & 4 ? z1 : z0);
    vtkNew<vtkCellArray> lines;
    const int edges[12][2] = {{0, 1}, {2, 3}, {4, 5}, {6, 7}, {0, 2}, {1, 3}, {4, 6}, {5, 7}, {0, 4}, {1, 5}, {2, 6}, {3, 7}};
    for (const auto& e : edges) {
        const vtkIdType ids[2] = {e[0], e[1]};
        lines->InsertNextCell(2, ids);
    }
    vtkNew<vtkPolyData> pd;
    pd->SetPoints(pts);
    pd->SetLines(lines);
    outline_mapper_->SetInputData(pd);
}

void FieldView::setCrop(const NodeBox& box) {
    if (!is3D()) return;
    const NodeBox full = fullBox();
    NodeBox b;
    for (std::size_t a = 0; a < 3; ++a) {
        b.lo[a] = std::min(box.lo[a], full.hi[a]);
        b.hi[a] = std::clamp(box.hi[a], b.lo[a], full.hi[a]);
    }
    if (b == crop_) return;
    crop_ = b;
    rebuildSurface3D();
    gather(surface_ids_, scalars_);
    for (int a = 0; a < 3; ++a) rebuildSlice(a);
    rebuild3DValues();
    rebuildGlyphs();
    rebuildStreamlines();
    renderNow();
    emit displayChanged();
}

void FieldView::setSurfaceMode(SurfaceMode m) {
    if (!is3D()) return;
    surface_mode_ = m;
    vtkProperty* p = actor_->GetProperty();
    switch (m) {
        case SurfaceMode::Field:
            p->SetOpacity(1.0);
            mapper_->ScalarVisibilityOn();
            break;
        case SurfaceMode::Context: {  // viewer3d.py's context surface: flat, 0.15 opaque
            const theme::Rgb c = theme::rgb(theme::T::Context, scheme_);
            p->SetColor(c.r, c.g, c.b);
            p->SetOpacity(0.15);
            mapper_->ScalarVisibilityOff();
            break;
        }
        case SurfaceMode::Hidden: break;
    }
    actor_->SetVisibility(m != SurfaceMode::Hidden && !exploded_on_);
    updatePickList();
    renderNow();
    emit displayChanged();
}

void FieldView::enteringInteriorLayer() {
    // An opaque surface hides everything inside it: the first interior
    // layer switches it to the translucent context surface, as
    // viewer3d.py always draws it (section 15.19, S6a). Once per result.
    if (interior_seen_) return;
    interior_seen_ = true;
    if (surface_mode_ == SurfaceMode::Field) setSurfaceMode(SurfaceMode::Context);
}

void FieldView::updatePickList() {
    picker_->InitializePickList();
    picker_->RemoveAllLocators();
    if (!is3D()) {
        picker_->AddPickList(actor_);
        return;
    }
    if (surface_mode_ == SurfaceMode::Field && !exploded_on_) {
        picker_->AddPickList(actor_);
        picker_->AddLocator(locator_);
    }
    for (auto& sl : slices_)
        if (sl.state.on && sl.actor->GetVisibility()) {
            picker_->AddPickList(sl.actor);
            picker_->AddLocator(sl.locator);
        }
    if (iso_on_ && iso_actor_->GetVisibility()) {
        picker_->AddPickList(iso_actor_);
        picker_->AddLocator(iso_locator_);
    }
    for (const auto& r : regions_) picker_->AddPickList(r.actor);
}

// ------------------------------------------------------------- slices ----

void FieldView::setSlice(int axis, bool on, std::size_t index) {
    if (!is3D() || axis < 0 || axis > 2) return;
    auto& sl = slices_[static_cast<std::size_t>(axis)];
    const std::size_t n = model_->node_counts()[static_cast<std::size_t>(axis)];
    sl.state.on = on;
    sl.state.index = std::min(index, n - 1);
    if (on) enteringInteriorLayer();
    rebuildSlice(axis);
    updatePickList();
    renderNow();
    emit displayChanged();
}

void FieldView::rebuildSlice(int axis) {
    auto& sl = slices_[static_cast<std::size_t>(axis)];
    const auto a = static_cast<std::size_t>(axis);
    const std::size_t k = sl.state.index;
    const bool shown = sl.state.on && k >= crop_.lo[a] && k <= crop_.hi[a];  // a crop cuts slices too
    sl.actor->SetVisibility(shown);
    sl.locator_stale = true;
    if (!shown) return;
    auto t0 = std::chrono::steady_clock::now();
    // The slice is a nearest-shaded map at the node plane: in-plane patch
    // edges, one quad per node of the plane, spanning the crop box.
    const std::size_t b = a == 0 ? 1 : 0, c = a == 2 ? 1 : 2;  // in-plane axes, ascending
    const std::size_t nb = crop_.hi[b] - crop_.lo[b] + 1, nc = crop_.hi[c] - crop_.lo[c] + 1;
    const double plane = axes_um_[a][k];
    vtkNew<vtkPoints> pts;
    pts->SetDataTypeToDouble();
    pts->SetNumberOfPoints(static_cast<vtkIdType>((nb + 1) * (nc + 1)));
    vtkIdType p = 0;
    for (std::size_t jc = 0; jc <= nc; ++jc)
        for (std::size_t jb = 0; jb <= nb; ++jb) {
            double xyz[3];
            xyz[a] = plane;
            xyz[b] = edges_um_[b][crop_.lo[b] + jb];
            xyz[c] = edges_um_[c][crop_.lo[c] + jc];
            pts->SetPoint(p++, xyz);
        }
    vtkNew<vtkCellArray> quads;
    quads->AllocateExact(static_cast<vtkIdType>(nb * nc), static_cast<vtkIdType>(4 * nb * nc));
    sl.ids->SetNumberOfValues(static_cast<vtkIdType>(nb * nc));
    vtkIdType cell = 0;
    for (std::size_t jc = 0; jc < nc; ++jc)
        for (std::size_t jb = 0; jb < nb; ++jb) {
            const vtkIdType p0 = static_cast<vtkIdType>(jc * (nb + 1) + jb);
            const vtkIdType q[4] = {p0, p0 + 1, p0 + 1 + static_cast<vtkIdType>(nb + 1), p0 + static_cast<vtkIdType>(nb + 1)};
            quads->InsertNextCell(4, q);
            std::array<std::size_t, 3> ijk{};
            ijk[a] = k;
            ijk[b] = crop_.lo[b] + jb;
            ijk[c] = crop_.lo[c] + jc;
            sl.ids->SetValue(cell++, static_cast<vtkIdType>(nodeIndex(ijk[0], ijk[1], ijk[2])));
        }
    sl.ids->Modified();
    sl.poly->SetPoints(pts);
    sl.poly->SetPolys(quads);
    gather(sl.ids, sl.scalars);
    sl.poly->Modified();
    layer_t_.slice_ms = lap_ms(t0);
}

void FieldView::showCentralZPlane() {
    if (!is3D()) return;
    interior_seen_ = true;  // the surface mode is set explicitly just below
    setSlice(2, true, model_->node_counts()[2] / 2);  // mpl_canvas_item: values[shape[0] // 2]
    setSurfaceMode(SurfaceMode::Hidden);
    setViewPreset(ViewPreset::PlusZ);
}

// ------------------------------------------------ values for the interior ----

std::array<double, 2> FieldView::displayedMinMax(const std::vector<double>& raw) const {
    const FieldKind kind = fieldKind();
    const bool abs_log = kind == FieldKind::Recombination || (kind == FieldKind::Generic && log_);
    double lo = std::numeric_limits<double>::infinity(), hi = -lo;
    for (const double v : raw) {
        const double t = abs_log ? std::max(std::abs(v), kMinPositive) : v;
        if (t < lo) lo = t;
        if (t > hi) hi = t;
    }
    if (!(lo <= hi)) return {std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()};  // all NaN
    return abs_log ? std::array<double, 2>{std::log10(lo), std::log10(hi)}
                   : std::array<double, 2>{displayTransform(lo), displayTransform(hi)};
}

const std::vector<double>& FieldView::croppedDisplayed() {
    if (crop_values_version_ == values_version_ && crop_values_box_ == crop_) return crop_values_;
    const auto s = cropSize();
    crop_values_.resize(s[0] * s[1] * s[2]);
    std::size_t o = 0;
    for (std::size_t k = crop_.lo[2]; k <= crop_.hi[2]; ++k)
        for (std::size_t j = crop_.lo[1]; j <= crop_.hi[1]; ++j) {
            const std::size_t row = nodeIndex(crop_.lo[0], j, k);
            for (std::size_t i = 0; i < s[0]; ++i) crop_values_[o++] = displayTransform(raw_.values[row + i]);
        }
    crop_values_version_ = values_version_;
    crop_values_box_ = crop_;
    return crop_values_;
}

void FieldView::rebuild3DValues() {
    if (iso_on_) rebuildIso();
    if (volume_on_) rebuildVolume();
}

// ---------------------------------------------------------- isosurface ----

void FieldView::setIsosurface(bool on) {
    if (!is3D()) return;
    iso_on_ = on;
    if (on) enteringInteriorLayer();
    rebuildIso();
    updatePickList();
    renderNow();
    emit displayChanged();
}

void FieldView::setIsoLevel(double level) {
    if (!is3D()) return;
    iso_level_ = level;
    if (iso_on_) {
        rebuildIso();
        renderNow();
    }
    emit displayChanged();
}

void FieldView::rebuildIso() {
    iso_actor_->SetVisibility(iso_on_);
    if (!iso_on_) return;
    auto t0 = std::chrono::steady_clock::now();
    if (iso_version_ != values_version_ || !(iso_box_ == crop_) || iso_built_level_ != iso_level_) {
        // S5's contour method in 3D: flying edges on the INDEX-space image of
        // the displayed node values, each vertex mapped back along the true
        // (graded) axes. Marching cubes interpolates linearly along grid
        // edges, so a vertex at fractional index i + f sits at
        // x_i + f (x_{i+1} - x_i): exactly the rectilinear grid's isosurface.
        const std::vector<double>& vals = croppedDisplayed();
        const auto s = cropSize();
        iso_image_->SetDimensions(static_cast<int>(s[0]), static_cast<int>(s[1]), static_cast<int>(s[2]));
        iso_image_->SetOrigin(0.0, 0.0, 0.0);
        iso_image_->SetSpacing(1.0, 1.0, 1.0);
        vtkNew<vtkDoubleArray> arr;
        arr->SetName("displayed");
        arr->SetArray(const_cast<double*>(vals.data()), static_cast<vtkIdType>(vals.size()), 1);  // borrowed: vals outlives the filter run
        iso_image_->GetPointData()->SetScalars(arr);
        iso_filter_->SetNumberOfContours(1);
        iso_filter_->SetValue(0, iso_level_);
        iso_filter_->Modified();
        iso_filter_->Update();
        vtkPolyData* in_index = iso_filter_->GetOutput();
        const vtkIdType np = in_index->GetNumberOfPoints();
        vtkNew<vtkPoints> pts;
        pts->SetDataTypeToDouble();
        pts->SetNumberOfPoints(np);
        for (vtkIdType q = 0; q < np; ++q) {
            double pi[3];
            in_index->GetPoint(q, pi);
            pts->SetPoint(q, along(axes_um_[0], crop_.lo[0], pi[0]), along(axes_um_[1], crop_.lo[1], pi[1]),
                          along(axes_um_[2], crop_.lo[2], pi[2]));
        }
        iso_poly_->Initialize();
        iso_poly_->SetPoints(pts);
        vtkNew<vtkCellArray> polys;  // the filter reuses its output on the next level
        polys->DeepCopy(in_index->GetPolys());
        iso_poly_->SetPolys(polys);
        iso_poly_->Modified();
        iso_image_->GetPointData()->Initialize();  // drop the borrowed array
        iso_version_ = values_version_;
        iso_box_ = crop_;
        iso_built_level_ = iso_level_;
        iso_locator_stale_ = true;
    }
    // The level's colour under the view's map and range (finding 5).
    double rgb[3];
    lut_->GetColor(lut_input(iso_level_, norm_[0], norm_[1]), rgb);
    iso_actor_->GetProperty()->SetColor(rgb);
    layer_t_.iso_ms = lap_ms(t0);
}

// -------------------------------------------------------------- volume ----

void FieldView::setVolume(bool on) {
    if (!is3D()) return;
    volume_on_ = on;
    if (on) {
        enteringInteriorLayer();
        // The current preset's colour map, as viewer3d.py's add_volume takes
        // it -- setColorMap refills the volume through rebuildScalars().
        if (colorMap() != volumePresetSpec(volume_preset_).map || !cmap_override_) {
            setColorMap(volumePresetSpec(volume_preset_).map);
            return;
        }
    }
    rebuildVolume();
    renderNow();
    emit displayChanged();
}

void FieldView::setVolumePreset(VolumePreset p) {
    if (!is3D()) return;
    volume_preset_ = p;
    // The preset's colour map becomes the view's, so the bar describes the
    // volume too; rebuildScalars() then refills the volume (3D values hook).
    setColorMap(volumePresetSpec(p).map);
}

void FieldView::rebuildVolume() {
    volume_->SetVisibility(volume_on_);
    if (!volume_on_) return;
    auto t0 = std::chrono::steady_clock::now();
    const std::vector<double>& vals = croppedDisplayed();
    const auto s = cropSize();
    volume_grid_->SetDimensions(static_cast<int>(s[0]), static_cast<int>(s[1]), static_cast<int>(s[2]));
    volume_grid_->SetXCoordinates(coords(axes_um_[0], crop_.lo[0], crop_.hi[0]));
    volume_grid_->SetYCoordinates(coords(axes_um_[1], crop_.lo[1], crop_.hi[1]));
    volume_grid_->SetZCoordinates(coords(axes_um_[2], crop_.lo[2], crop_.hi[2]));
    vtkNew<vtkFloatArray> scal;  // the GPU mapper uploads float anyway
    scal->SetName("normalised");
    scal->SetNumberOfValues(static_cast<vtkIdType>(vals.size()));
    for (std::size_t q = 0; q < vals.size(); ++q) {
        const double u = lut_input(vals[q], norm_[0], norm_[1]);
        scal->SetValue(static_cast<vtkIdType>(q), static_cast<float>(std::isfinite(u) ? std::clamp(u, 0.0, 1.0) : 0.0));
    }
    volume_grid_->GetPointData()->SetScalars(scal);
    volume_grid_->Modified();

    // Colour: the view's 256-entry table over [0, 1]; opacity: the preset's
    // constant, per PyVista's opacity_unit_distance = length / (mean dims - 1).
    vtkNew<vtkColorTransferFunction> colour;
    const vtkIdType nt = lut_->GetNumberOfTableValues();
    for (vtkIdType q = 0; q < nt; ++q) {
        double rgba[4];
        lut_->GetTableValue(q, rgba);
        colour->AddRGBPoint(nt > 1 ? static_cast<double>(q) / static_cast<double>(nt - 1) : 0.0, rgba[0], rgba[1], rgba[2]);
    }
    vtkNew<vtkPiecewiseFunction> opacity;
    const double op = volumePresetSpec(volume_preset_).opacity;
    opacity->AddPoint(0.0, op);
    opacity->AddPoint(1.0, op);
    volume_property_->SetColor(colour);
    volume_property_->SetScalarOpacity(opacity);
    double d2 = 0.0;
    for (std::size_t a = 0; a < 3; ++a) {
        const double w = axes_um_[a][crop_.hi[a]] - axes_um_[a][crop_.lo[a]];
        d2 += w * w;
    }
    const double mean_dims = (static_cast<double>(s[0]) + static_cast<double>(s[1]) + static_cast<double>(s[2])) / 3.0;
    volume_property_->SetScalarOpacityUnitDistance(mean_dims > 1.0 ? std::sqrt(d2) / (mean_dims - 1.0) : 1.0);
    layer_t_.volume_ms = lap_ms(t0);
}

// ----------------------------------------------- glyphs and streamlines ----

void FieldView::setVectorField(const std::string& name) {
    if (!is3D()) return;
    const auto& names = model_->vector_names();
    if (std::find(names.begin(), names.end(), name) == names.end()) return;
    vector_name_ = name;
    rebuildGlyphs();
    rebuildStreamlines();
    renderNow();
    emit displayChanged();
}

void FieldView::setGlyphs(bool on) {
    if (!is3D()) return;
    glyphs_on_ = on && !vector_name_.empty();
    if (glyphs_on_) enteringInteriorLayer();
    rebuildGlyphs();
    renderNow();
    emit displayChanged();
}

void FieldView::setGlyphSpacing(double fraction) {
    if (!is3D()) return;
    glyph_spacing_ = std::clamp(fraction, 0.0, 0.5);
    if (glyphs_on_) {
        rebuildGlyphs();
        renderNow();
    }
    emit displayChanged();
}

void FieldView::setStreamlines(bool on) {
    if (!is3D()) return;
    streamlines_on_ = on && !vector_name_.empty();
    if (streamlines_on_) enteringInteriorLayer();
    rebuildStreamlines();
    renderNow();
    emit displayChanged();
}

void FieldView::rebuildGlyphs() {
    glyph_actor_->VisibilityOff();
    glyph_sources_->Initialize();
    glyph_poly_->Initialize();
    glyph_scale_ = 0.0;
    if (!glyphs_on_ || vector_name_.empty()) {
        updateBars();
        return;
    }
    auto t0 = std::chrono::steady_clock::now();
    const VectorField vf = model_->vector(vector_name_);
    // Every node of the crop box, with its J and node index...
    const auto s = cropSize();
    const vtkIdType count = static_cast<vtkIdType>(s[0] * s[1] * s[2]);
    vtkNew<vtkPoints> pts;
    pts->SetDataTypeToDouble();
    pts->SetNumberOfPoints(count);
    vtkNew<vtkDoubleArray> J;
    J->SetName(kVectorArray);
    J->SetNumberOfComponents(3);
    J->SetNumberOfTuples(count);
    vtkNew<vtkIdTypeArray> ids;
    ids->SetName(kNodeIdArray);
    ids->SetNumberOfValues(count);
    double max_mag = 0.0;
    vtkIdType q = 0;
    for (std::size_t k = crop_.lo[2]; k <= crop_.hi[2]; ++k)
        for (std::size_t j = crop_.lo[1]; j <= crop_.hi[1]; ++j)
            for (std::size_t i = crop_.lo[0]; i <= crop_.hi[0]; ++i, ++q) {
                const std::size_t node = nodeIndex(i, j, k);
                pts->SetPoint(q, axes_um_[0][i], axes_um_[1][j], axes_um_[2][k]);
                double v[3] = {vf.components[0][node], vf.components[1][node], vf.components[2][node]};
                if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) v[0] = v[1] = v[2] = 0.0;
                J->SetTuple(q, v);
                ids->SetValue(q, static_cast<vtkIdType>(node));
                max_mag = std::max(max_mag, std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]));
            }
    if (!(max_mag > 0.0)) {  // an all-zero / all-NaN field: nothing to orient along (viewer3d.py refuses too)
        updateBars();
        return;
    }
    // ... thinned as PyVista's glyph(tolerance=) intends: a point closer
    // than tolerance x (the points' bounding-box diagonal) to one already
    // kept is dropped, in node order. Done here rather than with
    // vtkCleanPolyData, which pairs a merged point's coordinates with
    // ANOTHER point's data (measured: node (0,0,0)'s position carrying node
    // (1,1,2)'s J) -- every arrow must sit on the node whose J it shows.
    double d2box = 0.0;
    for (std::size_t a = 0; a < 3; ++a) {
        const double w = axes_um_[a][crop_.hi[a]] - axes_um_[a][crop_.lo[a]];
        d2box += w * w;
    }
    const double tol = glyph_spacing_ * std::sqrt(d2box);
    std::vector<vtkIdType> keep;
    if (tol <= 0.0) {
        keep.resize(static_cast<std::size_t>(count));
        for (vtkIdType q2 = 0; q2 < count; ++q2) keep[static_cast<std::size_t>(q2)] = q2;
    } else {
        std::unordered_map<long long, std::vector<vtkIdType>> bins;  // kept points by tol-sized bin
        auto bin_of = [&](const double x[3], int c) { return static_cast<long long>(std::floor(x[c] / tol)); };
        auto key = [](long long bx, long long by, long long bz) {
            return (bx * 73856093LL) ^ (by * 19349663LL) ^ (bz * 83492791LL);
        };
        for (vtkIdType q2 = 0; q2 < count; ++q2) {
            double x[3];
            pts->GetPoint(q2, x);
            const long long bx = bin_of(x, 0), by = bin_of(x, 1), bz = bin_of(x, 2);
            bool near = false;
            for (long long dx = -1; dx <= 1 && !near; ++dx)
                for (long long dy = -1; dy <= 1 && !near; ++dy)
                    for (long long dz = -1; dz <= 1 && !near; ++dz) {
                        const auto it = bins.find(key(bx + dx, by + dy, bz + dz));
                        if (it == bins.end()) continue;
                        for (vtkIdType kept : it->second) {
                            double y[3];
                            pts->GetPoint(kept, y);
                            const double dd = (x[0] - y[0]) * (x[0] - y[0]) + (x[1] - y[1]) * (x[1] - y[1]) +
                                              (x[2] - y[2]) * (x[2] - y[2]);
                            if (dd < tol * tol) {
                                near = true;
                                break;
                            }
                        }
                    }
            if (near) continue;
            keep.push_back(q2);
            bins[key(bx, by, bz)].push_back(q2);
        }
    }
    vtkNew<vtkPoints> kpts;
    kpts->SetDataTypeToDouble();
    kpts->SetNumberOfPoints(static_cast<vtkIdType>(keep.size()));
    vtkNew<vtkDoubleArray> kJ;
    kJ->SetName(kVectorArray);
    kJ->SetNumberOfComponents(3);
    kJ->SetNumberOfTuples(static_cast<vtkIdType>(keep.size()));
    vtkNew<vtkIdTypeArray> kids;
    kids->SetName(kNodeIdArray);
    kids->SetNumberOfValues(static_cast<vtkIdType>(keep.size()));
    for (std::size_t o = 0; o < keep.size(); ++o) {
        const auto oo = static_cast<vtkIdType>(o);
        kpts->SetPoint(oo, pts->GetPoint(keep[o]));
        kJ->SetTuple(oo, J->GetTuple(keep[o]));
        kids->SetValue(oo, ids->GetValue(keep[o]));
    }
    glyph_sources_->Initialize();
    glyph_sources_->SetPoints(kpts);
    glyph_sources_->GetPointData()->AddArray(kJ);
    glyph_sources_->GetPointData()->AddArray(kids);
    glyph_sources_->GetPointData()->SetActiveVectors(kVectorArray);

    // Arrow length proportional to |J|, the LARGEST as long as the spacing
    // (section 15.19 finding 1: PyVista's factor 1 on A/cm^2 in cm made
    // them millions of device lengths long).
    const double arrow = std::max(glyph_spacing_, 0.02) * diagonalUm();
    glyph_scale_ = arrow / max_mag;
    vtkNew<vtkArrowSource> arrow_src;
    vtkNew<vtkGlyph3D> glyph;
    glyph->SetInputData(glyph_sources_);
    glyph->SetSourceConnection(arrow_src->GetOutputPort());
    glyph->SetInputArrayToProcess(1, 0, 0, vtkDataObject::FIELD_ASSOCIATION_POINTS, kVectorArray);
    glyph->SetVectorModeToUseVector();
    glyph->SetScaleModeToScaleByVector();
    glyph->SetScaleFactor(glyph_scale_);
    glyph->OrientOn();
    glyph->SetColorModeToColorByVector();  // output scalars: |J|
    glyph->Update();
    glyph_poly_->ShallowCopy(glyph->GetOutput());
    vector_lut_->SetTableRange(0.0, max_mag);
    glyph_actor_->VisibilityOn();
    updateBars();
    layer_t_.glyph_ms = lap_ms(t0);
}

void FieldView::rebuildStreamlines() {
    stream_actor_->VisibilityOff();
    stream_lines_->Initialize();
    if (!streamlines_on_ || vector_name_.empty()) {
        updateBars();
        return;
    }
    auto t0 = std::chrono::steady_clock::now();
    const VectorField vf = model_->vector(vector_name_);
    const auto s = cropSize();
    vtkNew<vtkRectilinearGrid> g;
    g->SetDimensions(static_cast<int>(s[0]), static_cast<int>(s[1]), static_cast<int>(s[2]));
    g->SetXCoordinates(coords(axes_um_[0], crop_.lo[0], crop_.hi[0]));
    g->SetYCoordinates(coords(axes_um_[1], crop_.lo[1], crop_.hi[1]));
    g->SetZCoordinates(coords(axes_um_[2], crop_.lo[2], crop_.hi[2]));
    vtkNew<vtkDoubleArray> J;
    J->SetName(kVectorArray);
    J->SetNumberOfComponents(3);
    J->SetNumberOfTuples(static_cast<vtkIdType>(s[0] * s[1] * s[2]));
    double max_mag = 0.0;
    vtkIdType q = 0;
    for (std::size_t k = crop_.lo[2]; k <= crop_.hi[2]; ++k)
        for (std::size_t j = crop_.lo[1]; j <= crop_.hi[1]; ++j)
            for (std::size_t i = crop_.lo[0]; i <= crop_.hi[0]; ++i, ++q) {
                const std::size_t node = nodeIndex(i, j, k);
                double v[3] = {vf.components[0][node], vf.components[1][node], vf.components[2][node]};
                if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) v[0] = v[1] = v[2] = 0.0;
                J->SetTuple(q, v);
                max_mag = std::max(max_mag, std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]));
            }
    if (!(max_mag > 0.0)) {
        updateBars();
        return;
    }
    g->GetPointData()->SetVectors(J);
    const double diag = [&] {
        double d2 = 0.0;
        for (std::size_t a = 0; a < 3; ++a) {
            const double w = axes_um_[a][crop_.hi[a]] - axes_um_[a][crop_.lo[a]];
            d2 += w * w;
        }
        return std::sqrt(d2);
    }();
    // PyVista's streamlines() defaults (section 15.19 finding 2), with a
    // FIXED random sequence so the seeds repeat.
    vtkNew<vtkMinimalStandardRandomSequence> rng;
    rng->SetSeed(1);
    vtkNew<vtkPointSource> seeds;
    seeds->SetRandomSequence(rng);
    seeds->SetCenter(0.5 * (axes_um_[0][crop_.lo[0]] + axes_um_[0][crop_.hi[0]]),
                     0.5 * (axes_um_[1][crop_.lo[1]] + axes_um_[1][crop_.hi[1]]),
                     0.5 * (axes_um_[2][crop_.lo[2]] + axes_um_[2][crop_.hi[2]]));
    seeds->SetRadius(0.5 * diag);
    seeds->SetNumberOfPoints(100);
    vtkNew<vtkStreamTracer> tracer;
    tracer->SetInputData(g);
    tracer->SetSourceConnection(seeds->GetOutputPort());
    tracer->SetInputArrayToProcess(0, 0, 0, vtkDataObject::FIELD_ASSOCIATION_POINTS, kVectorArray);
    tracer->SetIntegratorTypeToRungeKutta45();
    tracer->SetIntegrationDirectionToBoth();
    tracer->SetIntegrationStepUnit(vtkStreamTracer::CELL_LENGTH_UNIT);
    tracer->SetInitialIntegrationStep(0.5);
    tracer->SetMinimumIntegrationStep(0.01);
    tracer->SetMaximumIntegrationStep(1.0);
    tracer->SetMaximumNumberOfSteps(2000);
    tracer->SetTerminalSpeed(1e-12);
    tracer->SetMaximumError(1e-6);
    tracer->SetMaximumPropagation(100.0 * diag);
    tracer->SetComputeVorticity(false);
    tracer->Update();
    stream_lines_->ShallowCopy(tracer->GetOutput());
    if (stream_lines_->GetNumberOfPoints() == 0) {  // no seed found a line (viewer3d.py: no actor)
        updateBars();
        return;
    }
    vtkNew<vtkTubeFilter> tube;
    tube->SetInputData(stream_lines_);
    tube->SetRadius(0.002 * diag);
    tube->SetNumberOfSides(20);  // PyVista's tube() default
    tube->Update();
    vtkNew<vtkPolyData> tubed;
    tubed->ShallowCopy(tube->GetOutput());
    stream_mapper_->SetInputData(tubed);
    // vtkTubeFilter can drop the vector array on very short lines
    // (viewer3d.py's note): colour by |J| when it survived, else plain.
    if (tubed->GetPointData()->GetArray(kVectorArray)) {
        stream_mapper_->SetScalarModeToUsePointFieldData();
        stream_mapper_->SelectColorArray(kVectorArray);
        stream_mapper_->ScalarVisibilityOn();
    } else {
        stream_mapper_->ScalarVisibilityOff();
    }
    vector_lut_->SetTableRange(0.0, max_mag);
    stream_actor_->VisibilityOn();
    updateBars();
    layer_t_.streamline_ms = lap_ms(t0);
}

void FieldView::updateBars() {
    // The bar column: the field's bar, and -- while a vector overlay is
    // shown -- |J|'s below it (section 15.19 finding 9).
    const bool vec = is3D() && (glyph_actor_->GetVisibility() || stream_actor_->GetVisibility());
    if (vec) {
        bar_->SetPosition(0.05, 0.52);
        bar_->SetPosition2(0.72, 0.43);
        title_->SetPosition(0.88, 0.735);
        std::string unit;
        if (!vector_name_.empty()) unit = model_->vector(vector_name_).unit;
        vtitle_->SetInput(("|" + vector_name_ + "| [" + unit + "]").c_str());
    } else {
        bar_->SetPosition(0.05, 0.05);
        bar_->SetPosition2(0.72, 0.9);
        title_->SetPosition(0.88, 0.5);
    }
    vbar_->SetVisibility(vec);
    vtitle_->SetVisibility(vec);
}

// ------------------------------------------------------- exploded view ----

bool FieldView::explodedAvailable(QString* why) const {
    auto say = [&](const char* s) {
        if (why) *why = QString::fromUtf8(s);
        return false;
    };
    if (!is3D()) return say("the exploded view is 3D only");
    std::optional<nlohmann::ordered_json> list;
    try {
        list = model_->region_materials();
        if (!list || !list->is_array() || list->empty()) list = model_->structure_regions();
    } catch (const std::exception&) {
        return say("the result's region metadata is not valid JSON");
    }
    if (!list || !list->is_array() || list->empty())
        return say("the result has no regions (no region_materials or structure_regions)");
    for (const auto& r : *list)
        if (r.is_object() && r.contains("box") && r["box"].is_array() && r["box"].size() >= 6) return true;
    return say("none of the result's regions has a 3D box");
}

void FieldView::setExploded(bool on) {
    if (!is3D()) return;
    exploded_on_ = on && explodedAvailable();
    rebuildExploded();
    renderNow();
    emit displayChanged();
}

void FieldView::setExplodedSeparation(double um) {
    if (!is3D()) return;
    exploded_sep_um_ = std::max(0.0, um);
    if (exploded_on_) {
        rebuildExploded();
        renderNow();
    }
    emit displayChanged();
}

void FieldView::rebuildExploded() {
    for (auto& a : region_actors_) renderer_->RemoveViewProp(a);
    region_actors_.clear();
    regions_.clear();
    actor_->SetVisibility(surface_mode_ != SurfaceMode::Hidden && !exploded_on_);
    if (!exploded_on_) {
        updatePickList();
        return;
    }
    auto t0 = std::chrono::steady_clock::now();
    // viewer3d.py's order: material regions, else structural ones.
    std::optional<nlohmann::ordered_json> list = model_->region_materials();
    if (!list || !list->is_array() || list->empty()) list = model_->structure_regions();
    const auto n = model_->node_counts();
    std::size_t idx = 0;
    for (const auto& r : *list) {
        const std::size_t list_index = idx++;
        if (!r.is_object() || !r.contains("box") || !r["box"].is_array() || r["box"].size() < 6) continue;
        const auto& box = r["box"];
        ExplodedRegion er;
        er.name = r.value("name", r.value("material", "region " + std::to_string(list_index)));
        er.list_index = list_index;
        bool empty = false;
        for (std::size_t a = 0; a < 3 && !empty; ++a) {
            // The node mask viewer3d.py uses: lo <= x <= hi, in cm.
            const double lo = box[2 * a].get<double>(), hi = box[2 * a + 1].get<double>();
            const auto& ax = model_->axis(static_cast<int>(a));
            std::size_t first = n[a], last = 0;
            for (std::size_t i = 0; i < ax.size(); ++i)
                if (ax[i] >= lo && ax[i] <= hi) {
                    first = std::min(first, i);
                    last = i;
                }
            if (first == n[a]) empty = true;
            er.nodes.lo[a] = first;
            er.nodes.hi[a] = last;
        }
        if (empty) continue;
        er.offset_um = static_cast<double>(list_index) * exploded_sep_um_;
        vtkNew<vtkExtractRectilinearGrid> ex;
        ex->SetInputData(dual_grid_);
        ex->SetVOI(static_cast<int>(er.nodes.lo[0]), static_cast<int>(er.nodes.hi[0] + 1),
                   static_cast<int>(er.nodes.lo[1]), static_cast<int>(er.nodes.hi[1] + 1),
                   static_cast<int>(er.nodes.lo[2]), static_cast<int>(er.nodes.hi[2] + 1));
        vtkNew<vtkDataSetSurfaceFilter> sf;
        sf->SetInputConnection(ex->GetOutputPort());
        sf->Update();
        vtkNew<vtkPolyData> pd;
        pd->ShallowCopy(sf->GetOutput());
        vtkNew<vtkPolyDataMapper> m;
        m->SetInputData(pd);
        m->ScalarVisibilityOff();
        auto actor = vtkSmartPointer<vtkActor>::New();
        actor->SetMapper(m);
        const theme::Rgb c = theme::regionRgb(list_index);
        const theme::Rgb edge = theme::rgb(theme::T::BorderStrong, scheme_);
        actor->GetProperty()->SetColor(c.r, c.g, c.b);
        actor->GetProperty()->SetOpacity(0.6);  // viewer3d.py's region surfaces
        actor->GetProperty()->EdgeVisibilityOn();
        actor->GetProperty()->SetEdgeColor(edge.r, edge.g, edge.b);
        actor->SetPosition(0.0, 0.0, er.offset_um);
        renderer_->AddViewProp(actor);
        er.actor = actor;
        region_actors_.push_back(actor);
        regions_.push_back(er);
    }
    updatePickList();
    layer_t_.exploded_ms = lap_ms(t0);
}

// ------------------------------------------------------------ playback ----

const SweepSnapshots* FieldView::snapshots() const {
    if (!snapshots_checked_) {
        snapshots_checked_ = true;
        if (is3D() && model_->has_sweep_snapshots()) {
            try {
                snapshots_ = model_->sweep_snapshots();
            } catch (const std::exception&) {
                snapshots_.reset();  // the store raises too; the playback dock stays disabled
            }
        }
    }
    return snapshots_ ? &*snapshots_ : nullptr;
}

bool FieldView::showingSnapshot() const {
    if (!snapshot_ || !model_ || source_ != model_) return false;
    const SweepSnapshots* s = snapshots();
    if (!s || *snapshot_ >= s->count()) return false;
    return std::find(s->field_names.begin(), s->field_names.end(), field_) != s->field_names.end();
}

void FieldView::loadSnapshotValues() {
    raw_.values = model_->snapshot_field(*snapshots_, field_, *snapshot_);
}

std::array<double, 2> FieldView::snapshotUnion() {
    const std::string key = field_ + (log_ ? "|log" : "|lin");
    if (auto it = snapshot_union_.find(key); it != snapshot_union_.end()) return it->second;
    double lo = std::numeric_limits<double>::infinity(), hi = -lo;
    for (std::size_t k = 0; k < snapshots_->count(); ++k) {
        const auto r = displayedMinMax(model_->snapshot_field(*snapshots_, field_, k));
        if (r[0] <= r[1]) {
            lo = std::min(lo, r[0]);
            hi = std::max(hi, r[1]);
        }
    }
    if (!(lo <= hi)) lo = hi = 0.0;
    return snapshot_union_[key] = {lo, hi};
}

void FieldView::setSnapshot(std::optional<std::size_t> k) {
    if (!is3D()) return;
    const SweepSnapshots* s = snapshots();
    if (k && (!s || s->count() == 0)) k.reset();
    if (k && s) k = std::min(*k, s->count() - 1);
    if (k == snapshot_) return;
    auto t0 = std::chrono::steady_clock::now();
    snapshot_ = k;
    ++values_version_;
    rebuildScalars();  // decodes the snapshot, gathers, refreshes the isosurface / volume
    layer_t_.snapshot_ms = lap_ms(t0);
    renderNow();
    emit displayChanged();
}

// --------------------------------------------------------------- views ----

void FieldView::setViewPreset(ViewPreset p) {
    if (!is3D()) return;
    vtkCamera* cam = renderer_->GetActiveCamera();
    double pos[3] = {0.8, -0.6, -1.0}, up[3] = {0.0, -1.0, 0.0};  // Iso: as P0's default
    switch (p) {
        case ViewPreset::Iso: break;
        case ViewPreset::PlusX: pos[0] = -1; pos[1] = 0; pos[2] = 0; break;
        case ViewPreset::MinusX: pos[0] = 1; pos[1] = 0; pos[2] = 0; break;
        case ViewPreset::PlusY: pos[0] = 0; pos[1] = -1; pos[2] = 0; up[1] = 0; up[2] = 1; break;
        case ViewPreset::MinusY: pos[0] = 0; pos[1] = 1; pos[2] = 0; up[1] = 0; up[2] = 1; break;
        case ViewPreset::PlusZ: pos[0] = 0; pos[1] = 0; pos[2] = -1; break;   // as the 2D map: x right, y down
        case ViewPreset::MinusZ: pos[0] = 0; pos[1] = 0; pos[2] = 1; break;
    }
    cam->ParallelProjectionOff();
    cam->SetFocalPoint(0.0, 0.0, 0.0);
    cam->SetPosition(pos);
    cam->SetViewUp(up);
    renderer_->ResetCamera();
    renderNow();
}

}  // namespace tcad::desktop
