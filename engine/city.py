"""Deterministic places, civic services, and bounded decision attention.

Semantics 12 adds a city substrate without adding a second clock or scheduler.
All writes are made by the existing single-writer phase loop and every
coordinate, queue tie-break, and assignment is stable across replay.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .firms import normalize_business_idea
from .ledger import Leg, SYS_EXTERNAL, SYS_GOV
from .store import load_json


SLOTS = ("morning", "business", "evening")
LONG_LEASE_END = 2_147_483_647
APPLICATION_FIELDS = (
    "name",
    "sector",
    "lawyer_agent_id",
    "opening_capital",
    "business_idea",
)

DEFAULT_CITY_CONFIG: dict[str, Any] = {
    "enabled": False,
    "residential_districts_per_region": 4,
    "business_permits": {
        "required": True,
        "office_capacity": 6,
        "appointment_lead_ticks": 1,
        "decision_sla_ticks": 3,
        "authorization_ttl_ticks": 30,
        "max_no_shows": 3,
        "application_fee_cents": 2_500,
        "discretionary_competitor_floor": 2,
        "prohibited_sectors": [],
    },
    "attention": {"lane_limit": 8},
}


class CityError(ValueError):
    """Raised when a civic operation violates the deterministic contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _clean_text(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def canonical_application(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact permit payload later bound to incorporation."""
    name = _clean_text(value.get("name"), 60)
    if not name:
        raise CityError("business permit needs a company name")
    sector = _clean_text(value.get("sector", "services"), 40).lower()
    if not sector:
        raise CityError("business permit needs a sector")
    lawyer_raw = value.get("lawyer_agent_id")
    capital_raw = value.get("opening_capital")
    if isinstance(lawyer_raw, bool) or isinstance(capital_raw, bool):
        raise CityError("lawyer_agent_id and opening_capital must be integers")
    try:
        lawyer_id = int(lawyer_raw)
        opening_capital = int(capital_raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CityError(
            "lawyer_agent_id and opening_capital must be integers") from exc
    if lawyer_id <= 0:
        raise CityError("lawyer_agent_id must be positive")
    if opening_capital < 0:
        raise CityError("opening capital must be nonnegative")
    try:
        business_idea = normalize_business_idea(value.get("business_idea"))
    except ValueError as exc:
        raise CityError(str(exc)) from exc
    return {
        "name": name,
        "sector": sector,
        "lawyer_agent_id": lawyer_id,
        "opening_capital": opening_capital,
        "business_idea": business_idea,
    }


class City:
    """Authoritative Semantics-12 city and permit-office service."""

    def __init__(self, economy, config: dict | None = None):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        supplied = dict(config or {})
        permit = {
            **DEFAULT_CITY_CONFIG["business_permits"],
            **dict(supplied.get("business_permits") or {}),
        }
        attention = {
            **DEFAULT_CITY_CONFIG["attention"],
            **dict(supplied.get("attention") or {}),
        }
        self.config = {
            **DEFAULT_CITY_CONFIG,
            **supplied,
            "business_permits": permit,
            "attention": attention,
        }
        self.engine_semantics_version = int(economy.engine_semantics_version)
        requested = bool(self.config.get("enabled", False))
        if requested and self.engine_semantics_version < 12:
            raise CityError("city.enabled requires engine_semantics_version 12")
        if requested and not bool(economy.regions.enabled):
            raise CityError("city.enabled requires living_world.enabled")
        self.enabled = requested and self.engine_semantics_version >= 12
        self.permits_required = bool(permit.get("required", True))
        self.office_capacity = max(1, int(permit.get("office_capacity", 6)))
        self.appointment_lead_ticks = max(
            1, int(permit.get("appointment_lead_ticks", 1)))
        self.decision_sla_ticks = max(
            1, int(permit.get("decision_sla_ticks", 3)))
        self.authorization_ttl_ticks = max(
            1, int(permit.get("authorization_ttl_ticks", 30)))
        self.max_no_shows = max(
            1, min(3, int(permit.get("max_no_shows", 3))))
        self.application_fee_cents = max(
            0, int(permit.get("application_fee_cents", 2_500)))
        self.discretionary_competitor_floor = max(
            0, int(permit.get("discretionary_competitor_floor", 2)))
        self.prohibited_sectors = {
            _clean_text(item, 40).lower()
            for item in permit.get("prohibited_sectors", [])
            if _clean_text(item, 40)
        }
        self.lane_limit = max(
            1, min(8, int(attention.get("lane_limit", 8))))

    # -- stable identity and placement -------------------------------------
    @staticmethod
    def _stable_fraction(*parts: Any) -> float:
        digest = hashlib.sha256(
            "|".join(str(part) for part in parts).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    def _coordinates(self, region, place_key: str) -> tuple[float, float]:
        base_x = float(region["x"])
        base_y = float(region["y"])
        x = base_x + (self._stable_fraction(place_key, "x") - 0.5) * 0.18
        y = base_y + (self._stable_fraction(place_key, "y") - 0.5) * 0.18
        return round(max(0.02, min(0.98, x)), 6), round(
            max(0.02, min(0.98, y)), 6)

    def _ensure_place(
        self,
        *,
        place_key: str,
        region,
        name: str,
        kind: str,
        owner_type: str,
        owner_id: int | None,
        capacity: int | None,
        tick: int,
        metadata: dict | None = None,
    ) -> int:
        row = self.store.query_one(
            "SELECT id FROM places WHERE place_key=?", (place_key,))
        if row is not None:
            place_id = int(row["id"])
            self.store.update(
                "places", place_id, active=1, closed_tick=None,
                capacity=capacity, metadata_json=_canonical_json(metadata or {}))
            return place_id
        x, y = self._coordinates(region, place_key)
        return self.store.insert(
            "places",
            place_key=place_key,
            region_id=int(region["id"]),
            name=name,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
            x=x,
            y=y,
            capacity=capacity,
            active=1,
            created_tick=int(tick),
            metadata_json=_canonical_json(metadata or {}),
        )

    def _region_rows(self) -> list:
        return self.store.query("SELECT * FROM regions ORDER BY id")

    def _office_for_region(self, region_id: int):
        return self.store.query_one(
            "SELECT p.*,a.id AS agency_id,a.name AS agency_name "
            "FROM places p JOIN agencies a "
            "ON p.owner_type='agency' AND p.owner_id=a.id "
            "WHERE p.region_id=? AND p.kind='licensing_office' AND p.active=1 "
            "ORDER BY p.id LIMIT 1",
            (int(region_id),),
        )

    def _agency_for_region(self, region_id: int) -> int:
        office = self._office_for_region(region_id)
        if office is None:
            raise CityError(f"region {region_id} has no licensing office")
        return int(office["agency_id"])

    # -- genesis and routine leases ---------------------------------------
    def initialize(self, tick: int = 0) -> None:
        if not self.enabled:
            return
        regions = self._region_rows()
        if not regions:
            raise CityError("city initialization requires at least one region")
        district_count = max(
            1, int(self.config.get("residential_districts_per_region", 4)))
        for region in regions:
            region_id = int(region["id"])
            region_key = str(region["region_key"])
            for index in range(district_count):
                self._ensure_place(
                    place_key=f"region:{region_key}:residential:{index + 1}",
                    region=region,
                    name=f"{region['name']} Residential District {index + 1}",
                    kind="residential_district",
                    owner_type="region",
                    owner_id=region_id,
                    capacity=None,
                    tick=tick,
                    metadata={"district_number": index + 1},
                )
            self._ensure_place(
                place_key=f"region:{region_key}:commons",
                region=region,
                name=f"{region['name']} Public Commons",
                kind="public_commons",
                owner_type="region",
                owner_id=region_id,
                capacity=None,
                tick=tick,
            )
            agency_name = f"{region['name']} Business Licensing Agency"
            agency = self.store.query_one(
                "SELECT id FROM agencies WHERE name=?", (agency_name,))
            if agency is None:
                leader = self.store.scalar(
                    "SELECT id FROM agents WHERE alive=1 AND role='gov_official' "
                    "AND region_id=? ORDER BY id LIMIT 1",
                    (region_id,),
                    default=None,
                )
                agency_id = self.store.insert(
                    "agencies",
                    name=agency_name,
                    mandate="Review and issue business operating permits.",
                    capacity=float(self.office_capacity),
                    leader_agent_id=int(leader) if leader is not None else None,
                )
            else:
                agency_id = int(agency["id"])
            office_id = self._ensure_place(
                place_key=f"region:{region_key}:licensing-office",
                region=region,
                name=f"{region['name']} Permit Office",
                kind="licensing_office",
                owner_type="agency",
                owner_id=agency_id,
                capacity=self.office_capacity,
                tick=tick,
                metadata={"service": "business_permit"},
            )
            self._ensure_clerk(
                region, agency_id, office_id, tick=tick, allow_promotion=False)
        self._sync_firm_workplaces(tick)
        self._sync_routine_leases(tick)
        self.establish_effective_presence(tick)
        if not self.store.query_one(
                "SELECT 1 FROM events WHERE kind='civic_city_initialized' LIMIT 1"):
            self._log_semantic(
                tick,
                "civic_city_initialized",
                actor_type="government",
                actor_id=1,
                verb="opened",
                object_type="city_service",
                object_id=1,
                outcome="ready",
                payload={
                    "places": int(self.store.scalar(
                        "SELECT COUNT(*) FROM places", default=0)),
                    "permit_offices": int(self.store.scalar(
                        "SELECT COUNT(*) FROM places "
                        "WHERE kind='licensing_office'", default=0)),
                    "permit_clerks": int(self.store.scalar(
                        "SELECT COUNT(*) FROM agency_staff "
                        "WHERE role_key='permit_clerk' AND active=1", default=0)),
                },
                phase="NIGHT_CLOSE",
                importance=3.0,
            )

    def _create_clerk(
        self, region, agency_id: int, office_id: int, tick: int,
    ) -> int:
        region_id = int(region["id"])
        sequence = int(self.store.scalar(
            "SELECT COUNT(*) FROM agency_staff WHERE region_id=? AND role_key='permit_clerk'",
            (region_id,), default=0)) + 1
        name = f"Permit Clerk {region['name']} {sequence}"
        age = 32 + int(self._stable_fraction(
            region["region_key"], "permit-clerk", sequence) * 24)
        agent_id = self.store.insert(
            "agents",
            name=name,
            kind="staff",
            occupation="permit clerk",
            role="permit_clerk",
            employer_id=None,
            age=age,
            health="healthy",
            dependents=0,
            personality_json=_canonical_json({
                "agency_id": agency_id,
                "region_id": region_id,
                "service": "business_permit",
            }),
            political_lean=0.0,
            media_diet_json="[]",
            risk_tolerance=0.5,
            cadence_json='{"act":1}',
            model_tier="strong",
            alive=1,
            retired=0,
            arrived_tick=int(tick),
            region_id=region_id,
            population_tier="core",
            pinned_core=1,
        )
        bank_id = self.store.scalar(
            "SELECT id FROM banks WHERE region_id=? AND status='open' ORDER BY id LIMIT 1",
            (region_id,), default=None)
        if bank_id is None:
            bank_id = self.store.scalar(
                "SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1",
                default=None)
        currency = str(region["currency_code"] or "USD")
        checking_id = self.ledger.create_account(
            "agent",
            agent_id,
            "checking",
            bank_id=int(bank_id) if bank_id is not None else None,
            label=f"agent:{agent_id}:checking",
            opening_cents=150_000,
            funding_label=SYS_EXTERNAL,
            currency_code=currency,
        )
        self.store.update(
            "agents", agent_id, checking_account_id=checking_id)
        self.store.insert(
            "agency_staff",
            agency_id=int(agency_id),
            agent_id=agent_id,
            place_id=int(office_id),
            region_id=region_id,
            role_key="permit_clerk",
            effective_tick=int(tick),
            active=1,
            created_tick=int(tick),
        )
        self._log_semantic(
            tick,
            "agency_staff_appointed",
            actor_type="agency",
            actor_id=agency_id,
            verb="appointed",
            object_type="agent",
            object_id=agent_id,
            outcome="active",
            payload={
                "role_key": "permit_clerk",
                "region_id": region_id,
                "place_id": office_id,
            },
            phase="NIGHT_CLOSE",
            subject_type="agent",
            subject_id=agent_id,
            importance=2.0,
        )
        return agent_id

    def _promote_successor(
        self, region, agency_id: int, office_id: int, tick: int,
    ) -> int | None:
        row = self.store.query_one(
            "SELECT a.id FROM agents a "
            "LEFT JOIN agency_staff s ON s.agent_id=a.id AND s.active=1 "
            "WHERE a.alive=1 AND a.region_id=? AND a.employer_id IS NULL "
            "AND a.role IS NULL AND a.kind='citizen' AND s.id IS NULL "
            "ORDER BY a.id LIMIT 1",
            (int(region["id"]),),
        )
        if row is None:
            return None
        agent_id = int(row["id"])
        self.store.update(
            "agents",
            agent_id,
            kind="staff",
            occupation="permit clerk",
            role="permit_clerk",
            model_tier="strong",
            population_tier="core",
            pinned_core=1,
        )
        self.store.insert(
            "agency_staff",
            agency_id=int(agency_id),
            agent_id=agent_id,
            place_id=int(office_id),
            region_id=int(region["id"]),
            role_key="permit_clerk",
            effective_tick=int(tick),
            active=1,
            created_tick=int(tick),
        )
        self._log_semantic(
            tick,
            "agency_staff_succeeded",
            actor_type="agency",
            actor_id=agency_id,
            verb="reassigned",
            object_type="agent",
            object_id=agent_id,
            outcome="active",
            payload={
                "role_key": "permit_clerk",
                "region_id": int(region["id"]),
                "place_id": office_id,
            },
            phase="NIGHT_CLOSE",
            subject_type="agent",
            subject_id=agent_id,
            importance=2.5,
        )
        return agent_id

    def _ensure_clerk(
        self,
        region,
        agency_id: int,
        office_id: int,
        *,
        tick: int,
        allow_promotion: bool,
    ) -> int:
        row = self.store.query_one(
            "SELECT s.agent_id FROM agency_staff s JOIN agents a ON a.id=s.agent_id "
            "WHERE s.agency_id=? AND s.region_id=? AND s.role_key='permit_clerk' "
            "AND s.active=1 AND a.alive=1 AND a.region_id=? "
            "ORDER BY s.agent_id LIMIT 1",
            (int(agency_id), int(region["id"]), int(region["id"])),
        )
        if row is not None:
            return int(row["agent_id"])
        promoted = (
            self._promote_successor(
                region, agency_id, office_id, tick)
            if allow_promotion else None
        )
        return promoted or self._create_clerk(
            region, agency_id, office_id, tick)

    def _sync_firm_workplaces(self, tick: int) -> None:
        for firm in self.store.query(
                "SELECT f.*,r.id AS place_region_id,r.region_key,"
                "r.name AS region_name,r.x,r.y "
                "FROM firms f JOIN regions r ON r.id=f.region_id "
                "WHERE f.status<>'bankrupt' ORDER BY f.id"):
            region = dict(firm)
            region["id"] = int(firm["place_region_id"])
            self._ensure_place(
                place_key=f"firm:{int(firm['id'])}:workplace",
                region=region,
                name=f"{firm['name']} Workplace",
                kind="firm_workplace",
                owner_type="firm",
                owner_id=int(firm["id"]),
                capacity=None,
                tick=tick,
                metadata={"sector": str(firm["sector"] or "")},
            )
        self.store.execute(
            "UPDATE places SET active=0,closed_tick=? "
            "WHERE kind='firm_workplace' AND active=1 AND owner_id IN "
            "(SELECT id FROM firms WHERE status='bankrupt')",
            (int(tick),),
        )

    def register_firm_workplace(self, firm_id: int, tick: int) -> int | None:
        if not self.enabled:
            return None
        firm = self.store.query_one(
            "SELECT f.*,r.id AS place_region_id,r.region_key,"
            "r.name AS region_name,r.x,r.y "
            "FROM firms f JOIN regions r ON r.id=f.region_id WHERE f.id=?",
            (int(firm_id),),
        )
        if firm is None:
            return None
        region = dict(firm)
        region["id"] = int(firm["place_region_id"])
        place_id = self._ensure_place(
            place_key=f"firm:{int(firm_id)}:workplace",
            region=region,
            name=f"{firm['name']} Workplace",
            kind="firm_workplace",
            owner_type="firm",
            owner_id=int(firm_id),
            capacity=None,
            tick=tick,
            metadata={"sector": str(firm["sector"] or "")},
        )
        self._sync_routine_leases(tick)
        return place_id

    def _lease_key(
        self,
        agent_id: int,
        place_id: int,
        slot: str,
        start_tick: int,
        end_tick: int,
        priority: int,
        source_type: str,
        source_id: int | None,
    ) -> str:
        return _hash_json({
            "agent_id": int(agent_id),
            "place_id": int(place_id),
            "slot": slot,
            "start_tick": int(start_tick),
            "end_tick": int(end_tick),
            "priority": int(priority),
            "source_type": source_type,
            "source_id": int(source_id) if source_id is not None else None,
        })

    def _ensure_lease(
        self,
        *,
        agent_id: int,
        place_id: int,
        slot: str,
        start_tick: int,
        end_tick: int,
        priority: int,
        source_type: str,
        source_id: int | None,
        created_tick: int,
    ) -> int:
        if slot not in SLOTS:
            raise CityError(f"unsupported city slot: {slot}")
        if end_tick == LONG_LEASE_END and source_type != "appointment":
            existing = self.store.query_one(
                "SELECT id FROM occupancy_leases WHERE agent_id=? AND place_id=? "
                "AND slot=? AND source_type=? "
                "AND ((source_id IS NULL AND ? IS NULL) OR source_id=?) "
                "AND status='active' AND end_tick=? ORDER BY id DESC LIMIT 1",
                (
                    int(agent_id), int(place_id), slot, source_type,
                    int(source_id) if source_id is not None else None,
                    int(source_id) if source_id is not None else None,
                    LONG_LEASE_END,
                ),
            )
            if existing is not None:
                return int(existing["id"])
        dedupe = self._lease_key(
            agent_id, place_id, slot, start_tick, end_tick, priority,
            source_type, source_id)
        self.store.execute(
            "INSERT OR IGNORE INTO occupancy_leases "
            "(dedupe_key,agent_id,place_id,slot,start_tick,end_tick,priority,"
            "source_type,source_id,status,created_tick) "
            "VALUES (?,?,?,?,?,?,?,?,?,'active',?)",
            (
                dedupe, int(agent_id), int(place_id), slot, int(start_tick),
                int(end_tick), int(priority), source_type,
                int(source_id) if source_id is not None else None,
                int(created_tick),
            ),
        )
        row = self.store.query_one(
            "SELECT id,status FROM occupancy_leases WHERE dedupe_key=?",
            (dedupe,))
        lease_id = int(row["id"])
        if row["status"] != "active":
            self.store.update(
                "occupancy_leases", lease_id,
                status="active", ended_tick=None)
        return lease_id

    def _cancel_routine_except(
        self,
        agent_id: int,
        slot: str,
        desired_place_id: int,
        tick: int,
    ) -> None:
        self.store.execute(
            "UPDATE occupancy_leases SET status='cancelled',ended_tick=? "
            "WHERE agent_id=? AND slot=? AND status='active' "
            "AND source_type IN "
            "('routine_home','routine_work','agency_assignment','public_commons') "
            "AND place_id<>?",
            (int(tick), int(agent_id), slot, int(desired_place_id)),
        )

    def _home_place(self, region_id: int, agent_id: int):
        rows = self.store.query(
            "SELECT id FROM places WHERE region_id=? "
            "AND kind='residential_district' AND active=1 ORDER BY id",
            (int(region_id),),
        )
        if not rows:
            return None
        index = int(self._stable_fraction(
            "home", region_id, agent_id) * len(rows)) % len(rows)
        return int(rows[index]["id"])

    def _business_place(self, agent) -> tuple[int, str, int | None] | None:
        agent_id = int(agent["id"])
        staff = self.store.query_one(
            "SELECT place_id,agency_id FROM agency_staff "
            "WHERE agent_id=? AND active=1 ORDER BY id DESC LIMIT 1",
            (agent_id,),
        )
        if staff is not None:
            return (
                int(staff["place_id"]),
                "agency_assignment",
                int(staff["agency_id"]),
            )
        firm_id = None
        if agent["employer_id"] is not None:
            firm_id = int(agent["employer_id"])
        else:
            founded = self.store.scalar(
                "SELECT id FROM firms WHERE founder_agent_id=? "
                "AND status<>'bankrupt' ORDER BY id LIMIT 1",
                (agent_id,), default=None)
            if founded is not None:
                firm_id = int(founded)
        if firm_id is not None:
            workplace = self.store.scalar(
                "SELECT id FROM places WHERE owner_type='firm' AND owner_id=? "
                "AND kind='firm_workplace' AND active=1 ORDER BY id LIMIT 1",
                (firm_id,), default=None)
            if workplace is not None:
                return int(workplace), "routine_work", firm_id
        commons = self.store.scalar(
            "SELECT id FROM places WHERE region_id=? AND kind='public_commons' "
            "AND active=1 ORDER BY id LIMIT 1",
            (int(agent["region_id"]),), default=None)
        if commons is None:
            return None
        return int(commons), "public_commons", int(agent["region_id"])

    def _sync_routine_leases(self, tick: int) -> None:
        if not self.enabled:
            return
        self.store.execute(
            "UPDATE occupancy_leases SET status='cancelled',ended_tick=? "
            "WHERE status='active' AND agent_id IN "
            "(SELECT id FROM agents WHERE alive=0)",
            (int(tick),),
        )
        for agent in self.store.query(
                "SELECT * FROM agents WHERE alive=1 AND region_id IS NOT NULL "
                "ORDER BY id"):
            agent_id = int(agent["id"])
            home_id = self._home_place(int(agent["region_id"]), agent_id)
            if home_id is not None:
                for slot in ("morning", "evening"):
                    self._cancel_routine_except(
                        agent_id, slot, home_id, tick)
                    self._ensure_lease(
                        agent_id=agent_id,
                        place_id=home_id,
                        slot=slot,
                        start_tick=int(tick),
                        end_tick=LONG_LEASE_END,
                        priority=10,
                        source_type="routine_home",
                        source_id=int(agent["region_id"]),
                        created_tick=int(tick),
                    )
            business = self._business_place(agent)
            if business is not None:
                place_id, source_type, source_id = business
                self._cancel_routine_except(
                    agent_id, "business", place_id, tick)
                self._ensure_lease(
                    agent_id=agent_id,
                    place_id=place_id,
                    slot="business",
                    start_tick=int(tick),
                    end_tick=LONG_LEASE_END,
                    priority=60 if source_type == "agency_assignment" else (
                        50 if source_type == "routine_work" else 5),
                    source_type=source_type,
                    source_id=source_id,
                    created_tick=int(tick),
                )

    def establish_effective_presence(self, tick: int) -> None:
        if not self.enabled:
            return
        self.store.execute(
            "DELETE FROM effective_presence WHERE tick=?", (int(tick),))
        self.store.execute(
            "INSERT INTO effective_presence "
            "(tick,slot,agent_id,place_id,lease_id,priority,source_type) "
            "SELECT ?,slot,agent_id,place_id,id,priority,source_type FROM ("
            " SELECT l.*,ROW_NUMBER() OVER ("
            "  PARTITION BY l.agent_id,l.slot "
            "  ORDER BY l.priority DESC,l.start_tick DESC,l.id DESC"
            " ) AS rn "
            " FROM occupancy_leases l "
            " JOIN agents a ON a.id=l.agent_id AND a.alive=1 "
            " JOIN places p ON p.id=l.place_id AND p.active=1 "
            " WHERE l.status='active' AND l.start_tick<=? AND l.end_tick>=?"
            ") ranked WHERE rn=1 ORDER BY agent_id,slot",
            (int(tick), int(tick), int(tick)),
        )

    # -- nightly reconciliation -------------------------------------------
    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        self.store.execute(
            "UPDATE civic_authorizations SET status='expired' "
            "WHERE status='active' AND expiry_tick<?",
            (int(tick),),
        )
        expired = self.store.query(
            "SELECT id,holder_agent_id,case_id,expiry_tick FROM civic_authorizations "
            "WHERE status='expired' AND expiry_tick=? ORDER BY id",
            (int(tick) - 1,),
        )
        for authorization in expired:
            self._log_semantic(
                tick,
                "civic_authorization_expired",
                actor_type="government",
                actor_id=1,
                verb="expired",
                object_type="civic_authorization",
                object_id=int(authorization["id"]),
                outcome="expired",
                payload={
                    "holder_agent_id": int(authorization["holder_agent_id"]),
                    "case_id": int(authorization["case_id"]),
                    "expiry_tick": int(authorization["expiry_tick"]),
                },
                phase="NIGHT_CLOSE",
                subject_type="agent",
                subject_id=int(authorization["holder_agent_id"]),
                importance=2.0,
            )
        self._reconcile_applicants(tick)
        self._reconcile_staff(tick)
        self._sync_firm_workplaces(tick)
        self._sync_routine_leases(tick)
        self.establish_effective_presence(tick)

    def _reconcile_applicants(self, tick: int) -> None:
        deceased = self.store.query(
            "SELECT c.id,c.applicant_agent_id FROM service_cases c "
            "JOIN agents a ON a.id=c.applicant_agent_id "
            "WHERE a.alive=0 AND c.status IN "
            "('applied','appointment_scheduled','submitted','under_review') "
            "ORDER BY c.id")
        for case in deceased:
            case_id = int(case["id"])
            self.store.execute(
                "UPDATE service_cases SET status='abandoned',updated_tick=?,"
                "decided_tick=?,decision='deny',reason_code='applicant_deceased' "
                "WHERE id=?",
                (int(tick), int(tick), case_id),
            )
            self._cancel_case_appointments(case_id, tick)
            self.store.execute(
                "UPDATE institution_tasks SET status='cancelled',completed_tick=? "
                "WHERE source_case_id=? AND status IN ('pending','assigned')",
                (int(tick), case_id),
            )
            event_id = self._log_semantic(
                tick,
                "business_permit_abandoned",
                actor_type="government",
                actor_id=1,
                verb="closed",
                object_type="service_case",
                object_id=case_id,
                outcome="applicant_deceased",
                payload={"applicant_agent_id": int(case["applicant_agent_id"])},
                phase="NIGHT_CLOSE",
                subject_type="agent",
                subject_id=int(case["applicant_agent_id"]),
                importance=2.5,
            )
            self.store.update(
                "service_cases", case_id, outcome_event_id=event_id)
        self.store.execute(
            "UPDATE civic_authorizations SET status='revoked' "
            "WHERE status='active' AND holder_agent_id IN "
            "(SELECT id FROM agents WHERE alive=0)")

        moved = self.store.query(
            "SELECT c.id,c.applicant_agent_id,c.region_id,a.region_id AS current_region,"
            "c.status FROM service_cases c JOIN agents a ON a.id=c.applicant_agent_id "
            "WHERE a.alive=1 AND a.region_id IS NOT NULL "
            "AND c.region_id<>a.region_id AND c.status IN "
            "('applied','appointment_scheduled','submitted','under_review') "
            "ORDER BY c.id")
        for case in moved:
            case_id = int(case["id"])
            region_id = int(case["current_region"])
            agency_id = self._agency_for_region(region_id)
            status = str(case["status"])
            if status == "appointment_scheduled":
                self._cancel_case_appointments(case_id, tick)
                status = "applied"
            self.store.execute(
                "UPDATE service_cases SET region_id=?,agency_id=?,status=?,updated_tick=? "
                "WHERE id=?",
                (region_id, agency_id, status, int(tick), case_id),
            )
            self.store.execute(
                "UPDATE institution_tasks SET agency_id=?,assigned_agent_id=NULL,"
                "assigned_tick=NULL,status='pending' "
                "WHERE source_case_id=? AND status='assigned'",
                (agency_id, case_id),
            )
            self._log_semantic(
                tick,
                "business_permit_case_transferred",
                actor_type="government",
                actor_id=1,
                verb="transferred",
                object_type="service_case",
                object_id=case_id,
                outcome="new_region",
                payload={
                    "applicant_agent_id": int(case["applicant_agent_id"]),
                    "from_region_id": int(case["region_id"]),
                    "to_region_id": region_id,
                    "agency_id": agency_id,
                },
                phase="NIGHT_CLOSE",
                subject_type="agent",
                subject_id=int(case["applicant_agent_id"]),
                importance=1.8,
            )

    def _reconcile_staff(self, tick: int) -> None:
        invalid = self.store.query(
            "SELECT s.id,s.agent_id,s.agency_id,s.region_id "
            "FROM agency_staff s JOIN agents a ON a.id=s.agent_id "
            "WHERE s.active=1 AND (a.alive=0 OR a.region_id<>s.region_id "
            "OR COALESCE(a.role,'')<>'permit_clerk') ORDER BY s.id")
        for staff in invalid:
            staff_id = int(staff["id"])
            agent_id = int(staff["agent_id"])
            self.store.update(
                "agency_staff", staff_id,
                active=0, ended_tick=int(tick))
            self.store.execute(
                "UPDATE institution_tasks SET assigned_agent_id=NULL,"
                "assigned_tick=NULL,status='pending' "
                "WHERE assigned_agent_id=? AND status='assigned'",
                (agent_id,),
            )
            self._log_semantic(
                tick,
                "agency_staff_ended",
                actor_type="agency",
                actor_id=int(staff["agency_id"]),
                verb="released",
                object_type="agent",
                object_id=agent_id,
                outcome="succession_required",
                payload={"region_id": int(staff["region_id"])},
                phase="NIGHT_CLOSE",
                subject_type="agent",
                subject_id=agent_id,
                importance=2.0,
            )
        for region in self._region_rows():
            office = self._office_for_region(int(region["id"]))
            if office is not None:
                self._ensure_clerk(
                    region,
                    int(office["agency_id"]),
                    int(office["id"]),
                    tick=tick,
                    allow_promotion=True,
                )
        self._assign_tasks(tick, phase="NIGHT_CLOSE")

    # -- permit actions ----------------------------------------------------
    def _authorized_application(
        self, tick: int, actor_id: int, payload: dict[str, Any],
    ) -> bool:
        authorizations = getattr(
            self.e, "_business_permit_application_authorizations", {})
        expected = authorizations.get((int(tick), int(actor_id)))
        return expected is not None and expected == payload

    def apply_business_permit(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not self.enabled or not self.permits_required:
            return {"ok": False, "reason": "business permits are not enabled"}
        try:
            payload = canonical_application(action)
        except CityError as exc:
            return {"ok": False, "reason": str(exc)}
        if bool(self.e.config.get("entrepreneurship", {}).get("enabled", False)):
            if not self._authorized_application(tick, actor_id, payload):
                return {
                    "ok": False,
                    "reason": (
                        "apply_business_permit is available only from a supplied "
                        "entrepreneurship opportunity"),
                }
        agent = self.store.query_one(
            "SELECT * FROM agents WHERE id=?", (int(actor_id),))
        if agent is None or not bool(agent["alive"]):
            return {"ok": False, "reason": "applicant is not alive"}
        if agent["region_id"] is None:
            return {"ok": False, "reason": "applicant has no civic region"}
        if self.store.query_one(
                "SELECT 1 FROM firms WHERE founder_agent_id=? "
                "AND status<>'bankrupt' LIMIT 1", (int(actor_id),)):
            return {
                "ok": False,
                "reason": "founder already controls an active company",
            }
        if self.store.query_one(
                "SELECT 1 FROM service_cases WHERE applicant_agent_id=? "
                "AND status IN "
                "('applied','appointment_scheduled','submitted','under_review') "
                "LIMIT 1", (int(actor_id),)):
            return {"ok": False, "reason": "an active permit case already exists"}
        if self.store.query_one(
                "SELECT 1 FROM civic_authorizations WHERE holder_agent_id=? "
                "AND status='active' AND expiry_tick>=? LIMIT 1",
                (int(actor_id), int(tick))):
            return {
                "ok": False,
                "reason": "an active business permit authorization already exists",
            }
        checking_id = self.ledger.agent_checking_id(int(actor_id))
        if checking_id is None:
            return {"ok": False, "reason": "applicant has no checking account"}
        if self.ledger.balance(checking_id) < self.application_fee_cents:
            return {
                "ok": False,
                "reason": "insufficient funds for the non-refundable permit fee",
            }
        account = self.store.query_one(
            "SELECT currency_code FROM accounts WHERE id=?", (checking_id,))
        currency = str(account["currency_code"] or "USD")
        government_id = self.ledger.system_account(
            SYS_GOV, currency_code=currency)
        fee_transaction_id = self.ledger.post(
            int(tick),
            "business_permit_fee",
            [
                Leg(
                    checking_id,
                    -self.application_fee_cents,
                    "non-refundable business permit fee",
                ),
                Leg(
                    government_id,
                    self.application_fee_cents,
                    "business permit fee revenue",
                ),
            ],
            memo=f"agent {actor_id} business permit application",
        )
        region_id = int(agent["region_id"])
        agency_id = self._agency_for_region(region_id)
        payload_json = _canonical_json(payload)
        payload_hash = _hash_json(payload)
        case_id = self.store.insert(
            "service_cases",
            case_type="business_permit",
            agency_id=agency_id,
            applicant_agent_id=int(actor_id),
            region_id=region_id,
            priority=0,
            status="applied",
            created_tick=int(tick),
            updated_tick=int(tick),
            no_show_count=0,
            business_name=payload["name"],
            sector=payload["sector"],
            lawyer_agent_id=payload["lawyer_agent_id"],
            opening_capital_cents=payload["opening_capital"],
            business_idea_json=_canonical_json(payload["business_idea"]),
            application_payload_json=payload_json,
            application_payload_hash=payload_hash,
            fee_cents=self.application_fee_cents,
            fee_transaction_id=fee_transaction_id,
        )
        event_id = self._log_semantic(
            tick,
            "business_permit_applied",
            actor_type="agent",
            actor_id=int(actor_id),
            verb="applied_for",
            object_type="service_case",
            object_id=case_id,
            outcome="fee_paid",
            payload={
                "case_id": case_id,
                "agency_id": agency_id,
                "region_id": region_id,
                "fee_cents": self.application_fee_cents,
                "fee_transaction_id": fee_transaction_id,
                "business_name": payload["name"],
                "sector": payload["sector"],
                "application_payload_hash": payload_hash,
            },
            phase="EXECUTION",
            subject_type="agent",
            subject_id=int(actor_id),
            importance=2.5,
        )
        self.store.update(
            "service_cases", case_id, created_event_id=event_id)
        return {
            "ok": True,
            "case_id": case_id,
            "fee_cents": self.application_fee_cents,
            "status": "applied",
        }

    def attend_appointment(
        self, tick: int, actor_id: int, appointment_id: int,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "civic appointments are not enabled"}
        appointment = self.store.query_one(
            "SELECT ap.*,c.status AS case_status FROM service_appointments ap "
            "JOIN service_cases c ON c.id=ap.case_id WHERE ap.id=?",
            (int(appointment_id),),
        )
        if appointment is None:
            return {"ok": False, "reason": "appointment not found"}
        if int(appointment["applicant_agent_id"]) != int(actor_id):
            return {"ok": False, "reason": "appointment belongs to another applicant"}
        if appointment["status"] != "scheduled":
            return {"ok": False, "reason": "appointment is not scheduled"}
        if int(appointment["scheduled_tick"]) != int(tick):
            return {
                "ok": False,
                "reason": (
                    f"appointment is scheduled for tick "
                    f"{int(appointment['scheduled_tick'])}"),
            }
        if appointment["case_status"] != "appointment_scheduled":
            return {"ok": False, "reason": "permit case is not awaiting attendance"}
        case_id = int(appointment["case_id"])
        event_id = self._log_semantic(
            tick,
            "civic_appointment_attended",
            actor_type="agent",
            actor_id=int(actor_id),
            verb="attended",
            object_type="service_appointment",
            object_id=int(appointment_id),
            outcome="case_submitted",
            payload={
                "case_id": case_id,
                "agency_id": int(appointment["agency_id"]),
                "place_id": int(appointment["place_id"]),
                "attempt_number": int(appointment["attempt_number"]),
            },
            phase="EXECUTION",
            subject_type="agent",
            subject_id=int(actor_id),
            importance=2.5,
        )
        self.store.execute(
            "UPDATE service_appointments SET status='attended',attended_tick=?,"
            "outcome_event_id=? WHERE id=? AND status='scheduled'",
            (int(tick), event_id, int(appointment_id)),
        )
        self.store.execute(
            "UPDATE service_cases SET status='submitted',submitted_tick=?,"
            "updated_tick=? WHERE id=? AND status='appointment_scheduled'",
            (int(tick), int(tick), case_id),
        )
        return {
            "ok": True,
            "appointment_id": int(appointment_id),
            "case_id": case_id,
            "status": "submitted",
        }

    def decide_business_permit(
        self,
        tick: int,
        actor_id: int,
        case_id: int,
        decision: str,
        reason_code: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "business permits are not enabled"}
        decision = str(decision)
        reason_code = str(reason_code)
        valid_reasons = {
            "approve": {"market_capacity_supported"},
            "deny": {"market_capacity_constrained"},
        }
        if decision not in valid_reasons or reason_code not in valid_reasons[decision]:
            return {
                "ok": False,
                "reason": "decision and reason_code are not an allowed permit judgment",
            }
        task = self.store.query_one(
            "SELECT t.*,c.status AS case_status FROM institution_tasks t "
            "JOIN service_cases c ON c.id=t.source_case_id "
            "JOIN agency_staff s ON s.agent_id=t.assigned_agent_id "
            "AND s.agency_id=t.agency_id AND s.active=1 "
            "WHERE t.source_case_id=? AND t.task_type='decide_business_permit' "
            "AND t.status='assigned' AND t.assigned_agent_id=?",
            (int(case_id), int(actor_id)),
        )
        if task is None:
            return {"ok": False, "reason": "permit case is not assigned to this clerk"}
        if task["case_status"] != "under_review":
            return {"ok": False, "reason": "permit case is no longer under review"}
        if decision == "approve":
            authorization_id, event_id = self._approve_case(
                tick, int(case_id), reason_code, actor_id=int(actor_id))
            result: dict[str, Any] = {
                "ok": True,
                "case_id": int(case_id),
                "decision": decision,
                "authorization_id": authorization_id,
            }
        else:
            event_id = self._deny_case(
                tick, int(case_id), reason_code, actor_id=int(actor_id))
            result = {
                "ok": True,
                "case_id": int(case_id),
                "decision": decision,
            }
        self.store.execute(
            "UPDATE institution_tasks SET status='completed',completed_tick=?,"
            "outcome_event_id=? WHERE id=? AND status='assigned'",
            (int(tick), event_id, int(task["id"])),
        )
        return result

    # -- finalize maintenance ---------------------------------------------
    def finalize(self, tick: int) -> None:
        if not self.enabled:
            return
        self._record_no_shows(tick)
        self._resolve_submitted_cases(tick)
        self._assign_tasks(tick)
        self._schedule_appointments(tick)
        self._sync_firm_workplaces(tick)
        self._sync_routine_leases(tick)
        self.record_metrics(tick)

    def _cancel_case_appointments(self, case_id: int, tick: int) -> None:
        appointments = self.store.query(
            "SELECT id,lease_id FROM service_appointments "
            "WHERE case_id=? AND status='scheduled' ORDER BY id",
            (int(case_id),),
        )
        for appointment in appointments:
            self.store.update(
                "service_appointments", int(appointment["id"]),
                status="cancelled")
            if appointment["lease_id"] is not None:
                self.store.execute(
                    "UPDATE occupancy_leases SET status='cancelled',ended_tick=? "
                    "WHERE id=? AND status='active'",
                    (int(tick), int(appointment["lease_id"])),
                )

    def _record_no_shows(self, tick: int) -> None:
        appointments = self.store.query(
            "SELECT ap.*,c.no_show_count,c.applicant_agent_id,c.status AS case_status "
            "FROM service_appointments ap JOIN service_cases c ON c.id=ap.case_id "
            "WHERE ap.status='scheduled' AND ap.scheduled_tick<=? "
            "ORDER BY ap.scheduled_tick,ap.capacity_rank,ap.case_id,ap.id",
            (int(tick),),
        )
        for appointment in appointments:
            case_id = int(appointment["case_id"])
            applicant_id = int(appointment["applicant_agent_id"])
            count = int(appointment["no_show_count"]) + 1
            abandoned = count >= self.max_no_shows
            event_id = self._log_semantic(
                tick,
                "civic_appointment_no_show",
                actor_type="agent",
                actor_id=applicant_id,
                verb="missed",
                object_type="service_appointment",
                object_id=int(appointment["id"]),
                outcome="case_abandoned" if abandoned else "reschedule_required",
                payload={
                    "case_id": case_id,
                    "attempt_number": int(appointment["attempt_number"]),
                    "no_show_count": count,
                    "max_no_shows": self.max_no_shows,
                },
                phase="FINALIZE",
                subject_type="agent",
                subject_id=applicant_id,
                importance=2.5 if abandoned else 1.8,
            )
            self.store.execute(
                "UPDATE service_appointments SET status='no_show',outcome_event_id=? "
                "WHERE id=?",
                (event_id, int(appointment["id"])),
            )
            if appointment["lease_id"] is not None:
                self.store.execute(
                    "UPDATE occupancy_leases SET status='expired',ended_tick=? "
                    "WHERE id=? AND status='active'",
                    (int(tick), int(appointment["lease_id"])),
                )
            if abandoned:
                self.store.execute(
                    "UPDATE service_cases SET status='abandoned',no_show_count=?,"
                    "updated_tick=?,decided_tick=?,decision='deny',"
                    "reason_code='three_no_shows',outcome_event_id=? WHERE id=?",
                    (count, int(tick), int(tick), event_id, case_id),
                )
            else:
                self.store.execute(
                    "UPDATE service_cases SET status='applied',no_show_count=?,"
                    "updated_tick=? WHERE id=?",
                    (count, int(tick), case_id),
                )

    def _mechanical_failure(self, case) -> str | None:
        case_id = int(case["id"])
        earlier = self.store.query_one(
            "SELECT id FROM service_cases WHERE id<>? "
            "AND business_name=? COLLATE NOCASE "
            "AND status IN "
            "('applied','appointment_scheduled','submitted','under_review','approved') "
            "AND (created_tick<? OR (created_tick=? AND id<?)) "
            "ORDER BY created_tick,id LIMIT 1",
            (
                case_id,
                str(case["business_name"]),
                int(case["created_tick"]),
                int(case["created_tick"]),
                case_id,
            ),
        )
        firm = self.store.query_one(
            "SELECT id FROM firms WHERE name=? COLLATE NOCASE "
            "AND status<>'bankrupt' ORDER BY id LIMIT 1",
            (str(case["business_name"]),),
        )
        if earlier is not None or firm is not None:
            return "duplicate_name"
        if str(case["sector"]).lower() in self.prohibited_sectors:
            return "prohibited_sector"
        lawyer = self.store.query_one(
            "SELECT alive,occupation FROM agents WHERE id=?",
            (int(case["lawyer_agent_id"]),),
        )
        if (
            lawyer is None
            or not bool(lawyer["alive"])
            or str(lawyer["occupation"] or "").lower() != "lawyer"
        ):
            return "dead_or_unqualified_lawyer"
        checking_id = self.ledger.agent_checking_id(
            int(case["applicant_agent_id"]))
        if (
            checking_id is None
            or self.ledger.balance(checking_id)
            < int(case["opening_capital_cents"])
        ):
            return "insufficient_capital"
        return None

    def _market_facts(self, case) -> dict[str, Any]:
        competitors = int(self.store.scalar(
            "SELECT COUNT(*) FROM firms WHERE status IN ('private','listed') "
            "AND lower(COALESCE(sector,''))=lower(?) AND region_id=?",
            (str(case["sector"]), int(case["region_id"])),
            default=0,
        ))
        inventory = int(self.store.scalar(
            "SELECT COALESCE(SUM(inventory),0) FROM firms "
            "WHERE status IN ('private','listed') "
            "AND lower(COALESCE(sector,''))=lower(?) AND region_id=?",
            (str(case["sector"]), int(case["region_id"])),
            default=0,
        ))
        return {
            "competitors": competitors,
            "inventory": inventory,
            "discretionary_competitor_floor": (
                self.discretionary_competitor_floor),
            "borderline": competitors >= self.discretionary_competitor_floor,
        }

    def _resolve_submitted_cases(self, tick: int) -> None:
        cases = self.store.query(
            "SELECT * FROM service_cases WHERE status='submitted' "
            "ORDER BY priority DESC,created_tick,id")
        for case in cases:
            case_id = int(case["id"])
            failure = self._mechanical_failure(case)
            if failure is not None:
                self._deny_case(tick, case_id, failure, actor_id=None)
                continue
            facts = self._market_facts(case)
            if not bool(facts["borderline"]):
                self._approve_case(
                    tick, case_id, "clearly_compliant", actor_id=None)
                continue
            self.store.execute(
                "UPDATE service_cases SET status='under_review',updated_tick=? "
                "WHERE id=? AND status='submitted'",
                (int(tick), case_id),
            )
            self.store.execute(
                "INSERT OR IGNORE INTO institution_tasks "
                "(agency_id,task_type,source_case_id,priority,created_tick,due_tick,"
                "status,payload_json) VALUES "
                "(?,'decide_business_permit',?,?,?,?, 'pending',?)",
                (
                    int(case["agency_id"]),
                    case_id,
                    int(case["priority"]),
                    int(tick),
                    int(tick) + self.decision_sla_ticks,
                    _canonical_json({
                        "case_id": case_id,
                        "business_name": str(case["business_name"]),
                        "sector": str(case["sector"]),
                        "opening_capital_cents": int(
                            case["opening_capital_cents"]),
                        "market": facts,
                    }),
                ),
            )
            self._log_semantic(
                tick,
                "business_permit_referred",
                actor_type="agency",
                actor_id=int(case["agency_id"]),
                verb="referred",
                object_type="service_case",
                object_id=case_id,
                outcome="institutional_judgment_required",
                payload={
                    "applicant_agent_id": int(case["applicant_agent_id"]),
                    "market": facts,
                },
                phase="FINALIZE",
                subject_type="agent",
                subject_id=int(case["applicant_agent_id"]),
                importance=2.0,
            )

    def _approve_case(
        self,
        tick: int,
        case_id: int,
        reason_code: str,
        *,
        actor_id: int | None,
    ) -> tuple[int, int]:
        case = self.store.query_one(
            "SELECT * FROM service_cases WHERE id=?", (int(case_id),))
        if case is None or case["status"] not in {"submitted", "under_review"}:
            raise CityError("permit case cannot be approved from its current state")
        authorization_id = self.store.insert(
            "civic_authorizations",
            authorization_type="business_permit",
            holder_agent_id=int(case["applicant_agent_id"]),
            case_id=int(case_id),
            application_payload_json=str(case["application_payload_json"]),
            application_payload_hash=str(case["application_payload_hash"]),
            issued_tick=int(tick),
            expiry_tick=int(tick) + self.authorization_ttl_ticks,
            status="active",
        )
        event_id = self._log_semantic(
            tick,
            "business_permit_approved",
            actor_type="agent" if actor_id is not None else "agency",
            actor_id=(
                int(actor_id) if actor_id is not None
                else int(case["agency_id"])),
            verb="approved",
            object_type="service_case",
            object_id=int(case_id),
            outcome="authorization_issued",
            payload={
                "applicant_agent_id": int(case["applicant_agent_id"]),
                "authorization_id": authorization_id,
                "expiry_tick": int(tick) + self.authorization_ttl_ticks,
                "reason_code": reason_code,
                "decision_mode": (
                    "permit_clerk" if actor_id is not None else "mechanical"),
                "application_payload_hash": str(
                    case["application_payload_hash"]),
            },
            phase="EXECUTION" if actor_id is not None else "FINALIZE",
            subject_type="agent",
            subject_id=int(case["applicant_agent_id"]),
            importance=3.0,
        )
        self.store.execute(
            "UPDATE civic_authorizations SET issued_event_id=? WHERE id=?",
            (event_id, authorization_id),
        )
        self.store.execute(
            "UPDATE service_cases SET status='approved',updated_tick=?,decided_tick=?,"
            "decision='approve',reason_code=?,outcome_event_id=? WHERE id=?",
            (
                int(tick), int(tick), reason_code, event_id, int(case_id),
            ),
        )
        return authorization_id, event_id

    def _deny_case(
        self,
        tick: int,
        case_id: int,
        reason_code: str,
        *,
        actor_id: int | None,
    ) -> int:
        case = self.store.query_one(
            "SELECT * FROM service_cases WHERE id=?", (int(case_id),))
        if case is None or case["status"] not in {"submitted", "under_review"}:
            raise CityError("permit case cannot be denied from its current state")
        event_id = self._log_semantic(
            tick,
            "business_permit_denied",
            actor_type="agent" if actor_id is not None else "agency",
            actor_id=(
                int(actor_id) if actor_id is not None
                else int(case["agency_id"])),
            verb="denied",
            object_type="service_case",
            object_id=int(case_id),
            outcome=reason_code,
            payload={
                "applicant_agent_id": int(case["applicant_agent_id"]),
                "reason_code": reason_code,
                "decision_mode": (
                    "permit_clerk" if actor_id is not None else "mechanical"),
            },
            phase="EXECUTION" if actor_id is not None else "FINALIZE",
            subject_type="agent",
            subject_id=int(case["applicant_agent_id"]),
            importance=3.0,
        )
        self.store.execute(
            "UPDATE service_cases SET status='denied',updated_tick=?,decided_tick=?,"
            "decision='deny',reason_code=?,outcome_event_id=? WHERE id=?",
            (
                int(tick), int(tick), reason_code, event_id, int(case_id),
            ),
        )
        return event_id

    def _assign_tasks(self, tick: int, *, phase: str = "FINALIZE") -> None:
        tasks = self.store.query(
            "SELECT * FROM institution_tasks WHERE status='pending' "
            "ORDER BY priority DESC,created_tick,source_case_id,id")
        for task in tasks:
            clerk = self.store.query_one(
                "SELECT s.agent_id,COUNT(t.id) AS open_tasks "
                "FROM agency_staff s JOIN agents a ON a.id=s.agent_id "
                "LEFT JOIN institution_tasks t ON t.assigned_agent_id=s.agent_id "
                "AND t.status='assigned' "
                "WHERE s.agency_id=? AND s.role_key='permit_clerk' "
                "AND s.active=1 AND a.alive=1 "
                "GROUP BY s.agent_id ORDER BY open_tasks,s.agent_id LIMIT 1",
                (int(task["agency_id"]),),
            )
            if clerk is None:
                continue
            agent_id = int(clerk["agent_id"])
            event_id = self._log_semantic(
                tick,
                "institution_task_assigned",
                actor_type="agency",
                actor_id=int(task["agency_id"]),
                verb="assigned",
                object_type="institution_task",
                object_id=int(task["id"]),
                outcome="permit_clerk_wake_required",
                payload={
                    "case_id": int(task["source_case_id"]),
                    "assigned_agent_id": agent_id,
                    "due_tick": int(task["due_tick"]),
                },
                phase=phase,
                subject_type="agent",
                subject_id=agent_id,
                importance=2.2,
            )
            self.store.execute(
                "UPDATE institution_tasks SET assigned_agent_id=?,assigned_tick=?,"
                "status='assigned',assigned_event_id=? WHERE id=? AND status='pending'",
                (agent_id, int(tick), event_id, int(task["id"])),
            )

    def _earliest_capacity(
        self, place_id: int, first_tick: int,
    ) -> tuple[int, int]:
        capacity = int(self.store.scalar(
            "SELECT capacity FROM places WHERE id=?", (int(place_id),),
            default=self.office_capacity))
        candidate = int(first_tick)
        while True:
            used = int(self.store.scalar(
                "SELECT COUNT(*) FROM service_appointments "
                "WHERE place_id=? AND scheduled_tick=? "
                "AND status IN ('scheduled','attended','no_show')",
                (int(place_id), candidate),
                default=0,
            ))
            if used < capacity:
                return candidate, used + 1
            candidate += 1

    def _schedule_appointments(self, tick: int) -> None:
        cases = self.store.query(
            "SELECT c.*,p.id AS place_id FROM service_cases c "
            "JOIN places p ON p.owner_type='agency' AND p.owner_id=c.agency_id "
            "AND p.kind='licensing_office' AND p.active=1 "
            "WHERE c.status='applied' "
            "ORDER BY c.priority DESC,c.created_tick,c.id")
        for case in cases:
            case_id = int(case["id"])
            attempt = int(case["no_show_count"]) + 1
            if attempt > self.max_no_shows:
                continue
            schedule_sequence = int(self.store.scalar(
                "SELECT COALESCE(MAX(schedule_sequence),0)+1 "
                "FROM service_appointments WHERE case_id=?",
                (case_id,),
                default=1,
            ))
            scheduled_tick, capacity_rank = self._earliest_capacity(
                int(case["place_id"]),
                int(tick) + self.appointment_lead_ticks,
            )
            lease_id = self._ensure_lease(
                agent_id=int(case["applicant_agent_id"]),
                place_id=int(case["place_id"]),
                slot="business",
                start_tick=scheduled_tick,
                end_tick=scheduled_tick,
                priority=100,
                source_type="appointment",
                source_id=case_id,
                created_tick=int(tick),
            )
            appointment_id = self.store.insert(
                "service_appointments",
                case_id=case_id,
                agency_id=int(case["agency_id"]),
                place_id=int(case["place_id"]),
                applicant_agent_id=int(case["applicant_agent_id"]),
                scheduled_tick=scheduled_tick,
                slot="business",
                attempt_number=attempt,
                schedule_sequence=schedule_sequence,
                capacity_rank=capacity_rank,
                lease_id=lease_id,
                status="scheduled",
                created_tick=int(tick),
            )
            event_id = self._log_semantic(
                tick,
                "civic_appointment_scheduled",
                actor_type="agency",
                actor_id=int(case["agency_id"]),
                verb="scheduled",
                object_type="service_appointment",
                object_id=appointment_id,
                outcome="applicant_wake_required",
                payload={
                    "case_id": case_id,
                    "applicant_agent_id": int(case["applicant_agent_id"]),
                    "place_id": int(case["place_id"]),
                    "scheduled_tick": scheduled_tick,
                    "slot": "business",
                    "attempt_number": attempt,
                    "schedule_sequence": schedule_sequence,
                    "capacity_rank": capacity_rank,
                },
                phase="FINALIZE",
                subject_type="agent",
                subject_id=int(case["applicant_agent_id"]),
                importance=2.5,
            )
            self.store.execute(
                "UPDATE service_appointments SET scheduled_event_id=? WHERE id=?",
                (event_id, appointment_id),
            )
            self.store.execute(
                "UPDATE service_cases SET status='appointment_scheduled',"
                "updated_tick=? WHERE id=? AND status='applied'",
                (int(tick), case_id),
            )

    # -- authorization and incorporation ----------------------------------
    def active_authorization(
        self, agent_id: int, tick: int,
    ):
        return self.store.query_one(
            "SELECT ca.*,c.business_name,c.sector,c.lawyer_agent_id,"
            "c.opening_capital_cents,c.business_idea_json "
            "FROM civic_authorizations ca JOIN service_cases c ON c.id=ca.case_id "
            "WHERE ca.holder_agent_id=? AND ca.authorization_type='business_permit' "
            "AND ca.status='active' AND ca.issued_tick<=? AND ca.expiry_tick>=? "
            "ORDER BY ca.issued_tick,ca.id LIMIT 1",
            (int(agent_id), int(tick), int(tick)),
        )

    def founding_opportunity(
        self, agent_id: int, tick: int,
    ) -> dict[str, Any] | None:
        if not self.enabled or not self.permits_required:
            return None
        authorization = self.active_authorization(agent_id, tick)
        if authorization is None:
            return None
        payload = load_json(
            authorization["application_payload_json"], {}) or {}
        return {
            "review_tick": int(tick),
            "permit": {
                "authorization_id": int(authorization["id"]),
                "case_id": int(authorization["case_id"]),
                "issued_tick": int(authorization["issued_tick"]),
                "expiry_tick": int(authorization["expiry_tick"]),
                "application_payload_hash": str(
                    authorization["application_payload_hash"]),
            },
            "business_idea": payload.get("business_idea", {}),
            "action": {"type": "found_company", **payload},
        }

    def has_open_case(self, agent_id: int) -> bool:
        if not self.enabled:
            return False
        return self.store.query_one(
            "SELECT 1 FROM service_cases WHERE applicant_agent_id=? "
            "AND status IN "
            "('applied','appointment_scheduled','submitted','under_review') "
            "LIMIT 1",
            (int(agent_id),),
        ) is not None

    def reserve_authorization(
        self,
        tick: int,
        actor_id: int,
        action: Mapping[str, Any],
    ) -> tuple[int | None, str | None]:
        if not self.enabled or not self.permits_required:
            return None, None
        extras = set(action).difference({
            "type",
            *APPLICATION_FIELDS,
            "evidence_event_ids",
            "model_call_id",
            "rationale_summary",
        })
        if extras:
            return None, (
                "found_company has fields not authorized by the permit: "
                f"{sorted(extras)}")
        try:
            payload = canonical_application(action)
        except CityError as exc:
            return None, str(exc)
        payload_hash = _hash_json(payload)
        matching = self.store.query_one(
            "SELECT * FROM civic_authorizations WHERE holder_agent_id=? "
            "AND authorization_type='business_permit' AND status='active' "
            "AND expiry_tick>=? AND application_payload_hash=? "
            "ORDER BY issued_tick,id LIMIT 1",
            (int(actor_id), int(tick), payload_hash),
        )
        if matching is None:
            any_active = self.store.query_one(
                "SELECT 1 FROM civic_authorizations WHERE holder_agent_id=? "
                "AND authorization_type='business_permit' AND status='active' "
                "AND expiry_tick>=? LIMIT 1",
                (int(actor_id), int(tick)),
            )
            return None, (
                "business permit authorization payload mismatch"
                if any_active is not None
                else "an active business permit authorization is required")
        authorization_id = int(matching["id"])
        cursor = self.store.execute(
            "UPDATE civic_authorizations SET status='consumed',consumed_tick=? "
            "WHERE id=? AND status='active' AND expiry_tick>=?",
            (int(tick), authorization_id, int(tick)),
        )
        if cursor.rowcount != 1:
            return None, "business permit authorization was already consumed"
        return authorization_id, None

    def complete_authorization_consumption(
        self,
        tick: int,
        authorization_id: int,
        firm_id: int,
    ) -> int:
        authorization = self.store.query_one(
            "SELECT * FROM civic_authorizations WHERE id=?",
            (int(authorization_id),),
        )
        if (
            authorization is None
            or authorization["status"] != "consumed"
            or int(authorization["consumed_tick"]) != int(tick)
        ):
            raise CityError("business permit consumption is not reserved")
        event_id = self._log_semantic(
            tick,
            "civic_authorization_consumed",
            actor_type="agent",
            actor_id=int(authorization["holder_agent_id"]),
            verb="consumed",
            object_type="civic_authorization",
            object_id=int(authorization_id),
            outcome="firm_founded",
            payload={
                "case_id": int(authorization["case_id"]),
                "firm_id": int(firm_id),
                "application_payload_hash": str(
                    authorization["application_payload_hash"]),
            },
            phase="EXECUTION",
            subject_type="firm",
            subject_id=int(firm_id),
            importance=3.0,
        )
        self.store.execute(
            "UPDATE civic_authorizations SET consumed_by_firm_id=?,"
            "consumed_event_id=? WHERE id=?",
            (int(firm_id), event_id, int(authorization_id)),
        )
        case = self.store.query_one(
            "SELECT created_tick FROM service_cases WHERE id=?",
            (int(authorization["case_id"]),),
        )
        if case is not None:
            self.store.record_metric(
                tick,
                "civic_firm_entry_delay_ticks",
                int(tick) - int(case["created_tick"]),
            )
        self.register_firm_workplace(firm_id, tick)
        return event_id

    # -- decision context and attention -----------------------------------
    def required_appointment_action(
        self, agent_id: int, tick: int,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        row = self.store.query_one(
            "SELECT id,case_id,place_id,scheduled_tick,slot,attempt_number "
            "FROM service_appointments WHERE applicant_agent_id=? "
            "AND scheduled_tick=? AND status='scheduled' "
            "ORDER BY id LIMIT 1",
            (int(agent_id), int(tick)),
        )
        if row is None:
            return None
        return {
            "type": "attend_civic_appointment",
            "appointment_id": int(row["id"]),
        }

    def clerk_work(self, agent_id: int, tick: int) -> dict[str, Any]:
        staff = self.store.query_one(
            "SELECT s.*,a.name AS agency_name,p.name AS place_name "
            "FROM agency_staff s JOIN agencies a ON a.id=s.agency_id "
            "JOIN places p ON p.id=s.place_id "
            "WHERE s.agent_id=? AND s.active=1 AND s.role_key='permit_clerk'",
            (int(agent_id),),
        )
        if staff is None:
            return {"role": "permit_clerk", "eligible_actions": []}
        rows = self.store.query(
            "SELECT t.id AS task_id,t.due_tick,t.priority,t.payload_json,"
            "c.id AS case_id,c.business_name,c.sector,c.opening_capital_cents,"
            "c.created_tick,c.submitted_tick "
            "FROM institution_tasks t JOIN service_cases c ON c.id=t.source_case_id "
            "WHERE t.assigned_agent_id=? AND t.status='assigned' "
            "ORDER BY CASE WHEN t.due_tick<=? THEN 0 ELSE 1 END,"
            "t.due_tick,t.priority DESC,t.created_tick,t.source_case_id,t.id LIMIT 8",
            (int(agent_id), int(tick)),
        )
        cases = []
        eligible: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            item = {
                "task_id": int(row["task_id"]),
                "case_id": int(row["case_id"]),
                "business_name": str(row["business_name"]),
                "sector": str(row["sector"]),
                "opening_capital_cents": int(row["opening_capital_cents"]),
                "created_tick": int(row["created_tick"]),
                "submitted_tick": (
                    int(row["submitted_tick"])
                    if row["submitted_tick"] is not None else None),
                "due_tick": int(row["due_tick"]),
                "overdue": int(row["due_tick"]) <= int(tick),
                "review_record": load_json(row["payload_json"], {}) or {},
            }
            cases.append(item)
            if index == 0:
                eligible.extend([
                    {
                        "type": "decide_business_permit",
                        "case_id": int(row["case_id"]),
                        "decision": "approve",
                        "reason_code": "market_capacity_supported",
                    },
                    {
                        "type": "decide_business_permit",
                        "case_id": int(row["case_id"]),
                        "decision": "deny",
                        "reason_code": "market_capacity_constrained",
                    },
                ])
        return {
            "role": "permit_clerk",
            "agency": {
                "id": int(staff["agency_id"]),
                "name": str(staff["agency_name"]),
                "place_id": int(staff["place_id"]),
                "place_name": str(staff["place_name"]),
                "region_id": int(staff["region_id"]),
            },
            "assigned_cases": cases,
            "eligible_actions": eligible,
        }

    def attention_for_agent(
        self, agent_id: int, tick: int,
    ) -> dict[str, list[dict[str, Any]]]:
        lanes: dict[str, list[dict[str, Any]]] = {
            "mentions": [],
            "needs_action": [],
            "activity": [],
        }
        if not self.enabled:
            return lanes

        def event_item(
            event_id: int | None,
            *,
            title: str,
            summary: str,
            subject_type: str | None = None,
            subject_id: int | None = None,
            action: dict | None = None,
            occurred_tick: int | None = None,
        ) -> dict[str, Any]:
            event = (
                self.store.query_one(
                    "SELECT id,tick,kind,payload_json FROM events WHERE id=?",
                    (int(event_id),))
                if event_id is not None else None
            )
            return {
                "source_event_id": (
                    int(event["id"]) if event is not None else None),
                "event_kind": (
                    str(event["kind"]) if event is not None else None),
                "subject_type": subject_type,
                "subject_id": int(subject_id) if subject_id is not None else None,
                "title": title,
                "summary": summary,
                "action": action,
                "occurred_tick": (
                    int(event["tick"]) if event is not None
                    else int(occurred_tick if occurred_tick is not None else tick)),
            }

        appointments = self.store.query(
            "SELECT ap.*,p.name AS place_name FROM service_appointments ap "
            "JOIN places p ON p.id=ap.place_id "
            "WHERE ap.applicant_agent_id=? AND ap.status='scheduled' "
            "AND ap.scheduled_tick>=? ORDER BY ap.scheduled_tick,ap.id LIMIT 8",
            (int(agent_id), int(tick)),
        )
        for appointment in appointments:
            action = {
                "type": "attend_civic_appointment",
                "appointment_id": int(appointment["id"]),
            }
            item = event_item(
                (
                    int(appointment["scheduled_event_id"])
                    if appointment["scheduled_event_id"] is not None else None),
                title="Business permit appointment",
                summary=(
                    f"Attend {appointment['place_name']} on tick "
                    f"{int(appointment['scheduled_tick'])}."),
                subject_type="service_appointment",
                subject_id=int(appointment["id"]),
                action=action,
                occurred_tick=int(appointment["created_tick"]),
            )
            lanes["mentions"].append(item)
            if int(appointment["scheduled_tick"]) <= int(tick):
                lanes["needs_action"].append(item)

        authorization = self.active_authorization(agent_id, tick)
        if authorization is not None:
            payload = load_json(
                authorization["application_payload_json"], {}) or {}
            lanes["needs_action"].append(event_item(
                (
                    int(authorization["issued_event_id"])
                    if authorization["issued_event_id"] is not None else None),
                title="Business permit approved",
                summary=(
                    f"Incorporate before tick "
                    f"{int(authorization['expiry_tick'])}."),
                subject_type="civic_authorization",
                subject_id=int(authorization["id"]),
                action={"type": "found_company", **payload},
                occurred_tick=int(authorization["issued_tick"]),
            ))

        outcomes = self.store.query(
            "SELECT id,status,reason_code,outcome_event_id,updated_tick "
            "FROM service_cases WHERE applicant_agent_id=? "
            "AND outcome_event_id IS NOT NULL AND updated_tick<=? "
            "ORDER BY updated_tick DESC,id DESC LIMIT 8",
            (int(agent_id), int(tick)),
        )
        for case in outcomes:
            lanes["mentions"].append(event_item(
                int(case["outcome_event_id"]),
                title=f"Permit case {str(case['status']).replace('_', ' ')}",
                summary=(
                    str(case["reason_code"]).replace("_", " ")
                    if case["reason_code"] else "The permit office recorded an outcome."),
                subject_type="service_case",
                subject_id=int(case["id"]),
                occurred_tick=int(case["updated_tick"]),
            ))

        tasks = self.store.query(
            "SELECT id,source_case_id,due_tick,assigned_event_id,assigned_tick "
            "FROM institution_tasks WHERE assigned_agent_id=? AND status='assigned' "
            "ORDER BY CASE WHEN due_tick<=? THEN 0 ELSE 1 END,due_tick,id LIMIT 8",
            (int(agent_id), int(tick)),
        )
        for task in tasks:
            item = event_item(
                (
                    int(task["assigned_event_id"])
                    if task["assigned_event_id"] is not None else None),
                title="Permit decision required",
                summary=(
                    f"Review case {int(task['source_case_id'])} by tick "
                    f"{int(task['due_tick'])}."),
                subject_type="institution_task",
                subject_id=int(task["id"]),
                action=None,
                occurred_tick=int(task["assigned_tick"] or tick),
            )
            lanes["needs_action"].append(item)
            lanes["mentions"].append(item)

        source_ids: set[int] = set()
        for lane in ("mentions", "needs_action"):
            for item in lanes[lane]:
                if item["source_event_id"] is not None:
                    source_ids.add(int(item["source_event_id"]))
        recent = self.store.query(
            "SELECT id,tick,kind,payload_json FROM events "
            "WHERE tick<=? AND kind IN "
            "('business_permit_applied','civic_appointment_scheduled',"
            "'civic_appointment_attended','civic_appointment_no_show',"
            "'business_permit_referred','business_permit_approved',"
            "'business_permit_denied','business_permit_abandoned',"
            "'institution_task_assigned','civic_authorization_consumed',"
            "'civic_authorization_expired') "
            "AND (subject_type='agent' AND subject_id=? "
            "OR CAST(json_extract(payload_json,'$.applicant_agent_id') AS INTEGER)=? "
            "OR CAST(json_extract(payload_json,'$.assigned_agent_id') AS INTEGER)=?) "
            "ORDER BY tick DESC,id DESC LIMIT 16",
            (int(tick), int(agent_id), int(agent_id), int(agent_id)),
        )
        for event in recent:
            source_ids.add(int(event["id"]))
            lanes["activity"].append(event_item(
                int(event["id"]),
                title=str(event["kind"]).replace("_", " "),
                summary="A committed civic event changed the city record.",
                occurred_tick=int(event["tick"]),
            ))

        def newest(item: dict[str, Any]) -> tuple[int, int, str]:
            return (
                -int(item["occurred_tick"]),
                -int(item["source_event_id"] or 0),
                str(item["title"]),
            )

        lanes["mentions"] = sorted(
            lanes["mentions"], key=newest)[:self.lane_limit]
        lanes["activity"] = sorted(
            lanes["activity"], key=newest)[:self.lane_limit]
        lanes["needs_action"] = lanes["needs_action"][:self.lane_limit]
        return lanes

    def persist_attention_context(
        self,
        agent_id: int,
        tick: int,
        purpose: str,
        lanes: dict[str, list[dict[str, Any]]],
    ) -> tuple[str, list[int]]:
        if not self.enabled:
            return "", []
        snapshot = {
            lane: list(lanes.get(lane, []))[:self.lane_limit]
            for lane in ("mentions", "needs_action", "activity")
        }
        identity = {
            "agent_id": int(agent_id),
            "tick": int(tick),
            "purpose": str(purpose),
            "lanes": snapshot,
        }
        context_key = _hash_json(identity)
        snapshot_json = _canonical_json(snapshot)
        self.store.execute(
            "INSERT OR IGNORE INTO attention_contexts "
            "(context_key,agent_id,tick,purpose,lane_limit,snapshot_json,created_tick) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                context_key, int(agent_id), int(tick), str(purpose),
                self.lane_limit, snapshot_json, int(tick),
            ),
        )
        context = self.store.query_one(
            "SELECT id,context_key,snapshot_json FROM attention_contexts "
            "WHERE agent_id=? AND tick=? AND purpose=?",
            (int(agent_id), int(tick), str(purpose)),
        )
        if context is None:
            raise RuntimeError("attention context failed to persist")
        if (
            str(context["context_key"]) != context_key
            or str(context["snapshot_json"]) != snapshot_json
        ):
            raise RuntimeError("attention context replay identity mismatch")
        context_id = int(context["id"])
        source_event_ids: list[int] = []
        for lane in ("mentions", "needs_action", "activity"):
            for ordinal, item in enumerate(snapshot[lane]):
                action = item.get("action")
                event_id = item.get("source_event_id")
                if event_id is not None:
                    source_event_ids.append(int(event_id))
                self.store.execute(
                    "INSERT OR IGNORE INTO attention_context_items "
                    "(context_id,lane,ordinal,source_event_id,subject_type,subject_id,"
                    "title,summary,action_type,action_payload_json,occurred_tick) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        context_id,
                        lane,
                        ordinal,
                        int(event_id) if event_id is not None else None,
                        item.get("subject_type"),
                        (
                            int(item["subject_id"])
                            if item.get("subject_id") is not None else None),
                        str(item.get("title") or ""),
                        str(item.get("summary") or ""),
                        (
                            str(action.get("type"))
                            if isinstance(action, dict) and action.get("type")
                            else None),
                        (
                            _canonical_json(action)
                            if isinstance(action, dict) else None),
                        int(item.get("occurred_tick", tick)),
                    ),
                )
        return context_key, sorted(set(source_event_ids))

    def bind_attention_decision(
        self, context_key: str | None, decision_id: int,
    ) -> None:
        if not self.enabled or not context_key:
            return
        self.store.execute(
            "UPDATE attention_contexts SET decision_id=? "
            "WHERE context_key=? AND decision_id IS NULL",
            (int(decision_id), str(context_key)),
        )

    # -- projections and metrics ------------------------------------------
    def public_summary(self, tick: int | None = None) -> dict[str, Any]:
        as_of = int(self.store.tick if tick is None else tick)
        if not self.enabled:
            return {
                "enabled": False,
                "tick": as_of,
                "queue": {"depth": 0, "oldest_age_ticks": 0},
                "offices": [],
            }
        queue_statuses = (
            "'applied','appointment_scheduled','submitted','under_review'")
        depth = int(self.store.scalar(
            f"SELECT COUNT(*) FROM service_cases WHERE created_tick<=? "
            f"AND status IN ({queue_statuses})",
            (as_of,), default=0))
        oldest = self.store.scalar(
            f"SELECT MIN(created_tick) FROM service_cases WHERE created_tick<=? "
            f"AND status IN ({queue_statuses})",
            (as_of,), default=None)
        offices = []
        for office in self.store.query(
                "SELECT p.id,p.name,p.region_id,p.capacity,p.x,p.y,"
                "a.id AS agency_id,a.name AS agency_name "
                "FROM places p JOIN agencies a ON a.id=p.owner_id "
                "WHERE p.kind='licensing_office' AND p.active=1 ORDER BY p.id"):
            office_depth = int(self.store.scalar(
                "SELECT COUNT(*) FROM service_cases WHERE agency_id=? "
                "AND created_tick<=? AND status IN "
                "('applied','appointment_scheduled','submitted','under_review')",
                (int(office["agency_id"]), as_of), default=0))
            scheduled = int(self.store.scalar(
                "SELECT COUNT(*) FROM service_appointments "
                "WHERE place_id=? AND scheduled_tick=? "
                "AND status IN ('scheduled','attended','no_show')",
                (int(office["id"]), as_of), default=0))
            occupancy = int(self.store.scalar(
                "SELECT COUNT(*) FROM effective_presence WHERE tick=? "
                "AND place_id=? AND slot='business'",
                (as_of, int(office["id"])), default=0))
            offices.append({
                "place_id": int(office["id"]),
                "name": str(office["name"]),
                "region_id": int(office["region_id"]),
                "agency_id": int(office["agency_id"]),
                "agency_name": str(office["agency_name"]),
                "capacity": int(office["capacity"] or self.office_capacity),
                "scheduled_today": scheduled,
                "occupancy": occupancy,
                "queue_depth": office_depth,
                "x": float(office["x"]),
                "y": float(office["y"]),
            })
        counts = {
            str(row["status"]): int(row["count"])
            for row in self.store.query(
                "SELECT status,COUNT(*) AS count FROM service_cases "
                "WHERE created_tick<=? GROUP BY status ORDER BY status",
                (as_of,))
        }
        return {
            "enabled": True,
            "tick": as_of,
            "queue": {
                "depth": depth,
                "oldest_age_ticks": (
                    max(0, as_of - int(oldest)) if oldest is not None else 0),
            },
            "cases_by_status": counts,
            "offices": offices,
        }

    @staticmethod
    def _case_view(row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "case_type": str(row["case_type"]),
            "agency_id": int(row["agency_id"]),
            "applicant_agent_id": int(row["applicant_agent_id"]),
            "region_id": int(row["region_id"]),
            "priority": int(row["priority"]),
            "status": str(row["status"]),
            "created_tick": int(row["created_tick"]),
            "submitted_tick": (
                int(row["submitted_tick"])
                if row["submitted_tick"] is not None else None),
            "decided_tick": (
                int(row["decided_tick"])
                if row["decided_tick"] is not None else None),
            "no_show_count": int(row["no_show_count"]),
            "business_name": str(row["business_name"]),
            "sector": str(row["sector"]),
            "lawyer_agent_id": int(row["lawyer_agent_id"]),
            "opening_capital_cents": int(row["opening_capital_cents"]),
            "business_idea": load_json(row["business_idea_json"], {}) or {},
            "decision": row["decision"],
            "reason_code": row["reason_code"],
            "created_event_id": (
                int(row["created_event_id"])
                if row["created_event_id"] is not None else None),
            "outcome_event_id": (
                int(row["outcome_event_id"])
                if row["outcome_event_id"] is not None else None),
        }

    def cases_for_viewer(
        self, viewer_agent_id: int | None, tick: int | None = None,
    ) -> dict[str, Any]:
        as_of = int(self.store.tick if tick is None else tick)
        if not self.enabled or viewer_agent_id is None:
            return {
                "visibility": "public",
                "items": [],
                "summary": self.public_summary(as_of),
            }
        agent = self.store.query_one(
            "SELECT id,role FROM agents WHERE id=?", (int(viewer_agent_id),))
        if agent is None:
            raise CityError("viewer agent not found")
        leader = self.store.query_one(
            "SELECT id FROM agencies WHERE leader_agent_id=? ORDER BY id LIMIT 1",
            (int(viewer_agent_id),),
        )
        if leader is not None:
            return {
                "visibility": "agency_leader_aggregate",
                "items": [],
                "summary": self.public_summary(as_of),
            }
        staff = self.store.query_one(
            "SELECT agency_id FROM agency_staff WHERE agent_id=? "
            "AND role_key='permit_clerk' AND active=1",
            (int(viewer_agent_id),),
        )
        if staff is not None:
            rows = self.store.query(
                "SELECT c.* FROM service_cases c JOIN institution_tasks t "
                "ON t.source_case_id=c.id WHERE t.assigned_agent_id=? "
                "AND c.created_tick<=? ORDER BY c.priority DESC,c.created_tick,c.id",
                (int(viewer_agent_id), as_of),
            )
            return {
                "visibility": "assigned_clerk",
                "items": [self._case_view(row) for row in rows],
            }
        rows = self.store.query(
            "SELECT * FROM service_cases WHERE applicant_agent_id=? "
            "AND created_tick<=? ORDER BY created_tick DESC,id DESC",
            (int(viewer_agent_id), as_of),
        )
        return {
            "visibility": "applicant",
            "items": [self._case_view(row) for row in rows],
        }

    def attention_projection(
        self, agent_id: int, tick: int | None = None,
    ) -> dict[str, Any]:
        as_of = int(self.store.tick if tick is None else tick)
        lanes = self.attention_for_agent(agent_id, as_of)
        persisted = self.store.query_one(
            "SELECT id,context_key,tick,purpose,decision_id "
            "FROM attention_contexts WHERE agent_id=? AND tick<=? "
            "ORDER BY tick DESC,id DESC LIMIT 1",
            (int(agent_id), as_of),
        )
        return {
            "agent_id": int(agent_id),
            "tick": as_of,
            "lane_limit": self.lane_limit,
            "lanes": lanes,
            "last_decision_context": (
                {
                    "id": int(persisted["id"]),
                    "context_key": str(persisted["context_key"]),
                    "tick": int(persisted["tick"]),
                    "purpose": str(persisted["purpose"]),
                    "decision_id": (
                        int(persisted["decision_id"])
                        if persisted["decision_id"] is not None else None),
                }
                if persisted is not None else None
            ),
        }

    def place_detail(self, place_id: int, tick: int) -> dict[str, Any] | None:
        row = self.store.query_one(
            "SELECT * FROM places WHERE id=?", (int(place_id),))
        if row is None or int(row["created_tick"]) > int(tick):
            return None
        occupancy = {
            slot: int(self.store.scalar(
                "SELECT COUNT(*) FROM effective_presence "
                "WHERE tick=? AND place_id=? AND slot=?",
                (int(tick), int(place_id), slot), default=0))
            for slot in SLOTS
        }
        detail = {
            **dict(row),
            "metadata": load_json(row["metadata_json"], {}) or {},
            "occupancy": occupancy,
        }
        detail.pop("metadata_json", None)
        if row["kind"] == "licensing_office":
            detail["queue_depth"] = int(self.store.scalar(
                "SELECT COUNT(*) FROM service_cases WHERE agency_id=? "
                "AND status IN "
                "('applied','appointment_scheduled','submitted','under_review')",
                (int(row["owner_id"]),), default=0))
        return detail

    def agency_detail(self, agency_id: int, tick: int) -> dict[str, Any] | None:
        agency = self.store.query_one(
            "SELECT * FROM agencies WHERE id=?", (int(agency_id),))
        if agency is None:
            return None
        staff = int(self.store.scalar(
            "SELECT COUNT(*) FROM agency_staff WHERE agency_id=? AND active=1",
            (int(agency_id),), default=0))
        queue = int(self.store.scalar(
            "SELECT COUNT(*) FROM service_cases WHERE agency_id=? "
            "AND created_tick<=? AND status IN "
            "('applied','appointment_scheduled','submitted','under_review')",
            (int(agency_id), int(tick)), default=0))
        return {
            **dict(agency),
            "active_staff": staff,
            "queue_depth": queue,
            "cases_by_status": {
                str(row["status"]): int(row["count"])
                for row in self.store.query(
                    "SELECT status,COUNT(*) AS count FROM service_cases "
                    "WHERE agency_id=? AND created_tick<=? "
                    "GROUP BY status ORDER BY status",
                    (int(agency_id), int(tick)),
                )
            },
        }

    def map_places(self, tick: int) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        items = []
        for row in self.store.query(
                "SELECT * FROM places WHERE created_tick<=? "
                "AND (closed_tick IS NULL OR closed_tick>?) ORDER BY id",
                (int(tick), int(tick))):
            item = dict(row)
            item["metadata"] = load_json(item.pop("metadata_json", None), {}) or {}
            item["occupancy"] = {
                slot: int(self.store.scalar(
                    "SELECT COUNT(*) FROM effective_presence "
                    "WHERE tick=? AND place_id=? AND slot=?",
                    (int(tick), int(row["id"]), slot), default=0))
                for slot in SLOTS
            }
            if row["kind"] == "licensing_office":
                item["queue_depth"] = int(self.store.scalar(
                    "SELECT COUNT(*) FROM service_cases WHERE agency_id=? "
                    "AND created_tick<=? AND status IN "
                    "('applied','appointment_scheduled','submitted','under_review')",
                    (int(row["owner_id"]), int(tick)), default=0))
            items.append(item)
        return items

    def map_presence(self, tick: int, *, public: bool = True) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        rows = self.store.query(
            "SELECT ep.tick,ep.slot,ep.agent_id,a.name,a.role,a.occupation,"
            "ep.place_id,p.name AS place_name,p.kind AS place_kind,p.x,p.y,"
            "ep.source_type,ep.priority "
            "FROM effective_presence ep JOIN agents a ON a.id=ep.agent_id "
            "JOIN places p ON p.id=ep.place_id "
            "WHERE ep.tick=? ORDER BY ep.slot,ep.place_id,ep.agent_id",
            (int(tick),),
        )
        if not public:
            return [dict(row) for row in rows]
        visible = [
            dict(row) for row in rows
            if row["place_kind"] != "licensing_office"
        ]
        for row in self.store.query(
                "SELECT ep.slot,ep.place_id,p.name AS place_name,p.kind AS place_kind,"
                "p.x,p.y,COUNT(*) AS occupancy "
                "FROM effective_presence ep JOIN places p ON p.id=ep.place_id "
                "WHERE ep.tick=? AND p.kind='licensing_office' "
                "GROUP BY ep.slot,ep.place_id,p.name,p.kind,p.x,p.y "
                "ORDER BY ep.slot,ep.place_id",
                (int(tick),)):
            visible.append({
                "tick": int(tick),
                "slot": str(row["slot"]),
                "agent_id": None,
                "name": None,
                "role": None,
                "occupation": None,
                "place_id": int(row["place_id"]),
                "place_name": str(row["place_name"]),
                "place_kind": str(row["place_kind"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "source_type": "privacy_aggregate",
                "priority": None,
                "occupancy": int(row["occupancy"]),
            })
        return visible

    def record_metrics(self, tick: int) -> None:
        queue = self.public_summary(tick)["queue"]
        self.store.record_metric(
            tick, "civic_queue_depth", float(queue["depth"]))
        self.store.record_metric(
            tick, "civic_oldest_queue_age_ticks",
            float(queue["oldest_age_ticks"]))
        self.store.record_metric(
            tick,
            "civic_peak_queue_age_ticks",
            max(
                float(queue["oldest_age_ticks"]),
                self.store.metric_latest(
                    "civic_peak_queue_age_ticks", 0.0),
            ),
        )
        self.store.record_metric(
            tick,
            "civic_peak_queue_depth",
            max(
                float(queue["depth"]),
                self.store.metric_latest("civic_peak_queue_depth", 0.0),
            ),
        )
        approval_latency = self.store.scalar(
            "SELECT AVG(decided_tick-created_tick) FROM service_cases "
            "WHERE status='approved' AND decided_tick IS NOT NULL",
            default=0.0)
        self.store.record_metric(
            tick,
            "civic_approval_latency_ticks",
            float(approval_latency or 0.0),
        )
        denials = int(self.store.scalar(
            "SELECT COUNT(*) FROM service_cases WHERE status='denied'",
            default=0))
        self.store.record_metric(
            tick, "civic_permit_denials", float(denials))
        lost = int(self.store.scalar(
            "SELECT COUNT(*) FROM effective_presence ep "
            "JOIN places p ON p.id=ep.place_id "
            "JOIN employments e ON e.agent_id=ep.agent_id AND e.status='active' "
            "WHERE ep.tick<=? AND ep.slot='business' "
            "AND p.kind='licensing_office'",
            (int(tick),), default=0))
        self.store.record_metric(
            tick, "civic_lost_production_worker_days", float(lost))
        entry_delay = self.store.scalar(
            "SELECT AVG(f.founded_tick-a.arrived_tick) FROM firms f "
            "JOIN agents a ON a.id=f.founder_agent_id "
            "WHERE f.founder_agent_id IS NOT NULL",
            default=0.0,
        )
        self.store.record_metric(
            tick,
            "civic_firm_entry_delay_ticks",
            float(entry_delay or 0.0),
        )
        used = int(self.store.scalar(
            "SELECT COUNT(*) FROM service_appointments "
            "WHERE scheduled_tick<=? "
            "AND status IN ('scheduled','attended','no_show')",
            (int(tick),), default=0))
        capacity = int(self.store.scalar(
            "SELECT COALESCE(SUM(capacity),0) FROM places "
            "WHERE kind='licensing_office' AND active=1",
            default=0))
        capacity_days = capacity * max(1, int(tick) + 1)
        utilization = float(used / capacity_days) if capacity_days else 0.0
        self.store.record_metric(
            tick, "civic_office_utilization", utilization)

    # -- event receipts ----------------------------------------------------
    def _log_semantic(
        self,
        tick: int,
        kind: str,
        *,
        actor_type: str,
        actor_id: int,
        verb: str,
        object_type: str,
        object_id: int,
        outcome: str,
        payload: dict[str, Any] | None = None,
        phase: str,
        subject_type: str | None = None,
        subject_id: int | None = None,
        importance: float = 1.0,
    ) -> int:
        body = dict(payload or {})
        body["semantic_receipt"] = {
            "actor": {"type": actor_type, "id": int(actor_id)},
            "verb": str(verb),
            "object": {"type": object_type, "id": int(object_id)},
            "outcome": str(outcome),
        }
        return self.store.log_event(
            int(tick),
            kind,
            body,
            phase=phase,
            subject_type=subject_type or object_type,
            subject_id=(
                int(subject_id) if subject_id is not None else int(object_id)),
            importance=float(importance),
        )
