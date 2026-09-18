"""Opt-in, deterministic personal identities for formerly role-labelled people.

Version 1 never consumes a simulation random stream. Activation is prospective:
the saved configuration and rename events retain the old labels for replay.
"""
from __future__ import annotations

import hashlib
import re

from agents.personas.base import FIRST_NAMES, LAST_NAMES


def is_role_label(name: str) -> bool:
    value = str(name or "").strip()
    return not value or bool(re.fullmatch(
        r"(?:House Member \d+|Senate Member \d+|Registered Lobbyist \d+|"
        r"Officer \d+|(?:Editor|Reporter) (?:The Ledger|Commons Dispatch)|"
        r"Director Northstar .+|Exchange Operator|VC Partner|Agent \d+)", value))


def assign_personal_names(store, config: dict, tick: int) -> int:
    settings = config.get("personal_names", {})
    if (int(config.get("engine_semantics_version", 1)) < 7
            or settings.get("version") != 1
            or tick < int(settings.get("activation_tick", 0))):
        return 0
    people = store.query("SELECT id,name FROM agents ORDER BY id")
    used = {str(row["name"]).casefold() for row in people if not is_role_label(row["name"])}
    renamed = 0
    for person in people:
        if not is_role_label(person["name"]):
            continue
        identity = int(person["id"])
        digest = hashlib.sha256(f"personal-name-v1:{config.get('seed', 42)}:{identity}".encode()).digest()
        start = int.from_bytes(digest[:8], "big")
        count = len(FIRST_NAMES) * len(LAST_NAMES)
        for offset in range(count):
            index = (start + offset) % count
            name = f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {LAST_NAMES[index // len(FIRST_NAMES)]}"
            if name.casefold() not in used:
                break
        else:
            # Finite name pool: a stable middle initial sequence extends it.
            suffix = identity
            middle = ""
            while suffix:
                suffix, letter = divmod(suffix, 26)
                middle = chr(65 + letter) + middle
            name = f"{FIRST_NAMES[identity % len(FIRST_NAMES)]} {middle}. {LAST_NAMES[identity % len(LAST_NAMES)]}"
        store.update("agents", identity, name=name)
        store.log_event(tick, "agent_personal_name_assigned", {
            "agent_id": identity, "previous_name": person["name"], "name": name,
            "naming_version": 1,
        }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=identity)
        used.add(name.casefold())
        renamed += 1
    return renamed
