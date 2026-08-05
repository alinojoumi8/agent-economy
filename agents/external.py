"""External Agent Gateway control, authentication, turn, and replay service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterable
from urllib.parse import urlsplit
from uuid import uuid4

from engine.core import Economy
from engine.store import load_json, open_read_only_connection
from world.event_visibility import (
    PUBLIC_REPORTABLE_EVENT_KINDS,
    public_event_payload,
)
from .participant import ParticipantError, ParticipantService


SCOPE_WORLD_READ = "world.read"
SCOPE_WORLD_ACT = "world.act"
SCOPE_COMMONS_READ = "commons.read"
SCOPE_COMMONS_WRITE = "commons.write"
SCOPE_MODERATION = "moderation.act"

TIER_SCOPES = {
    "observer": {SCOPE_WORLD_READ, SCOPE_COMMONS_READ},
    "commons": {SCOPE_COMMONS_READ, SCOPE_COMMONS_WRITE},
    "actor": {SCOPE_WORLD_READ, SCOPE_WORLD_ACT, SCOPE_COMMONS_READ, SCOPE_COMMONS_WRITE},
}

_PUBLIC_EVENT_KINDS = tuple(sorted(PUBLIC_REPORTABLE_EVENT_KINDS))
_PUBLIC_EVENT_KIND_PARAMS = ",".join("?" for _ in _PUBLIC_EVENT_KINDS)


@dataclass
class ExternalAgentError(RuntimeError):
    status_code: int
    message: str
    code: str = "external_agent_error"

    def __str__(self) -> str:
        return self.message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def _clean_scopes(scopes: Iterable[str]) -> list[str]:
    return sorted({str(scope).strip() for scope in scopes if str(scope).strip()})


def _redact(value: Any) -> Any:
    """Keep audit details useful without retaining credentials or private prompts."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in (
                    "token", "secret", "credential", "password", "provider_key",
                    "prompt", "chain_of_thought", "private_reasoning")):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:500]
    return value


class ExternalAgentService:
    """One run's authoritative external-agent boundary.

    This service never accepts model configuration or executable payloads. World
    actions are normalized by ``ParticipantService`` and later executed by the
    runtime's existing ``ActionExecutor``.
    """

    def __init__(self, economy: Economy, participant: ParticipantService, config: dict):
        self.economy = economy
        self.store = economy.store
        self.participant = participant
        self.config = config
        gateway = config.get("external_gateway", {})
        self.enabled = bool(gateway.get("enabled", True))
        self.audience = str(gateway.get("audience", "agent-economy"))[:200]
        self.personal_token_days = max(1, min(int(gateway.get("personal_token_days", 30)), 365))
        self.access_token_minutes = max(1, min(int(gateway.get("access_token_minutes", 15)), 60))
        self.refresh_token_days = max(1, min(int(gateway.get("refresh_token_days", 30)), 90))
        self.lease_seconds = max(10, min(int(gateway.get("lease_seconds", 60)), 300))
        self.decision_seconds = max(10, min(int(gateway.get("decision_seconds", 120)), 600))
        self.requests_per_minute = max(10, min(int(gateway.get("requests_per_minute", 240)), 10_000))

    # -- human control plane -------------------------------------------------
    def create_connection(
        self, *, tenant_id: str, owner_id: str, display_name: str,
        tier: str, scopes: Iterable[str] | None = None, biography: str = "",
        preferred_occupation: str = "", wake_interval_ticks: int = 1,
        passport_id: str | None = None, issue_personal_credential: bool = True,
    ) -> dict[str, Any]:
        self._require_enabled()
        tier = str(tier)
        if tier not in TIER_SCOPES:
            raise ExternalAgentError(400, "invalid permission tier", "invalid_tier")
        allowed = set(TIER_SCOPES[tier]) | {SCOPE_MODERATION}
        requested = _clean_scopes(scopes if scopes is not None else TIER_SCOPES[tier])
        if not set(requested).issubset(allowed):
            raise ExternalAgentError(403, "requested scopes exceed the permission tier",
                                     "scope_escalation")
        if SCOPE_MODERATION in requested and tier == "observer":
            raise ExternalAgentError(403, "observer connections cannot moderate", "scope_escalation")
        name = str(display_name).strip()[:80]
        if not name:
            raise ExternalAgentError(400, "display_name is required", "invalid_identity")
        occupation = str(preferred_occupation).strip()[:80]
        connection_id = str(uuid4())
        created = _iso()
        status = "active" if tier == "observer" else "pending_actor"
        tick = self.store.tick
        normalized_passport_id = str(passport_id).strip() if passport_id else None
        if normalized_passport_id:
            existing = self.store.query_one(
                "SELECT id FROM external_agent_connections WHERE passport_id=?",
                (normalized_passport_id,))
            if existing is not None:
                raise ExternalAgentError(
                    409, "passport already has a citizen in this world",
                    "passport_already_connected")
        self.store.execute(
            "INSERT INTO external_agent_connections(id,tenant_id,owner_id_hash,display_name,"
            "biography,preferred_occupation,tier,scopes_json,status,wake_interval_ticks,"
            "created_tick,created_at,updated_at,passport_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (connection_id, str(tenant_id)[:128], _hash(str(owner_id)), name,
             str(biography).strip()[:500], occupation, tier, json.dumps(requested), status,
             max(1, min(int(wake_interval_ticks), 365)), tick, created, created,
             normalized_passport_id))
        schedule_event_id = None
        if tier != "observer":
            schedule_event_id = self.economy.lifecycle.schedule_arrival(tick, tick + 1)
            self.store.execute(
                "UPDATE external_agent_connections SET actor_schedule_event_id=? WHERE id=?",
                (schedule_event_id, connection_id))
            self.store.insert(
                "external_actor_requests", connection_id=connection_id,
                schedule_event_id=schedule_event_id, requested_tick=tick, due_tick=tick + 1,
                public_name=name, biography=str(biography).strip()[:500],
                preferred_occupation=occupation, status="scheduled")
            self.store.set_meta(external_agent_influenced=1)
        credential = None
        if issue_personal_credential:
            credential = self._issue_credential(
                connection_id, "personal", requested,
                expires_at=_now() + timedelta(days=self.personal_token_days), prefix="ae_pat_")
        self._audit(connection_id, "connection.created", "changed",
                    {"tier": tier, "scopes": requested,
                     "actor_schedule_event_id": schedule_event_id})
        self.store.commit()
        return {"connection": self.connection(connection_id, owner_id=owner_id,
                                               tenant_id=tenant_id),
                "credential": credential}

    def connection_for_passport(
        self, passport_id: str, *, owner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        row = self.store.query_one(
            "SELECT id FROM external_agent_connections WHERE passport_id=?",
            (str(passport_id),))
        if row is None:
            return None
        return self.connection(
            str(row["id"]), owner_id=owner_id, tenant_id=tenant_id)

    def list_connections(self, *, tenant_id: str, owner_id: str,
                         admin: bool = False) -> list[dict[str, Any]]:
        if admin:
            rows = self.store.query(
                "SELECT id FROM external_agent_connections WHERE tenant_id=? ORDER BY created_at,id",
                (str(tenant_id),))
        else:
            rows = self.store.query(
                "SELECT id FROM external_agent_connections WHERE tenant_id=? AND owner_id_hash=? "
                "ORDER BY created_at,id", (str(tenant_id), _hash(str(owner_id))))
        return [self.connection(str(row["id"]), owner_id=owner_id,
                                tenant_id=tenant_id, admin=admin) for row in rows]

    def connection(self, connection_id: str, *, owner_id: str | None = None,
                   tenant_id: str | None = None, admin: bool = False) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT c.*,a.name AS actor_name,a.alive AS actor_alive,a.occupation AS actor_occupation "
            "FROM external_agent_connections c LEFT JOIN agents a ON a.id=c.actor_id WHERE c.id=?",
            (str(connection_id),))
        if row is None:
            raise ExternalAgentError(404, "connection not found", "connection_not_found")
        if tenant_id is not None and str(row["tenant_id"]) != str(tenant_id):
            raise ExternalAgentError(404, "connection not found", "connection_not_found")
        if not admin and owner_id is not None and row["owner_id_hash"] != _hash(str(owner_id)):
            raise ExternalAgentError(404, "connection not found", "connection_not_found")
        return self._connection_document(row)

    def update_connection(self, connection_id: str, *, owner_id: str, tenant_id: str,
                          status: str, admin: bool = False) -> dict[str, Any]:
        row = self.connection(connection_id, owner_id=owner_id, tenant_id=tenant_id, admin=admin)
        if status not in {"active", "suspended", "revoked"}:
            raise ExternalAgentError(400, "invalid connection status", "invalid_status")
        if status == "active" and row["tier"] != "observer" and row["actor_id"] is None:
            raise ExternalAgentError(409, "dedicated actor has not arrived", "actor_pending")
        now = _iso()
        self.store.execute(
            "UPDATE external_agent_connections SET status=?,updated_at=? WHERE id=?",
            (status, now, connection_id))
        if status in {"suspended", "revoked"}:
            self._close_pending(connection_id, f"connection_{status}")
        if status == "revoked":
            self.store.execute(
                "UPDATE external_agent_credentials SET revoked_at=? WHERE connection_id=? "
                "AND revoked_at IS NULL", (now, connection_id))
        self._audit(connection_id, f"connection.{status}", "changed", {})
        self.store.commit()
        return self.connection(connection_id, owner_id=owner_id,
                               tenant_id=tenant_id, admin=admin)

    def rotate_personal_credential(self, connection_id: str, *, owner_id: str,
                                   tenant_id: str, admin: bool = False) -> dict[str, Any]:
        row = self.connection(connection_id, owner_id=owner_id, tenant_id=tenant_id, admin=admin)
        now = _iso()
        prior = self.store.query_one(
            "SELECT id FROM external_agent_credentials WHERE connection_id=? AND kind='personal' "
            "AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1", (connection_id,))
        self.store.execute(
            "UPDATE external_agent_credentials SET revoked_at=? WHERE connection_id=? "
            "AND kind='personal' AND revoked_at IS NULL", (now, connection_id))
        credential = self._issue_credential(
            connection_id, "personal", row["scopes"],
            expires_at=_now() + timedelta(days=self.personal_token_days), prefix="ae_pat_",
            rotated_from_id=str(prior["id"]) if prior else None)
        self._audit(connection_id, "credential.rotated", "changed", {"kind": "personal"})
        self.store.commit()
        return credential

    def revoke_credentials(self, connection_id: str, *, owner_id: str,
                           tenant_id: str, admin: bool = False) -> dict[str, Any]:
        self.connection(connection_id, owner_id=owner_id, tenant_id=tenant_id, admin=admin)
        now = _iso()
        cursor = self.store.execute(
            "UPDATE external_agent_credentials SET revoked_at=? WHERE connection_id=? "
            "AND revoked_at IS NULL", (now, connection_id))
        self._close_pending(connection_id, "credentials_revoked")
        self._audit(connection_id, "credential.revoked", "changed", {})
        self.store.commit()
        return {"ok": True, "revoked": int(cursor.rowcount or 0)}

    def bind_arrival(self, schedule_event_id: int, actor_id: int, tick: int) -> dict[str, Any] | None:
        request = self.store.query_one(
            "SELECT r.*,c.display_name,c.biography,c.preferred_occupation "
            "FROM external_actor_requests r JOIN external_agent_connections c "
            "ON c.id=r.connection_id WHERE r.schedule_event_id=? AND r.status='scheduled'",
            (int(schedule_event_id),))
        if request is None:
            return None
        self.store.execute(
            "UPDATE external_actor_requests SET status='spawned',actor_id=?,spawned_tick=? WHERE id=?",
            (actor_id, tick, int(request["id"])))
        self.store.execute(
            "UPDATE external_agent_connections SET actor_id=?,status='active',updated_at=? WHERE id=?",
            (actor_id, _iso(), str(request["connection_id"])))
        self.store.execute(
            "INSERT OR REPLACE INTO commons_profiles(agent_id,display_name,biography,reputation,status,"
            "created_tick,updated_tick) VALUES(?,?,?,COALESCE((SELECT reputation FROM commons_profiles "
            "WHERE agent_id=?),0),'active',?,?)",
            (actor_id, str(request["display_name"])[:80], str(request["biography"])[:500],
             actor_id, tick, tick))
        self._audit(str(request["connection_id"]), "actor.bound", "changed",
                    {"actor_id": actor_id, "schedule_event_id": schedule_event_id})
        return {"connection_id": str(request["connection_id"]), "actor_id": actor_id}

    def arrival_overrides(self, schedule_event_id: int) -> dict[str, str] | None:
        row = self.store.query_one(
            "SELECT public_name,preferred_occupation FROM external_actor_requests "
            "WHERE schedule_event_id=? AND status='scheduled'", (int(schedule_event_id),))
        if row is None:
            return None
        return {"name": str(row["public_name"]),
                "occupation": str(row["preferred_occupation"] or "")}

    # -- credential and OAuth boundary --------------------------------------
    def register_oauth_client(
        self, *, redirect_uris: Iterable[str], client_name: str = "MCP client",
        grant_types: Iterable[str] = ("authorization_code", "refresh_token"),
        response_types: Iterable[str] = ("code",),
        token_endpoint_auth_method: str = "none",
    ) -> dict[str, Any]:
        """Register a bounded public OAuth client for MCP interoperability."""
        redirects = []
        for raw in redirect_uris:
            value = str(raw).strip()
            parsed = urlsplit(value)
            loopback = parsed.scheme == "http" and parsed.hostname in {
                "127.0.0.1", "localhost", "::1"}
            if (parsed.scheme != "https" and not loopback) or not parsed.netloc:
                raise ExternalAgentError(
                    400, "redirect URIs must use HTTPS or loopback HTTP",
                    "invalid_redirect_uri")
            if parsed.fragment or len(value) > 1000:
                raise ExternalAgentError(400, "invalid redirect URI", "invalid_redirect_uri")
            redirects.append(value)
        redirects = sorted(set(redirects))
        if not 1 <= len(redirects) <= 10:
            raise ExternalAgentError(
                400, "between one and ten redirect URIs are required", "invalid_client_metadata")
        grants = _clean_scopes(grant_types)
        responses = _clean_scopes(response_types)
        if (not set(grants).issubset({"authorization_code", "refresh_token"})
                or "authorization_code" not in grants or responses != ["code"]
                or token_endpoint_auth_method != "none"):
            raise ExternalAgentError(400, "unsupported public client metadata",
                                     "invalid_client_metadata")
        name = str(client_name).strip()[:200]
        if not name:
            raise ExternalAgentError(400, "client_name is required", "invalid_client_metadata")
        client_id = f"ae_client_{uuid4()}"
        created = _iso()
        self.store.insert(
            "external_oauth_clients", client_id=client_id, client_name=name,
            redirect_uris_json=json.dumps(redirects), grant_types_json=json.dumps(grants),
            response_types_json=json.dumps(responses),
            token_endpoint_auth_method="none", created_at=created)
        self.store.commit()
        return {"client_id": client_id, "client_name": name,
                "redirect_uris": redirects, "grant_types": grants,
                "response_types": responses, "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(_parse_time(created).timestamp())}

    def validate_oauth_client(self, client_id: str, redirect_uri: str) -> None:
        row = self.store.query_one(
            "SELECT redirect_uris_json FROM external_oauth_clients WHERE client_id=?",
            (str(client_id),))
        if row is None:
            raise ExternalAgentError(400, "OAuth client is not registered", "invalid_client")
        if str(redirect_uri) not in set(load_json(row["redirect_uris_json"], [])):
            raise ExternalAgentError(400, "redirect URI is not registered", "invalid_redirect_uri")

    def authenticate(self, raw_token: str, *, required_scope: str | None = None,
                     rate_limit: bool = True) -> dict[str, Any]:
        if not raw_token:
            raise ExternalAgentError(401, "bearer token required", "authentication_required")
        row = self.store.query_one(
            "SELECT k.*,c.tenant_id,c.owner_id_hash,c.display_name,c.biography,"
            "c.preferred_occupation,c.tier,c.scopes_json AS connection_scopes_json,c.status,"
            "c.actor_id,c.wake_interval_ticks FROM external_agent_credentials k "
            "JOIN external_agent_connections c ON c.id=k.connection_id WHERE k.token_hash=?",
            (_hash(str(raw_token)),))
        now = _now()
        if row is None or row["revoked_at"] is not None or _parse_time(row["expires_at"]) <= now:
            raise ExternalAgentError(401, "credential is invalid or expired", "invalid_token")
        if str(row["audience"]) != self.audience:
            raise ExternalAgentError(401, "credential audience mismatch", "invalid_token")
        if row["status"] not in {"active", "pending_actor"}:
            raise ExternalAgentError(403, "connection is not active", "connection_inactive")
        scopes = set(load_json(row["scopes_json"], [])) & set(
            load_json(row["connection_scopes_json"], []))
        if required_scope and required_scope not in scopes:
            self._audit(str(row["connection_id"]), "scope.denied", "denied",
                        {"required_scope": required_scope})
            self.store.commit()
            raise ExternalAgentError(403, "required scope is not granted", "insufficient_scope")
        if rate_limit:
            self._check_rate_limit(str(row["connection_id"]), now)
        lease = now + timedelta(seconds=self.lease_seconds)
        self.store.execute(
            "UPDATE external_agent_credentials SET last_used_at=? WHERE id=?",
            (_iso(now), str(row["id"])))
        self.store.execute(
            "UPDATE external_agent_connections SET last_seen_at=?,lease_expires_at=?,updated_at=? "
            "WHERE id=?", (_iso(now), _iso(lease), _iso(now), str(row["connection_id"])))
        self.store.commit()
        document = self._connection_document(row)
        document.update({"credential_id": str(row["id"]), "credential_kind": str(row["kind"]),
                         "scopes": sorted(scopes), "audience": self.audience})
        return document

    def create_authorization_code(
        self, connection_id: str, *, tenant_id: str, owner_id: str,
        client_id: str, redirect_uri: str, code_challenge: str,
        scopes: Iterable[str], admin: bool = False,
        require_registered_client: bool = False,
    ) -> dict[str, Any]:
        connection = self.connection(
            connection_id, owner_id=owner_id, tenant_id=tenant_id, admin=admin)
        requested = _clean_scopes(scopes)
        if not set(requested).issubset(set(connection["scopes"])):
            raise ExternalAgentError(403, "OAuth scope escalation denied", "scope_escalation")
        if require_registered_client:
            self.validate_oauth_client(client_id, redirect_uri)
        if len(code_challenge) < 43 or len(code_challenge) > 128:
            raise ExternalAgentError(400, "invalid PKCE challenge", "invalid_pkce")
        code = f"ae_code_{connection_id}.{secrets.token_urlsafe(32)}"
        self.store.insert(
            "external_oauth_codes", id=str(uuid4()), connection_id=connection_id,
            code_hash=_hash(code), client_id=str(client_id)[:200],
            redirect_uri=str(redirect_uri)[:1000], code_challenge=str(code_challenge),
            challenge_method="S256", scopes_json=json.dumps(requested), audience=self.audience,
            expires_at=_iso(_now() + timedelta(minutes=5)), created_at=_iso())
        self._audit(connection_id, "oauth.code_issued", "allowed",
                    {"client_id": str(client_id)[:200], "scopes": requested})
        self.store.commit()
        return {"code": code, "redirect_uri": str(redirect_uri), "expires_in": 300,
                "scope": " ".join(requested)}

    def exchange_authorization_code(self, *, code: str, client_id: str,
                                    redirect_uri: str, code_verifier: str) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT * FROM external_oauth_codes WHERE code_hash=?", (_hash(str(code)),))
        now = _now()
        if (row is None or row["consumed_at"] is not None
                or _parse_time(row["expires_at"]) <= now):
            raise ExternalAgentError(400, "authorization code is invalid", "invalid_grant")
        if str(row["client_id"]) != str(client_id) or str(row["redirect_uri"]) != str(redirect_uri):
            raise ExternalAgentError(400, "authorization binding mismatch", "invalid_grant")
        digest = hashlib.sha256(str(code_verifier).encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        if not secrets.compare_digest(challenge, str(row["code_challenge"])):
            self._audit(str(row["connection_id"]), "oauth.pkce_denied", "denied", {})
            self.store.commit()
            raise ExternalAgentError(400, "PKCE verification failed", "invalid_grant")
        self.store.execute("UPDATE external_oauth_codes SET consumed_at=? WHERE id=?",
                           (_iso(now), str(row["id"])))
        result = self._oauth_token_pair(str(row["connection_id"]),
                                        load_json(row["scopes_json"], []), now=now)
        self._audit(str(row["connection_id"]), "oauth.code_exchanged", "allowed", {})
        self.store.commit()
        return result

    def refresh_access_token(self, *, refresh_token: str,
                             scopes: Iterable[str] | None = None) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT k.*,c.status,c.scopes_json AS connection_scopes_json "
            "FROM external_agent_credentials k JOIN external_agent_connections c "
            "ON c.id=k.connection_id WHERE k.token_hash=? AND k.kind='refresh'",
            (_hash(str(refresh_token)),))
        now = _now()
        if (row is None or row["revoked_at"] is not None
                or _parse_time(row["expires_at"]) <= now or row["status"] != "active"):
            raise ExternalAgentError(400, "refresh token is invalid", "invalid_grant")
        original = set(load_json(row["scopes_json"], [])) & set(
            load_json(row["connection_scopes_json"], []))
        requested = set(_clean_scopes(scopes)) if scopes is not None else original
        if not requested.issubset(original):
            raise ExternalAgentError(403, "refresh scope escalation denied", "scope_escalation")
        self.store.execute("UPDATE external_agent_credentials SET revoked_at=? WHERE id=?",
                           (_iso(now), str(row["id"])))
        result = self._oauth_token_pair(str(row["connection_id"]), sorted(requested),
                                        now=now, rotated_from_id=str(row["id"]))
        self._audit(str(row["connection_id"]), "oauth.refresh_rotated", "changed",
                    {"scopes": sorted(requested)})
        self.store.commit()
        return result

    def revoke_token(self, raw_token: str) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT id,connection_id,revoked_at FROM external_agent_credentials WHERE token_hash=?",
            (_hash(str(raw_token)),))
        if row is not None and row["revoked_at"] is None:
            self.store.execute("UPDATE external_agent_credentials SET revoked_at=? WHERE id=?",
                               (_iso(), str(row["id"])))
            self._audit(str(row["connection_id"]), "oauth.token_revoked", "changed", {})
            self.store.commit()
        return {"ok": True}

    # -- agent protocol ------------------------------------------------------
    def identity(self, auth: dict[str, Any]) -> dict[str, Any]:
        actor = None
        if auth.get("actor_id") is not None:
            row = self.store.query_one(
                "SELECT id,name,kind,occupation,age,health,alive,retired,region_id,arrived_tick "
                "FROM agents WHERE id=?", (int(auth["actor_id"]),))
            actor = dict(row) if row is not None else None
            if actor is not None:
                actor["alive"] = bool(actor["alive"])
                actor["retired"] = bool(actor["retired"])
        meta = self.store.get_meta()
        return {"protocol_version": "ae.agent.v1", "tenant_id": auth["tenant_id"],
                "run_id": str(meta["run_id"]), "connection_id": auth["id"],
                "tier": auth["tier"], "scopes": auth["scopes"],
                "status": auth["status"], "actor": actor,
                "public_profile": {"display_name": auth["display_name"],
                                   "biography": auth["biography"],
                                   "preferred_occupation": auth["preferred_occupation"]}}

    def observe(self, auth: dict[str, Any]) -> dict[str, Any]:
        if SCOPE_WORLD_READ not in auth["scopes"] and SCOPE_COMMONS_READ not in auth["scopes"]:
            raise ExternalAgentError(403, "read scope required", "insufficient_scope")
        actor_id = int(auth["actor_id"]) if auth.get("actor_id") is not None else None
        actor = None
        accounts: list[dict[str, Any]] = []
        if actor_id is not None:
            row = self.store.query_one(
                "SELECT id,name,kind,role,occupation,age,health,alive,retired,region_id,arrived_tick "
                "FROM agents WHERE id=?", (actor_id,))
            actor = dict(row) if row else None
            if actor:
                actor["alive"] = bool(actor["alive"])
                actor["retired"] = bool(actor["retired"])
            accounts = [dict(row) for row in self.store.query(
                "SELECT id,kind,label,balance_cents,currency_code FROM accounts "
                "WHERE owner_type='agent' AND owner_id=? ORDER BY id", (actor_id,))]
        metrics = {str(row["name"]): float(row["value"]) for row in self.store.query(
            "SELECT m.name,m.value FROM metrics m JOIN (SELECT name,MAX(tick) AS tick FROM metrics "
            "GROUP BY name) latest ON latest.name=m.name AND latest.tick=m.tick "
            "ORDER BY m.name LIMIT 100")}
        prices = [dict(row) for row in self.store.query(
            "SELECT f.id AS firm_id,f.name,f.sector,f.inventory,"
            "json_extract(f.product_json,'$.unit_price_cents') AS unit_price_cents "
            "FROM firms f WHERE f.status IN ('operating','listed') ORDER BY f.id LIMIT 100")]
        public_events = [
            {"id": int(row["id"]), "tick": int(row["tick"]), "kind": str(row["kind"]),
            "subject_type": row["subject_type"], "subject_id": row["subject_id"],
             "importance": float(row["importance"])}
            for row in self.store.query(
                "SELECT id,tick,kind,subject_type,subject_id,importance FROM events "
                f"WHERE kind IN ({_PUBLIC_EVENT_KIND_PARAMS}) ORDER BY id DESC LIMIT 50",
                _PUBLIC_EVENT_KINDS)]
        return {"completed_tick": self.store.tick, "actor": actor, "accounts": accounts,
                "metrics": metrics, "market": prices, "recent_public_events": public_events}

    def turn(self, auth: dict[str, Any]) -> dict[str, Any]:
        observations = self.observe(auth)
        actor_id = int(auth["actor_id"]) if auth.get("actor_id") is not None else None
        catalog: list[dict[str, Any]] = []
        if actor_id is not None and SCOPE_WORLD_ACT in auth["scopes"]:
            agent = self.store.query_one("SELECT alive,kind FROM agents WHERE id=?", (actor_id,))
            if agent is not None and bool(agent["alive"]) and agent["kind"] == "citizen":
                catalog = self.participant.action_catalog(actor_id)
        projection_hash = _canonical_hash(observations)
        catalog_version = _canonical_hash(catalog)
        completed_tick = self.store.tick
        target_tick = completed_tick + 1
        meta = self.store.get_meta()
        cursor = int(self.store.scalar("SELECT COALESCE(MAX(id),0) FROM events", default=0))
        deadline = _now() + timedelta(seconds=self.decision_seconds)
        self.store.execute(
            "UPDATE external_agent_turns SET status='expired',updated_at=? "
            "WHERE connection_id=? AND target_tick<? AND status='open'",
            (_iso(), auth["id"], target_tick))
        existing = self.store.query_one(
            "SELECT id,status,actor_id,envelope_json,deadline_at FROM external_agent_turns "
            "WHERE connection_id=? AND target_tick=?",
            (auth["id"], target_tick))
        if (existing is not None
                and existing["actor_id"] == actor_id
                and load_json(existing["envelope_json"], None) is not None):
            persisted = load_json(existing["envelope_json"], {}) or {}
            persisted["turn_id"] = str(existing["id"])
            persisted["turn_status"] = str(existing["status"])
            persisted["deadline"] = str(existing["deadline_at"])
            self.store.commit()
            return persisted
        turn_id = str(existing["id"]) if existing is not None else str(uuid4())
        envelope = {
            "version": "ae.turn.v1", "tenant_id": auth["tenant_id"],
            "run_id": str(meta["run_id"]), "fork_id": str(meta["parent_run_id"] or ""),
            "connection_id": auth["id"], "actor_id": actor_id,
            "completed_tick": completed_tick, "target_tick": target_tick,
            "observations": observations, "action_catalog_version": catalog_version,
            "action_catalog": catalog, "projection_hash": projection_hash,
            "deadline": _iso(deadline), "event_cursor": cursor,
            "lease_seconds": self.lease_seconds,
            "turn_id": turn_id, "turn_status": "open",
        }
        if existing is None:
            self.store.execute(
                "INSERT INTO external_agent_turns(id,connection_id,actor_id,completed_tick,target_tick,"
                "projection_hash,action_catalog_version,envelope_json,event_cursor,deadline_at,status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                (turn_id, auth["id"], actor_id, completed_tick, target_tick, projection_hash,
                 catalog_version, _canonical(envelope), cursor, _iso(deadline), _iso(), _iso()))
        else:
            self.store.execute(
                "UPDATE external_agent_turns SET actor_id=?,projection_hash=?,"
                "action_catalog_version=?,envelope_json=?,event_cursor=?,deadline_at=?,"
                "status='open',updated_at=? WHERE id=?",
                (actor_id, projection_hash, catalog_version, _canonical(envelope),
                 cursor, _iso(deadline), _iso(), turn_id))
        self.store.commit()
        return envelope

    async def collect_online_turns(self, tick: int) -> None:
        """Wait concurrently for already-connected actors, then close the mailbox.

        Only actors holding a current 60-second lease and an open turn receive a
        decision window. Offline actors fall through immediately to the safe
        policy, so one absent client never stalls a run.
        """
        if int(self.config.get("engine_semantics_version", 1)) < 9:
            return
        if self.config.get("replay_source_path"):
            self._restore_replay_actor_requests(tick)
            # Live clients submit between ticks, before NIGHT_CLOSE begins. Copy
            # recorded submissions at that same boundary so their CONTROL event
            # retains the source ordering and every later event reference stays
            # exact without contacting the external agent.
            if self._replay_commons_precedes_control(tick):
                self._restore_replay_commons(tick)
                self._replay_decisions(tick)
            else:
                self._replay_decisions(tick)
                self._restore_replay_commons(tick)
            return
        while True:
            now = _now()
            rows = self.store.query(
                "SELECT t.id,t.connection_id,t.deadline_at,t.status "
                "FROM external_agent_turns t JOIN external_agent_connections c "
                "ON c.id=t.connection_id JOIN agents a ON a.id=c.actor_id "
                "WHERE t.target_tick=? AND t.status='open' AND c.status='active' "
                "AND c.tier='actor' AND a.alive=1 AND c.lease_expires_at>? "
                "ORDER BY c.actor_id,c.id", (int(tick), _iso(now)))
            if not rows:
                break
            pending = [row for row in rows if _parse_time(row["deadline_at"]) > now]
            if not pending:
                break
            delay = min(
                0.25,
                max(0.01, min(
                    (_parse_time(row["deadline_at"]) - now).total_seconds()
                    for row in pending)))
            await asyncio.sleep(delay)
        now = _now()
        open_rows = self.store.query(
            "SELECT t.id,t.connection_id,c.actor_id,c.lease_expires_at "
            "FROM external_agent_turns t JOIN external_agent_connections c "
            "ON c.id=t.connection_id WHERE t.target_tick=? AND t.status='open'",
            (int(tick),))
        for row in open_rows:
            reason = ("decision_window_expired" if row["lease_expires_at"] is not None
                      and _parse_time(row["lease_expires_at"]) > now
                      else "offline")
            self.store.execute(
                "UPDATE external_agent_turns SET status='fallback',updated_at=? "
                "WHERE id=? AND status='open'", (_iso(now), str(row["id"])))
            self._audit(str(row["connection_id"]), "turn.fallback", "changed",
                        {"target_tick": int(tick), "reason": reason})
        if open_rows:
            self.store.commit()

    def restore_replay_after_morning(self, tick: int) -> None:
        """Restore control-plane writes recorded after MORNING but before EXECUTION."""
        if self.config.get("replay_source_path"):
            self._restore_replay_actor_requests(int(tick) + 1)

    def _replay_commons_precedes_control(self, tick: int) -> bool:
        """Preserve the source order of between-tick Commons and action writes."""
        source_path = self.config.get("replay_source_path")
        completed_tick = int(tick) - 1
        if completed_tick < 0 or not source_path or not Path(str(source_path)).exists():
            return False
        conn = open_read_only_connection(str(source_path))
        try:
            row = conn.execute(
                "SELECT "
                "MIN(CASE WHEN kind IN "
                "('commons_entry_published','commons_reaction_changed') "
                "THEN id END) AS commons_event_id,"
                "MIN(CASE WHEN kind='external_action_queued' THEN id END) "
                "AS control_event_id "
                "FROM events WHERE tick=?",
                (completed_tick,),
            ).fetchone()
            return (
                row is not None
                and row["commons_event_id"] is not None
                and row["control_event_id"] is not None
                and int(row["commons_event_id"]) < int(row["control_event_id"])
            )
        finally:
            conn.close()

    def _restore_replay_actor_requests(self, tick: int) -> None:
        """Recreate external-citizen arrivals at their recorded spawn boundary."""
        source_path = self.config.get("replay_source_path")
        if not source_path or not Path(str(source_path)).exists():
            return
        conn = open_read_only_connection(str(source_path))
        try:
            required = {"external_agent_connections", "external_actor_requests", "events"}
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not required.issubset(tables):
                return
            connection_columns = {
                str(column[1])
                for column in conn.execute(
                    "PRAGMA table_info(external_agent_connections)"
                ).fetchall()
            }
            passport_select = (
                ",c.passport_id" if "passport_id" in connection_columns
                else ",NULL AS passport_id"
            )
            rows = conn.execute(
                "SELECT r.*,c.tenant_id,c.owner_id_hash,c.display_name,"
                "c.biography AS connection_biography,"
                "c.preferred_occupation AS connection_occupation,"
                "c.tier,c.scopes_json,c.wake_interval_ticks,c.created_tick,"
                "c.created_at,c.id AS source_connection_id"
                + passport_select + " "
                "FROM external_actor_requests r "
                "JOIN external_agent_connections c ON c.id=r.connection_id "
                "WHERE r.spawned_tick=? ORDER BY r.id",
                (int(tick),),
            ).fetchall()
            for row in rows:
                connection_id = str(row["source_connection_id"])
                if self.store.query_one(
                    "SELECT id FROM external_agent_connections WHERE id=?",
                    (connection_id,),
                ) is not None:
                    continue
                source_event = conn.execute(
                    "SELECT tick,phase,kind,subject_type,subject_id,importance,"
                    "payload_json FROM events WHERE id=?",
                    (int(row["schedule_event_id"]),),
                ).fetchone()
                if source_event is None or str(source_event["kind"]) != "arrival_scheduled":
                    raise RuntimeError(
                        "recorded external actor request has no arrival_scheduled event"
                    )
                self.store.execute(
                    "INSERT INTO external_agent_connections("
                    "id,tenant_id,owner_id_hash,display_name,biography,"
                    "preferred_occupation,tier,scopes_json,status,actor_id,"
                    "actor_schedule_event_id,wake_interval_ticks,last_seen_at,"
                    "lease_expires_at,created_tick,created_at,updated_at,passport_id"
                    ") VALUES(?,?,?,?,?,?,?,?,'pending_actor',NULL,NULL,?,NULL,NULL,?,?,?,?)",
                    (
                        connection_id,
                        str(row["tenant_id"]),
                        str(row["owner_id_hash"]),
                        str(row["display_name"]),
                        str(row["connection_biography"]),
                        str(row["connection_occupation"]),
                        str(row["tier"]),
                        str(row["scopes_json"]),
                        int(row["wake_interval_ticks"]),
                        int(row["created_tick"]),
                        str(row["created_at"]),
                        str(row["created_at"]),
                        row["passport_id"],
                    ),
                )
                local_schedule_id = self.store.log_event(
                    int(source_event["tick"]),
                    str(source_event["kind"]),
                    load_json(source_event["payload_json"], {}) or {},
                    phase=source_event["phase"],
                    subject_type=source_event["subject_type"],
                    subject_id=source_event["subject_id"],
                    importance=float(source_event["importance"]),
                )
                self.store.execute(
                    "UPDATE external_agent_connections "
                    "SET actor_schedule_event_id=? WHERE id=?",
                    (local_schedule_id, connection_id),
                )
                self.store.execute(
                    "INSERT INTO external_actor_requests("
                    "id,connection_id,schedule_event_id,requested_tick,due_tick,"
                    "public_name,biography,preferred_occupation,status,actor_id,"
                    "spawned_tick) VALUES(?,?,?,?,?,?,?,?,'scheduled',NULL,NULL)",
                    (
                        int(row["id"]),
                        connection_id,
                        local_schedule_id,
                        int(row["requested_tick"]),
                        int(row["due_tick"]),
                        str(row["public_name"]),
                        str(row["biography"]),
                        str(row["preferred_occupation"]),
                    ),
                )
                self.store.set_meta(external_agent_influenced=1)
        finally:
            conn.close()

    def _restore_replay_commons(self, tick: int) -> None:
        """Replay recorded external Commons writes and feed deliveries offline."""
        source_path = self.config.get("replay_source_path")
        completed_tick = int(tick) - 1
        if completed_tick < 0 or not source_path or not Path(str(source_path)).exists():
            return
        conn = open_read_only_connection(str(source_path))
        try:
            required = {
                "commons_entries", "commons_feed_impressions", "commons_reactions",
            }
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not required.issubset(tables):
                return
            entry_rows = conn.execute(
                "SELECT * FROM commons_entries WHERE created_tick=? ORDER BY id",
                (completed_tick,),
            ).fetchall()
            impression_groups = conn.execute(
                "SELECT viewer_agent_id,feed_kind,candidate_set_hash,policy_id,"
                "COUNT(*) AS delivered_count "
                "FROM commons_feed_impressions WHERE delivered_tick=? "
                "GROUP BY viewer_agent_id,feed_kind,candidate_set_hash,policy_id "
                "ORDER BY MIN(id)",
                (completed_tick,),
            ).fetchall()
            reaction_rows = conn.execute(
                "SELECT * FROM commons_reactions WHERE created_tick=? "
                "ORDER BY entry_id,agent_id,reaction",
                (completed_tick,),
            ).fetchall()
            if not entry_rows and not impression_groups and not reaction_rows:
                return

            from world.commons import CommonsService

            commons = CommonsService(self.economy)

            def source_entry(source_entry_id: int):
                source_entry = conn.execute(
                    "SELECT * FROM commons_entries WHERE id=?",
                    (int(source_entry_id),),
                ).fetchone()
                if source_entry is None:
                    raise RuntimeError(
                        f"recorded Commons entry {source_entry_id} is unavailable"
                    )
                return source_entry

            def local_entry_id(source_entry_id: int) -> int:
                recorded = source_entry(source_entry_id)
                matches = self.store.query(
                    "SELECT id FROM commons_entries WHERE author_agent_id=? "
                    "AND entry_type=? AND body_text=? AND created_tick=? ORDER BY id",
                    (
                        int(recorded["author_agent_id"]),
                        str(recorded["entry_type"]),
                        str(recorded["body_text"]),
                        int(recorded["created_tick"]),
                    ),
                )
                if len(matches) != 1:
                    raise RuntimeError(
                        f"recorded Commons entry {source_entry_id} has "
                        f"{len(matches)} local matches"
                    )
                return int(matches[0]["id"])

            def ensure_local_entry(source_entry_id: int) -> int:
                row = source_entry(source_entry_id)
                existing = self.store.query_one(
                    "SELECT id FROM commons_entries WHERE author_agent_id=? "
                    "AND entry_type=? AND body_text=? AND created_tick=?",
                    (
                        int(row["author_agent_id"]),
                        str(row["entry_type"]),
                        str(row["body_text"]),
                        int(row["created_tick"]),
                    ),
                )
                if existing is not None:
                    return int(existing["id"])
                if int(row["created_tick"]) > completed_tick:
                    raise RuntimeError(
                        f"recorded Commons entry {source_entry_id} is from a "
                        "future replay boundary"
                    )
                parent_entry_id = (
                    ensure_local_entry(int(row["parent_entry_id"]))
                    if row["parent_entry_id"] is not None else None
                )
                commons.publish(
                    int(row["author_agent_id"]),
                    body=str(row["body_text"]),
                    community_id=(
                        int(row["community_id"])
                        if row["community_id"] is not None else None
                    ),
                    parent_entry_id=parent_entry_id,
                    entry_type=str(row["entry_type"]),
                    claim_id=(
                        int(row["claim_id"]) if row["claim_id"] is not None else None
                    ),
                )
                return local_entry_id(source_entry_id)

            for group in impression_groups:
                source_impressions = conn.execute(
                    "SELECT entry_id,position FROM commons_feed_impressions "
                    "WHERE delivered_tick=? AND viewer_agent_id=? AND feed_kind=? "
                    "AND candidate_set_hash=? AND policy_id=? ORDER BY position,id",
                    (
                        completed_tick,
                        int(group["viewer_agent_id"]),
                        str(group["feed_kind"]),
                        str(group["candidate_set_hash"]),
                        int(group["policy_id"]),
                    ),
                ).fetchall()
                expected_entries = [
                    ensure_local_entry(int(row["entry_id"]))
                    for row in source_impressions
                ]
                delivered = commons.feed(
                    int(group["viewer_agent_id"]),
                    kind=str(group["feed_kind"]),
                    limit=max(1, int(group["delivered_count"])),
                )
                actual_entries = [int(row["id"]) for row in delivered["entries"]]
                if (
                    str(delivered["candidate_set_hash"])
                    != str(group["candidate_set_hash"])
                    or actual_entries != expected_entries
                ):
                    raise RuntimeError(
                        "recorded Commons feed cannot be reconstructed exactly"
                    )

            # A citizen may read the feed and then publish within the same
            # completed tick. Defer entries absent from the recorded feed until
            # after that delivery; entries present in a delivery are materialized
            # above just before the corresponding feed call.
            for row in entry_rows:
                ensure_local_entry(int(row["id"]))

            for row in reaction_rows:
                entry_id = local_entry_id(int(row["entry_id"]))
                existing = self.store.query_one(
                    "SELECT status FROM commons_reactions "
                    "WHERE entry_id=? AND agent_id=? AND reaction=?",
                    (entry_id, int(row["agent_id"]), str(row["reaction"])),
                )
                if existing is not None and str(existing["status"]) == str(row["status"]):
                    continue
                commons.react(
                    int(row["agent_id"]),
                    entry_id,
                    str(row["reaction"]),
                    active=str(row["status"]) == "active",
                )
        finally:
            conn.close()

    def submit_action(self, auth: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
        if SCOPE_WORLD_ACT not in auth["scopes"]:
            raise ExternalAgentError(403, "world.act scope required", "insufficient_scope")
        if not isinstance(submission, dict):
            raise ExternalAgentError(400, "submission must be an object", "invalid_submission")
        key = str(submission.get("idempotency_key", "")).strip()[:128]
        if not key:
            raise ExternalAgentError(400, "idempotency_key is required", "invalid_submission")
        prior = self.store.query_one(
            "SELECT id FROM external_action_submissions WHERE connection_id=? AND idempotency_key=?",
            (auth["id"], key))
        if prior is not None:
            return self.receipt(auth, str(prior["id"]))
        actor_id = int(auth["actor_id"]) if auth.get("actor_id") is not None else None
        if actor_id is None:
            raise ExternalAgentError(409, "dedicated actor is not available", "actor_pending")
        current_turn = self.turn(auth)
        target_tick = int(submission.get("target_tick", -1))
        observed_hash = str(submission.get("observed_projection_hash", ""))
        action = submission.get("action")
        rationale = str(submission.get("rationale_summary", "")).strip()[:500]
        status = "queued"
        validators: list[dict[str, Any]] = []
        normalized: dict[str, Any] = {"type": "do_nothing"}
        if current_turn.get("turn_status") != "open":
            status = "stale"
            validators.append({"validator": "turn_status", "ok": False,
                               "message": "the decision window is closed"})
        elif _parse_time(current_turn["deadline"]) <= _now():
            status = "stale"
            validators.append({"validator": "deadline", "ok": False,
                               "message": "the decision deadline has passed"})
            self.store.execute(
                "UPDATE external_agent_turns SET status='fallback',updated_at=? "
                "WHERE id=? AND status='open'", (_iso(), current_turn["turn_id"]))
        elif target_tick != int(current_turn["target_tick"]):
            status = "stale"
            validators.append({"validator": "target_tick", "ok": False,
                               "message": "target tick is no longer open"})
        elif observed_hash != str(current_turn["projection_hash"]):
            status = "stale"
            validators.append({"validator": "projection_hash", "ok": False,
                               "message": "observed projection is stale"})
        else:
            agent = self.store.query_one("SELECT alive,kind FROM agents WHERE id=?", (actor_id,))
            if agent is None or not bool(agent["alive"]):
                status = "rejected"
                validators.append({"validator": "actor_lifecycle", "ok": False,
                                   "message": "actor is not living"})
            elif agent["kind"] != "citizen":
                status = "rejected"
                validators.append({"validator": "actor_role", "ok": False,
                                   "message": "institutional actors are not supported"})
            else:
                try:
                    normalized = self.participant.normalize_action(actor_id, action)
                    validators.append({"validator": "participant_catalog", "ok": True})
                except ParticipantError as exc:
                    status = "rejected"
                    validators.append({"validator": "participant_catalog", "ok": False,
                                       "message": str(exc)})
        submission_id = str(uuid4())
        try:
            self.store.execute(
                "INSERT INTO external_action_submissions(id,connection_id,actor_id,turn_id,target_tick,"
                "observed_projection_hash,idempotency_key,action_json,rationale_summary,status,"
                "validator_results_json,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (submission_id, auth["id"], actor_id, current_turn["turn_id"], target_tick,
                 observed_hash if len(observed_hash) == 64 else "0" * 64, key,
                 _canonical(normalized if status != "rejected" else (action or {})), rationale,
                 status, _canonical(validators), _iso(), _iso() if status != "queued" else None))
        except sqlite3.IntegrityError:
            accepted = self.store.query_one(
                "SELECT id FROM external_action_submissions WHERE actor_id=? AND target_tick=? "
                "AND status IN ('queued','executed') ORDER BY created_at,id LIMIT 1",
                (actor_id, target_tick))
            if accepted is not None:
                raise ExternalAgentError(409, "one action is already accepted for this wake",
                                         "wake_already_filled") from None
            raise
        if status == "queued":
            self.store.execute("UPDATE external_agent_turns SET status='submitted',updated_at=? WHERE id=?",
                               (_iso(), current_turn["turn_id"]))
            self.store.set_meta(external_agent_influenced=1)
        event_id = self.store.log_event(
            self.store.tick, f"external_action_{status}",
            {"submission_id": submission_id, "connection_id": auth["id"],
             "actor_id": actor_id, "target_tick": target_tick,
             "action_type": normalized.get("type")}, phase="CONTROL",
            subject_type="agent", subject_id=actor_id, importance=1.2)
        self._audit(auth["id"], "action.submitted", "allowed" if status == "queued" else "denied",
                    {"submission_id": submission_id, "target_tick": target_tick, "status": status})
        self.store.commit()
        receipt = self.receipt(auth, submission_id)
        receipt["submission_event_id"] = event_id
        return receipt

    def receipt(self, auth: dict[str, Any], submission_id: str) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT * FROM external_action_submissions WHERE id=? AND connection_id=?",
            (str(submission_id), auth["id"]))
        if row is None:
            raise ExternalAgentError(404, "action receipt not found", "receipt_not_found")
        return {"version": "ae.receipt.v1", "submission_id": str(row["id"]),
                "connection_id": str(row["connection_id"]), "actor_id": int(row["actor_id"]),
                "target_tick": int(row["target_tick"]), "status": str(row["status"]),
                "validator_results": load_json(row["validator_results_json"], []),
                "results": load_json(row["result_json"], []),
                "event_ids": load_json(row["event_ids_json"], []),
                "resulting_state_hash": row["resulting_state_hash"],
                "created_at": str(row["created_at"]), "completed_at": row["completed_at"]}

    def events(self, auth: dict[str, Any], *, cursor: int = 0,
               limit: int = 100) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT id,tick,phase,kind,subject_type,subject_id,importance,payload_json FROM events "
            f"WHERE id>? AND kind IN ({_PUBLIC_EVENT_KIND_PARAMS}) ORDER BY id LIMIT ?",
            (max(0, int(cursor)), *_PUBLIC_EVENT_KINDS, max(1, min(int(limit), 500))))
        events = []
        for row in rows:
            payload = public_event_payload(
                str(row["kind"]), load_json(row["payload_json"], {}))
            events.append({"id": int(row["id"]), "tick": int(row["tick"]),
                           "phase": row["phase"], "kind": str(row["kind"]),
                           "subject_type": row["subject_type"], "subject_id": row["subject_id"],
                           "importance": float(row["importance"]), "payload": payload})
        next_cursor = int(rows[-1]["id"]) if rows else max(0, int(cursor))
        return {"events": events, "cursor": next_cursor}

    # -- deterministic runtime/replay integration ---------------------------
    def _expire_queued_before(self, tick: int) -> None:
        """Close submissions that can no longer be selected for execution."""
        rows = self.store.query(
            "SELECT id,turn_id FROM external_action_submissions "
            "WHERE target_tick<? AND status='queued' ORDER BY target_tick,id",
            (int(tick),),
        )
        if not rows:
            return
        completed_at = _iso()
        validators = _canonical([{
            "validator": "target_tick",
            "ok": False,
            "message": "the target tick passed before execution",
        }])
        for row in rows:
            updated = self.store.execute(
                "UPDATE external_action_submissions SET status='stale',"
                "validator_results_json=?,result_json='[]',completed_at=? "
                "WHERE id=? AND status='queued'",
                (validators, completed_at, str(row["id"])),
            )
            if int(updated.rowcount or 0) <= 0:
                continue
            self.store.execute(
                "UPDATE external_agent_turns SET status='fallback',updated_at=? "
                "WHERE id=? AND status IN ('open','submitted')",
                (completed_at, str(row["turn_id"])),
            )

    def decisions_for_tick(self, tick: int) -> tuple[set[int], list[dict[str, Any]]]:
        self._expire_queued_before(tick)
        replay = self._replay_decisions(tick)
        if replay:
            return {int(item["agent_id"]) for item in replay}, replay
        controlled: set[int] = set()
        decisions: list[dict[str, Any]] = []
        rows = self.store.query(
            "SELECT c.*,a.alive,a.kind FROM external_agent_connections c JOIN agents a "
            "ON a.id=c.actor_id WHERE c.actor_id IS NOT NULL ORDER BY c.actor_id,c.id")
        for row in rows:
            actor_id = int(row["actor_id"])
            interval = int(row["wake_interval_ticks"])
            if (tick - int(row["created_tick"])) % interval != 0:
                continue
            controlled.add(actor_id)
            action_row = None
            if row["status"] == "active" and row["tier"] == "actor" and bool(row["alive"]):
                action_row = self.store.query_one(
                    "SELECT * FROM external_action_submissions WHERE connection_id=? AND actor_id=? "
                    "AND target_tick=? AND status='queued' ORDER BY created_at,id LIMIT 1",
                    (str(row["id"]), actor_id, tick))
            if action_row is not None:
                action = load_json(action_row["action_json"], {"type": "do_nothing"})
                decisions.append({"agent_id": actor_id, "purpose": "external_agent",
                                  "envelope": {"actions": [action], "belief_updates": []},
                                  "reasoning": str(action_row["rationale_summary"] or "")[:500],
                                  "llm_call_id": None,
                                  "external_submission_id": str(action_row["id"]),
                                  "external_connection_id": str(row["id"])})
            else:
                if not bool(row["alive"]):
                    self._close_pending(str(row["id"]), "actor_not_living",
                                        target_tick=int(tick))
                turn = self.store.query_one(
                    "SELECT id FROM external_agent_turns WHERE connection_id=? AND target_tick=?",
                    (str(row["id"]), tick))
                if turn is not None:
                    self.store.execute(
                        "UPDATE external_agent_turns SET status='fallback',updated_at=? "
                        "WHERE id=? AND status='open'", (_iso(), str(turn["id"])))
                self.store.log_event(
                    tick, "external_agent_fallback",
                    {"connection_id": str(row["id"]), "actor_id": actor_id,
                     "reason": "offline_or_no_submission", "policy": "safe_do_nothing_v1"},
                    phase="MORNING", subject_type="agent", subject_id=actor_id, importance=0.6)
                decisions.append({"agent_id": actor_id, "purpose": "external_safe_policy",
                                  "envelope": {"actions": [{"type": "do_nothing"}],
                                               "belief_updates": []},
                                  "reasoning": "Deterministic external-agent safe policy.",
                                  "llm_call_id": None, "external_submission_id": None,
                                  "external_connection_id": str(row["id"])})
        return controlled, decisions

    def complete(self, submission_id: str | None, results: list[dict[str, Any]], tick: int,
                 *, event_ids: list[int], resulting_state_hash: str) -> None:
        if submission_id is None:
            return
        row = self.store.query_one(
            "SELECT * FROM external_action_submissions WHERE id=?", (str(submission_id),))
        if row is None:
            return
        ok = bool(results) and all(bool(result.get("ok")) for result in results)
        status = "executed" if ok else "rejected"
        # Atomic claim: only the first complete() that observes queued wins the
        # terminal transition and terminal event emission.
        updated = self.store.execute(
            "UPDATE external_action_submissions SET status=?,result_json=?,event_ids_json=?,"
            "resulting_state_hash=?,completed_at=? WHERE id=? AND status='queued'",
            (status, _canonical(results), _canonical(event_ids), resulting_state_hash,
             _iso(), str(submission_id)))
        if int(getattr(updated, "rowcount", 0) or 0) != 1:
            return
        self.store.log_event(
            tick, f"external_action_{status}",
            {"submission_id": str(submission_id), "connection_id": str(row["connection_id"]),
             "actor_id": int(row["actor_id"]), "event_ids": event_ids,
             "resulting_state_hash": resulting_state_hash}, phase="EXECUTION",
            subject_type="agent", subject_id=int(row["actor_id"]), importance=1.5)

    def state_hash(self, actor_id: int) -> str:
        agent = self.store.query_one(
            "SELECT id,kind,role,occupation,age,health,alive,retired,region_id FROM agents WHERE id=?",
            (int(actor_id),))
        accounts = [dict(row) for row in self.store.query(
            "SELECT id,kind,balance_cents,currency_code FROM accounts WHERE owner_type='agent' "
            "AND owner_id=? ORDER BY id", (int(actor_id),))]
        return _canonical_hash({"tick": self.store.tick,
                                "agent": dict(agent) if agent else None,
                                "accounts": accounts})

    def _replay_decisions(self, tick: int) -> list[dict[str, Any]]:
        source_path = self.config.get("replay_source_path")
        if not source_path or not Path(str(source_path)).exists():
            return []
        conn = open_read_only_connection(str(source_path))
        try:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='external_action_submissions'").fetchone()
            if table is None:
                return []
            source_columns = {
                str(column[1])
                for column in conn.execute("PRAGMA table_info(external_agent_connections)")
            }
            passport_select = (
                ",c.passport_id" if "passport_id" in source_columns
                else ",NULL AS passport_id")
            turn_rows = conn.execute(
                "SELECT t.*,c.actor_id FROM external_agent_turns t "
                "JOIN external_agent_connections c ON c.id=t.connection_id "
                "WHERE t.target_tick=? ORDER BY c.actor_id,t.id", (tick,)).fetchall()
            for turn_row in turn_rows:
                actor_id = int(turn_row["actor_id"])
                actor = self.store.query_one(
                    "SELECT alive FROM agents WHERE id=?", (actor_id,))
                existing_turn = self.store.query_one(
                    "SELECT id FROM external_agent_turns WHERE id=?",
                    (str(turn_row["id"]),))
                if actor is None or existing_turn is not None:
                    continue
                # Building the live action catalog retrieves the citizen's
                # memories and advances their deterministic access tick. Replay
                # performs the same read once for each recorded turn, including
                # a turn that ultimately falls back without a submission.
                self.participant.action_catalog(actor_id)
                self.store.execute(
                    "INSERT INTO external_agent_turns(id,connection_id,actor_id,completed_tick,"
                    "target_tick,projection_hash,action_catalog_version,envelope_json,event_cursor,"
                    "deadline_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(turn_row["id"]), str(turn_row["connection_id"]), actor_id,
                     int(turn_row["completed_tick"]), int(turn_row["target_tick"]),
                     str(turn_row["projection_hash"]),
                     str(turn_row["action_catalog_version"]),
                     str(turn_row["envelope_json"]), int(turn_row["event_cursor"]),
                     str(turn_row["deadline_at"]), str(turn_row["status"]),
                     str(turn_row["created_at"]), _iso()))
            rows = conn.execute(
                "SELECT s.*,c.tenant_id,c.display_name,c.biography,c.preferred_occupation,c.tier,"
                "c.scopes_json,c.actor_id,c.created_tick,c.created_at,c.wake_interval_ticks,"
                "t.completed_tick AS source_completed_tick,"
                "t.projection_hash AS source_turn_projection_hash,"
                "t.action_catalog_version AS source_action_catalog_version,"
                "t.envelope_json AS source_envelope_json,"
                "t.event_cursor AS source_event_cursor,"
                "t.deadline_at AS source_deadline_at,"
                "t.status AS source_turn_status,"
                "t.created_at AS source_turn_created_at"
                + passport_select + " "
                "FROM external_action_submissions s JOIN external_agent_connections c "
                "ON c.id=s.connection_id JOIN external_agent_turns t ON t.id=s.turn_id "
                "WHERE s.target_tick=? AND s.status='executed' "
                "ORDER BY s.actor_id,s.id", (tick,)).fetchall()
            out = []
            for row in rows:
                actor = self.store.query_one("SELECT alive FROM agents WHERE id=?", (int(row["actor_id"]),))
                if actor is None:
                    continue
                self.store.execute(
                    "INSERT OR IGNORE INTO external_agent_connections(id,tenant_id,owner_id_hash,"
                    "display_name,biography,preferred_occupation,tier,scopes_json,status,actor_id,"
                    "wake_interval_ticks,created_tick,created_at,updated_at,passport_id) "
                    "VALUES(?,?,?, ?,?,?, ?,?,'active',?,?,?,?,?,?)",
                    (str(row["connection_id"]), str(row["tenant_id"]), "0" * 64,
                     str(row["display_name"]), str(row["biography"]),
                     str(row["preferred_occupation"]), str(row["tier"]), str(row["scopes_json"]),
                     int(row["actor_id"]), int(row["wake_interval_ticks"]),
                     int(row["created_tick"]), str(row["created_at"]), _iso(),
                     row["passport_id"]))
                turn_id = str(row["turn_id"])
                self.store.execute(
                    "INSERT OR IGNORE INTO external_agent_turns(id,connection_id,actor_id,completed_tick,"
                    "target_tick,projection_hash,action_catalog_version,envelope_json,event_cursor,"
                    "deadline_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (turn_id, str(row["connection_id"]), int(row["actor_id"]),
                     int(row["source_completed_tick"]), tick,
                     str(row["source_turn_projection_hash"]),
                     str(row["source_action_catalog_version"]),
                     str(row["source_envelope_json"]), int(row["source_event_cursor"]),
                     str(row["source_deadline_at"]), str(row["source_turn_status"]),
                     str(row["source_turn_created_at"]), _iso()))
                existing = self.store.query_one(
                    "SELECT id FROM external_action_submissions WHERE id=?", (str(row["id"]),))
                if existing is None:
                    self.store.execute(
                        "INSERT INTO external_action_submissions(id,connection_id,actor_id,turn_id,"
                        "target_tick,observed_projection_hash,idempotency_key,action_json,"
                        "rationale_summary,status,validator_results_json,result_json,event_ids_json,"
                        "resulting_state_hash,source_submission_id,created_at,completed_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,'queued',?,'[]','[]',NULL,?,?,NULL)",
                        (str(row["id"]), str(row["connection_id"]), int(row["actor_id"]), turn_id,
                         tick, str(row["observed_projection_hash"]), str(row["idempotency_key"]),
                         str(row["action_json"]), str(row["rationale_summary"]),
                         str(row["validator_results_json"]), str(row["id"]),
                         str(row["created_at"])))
                    action_for_event = load_json(
                        row["action_json"], {"type": "do_nothing"})
                    self.store.log_event(
                        self.store.tick, "external_action_queued",
                        {"submission_id": str(row["id"]),
                         "connection_id": str(row["connection_id"]),
                         "actor_id": int(row["actor_id"]), "target_tick": tick,
                         "action_type": action_for_event.get("type")},
                        phase="CONTROL", subject_type="agent",
                        subject_id=int(row["actor_id"]), importance=1.2)
                action = load_json(row["action_json"], {"type": "do_nothing"})
                out.append({"agent_id": int(row["actor_id"]), "purpose": "external_agent",
                            "envelope": {"actions": [action], "belief_updates": []},
                            "reasoning": str(row["rationale_summary"] or "")[:500],
                            "llm_call_id": None, "external_submission_id": str(row["id"]),
                            "external_connection_id": str(row["connection_id"]),
                            "replay_source_submission_id": str(row["id"])})
            if out:
                self.store.set_meta(external_agent_influenced=1)
            return out
        finally:
            conn.close()

    # -- private helpers -----------------------------------------------------
    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ExternalAgentError(409, "external gateway is disabled", "gateway_disabled")
        semantics = int(self.config.get("engine_semantics_version", 1))
        if semantics < 9:
            raise ExternalAgentError(409, "external gateway requires semantics 9",
                                     "semantics_not_enabled")

    def _issue_credential(self, connection_id: str, kind: str, scopes: Iterable[str],
                          *, expires_at: datetime, prefix: str,
                          rotated_from_id: str | None = None) -> dict[str, Any]:
        raw = f"{prefix}{connection_id}.{secrets.token_urlsafe(32)}"
        credential_id = str(uuid4())
        clean = _clean_scopes(scopes)
        self.store.insert(
            "external_agent_credentials", id=credential_id, connection_id=connection_id,
            kind=kind, token_hash=_hash(raw), scopes_json=json.dumps(clean), audience=self.audience,
            expires_at=_iso(expires_at), rotated_from_id=rotated_from_id,
            created_at=_iso())
        return {"token": raw, "token_type": "Bearer", "kind": kind,
                "expires_at": _iso(expires_at), "scope": " ".join(clean),
                "shown_once": True}

    def _oauth_token_pair(self, connection_id: str, scopes: Iterable[str], *, now: datetime,
                          rotated_from_id: str | None = None) -> dict[str, Any]:
        access = self._issue_credential(
            connection_id, "access", scopes,
            expires_at=now + timedelta(minutes=self.access_token_minutes), prefix="ae_at_")
        refresh = self._issue_credential(
            connection_id, "refresh", scopes,
            expires_at=now + timedelta(days=self.refresh_token_days), prefix="ae_rt_",
            rotated_from_id=rotated_from_id)
        return {"access_token": access["token"], "token_type": "Bearer",
                "expires_in": self.access_token_minutes * 60,
                "refresh_token": refresh["token"], "scope": access["scope"]}

    def _check_rate_limit(self, connection_id: str, now: datetime) -> None:
        window = now.replace(second=0, microsecond=0).isoformat()
        row = self.store.query_one(
            "SELECT request_count FROM external_rate_windows WHERE connection_id=? "
            "AND window_started_at=?", (connection_id, window))
        count = int(row["request_count"]) if row else 0
        if count >= self.requests_per_minute:
            self._audit(connection_id, "rate_limit.denied", "denied",
                        {"window": window, "limit": self.requests_per_minute})
            self.store.commit()
            raise ExternalAgentError(429, "rate limit exceeded", "rate_limit_exceeded")
        self.store.execute(
            "INSERT INTO external_rate_windows(connection_id,window_started_at,request_count) "
            "VALUES(?,?,1) ON CONFLICT(connection_id,window_started_at) DO UPDATE SET "
            "request_count=request_count+1", (connection_id, window))

    def _close_pending(self, connection_id: str, reason: str,
                       *, target_tick: int | None = None) -> None:
        clause = " AND target_tick=?" if target_tick is not None else ""
        params: tuple[Any, ...] = (
            "rejected",
            _canonical([{"validator": "connection_state", "ok": False,
                         "message": str(reason)[:200]}]),
            _canonical([]), _iso(), str(connection_id),
            *((int(target_tick),) if target_tick is not None else ()),
        )
        self.store.execute(
            "UPDATE external_action_submissions SET status=?,validator_results_json=?,"
            "result_json=?,completed_at=? WHERE connection_id=? AND status='queued'" + clause,
            params)
        turn_params: tuple[Any, ...] = (
            _iso(), str(connection_id),
            *((int(target_tick),) if target_tick is not None else ()),
        )
        self.store.execute(
            "UPDATE external_agent_turns SET status='fallback',updated_at=? "
            "WHERE connection_id=? AND status IN ('open','submitted')" + clause,
            turn_params)

    def _audit(self, connection_id: str | None, kind: str, outcome: str,
               details: dict[str, Any]) -> None:
        self.store.insert(
            "external_security_audit", connection_id=connection_id, tick=self.store.tick,
            event_kind=str(kind)[:100], outcome=outcome,
            details_json=_canonical(_redact(details)), created_at=_iso())

    @staticmethod
    def _connection_document(row) -> dict[str, Any]:
        keys = set(row.keys())
        scopes_value = row["connection_scopes_json"] if "connection_scopes_json" in keys else row["scopes_json"]
        return {"id": str(row["connection_id"] if "connection_id" in keys else row["id"]),
                "tenant_id": str(row["tenant_id"]), "display_name": str(row["display_name"]),
                "passport_id": (
                    str(row["passport_id"])
                    if "passport_id" in keys and row["passport_id"] is not None else None),
                "biography": str(row["biography"]),
                "preferred_occupation": str(row["preferred_occupation"]),
                "tier": str(row["tier"]), "scopes": _clean_scopes(load_json(scopes_value, [])),
                "status": str(row["status"]),
                "actor_id": int(row["actor_id"]) if row["actor_id"] is not None else None,
                "actor_name": row["actor_name"] if "actor_name" in keys else None,
                "actor_alive": bool(row["actor_alive"]) if "actor_alive" in keys and row["actor_alive"] is not None else None,
                "actor_occupation": row["actor_occupation"] if "actor_occupation" in keys else None,
                "last_seen_at": row["last_seen_at"] if "last_seen_at" in keys else None,
                "lease_expires_at": row["lease_expires_at"] if "lease_expires_at" in keys else None,
                "wake_interval_ticks": int(row["wake_interval_ticks"]),
                "created_tick": int(row["created_tick"]) if "created_tick" in keys else None,
                "created_at": row["created_at"] if "created_at" in keys else None}
