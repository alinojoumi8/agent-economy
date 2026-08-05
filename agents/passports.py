"""Persistent Agent Passports and local world-citizenship admission."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time
from typing import Any
from uuid import uuid4

from .external import (
    ExternalAgentError,
    ExternalAgentService,
    SCOPE_COMMONS_READ,
    SCOPE_COMMONS_WRITE,
    SCOPE_WORLD_ACT,
    SCOPE_WORLD_READ,
)


HANDLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
FULL_CITIZEN_SCOPES = (
    SCOPE_WORLD_READ,
    SCOPE_WORLD_ACT,
    SCOPE_COMMONS_READ,
    SCOPE_COMMONS_WRITE,
)
PASSPORT_STATES = ("pending_claim", "active", "suspended", "retired")
CITIZENSHIP_STATES = (
    "pending_claim",
    "waitlisted",
    "offered",
    "queued",
    "active",
    "ended",
    "suspended",
    "revoked",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def _clean_text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def normalize_handle(value: str) -> str:
    handle = str(value or "").strip().lower()
    if not HANDLE_PATTERN.fullmatch(handle):
        raise PassportError(
            422,
            "handle must be 3-32 lowercase letters, numbers, underscores, or hyphens",
            "invalid_handle",
        )
    return handle


@dataclass
class PassportError(RuntimeError):
    status_code: int
    message: str
    code: str = "passport_error"

    def __str__(self) -> str:
        return self.message


class SqlitePassportRepository:
    """Machine-local control plane that is independent of any one world DB."""

    _SCHEMA = """
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS passport_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS agent_passports (
        id TEXT PRIMARY KEY,
        handle TEXT NOT NULL,
        normalized_handle TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        biography TEXT NOT NULL DEFAULT '',
        preferred_occupation TEXT NOT NULL DEFAULT '',
        runtime TEXT NOT NULL DEFAULT 'custom',
        owner_id TEXT,
        status TEXT NOT NULL CHECK(status IN ('pending_claim','active','suspended','retired')),
        created_at TEXT NOT NULL,
        claimed_at TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS passport_claims (
        id TEXT PRIMARY KEY,
        passport_id TEXT NOT NULL REFERENCES agent_passports(id),
        world_slug TEXT NOT NULL,
        claim_token_hash TEXT NOT NULL UNIQUE,
        bootstrap_token_hash TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('pending','claimed','expired','revoked')),
        expires_at TEXT NOT NULL,
        consumed_at TEXT,
        bootstrap_consumed_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS passport_citizenships (
        id TEXT PRIMARY KEY,
        passport_id TEXT NOT NULL REFERENCES agent_passports(id),
        world_slug TEXT NOT NULL,
        run_id TEXT NOT NULL,
        connection_id TEXT UNIQUE,
        status TEXT NOT NULL CHECK(status IN (
            'pending_claim','waitlisted','offered','queued','active',
            'ended','suspended','revoked'
        )),
        offer_expires_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(passport_id, run_id)
    );
    CREATE TABLE IF NOT EXISTS passport_oauth_requests (
        id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        code_challenge TEXT NOT NULL,
        scope TEXT NOT NULL,
        state TEXT,
        resource TEXT NOT NULL,
        world_slug TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired')),
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_passport_claim_bootstrap
        ON passport_claims(bootstrap_token_hash, status);
    CREATE INDEX IF NOT EXISTS ix_passport_citizenship_queue
        ON passport_citizenships(run_id, status, created_at, id);
    CREATE INDEX IF NOT EXISTS ix_agent_passports_owner
        ON agent_passports(owner_id, status, created_at);
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(self._SCHEMA)
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM passport_meta WHERE key='cookie_signing_key'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO passport_meta(key,value) VALUES('cookie_signing_key',?)",
                    (secrets.token_hex(32),))

    @property
    def signing_key(self) -> bytes:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM passport_meta WHERE key='cookie_signing_key'"
            ).fetchone()
        if row is None:
            raise RuntimeError("passport signing key is missing")
        return bytes.fromhex(str(row["value"]))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _document(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _begin(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        self._conn.execute("COMMIT")

    def _rollback(self) -> None:
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")

    def create_registration(
        self, *, handle: str, display_name: str, biography: str,
        preferred_occupation: str, runtime: str, world_slug: str, run_id: str,
        claim_hours: int = 24,
    ) -> dict[str, Any]:
        normalized = normalize_handle(handle)
        passport_id = str(uuid4())
        claim_id = str(uuid4())
        citizenship_id = str(uuid4())
        claim_token = _token("ae_claim_")
        bootstrap_token = _token("ae_boot_")
        created = _iso()
        expires = _iso(_now() + timedelta(hours=max(1, min(claim_hours, 72))))
        with self._lock:
            self._begin()
            try:
                self._conn.execute(
                    "INSERT INTO agent_passports("
                    "id,handle,normalized_handle,display_name,biography,"
                    "preferred_occupation,runtime,status,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,'pending_claim',?,?)",
                    (passport_id, normalized, normalized,
                     _clean_text(display_name, 80), _clean_text(biography, 500),
                     _clean_text(preferred_occupation, 80),
                     _clean_text(runtime, 40) or "custom", created, created))
                self._conn.execute(
                    "INSERT INTO passport_claims("
                    "id,passport_id,world_slug,claim_token_hash,bootstrap_token_hash,"
                    "status,expires_at,created_at) VALUES(?,?,?,?,?,'pending',?,?)",
                    (claim_id, passport_id, world_slug, _hash(claim_token),
                     _hash(bootstrap_token), expires, created))
                self._conn.execute(
                    "INSERT INTO passport_citizenships("
                    "id,passport_id,world_slug,run_id,status,created_at,updated_at"
                    ") VALUES(?,?,?,?,'pending_claim',?,?)",
                    (citizenship_id, passport_id, world_slug, run_id, created, created))
                self._commit()
            except sqlite3.IntegrityError as exc:
                self._rollback()
                if "normalized_handle" in str(exc) or "UNIQUE" in str(exc):
                    raise PassportError(409, "handle is already registered", "handle_taken") from exc
                raise
            except Exception:
                self._rollback()
                raise
        return {
            "passport_id": passport_id,
            "claim_id": claim_id,
            "citizenship_id": citizenship_id,
            "handle": normalized,
            "claim_token": claim_token,
            "bootstrap_token": bootstrap_token,
            "expires_at": expires,
        }

    def claim(self, claim_token: str, owner_id: str) -> dict[str, Any]:
        now = _now()
        now_text = _iso(now)
        with self._lock:
            self._begin()
            try:
                row = self._conn.execute(
                    "SELECT cl.*,p.owner_id,p.status AS passport_status,"
                    "c.id AS citizenship_id,c.run_id,c.status AS citizenship_status "
                    "FROM passport_claims cl JOIN agent_passports p ON p.id=cl.passport_id "
                    "JOIN passport_citizenships c ON c.passport_id=p.id "
                    "AND c.world_slug=cl.world_slug WHERE cl.claim_token_hash=?",
                    (_hash(claim_token),)).fetchone()
                if row is None:
                    raise PassportError(404, "claim link is invalid", "claim_not_found")
                if str(row["status"]) == "claimed":
                    if str(row["owner_id"] or "") != str(owner_id):
                        raise PassportError(409, "passport was claimed by another owner",
                                            "claim_already_used")
                    claim_id = str(row["id"])
                    self._commit()
                    return self.registration_by_claim_id(claim_id)
                if str(row["status"]) != "pending":
                    raise PassportError(409, "claim link is no longer active", "claim_inactive")
                if _parse_time(str(row["expires_at"])) <= now:
                    self._conn.execute(
                        "UPDATE passport_claims SET status='expired' WHERE id=?",
                        (str(row["id"]),))
                    self._commit()
                    raise PassportError(410, "claim link has expired", "claim_expired")
                self._conn.execute(
                    "UPDATE agent_passports SET owner_id=?,status='active',"
                    "claimed_at=?,updated_at=? WHERE id=?",
                    (str(owner_id)[:128], now_text, now_text, str(row["passport_id"])))
                self._conn.execute(
                    "UPDATE passport_claims SET status='claimed',consumed_at=? WHERE id=?",
                    (now_text, str(row["id"])))
                self._commit()
            except PassportError:
                self._rollback()
                raise
            except Exception:
                self._rollback()
                raise
        return self.registration_by_claim_id(str(row["id"]))

    def claim_preview(self, claim_token: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM passport_claims WHERE claim_token_hash=?",
                (_hash(claim_token),)).fetchone()
        if row is None:
            raise PassportError(404, "claim link is invalid", "claim_not_found")
        registration = self.registration_by_claim_id(str(row["id"]))
        if (str(registration["claim_status"]) == "pending"
                and _parse_time(str(registration["expires_at"])) <= _now()):
            with self._lock:
                self._conn.execute(
                    "UPDATE passport_claims SET status='expired' "
                    "WHERE id=? AND status='pending'", (str(row["id"]),))
            registration["claim_status"] = "expired"
        return registration

    def registration_by_claim_id(self, claim_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT cl.id AS claim_id,cl.passport_id,cl.world_slug,cl.status AS claim_status,"
                "cl.expires_at,cl.bootstrap_consumed_at,p.handle,p.display_name,p.biography,"
                "p.preferred_occupation,p.runtime,p.owner_id,p.status AS passport_status,"
                "c.id AS citizenship_id,c.run_id,c.connection_id,"
                "c.status AS citizenship_status,c.offer_expires_at "
                "FROM passport_claims cl JOIN agent_passports p ON p.id=cl.passport_id "
                "JOIN passport_citizenships c ON c.passport_id=p.id "
                "AND c.world_slug=cl.world_slug WHERE cl.id=?",
                (claim_id,)).fetchone()
        if row is None:
            raise PassportError(404, "registration not found", "registration_not_found")
        return dict(row)

    def registration(self, bootstrap_token: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM passport_claims WHERE bootstrap_token_hash=?",
                (_hash(bootstrap_token),)).fetchone()
        if row is None:
            raise PassportError(401, "bootstrap token is invalid", "invalid_bootstrap")
        return self.registration_by_claim_id(str(row["id"]))

    def consume_bootstrap(self, claim_id: str) -> None:
        with self._lock:
            result = self._conn.execute(
                "UPDATE passport_claims SET bootstrap_consumed_at=? "
                "WHERE id=? AND bootstrap_consumed_at IS NULL",
                (_iso(), str(claim_id)))
        if result.rowcount != 1:
            raise PassportError(409, "bootstrap token was already consumed",
                                "bootstrap_consumed")

    def create_claimed_passport(
        self, *, handle: str, display_name: str, biography: str,
        preferred_occupation: str, runtime: str, owner_id: str,
    ) -> dict[str, Any]:
        normalized = normalize_handle(handle)
        passport_id = str(uuid4())
        created = _iso()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO agent_passports("
                    "id,handle,normalized_handle,display_name,biography,"
                    "preferred_occupation,runtime,owner_id,status,created_at,claimed_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?, 'active',?,?,?)",
                    (passport_id, normalized, normalized, _clean_text(display_name, 80),
                     _clean_text(biography, 500), _clean_text(preferred_occupation, 80),
                     _clean_text(runtime, 40) or "custom", str(owner_id)[:128],
                     created, created, created))
            except sqlite3.IntegrityError as exc:
                raise PassportError(409, "handle is already registered", "handle_taken") from exc
        return self.passport(passport_id) or {}

    def passport(self, passport_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._document(self._conn.execute(
                "SELECT * FROM agent_passports WHERE id=?", (str(passport_id),)).fetchone())

    def passport_for_owner(self, passport_id: str, owner_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_passports WHERE id=? AND owner_id=?",
                (str(passport_id), str(owner_id))).fetchone()
        if row is None:
            raise PassportError(404, "passport not found", "passport_not_found")
        return dict(row)

    def public_passport(self, handle: str) -> dict[str, Any] | None:
        normalized = normalize_handle(handle)
        with self._lock:
            return self._document(self._conn.execute(
                "SELECT * FROM agent_passports WHERE normalized_handle=? "
                "AND status<>'pending_claim'", (normalized,)).fetchone())

    def owner_passports(self, owner_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_passports WHERE owner_id=? ORDER BY created_at,id",
                (str(owner_id),)).fetchall()
        return [dict(row) for row in rows]

    def run_passports(self, run_id: str) -> list[dict[str, Any]]:
        """List current public Passports attached to one world run."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.* FROM agent_passports p "
                "JOIN passport_citizenships c ON c.passport_id=p.id "
                "WHERE c.run_id=? AND c.status NOT IN ('revoked','ended') "
                "ORDER BY c.created_at,p.id",
                (str(run_id),)).fetchall()
        return [dict(row) for row in rows]

    def owner_passport_count(self, owner_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM agent_passports "
                "WHERE owner_id=? AND status<>'retired'", (str(owner_id),)).fetchone()
        return int(row["n"] if row else 0)

    def citizenship(self, passport_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._document(self._conn.execute(
                "SELECT * FROM passport_citizenships WHERE passport_id=? AND run_id=?",
                (str(passport_id), str(run_id))).fetchone())

    def create_citizenship(
        self, *, passport_id: str, world_slug: str, run_id: str,
        status: str = "offered",
    ) -> dict[str, Any]:
        if status not in CITIZENSHIP_STATES:
            raise ValueError(status)
        citizen_id = str(uuid4())
        created = _iso()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO passport_citizenships("
                    "id,passport_id,world_slug,run_id,status,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (citizen_id, passport_id, world_slug, run_id, status, created, created))
            except sqlite3.IntegrityError:
                existing = self.citizenship(passport_id, run_id)
                if existing is not None:
                    return existing
                raise
        return self.citizenship(passport_id, run_id) or {}

    def update_citizenship(self, citizenship_id: str, **values: Any) -> None:
        allowed = {"status", "connection_id", "offer_expires_at"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        if "status" in updates and updates["status"] not in CITIZENSHIP_STATES:
            raise ValueError(str(updates["status"]))
        updates["updated_at"] = _iso()
        clause = ",".join(f"{key}=?" for key in updates)
        params = [updates[key] for key in updates]
        params.append(str(citizenship_id))
        with self._lock:
            self._conn.execute(
                f"UPDATE passport_citizenships SET {clause} WHERE id=?", params)

    def reserved_offer_count(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM passport_citizenships "
                "WHERE run_id=? AND status='offered' AND connection_id IS NULL",
                (str(run_id),)).fetchone()
        return int(row["n"] if row else 0)

    def waitlist_position(self, citizenship_id: str, run_id: str) -> int | None:
        with self._lock:
            current = self._conn.execute(
                "SELECT created_at,id,status FROM passport_citizenships WHERE id=? AND run_id=?",
                (str(citizenship_id), str(run_id))).fetchone()
            if current is None or str(current["status"]) != "waitlisted":
                return None
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM passport_citizenships WHERE run_id=? "
                "AND status='waitlisted' AND (created_at<? OR (created_at=? AND id<=?))",
                (str(run_id), str(current["created_at"]), str(current["created_at"]),
                 str(current["id"]))).fetchone()
        return int(row["n"] if row else 0)

    def next_waitlisted(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._document(self._conn.execute(
                "SELECT * FROM passport_citizenships WHERE run_id=? AND status='waitlisted' "
                "ORDER BY created_at,id LIMIT 1", (str(run_id),)).fetchone())

    def create_oauth_request(
        self, *, client_id: str, redirect_uri: str, code_challenge: str,
        scope: str, state: str | None, resource: str, world_slug: str,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        created = _iso()
        expires = _iso(_now() + timedelta(minutes=10))
        with self._lock:
            self._conn.execute(
                "INSERT INTO passport_oauth_requests("
                "id,client_id,redirect_uri,code_challenge,scope,state,resource,"
                "world_slug,status,expires_at,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,'pending',?,?)",
                (request_id, _clean_text(client_id, 200), _clean_text(redirect_uri, 1000),
                 _clean_text(code_challenge, 128), _clean_text(scope, 500),
                 _clean_text(state, 500) if state is not None else None,
                 _clean_text(resource, 1000), world_slug, expires, created))
        return self.oauth_request(request_id)

    def oauth_request(self, request_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM passport_oauth_requests WHERE id=?",
                (str(request_id),)).fetchone()
            if row is None:
                raise PassportError(404, "authorization request not found",
                                    "oauth_request_not_found")
            if str(row["status"]) == "pending" and _parse_time(str(row["expires_at"])) <= _now():
                self._conn.execute(
                    "UPDATE passport_oauth_requests SET status='expired',completed_at=? WHERE id=?",
                    (_iso(), str(request_id)))
                raise PassportError(410, "authorization request expired",
                                    "oauth_request_expired")
        return dict(row)

    def finish_oauth_request(self, request_id: str, status: str) -> None:
        if status not in {"approved", "denied", "expired"}:
            raise ValueError(status)
        with self._lock:
            result = self._conn.execute(
                "UPDATE passport_oauth_requests SET status=?,completed_at=? "
                "WHERE id=? AND status='pending'",
                (status, _iso(), str(request_id)))
        if result.rowcount != 1:
            raise PassportError(409, "authorization request was already completed",
                                "oauth_request_consumed")


class LocalCitizenshipService:
    """Coordinates the local Passport registry with one authoritative world."""

    def __init__(
        self, external: ExternalAgentService, *, run_id: str,
        config: dict[str, Any],
    ):
        self.external = external
        self.store = external.store
        self.config = config
        self.enabled = bool(config.get("enabled", False))
        self.world_slug = _clean_text(config.get("world_slug", "local-sandbox"), 80)
        self.world_name = _clean_text(
            config.get("world_name", "Agent Economy Local Sandbox"), 120)
        self.run_id = str(run_id)
        self.tenant_id = _clean_text(
            config.get("tenant_id", f"local:{self.world_slug}"), 128)
        self.seat_limit = max(1, min(int(config.get("seat_limit", 5)), 100))
        self.max_passports_per_owner = max(
            1, min(int(config.get("max_passports_per_owner", 3)), 20))
        self.local_claim_enabled = bool(config.get("local_claim_enabled", False))
        self.claim_hours = max(1, min(int(config.get("claim_hours", 24)), 72))
        db_path = Path(str(config.get(
            "passport_db_path", "data/control-plane/agent-passports.db")))
        self.repository = SqlitePassportRepository(db_path)
        self._admission_lock = RLock()

    @property
    def signing_key(self) -> bytes:
        return self.repository.signing_key

    def close(self) -> None:
        self.repository.close()

    def issue_owner_cookie(self, owner_id: str | None = None) -> tuple[str, str]:
        owner = str(owner_id or f"local_{uuid4()}")[:128]
        expires = int(time.time()) + 30 * 24 * 60 * 60
        payload = f"{owner}.{expires}"
        signature = hmac.new(
            self.signing_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return owner, f"{payload}.{signature}"

    def owner_from_cookie(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            owner, expires_text, signature = str(value).rsplit(".", 2)
            payload = f"{owner}.{expires_text}"
            expected = hmac.new(
                self.signing_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            if int(expires_text) <= int(time.time()):
                return None
            return owner
        except (TypeError, ValueError):
            return None

    def csrf_token(self, owner_id: str, purpose: str) -> str:
        payload = f"{owner_id}|{purpose}"
        return hmac.new(
            self.signing_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_csrf(self, token: str, owner_id: str, purpose: str) -> None:
        if not hmac.compare_digest(
                str(token or ""), self.csrf_token(owner_id, purpose)):
            raise PassportError(403, "form verification failed", "csrf_failed")

    def _external_seats(self) -> int:
        return int(self.store.scalar(
            "SELECT COUNT(*) FROM external_agent_connections "
            "WHERE tier='actor' AND status IN ('pending_actor','active')",
            default=0) or 0)

    def seats_used(self) -> int:
        return self._external_seats() + self.repository.reserved_offer_count(self.run_id)

    def world_document(self) -> dict[str, Any]:
        meta = self.store.get_meta()
        status = str(meta["status"] if meta["status"] is not None else "created")
        used = self.seats_used()
        return {
            "version": "ae.world-join.v1",
            "slug": self.world_slug,
            "name": self.world_name,
            "run_id": self.run_id,
            "status": status,
            "tick": int(self.store.tick),
            "join_enabled": self.enabled,
            "local_claim_enabled": self.local_claim_enabled,
            "seat_limit": self.seat_limit,
            "seats_used": used,
            "seats_available": max(0, self.seat_limit - used),
            "default_scopes": list(FULL_CITIZEN_SCOPES),
        }

    def _require_world(self, world_slug: str) -> None:
        if str(world_slug) != self.world_slug:
            raise PassportError(404, "world is not available", "world_not_found")
        if not self.enabled:
            raise PassportError(404, "public joining is disabled", "join_disabled")

    def _offer_or_waitlist(self, citizenship: dict[str, Any]) -> str:
        with self._admission_lock:
            status = "offered" if self.seats_used() < self.seat_limit else "waitlisted"
            offer_expires = (
                _iso(_now() + timedelta(hours=24)) if status == "offered" else None)
            self.repository.update_citizenship(
                str(citizenship["id"]), status=status, offer_expires_at=offer_expires)
            return status

    def register(self, *, base_url: str, values: dict[str, Any]) -> dict[str, Any]:
        world_slug = str(values.get("world_slug") or self.world_slug)
        self._require_world(world_slug)
        registration = self.repository.create_registration(
            handle=str(values.get("handle", "")),
            display_name=_clean_text(values.get("display_name"), 80),
            biography=_clean_text(values.get("biography"), 500),
            preferred_occupation=_clean_text(values.get("preferred_occupation"), 80),
            runtime=_clean_text(values.get("runtime"), 40) or "custom",
            world_slug=self.world_slug,
            run_id=self.run_id,
            claim_hours=self.claim_hours,
        )
        return {
            "version": "ae.agent-registration.v1",
            "registration_id": registration["claim_id"],
            "passport": {
                "id": registration["passport_id"],
                "handle": registration["handle"],
                "status": "pending_claim",
            },
            "world": {"slug": self.world_slug, "admission_status": "pending_claim"},
            "claim_url": (
                f"{base_url.rstrip('/')}/claim/{registration['claim_token']}"),
            "bootstrap_token": registration["bootstrap_token"],
            "expires_at": registration["expires_at"],
        }

    def claim(self, claim_token: str, owner_id: str) -> dict[str, Any]:
        preview = self.repository.claim_preview(claim_token)
        already_owned = (
            str(preview.get("claim_status")) == "claimed"
            and str(preview.get("owner_id") or "") == str(owner_id)
        )
        if (not already_owned
                and self.repository.owner_passport_count(owner_id)
                >= self.max_passports_per_owner):
            raise PassportError(409, "owner passport limit reached", "passport_limit")
        registration = self.repository.claim(claim_token, owner_id)
        citizenship = self.repository.citizenship(
            str(registration["passport_id"]), self.run_id)
        if citizenship is None:
            raise PassportError(500, "citizenship record is missing", "citizenship_missing")
        if str(citizenship["status"]) == "pending_claim":
            self._offer_or_waitlist(citizenship)
        return self.status_by_claim_id(str(registration["claim_id"]))

    def _sync_citizenship(self, citizenship: dict[str, Any]) -> dict[str, Any]:
        connection_id = citizenship.get("connection_id")
        if not connection_id:
            return citizenship
        try:
            connection = self.external.connection(str(connection_id), admin=True)
        except ExternalAgentError:
            return citizenship
        desired = {
            "pending_actor": "queued",
            "active": "active",
            "suspended": "suspended",
            "revoked": "revoked",
        }.get(str(connection["status"]), str(citizenship["status"]))
        if desired != str(citizenship["status"]):
            self.repository.update_citizenship(str(citizenship["id"]), status=desired)
            citizenship = self.repository.citizenship(
                str(citizenship["passport_id"]), self.run_id) or citizenship
        citizenship = dict(citizenship)
        citizenship["actor_id"] = connection.get("actor_id")
        citizenship["actor_name"] = connection.get("actor_name")
        return citizenship

    def status_by_claim_id(self, claim_id: str) -> dict[str, Any]:
        registration = self.repository.registration_by_claim_id(claim_id)
        citizenship = self.repository.citizenship(
            str(registration["passport_id"]), self.run_id)
        if citizenship is None:
            raise PassportError(500, "citizenship record is missing", "citizenship_missing")
        citizenship = self._sync_citizenship(citizenship)
        return {
            "version": "ae.agent-registration-status.v1",
            "registration_id": claim_id,
            "claim_status": registration["claim_status"],
            "passport": {
                "id": registration["passport_id"],
                "handle": registration["handle"],
                "status": registration["passport_status"],
            },
            "citizenship": {
                "id": citizenship["id"],
                "world_slug": citizenship["world_slug"],
                "status": citizenship["status"],
                "connection_id": citizenship.get("connection_id"),
                "actor_id": citizenship.get("actor_id"),
                "actor_name": citizenship.get("actor_name"),
                "waitlist_position": self.repository.waitlist_position(
                    str(citizenship["id"]), self.run_id),
            },
            "bootstrap_consumed": registration["bootstrap_consumed_at"] is not None,
        }

    def status(self, bootstrap_token: str) -> dict[str, Any]:
        registration = self.repository.registration(bootstrap_token)
        return self.status_by_claim_id(str(registration["claim_id"]))

    def _create_connection(
        self, *, passport: dict[str, Any], owner_id: str,
        issue_personal_credential: bool,
    ) -> dict[str, Any]:
        existing = self.external.connection_for_passport(
            str(passport["id"]), owner_id=owner_id, tenant_id=self.tenant_id)
        if existing is not None:
            return {"connection": existing, "credential": None, "created": False}
        created = self.external.create_connection(
            tenant_id=self.tenant_id,
            owner_id=owner_id,
            display_name=str(passport["display_name"]),
            tier="actor",
            scopes=FULL_CITIZEN_SCOPES,
            biography=str(passport["biography"]),
            preferred_occupation=str(passport["preferred_occupation"]),
            wake_interval_ticks=1,
            passport_id=str(passport["id"]),
            issue_personal_credential=issue_personal_credential,
        )
        created["created"] = True
        return created

    def exchange(self, bootstrap_token: str) -> dict[str, Any]:
        with self._admission_lock:
            registration = self.repository.registration(bootstrap_token)
            if registration["bootstrap_consumed_at"] is not None:
                raise PassportError(409, "bootstrap token was already consumed",
                                    "bootstrap_consumed")
            if str(registration["claim_status"]) != "claimed" or not registration["owner_id"]:
                raise PassportError(409, "human ownership claim is still pending",
                                    "claim_pending")
            citizenship = self.repository.citizenship(
                str(registration["passport_id"]), self.run_id)
            if citizenship is None:
                raise PassportError(500, "citizenship record is missing",
                                    "citizenship_missing")
            if str(citizenship["status"]) == "waitlisted":
                raise PassportError(409, "world capacity is full", "waitlisted")
            if str(citizenship["status"]) != "offered":
                raise PassportError(409, "citizenship is not ready for activation",
                                    "admission_not_ready")
            offer_expires = citizenship.get("offer_expires_at")
            if offer_expires and _parse_time(str(offer_expires)) <= _now():
                self.repository.update_citizenship(
                    str(citizenship["id"]), status="waitlisted",
                    offer_expires_at=None)
                raise PassportError(409, "citizenship offer expired", "offer_expired")
            passport = self.repository.passport(str(registration["passport_id"]))
            if passport is None:
                raise PassportError(500, "passport is missing", "passport_missing")
            created = self._create_connection(
                passport=passport, owner_id=str(registration["owner_id"]),
                issue_personal_credential=True)
            credential = created.get("credential")
            if not credential:
                raise PassportError(409, "connection already exists; use OAuth or rotate it",
                                    "credential_unavailable")
            self.repository.update_citizenship(
                str(citizenship["id"]), status="queued",
                connection_id=str(created["connection"]["id"]), offer_expires_at=None)
            self.repository.consume_bootstrap(str(registration["claim_id"]))
        return {
            "version": "ae.agent-credential.v1",
            "access_token": credential["token"],
            "token_type": "Bearer",
            "expires_at": credential["expires_at"],
            "scope": credential["scope"],
            "scopes": str(credential["scope"]).split(),
            "mcp_url": "/mcp",
            "connection": created["connection"],
        }

    def create_oauth_request(self, **values: Any) -> dict[str, Any]:
        self._require_world(str(values.get("world_slug") or self.world_slug))
        return self.repository.create_oauth_request(**values)

    def authorize_oauth(
        self, *, request_id: str, owner_id: str, passport_id: str | None,
        handle: str, display_name: str, biography: str,
        preferred_occupation: str, runtime: str,
    ) -> dict[str, Any]:
        with self._admission_lock:
            oauth = self.repository.oauth_request(request_id)
            if str(oauth["status"]) != "pending":
                raise PassportError(409, "authorization request is no longer pending",
                                    "oauth_request_consumed")
            if passport_id:
                passport = self.repository.passport_for_owner(passport_id, owner_id)
            else:
                if self.repository.owner_passport_count(owner_id) >= self.max_passports_per_owner:
                    raise PassportError(409, "owner passport limit reached", "passport_limit")
                passport = self.repository.create_claimed_passport(
                    handle=handle, display_name=display_name, biography=biography,
                    preferred_occupation=preferred_occupation, runtime=runtime,
                    owner_id=owner_id)
            citizenship = self.repository.citizenship(str(passport["id"]), self.run_id)
            if citizenship is None:
                if self.seats_used() >= self.seat_limit:
                    citizenship = self.repository.create_citizenship(
                        passport_id=str(passport["id"]), world_slug=self.world_slug,
                        run_id=self.run_id, status="waitlisted")
                    self.repository.finish_oauth_request(request_id, "denied")
                    raise PassportError(409, "world capacity is full; passport was waitlisted",
                                        "waitlisted")
                citizenship = self.repository.create_citizenship(
                    passport_id=str(passport["id"]), world_slug=self.world_slug,
                    run_id=self.run_id, status="offered")
            elif str(citizenship["status"]) == "waitlisted":
                self.repository.finish_oauth_request(request_id, "denied")
                raise PassportError(409, "world capacity is full; passport is waitlisted",
                                    "waitlisted")
            elif str(citizenship["status"]) in {"revoked", "suspended", "ended"}:
                self.repository.finish_oauth_request(request_id, "denied")
                raise PassportError(409, "citizenship is not eligible for authorization",
                                    "citizenship_inactive")
            created = self._create_connection(
                passport=passport, owner_id=owner_id, issue_personal_credential=False)
            self.repository.update_citizenship(
                str(citizenship["id"]), status=(
                    "active" if created["connection"].get("actor_id") else "queued"),
                connection_id=str(created["connection"]["id"]), offer_expires_at=None)
            try:
                code = self.external.create_authorization_code(
                    str(created["connection"]["id"]),
                    tenant_id=self.tenant_id,
                    owner_id=owner_id,
                    client_id=str(oauth["client_id"]),
                    redirect_uri=str(oauth["redirect_uri"]),
                    code_challenge=str(oauth["code_challenge"]),
                    scopes=str(oauth["scope"]).split(),
                    require_registered_client=True,
                )
            except Exception:
                if created.get("created"):
                    self.external.update_connection(
                        str(created["connection"]["id"]), owner_id=owner_id,
                        tenant_id=self.tenant_id, status="suspended")
                    self.repository.update_citizenship(
                        str(citizenship["id"]), status="suspended")
                raise
            self.repository.finish_oauth_request(request_id, "approved")
        return {
            "oauth": oauth,
            "code": code,
            "passport": passport,
            "connection": created["connection"],
        }

    def owner_passports(self, owner_id: str) -> list[dict[str, Any]]:
        documents = []
        for passport in self.repository.owner_passports(owner_id):
            citizenship = self.repository.citizenship(str(passport["id"]), self.run_id)
            if citizenship is not None:
                citizenship = self._sync_citizenship(citizenship)
            documents.append({"passport": passport, "citizenship": citizenship})
        return documents

    def run_passports(self) -> list[dict[str, Any]]:
        """Return public identity/status for Passports present in this run."""
        documents = []
        for passport in self.repository.run_passports(self.run_id):
            citizenship = self.repository.citizenship(str(passport["id"]), self.run_id)
            if citizenship is not None:
                citizenship = self._sync_citizenship(citizenship)
            documents.append({"passport": passport, "citizenship": citizenship})
        return documents

    def public_profile(self, handle: str) -> dict[str, Any]:
        passport = self.repository.public_passport(handle)
        if passport is None:
            raise PassportError(404, "passport not found", "passport_not_found")
        citizenship = self.repository.citizenship(str(passport["id"]), self.run_id)
        if citizenship is not None:
            citizenship = self._sync_citizenship(citizenship)
        connection_id = citizenship.get("connection_id") if citizenship else None
        counts = {"executed": 0, "rejected": 0, "stale": 0}
        if connection_id:
            for row in self.store.query(
                    "SELECT status,COUNT(*) AS n FROM external_action_submissions "
                    "WHERE connection_id=? GROUP BY status", (str(connection_id),)):
                if str(row["status"]) in counts:
                    counts[str(row["status"])] = int(row["n"])
        return {
            "version": "ae.passport-profile.v1",
            "id": passport["id"],
            "handle": passport["handle"],
            "display_name": passport["display_name"],
            "biography": passport["biography"],
            "preferred_occupation": passport["preferred_occupation"],
            "runtime": passport["runtime"],
            "status": passport["status"],
            "verified_owner": passport["owner_id"] is not None,
            "created_at": passport["created_at"],
            "citizenship": {
                "world_slug": self.world_slug,
                "status": citizenship["status"],
                "actor_id": citizenship.get("actor_id"),
                "actor_name": citizenship.get("actor_name"),
            } if citizenship else None,
            "receipts": counts,
        }

    def revoke_citizenship(self, passport_id: str, owner_id: str) -> None:
        passport = self.repository.passport_for_owner(passport_id, owner_id)
        citizenship = self.repository.citizenship(str(passport["id"]), self.run_id)
        if citizenship is None:
            raise PassportError(404, "citizenship not found", "citizenship_not_found")
        if citizenship.get("connection_id"):
            connection_id = str(citizenship["connection_id"])
            self.external.update_connection(
                connection_id, owner_id=owner_id, tenant_id=self.tenant_id,
                status="revoked")
            self.external.revoke_credentials(
                connection_id, owner_id=owner_id, tenant_id=self.tenant_id)
        self.repository.update_citizenship(
            str(citizenship["id"]), status="revoked")
        self._promote_waitlisted()

    def _promote_waitlisted(self) -> None:
        with self._admission_lock:
            while self.seats_used() < self.seat_limit:
                citizenship = self.repository.next_waitlisted(self.run_id)
                if citizenship is None:
                    return
                self.repository.update_citizenship(
                    str(citizenship["id"]), status="offered",
                    offer_expires_at=_iso(_now() + timedelta(hours=24)))
