"""Deterministic organization membership snapshots for message delivery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class OrganizationReferenceError(ValueError):
    """Raised when an organization reference has no authoritative target."""


GOVERNMENT_ROLES = {
    "central_banker",
    "gov_official",
    "judge",
    "regulator",
    "competition_regulator",
    "labor_regulator",
    "legislator_house",
    "legislator_senate",
    "executive",
}


@dataclass(frozen=True)
class MembershipSnapshot:
    organization_kind: str
    organization_id: int
    tick: int
    member_ids: tuple[int, ...]
    snapshot_hash: str

    def reference_json(self) -> str:
        return json.dumps(
            {
                "organization_kind": self.organization_kind,
                "organization_id": self.organization_id,
                "tick": self.tick,
                "member_ids": list(self.member_ids),
                "snapshot_hash": self.snapshot_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class OrganizationMembershipResolver:
    """Adapt current firm, bank, government, and outlet identities."""

    def __init__(self, store, config: dict | None = None):
        self.store = store
        self.config = config or {}

    def validate_reference(self, kind: str, organization_id: int) -> None:
        if kind not in {"firm", "bank", "government", "outlet"}:
            raise OrganizationReferenceError("unsupported organization kind")
        if isinstance(organization_id, bool) or int(organization_id) <= 0:
            raise OrganizationReferenceError("organization id must be positive")
        organization_id = int(organization_id)
        if kind == "firm":
            exists = self.store.query_one("SELECT id FROM firms WHERE id=?", (organization_id,))
        elif kind == "bank":
            exists = self.store.query_one("SELECT id FROM banks WHERE id=?", (organization_id,))
        elif kind == "government":
            exists = organization_id == 1 and (
                bool(self.config.get("government"))
                or self.store.query_one(
                    "SELECT id FROM agents WHERE role IN ("
                    + ",".join("?" for _ in sorted(GOVERNMENT_ROLES))
                    + ") LIMIT 1",
                    tuple(sorted(GOVERNMENT_ROLES)),
                ) is not None
            )
        else:
            exists = self.store.query_one(
                "SELECT id FROM agents WHERE "
                "json_extract(personality_json,'$.outlet_id')=? LIMIT 1",
                (organization_id,),
            )
            if exists is None:
                configured = self._configured_outlet_ids()
                exists = organization_id in configured
        if not exists:
            raise OrganizationReferenceError(
                f"unknown {kind} organization reference")

    def snapshot(self, kind: str, organization_id: int, tick: int) -> MembershipSnapshot:
        self.validate_reference(kind, organization_id)
        organization_id = int(organization_id)
        if kind == "firm":
            rows = self.store.query(
                "SELECT DISTINCT a.id FROM agents a WHERE a.alive=1 AND ("
                "a.id=(SELECT founder_agent_id FROM firms WHERE id=?) OR "
                "EXISTS(SELECT 1 FROM employments e WHERE e.agent_id=a.id "
                "AND e.firm_id=? AND e.status='active' AND e.start_tick<=? "
                "AND (e.end_tick IS NULL OR e.end_tick>=?))) ORDER BY a.id",
                (organization_id, organization_id, tick, tick),
            )
        elif kind == "bank":
            rows = self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND employer_id=? "
                "AND role IN ('credit_officer','teller') ORDER BY id",
                (organization_id,),
            )
        elif kind == "government":
            roles = tuple(sorted(GOVERNMENT_ROLES))
            rows = self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND role IN ("
                + ",".join("?" for _ in roles)
                + ") ORDER BY id",
                roles,
            )
        else:
            rows = self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND role IN ('editor','reporter') "
                "AND json_extract(personality_json,'$.outlet_id')=? ORDER BY id",
                (organization_id,),
            )
        member_ids = tuple(int(row["id"]) for row in rows)
        canonical = json.dumps(
            {
                "organization_kind": kind,
                "organization_id": organization_id,
                "tick": int(tick),
                "member_ids": list(member_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return MembershipSnapshot(kind, organization_id, int(tick), member_ids, digest)

    def _configured_outlet_ids(self) -> set[int]:
        candidates = self.config.get("news", {}).get("outlets", [])
        if not candidates:
            candidates = self.config.get("outlets", [])
        ids = set()
        for index, item in enumerate(candidates, start=1):
            if isinstance(item, dict):
                raw = item.get("id", index)
            else:
                raw = index
            try:
                ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        return ids
