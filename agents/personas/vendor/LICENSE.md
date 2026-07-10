# Vendored persona generation — attribution

The census-based persona-generation *approach* used here is adapted from:

**LLM-Economist** (Karten et al., 2025) — https://github.com/sethkarten/LLM-Economist
License: MIT.

Per TECH-SPEC §15, the design (real occupation/age/income distributions expanded
into LLM-ready personas) is borrowed and re-implemented cleanly in
`persona_gen.py`. Upstream attribution is retained here. This directory holds the
vendored component; per the repository rule, vendored code is not modified in
place elsewhere — it is wrapped by `agents/personas/library.py`.

MIT License text (upstream): https://github.com/sethkarten/LLM-Economist/blob/main/LICENSE
