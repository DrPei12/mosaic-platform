# MOSAIC model-workspace redesign analysis

These references translate the supplied Bailian playground screens into the
existing MOSAIC product and real API contracts. They are the visual source of
truth for the text, image, video and audio workspaces.

## Shared frame

- Keep the existing 240 px MOSAIC navigation rail; do not import Bailian's
  unrelated product navigation.
- Model workspaces use a route-aware task frame: 64 px contextual header,
  40-44 px pale-blue billing notice, then one open white canvas.
- Maximum primary interaction width is 880-960 px. The page should feel sparse,
  but all core controls remain visible at a 1366 x 768 laptop viewport.
- Palette: white canvas, `#151823` ink, cool gray muted surfaces, hairline
  borders, existing MOSAIC cobalt accent. No decorative gradients or glass.
- Containers use 10-12 px radius, with one restrained focus shadow on the main
  composer. Avoid nested cards and repeated status pills.

## Text workspace

- Remove the permanent desktop conversation column. Conversation history
  remains available from one header button and the existing accessible dialog.
- Empty state: centered model heading and large composer in the first viewport.
- Active state: 760-880 px message rail, understated avatars, open text rows,
  thin dividers, copy/regenerate actions, and a sticky/floating composer.
- Preserve all current SSE resume, stop, regenerate, draft and route-race
  semantics. The redesign is presentation-only.

## Image workspace

- Center the model heading and one prompt composer.
- Current backend supports prompt, output size and count. A reference-image
  tile may be visible only as disabled/future capability; it must not imply a
  working upload.
- Below the composer, use four fixed-aspect inspiration tiles and a direct link
  to generation history. Inspiration content never substitutes a generated
  result.

## Video workspace

- Center the heading and a single wide composer with the real controls:
  resolution, aspect ratio and duration.
- A reference-media tile is explicitly marked `即将支持` because the current
  route is text-to-video.
- Use a compact four-tile inspiration row instead of the old form-card layout.

## Audio workspace

- Use a two-column desktop editor: large text input on the left, voice/language
  selection on the right; stack on smaller screens.
- Default to the verified `Cherry` voice and `Chinese` language. Do not invent
  additional selectable voices.
- A recent-output row may show only data returned by the real generation API;
  otherwise link to history rather than rendering a fake waveform result.

## Responsive and accessibility

- Desktop keeps the global navigation rail. Tablet/mobile uses the existing
  accessible navigation dialog and bottom navigation.
- Task headers and notice bars must wrap rather than overflow.
- Every input retains a visible label or accessible name; status changes remain
  live regions; all targets remain at least 44 px.
- Reduced motion remains functional and the first viewport cannot depend on
  hover.

## Generated references

- `text-empty.png`
- `text-active.png`
- `image-studio.png`
- `video-studio.png`
- `audio-studio.png`
