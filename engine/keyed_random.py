"""Versioned, stateless demographic draws independent of cohort/order changes."""
from __future__ import annotations

import hashlib
import json


def demographic_draw(seed: int, mechanism: str, tick: int, agent_id: int) -> float:
    """One 53-bit uniform draw per seed/mechanism/day/person; never uses hash()."""
    key = json.dumps(["demography_v1", int(seed), mechanism, int(tick), int(agent_id)],
                     ensure_ascii=True, separators=(",", ":")).encode("ascii")
    bits = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 11
    return bits / (1 << 53)
