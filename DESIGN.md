---
name: Agent Economy — Civic Weather Room
description: A living economic city rendered as a precise, evidence-linked civic science instrument.
colors:
  survey-navy: "#12233F"
  blueprint-cobalt: "#2457D6"
  signal-vermilion: "#E44732"
  field-chartreuse: "#B7D64A"
  instrument-cyan: "#48AEB0"
  cool-chart-paper: "#EEF2F0"
  porcelain-white: "#FAFCFA"
  slate-ink: "#263A53"
  survey-gray: "#586878"
  rule-gray: "#C8D0D3"
typography:
  display:
    fontFamily: "Bahnschrift SemiCondensed, Arial Narrow, sans-serif"
    fontSize: "clamp(2.1rem, 4.1vw, 4.5rem)"
    fontWeight: 620
    lineHeight: 0.88
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Bahnschrift SemiCondensed, Arial Narrow, sans-serif"
    fontSize: "clamp(1.65rem, 3vw, 2.55rem)"
    fontWeight: 620
    lineHeight: 1
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Segoe UI Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Cascadia Code, SFMono-Regular, Consolas, monospace"
    fontSize: "0.58rem"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "0.08em"
rounded:
  control: "3px"
  panel: "8px"
  major-field: "12px"
spacing:
  base: "4px"
  control: "8px"
  instrument: "16px"
  field: "24px"
components:
  button-primary:
    backgroundColor: "{colors.blueprint-cobalt}"
    textColor: "{colors.porcelain-white}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "39px"
  button-primary-hover:
    backgroundColor: "#1848BC"
    textColor: "{colors.porcelain-white}"
    rounded: "{rounded.control}"
  field:
    backgroundColor: "{colors.porcelain-white}"
    textColor: "{colors.survey-navy}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  nav-active:
    backgroundColor: "{colors.field-chartreuse}"
    textColor: "{colors.survey-navy}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  instrument-panel:
    backgroundColor: "{colors.porcelain-white}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.panel}"
    padding: "16px"
---

# Design System: Agent Economy — Civic Weather Room

## Overview

**Creative North Star: "The Civic Weather Room"**

Agent Economy should feel like a daylit municipal observatory built to read a
living city: cool chart paper, powder-coated instrument housings, cadastral ink,
translucent acetate overlays, and saturated signals that mean something
specific. The city is not scenery. It is a spatial index into agents,
institutions, communications, transactions, and their evidence.

The system pairs a large cartographic field with compact operating instruments.
Dense information is organized by survey lines, numbered coordinates,
districts, and evidence transects rather than repeated dashboard cards. Motion
behaves like a scientific display: fronts reform, paths advance, and markers
change state only when underlying data changes.

**Key Characteristics:**

- A cool, daylit field with large navy and cobalt cartographic regions.
- Signal colors reserved for distinct, named data states.
- Survey grids, registration marks, contour lines, and acetate layers.
- A spatial city overview that always leads to inspectable evidence.
- Compact civic typography with highly legible tables and labels.
- Purposeful, synchronized motion with a complete reduced-motion equivalent.

## Colors

The palette uses a Full Palette strategy: cool municipal neutrals carry long
operator sessions, while three saturated inks own whole data roles instead of
appearing as decorative accents.

### Primary

- **Survey Navy** (`#12233F`): primary ink, navigation fields, map depth, and
  high-trust controls.
- **Blueprint Cobalt** (`#2457D6`): selected routes, active evidence links, and
  the current investigative focus.

### Secondary

- **Signal Vermilion** (`#E44732`): alerts, rejected actions, failed invariants,
  and conditions requiring intervention.
- **Field Chartreuse** (`#B7D64A`): verified live work, healthy flows, completed
  settlement, and positive system health.

### Tertiary

- **Instrument Cyan** (`#48AEB0`): communications, provider activity, and
  secondary live movement.

### Neutral

- **Cool Chart Paper** (`#EEF2F0`): the default daylit workspace ground.
- **Porcelain White** (`#FAFCFA`): tables, inspectors, and readable instruments.
- **Slate Ink** (`#263A53`): body copy and dense labels.
- **Survey Gray** (`#586878`): secondary copy and inactive states.
- **Rule Gray** (`#C8D0D3`): measured dividers, grid lines, and registration
  marks.

**The Named Signal Rule.** A saturated color must map to a documented state or
data family. No rainbow decoration and no arbitrary recoloring.

**The Field Ownership Rule.** Color appears in decisive regions, routes, and
marks. It is not scattered as interchangeable accent chips.

## Typography

**Display Font:** Bahnschrift SemiCondensed (with DIN Alternate and Arial Narrow
fallbacks)

**Body Font:** Segoe UI Variable (with Segoe UI and system UI fallbacks)

**Label/Mono Font:** Cascadia Code (with SFMono-Regular and Consolas fallbacks)

**Character:** Condensed civic signage gives workspaces and districts an
institutional voice; the body face remains calm and highly readable; monospaced
type is reserved for coordinates, ticks, identifiers, provider telemetry, and
evidence provenance.

### Hierarchy

- **Display** (620, fluid 2.1–4.5rem, 0.88): the city title and first-surface
  civic statements,
  never routine card headings.
- **Headline** (620, fluid 1.65–2.55rem, 1): workspace and inspector titles.
- **Title** (650, 0.9–1.15rem, 1.2): instruments, agents, firms, and events.
- **Body** (400–520, 0.78–1rem, 1.55): explanations and evidence summaries,
  generally capped near 70 characters per line.
- **Label** (600, 0.62–0.72rem, tracked uppercase): survey coordinates, states,
  field legends, and control labels.

**The Two-Language Rule.** Condensed type names the civic world; mono type
proves its coordinates and provenance. Body text does neither job.

## Layout

The dominant spatial model is a surveyed field plus instruments. On wide
screens the live city owns roughly two thirds of the first viewport and the
evidence/activity instrument owns the remaining third. The navigation is a
stable civic index, not a stack of promotional cards. Secondary workspaces use
wide ledgers, transects, and split views aligned to the same survey grid.

Large surfaces may touch or overlap like chart sheets and acetate layers.
Spacing follows a compact 4px base with 8px controls, 16px instruments, and
24px field changes. The World OS rail is 252px wide. The live atlas and evidence
lens use a 2.05fr / 0.78fr split with a 650px minimum working height. Dense
sections earn quiet margins; every heading has more space above it than below.

At 980px and below the evidence instrument moves beneath the atlas while the
selection persists. At 760px and below controls become stacked corridors and
the atlas keeps at least 570px of height; at 460px it keeps 520px. On phones the
reading order is district overview, selected agent, current activity, then
evidence. The full city is never shrunk into an illegible thumbnail.

## Elevation & Depth

Depth comes from material stacking: cool paper below, translucent acetate data
layers over the city, and powder-coated instruments above them. Surfaces are
flat and divided by rules; the implemented city, panels, rail, top bar, and
fields use no resting box shadow. Selected agent marks gain concentric rules,
while dialogs may use a backdrop because they genuinely overlay the field.

**The Measured Depth Rule.** If an element cannot move, overlay, or receive
focus, it should not float.

## Shapes

The form language is rectilinear and surveyed. Major fields have square or
subtly eased corners; tabs and legends may use clipped corners inspired by
map-sheet indexing. Circular forms are reserved for agent markers, measured
pressure fields, and status beacons. Decorative pill containers are avoided.

Lines carry hierarchy: hairline survey rules, heavier district boundaries, and
bold active transects. Controls use measured 3px corners, instruments use 8px
corners, and the major city field uses 12px corners. The mast and firm
footprints use clipped survey-plate corners. Shapes should look plotted,
stamped, folded, or mounted, not inflated.

## Components

### Buttons

- **Shape:** Compact plotted controls with 3px corners and a minimum 39px
  primary action height.
- **Primary:** Blueprint Cobalt field with Porcelain White text and 12px
  horizontal padding.
- **Hover / Focus:** Primary darkens to its implemented pressed blue; secondary
  controls move onto a cool-paper field. All controls use the global visible
  cobalt focus ring.
- **Disabled:** Opacity is reduced to 38–45% and the pointer changes to
  not-allowed; controls never disappear while unavailable.

### Fields

- **Style:** White field, Rule Gray stroke, Survey Navy text, 3px corners, and
  compact 8px by 12px internal space.
- **Focus:** The global 2px Blueprint Cobalt outline sits 3px outside the field.
- **Search:** Search can combine with city layers and committed-event filtering;
  the empty state offers a complete reset.

### Navigation

- **Desktop:** A stable Survey Navy civic rail. The selected workspace owns a
  full Field Chartreuse region with Survey Navy icon and copy.
- **Hover / Focus:** Unselected routes gain a quiet white wash; selected routes
  use Vermilion only as the small route indicator.
- **Mobile:** The rail becomes a horizontal workspace index. The brand mark and
  navigation remain visible while captions yield before icons or targets.

### Instrument Panels

- **Shape:** Porcelain White with a 1px Rule Gray boundary and 8px corners.
- **Hierarchy:** Panels are joined by rules and aligned columns, not separated
  into equal promotional cards.
- **States:** Loading, error, empty, selected, stale, historical, and disabled
  states retain their own text treatment; color is always paired with wording.

### Civic City

The signature component is a code-native surveyed atlas with named districts,
firm footprints, keyboard-reachable agent marks, a selected evidence transect,
layer controls, search, and a contiguous instrumentation rail. On desktop, the
evidence lens is a bounded inspector overlay on the atlas; below 980px, the
selected mark surfaces in an immediate map action that leads to the full lens.
Actor-linked transects end in directional arrowheads. Markers pulse only when a
recent committed event exposes an actor identifier. Runs without coordinates
use deterministic role-based placement and say **Derived civic layout** in both
the atlas and evidence lens. Historical views disclose that events are
tick-resolved while entity rosters come from current endpoints.

### Identity Mark

The generated World OS emblem is a clipped municipal survey plate containing
the four signal roles. It is rendered from
`dashboard/src/assets/world-os-emblem.png`; text remains live HTML beside it,
never rasterized into the asset.

## Do's and Don'ts

### Do:

- **Do** let the city or investigative field own the composition.
- **Do** make every live mark keyboard reachable and connect it to a readable
  inspector or table row.
- **Do** distinguish observed, derived, inferred, stale, and synthetic layout
  states in both text and form.
- **Do** use synchronized transitions that reveal a change in world state.
- **Do** keep dense data aligned to stable columns, coordinates, and legends.

### Don't:

- **Don't** turn the world into an isometric game, reward loop, or decorative
  agent aquarium.
- **Don't** use generic dark-SaaS glass panels, neon glows, or interchangeable
  metric-card grids.
- **Don't** imply geographic precision when a run exposes no coordinates;
  derived layouts must say so.
- **Don't** use motion or color as the only expression of state.
- **Don't** place rasterized text or controls inside generated imagery.
