# PyTCAD Design System

> Category: Professional Engineering Tool (EDA / TCAD)
> A dense, dark instrument surface for semiconductor process/device simulation. Precision over polish, state legibility over decoration. Built for Qt Quick/QML + PySide6.
>
> Authored via OpenDesign (`pytcad-design-system-9386`) and committed here as the
> authoritative source of truth for `gui/qml/Theme.qml` and every QML component/panel.
> See `Theme.qml`'s own header comment and section 12 below ("QML Mapping Notes")
> before hand-editing tokens. The "v2.1 correction" changes described in section 2
> have been applied to `Theme.qml` and the panels/components it identifies; anything
> not yet applied is called out explicitly rather than implied as done.

## 0. Overview

PyTCAD is a professional TCAD/EDA desktop application, not a SaaS product. Its users run long, out-of-process numerical solves (process simulation, device simulation, mesh generation) and need to read structural state, validation state, and solve state at a glance across dozens of dense panels. The design system below optimizes for **information density, unambiguous state, and precise data entry** — never for marketing impact.

| Token | Value | Role |
|---|---|---|
| `bg` | `#0A0B0E` | Canvas / viewport — darkest surface in the app |
| `panel` | `#0D0E12` | Docked panel body |
| `panelAlt` | `#111217` | Inset wells, alternating rows, nested groups |
| `panelRaised` | `#16171D` | Panel headers, toolbars, hovered rows |
| `border` | `#1F2026` | Structural dividers between panels/rows |
| `text` | `#E4E4E7` | Primary content text |
| `accent` | `#8B5CF6` | Sole brand mark — selection, focus, tab underline |

## 1. Prior Art

PyTCAD's reference class is **professional engineering tools**, not consumer software:

- **Cadence Virtuoso / KiCad / Synopsys Custom Compiler** — dense property forms, layer/net trees, non-modal DRC violation lists that stay visible while you keep working.
- **ANSYS Workbench / COMSOL Multiphysics** — project trees that mirror a physical/numerical pipeline (geometry → mesh → solve → results), each node carrying its own stale/solved/failed badge.
- **ParaView / VisIt** — pipeline browser + properties panel + render view triptych; color/opacity driven strictly by data, never by decoration.
- **VS Code / JetBrains IDEs** — dockable panel chrome, command-dense status bar, unambiguous list/tree selection highlighting, keyboard-first navigation with visible focus rings everywhere.

What these share, and what PyTCAD adopts: **the content (viewport, mesh, plot, netlist) is always the brightest, highest-contrast surface on screen; the chrome that surrounds it is deliberately quieter.** Panels are instrument surfaces, addressed by borders and luminance steps — not by cards, shadows, or whitespace.

## 2. Baseline Critique — Correcting the Reskin

The existing `Theme.qml` palette (background `#0a0b0e`, panel `#0d0e12`/`#111217`/`#16171d`, border `#1f2026`, text `#e4e4e7`/`#a1a1aa`, accent `#8b5cf6`, running `#d9a441`, ok `#61bd6d`, error `#e05c56`) is a **good, correctly dark foundation** and is kept almost entirely intact below. Two things layered on top of it in the recent reskin actively work against the brief and are reversed:

| Reskin change | Verdict | Why |
|---|---|---|
| `cardBg`/`cardBorder`/`cardShadow`, 10px card radius on panels | **Reverse.** | Docked panels are not cards. A shadowed, rounded rectangle reads as a floating consumer-app tile, and at TCAD panel counts (6–10 visible at once) the shadows compound into visual noise that competes with the data. Panels should be separated by a 1px border and a luminance step (`bg` → `panel` → `panelRaised`), exactly like Virtuoso's or VS Code's dock chrome. Shadows are reserved for the one class of surface that *is* genuinely floating above the canvas: popovers, context menus, tooltips, and modal dialogs (§6). |
| Violet→blue gradient on tab indicators and the primary Run button | **Reverse on tabs, repurpose on Run.** | A gradient on a tab indicator or a button fill is pure decoration — it encodes nothing. Tabs get a flat 2px accent underline instead (§6, Tab). The gradient itself isn't wasted: its two endpoints are repurposed with real meaning — violet stays the single brand/selection mark, and the blue endpoint (`#3B82F6`) becomes the solid **running** state color (see below), while the two-stop gradient survives in exactly one place: the determinate solve-progress fill, where left-to-right violet→blue literally reads as "queued → in progress" (§6, Busy Indicator). |

**Amber is reassigned from "running" to "warning."** Amber/gold reads as *caution* in every engineering convention (instrument panels, hazard labeling, the rest of this app's own UI). Using it for a normal, healthy "solver is working" state fights the color's learned meaning and leaves validation warnings with no distinct hue at all. The corrected mapping:

- **running** → `#3B82F6` (blue, the repurposed gradient endpoint — "process active," not tied to good/bad)
- **warning** → `#D9A441` (the former "running" amber — now used the way engineers already read it)
- **converged/ok** → `#61BD6D` (unchanged)
- **failed/error** → `#E05C56` (unchanged)

**Violet stays.** As a single, restrained mark — selection fill, focus ring, tab underline, and (in a deepened shade) the primary button — it is defensible: it never appears as a background wash, never repeats more than the charter's two-per-screen budget, and it is the one color in the system that carries no solver/validation meaning, so it can safely mean "this is the thing that's focused/selected/primary" without colliding with state semantics.

Radii shrink from 10px to 0–3px (§5), shadows are removed from every docked surface (§7), and the gradient is demoted from brand decoration to a single functional progress encoding (§6, §8).

**Applied to the codebase (2026-09-04):** `Theme.qml`'s `running`/`warning` tokens, the flat panel treatment on `workbenchDock`/`propertiesDock`/`consoleDock`/`ViewportPanel`/`MeshPanel`'s stat tiles, and the flat tab underline in `Main.qml` all implement this section directly — see each file's "v2.1 correction" comments. `cardBg`/`cardBorder`/`cardShadow`/`radiusCard` remain defined in `Theme.qml` (values unchanged) but are reserved for a future overlay/popover layer; no docked panel consumes them any more. The full component inventory in §9 (status pill with glyphs, dedicated `RunningPulse`/progress-bar components, per-component hover/focus states beyond what already existed) is the spec for that layer — **not yet built**; today's panels use the corrected token values through their existing components.

## 3. Color

### 3.1 Dark mode (primary)

**Surfaces**

| Token | Hex | Role |
|---|---|---|
| `bg` | `#0A0B0E` | Viewport / canvas / render surface |
| `panel` | `#0D0E12` | Docked panel body |
| `panelAlt` | `#111217` | Inset wells, alternating table rows, nested groups |
| `panelRaised` | `#16171D` | Panel headers, toolbars, hovered rows, active tab strip |
| `overlay` | `#1C1D24` | Popover / menu / tooltip / modal body (only surface allowed a shadow) |
| `border` | `#1F2026` | Panel-to-panel dividers, table borders |
| `borderSubtle` | `#17181D` | Inner dividers (tree indent guides, grouped-field separators) |
| `borderStrong` | `#2A2C35` | Hover/pressed border emphasis (non-focus) |

**Text**

| Token | Hex | Role | Contrast on `panel` |
|---|---|---|---|
| `text` | `#E4E4E7` | Primary content, values | 15.2:1 |
| `textDim` | `#A1A1AA` | Secondary labels, column headers | 7.5:1 |
| `textFaint` | `#6B6B76` | Timestamps, disabled labels, idle-state marker | 3.7:1 |
| `textOnAccent` | `#FFFFFF` | Text/icons on solid accent fill | — |

**Accent (single brand mark)**

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `accent` | `#8B5CF6` | Focus ring, selection fill edge, tab underline, icon marks | 4.6:1 on `panel` |
| `accentSolid` | `#7C4EEB` | Primary button fill (deepened so white text clears AA) | 5.1:1 with white |
| `accentSolidHover` | `#6D3FD9` | Primary button hover | 6.2:1 with white |
| `accentSolidActive` | `#5F34C4` | Primary button pressed | 7.6:1 with white |
| `accentMutedBg` | `#1C1732` | Selected list/tree row background | 13.6:1 for `text` on top |

**Solver / validation state colors** — five solid hues, each with a dedicated tinted background for pill/banner fills. See §3.3 for the full semantics and rationale.

| State | Solid | Tinted bg | Contrast (solid on tinted bg) |
|---|---|---|---|
| Idle | `#6B6B76` (`textFaint`) | — (no fill, outline only) | 3.7:1 on `panel` |
| Running | `#3B82F6` | `#0F1C33` | 4.6:1 |
| Converged / OK | `#61BD6D` | `#142A18` | 6.6:1 |
| Warning | `#D9A441` | `#2E2410` | 6.8:1 |
| Error / Failed | `#E05C56` | `#341614` | 4.6:1 |

```css
:root {
  --bg: #0A0B0E;
  --panel: #0D0E12;
  --panel-alt: #111217;
  --panel-raised: #16171D;
  --overlay: #1C1D24;
  --border: #1F2026;
  --border-subtle: #17181D;
  --border-strong: #2A2C35;
  --text: #E4E4E7;
  --text-dim: #A1A1AA;
  --text-faint: #6B6B76;
  --text-on-accent: #FFFFFF;
  --accent: #8B5CF6;
  --accent-solid: #7C4EEB;
  --accent-solid-hover: #6D3FD9;
  --accent-solid-active: #5F34C4;
  --accent-muted-bg: #1C1732;
  --state-idle: #6B6B76;
  --state-running: #3B82F6;
  --state-running-bg: #0F1C33;
  --state-ok: #61BD6D;
  --state-ok-bg: #142A18;
  --state-warning: #D9A441;
  --state-warning-bg: #2E2410;
  --state-error: #E05C56;
  --state-error-bg: #341614;
}
```

### 3.2 Light mode (secondary)

Light mode exists for daylight lab environments and screenshots/documentation, but dark is the default and the mode every state color above was tuned for. Structure mirrors dark mode 1:1 — same token names, no new roles.

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `bg` | `#F4F4F6` | Canvas | — |
| `panel` | `#FFFFFF` | Panel body | — |
| `panelAlt` | `#FAFAFB` | Inset wells / alt rows | — |
| `panelRaised` | `#EEEEF1` | Headers / toolbars / hovered rows | — |
| `border` | `#D8D8DD` | Dividers | 1.4:1 vs `panelAlt` (structural, not text) |
| `borderSubtle` | `#E6E6EA` | Inner dividers | — |
| `text` | `#1C1D22` | Primary text | 15.3:1 on `bg` |
| `textDim` | `#55565F` | Secondary | 7.3:1 on `panel` |
| `textFaint` | `#85868F` | Tertiary | 3.6:1 on `panel` |
| `accent` | `#7C3AED` | Mark color | 5.7:1 on `panel` |
| `accentSolid` | `#7C3AED` | Button fill | 5.7:1 with white text |
| `accentSolidHover` | `#6C2BDC` | Button hover | 7.0:1 with white text |
| `state-running` | `#1D4EB8` | Running | 6.7:1 on white |
| `state-ok` | `#15803D` | Converged | 5.0:1 on white |
| `state-warning` | `#92620A` | Warning | 5.3:1 on white |
| `state-error` | `#B91C1C` | Error | 6.5:1 on white |

Light-mode state background tints follow the same recipe as dark (≈10–15% fill of the solid hue over `panelAlt`).

### 3.3 Solver / validation state semantics

This is the highest-stakes color decision in the system: PyTCAD runs long out-of-process solves, and every one of the states below must be identifiable **without reading the label text**, at a glance, at panel-thumbnail scale.

| State | Signal | Motion | Distinguishing device |
|---|---|---|---|
| **Idle** | Neutral gray dot, outline pill (no fill) | None | The *only* state with no fill and no hue — absence of color is itself the signal ("nothing has happened yet") |
| **Running** | Solid blue dot, filled pill | Dot opacity breathes 100%→55%→100%, 1.4s ease-in-out, infinite (§8) | The one state permitted a loop — it is reporting a literally ongoing background process, not decorating |
| **Converged / OK** | Solid green dot, filled pill | One-shot 200ms flash on transition into this state, then static | Green is used nowhere else in the system |
| **Warning** | Solid amber dot, filled pill, triangle glyph | None (static) | Triangle glyph — never shares a shape with error |
| **Failed / Error** | Solid red dot, filled pill, octagon/x glyph | None (static) | Octagon glyph — distinguishes from warning even for red/green colorblind users |
| **Stale** | *Modifier*, not a hue — dashed 1px outline overlaid on whatever the last real state was, plus a small refresh glyph | None | Stale is orthogonal to outcome: a converged result can go stale the moment upstream structure changes. Encoding it as a pattern (dashed border), not a sixth color, keeps the five solver hues from crowding into indistinguishable territory. **Not yet built** — today, stale conditions (e.g. `FamilySweepController.isStale`) use the `warning` color directly rather than a dashed modifier; the dashed-overlay treatment is future work, tracked here rather than silently dropped. |

Non-solver interaction states (selected / disabled / hover / focus) are defined per-component in §9 and never reuse a solver hue — `accent` (violet) is categorically different from any solver state, so a selected row and a converged row are never confusable.

## 4. Typography

No display face. This is a deliberate reading of the charter's "a single type family is appropriate only for utilitarian or data-dense briefs" exception — TCAD panel chrome has no headline moments, so the two-family split is **sans for labels/chrome vs. mono for numeric/scientific data**, not sans vs. serif-display.

```css
--font-sans: "Inter", "Segoe UI", -apple-system, system-ui, sans-serif; /* labels, chrome, prose */
--font-mono: "JetBrains Mono", "SF Mono", "Cascadia Mono", Consolas, ui-monospace, monospace; /* all numeric/scientific data */
```

**Rule: any value that came out of the solver, a mesh, or a field the user types a number into is set in mono. Everything else — labels, menu items, panel titles, button text, tree/list primary text — is sans.**

`gui/qml/Theme.qml` currently ships `Theme.mono` as `"DejaVu Sans Mono", "Consolas", monospace` and `Theme.family` as `"Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif` — functionally the same split this section specifies (JetBrains Mono is not bundled; DejaVu Sans Mono is an acceptable system-available substitute with the same "unambiguous digits" property). No change made to those two tokens in this pass.

| Role | Size | Weight | Line-height | Family | Use |
|---|---|---|---|---|---|
| Micro | 10px | 600, uppercase, 0.06em tracking | 1.0 | Sans | Status pill labels, unit suffixes, column header caps |
| Label | 11px | 500 | 1.2 | Sans | Field labels, tree/list secondary text, tooltips |
| Body | 12px | 400 | 1.4 | Sans | Default UI text, menu items, dialog copy |
| Body Strong | 12px | 600 | 1.4 | Sans | Active tab label, selected row, emphasized body |
| Data | 12px | 400 | 1.0 | Mono | Table cells, numeric field values |
| Data Large | 13px | 500 | 1.0 | Mono | Key readouts — residual value, primary result metric |
| Subhead | 13px | 600, uppercase, 0.04em tracking | 1.2 | Sans | Panel section headers |
| Title | 14px | 600 | 1.2 | Sans | Dock/panel titles, dialog titles |
| App Title | 16px | 600 | 1.2 | Sans | Top window bar only — the largest text anywhere in PyTCAD |

16px is the system's ceiling. There is no 18/24/32px anywhere — enforced explicitly in §11.

## 5. Spacing

Eight-step strict scale, 2px floor. Rows and controls are built from the small end (`xs`–`lg`); only section-level gaps ever reach `2xl`/`3xl`.

| Token | Value | `Theme.qml` equivalent | Typical use |
|---|---|---|---|
| `space-2xs` | 2px | *(new — not yet in Theme.qml)* | Icon-to-label gap, dot-to-text gap in pills |
| `space-xs` | 4px | `padXs` | Row vertical padding, tight control internal padding |
| `space-sm` | 6px | `padSm` | List/tree row vertical padding |
| `space-md` | 8px | `pad` | Field/control horizontal padding, standard row gap |
| `space-lg` | 12px | `padLg` | Panel internal padding, control group gap |
| `space-xl` | 16px | `padXl` | Panel header padding, dialog padding |
| `space-2xl` | 24px | *(new — not yet in Theme.qml)* | Section gap within a panel |
| `space-3xl` | 32px | *(new — not yet in Theme.qml)* | Top-level layout gutters only (rare) |

`Theme.qml`'s existing `padXs/padSm/pad/padLg/padXl` scale already matches this 1:1 in value; `space-2xs/2xl/3xl` are net-new steps this pass did not add (no current call site needs them yet — add on first real use rather than speculatively).

## 6. Radius

Three steps, capped at 3px. Radius is used to distinguish *floating* surfaces from *docked* ones — it is never a decorative softness applied uniformly.

| Token | Value | `Theme.qml` equivalent | Applies to | Why |
|---|---|---|---|---|
| `radius-0` | 0px | *(use `0` directly)* | Panels, docks, toolbars, tables, list/tree containers | Docked chrome is structural, not a "card" — sharp corners read as an instrument surface |
| `radius-xs` | 2px | *(new — not yet in Theme.qml)* | Buttons, inputs, spin/combo boxes, pills, tabs | Just enough softness for a control to read as clickable without becoming rounded-card decoration |
| `radius-sm` | 3px | `radiusSm` / `radius` | Popovers, context menus, tooltips, modal dialogs, and (applied in this pass) stat tiles/tab pills | The primary "just barely rounded" step already in `Theme.qml`; reused for docked micro-surfaces in this pass rather than adding a fourth token for the same 3px value |

`radiusLg` (6px) and `radiusCard` (10px) remain defined in `Theme.qml` for compatibility and for the future overlay layer (`radiusCard`) — this pass moved every docked-surface call site this audit found (`MeshPanel.qml`'s stat tiles, `Main.qml`'s tab background) from `radiusLg`/`radiusCard` down to `radiusSm` or `0`. A handful of icon-button and toolbar `radiusSm`-already values were left untouched since they already complied.

## 7. Elevation / Depth

No drop-shadow cards. Depth is communicated by **border + luminance step** for every docked surface; shadow is reserved exclusively for the transient overlay layer.

| Level | Token | Hex (dark) | Surface |
|---|---|---|---|
| 0 | `bg` | `#0A0B0E` | Viewport / canvas — always the darkest, most contrast-reserved surface |
| 1 | `panel` | `#0D0E12` | Docked panel body |
| 2 | `panelAlt` | `#111217` | Inset well, alternating row, nested group |
| 3 | `panelRaised` | `#16171D` | Panel header, toolbar, hovered row, active tab strip |
| 4 (overlay only) | `overlay` / `cardBg` | `#1C1D24` (spec) / `#16171D` (current `Theme.cardBg`, unchanged) | Popover, context menu, tooltip, modal — the one level with a shadow |

```css
--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.45);
```

Justification for keeping this single shadow: a context menu or dropdown list genuinely renders on top of app content and can occlude it — the shadow disambiguates "this is a layer above the app" from "this is another docked panel," which a border alone can't do when the overlay sits directly on top of similarly-colored chrome. No other surface qualifies; a docked properties panel never occludes anything, so it never needs one.

`Theme.qml` keeps its existing `cardBg`/`cardBorder`/`cardShadow` values as the de facto `overlay` role (a dedicated `overlay` token distinct from `cardBg` was not added in this pass, to avoid a second near-duplicate near-black hex with no current consumer — PyTCAD has no popover/menu/modal component yet that would use it). Add a distinct `overlay` token when the first real overlay component is built, rather than now.

## 8. Motion

Motion is a state signal, never delight. Durations are short; only one animation loops.

| Interaction | Duration | Easing | Notes |
|---|---|---|---|
| Hover (bg/border shift) | 80ms | ease-out | Buttons, rows, tabs |
| Focus ring appear | 80ms | ease-out | Near-instant — focus must never feel laggy |
| Selection change | 100ms | ease-out | Row/tab/tree background fill |
| Validation banner appear | 100ms | ease-out | 4px slide-down, draws the eye once |
| Panel show/hide (dock collapse) | 120ms | ease-out | Opacity + height; instant is an acceptable default too |
| Progress bar fill | 150ms | linear | Tracks real solver progress ticks — never eased for "smoothness" |
| Converged/failed one-shot flash | 200ms | ease-out | Background flashes once on transition into the new state, then holds static |
| **Running-state pulse** | **1.4s** | **ease-in-out, infinite** | **The only looping animation in the system.** Dot opacity 100%→55%→100%. It reports a literally ongoing background process (a solver is actively computing) — this is exactly the "state transition," not decoration, the charter permits |

**Explicitly no motion on:** tab content swap (instant), splitter/dock drag (1:1 with pointer, no inertia/easing), window resize, table/tree scroll, list row insertion/removal (appears/disappears instantly — a flash-then-static acknowledgement is enough, no slide/bounce).

`Theme.qml`'s existing `animFast`(110ms)/`animMed`(200ms)/`animSlow`(360ms) durations are close to but not identical to this scale (`motion-fast`80/`motion-base`100/`motion-slow`150). Left unchanged in this pass — every current color/hover `Behavior` in the codebase already uses `Theme.animFast`, and retuning it is a value-only follow-up, not a token-shape change. A dedicated pulse component (`RunningPulse.qml`) implementing the one sanctioned loop is **not yet built** — `StatusIndicator.qml`'s existing busy-dot pulse (`SequentialAnimation` on `opacity`, 800ms) already does the "infinite loop only for busy" job; retuning its duration to 1.4s and factoring it into a shared component is follow-up work, not done in this pass.

**The one sanctioned gradient:**

```css
--gradient-progress: linear-gradient(90deg, #8B5CF6 0%, #3B82F6 100%);
```

Reserved for exactly one future use: a determinate solve-progress bar fill. PyTCAD has no determinate progress bar today (`BusyOverlay.qml` is indeterminate-only) — this pass removed the gradient from the one place it *was* wired up (the tab indicator, `Main.qml`) and did not add a new progress-bar component. `Theme.accentGradientStart`/`accentGradientEnd` remain defined in `Theme.qml`, unused until that component exists.

## 9. Component Inventory

Every component defines default/hover/focus/selected/disabled/error as applicable. `accentMutedBg` (`#1C1732`) is reused for every "selected" treatment across list, tree, and tab so selection reads as one consistent language app-wide. **Status:** the states below are the target spec for each component; this pass corrected the token *values* consumed by PyTCAD's existing components (see §2) but did not rebuild every component from scratch into dedicated `.qml` types with the full state matrix below — that is the natural next phase, tracked here rather than silently implied as finished.

### Panel Header
- **Default:** `panelRaised` bg, `borderSubtle` bottom border, `subhead` label (uppercase, `textDim`), optional right-aligned icon buttons, height 28px.
- **Hover:** only the icon buttons respond (see Button, icon variant); the header bar itself is static.
- **Collapsed:** chevron rotates -90°, no other change; instant, no easing needed at this scale.

### Text Field (numeric)
- **Default:** `panelAlt` bg, 1px `border`, `data` (mono) value, right-aligned unit suffix in `textFaint` micro size, height 22–24px, `radius-xs`.
- **Hover:** border → `borderStrong`.
- **Focus:** border → `accent`, 2px outer focus ring (`accent` @ 55% opacity), bg unchanged.
- **Disabled:** opacity 45%, border removed, bg → `panel`.
- **Error:** border → `state-error`, small octagon glyph right-aligned before the unit suffix; error persists visually until the field is corrected, not just on blur.
- **Read-only:** no border, bg → transparent, value stays mono/full-contrast (read-only is not the same as disabled).

### Combo Box
- **Default:** identical shell to text field, value in `body`/sans (it's a choice, not raw data) + chevron icon (`textDim`).
- **Hover:** border → `borderStrong`, chevron → `text`.
- **Focus:** `accent` border + focus ring.
- **Open:** popover uses `overlay` bg, `radius-sm`, `--shadow-overlay`; selected item row uses `accentMutedBg`; hovered item uses `panelRaised`.
- **Disabled:** opacity 45%.

### Spin Box
- Text field shell + stepper column (up/down chevrons), 16px wide, split by a `borderSubtle` hairline from the value field.
- **Stepper default:** icon `textDim`. **Hover:** icon `text`, cell bg `panelRaised`. **Active (pressed):** cell bg `accentMutedBg`, icon `accent`. **Disabled:** stepper hidden entirely (not grayed — removed, since there's nothing to step).

### Button — Primary
- **Default:** `accentSolid` (`#7C4EEB`) fill, `textOnAccent` (white) label, `radius-xs`, height 24–28px, no gradient.
- **Hover:** fill → `accentSolidHover` (`#6D3FD9`) — darkens, not lightens, so white-text contrast only improves (5.1:1 → 6.2:1).
- **Active:** fill → `accentSolidActive` (`#5F34C4`, 7.6:1).
- **Focus:** 2px `accent` ring outside the fill.
- **Disabled:** `panelAlt` fill, `textFaint` label, no border.
- Only one primary button may exist per adjacent group — running a solve, applying a form: one accent-filled action, everything else secondary.
- **Not applied to Run/Stop in this pass:** `MainToolBar.qml`'s Run/Stop buttons use a green/red (`Theme.ok`/`Theme.error`) fill, a pre-existing, intuitive "go/stop" media-control convention distinct from this generic form-submit "primary button" spec. Left as-is deliberately rather than forced into violet — the two conventions serve different purposes and neither the original reskin nor this correction pass ever applied the gradient there in practice (only the Theme.qml header comment claimed it aspirationally).

### Button — Secondary
- **Default:** `panelAlt` bg, 1px `border`, `text` label.
- **Hover:** bg → `panelRaised`, border → `borderStrong`.
- **Focus:** `accent` ring.
- **Active:** bg → `panel` (darker, pressed feel).
- **Disabled:** `textFaint` label, `borderSubtle` border.

### Button — Icon-only
- **Default:** transparent, icon `textDim`, `radius-xs` hit area (24×24px minimum).
- **Hover:** bg → `panelRaised`, icon → `text`.
- **Focus:** `accent` ring.
- **Toggled/active:** bg → `accentMutedBg`, icon → `accent`.
- **Disabled:** icon `textFaint`, no hover response.

### List Row
- **Default:** transparent (inherits panel bg), `text` primary / `textDim` secondary column, height 22px.
- **Hover:** bg → `panelRaised`.
- **Selected:** bg → `accentMutedBg`, 2px `accent` left edge bar, text stays `text` (full contrast — selection never dims text).
- **Focus (keyboard nav):** 1px inset `accent` ring in addition to whatever selection/hover state applies.
- **Disabled/N-A row:** `textFaint`, no hover response.

### Tree Row
- List Row rules + indent guides (`borderSubtle` vertical rules per depth level) + expand/collapse chevron (`textDim`, → `text` on hover). Selection tint spans the full row width regardless of indent depth so it stays legible at any nesting.

### Tab
- **Default:** `textDim` label, no underline, height 28px.
- **Hover:** label → `text` (brightens — never the reverse).
- **Selected/active:** label → `text` + `body-strong` weight, flat 2px `accent` underline (no gradient).
- **Focus:** `accent` ring on the tab hit area.
- **Disabled:** `textFaint`, non-interactive.
- **Applied in this pass** (`Main.qml`'s sidebar `TabBar`): the gradient underline is now a flat `Theme.accent` fill; the checked label color is `Theme.text` + bold instead of the gradient's blue endpoint; the default/hover label uses `Theme.textDim`/`Theme.text`; the selection-pill background radius dropped from `radiusLg` (6px) to `radiusSm` (3px).

### Status Pill / Indicator
- Shape: dot (6px) + `micro` label, `radius-xs` pill container, `space-2xs` internal gap, height 18–20px.
- **Idle:** outline only (`borderStrong` 1px), `textFaint` dot + label, no fill.
- **Running:** `state-running-bg` fill, `state-running` dot (pulsing, §8) + label.
- **Converged:** `state-ok-bg` fill, `state-ok` dot + label, one-shot flash on entry.
- **Warning:** `state-warning-bg` fill, `state-warning` dot + triangle glyph + label.
- **Error:** `state-error-bg` fill, `state-error` dot + octagon glyph + label.
- **Stale (modifier):** dashed 1px outline over whatever pill above applies, small refresh glyph appended — never a standalone color.
- **Not yet built as a dedicated component:** `StatusIndicator.qml` today is four plain dots (busy/result/dirty/error), not this pill shape with glyphs. This pass corrected which *token* each dot uses (dirty → `Theme.warning`, unchanged busy/result/error) without rebuilding it into the pill-with-glyph shape above.

### Validation Banner
Deliberately **not** the "colored left bar + rounded card" pattern — flat, full-width, sharp-cornered, tinted across its entire surface so it can't be mistaken for a decorative accent:
- **Warning:** `state-warning-bg` full fill, 1px `state-warning` top+bottom border (not just left), triangle glyph + `body` message in `text`, warning count badge in `state-warning`, `radius-0`.
- **Error:** same structure in `state-error` / `state-error-bg`, octagon glyph.
- Sits inline, docked to the panel/section it concerns (e.g., bottom of a properties form) — never a floating toast.
- **Applied in this pass** (`ValidationBanner.qml`): now uses `Theme.warning` instead of the ambiguous `Theme.running`. The full tinted-fill/top-and-bottom-border/glyph treatment above is **not yet built** — the component still renders as a solid-color bar without the triangle glyph or count badge.

### Busy / Progress Indicator
- **Determinate** (known % — mesh generation, sweep steps): 4px track (`panelAlt`), `--gradient-progress` fill, `radius-xs`, width transitions 150ms linear.
- **Indeterminate** (unknown duration — most solves): **no spinner, no marquee bar.** The running Status Pill's pulsing dot plus a mono elapsed-time readout (`00:42`) is the sole busy signal — consistent with "no decorative looping animation" beyond the one already-justified pulse.
- **Not yet built:** PyTCAD's `BusyOverlay.qml` is a distinct, pre-existing full-viewport overlay (dimmed backdrop + status text) for the indeterminate case; a determinate progress-fill component using `--gradient-progress` does not exist yet.

### Splitter / Dock
- **Default (resting):** 1px `border` hairline between panels.
- **Hover:** cursor changes to resize; a 2px `accent`-tinted highlight appears only directly under the pointer (not the full splitter length).
- **Dragging:** panel follows the pointer 1:1, no easing, no ghost/shadow preview.
- Qt Quick's built-in `SplitView` (used throughout `Main.qml`) already provides 1:1 pointer-following drag with no easing by default; the accent-tinted hover highlight is **not yet built**.

## 10. Layout Principles

- **Content beats chrome, always.** The viewport/plot/mesh canvas sits at elevation 0 (`bg`, the darkest tone) and gets the highest achievable contrast for its data. Docks, toolbars, and panel headers sit at elevation 1–3 and are deliberately quieter — the eye should land on data first, chrome second.
- **Row height targets:** list/tree row 22px (24px if it hosts an inline control), toolbar 32px, tab strip 28px, input/combo/spin 22–24px, panel header 28px, status bar 24px. These are pointer-precision targets, not touch targets (44px does not apply — PyTCAD assumes mouse/trackpad + keyboard).
- **Panel minimum width:** 220px before a dock collapses to an icon rail; below that, dense forms stop being legible.
- **No ad hoc padding.** Every gap in every component in §9 resolves to a token from §5 — nothing is a bespoke pixel value.
- **Density over whitespace.** Section gaps top out at `space-2xl` (24px); nothing in the chrome layer approaches marketing-page breathing room.

## 11. Do's and Don'ts

| Do | Don't (and why) |
|---|---|
| Separate panels with `border` + a luminance step | Don't wrap panels in shadowed cards — compounds into noise at 6–10 visible panels, reads as consumer SaaS |
| Use `radius-0`/`radius-xs` everywhere docked | Don't use radius > 3px anywhere — 8–16px rounding is the single fastest way to read as a dashboard template, not an instrument |
| Keep sections dense, `space-2xl` as the largest chrome gap | Don't add generous whitespace "for breathing room" — density is the point of this class of tool |
| Cap all text at 16px (`App Title`) | Don't introduce marketing-scale display type — nothing in this app is a headline |
| Animate only real state transitions (§8) | Don't add decorative animation (page-transition slides, bouncy easing, spinners) — motion must always mean something happened |
| Use `--gradient-progress` only on the determinate progress fill | Don't put gradients on tabs, buttons, or backgrounds — a gradient with no data meaning is decoration |
| One `accentSolid` primary button per action group | Don't stack multiple solid buttons for one action — violates the one-primary-CTA rule and confuses "which button actually runs the solve" |
| Give every solver state its own hue + shape glyph (§3.3) | Don't reuse warning's amber for "running" — caution and "healthy activity" must never share a color |
| Encode "stale" as a pattern modifier, not a sixth hue | Don't invent more solver-state colors than five — hue discrimination degrades past five, especially under solver fatigue/low light |
| Give every focusable element a visible `accent` focus ring | Don't rely on hover-only affordance — this app is keyboard-driven as often as mouse-driven |
| Mono for every solved/typed number, sans for every label | Don't mix — a numeric field set in a proportional face invites misreads of digit strings (mesh counts, doping concentrations) |

## 12. QML Mapping Notes

For whoever is next hand-editing `Theme.qml`:

- **Color palette (§3)** → one `QtObject` per role group (`Theme.color.surface.*`, `Theme.color.text.*`, `Theme.color.accent.*`, `Theme.color.state.*`), each leaf a `readonly property color`. Nest state colors as `{fg, bg}` pairs (e.g. `Theme.color.state.running.fg`, `.bg`) so every delegate resolves from one source instead of re-deriving tints locally. **This pass took the flatter, lower-risk path**: state fg/bg pairs were added as flat top-level properties (`Theme.running`, `Theme.runningBg`, `Theme.warning`, `Theme.warningBg`, `Theme.okBg`, `Theme.errorBg`) rather than nesting into a `Theme.color.state.*` sub-object, to avoid a breaking rename of every existing `Theme.running`/`Theme.ok`/`Theme.error` call site in one pass. Nesting into grouped `QtObject`s is a reasonable follow-up refactor, not required for the token *values* to be correct.
- **Typography (§4)** → QML has no single "font token" object; expose paired `readonly property int` for pixel size and weight per scale step (`Theme.type.body.size`, `Theme.type.body.weight`) plus two `readonly property string` family strings (`Theme.font.sans`, `Theme.font.mono`), composed at the call site (`font.family: Theme.font.mono; font.pixelSize: Theme.type.data.size`). **Not yet done** — `Theme.qml` still exposes only `fsTiny`/`fsSmall`/`fsBody`/`fsHeader`/`fsTitle` (no dedicated weight tokens) plus `Theme.mono`/`Theme.family`.
- **Spacing (§5)** → flat `readonly property int` per step under `Theme.spacing.xs/sm/md/lg/xl/xxl/xxxl`, consumed directly in `anchors.margins` and `RowLayout`/`ColumnLayout` `spacing:`. `Theme.qml`'s existing `padXs/padSm/pad/padLg/padXl` already is this scale under different names; add `space2xl`/`space3xl` on first real use.
- **Radius (§6)** → three `readonly property int radius0/radiusXs/radiusSm` on `Theme`, applied to `Rectangle.radius`; nothing else needed since the scale is intentionally this small. `Theme.qml` already has `radiusSm`/`radius` (both 3px); add a distinct 2px `radiusXs` when a call site actually needs to distinguish it from `radiusSm`.
- **Elevation (§7)** → expose the four surface hexes as `Theme.color.surface.level0..level3` (or `bg/panel/panelAlt/panelRaised`, which is what `Theme.qml` already has) plus one `Theme.shadow.overlay` object (`color`, `blurRadius`, `verticalOffset`) consumed only by the popup/menu/dialog delegate — never by an ordinary `Panel.qml`. `Theme.cardShadow` already exists as a flat color; a structured shadow object is future work once a real overlay component exists.
- **Motion (§8)** → `readonly property int durationFast/durationBase/durationSlow/durationPanel` plus a shared easing curve constant; the running-state pulse should live in exactly one reusable component (e.g. `RunningPulse.qml`, a `SequentialAnimation` on `opacity`) referenced by the `StatusPill` delegate rather than re-implemented per usage site. `Theme.qml`'s `animFast/animMed/animSlow` already serve this role under different names; `RunningPulse.qml` is not yet extracted (the pulse lives inline in `StatusIndicator.qml`).
- **Component states (§9)** → give each entry its own QML type (`StatusPill.qml`, `NumericField.qml`, `TreeRow.qml`…) exposing a `property string uiState` (or a `solverState` enum for pill/banner types) driving a `states: [ State { name: "hover"; ... } ]` block that reads exclusively from `Theme` — never a locally hard-coded hex. **Not yet built** — see the "Not yet built"/"Applied in this pass" notes per component in §9.
- **Solver-state semantics (§3.3)** → a single `Theme.state` grouping keyed by name (`idle/running/ok/warning/error`) each holding its `{dot, bg, glyph}` triplet, plus a separate `Theme.state.staleOverlay` (dash pattern + refresh glyph) applied as a modifier on top, matching the "pattern, not a sixth hue" rule. **Partially applied**: the fg/bg color pairs exist (flat, per the note above); glyphs and the stale dashed-overlay modifier are not yet built — `isStale`/rejected-attempt call sites use the flat `warning` color today.
