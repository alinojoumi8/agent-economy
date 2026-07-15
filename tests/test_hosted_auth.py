from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pytest

from hosted.auth import (
    AuthFailure,
    AuthService,
    AuthStore,
    InviteRecord,
    LoginThrottlePolicy,
    PendingUser,
    SessionRecord,
    UserRecord,
    login_throttle_key,
)
from hosted.security import (
    CSRF_COOKIE_NAME,
    REDACTED,
    SESSION_COOKIE_NAME,
    SecurityValidationError,
    build_csrf_cookie,
    build_session_cookie,
    expire_csrf_cookie,
    expire_session_cookie,
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


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery staple"


class DeterministicBytes:
    def __init__(self) -> None:
        self.counter = 0

    def __call__(self, size: int) -> bytes:
        self.counter += 1
        return bytes([self.counter]) * size


class MemoryAuthStore:
    """Strict fake exercising the same atomic boundary required of Postgres."""

    def __init__(self) -> None:
        self.invites: dict[str, InviteRecord] = {}
        self.users_by_id: dict[str, UserRecord] = {}
        self.user_ids_by_email: dict[str, str] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.failures: dict[str, list[datetime]] = defaultdict(list)
        self.audits: list[dict[str, Any]] = []
        self.force_redeem_race = False

    def add_invite(self, invite: InviteRecord) -> None:
        if invite.token_hash in self.invites:
            raise ValueError("duplicate invite hash")
        self.invites[invite.token_hash] = invite

    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        return self.invites.get(token_hash)

    def redeem_invite(
            self,
            token_hash: str,
            pending_user: PendingUser,
            redeemed_at: datetime) -> UserRecord | None:
        invite = self.invites.get(token_hash)
        if (self.force_redeem_race or invite is None or invite.redeemed_at is not None
                or invite.revoked_at is not None or redeemed_at >= invite.expires_at
                or pending_user.email in self.user_ids_by_email):
            return None
        user = UserRecord(
            user_id=f"user-{len(self.users_by_id) + 1}",
            email=pending_user.email,
            display_name=pending_user.display_name,
            password_hash=pending_user.password_hash,
            created_at=redeemed_at,
        )
        self.users_by_id[user.user_id] = user
        self.user_ids_by_email[user.email] = user.user_id
        self.invites[token_hash] = dataclasses.replace(invite, redeemed_at=redeemed_at)
        return user

    def revoke_invite(self, token_hash: str, revoked_at: datetime) -> bool:
        invite = self.invites.get(token_hash)
        if invite is None or invite.revoked_at is not None or invite.redeemed_at is not None:
            return False
        self.invites[token_hash] = dataclasses.replace(invite, revoked_at=revoked_at)
        return True

    def get_user_by_email(self, email: str) -> UserRecord | None:
        user_id = self.user_ids_by_email.get(email)
        return self.users_by_id.get(user_id) if user_id else None

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.users_by_id.get(user_id)

    def add_session(self, session: SessionRecord) -> None:
        if session.token_hash in self.sessions:
            raise ValueError("duplicate session hash")
        self.sessions[session.token_hash] = session

    def get_session_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        return self.sessions.get(token_hash)

    def revoke_session(self, token_hash: str, revoked_at: datetime) -> bool:
        session = self.sessions.get(token_hash)
        if session is None or session.revoked_at is not None:
            return False
        self.sessions[token_hash] = dataclasses.replace(session, revoked_at=revoked_at)
        return True

    def login_failures_since(
            self, throttle_key: str, since: datetime) -> Sequence[datetime]:
        return tuple(value for value in self.failures[throttle_key] if value > since)

    def record_login_failure(self, throttle_key: str, occurred_at: datetime) -> None:
        self.failures[throttle_key].append(occurred_at)

    def clear_login_failures(self, throttle_key: str) -> None:
        self.failures.pop(throttle_key, None)

    def record_auth_audit(
            self,
            event: str,
            occurred_at: datetime,
            actor_user_id: str | None,
            details: Mapping[str, Any]) -> None:
        self.audits.append({
            "event": event,
            "occurred_at": occurred_at,
            "actor_user_id": actor_user_id,
            "details": dict(details),
        })


@pytest.fixture
def auth_store() -> MemoryAuthStore:
    store = MemoryAuthStore()
    assert isinstance(store, AuthStore)
    return store


@pytest.fixture
def auth_service(auth_store: MemoryAuthStore) -> AuthService:
    return AuthService(
        auth_store,
        token_random_bytes=DeterministicBytes(),
        password_random_bytes=lambda size: b"\x7f" * size,
    )


def register_user(
        service: AuthService,
        *,
        email: str = "person@example.com",
        now: datetime = NOW) -> tuple[UserRecord, str]:
    invite = service.issue_invite(email=email, now=now)
    user = service.register_with_invite(
        invite_token=invite,
        email=email,
        display_name="Example Person",
        password=PASSWORD,
        now=now + timedelta(seconds=1),
    )
    return user, invite


def failure_code(callable_) -> str:
    with pytest.raises(AuthFailure) as caught:
        callable_()
    return caught.value.code


def test_password_hash_is_versioned_salted_and_constant_time_verified(monkeypatch):
    encoded = hash_password(PASSWORD, random_bytes=lambda size: b"\x11" * size)
    assert encoded.startswith("ae-scrypt$v1$n=16384,r=8,p=1,l=32$")
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("totally wrong password", encoded)

    calls: list[tuple[object, object]] = []
    import hosted.security as security
    original = security.hmac.compare_digest

    def observed(left, right):
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(security.hmac, "compare_digest", observed)
    assert verify_password(PASSWORD, encoded)
    assert calls and len(calls[-1][0]) == len(calls[-1][1]) == 32


@pytest.mark.parametrize("encoded", [
    "",
    "plaintext-password",
    "ae-scrypt$v2$n=16384,r=8,p=1,l=32$bad$bad",
    "ae-scrypt$v1$n=1,r=8,p=1,l=32$AAAAAAAAAAAAAAAAAAAAAA$" + "A" * 43,
    "x" * 257,
])
def test_password_verification_fails_closed_for_malformed_serializations(encoded):
    assert not verify_password(PASSWORD, encoded)


def test_opaque_tokens_are_exactly_256_bits_and_only_hashes_are_storable():
    token = generate_opaque_token(lambda size: bytes(range(size)))
    assert len(token) == 43
    assert parse_opaque_token(token) == token
    assert hash_opaque_token(token) == (
        "ea866a757e4c38babfa8127cbe9a409d3e1f93a00ff1488ff735fcf917afffd0"
    )
    with pytest.raises(RuntimeError, match="exactly 32 bytes"):
        generate_opaque_token(lambda _size: b"short")


@pytest.mark.parametrize("token", [None, "", "a" * 42, "a" * 44, "!" * 43, "a" * 42 + "="])
def test_malformed_opaque_tokens_are_rejected(token):
    with pytest.raises(SecurityValidationError):
        parse_opaque_token(token)


@pytest.mark.parametrize("email", [
    " person@example.com",
    "person@example.com ",
    "personexample.com",
    ".person@example.com",
    "person..name@example.com",
    "person@localhost",
    "person@-example.com",
    "person@exa_mple.com",
    "a" * 65 + "@example.com",
])
def test_email_parser_rejects_malformed_or_unbounded_values(email):
    with pytest.raises(SecurityValidationError):
        parse_email(email)


def test_external_identity_parsers_are_canonical_and_bounded():
    assert parse_email("Person@Example.COM") == "person@example.com"
    assert parse_display_name("Ren\N{LATIN SMALL LETTER E WITH ACUTE}e") == "Ren\N{LATIN SMALL LETTER E WITH ACUTE}e"
    assert parse_password(PASSWORD) == PASSWORD
    assert parse_client_key("203.0.113.4") == "203.0.113.4"
    for value in ("", " padded ", "x" * 81, "bad\nname"):
        with pytest.raises(SecurityValidationError):
            parse_display_name(value)
    for value in ("short", "x" * 257, "valid password\n"):
        with pytest.raises(SecurityValidationError):
            parse_password(value)
    for value in ("", "has space", "x" * 129, "line\n"):
        with pytest.raises(SecurityValidationError):
            parse_client_key(value)


def test_cookie_helpers_enforce_host_prefix_and_hardened_contract():
    token = generate_opaque_token(lambda size: b"\x22" * size)
    assert build_session_cookie(token) == (
        f"{SESSION_COOKIE_NAME}={token}; Path=/; Secure; HttpOnly; SameSite=Lax"
    )
    assert "Domain=" not in build_session_cookie(token)
    assert build_csrf_cookie(token) == (
        f"{CSRF_COOKIE_NAME}={token}; Path=/; Secure; SameSite=Lax"
    )
    assert "HttpOnly" not in build_csrf_cookie(token)
    assert expire_session_cookie().endswith("SameSite=Lax; Max-Age=0")
    assert expire_csrf_cookie().endswith("SameSite=Lax; Max-Age=0")


def test_csrf_requires_cookie_header_and_server_hash_bindings():
    token = generate_opaque_token(lambda size: b"\x33" * size)
    other = generate_opaque_token(lambda size: b"\x44" * size)
    stored = hash_opaque_token(token)
    assert validate_csrf_binding(token, token, stored)
    assert not validate_csrf_binding(token, other, stored)
    assert not validate_csrf_binding(other, other, stored)
    assert not validate_csrf_binding("malformed", token, stored)
    assert not validate_csrf_binding(token, token, "not-a-hash")


def test_auth_audit_redaction_is_recursive_bounded_and_catches_inline_secrets():
    details = {
        "password": PASSWORD,
        "nested": {
            "session_token": "raw-session",
            "token_hash": "digest",
            "message": (
                "authorization=Bearer-value and token=abc123 and session=raw-session"
            ),
        },
        "headers": ["Bearer raw-bearer", {"Set-Cookie": "raw-cookie"}],
        "email": "person@example.com",
        "blob": b"binary-secret",
    }
    redacted = redact_auth_audit_details(details)
    assert redacted["password"] == REDACTED
    assert redacted["nested"]["session_token"] == REDACTED
    assert redacted["nested"]["token_hash"] == REDACTED
    assert "abc123" not in redacted["nested"]["message"]
    assert "raw-session" not in redacted["nested"]["message"]
    assert "raw-bearer" not in redacted["headers"][0]
    assert redacted["headers"][1]["Set-Cookie"] == REDACTED
    assert redacted["email"] == "person@example.com"
    assert redacted["blob"] == REDACTED
    assert PASSWORD not in repr(redacted)


def test_invite_issue_and_registration_persist_only_hashes(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    raw_invite = auth_service.issue_invite(
        email="Person@Example.com",
        display_name_hint="Example Person",
        created_by_user_id="admin-1",
        now=NOW,
    )
    assert raw_invite not in repr(auth_store.invites)
    invite = auth_store.invites[hash_opaque_token(raw_invite)]
    assert invite.email == "person@example.com"
    assert invite.created_by_user_id == "admin-1"

    user = auth_service.register_with_invite(
        invite_token=raw_invite,
        email="person@example.com",
        display_name="Example Person",
        password=PASSWORD,
        now=NOW + timedelta(seconds=1),
    )
    assert user.user_id == "user-1"
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash)
    assert auth_store.invites[invite.token_hash].redeemed_at is not None
    assert raw_invite not in repr(auth_store.audits)
    assert PASSWORD not in repr(auth_store.audits)


def test_registration_rejects_missing_and_email_mismatched_invites(
        auth_service: AuthService):
    missing = generate_opaque_token(lambda size: b"\xee" * size)
    assert failure_code(lambda: auth_service.register_with_invite(
        invite_token=missing,
        email="person@example.com",
        display_name="Example Person",
        password=PASSWORD,
        now=NOW,
    )) == "invalid_invite"

    invite = auth_service.issue_invite(email="invited@example.com", now=NOW)
    assert failure_code(lambda: auth_service.register_with_invite(
        invite_token=invite,
        email="other@example.com",
        display_name="Example Person",
        password=PASSWORD,
        now=NOW,
    )) == "invalid_invite"


@pytest.mark.parametrize("state,expected", [
    ("revoked", "revoked_invite"),
    ("redeemed", "redeemed_invite"),
    ("expired", "expired_invite"),
])
def test_registration_rejects_revoked_redeemed_and_expired_invites(
        state, expected, auth_service: AuthService, auth_store: MemoryAuthStore):
    issued_at = NOW - timedelta(days=8) if state == "expired" else NOW
    token = auth_service.issue_invite(email="person@example.com", now=issued_at)
    token_hash = hash_opaque_token(token)
    invite = auth_store.invites[token_hash]
    if state == "revoked":
        auth_store.invites[token_hash] = dataclasses.replace(invite, revoked_at=NOW)
    elif state == "redeemed":
        auth_store.invites[token_hash] = dataclasses.replace(invite, redeemed_at=NOW)

    assert failure_code(lambda: auth_service.register_with_invite(
        invite_token=token,
        email="person@example.com",
        display_name="Example Person",
        password=PASSWORD,
        now=NOW,
    )) == expected


def test_registration_fails_closed_if_atomic_redemption_loses_a_race(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    token = auth_service.issue_invite(email="person@example.com", now=NOW)
    auth_store.force_redeem_race = True
    assert failure_code(lambda: auth_service.register_with_invite(
        invite_token=token,
        email="person@example.com",
        display_name="Example Person",
        password=PASSWORD,
        now=NOW + timedelta(seconds=1),
    )) == "invite_unavailable"
    assert not auth_store.users_by_id


def test_login_creates_distinct_hashed_session_and_csrf_credentials(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    user, _ = register_user(auth_service)
    credentials = auth_service.login(
        email=user.email,
        password=PASSWORD,
        client_key="203.0.113.4",
        now=NOW + timedelta(seconds=2),
    )
    assert credentials.session_token != credentials.csrf_token
    stored = auth_store.sessions[hash_opaque_token(credentials.session_token)]
    assert stored.user_id == user.user_id
    assert stored.csrf_token_hash == hash_opaque_token(credentials.csrf_token)
    assert credentials.session_token not in repr(auth_store.sessions)
    assert credentials.csrf_token not in repr(auth_store.sessions)
    assert credentials.session_cookie == build_session_cookie(credentials.session_token)
    assert credentials.csrf_cookie == build_csrf_cookie(credentials.csrf_token)
    assert credentials.session_token not in repr(auth_store.audits)


def test_login_uses_generic_failure_for_unknown_user_and_wrong_password(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    register_user(auth_service)
    wrong = lambda email: auth_service.login(
        email=email,
        password="wrong password value",
        client_key="203.0.113.5",
        now=NOW + timedelta(seconds=2),
    )
    assert failure_code(lambda: wrong("person@example.com")) == "invalid_credentials"
    assert failure_code(lambda: wrong("nobody@example.com")) == "invalid_credentials"
    assert sum(len(values) for values in auth_store.failures.values()) == 2


def test_disabled_user_cannot_log_in_or_reuse_an_existing_session(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    user, _ = register_user(auth_service)
    credentials = auth_service.login(
        email=user.email,
        password=PASSWORD,
        client_key="203.0.113.6",
        now=NOW + timedelta(seconds=2),
    )
    disabled = dataclasses.replace(user, disabled_at=NOW + timedelta(seconds=3))
    auth_store.users_by_id[user.user_id] = disabled
    assert failure_code(lambda: auth_service.login(
        email=user.email,
        password=PASSWORD,
        client_key="203.0.113.7",
        now=NOW + timedelta(seconds=4),
    )) == "account_disabled"
    assert failure_code(lambda: auth_service.authenticate_session(
        credentials.session_token,
        now=NOW + timedelta(seconds=4),
    )) == "account_disabled"


def test_login_throttle_is_bounded_deterministic_and_expires(auth_store: MemoryAuthStore):
    service = AuthService(
        auth_store,
        throttle_policy=LoginThrottlePolicy(max_failures=3, window=timedelta(seconds=60)),
        token_random_bytes=DeterministicBytes(),
        password_random_bytes=lambda size: b"\x55" * size,
    )
    user, _ = register_user(service)

    def attempt(at: datetime, password: str = "wrong password value"):
        return service.login(
            email=user.email,
            password=password,
            client_key="203.0.113.8",
            now=at,
        )

    assert failure_code(lambda: attempt(NOW + timedelta(seconds=2))) == "invalid_credentials"
    assert failure_code(lambda: attempt(NOW + timedelta(seconds=3))) == "invalid_credentials"
    with pytest.raises(AuthFailure) as threshold:
        attempt(NOW + timedelta(seconds=4))
    assert threshold.value.code == "login_throttled"
    assert threshold.value.retry_after_seconds == 58
    with pytest.raises(AuthFailure) as blocked:
        attempt(NOW + timedelta(seconds=30), PASSWORD)
    assert blocked.value.code == "login_throttled"
    assert blocked.value.retry_after_seconds == 32
    assert attempt(NOW + timedelta(seconds=63), PASSWORD).session_token


def test_throttle_storage_key_hides_inputs_and_partitions_clients():
    first = login_throttle_key("Person@example.com", "203.0.113.9")
    same = login_throttle_key("person@EXAMPLE.com", "203.0.113.9")
    other = login_throttle_key("person@example.com", "203.0.113.10")
    assert first == same
    assert first != other
    assert len(first) == 64
    assert "person" not in first and "203" not in first


def test_expired_revoked_and_unknown_sessions_fail_closed(
        auth_service: AuthService, auth_store: MemoryAuthStore):
    user, _ = register_user(auth_service)
    credentials = auth_service.login(
        email=user.email,
        password=PASSWORD,
        client_key="203.0.113.11",
        now=NOW + timedelta(seconds=2),
    )
    assert failure_code(lambda: auth_service.authenticate_session(
        generate_opaque_token(lambda size: b"\xfa" * size),
        now=NOW + timedelta(seconds=3),
    )) == "invalid_session"
    assert failure_code(lambda: auth_service.authenticate_session(
        credentials.session_token,
        now=credentials.expires_at,
    )) == "expired_session"
    assert auth_service.revoke_session(
        credentials.session_token, now=NOW + timedelta(seconds=4)
    )
    assert not auth_service.revoke_session(
        credentials.session_token, now=NOW + timedelta(seconds=5)
    )
    assert failure_code(lambda: auth_service.authenticate_session(
        credentials.session_token,
        now=NOW + timedelta(seconds=6),
    )) == "revoked_session"


def test_service_csrf_authorization_requires_all_three_bindings(
        auth_service: AuthService):
    user, _ = register_user(auth_service)
    credentials = auth_service.login(
        email=user.email,
        password=PASSWORD,
        client_key="203.0.113.12",
        now=NOW + timedelta(seconds=2),
    )
    authenticated = auth_service.authenticate_csrf(
        session_token=credentials.session_token,
        submitted_csrf_token=credentials.csrf_token,
        csrf_cookie_token=credentials.csrf_token,
        now=NOW + timedelta(seconds=3),
    )
    assert authenticated.user.user_id == user.user_id
    other = generate_opaque_token(lambda size: b"\xfb" * size)
    assert failure_code(lambda: auth_service.authenticate_csrf(
        session_token=credentials.session_token,
        submitted_csrf_token=credentials.csrf_token,
        csrf_cookie_token=other,
        now=NOW + timedelta(seconds=3),
    )) == "invalid_csrf"


def test_record_validation_rejects_naive_time_and_malformed_login_input(
        auth_service: AuthService):
    with pytest.raises(SecurityValidationError, match="timezone-aware"):
        auth_service.issue_invite(
            email="person@example.com",
            now=datetime(2026, 7, 15, 12, 0),
        )
    with pytest.raises(SecurityValidationError, match="password"):
        auth_service.login(
            email="person@example.com",
            password="short",
            client_key="203.0.113.13",
            now=NOW,
        )
    with pytest.raises(SecurityValidationError, match="client_key"):
        auth_service.login(
            email="person@example.com",
            password=PASSWORD,
            client_key="bad client key",
            now=NOW,
        )
