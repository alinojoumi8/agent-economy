"""Durable tenant-aware authentication backed by :mod:`hosted.catalog`.

Unlike the generic authentication domain service, this deployment service
binds every invite and session to a tenant at creation time.  There is one
record per credential: no in-memory or dual catalog/auth-store writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from .auth import (
    AuthFailure,
    LoginThrottlePolicy,
    SessionCredentials,
    UserRecord as AuthUserRecord,
)
from .security import (
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    parse_client_key,
    parse_display_name,
    parse_email,
    parse_opaque_token,
    parse_password,
    redact_auth_audit_details,
    validate_csrf_binding,
    verify_password,
)


MIN_TTL = timedelta(minutes=5)
MAX_INVITE_TTL = timedelta(days=30)
MAX_SESSION_TTL = timedelta(days=30)


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ttl(value: timedelta, *, label: str, maximum: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or not (MIN_TTL <= value <= maximum):
        raise ValueError(f"{label} must be between {MIN_TTL} and {maximum}")
    return value


def _tenant(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("tenant_id must be a UUID") from exc


def _auth_user(record: Any) -> AuthUserRecord:
    created = getattr(record, "created_at", None)
    if created is None:
        raise RuntimeError("catalog user record is missing created_at")
    return AuthUserRecord(
        user_id=str(record.id),
        email=str(record.email_normalized),
        display_name=str(record.display_name),
        password_hash=str(record.password_hash),
        created_at=created,
        disabled_at=getattr(record, "disabled_at", None),
    )


@dataclass(frozen=True)
class TenantBoundSession:
    token_hash: str
    csrf_token_hash: str
    user_id: str
    tenant_id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class CatalogAuthenticatedSession:
    user: AuthUserRecord
    session: TenantBoundSession


def _auth_session(record: Any) -> TenantBoundSession:
    created = getattr(record, "created_at", None)
    if created is None:
        raise RuntimeError("catalog session record is missing created_at")
    return TenantBoundSession(
        token_hash=str(record.token_hash),
        csrf_token_hash=str(record.csrf_secret_hash),
        user_id=str(record.user_id),
        tenant_id=_tenant(record.tenant_id),
        created_at=created,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
    )


class CatalogAuthService:
    """Invite-only auth with tenant membership enforced before session issue."""

    def __init__(
        self,
        catalog: Any,
        *,
        throttle_policy: LoginThrottlePolicy | None = None,
        invite_ttl: timedelta = timedelta(days=7),
        session_ttl: timedelta = timedelta(hours=12),
        token_random_bytes: Callable[[int], bytes] | None = None,
        password_random_bytes: Callable[[int], bytes] | None = None,
    ) -> None:
        if catalog is None:
            raise ValueError("catalog is required")
        self.catalog = catalog
        self.throttle_policy = throttle_policy or LoginThrottlePolicy()
        self.invite_ttl = _ttl(invite_ttl, label="invite_ttl", maximum=MAX_INVITE_TTL)
        self.session_ttl = _ttl(session_ttl, label="session_ttl", maximum=MAX_SESSION_TTL)
        self._token_random_bytes = token_random_bytes or secrets.token_bytes
        self._password_random_bytes = password_random_bytes or secrets.token_bytes
        self._dummy_password_hash = hash_password(
            "dummy-password-never-valid", random_bytes=lambda size: b"\0" * size
        )

    def _token(self) -> str:
        return generate_opaque_token(self._token_random_bytes)

    def _tenant_is_active(self, tenant_id: UUID) -> bool:
        """Fail closed for production catalogs while retaining small test adapters."""

        lookup = getattr(self.catalog, "get_tenant", None)
        if lookup is None:
            return True
        tenant = lookup(tenant_id)
        return tenant is not None and str(getattr(tenant, "status", "")) == "active"

    @staticmethod
    def _account_throttle_hash(tenant_id: UUID, email: str) -> str:
        material = f"ae-tenant-login-account-v1\0{tenant_id}\0{email}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _client_account_throttle_hash(
        tenant_id: UUID, email: str, client_key: str
    ) -> str:
        material = f"ae-tenant-login-client-v1\0{tenant_id}\0{email}\0{client_key}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _audit(
        self,
        tenant_id: UUID,
        event: str,
        now: datetime,
        *,
        actor_user_id: UUID | str | None = None,
        **details: Any,
    ) -> None:
        self.catalog.append_auth_audit(
            tenant_id,
            event=event,
            occurred_at=now,
            actor_user_id=actor_user_id,
            details=redact_auth_audit_details(details),
        )

    def issue_invite(
        self,
        *,
        tenant_id: UUID | str,
        email: object,
        role: str,
        now: datetime,
        created_by_user_id: UUID | str,
        display_name_hint: object | None = None,
        ttl: timedelta | None = None,
    ) -> str:
        tenant = _tenant(tenant_id)
        current = _utc(now, "now")
        canonical_email = parse_email(email)
        if display_name_hint is not None:
            parse_display_name(display_name_hint)
        lifetime = _ttl(ttl or self.invite_ttl, label="invite ttl", maximum=MAX_INVITE_TTL)
        token = self._token()
        audit_details = redact_auth_audit_details({
            "email_fingerprint": hashlib.sha256(canonical_email.encode("utf-8")).hexdigest(),
            "role": role,
            "expires_at": (current + lifetime).isoformat(),
        })
        self.catalog.create_invitation_with_audit(
            tenant,
            email=canonical_email,
            role=role,
            token_hash=hash_opaque_token(token),
            invited_by_user_id=created_by_user_id,
            expires_at=current + lifetime,
            occurred_at=current,
            event="auth.invite.issued",
            audit_details=audit_details,
        )
        return token

    def revoke_invite(self, invite_token: object, *, now: datetime) -> bool:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(invite_token)
        invitation = self.catalog.lookup_invitation_by_hash(token_hash)
        if invitation is None:
            return False
        revoked = self.catalog.revoke_invitation_by_hash(token_hash)
        self._audit(invitation.tenant_id, "auth.invite.revoked", current, revoked=revoked)
        return bool(revoked)

    def register_with_invite(
        self,
        *,
        invite_token: object,
        email: object,
        display_name: object,
        password: object,
        now: datetime,
    ) -> AuthUserRecord:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(invite_token)
        canonical_email = parse_email(email)
        canonical_name = parse_display_name(display_name)
        secret = parse_password(password)
        invitation = self.catalog.lookup_invitation_by_hash(token_hash)
        if invitation is None or invitation.email_normalized != canonical_email:
            raise AuthFailure("invalid_invite")
        if not self._tenant_is_active(_tenant(invitation.tenant_id)):
            raise AuthFailure("invalid_invite")
        existing_user = self.catalog.get_user_by_email(canonical_email)
        expected_existing_user_id: UUID | None = None
        registration_password_hash: str
        if existing_user is not None:
            existing_password_valid = verify_password(
                secret, str(existing_user.password_hash)
            )
            if not existing_password_valid or existing_user.disabled_at is not None:
                raise AuthFailure("invalid_invite")
            existing_id = getattr(existing_user, "id", None)
            try:
                expected_existing_user_id = (
                    existing_id if isinstance(existing_id, UUID) else UUID(str(existing_id))
                )
            except (TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError("catalog user record has an invalid id") from exc
            registration_password_hash = str(existing_user.password_hash)
        else:
            registration_password_hash = hash_password(
                secret, random_bytes=self._password_random_bytes
            )
        result = self.catalog.redeem_invitation_with_user(
            token_hash,
            email=canonical_email,
            display_name=canonical_name,
            password_hash=registration_password_hash,
            redeemed_at=current,
            audit_event="auth.registration.completed",
            audit_details=redact_auth_audit_details({
                "email_fingerprint": hashlib.sha256(canonical_email.encode("utf-8")).hexdigest()
            }),
            user_id=uuid4(),
            expected_existing_user_id=expected_existing_user_id,
        )
        if result is None:
            raise AuthFailure("invalid_invite")
        user, _membership = result
        auth_user = _auth_user(user)
        return auth_user

    def login(
        self,
        *,
        tenant_id: UUID | str,
        email: object,
        password: object,
        client_key: object,
        now: datetime,
    ) -> SessionCredentials:
        tenant = _tenant(tenant_id)
        current = _utc(now, "now")
        canonical_email = parse_email(email)
        secret = parse_password(password)
        client = parse_client_key(client_key)
        if not self._tenant_is_active(tenant):
            # Keep the expensive password path for absent/suspended tenants so
            # callers receive the same credential failure without an FK-backed
            # audit/attempt write becoming a tenant-existence oracle.
            verify_password(secret, self._dummy_password_hash)
            raise AuthFailure("invalid_credentials")
        account_hash = self._account_throttle_hash(tenant, canonical_email)
        client_account_hash = self._client_account_throttle_hash(
            tenant, canonical_email, client
        )
        since = current - self.throttle_policy.window
        reservation = self.catalog.reserve_login_attempt(
            tenant,
            account_hash,
            client_account_hash,
            since=since,
            occurred_at=current,
            max_failures=self.throttle_policy.max_failures,
        )
        if not bool(getattr(reservation, "tenant_active", False)):
            verify_password(secret, self._dummy_password_hash)
            raise AuthFailure("invalid_credentials")
        account_failures = list(getattr(reservation, "account_failures", ()))
        client_failures = list(
            getattr(reservation, "client_account_failures", ())
        )
        retry_after = max(
            self.throttle_policy.retry_after_seconds(account_failures, current),
            self.throttle_policy.retry_after_seconds(client_failures, current),
        )
        if not bool(getattr(reservation, "reserved", False)):
            if not retry_after:
                raise RuntimeError("login throttle refused a reservation without a retry window")
            self._audit(tenant, "auth.login.throttled", current, retry_after_seconds=retry_after)
            raise AuthFailure("login_throttled", retry_after_seconds=retry_after)

        user = self.catalog.get_user_by_email(canonical_email)
        membership = (
            self.catalog.get_membership(tenant, user.id) if user is not None else None
        )
        candidate_hash = user.password_hash if user is not None else self._dummy_password_hash
        verified = verify_password(secret, candidate_hash)
        eligible = (
            user is not None
            and user.disabled_at is None
            and membership is not None
            and membership.status == "active"
            and membership.role in {"observer", "agent_owner", "admin"}
        )
        if not verified or not eligible:
            self._audit(
                tenant,
                "auth.login.rejected" if not retry_after else "auth.login.throttled",
                current,
                retry_after_seconds=retry_after,
            )
            if retry_after:
                raise AuthFailure("login_throttled", retry_after_seconds=retry_after)
            raise AuthFailure("invalid_credentials")

        assert user is not None
        self.catalog.record_login_attempt(
            tenant,
            account_hash,
            client_account_hash=client_account_hash,
            succeeded=True,
            occurred_at=current,
            user_id=user.id,
        )
        session_token = self._token()
        csrf_token = self._token()
        for _ in range(3):
            if session_token != csrf_token:
                break
            csrf_token = self._token()
        if session_token == csrf_token:
            raise RuntimeError("secure random source repeated session and CSRF material")
        expires = current + self.session_ttl
        session = self.catalog.create_session(
            tenant,
            user.id,
            token_hash=hash_opaque_token(session_token),
            csrf_secret_hash=hash_opaque_token(csrf_token),
            expires_at=expires,
        )
        try:
            self._audit(tenant, "auth.login.completed", current, actor_user_id=user.id)
        except Exception:
            self.catalog.revoke_session(tenant, session.id)
            raise
        return SessionCredentials(session_token, csrf_token, expires)

    def authenticate_session(
        self, session_token: object, *, now: datetime
    ) -> CatalogAuthenticatedSession:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(session_token)
        session = self.catalog.lookup_session_by_hash(token_hash)
        if session is None or current >= session.expires_at:
            raise AuthFailure("invalid_session")
        if not self._tenant_is_active(_tenant(session.tenant_id)):
            raise AuthFailure("invalid_session")
        user = self.catalog.get_user_by_id(session.user_id)
        membership = (
            self.catalog.get_membership(session.tenant_id, session.user_id)
            if user is not None
            else None
        )
        if (
            user is None
            or user.disabled_at is not None
            or membership is None
            or membership.status != "active"
        ):
            raise AuthFailure("invalid_session")
        return CatalogAuthenticatedSession(_auth_user(user), _auth_session(session))

    def authenticate_csrf(
        self,
        *,
        session_token: object,
        submitted_csrf_token: object,
        csrf_cookie_token: object,
        now: datetime,
    ) -> CatalogAuthenticatedSession:
        authenticated = self.authenticate_session(session_token, now=now)
        if not validate_csrf_binding(
            submitted_csrf_token,
            csrf_cookie_token,
            authenticated.session.csrf_token_hash,
        ):
            raise AuthFailure("invalid_csrf")
        return authenticated

    def revoke_session(self, session_token: object, *, now: datetime) -> bool:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(session_token)
        session = self.catalog.lookup_session_by_hash(token_hash)
        if session is None:
            return False
        revoked = self.catalog.revoke_session_by_hash(token_hash)
        self._audit(
            session.tenant_id,
            "auth.session.revoked",
            current,
            actor_user_id=session.user_id,
            revoked=revoked,
        )
        return bool(revoked)


__all__ = ["CatalogAuthService", "CatalogAuthenticatedSession", "TenantBoundSession"]
