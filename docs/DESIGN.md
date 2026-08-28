# MOSAIC Design System

MOSAIC uses the **Editorial Instrument** direction: a bright, editorial, precise
tool for professional creators and internal decision-makers. The interface
should feel like a mature product surface, not a generic AI landing-page
template.

## Source of truth

The machine-readable source of truth is
[`packages/design-tokens/src/tokens.json`](../packages/design-tokens/src/tokens.json).
The package exports typed tokens from `src/index.ts` and generated CSS from
`src/tokens.css`. Do not hand-edit the CSS output. Run:

```sh
pnpm --filter @mosaic/design-tokens generate
pnpm --filter @mosaic/design-tokens check
```

Every color, radius, motion value, type size, line height, spacing value, grid
dimension, border width, focus dimension, layout dimension, and breakpoint used
by the web app must come from this package or from a component-level semantic
mapping that is traceable to it. MOSAIC is a centralized development brand;
components must not hard-code or independently redefine the brand name.

## Color

The palette is intentionally restrained. `accent` is the only brand emphasis;
the other semantic colors communicate state and must not become decorative
secondary accents.

| Token | Value | Use |
| --- | --- | --- |
| `color.canvas` | `#F5F6F8` | Page canvas |
| `color.surface` | `#FFFFFF` | Primary surfaces |
| `color.surfaceMuted` | `#ECEFF3` | Secondary regions and quiet controls |
| `color.ink` | `#15171A` | Primary text |
| `color.inkMuted` | `#667085` | Supporting text |
| `color.line` | `#D7DCE3` | Borders and separators |
| `color.accent` | `#2F5BEA` | Primary action and brand emphasis |
| `color.danger` | `#C63C45` | Errors and destructive states only |
| `color.warning` | `#A66616` | Warnings only |
| `color.success` | `#227A53` | Success and completion states only |

Do not use a purple/blue gradient as a substitute for the accent. State must
not be conveyed by color alone: pair it with text, an icon, or a meaningful
status label.

## Typography

- Latin text and UI numbers use **Geist Sans**.
- IDs, balances, usage, durations, tokens, and other technical values use
  **Geist Mono** with tabular numerals where comparison matters.
- Chinese text uses **Noto Sans SC**, followed by a system Chinese sans-serif
  fallback.
- Keep display headings to two lines or fewer where the layout allows it.
  Use clear weight contrast and compact tracking instead of novelty type.
- Do not introduce a random serif or display font to manufacture “premium”
  styling.

The type scale is fixed; use the semantic role rather than inventing a nearby
size. Each pair is `font-size / line-height`:

| Token | Size / line height | Semantic use |
| --- | --- | --- |
| `typography.display` | `56px / 64px` | Public hero or major product statement |
| `typography.h1` | `40px / 48px` | Page title |
| `typography.h2` | `30px / 38px` | Major section title |
| `typography.h3` | `22px / 28px` | Card, panel, or workspace heading |
| `typography.body` | `16px / 24px` | Default readable copy and controls |
| `typography.small` | `14px / 20px` | Supporting copy and secondary controls |
| `typography.meta` | `12px / 16px` | Metadata, timestamps, and compact status text |
| `typography.micro` | `11px / 16px` | Dense labels where space is genuinely constrained |

Do not use `micro` for paragraphs, primary actions, or essential error text.
Display and heading roles should preserve the stated line height so hierarchy
and wrapping remain stable across routes.

## Spacing

Spacing uses a 4px base unit. These are the reusable values; compose layouts
from this scale instead of introducing one-off pixel gaps:

| Token | Value | Typical semantic use |
| --- | --- | --- |
| `spacing.4` | `4px` | Icon-to-label or tight internal gap |
| `spacing.8` | `8px` | Control internals and compact lists |
| `spacing.12` | `12px` | Field groups and chip gaps |
| `spacing.16` | `16px` | Default component padding and mobile gutter |
| `spacing.24` | `24px` | Desktop gutter and section grouping |
| `spacing.32` | `32px` | Panel padding and subsection separation |
| `spacing.40` | `40px` | Large component grouping |
| `spacing.48` | `48px` | Section rhythm |
| `spacing.64` | `64px` | Major page separation |
| `spacing.96` | `96px` | Hero and major editorial breathing room |

Use the smallest value that preserves a clear relationship. Repeated spacing
should use the same token on sibling components so the interface reads as a
system rather than a collection of individually tuned cards.

## Shape and material

| Token | Value | Use |
| --- | --- | --- |
| `radius.control` | `8px` | Buttons, inputs, selects, and controls |
| `radius.surface` | `12px` | Cards and primary surfaces |
| `radius.media` | `10px` | Image, video, and audio media frames |
| `radius.pill` | `999px` | Filter chips and intentionally pill-shaped tags |

Use hierarchy through canvas, surface, muted-surface, and line values before
adding elevation. Ordinary cards use a 1px border and surface contrast; avoid
putting every element in a card. Shadows are reserved for overlays and real
layer changes. Do not use outer glows, floating orbs, full-page glassmorphism,
or a dark “cosmic” background.

The border and focus geometry is also tokenized:

- `border.width` is `1px` for ordinary rules, dividers, and card boundaries.
- `focus.ringWidth` is `3px` for keyboard focus rings; use the accent color or
  another high-contrast semantic color as appropriate.
- `focus.offset` is `2px` so the ring remains visually separate from the
  control boundary.

Focus geometry is not a decorative hover treatment. Keep it visible on every
keyboard-operable control, including controls rendered on muted surfaces.

## Layout and responsive rules

| Token | Value | Meaning |
| --- | --- | --- |
| `layout.content` | `1280px` | Maximum readable content width |
| `layout.workspace` | `1440px` | Maximum full workspace width |
| `layout.nav` | `240px` | Expanded navigation rail |
| `layout.compactBreakpoint` | `1024px` | Collapse navigation to compact mode |
| `layout.singleColumnBreakpoint` | `768px` | Collapse asymmetric workspaces to one column |
| `layout.topBarMobile` | `64px` | Mobile shell top bar height |
| `layout.topBarDesktop` | `80px` | Desktop shell and chat header height |
| `layout.mobileBottomNavigation` | `76px` | Mobile bottom navigation content height |
| `layout.conversationColumn` | `328px` | Desktop chat conversation column width |
| `layout.composerPanel` | `104px` | Chat composer panel minimum height |

Responsive class mapping is explicit: Tailwind `md` (`768px`) corresponds to
`layout.singleColumnBreakpoint`, and Tailwind `lg` (`1024px`) corresponds to
`layout.compactBreakpoint`. Keep the AppShell breakpoint contract test aligned
when either token or Tailwind's defaults changes.

The workspace grid is a 12-column grid. Use a `24px` desktop gutter and a
`16px` mobile gutter; these are `grid.columns`, `grid.desktopGutter`, and
`grid.mobileGutter` in the token source. At narrow widths, preserve readable
content and collapse columns intentionally rather than allowing arbitrary
fractional gaps.

The primary desktop review viewports are 1440×900 and 1728×1117. Keep the
navigation rail stable on wide screens and align content to a deliberate grid.
At 1024px and below, navigation becomes compact. At 768px and below, forms
and results use a single-column or explicitly sequenced tab layout; do not
simply squeeze a two-column workspace until it becomes unreadable.

## Motion

The token scale is:

| Token | Value | Use |
| --- | --- | --- |
| `motion.fast` | `180ms` | Immediate controls and feedback |
| `motion.normal` | `240ms` | Standard interaction and state changes |
| `motion.page` | `360ms` | Page or workspace transitions |
| `motion.ease` | `cubic-bezier(0.16, 1, 0.3, 1)` | Shared easing |

Prefer transform and opacity. A hover state may use a small translation,
border emphasis, or a media crop change; do not uniformly scale every card.
Streaming text, job status, and balance changes should animate only when they
represent a real state transition. The generated stylesheet sets every
millisecond duration token to `0ms` under `prefers-reduced-motion: reduce`;
components must preserve a usable static state under that preference.

## Accessibility

- Meet WCAG AA for ordinary text and controls.
- Keep interactive targets at least 44×44px.
- Provide visible, high-contrast focus styles using the 3px ring and 2px offset,
  plus a complete keyboard path for navigation, model selection, message
  sending, and job submission.
- Never rely on color alone for availability, errors, warnings, or job status.
- Preserve readable labels and recovery actions for loading, empty, offline,
  unauthorized, insufficient-balance, timeout, rejected, and failed states.
- Respect reduced motion without hiding content or making state changes
  ambiguous.

## Product-name boundary

These approved product-name strings retain `1.7B`:

- `Qwen3-TTS 1.7B VoiceDesign`
- `Qwen3-TTS 1.7B CustomVoice`
- `Qwen3-TTS 1.7B Base`

In these names, `1.7B` is part of the approved product label. It must not be
turned into a parameter-size badge or a general “model size” filter. Parameter
size, quantization, precision, provider, deployment, license, and date
snapshot are forbidden in user-facing model badges and cards.

## Forbidden AI-template patterns

- Purple/blue AI gradients, glowing neon accents, or a dark cosmic background.
- Repeated three-card rows that treat every capability as the same generic
  feature.
- Full-page glassmorphism, decorative blur, floating spheres, or gratuitous
  3D imagery.
- Unbounded “AI magic” copy, fake product screenshots assembled from empty
  `div`s, or claims of real provider availability in the internal demo.
- Provider IDs, parameter-size badges, quantization labels, or deployment
  details in product-facing UI.
- Uniform card zoom, looping motion without state meaning, or animation that
  cannot be disabled through reduced-motion preferences.

The result should read as a disciplined editorial instrument: quiet surfaces,
clear information hierarchy, one deliberate accent, and stateful interactions
that remain credible when the demo data is replaced by a real API.
