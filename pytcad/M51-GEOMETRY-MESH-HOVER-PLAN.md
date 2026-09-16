# M51 — 1D/2D geometry/mesh hover + overlay

## Scope

ARCHITECTURE.md's §7 "STANDING OPEN ITEMS" flagged M51 as unscoped: "NO
INTERACTIVE 1D/2D GEOMETRY/MESH VIEWER". Investigating before implementing
found the gap was narrower than that heading suggests — `ViewportPanel.qml`
already has real pan/zoom (`MouseArea` + `canvas.pan()`/`zoom()`/`fit()`/
`resetView()`), and `MplCanvasItem.hoverAt()` already drives a live readout
for 1D curve modes (series/C-V/transient/AC/convergence). What was actually
missing, confirmed by reading `_build_figure`/`hoverAt`: hovering did nothing
at all for 2D field maps (doping/bands/recombination), Structure mode, or
Mesh mode — `hoverAt` returned immediately whenever `self._series` was
empty, which it always was for those modes — and there was no way to see the
underlying mesh grid drawn over a filled 2D field.

Scoped with the user to: hover-to-inspect (nearest mesh node's value/region/
spacing) for 2D field maps, Structure, and Mesh modes, plus a "mesh overlay"
toggle for 2D field maps — reusing the existing `MouseArea`/pan/zoom/readout
plumbing, no new QML mouse-handling and no new dependency (explicitly
rejected: a heavier interactive backend like mplcursors/blitting, since the
existing Agg-render-then-inspect architecture already supported everything
needed once `hoverAt` learned the extra modes).

## What shipped

- `gui/visualization/mpl_canvas_item.py`: `hoverAt()` is now a dispatcher —
  1D curve series (`_hover_series`, the original logic, unchanged behavior,
  just moved into its own method), a 2D field-map grid (`_hover_field_grid`),
  Structure mode (`_hover_structure`), Mesh mode (`_hover_mesh`). Each
  render path sets exactly one of the hover-state fields it reads
  (`self._series` / `self._field_grid` / `self._mode == "structure"` +
  `self._structure` / `self._mode == "mesh"` + `self._mesh_axes_um`), all
  reset at the top of every `_build_figure()` call the same way `self._ax`/
  `self._series` already were — so there is never ambiguity about which
  hover source is live for the current render.
  - `_hover_field_grid`: snaps to the nearest MESH node (not the nearest
    pixel — a non-uniform mesh's cells aren't uniform pixels) and reports
    the field's RAW value, never the log-transformed one even when the log
    toggle is on — the log toggle only changes what the colormap/contours
    show, never what a reader is told the physical value is. Wired into
    all four 2D-field draw sites: the generic field-map path (any field via
    the field selector, "doping" mode's own name notwithstanding), the
    pre-solve doping preview, and the 2D branches of `_draw_bands`/
    `_draw_recombination`.
  - `_hover_structure`: point-in-region lookup against
    `self._structure.regions` (already an attribute — no new state needed
    beyond the live Axes), reporting the same n-type/p-type sign convention
    `_draw_structure`'s own coloring uses.
  - `_hover_mesh`: nearest node's index plus its LOCAL spacing to its next
    neighbor on each axis — never a single global spacing number, since a
    non-uniform mesh (M21) makes that number actively misleading near a
    refined region.
- `meshOverlay` (bool `Property`, mirrors the existing `contours` property
  exactly) + `_maybe_mesh_overlay(ax, x, y)` (mirrors `_maybe_contour`):
  draws the TRUE mesh axis coordinates — the same `(x, y)` array a caller
  already had in hand from its own `pcolormesh` call, never a re-derived
  approximation — as low-alpha white grid lines over a 2D field. Wired into
  the same four 2D-field draw sites as the hover-grid state.
- `gui/qml/panels/ViewportPanel.qml`: a "mesh" `CheckBox` next to the
  existing "contours" one, `onToggled: canvas.meshOverlay = checked` —
  identical pattern, no new QML infrastructure.
- `gui/tests/test_mpl_canvas_hover_m51.py` (8 tests): hover-value round-trip
  on a uniformly-doped 2D resistor (deterministic expected value regardless
  of which node the cursor snaps to), log-scale-on still reports the raw
  value, out-of-bounds hover clears the readout, Structure-mode region
  lookup (inside and outside every region), Mesh-mode node/spacing report,
  and the mesh-overlay toggle actually adding `Line2D` artifacts to the
  rendered Axes. All 8 pass; the pre-existing `test_mpl_canvas_item.py`
  (6), `test_mpl_canvas_series.py` (8), and `test_viewport_pan_zoom_fast_
  path.py` (6) suites re-run green, unchanged.
- Verified against the REAL running app (not just headless tests): loaded
  `resistor_2d`, ran a real solve, found the actual `mplCanvas` QML object
  in the live tree, hovered over a real rendered figure — readout read
  `"doping: 1.000e+17 cm^-3 @ x=2.03, y=0.53 um"` — and toggled the real
  mesh-overlay property, confirming 100 grid lines appear/disappear on the
  actual rendered Axes.

## Honest limits (deliberately not addressed here)

- No 3D geometry/mesh hover — that's `gui/services/viewer3d.py`'s job
  already (a real PyVista/VTK window); this milestone is the 1D/2D
  companion only, as originally proposed.
- 1D field plots (`dimensionality == 1`) already had curve hover via
  `_hover_series`/`_remember_series` before this milestone — untouched.
- No edge-level inspection (contacts/gates in Structure mode) — only
  region lookup. Contacts/gates are thin boundary lines in the current
  rendering, not areas a cursor naturally lands on; left for a future pass
  if requested.
- The mesh-overlay line styling (fixed low-alpha white) is a single
  reasonable default, not per-colormap-tuned — it stays readable across
  every colormap this module uses (viridis/plasma/RdBu_r/inferno) but was
  not individually verified against each one pixel-by-pixel.
