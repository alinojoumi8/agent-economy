"""Security primitives shared by hosted authentication adapters.

Only hashes cross the storage boundary.  Raw invite, session, and CSRF values
are returned to a caller exactly once and should be delivered over TLS.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping


SESSION_COOKIE_NAME = "__Host-ae_session"
CSRF_COOKIE_NAME = "__Host-ae_csrf"
OPAQUE_TOKEN_BYTES = 32
OPAQUE_TOKEN_LENGTH = 43
PASSWORD_HASH_VERSION = 1
REDACTED = "[REDACTED]"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_PART_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+\Z")
_DOMAIN_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PASSWORD_HASH_RE = re.compile(
    r"ae-scrypt\$v1\$n=(\d+),r=(\d+),p=(\d+),l=(\d+)"
    r"\$([A-Za-z0-9_-]{22})\$([A-Za-z0-9_-]{43})\Z"
)
_AUTH_SECRET_KEY_PARTS = (
    "authorization",
    "credential",
    "csrf",
    "cookie",
    "invite",
    "invite_token",
    "password",
    "passwd",
    "secret",
    "session",
    "session_token",
    "token",
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|authorization|credential|"
    r"csrf(?:_token)?|invite(?:_token)?|session(?:_token)?|token|cookie)"
    r"\s*[:=]\s*([^\s,;]+)"
)


class SecurityValidationError(ValueError):
    """Raised when an authentication input violates the public contract."""


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise SecurityValidationError(f"{field} must be a string")
    return value


def parse_email(value: object) -> str:
    """Return a canonical, bounded invitation/login email identifier."""
    email = _require_str(value, "email")
    if email != email.strip() or not (3 <= len(email) <= 254):
        raise SecurityValidationError("email must be 3 to 254 characters without outer whitespace")
    if email.count("@") != 1:
        raise SecurityValidationError("email must contain one @ separator")
    local, raw_domain = email.rsplit("@", 1)
    if not (1 <= len(local) <= 64) or not _LOCAL_PART_RE.fullmatch(local):
        raise SecurityValidationError("email local part is invalid")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise SecurityValidationError("email local part has invalid dot placement")
    try:
        domain = raw_domain.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise SecurityValidationError("email domain is invalid") from exc
    if len(domain) > 253 or "." not in domain:
        raise SecurityValidationError("email domain must be a bounded DNS name")
    labels = domain.split(".")
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        raise SecurityValidationError("email domain is invalid")
    canonical = f"{local.lower()}@{domain}"
    if len(canonical) > 254:
        raise SecurityValidationError("canonical email exceeds 254 characters")
    return canonical


def parse_display_name(value: object) -> str:
    """Validate a human label while preserving meaningful internal spaces."""
    raw = _require_str(value, "display_name")
    normalized = unicodedata.normalize("NFKC", raw)
    if raw != raw.strip() or not (1 <= len(normalized) <= 80):
        raise SecurityValidationError(
            "display_name must be 1 to 80 characters without outer whitespace"
        )
    if len(normalized.encode("utf-8")) > 320:
        raise SecurityValidationError("display_name exceeds the UTF-8 byte limit")
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise SecurityValidationError("display_name contains a control character")
    return normalized


def parse_password(value: object) -> str:
    """Bound password work without normalizing or trimming the secret."""
    password = _require_str(value, "password")
    if not (12 <= len(password) <= 256):
        raise SecurityValidationError("password must be 12 to 256 characters")
    if len(password.encode("utf-8")) > 1024:
        raise SecurityValidationError("password exceeds the UTF-8 byte limit")
    if any(unicodedata.category(char) == "Cc" for char in password):
        raise SecurityValidationError("password contains a control character")
    return password


def parse_client_key(value: object) -> str:
    """Validate a bounded deployment-supplied login throttling discriminator."""
    key = _require_str(value, "client_key")
    if key != key.strip() or not (1 <= len(key) <= 128):
        raise SecurityValidationError(
            "client_key must be 1 to 128 characters without outer whitespace"
        )
    if any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise SecurityValidationError("client_key must contain printable ASCII without spaces")
    return key


def parse_opaque_token(value: object) -> str:
    token = _require_str(value, "token")
    if not _TOKEN_RE.fullmatch(token):
        raise SecurityValidationError("token must be a 256-bit unpadded base64url value")
    try:
        decoded = base64.b64decode(token + "=", altchars=b"-_", validate=True)
    except ValueError as exc:
        raise SecurityValidationError("token is not valid base64url") from exc
    if len(decoded) != OPAQUE_TOKEN_BYTES or _b64url(decoded) != token:
        raise SecurityValidationError("token is not canonical 256-bit base64url")
    return token


def parse_token_hash(value: object) -> str:
    token_hash = _require_str(value, "token_hash")
    if not _SHA256_RE.fullmatch(token_hash):
        raise SecurityValidationError("token_hash must be a lowercase SHA-256 digest")
    return token_hash


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_b64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def generate_opaque_token(
        random_bytes: Callable[[int], bytes] | None = None) -> str:
    """Generate a canonical 256-bit invite, session, or CSRF credential."""
    material = (random_bytes or secrets.token_bytes)(OPAQUE_TOKEN_BYTES)
    if not isinstance(material, bytes) or len(material) != OPAQUE_TOKEN_BYTES:
        raise RuntimeError("secure random source must return exactly 32 bytes")
    return _b64url(material)


def hash_opaque_token(token: object) -> str:
    canonical = parse_opaque_token(token)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ScryptParameters:
    n: int = 1 << 14
    r: int = 8
    p: int = 1
    dklen: int = 32
    salt_bytes: int = 16

    def __post_init__(self) -> None:
        values = (self.n, self.r, self.p, self.dklen, self.salt_bytes)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise SecurityValidationError("scrypt parameters must be integers")
        if self.n < (1 << 14) or self.n > (1 << 17) or self.n & (self.n - 1):
            raise SecurityValidationError("scrypt n must be a supported power of two")
        if self.r != 8 or self.p not in {1, 2}:
            raise SecurityValidationError("unsupported scrypt work parameters")
        if self.dklen != 32 or self.salt_bytes != 16:
            raise SecurityValidationError("unsupported scrypt digest or salt size")


DEFAULT_SCRYPT_PARAMETERS = ScryptParameters()


def hash_password(
        password: object,
        *,
        random_bytes: Callable[[int], bytes] | None = None,
        parameters: ScryptParameters = DEFAULT_SCRYPT_PARAMETERS) -> str:
    """Hash a validated password with a self-describing versioned format."""
    secret = parse_password(password)
    salt = (random_bytes or secrets.token_bytes)(parameters.salt_bytes)
    if not isinstance(salt, bytes) or len(salt) != parameters.salt_bytes:
        raise RuntimeError("secure random source must return exactly 16 salt bytes")
    digest = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=parameters.n,
        r=parameters.r,
        p=parameters.p,
        dklen=parameters.dklen,
    )
    return (
        f"ae-scrypt$v{PASSWORD_HASH_VERSION}$n={parameters.n},r={parameters.r},"
        f"p={parameters.p},l={parameters.dklen}${_b64url(salt)}${_b64url(digest)}"
    )


def _parse_password_hash(encoded: object) -> tuple[ScryptParameters, bytes, bytes]:
    value = _require_str(encoded, "password_hash")
    if len(value) > 256:
        raise SecurityValidationError("password_hash is too long")
    match = _PASSWORD_HASH_RE.fullmatch(value)
    if match is None:
        raise SecurityValidationError("password_hash serialization is invalid")
    n, r, p, dklen = (int(match.group(index)) for index in range(1, 5))
    parameters = ScryptParameters(n=n, r=r, p=p, dklen=dklen, salt_bytes=16)
    try:
        salt = _decode_b64url(match.group(5))
        digest = _decode_b64url(match.group(6))
    except ValueError as exc:
        raise SecurityValidationError("password_hash base64 is invalid") from exc
    if len(salt) != parameters.salt_bytes or len(digest) != parameters.dklen:
        raise SecurityValidationError("password_hash material has invalid length")
    if _b64url(salt) != match.group(5) or _b64url(digest) != match.group(6):
        raise SecurityValidationError("password_hash base64 is not canonical")
    return parameters, salt, digest


def validate_password_hash(encoded: object) -> str:
    value = _require_str(encoded, "password_hash")
    _parse_password_hash(value)
    return value


def verify_password(password: object, encoded: object) -> bool:
    """Verify using constant-time digest comparison; malformed inputs fail closed."""
    try:
        secret = parse_password(password)
        parameters, salt, expected = _parse_password_hash(encoded)
        actual = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=salt,
            n=parameters.n,
            r=parameters.r,
            p=parameters.p,
            dklen=parameters.dklen,
        )
    except (SecurityValidationError, TypeError, ValueError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def build_session_cookie(token: object) -> str:
    """Return the exact hardened R22 session-cookie contract."""
    canonical = parse_opaque_token(token)
    return (
        f"{SESSION_COOKIE_NAME}={canonical}; Path=/; Secure; HttpOnly; SameSite=Lax"
    )


def expire_session_cookie() -> str:
    return (
        f"{SESSION_COOKIE_NAME}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0"
    )


def build_csrf_cookie(token: object) -> str:
    """Return the readable half of the double-submit CSRF binding."""
    canonical = parse_opaque_token(token)
    return f"{CSRF_COOKIE_NAME}={canonical}; Path=/; Secure; SameSite=Lax"


def expire_csrf_cookie() -> str:
    return f"{CSRF_COOKIE_NAME}=; Path=/; Secure; SameSite=Lax; Max-Age=0"


def validate_csrf_binding(
        submitted_token: object,
        cookie_token: object,
        stored_token_hash: object) -> bool:
    """Require header-to-cookie equality and a match to the server-held hash."""
    try:
        submitted = parse_opaque_token(submitted_token)
        cookie = parse_opaque_token(cookie_token)
        expected_hash = parse_token_hash(stored_token_hash)
    except SecurityValidationError:
        return False
    client_bound = hmac.compare_digest(submitted.encode("ascii"), cookie.encode("ascii"))
    server_bound = hmac.compare_digest(hash_opaque_token(submitted), expected_hash)
    return client_bound and server_bound


def _redact_text(value: str) -> str:
    safe = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    safe = _INLINE_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED}", safe
    )
    return safe if len(safe) <= 500 else safe[:497] + "..."


def _secret_key(key: str) -> bool:
    lowered = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(part in lowered for part in _AUTH_SECRET_KEY_PARTS)


def _redact_value(key: str, value: Any, depth: int) -> Any:
    if _secret_key(key):
        return REDACTED
    if depth >= 6:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _redact_value(str(child_key), child_value, depth + 1)
            for child_key, child_value in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple, set)):
        return [_redact_value(key, item, depth + 1) for item in list(value)[:50]]
    if isinstance(value, bytes):
        return REDACTED
    return _redact_text(str(value))


def redact_auth_audit_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded JSON-safe audit details with every auth secret removed."""
    if not isinstance(details, Mapping):
        raise SecurityValidationError("audit details must be a mapping")
    return {
        str(key): _redact_value(str(key), value, 0)
        for key, value in list(details.items())[:50]
    }
