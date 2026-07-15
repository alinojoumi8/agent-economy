# Persona-generation prior-art attribution

The persona-conditioning approach used here was inspired by **LLM-Economist**
(Karten et al., 2025): https://github.com/sethkarten/LLM-Economist

- Pinned upstream revision: `16dcc9c9e2b28b3b863b16f4425b7f099bdde81a`
- Referenced upstream implementation:
  https://github.com/sethkarten/LLM-Economist/blob/16dcc9c9e2b28b3b863b16f4425b7f099bdde81a/llm_economist/agents/persona_generator.py
- Upstream MIT license at that revision:
  https://github.com/sethkarten/LLM-Economist/blob/16dcc9c9e2b28b3b863b16f4425b7f099bdde81a/LICENSE

Agent Economy independently implements the general sample-then-enrich idea in
`agents/personas/base.py`; no upstream source code is copied or vendored. A
line-level comparison during the public-release audit found no exact shared
non-trivial source lines between the implementations.

The local occupation weights, income medians, age bands, wealth formula, names,
and trait priors are hand-authored synthetic heuristics for fictional simulation
initialization. This base sampler does not use Census, BLS, SCF, or other
microdata and is not empirically representative. The optional R21 initializer
in `research/r21.py` separately overlays pinned SCF/SUSB age, work, income,
liquid-wealth, and firm-size fields while retaining fictional identity and
traits; its source terms and transformations live in the dataset manifest and
repository `NOTICE`.

`agents/personas/library.py` is the stable application-owned boundary and adds
Agent Economy's governed arrival-enrichment contract.
