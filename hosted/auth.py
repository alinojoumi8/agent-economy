"""Invite-only hosted authentication domain services.

The service owns validation and security policy; an adapter owns durable
transactions.  A PostgreSQL catalog can implement :class:`AuthStore` without
coupling hosted identity to any simulation's replay-sensitive SQLite file.
"""
from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from hosted.security import (
    SecurityValidationError,
    build_csrf_cookie,
    build_session_cookie,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    parse_client_key,
    parse_display_name,
    parse_email,
    parse_opaque_token,
    parse_password,
    parse_token_hash,
    redact_auth_audit_details,
    validate_csrf_binding,
    validate_password_hash,
    verify_password,
)


MAX_INVITE_TTL = timedelta(days=30)
MAX_SESSION_TTL = timedelta(days=30)
MIN_CREDENTIAL_TTL = timedelta(minutes=5)


def _utc(value: datetime, field: str = "timestamp") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SecurityValidationError(f"{field} must be timezone-aware")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise SecurityValidationError(f"{field} is invalid") from exc
    if offset is None:
        raise SecurityValidationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _record_id(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not (1 <= len(value) <= 128):
        raise SecurityValidationError(f"{field} must be a bounded identifier")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise SecurityValidationError(f"{field} must be printable ASCII without spaces")
    return value


def _ttl(value: timedelta, maximum: timedelta, field: str) -> timedelta:
    if not isinstance(value, timedelta):
        raise SecurityValidationError(f"{field} must be a timedelta")
    if value < MIN_CREDENTIAL_TTL or value > maximum:
        raise SecurityValidationError(
            f"{field} must be between {MIN_CREDENTIAL_TTL} and {maximum}"
        )
    return value


@dataclass(frozen=True)
class InviteRecord:
    token_hash: str
    email: str
    created_at: datetime
    expires_at: datetime
    display_name_hint: str | None = None
    created_by_user_id: str | None = None
    redeemed_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_hash", parse_token_hash(self.token_hash))
        object.__setattr__(self, "email", parse_email(self.email))
        created = _utc(self.created_at, "created_at")
        expires = _utc(self.expires_at, "expires_at")
        if expires <= created:
            raise SecurityValidationError("invite expiry must follow creation")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if self.display_name_hint is not None:
            object.__setattr__(
                self, "display_name_hint", parse_display_name(self.display_name_hint)
            )
        if self.created_by_user_id is not None:
            object.__setattr__(
                self,
                "created_by_user_id",
                _record_id(self.created_by_user_id, "created_by_user_id"),
            )
        for field in ("redeemed_at", "revoked_at"):
            value = getattr(self, field)
            if value is not None:
                normalized = _utc(value, field)
                if normalized < created:
                    raise SecurityValidationError(f"{field} predates invite creation")
                object.__setattr__(self, field, normalized)


@dataclass(frozen=True)
class PendingUser:
    email: str
    display_name: str
    password_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", parse_email(self.email))
        object.__setattr__(self, "display_name", parse_display_name(self.display_name))
        object.__setattr__(self, "password_hash", validate_password_hash(self.password_hash))


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    email: str
    display_name: str
    password_hash: str
    created_at: datetime
    disabled_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _record_id(self.user_id, "user_id"))
        object.__setattr__(self, "email", parse_email(self.email))
        object.__setattr__(self, "display_name", parse_display_name(self.display_name))
        object.__setattr__(self, "password_hash", validate_password_hash(self.password_hash))
        created = _utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created)
        if self.disabled_at is not None:
            disabled = _utc(self.disabled_at, "disabled_at")
            if disabled < created:
                raise SecurityValidationError("disabled_at predates user creation")
            object.__setattr__(self, "disabled_at", disabled)


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str
    csrf_token_hash: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_hash", parse_token_hash(self.token_hash))
        object.__setattr__(self, "csrf_token_hash", parse_token_hash(self.csrf_token_hash))
        object.__setattr__(self, "user_id", _record_id(self.user_id, "user_id"))
        created = _utc(self.created_at, "created_at")
        expires = _utc(self.expires_at, "expires_at")
        if expires <= created:
            raise SecurityValidationError("session expiry must follow creation")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if self.revoked_at is not None:
            revoked = _utc(self.revoked_at, "revoked_at")
            if revoked < created:
                raise SecurityValidationError("revoked_at predates session creation")
            object.__setattr__(self, "revoked_at", revoked)


@dataclass(frozen=True)
class SessionCredentials:
    session_token: str
    csrf_token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_token", parse_opaque_token(self.session_token))
        object.__setattr__(self, "csrf_token", parse_opaque_token(self.csrf_token))
        if self.session_token == self.csrf_token:
            raise SecurityValidationError("session and CSRF tokens must be distinct")
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))

    @property
    def session_cookie(self) -> str:
        return build_session_cookie(self.session_token)

    @property
    def csrf_cookie(self) -> str:
        return build_csrf_cookie(self.csrf_token)


@dataclass(frozen=True)
class AuthenticatedSession:
    user: UserRecord
    session: SessionRecord


@dataclass(frozen=True)
class LoginThrottlePolicy:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if (isinstance(self.max_failures, bool)
                or not isinstance(self.max_failures, int)
                or not (1 <= self.max_failures <= 20)):
            raise SecurityValidationError("max_failures must be an integer from 1 to 20")
        if not isinstance(self.window, timedelta) or not (
                timedelta(seconds=30) <= self.window <= timedelta(hours=24)):
            raise SecurityValidationError("throttle window must be 30 seconds to 24 hours")

    def retry_after_seconds(
            self, failure_times: Sequence[datetime], now: datetime) -> int:
        current = _utc(now, "now")
        boundary = current - self.window
        recent = sorted(
            timestamp
            for value in failure_times
            if boundary < (timestamp := _utc(value, "failure timestamp")) <= current
        )
        if len(recent) < self.max_failures:
            return 0
        lock_started = recent[-self.max_failures]
        return max(0, math.ceil((lock_started + self.window - current).total_seconds()))


class AuthFailure(Exception):
    """A stable, secret-free authentication-domain failure."""

    def __init__(self, code: str, *, retry_after_seconds: int = 0) -> None:
        self.code = _record_id(code, "auth failure code")
        self.retry_after_seconds = max(0, int(retry_after_seconds))
        super().__init__(code)


@runtime_checkable
class AuthStore(Protocol):
    """Transactional persistence boundary for an R22 hosted catalog.

    ``redeem_invite`` must atomically confirm that the invite remains unused,
    unrevoked, and unexpired while creating a unique user.  Token arguments and
    record fields are SHA-256 hashes, never raw credentials.
    """

    def add_invite(self, invite: InviteRecord) -> None: ...

    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None: ...

    def redeem_invite(
            self,
            token_hash: str,
            pending_user: PendingUser,
            redeemed_at: datetime) -> UserRecord | None: ...

    def revoke_invite(self, token_hash: str, revoked_at: datetime) -> bool: ...

    def get_user_by_email(self, email: str) -> UserRecord | None: ...

    def get_user_by_id(self, user_id: str) -> UserRecord | None: ...

    def add_session(self, session: SessionRecord) -> None: ...

    def get_session_by_token_hash(self, token_hash: str) -> SessionRecord | None: ...

    def revoke_session(self, token_hash: str, revoked_at: datetime) -> bool: ...

    def login_failures_since(
            self, throttle_key: str, since: datetime) -> Sequence[datetime]: ...

    def record_login_failure(
            self, throttle_key: str, occurred_at: datetime) -> None: ...

    def clear_login_failures(self, throttle_key: str) -> None: ...

    def record_auth_audit(
            self,
            event: str,
            occurred_at: datetime,
            actor_user_id: str | None,
            details: Mapping[str, Any]) -> None: ...


def login_throttle_key(email: object, client_key: object) -> str:
    canonical_email = parse_email(email)
    canonical_client = parse_client_key(client_key)
    material = f"ae-login-throttle-v1\0{canonical_email}\0{canonical_client}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password(
        "dummy-password-never-valid",
        random_bytes=lambda size: b"\0" * size,
    )


class AuthService:
    """Apply invite, password, session, CSRF, and throttling policy."""

    def __init__(
            self,
            store: AuthStore,
            *,
            throttle_policy: LoginThrottlePolicy | None = None,
            invite_ttl: timedelta = timedelta(days=7),
            session_ttl: timedelta = timedelta(hours=12),
            token_random_bytes: Callable[[int], bytes] | None = None,
            password_random_bytes: Callable[[int], bytes] | None = None,
            dummy_password_hash: str | None = None) -> None:
        if not isinstance(store, AuthStore):
            raise TypeError("store must implement AuthStore")
        self.store = store
        self.throttle_policy = throttle_policy or LoginThrottlePolicy()
        self.invite_ttl = _ttl(invite_ttl, MAX_INVITE_TTL, "invite_ttl")
        self.session_ttl = _ttl(session_ttl, MAX_SESSION_TTL, "session_ttl")
        self._token_random_bytes = token_random_bytes or secrets.token_bytes
        self._password_random_bytes = password_random_bytes or secrets.token_bytes
        self._dummy_password_hash = validate_password_hash(
            dummy_password_hash or _dummy_password_hash()
        )

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _audit(
            self,
            event: str,
            now: datetime,
            *,
            actor_user_id: str | None = None,
            **details: Any) -> None:
        self.store.record_auth_audit(
            _record_id(event, "audit event"),
            _utc(now, "now"),
            actor_user_id,
            redact_auth_audit_details(details),
        )

    def _token(self) -> str:
        return generate_opaque_token(self._token_random_bytes)

    def issue_invite(
            self,
            *,
            email: object,
            now: datetime,
            display_name_hint: object | None = None,
            created_by_user_id: str | None = None,
            ttl: timedelta | None = None) -> str:
        current = _utc(now, "now")
        canonical_email = parse_email(email)
        hint = parse_display_name(display_name_hint) if display_name_hint is not None else None
        creator = (
            _record_id(created_by_user_id, "created_by_user_id")
            if created_by_user_id is not None else None
        )
        lifetime = _ttl(
            self.invite_ttl if ttl is None else ttl,
            MAX_INVITE_TTL,
            "invite ttl",
        )
        token = self._token()
        self.store.add_invite(InviteRecord(
            token_hash=hash_opaque_token(token),
            email=canonical_email,
            display_name_hint=hint,
            created_at=current,
            expires_at=current + lifetime,
            created_by_user_id=creator,
        ))
        self._audit(
            "auth.invite.issued",
            current,
            actor_user_id=creator,
            email_fingerprint=self._fingerprint(canonical_email),
            expires_at=(current + lifetime).isoformat(),
        )
        return token

    def revoke_invite(self, invite_token: object, *, now: datetime) -> bool:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(invite_token)
        revoked = self.store.revoke_invite(token_hash, current)
        self._audit("auth.invite.revoked", current, revoked=revoked)
        return revoked

    def register_with_invite(
            self,
            *,
            invite_token: object,
            email: object,
            display_name: object,
            password: object,
            now: datetime) -> UserRecord:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(invite_token)
        canonical_email = parse_email(email)
        canonical_name = parse_display_name(display_name)
        secret = parse_password(password)
        invite = self.store.get_invite_by_token_hash(token_hash)
        fingerprint = self._fingerprint(canonical_email)
        if invite is None or invite.email != canonical_email:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="invalid_invite")
            raise AuthFailure("invalid_invite")
        if invite.revoked_at is not None:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="revoked_invite")
            raise AuthFailure("revoked_invite")
        if invite.redeemed_at is not None:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="redeemed_invite")
            raise AuthFailure("redeemed_invite")
        if current >= invite.expires_at:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="expired_invite")
            raise AuthFailure("expired_invite")
        if self.store.get_user_by_email(canonical_email) is not None:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="account_exists")
            raise AuthFailure("account_exists")
        pending = PendingUser(
            email=canonical_email,
            display_name=canonical_name,
            password_hash=hash_password(
                secret,
                random_bytes=self._password_random_bytes,
            ),
        )
        user = self.store.redeem_invite(token_hash, pending, current)
        if user is None:
            self._audit("auth.registration.rejected", current,
                        email_fingerprint=fingerprint, reason="invite_unavailable")
            raise AuthFailure("invite_unavailable")
        self._audit(
            "auth.registration.completed",
            current,
            actor_user_id=user.user_id,
            email_fingerprint=fingerprint,
        )
        return user

    def _create_session(self, user: UserRecord, now: datetime) -> SessionCredentials:
        session_token = self._token()
        csrf_token = self._token()
        for _ in range(3):
            if csrf_token != session_token:
                break
            csrf_token = self._token()
        if csrf_token == session_token:
            raise RuntimeError("secure random source repeated session and CSRF material")
        expires = now + self.session_ttl
        self.store.add_session(SessionRecord(
            token_hash=hash_opaque_token(session_token),
            csrf_token_hash=hash_opaque_token(csrf_token),
            user_id=user.user_id,
            created_at=now,
            expires_at=expires,
        ))
        self._audit(
            "auth.session.created",
            now,
            actor_user_id=user.user_id,
            expires_at=expires.isoformat(),
        )
        return SessionCredentials(session_token, csrf_token, expires)

    def login(
            self,
            *,
            email: object,
            password: object,
            client_key: object,
            now: datetime) -> SessionCredentials:
        current = _utc(now, "now")
        canonical_email = parse_email(email)
        secret = parse_password(password)
        canonical_client = parse_client_key(client_key)
        throttle_key = login_throttle_key(canonical_email, canonical_client)
        since = current - self.throttle_policy.window
        failures = list(self.store.login_failures_since(throttle_key, since))
        retry_after = self.throttle_policy.retry_after_seconds(failures, current)
        fingerprint = self._fingerprint(canonical_email)
        if retry_after:
            self._audit(
                "auth.login.throttled",
                current,
                email_fingerprint=fingerprint,
                retry_after_seconds=retry_after,
            )
            raise AuthFailure("login_throttled", retry_after_seconds=retry_after)

        user = self.store.get_user_by_email(canonical_email)
        candidate_hash = user.password_hash if user is not None else self._dummy_password_hash
        verified = verify_password(secret, candidate_hash)
        if user is None or not verified:
            self.store.record_login_failure(throttle_key, current)
            retry_after = self.throttle_policy.retry_after_seconds(
                [*failures, current], current
            )
            event = "auth.login.throttled" if retry_after else "auth.login.rejected"
            self._audit(
                event,
                current,
                email_fingerprint=fingerprint,
                reason="invalid_credentials",
                retry_after_seconds=retry_after,
            )
            if retry_after:
                raise AuthFailure("login_throttled", retry_after_seconds=retry_after)
            raise AuthFailure("invalid_credentials")
        if user.disabled_at is not None:
            self._audit(
                "auth.login.rejected",
                current,
                actor_user_id=user.user_id,
                email_fingerprint=fingerprint,
                reason="account_disabled",
            )
            raise AuthFailure("account_disabled")
        self.store.clear_login_failures(throttle_key)
        credentials = self._create_session(user, current)
        self._audit(
            "auth.login.completed",
            current,
            actor_user_id=user.user_id,
            email_fingerprint=fingerprint,
        )
        return credentials

    def authenticate_session(
            self, session_token: object, *, now: datetime) -> AuthenticatedSession:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(session_token)
        session = self.store.get_session_by_token_hash(token_hash)
        if session is None:
            self._audit("auth.session.rejected", current, reason="invalid_session")
            raise AuthFailure("invalid_session")
        if session.revoked_at is not None:
            self._audit("auth.session.rejected", current,
                        actor_user_id=session.user_id, reason="revoked_session")
            raise AuthFailure("revoked_session")
        if current >= session.expires_at:
            self._audit("auth.session.rejected", current,
                        actor_user_id=session.user_id, reason="expired_session")
            raise AuthFailure("expired_session")
        user = self.store.get_user_by_id(session.user_id)
        if user is None:
            self._audit("auth.session.rejected", current, reason="invalid_session")
            raise AuthFailure("invalid_session")
        if user.disabled_at is not None:
            self._audit("auth.session.rejected", current,
                        actor_user_id=user.user_id, reason="account_disabled")
            raise AuthFailure("account_disabled")
        return AuthenticatedSession(user, session)

    def authenticate_csrf(
            self,
            *,
            session_token: object,
            submitted_csrf_token: object,
            csrf_cookie_token: object,
            now: datetime) -> AuthenticatedSession:
        authenticated = self.authenticate_session(session_token, now=now)
        if not validate_csrf_binding(
                submitted_csrf_token,
                csrf_cookie_token,
                authenticated.session.csrf_token_hash):
            self._audit(
                "auth.csrf.rejected",
                _utc(now, "now"),
                actor_user_id=authenticated.user.user_id,
                reason="invalid_csrf",
            )
            raise AuthFailure("invalid_csrf")
        return authenticated

    def revoke_session(self, session_token: object, *, now: datetime) -> bool:
        current = _utc(now, "now")
        token_hash = hash_opaque_token(session_token)
        session = self.store.get_session_by_token_hash(token_hash)
        revoked = self.store.revoke_session(token_hash, current) if session is not None else False
        self._audit(
            "auth.session.revoked",
            current,
            actor_user_id=session.user_id if session is not None else None,
            revoked=revoked,
        )
        return revoked
