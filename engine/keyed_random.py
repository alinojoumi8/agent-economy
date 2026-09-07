"""Versioned, stateless draws; historical demographic keys remain unchanged."""
from __future__ import annotations

import hashlib
import json


DAILY_STREAM_CONTRACT = "mechanism_day_identity_v1"


def stable_key(kind: str, *parts) -> str:
    """An event/person identity independent of unrelated database insertions."""
    payload = json.dumps(["identity_v1", kind, *parts], sort_keys=True,
                         ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return kind + ":" + hashlib.sha256(payload.encode("ascii")).hexdigest()


def daily_seed(seed: int, mechanism: str, tick: int, *identity) -> int:
    """One exactly representable 53-bit seed per mechanism/day/semantic key."""
    payload = json.dumps([DAILY_STREAM_CONTRACT, int(seed), mechanism, int(tick), *identity],
                         sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(payload.encode("ascii")).digest()[:8], "big") >> 11


def daily_draw(seed: int, mechanism: str, tick: int, *identity) -> float:
    """Uniform in [0, 1), without a mutable cursor or Python's process hash()."""
    return daily_seed(seed, mechanism, tick, *identity) / (1 << 53)


def person_key(store, agent_id: int) -> str:
    """Read a recorded origin key; initial/staff identities retain their IDs.

    Birth and arrival keys are recorded in their existing canonical events.
    Do not cache across transactions: a rolled-back insertion can reuse an ID.
    An engine-created staff member without a semantic origin is run-scoped;
    matching the numeric ID alone does not establish a cross-arm counterpart.
    """
    value = store.scalar(
        "SELECT json_extract(payload_json,'$.random_key') FROM events "
        "WHERE subject_type='agent' AND subject_id=? "
        "AND kind IN ('person_registered','birth') "
        "AND json_extract(payload_json,'$.random_key') IS NOT NULL ORDER BY id LIMIT 1",
        (int(agent_id),))
    return str(value) if value is not None else f"agent:{int(agent_id)}"


def policy_seed(economy, mechanism: str, tick: int, agent_id: int, legacy: int, *identity) -> int:
    """Gate call-local policy randomness without changing historical contexts."""
    if economy.engine_semantics_version < 16:
        return legacy
    return daily_seed(int(economy.config.get("seed", 42)), mechanism, tick,
                      person_key(economy.store, agent_id), *identity)


def demographic_draw(seed: int, mechanism: str, tick: int, agent_id: int) -> float:
    """One 53-bit uniform draw per seed/mechanism/day/person; never uses hash()."""
    key = json.dumps(["demography_v1", int(seed), mechanism, int(tick), int(agent_id)],
                     ensure_ascii=True, separators=(",", ":")).encode("ascii")
    bits = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 11
    return bits / (1 << 53)
