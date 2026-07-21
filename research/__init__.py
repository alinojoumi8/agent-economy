"""Offline-first dataset, scenario, and paired counterfactual tooling."""
"""Deterministic research, hashing, and export helpers."""

from .hashing import canonical_hashes, canonical_projection_hash, verify_hash_contract

__all__ = ["canonical_hashes", "canonical_projection_hash", "verify_hash_contract"]
