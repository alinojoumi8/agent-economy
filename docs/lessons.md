# Lessons

## 2026-10-29 — Theme-aware person details

The person details panel combined fixed dark surfaces and muted colors with
theme-dependent text, making the light theme unreadable. Pair surface and text
tokens, then verify rendered contrast in both themes. Include secondary labels,
badges and input placeholders at desktop and phone widths; a build alone does
not catch this failure.
