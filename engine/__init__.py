"""Deterministic economic engine: ledger, markets, credit, firms, lifecycle.

Nothing in this package calls an LLM. The engine *disposes*: it validates and
applies structured actions proposed elsewhere, and it owns every number in the
simulation (all money is integer cents, all randomness comes from one seeded PRNG).
"""
