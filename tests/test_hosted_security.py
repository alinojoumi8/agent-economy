from __future__ import annotations

import pytest

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


PASSWORD = "correct horse battery staple"


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


@pytest.mark.parametrize(
    "token",
    [None, "", "a" * 42, "a" * 44, "!" * 43, "a" * 42 + "="],
)
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
    assert parse_display_name(
        "Ren\N{LATIN SMALL LETTER E WITH ACUTE}e"
    ) == "Ren\N{LATIN SMALL LETTER E WITH ACUTE}e"
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
