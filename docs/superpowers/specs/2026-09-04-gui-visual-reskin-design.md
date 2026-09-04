# PyTCAD Desktop GUI — Visual Reskin Design

Status: approved by user 2026-09-04, ready for implementation planning.

## 1. Motivation

The user's stated complaint: "The GUI looks too basic, Mesh / main window
size is small, I want you to make it look more cool and amazing." This is
the first of four independently-scoped GUI improvement areas identified
in the initial conversation (visual/UX polish, workflow friction,
QML/code architecture, performance) — this spec covers **visual/UX polish
only**. The other three remain queued as separate future sub-projects and
are explicitly out of scope here (section 12).

Confirmed via a visual-companion mockup session (four style directions,
four accent-color options) with the user selecting concretely at each
step — see decisions below.

## 2. Goals

- Replace today's restrained, flat "scientific-instrument" look with a
  "Modern Dev Tool" visual identity (Linear/Vercel-inspired): near-black
  surfaces, floating rounded cards with soft shadow depth, a violet→blue
  gradient accent used for active/selected state and the primary action
  (Run).
- Replace the current plain Unicode glyphs (▤ ▦ ⚗ ∿ ⎍ ◈ ≡ ⏱ ⚛ ✎, plus
  toolbar ▶ ■ ↶ ↷ ☀/🌙) with a small custom vector icon set that can be
  colored/animated per Theme state.
- Fix the "everything feels small" complaint: the main window launches
  maximized by default, and the left workbench dock (currently 310px
  preferred / 240px minimum) is widened so panel content — the Mesh
  panel specifically named by the user — has room to breathe.
- Give both dark and light theme variants the new token set — dark is
  the primary/reference identity (all mockups were dark), light is a
  tuned equivalent, not an afterthought, since the existing Ctrl+D
  toggle must keep working.

## 3. Non-goals

- No changes to controllers, services, the numerical core (`pytcad/`),
  or `DeviceSpec`/wire formats. This is a QML/Theme-layer change only,
  consistent with AGENTS.md's layering rule (QML -> controllers ->
  services -> ... ; controllers/canvas never import pytcad).
- No workflow/UX flow changes (e.g., how sweeps are configured, how
  projects are saved) — that is the separate "workflow friction"
  sub-project already queued.
- No QML/controller code-architecture refactor beyond what's naturally
  touched while reskinning (e.g., a panel's layout structure may change
  to fit new content, but its controller API does not).
- No performance work.
- No new external asset files (image binaries, icon fonts) and no new
  Python dependencies — icons are inline SVG data URIs generated from
  QML, keeping the existing "one `pip install -r requirements.txt`"
  guarantee intact.

## 4. Visual direction (confirmed)

Four style directions were mocked up in the browser companion: A —
Refined Instrument (evolve current theme), B — Modern Dev Tool
(Linear/Vercel), C — Lab HUD (cyan-on-black sci-fi), D — Light
Professional (CAD-tool). **User selected B.**

Four accent colors were then mocked on top of style B: Violet–Blue,
Teal–Cyan, Orange–Amber, Sky–Indigo. **User selected Violet–Blue.**

Reference values from the approved mockup (`accent-color.html`,
`.p1` ruleset):

- Gradient: `#8b5cf6` (violet) → `#3b82f6` (blue), used at 135° for
  buttons/active glow, 90° for thin accent bars.
- Active-tab tint: `rgba(139,92,246,0.25)` → `rgba(59,130,246,0.15)`
  gradient wash, `#c4b5fd` text, `inset 0 0 0 1px rgba(139,92,246,0.35)`
  border.
- Base surfaces: window/toolbar `#0d0e12`, main content backdrop
  `#0a0b0e`, floating card `#16171d` with `#24252c` border and
  `0 8px 20px rgba(0,0,0,0.4)` shadow.

These are starting values transcribed from the approved mockup, not
final pixel-locked constants — small adjustments during implementation
(e.g., contrast/accessibility tuning) are expected and fine as long as
the identity (near-black + floating violet-blue-accented cards) is
preserved.

## 5. Theme.qml v2 (design-system layer)

Additive changes only — every existing token name (`background`,
`panel`, `accent`, `pad`, etc.) stays valid so nothing else in the
codebase breaks on day one; new tokens are introduced alongside, and
consumers migrate panel-by-panel in the rollout (section 9).

New tokens needed (dark value / light value):

- `cardBg` — `#16171d` / a light equivalent (e.g. `#ffffff` with a
  slightly stronger shadow, since the light variant can't rely on
  near-black for depth).
- `cardBorder` — `#24252c` / `#dde3e9`-ish.
- `cardShadow` — `Qt.rgba(0,0,0,0.4)` / a much softer light-mode shadow.
- `accentGradientStart` — `#8b5cf6` (kept identical in both themes —
  the accent is the brand, not a surface).
- `accentGradientEnd` — `#3b82f6`.
- `accentGlow` — already exists in Theme.qml today; retune its color to
  the violet-blue pair instead of the current plain blue.
- A helper (QML `Gradient`/`property var` or a small JS function) for
  building the 135°/90° gradients consistently, so every consumer
  doesn't hand-roll `GradientStop` pairs.

Existing `dark`/`background`/`panel`/etc. tokens are retuned toward the
new near-black base (`#0d0e12` / `#0a0b0e` family) rather than the
current `#171b20` family — this is a value change, not a new token, so
every existing consumer picks it up automatically.

## 6. Icons.qml (new singleton)

A `pragma Singleton` sibling to `Theme.qml`, exposing one function,
e.g. `Icons.svg(name, color)`, returning a `data:image/svg+xml,...`
URI for use as an `Image.source`. Icons needed, one per current glyph:

Workbench tabs: Project (⌂), Structure (▤), Mesh (▦), Process (⚗),
Sweeps (∿), Probe Station (⎍), Telemetry (◈), Bands (≡), Transient (⏱),
Physics Lab (⚛), Builder (✎).

Toolbar: Run (▶), Stop (■), Undo (↶), Redo (↷), theme toggle (☀/🌙).

Each icon is a simple geometric line/solid glyph (12–20px viewBox)
designed to read at 16–20px in the sidebar and toolbar, colorable via
the `color` argument so active/hover/dim states reuse the same icon
definition (matches how `Theme.text`/`Theme.accent`/`Theme.textFaint`
already drive icon-adjacent label colors today). A small headless test
(`gui/tests/test_icons.py`) asserts every name used in Main.qml/panels
resolves to a non-empty data URI in both themes — a cheap regression
gate against a typo silently rendering a blank icon.

**Risk flagged, not resolved here:** whether the Qt/PySide6 install in
this environment has the SVG image plugin available for `Image` to
decode a `data:image/svg+xml` URI is an implementation-time check, not
assumed. If unavailable, the fallback is generating icons as QML
`Shape`/`Canvas` paths instead of SVG data URIs — same visual result,
different QML mechanism. This is a plan-time/implementation-time
decision, not a design-time blocker.

## 7. Main.qml shell reskin

- Window launches maximized (`visibility: Window.Maximized` or
  equivalent set in `Component.onCompleted`) on first run; the current
  `width`/`height`/`minimumWidth`/`minimumHeight` values remain as the
  fallback for environments where maximizing doesn't apply (headless
  `QT_QPA_PLATFORM=offscreen` test runs must not regress — verified in
  section 10).
- Toolbar and footer restyled to the near-black chrome tones; the
  existing depth-shadow gradient under the toolbar stays (already a
  good pattern) but re-tuned to the new palette.
- Sidebar tabs (`workbenchTabs`) restyled as pill-shaped with the
  gradient-wash active state and new vector icons replacing the
  `icon + label` string concatenation; the existing gliding accent-bar
  indicator concept stays but adopts the gradient color.
- The viewport (`ViewportPanel`) reads as a floating card inset from
  a darker window backdrop, rather than being flush with the chrome —
  this is the biggest single visual change and the one closest to the
  "cool and amazing" ask.
- Workbench dock default/minimum width increases (from 310/240) — exact
  new values are an implementation-time fit-and-check against the
  widest tab label and the Mesh panel's new content (section 8), not
  pixel-locked here.
- Properties dock and console dock get the same card treatment
  (background, border, shadow) so all three docks read as one family.

## 8. Panel content restyle

Applied panel-by-panel, in this priority order (Mesh first, since it's
the panel the user explicitly named):

1. **MeshPanel** — the "Mesh statistics" block (currently a plain
   vertical `Label` list, `gui/qml/panels/MeshPanel.qml:19-45`) becomes
   a small card-grid: one tile per mesh axis showing node count and
   min/max extent, styled with the new `cardBg`/`cardBorder` tokens
   instead of bare text labels. `MeshEditor` above it gets the same
   card treatment for its input fields.
2. **StructurePanel**
3. **ProcessPanel**
4. **SweepPanel**
5. Remaining panels (Probe Station, Solver Telemetry, Band Diagram,
   Transient, Physics Lab, Device Templates, Project Tree, Properties,
   Console) — same treatment, order flexible, grouped into implementation
   slices of 2-3 panels each rather than one per slice, since later
   panels are smaller/simpler than the first four.

Each panel's restyle changes only its Rectangle/Layout/color bindings;
no `objectName`, exposed `Property`, or signal changes.

## 9. Rollout (slices)

Matches AGENTS.md's existing workflow discipline (plan -> TDD -> hard
debug -> commit, suite green every slice):

1. **Slice 0 — design system.** `Theme.qml` v2 tokens + `Icons.qml` +
   `test_icons.py`. No visible change yet (nothing consumes the new
   tokens/icons outside the new test). Suite green.
2. **Slice 1 — shell.** Main.qml reskin (toolbar, sidebar tabs +
   icons, viewport-as-card, docks, maximized launch). This is the
   first slice with a visible, screenshot-able result.
3. **Slices 2+ — panel contents**, in the order from section 8, each
   its own slice with the full suite run after.

Each slice: run `pytest tests/ gui/tests/ -n 6 -m "not slow" -q`,
then visually verify with `QT_QPA_PLATFORM=offscreen python3 -m
gui.app` (a real run, not just green tests) before calling it done —
per AGENTS.md's "never claim a change works... without ACTUALLY
RUNNING" rule and this project's own standing instruction to verify UI
changes by using the feature.

## 10. Testing & verification

- No controller/service/core code changes anywhere in this reskin, so
  no non-GUI test should be affected.
- `gui/tests` headless QML tests key off `objectName` and
  `@Property(QObject)` APIs almost exclusively (per AGENTS.md's own
  QML gotchas) — those are preserved unchanged, so most tests need no
  edits. The exception: any test asserting a literal color hex string
  or the old glyph text (e.g. a tab's `text` equalling `"▤ Structure"`)
  needs updating to match the new icon-based rendering — grep for such
  assertions before starting slice 1, don't discover them via failures
  alone.
- The maximized-launch change must not break `gui/tests/conftest.py`'s
  headless `QApplication`/offscreen setup — verify explicitly in slice
  1 rather than assuming it's fine.
- New `test_icons.py` (slice 0) as described in section 6.
- Full suite (`pytest tests/ gui/tests/ -q`, serial) run once at the
  end of the whole reskin as a final gate, in addition to the
  per-slice fast-suite runs.

## 11. Open questions / risks (carried into implementation, not blockers here)

- SVG image-plugin availability for icon rendering (section 6) —
  resolve by trying it in slice 0; fall back to QML `Shape` paths if
  needed.
- Exact widened dock width is a fit-and-check, not a pre-committed
  number.
- Whether any existing test hardcodes a color/glyph string that this
  reskin breaks — resolve by grepping `gui/tests/` for the current
  glyphs and hex values before slice 1.

## 12. Out of scope (queued separately, per the original conversation)

- Workflow/UX friction fixes.
- QML/controller code-architecture cleanup.
- Performance/responsiveness work.

Each remains a candidate for its own future brainstorming → design →
plan cycle.
