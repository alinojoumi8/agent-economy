# Lessons

## 2026-10-29 — Theme-aware person details

The person details panel combined fixed dark surfaces and muted colors with
theme-dependent text, making the light theme unreadable. Pair surface and text
tokens, then verify rendered contrast in both themes. Include secondary labels,
badges and input placeholders at desktop and phone widths; a build alone does
not catch this failure.

## 2026-10-29 — Validate recognizable citizens and actual movement

The user wanted StarNet's visibly living characters, but the district preview
retained tiny static citizen markers. Advancing twenty simulation days and
checking navigation did not validate that experience. Review character size at
the default camera and capture a sequence proving both translation and body
animation. Reuse the existing recorded-day presence/playback logic in 3D; do not
treat activity-ring pulses as walking or a running simulation as a visual test.
