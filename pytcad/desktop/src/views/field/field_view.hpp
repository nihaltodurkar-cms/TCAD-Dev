// FieldView: 2D and 3D scalar-field display of a solved result, on VTK
// inside the Qt Widgets shell (NATIVE-DESKTOP-PLAN.md sections 5.1, 15).
//
// Geometry is extracted ONCE per result (P1 S2): the node index of every
// displayed element rides through the geometry filter, so a field switch
// only gathers values. 3D picking goes through a static cell locator.
//
// S5 (2D map parity with the QML viewport, section 15.17):
//   - 2D maps use NEAREST shading, as pcolormesh(shading="nearest") does:
//     each node owns a flat patch between the midpoints to its neighbours
//     (grid_edges.hpp), drawn as cell data on that dual grid. What is on
//     screen is only computed values. (3D keeps the smooth surface until
//     S6 -- review revision 3.)
//   - Colours are matplotlib's own tables, fed matplotlib's Normalize
//     (colormaps.hpp): a node gets the colour the QML viewport gives it.
//   - Each kind of field keeps the QML viewport's display:
//       Generic       viridis; log10 max(|v|, 1e-30) with the log toggle
//       Band (Ec..)   viridis; always linear (the QML bands view ignores log)
//       Recombination inferno; always log10 max(|R|, 1e-30)
//       Doping        RdBu_r, symmetric range; with log, the SIGNED log
//                     sign(N) * log10(max(|N|, 1)) -- the one deliberate
//                     improvement over the QML result view (decision 2)
//     A colour-map override and a manual (optionally locked) range apply
//     on top.
//   - 2D overlays: contours at matplotlib's own contour(levels=8) levels
//     (contour_levels.hpp) on the displayed values, and lines through
//     every node coordinate; both in the theme's overlay colour.
//   - The scalar bar has its OWN viewport right of the map, so the map
//     can never run under it, and its title is a separate text actor
//     above it. A hover over the bar's viewport reads nothing.
//   - A field can come from another result on the same mesh: a derived
//     map (bands, recombination) the backend service computed.
// The hover readout always snaps to a real mesh node and reports the RAW
// value there (the M51 rule), whatever the display transform.
//
// S6 (3D parity with viewer3d.py, section 15.19; field_view_3d.cpp):
//   - 3D is nearest-shaded too: each node owns a voxel between the
//     midpoints to its neighbours. The outer faces of the (cropped) voxel
//     grid, and axis-aligned slices at node planes, are flat node-exact
//     patches, drawn unlit ("colours are data"). A pick on them names the
//     voxel's node directly.
//   - Interior layers: an isosurface (flying edges on the displayed node
//     values, coloured by its level), a volume (constant-opacity presets),
//     current-density glyphs and streamlines, an exploded view of the
//     result's regions, and sweep-snapshot playback.
#pragma once

#include "data/result_model.hpp"
#include "theme/tokens.hpp"
#include "views/colormaps.hpp"

#include <QString>
#include <QVTKOpenGLNativeWidget.h>
#include <vtkActor.h>
#include <vtkCellPicker.h>
#include <vtkDataSetSurfaceFilter.h>
#include <vtkExtractRectilinearGrid.h>
#include <vtkFlyingEdges2D.h>
#include <vtkFlyingEdges3D.h>
#include <vtkSmartVolumeMapper.h>
#include <vtkVolume.h>
#include <vtkVolumeProperty.h>
#include <vtkImageData.h>
#include <vtkDoubleArray.h>
#include <vtkGenericOpenGLRenderWindow.h>
#include <vtkIdTypeArray.h>
#include <vtkLookupTable.h>
#include <vtkNew.h>
#include <vtkPolyData.h>
#include <vtkPolyDataMapper.h>
#include <vtkRectilinearGrid.h>
#include <vtkRenderer.h>
#include <vtkScalarBarActor.h>
#include <vtkSmartPointer.h>
#include <vtkStaticCellLocator.h>
#include <vtkTextActor.h>

#include <array>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace tcad::desktop {

// Where the time of the last field switch / hover went, in ms
// (NATIVE-DESKTOP-PLAN.md section 15.11, Step 0).
struct SwitchTimings {
    double decode_ms = 0, fill_ms = 0, range_ms = 0, update_ms = 0, render_ms = 0;
};
struct HoverTimings {
    double pick_ms = 0, snap_ms = 0;
};
// The last contour build (S5 bench): displayed node values, levels, the
// contour filter itself, and the render.
struct ContourTimings {
    double fill_ms = 0, levels_ms = 0, filter_ms = 0, render_ms = 0;
};

// The last 3D layer builds (S6 bench), excluding the render.
struct Layer3DTimings {
    double crop_ms = 0, slice_ms = 0, iso_ms = 0, volume_ms = 0, glyph_ms = 0, streamline_ms = 0,
           exploded_ms = 0, snapshot_ms = 0;
};

enum class FieldKind { Generic, Doping, Band, Recombination };

// 3D display state (S6).
enum class SurfaceMode { Field, Context, Hidden };
enum class ViewPreset { Iso, PlusX, MinusX, PlusY, MinusY, PlusZ, MinusZ };
// viewer3d.py's TRANSFER_FUNCTION_PRESETS: a colour map and a constant
// opacity, whatever the names suggest (section 15.19 finding 4).
enum class VolumePreset { Linear, LogHigh, LogLow, Threshold };
struct VolumePresetSpec {
    ColorMap map;
    double opacity;
};
VolumePresetSpec volumePresetSpec(VolumePreset p);
const char* volumePresetName(VolumePreset p);
std::optional<VolumePreset> volumePresetFromName(const std::string& name);

struct NodeBox {  // inclusive node-index ranges per axis
    std::array<std::size_t, 3> lo{}, hi{};
    bool operator==(const NodeBox&) const = default;
};
struct SliceState {
    bool on = false;
    std::size_t index = 0;
};
// One exploded region as drawn: its name, the node-index box it covers,
// and its offset along z (um).
struct ExplodedRegion {
    std::string name;
    std::size_t list_index = 0;  // position in the result's region list (sets the offset)
    NodeBox nodes;
    double offset_um = 0;
    vtkActor* actor = nullptr;
};

// The kind a field's NAME implies: "doping"; "Ec"/"Ev"/"EFn"/"EFp"
// (band maps); "R" (the recombination map); anything else is generic.
FieldKind fieldKindOf(const std::string& name);

struct ColorRange {
    bool manual = false;  // false: auto (the data's own min..max)
    double lo = 0.0, hi = 1.0;
    bool locked = false;  // manual and kept across field switches
};

class FieldView : public QVTKOpenGLNativeWidget {
    Q_OBJECT

public:
    explicit FieldView(QWidget* parent = nullptr);
    ~FieldView() override;

    // `model` must outlive the view's use of it (MainWindow owns both).
    void setResult(const ResultModel* model);
    // A field of the result.
    void setField(const std::string& name);
    // A field of another result on the SAME mesh (a derived map from the
    // backend). Throws std::invalid_argument when its axes differ.
    void setDerivedField(const ResultModel* source, const std::string& name);
    const ResultModel* fieldSource() const { return source_; }
    const ResultModel* result() const { return model_; }

    void setLogScale(bool on);
    bool logScale() const { return log_; }
    // Whether a log transform is actually applied to the current field
    // (bands never; recombination always; others with the toggle).
    bool logEffective() const;
    void setColorMap(std::optional<ColorMap> override_map);  // nullopt: the field kind's default
    ColorMap colorMap() const;                              // in effect
    std::optional<ColorMap> colorMapOverride() const { return cmap_override_; }
    void setContours(bool on);
    bool contours() const { return contours_; }
    void setMeshLines(bool on);
    bool meshLines() const { return mesh_lines_; }
    void setManualRange(double lo, double hi, bool locked);
    void setAutoRange();
    const ColorRange& colorRange() const { return range_; }
    FieldKind fieldKind() const { return fieldKindOf(field_); }
    // The value range mapped onto the colour table's ends: displayed
    // values v show as lut_input(v, normRange()[0], normRange()[1]).
    std::array<double, 2> normRange() const { return norm_; }
    // A raw value as the current field displays it (before normalisation).
    double displayTransform(double raw) const;

    // Background and annotation colours from the theme tokens.
    void applyTheme(theme::Scheme scheme);
    vtkScalarBarActor* scalarBar() const { return bar_; }
    bool is3D() const;
    const std::string& field() const { return field_; }

    // Hover readout at widget (logical, top-left origin) pixel coords.
    // Returns false when the pointer is off the device or over the bar.
    bool readoutAt(double x_px, double y_px, QString* text);

    // Fit the camera to the device (the Python viewport's fit()/reset).
    void resetView();
    // Render synchronously and wait for the GPU (used by the benchmark).
    void renderNow();
    vtkRenderer* renderer() const { return renderer_; }
    vtkRenderer* barRenderer() const { return bar_renderer_; }
    const SwitchTimings& lastSwitchTimings() const { return switch_t_; }
    const ContourTimings& lastContourTimings() const { return contour_t_; }

    // Read-only views for the self-test (bench/selftest.cpp).
    vtkPolyData* displayedGeometry() const { return surface_; }
    // The node index of every displayed element: its patch CELLS (nearest
    // shading, 2D and -- since S6 -- 3D).
    vtkIdTypeArray* displayedNodeIds() const { return surface_ids_; }
    bool displaysCells() const { return true; }
    vtkDoubleArray* displayedScalars() const { return scalars_; }
    // The scalar bar's label range (the norm range, widened by +-0.5 for a
    // constant field so the labels have a span -- P0's behaviour).
    const double* scalarRange() const { return bar_lut_->GetRange(); }
    vtkLookupTable* lookupTable() const { return lut_; }
    vtkActor* fieldActor() const { return actor_; }
    vtkActor* contourActor() const { return contour_actor_; }
    vtkActor* meshActor() const { return mesh_actor_; }
    vtkTextActor* barTitle() const { return title_; }
    const std::vector<double>& contourLevels() const { return contour_levels_; }
    const std::vector<double>& axisUm(int a) const { return axes_um_[static_cast<std::size_t>(a)]; }
    const std::vector<double>& edgesUm(int a) const { return edges_um_[static_cast<std::size_t>(a)]; }
    QString readoutForPoint(const double p_um[3]) const;
    const HoverTimings& lastHoverTimings() const { return hover_t_; }
    // How often the GL context was (re)initialised: a reparent recreates it.
    int glInitializations() const { return gl_inits_; }

    // ---- 3D (S6, field_view_3d.cpp). Each is a no-op outside a 3D result. ----
    void setSurfaceMode(SurfaceMode m);
    SurfaceMode surfaceMode() const { return surface_mode_; }
    // Crop (clipping) to node-index ranges, clamped to the grid.
    void setCrop(const NodeBox& box);
    const NodeBox& crop() const { return crop_; }
    NodeBox fullBox() const;
    void setSlice(int axis, bool on, std::size_t index);
    SliceState slice(int axis) const { return slices_[static_cast<std::size_t>(axis)].state; }
    // The QML viewport's 3D view: the z-slice at nz // 2, surface hidden,
    // looking along +z.
    void showCentralZPlane();
    void setIsosurface(bool on);
    bool isosurface() const { return iso_on_; }
    void setIsoLevel(double displayed_level);  // in displayed units (log10 when log applies)
    double isoLevel() const { return iso_level_; }
    // Finite displayed min/max of the current field: the level's range.
    std::array<double, 2> dataRange() const { return data_range_; }
    void setVolume(bool on);
    bool volume() const { return volume_on_; }
    // Sets the view's colour map to the preset's (the bar stays true) and
    // the volume's constant opacity.
    void setVolumePreset(VolumePreset p);
    VolumePreset volumePreset() const { return volume_preset_; }
    void setVectorField(const std::string& name);
    const std::string& vectorField() const { return vector_name_; }
    void setGlyphs(bool on);
    bool glyphs() const { return glyphs_on_; }
    void setGlyphSpacing(double fraction);  // of the device diagonal, 0..0.5
    double glyphSpacing() const { return glyph_spacing_; }
    void setStreamlines(bool on);
    bool streamlines() const { return streamlines_on_; }
    // Why not, when the result has no usable regions.
    bool explodedAvailable(QString* why = nullptr) const;
    void setExploded(bool on);
    bool exploded() const { return exploded_on_; }
    void setExplodedSeparation(double um);
    double explodedSeparation() const { return exploded_sep_um_; }
    double diagonalUm() const;  // the device's (node box) diagonal
    // Sweep playback: nullptr when the result has none.
    const SweepSnapshots* snapshots() const;
    // Show snapshot k of the current field (nullopt: the result's own).
    void setSnapshot(std::optional<std::size_t> k);
    std::optional<std::size_t> snapshot() const { return snapshot_; }
    // Whether the current field is being shown from a snapshot.
    bool showingSnapshot() const;
    void setViewPreset(ViewPreset p);
    const Layer3DTimings& lastLayerTimings() const { return layer_t_; }
    static constexpr double kDragFps = 30.0;  // the interactor's rate while dragging (volume LOD)

    // Read-only views for the self-test.
    vtkRectilinearGrid* dualGrid() const { return dual_grid_; }
    vtkPolyData* slicePoly(int axis) const { return slices_[static_cast<std::size_t>(axis)].poly; }
    vtkIdTypeArray* sliceNodeIds(int axis) const { return slices_[static_cast<std::size_t>(axis)].ids; }
    vtkDoubleArray* sliceScalars(int axis) const { return slices_[static_cast<std::size_t>(axis)].scalars; }
    vtkActor* sliceActor(int axis) const { return slices_[static_cast<std::size_t>(axis)].actor; }
    vtkPolyData* isoPoly() const { return iso_poly_; }
    vtkActor* isoActor() const { return iso_actor_; }
    vtkVolume* volumeProp() const { return volume_; }
    vtkRectilinearGrid* volumeGrid() const { return volume_grid_; }
    vtkPolyData* glyphSources() const { return glyph_sources_; }  // the arrows' base points, with "J" and node ids
    double glyphScaleFactor() const { return glyph_scale_; }      // arrow length = factor * |J| (um)
    vtkPolyData* glyphPoly() const { return glyph_poly_; }
    vtkPolyData* streamlinePoly() const { return stream_lines_; }  // before tubing
    vtkActor* streamlineActor() const { return stream_actor_; }
    vtkActor* glyphActor() const { return glyph_actor_; }
    vtkActor* outlineActor() const { return outline_actor_; }
    vtkScalarBarActor* vectorBar() const { return vbar_; }
    const std::vector<ExplodedRegion>& explodedRegions() const { return regions_; }
    QString readoutForNode(std::size_t node) const;
    // 3D: the node whose voxel holds world point p, within the crop box;
    // `fixed_axis` >= 0 pins that axis to `fixed_index` (a slice's plane).
    std::size_t voxelNode(const double p[3], int fixed_axis = -1, std::size_t fixed_index = 0) const;

signals:
    void readoutChanged(const QString& text);
    void displayChanged();  // field, scale, colour map, range or overlays changed

protected:
    void mouseMoveEvent(QMouseEvent* event) override;
    void leaveEvent(QEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void initializeGL() override;

private:
    void showField(const ResultModel* source, const std::string& name);
    void rebuildScalars();
    void rebuildContours();
    void buildMeshLines();
    void updateViewports();
    void updateBarTitle();
    void resetCamera();
    void refresh();  // mapper update + render, timed
    std::size_t nearestNode(int axis, double coord_um) const;
    // Transformed, normalised values of `ids`' nodes into `out` (the gather).
    void gather(vtkIdTypeArray* ids, vtkDoubleArray* out) const;

    // 3D (field_view_3d.cpp)
    void setup3D();                // once, in the constructor
    void reset3D();                // per result: grids, crop, layers off
    void rebuildSurface3D();       // crop -> faces, their node ids, locator
    void rebuildSlice(int axis);   // geometry and node ids
    void rebuild3DValues();        // after any change of the displayed values
    void rebuildIso();
    void rebuildVolume();
    void rebuildGlyphs();
    void rebuildStreamlines();
    void rebuildExploded();
    void rebuildOutline();
    void updateBars();
    void updatePickList();
    void enteringInteriorLayer();  // Field -> Context the first time
    const std::vector<double>& croppedDisplayed();  // displayed values of the crop box's nodes, x fastest (cached)
    std::array<double, 2> displayedMinMax(const std::vector<double>& raw) const;  // finite, transformed
    std::array<std::size_t, 3> cropSize() const;
    void loadSnapshotValues();     // raw_ from the snapshot, when one applies
    std::array<double, 2> snapshotUnion();
    std::size_t nodeIndex(std::size_t i, std::size_t j, std::size_t k) const;
    // The world ray through display point (xd, yd): origin o, direction d (near to far).
    bool displayRay(double xd, double yd, double o[3], double d[3]) const;
    // Where that ray enters the crop box's patch-edge box.
    bool rayCropBox(const double o[3], const double d[3], double hit[3]) const;

    const ResultModel* model_ = nullptr;   // geometry, and the result's own fields
    const ResultModel* source_ = nullptr;  // where the current field comes from
    std::string field_;
    ScalarField raw_;  // raw values of the current field (the readout never shows transformed ones)
    bool log_ = false;
    bool contours_ = false;
    bool mesh_lines_ = false;
    std::optional<ColorMap> cmap_override_;
    ColorRange range_;
    std::array<double, 2> norm_{0.0, 1.0};
    std::vector<double> contour_levels_;
    theme::Scheme scheme_ = theme::Scheme::Dark;
    QString readout_;
    SwitchTimings switch_t_;
    HoverTimings hover_t_;
    ContourTimings contour_t_;
    int gl_inits_ = 0;

    vtkNew<vtkGenericOpenGLRenderWindow> window_;
    vtkNew<vtkRenderer> renderer_;
    vtkNew<vtkRenderer> bar_renderer_;
    vtkNew<vtkRectilinearGrid> grid_;       // the node grid: 3D surface, 2D contours
    vtkNew<vtkRectilinearGrid> dual_grid_;  // 2D: patch edges, one cell per node
    vtkNew<vtkDoubleArray> scalars_;        // displayed, normalised to [0, 1]
    vtkNew<vtkDoubleArray> node_values_;    // 2D: displayed (transformed) node values, for contours
    vtkNew<vtkLookupTable> lut_;            // over [0, 1]: the map
    vtkNew<vtkLookupTable> bar_lut_;        // the same table over the value range: the bar's labels
    vtkNew<vtkPolyDataMapper> mapper_;
    vtkNew<vtkActor> actor_;
    vtkNew<vtkScalarBarActor> bar_;
    vtkNew<vtkTextActor> title_;
    vtkNew<vtkImageData> index_grid_;        // 2D contours: node values on a unit (index) grid
    vtkNew<vtkFlyingEdges2D> flying_edges_;  // ... contoured there, multithreaded
    vtkNew<vtkPolyData> contour_poly_;       // ... and mapped back onto the true axes
    vtkNew<vtkPolyDataMapper> contour_mapper_;
    vtkNew<vtkActor> contour_actor_;
    vtkNew<vtkPolyDataMapper> mesh_mapper_;
    vtkNew<vtkActor> mesh_actor_;
    vtkNew<vtkCellPicker> picker_;
    vtkNew<vtkStaticCellLocator> locator_;
    vtkSmartPointer<vtkPolyData> surface_;         // the displayed geometry, built per result
    vtkSmartPointer<vtkIdTypeArray> surface_ids_;  // its elements' node indices into the field
    std::array<std::vector<double>, 3> axes_um_;
    std::array<std::vector<double>, 3> edges_um_;  // nearest-shading patch edges (2D and 3D)

    // ---- 3D state (S6) ----
    std::array<double, 2> data_range_{0.0, 1.0};  // finite displayed min/max of the current values
    int values_version_ = 0;                      // bumped whenever the displayed values change
    SurfaceMode surface_mode_ = SurfaceMode::Field;
    bool interior_seen_ = false;  // the Field -> Context switch happens once per result
    NodeBox crop_;
    vtkNew<vtkExtractRectilinearGrid> crop_filter_;
    vtkNew<vtkDataSetSurfaceFilter> surface_filter_;
    vtkNew<vtkPolyDataMapper> outline_mapper_;
    vtkNew<vtkActor> outline_actor_;
    struct Slice {
        SliceState state;
        vtkNew<vtkPolyData> poly;
        vtkNew<vtkIdTypeArray> ids;
        vtkNew<vtkDoubleArray> scalars;
        vtkNew<vtkPolyDataMapper> mapper;
        vtkNew<vtkActor> actor;
        vtkNew<vtkStaticCellLocator> locator;
        bool locator_stale = true;
    };
    std::array<Slice, 3> slices_;
    bool iso_on_ = false;
    double iso_level_ = 0.0;
    int iso_version_ = -1;  // values_version_ the isosurface was built from
    vtkNew<vtkImageData> iso_image_;
    vtkNew<vtkFlyingEdges3D> iso_filter_;
    vtkNew<vtkPolyData> iso_poly_;
    vtkNew<vtkPolyDataMapper> iso_mapper_;
    vtkNew<vtkActor> iso_actor_;
    vtkNew<vtkStaticCellLocator> iso_locator_;
    bool iso_locator_stale_ = true;
    bool volume_on_ = false;
    VolumePreset volume_preset_ = VolumePreset::Linear;
    vtkNew<vtkRectilinearGrid> volume_grid_;
    vtkNew<vtkSmartVolumeMapper> volume_mapper_;
    vtkNew<vtkVolumeProperty> volume_property_;
    vtkNew<vtkVolume> volume_;
    std::string vector_name_;
    bool glyphs_on_ = false;
    double glyph_spacing_ = 0.05;  // viewer3d.py's default
    double glyph_scale_ = 0.0;
    bool streamlines_on_ = false;
    vtkNew<vtkPolyData> glyph_sources_;
    vtkNew<vtkPolyData> glyph_poly_;
    vtkNew<vtkPolyDataMapper> glyph_mapper_;
    vtkNew<vtkActor> glyph_actor_;
    vtkNew<vtkPolyData> stream_lines_;
    vtkNew<vtkPolyDataMapper> stream_mapper_;
    vtkNew<vtkActor> stream_actor_;
    vtkNew<vtkLookupTable> vector_lut_;  // plasma over [0, max |J|]
    vtkNew<vtkScalarBarActor> vbar_;
    vtkNew<vtkTextActor> vtitle_;
    bool exploded_on_ = false;
    double exploded_sep_um_ = 0.0;
    std::vector<ExplodedRegion> regions_;
    std::vector<vtkSmartPointer<vtkActor>> region_actors_;
    std::optional<std::size_t> snapshot_;
    std::vector<double> crop_values_;  // croppedDisplayed()'s cache ...
    int crop_values_version_ = -1;     // ... valid for this values_version_
    NodeBox crop_values_box_;          // ... and this crop
    NodeBox iso_box_;                  // the crop the isosurface was built on
    double iso_built_level_ = 0.0;
    mutable std::optional<SweepSnapshots> snapshots_;  // parsed on first use
    mutable bool snapshots_checked_ = false;
    std::map<std::string, std::array<double, 2>> snapshot_union_;  // raw min/max over a field's snapshots, per transform
    Layer3DTimings layer_t_;
};

}  // namespace tcad::desktop
