from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hosted.auth import AuthFailure, LoginThrottlePolicy
from hosted.catalog_auth import CatalogAuthService
from hosted.security import hash_opaque_token, hash_password


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery staple"


class Catalog:
    def __init__(self):
        self.tenant_id = uuid4()
        self.tenant_status = "active"
        self.user_id = uuid4()
        self.invitation = None
        self.user = None
        self.membership = None
        self.session = None
        self.calls = []
        self.failures = []

    def get_tenant(self, tenant_id):
        if tenant_id != self.tenant_id:
            return None
        return SimpleNamespace(id=self.tenant_id, status=self.tenant_status)

    def create_invitation(self, tenant_id, **kwargs):
        self.calls.append(("create_invitation", tenant_id, kwargs))
        self.invitation = SimpleNamespace(
            id=uuid4(), tenant_id=tenant_id, email_normalized=kwargs["email"],
            role=kwargs["role"], token_hash=kwargs["token_hash"],
            invited_by_user_id=kwargs["invited_by_user_id"], expires_at=kwargs["expires_at"],
            accepted_at=None, revoked_at=None, created_at=NOW,
        )
        return self.invitation

    def create_invitation_with_audit(self, tenant_id, **kwargs):
        invitation = self.create_invitation(
            tenant_id,
            email=kwargs["email"],
            role=kwargs["role"],
            token_hash=kwargs["token_hash"],
            invited_by_user_id=kwargs["invited_by_user_id"],
            expires_at=kwargs["expires_at"],
        )
        self.append_auth_audit(
            tenant_id,
            event=kwargs["event"],
            occurred_at=kwargs["occurred_at"],
            actor_user_id=kwargs["invited_by_user_id"],
            details=kwargs["audit_details"],
        )
        return invitation

    def append_auth_audit(self, tenant_id, **kwargs):
        self.calls.append(("audit", tenant_id, kwargs))
        return len(self.calls)

    def lookup_invitation_by_hash(self, token_hash):
        return self.invitation if self.invitation and self.invitation.token_hash == token_hash else None

    def revoke_invitation_by_hash(self, token_hash):
        self.calls.append(("revoke_invitation", token_hash))
        return self.lookup_invitation_by_hash(token_hash) is not None

    def redeem_invitation_with_user(self, token_hash, **kwargs):
        self.calls.append(("redeem", token_hash, kwargs))
        if self.lookup_invitation_by_hash(token_hash) is None:
            return None
        existing_user_id = kwargs.get("expected_existing_user_id")
        if existing_user_id is not None:
            if self.user is None or self.user.id != existing_user_id:
                return None
        else:
            self.user = SimpleNamespace(
                id=self.user_id,
                email_normalized=kwargs["email"],
                display_name=kwargs["display_name"],
                password_hash=kwargs["password_hash"],
                disabled_at=None,
                created_at=kwargs["redeemed_at"],
            )
        self.membership = SimpleNamespace(
            tenant_id=self.tenant_id, user_id=self.user_id, role="observer", status="active"
        )
        return self.user, self.membership

    def get_user_by_email(self, email):
        return self.user if self.user and self.user.email_normalized == email else None

    def get_user_by_id(self, user_id):
        return self.user if self.user and self.user.id == user_id else None

    def get_membership(self, tenant_id, user_id):
        if self.membership and self.membership.tenant_id == tenant_id and self.membership.user_id == user_id:
            return self.membership
        return None

    def reserve_login_attempt(
        self,
        tenant_id,
        account_hash,
        client_account_hash,
        *,
        since,
        occurred_at,
        max_failures,
    ):
        self.calls.append(
            (
                "reserve_login",
                tenant_id,
                account_hash,
                client_account_hash,
                since,
                occurred_at,
            )
        )
        if tenant_id != self.tenant_id or self.tenant_status != "active":
            return SimpleNamespace(
                tenant_active=False,
                account_failures=(),
                client_account_failures=(),
                reserved=False,
            )
        failures = tuple(value for value in self.failures if value > since)
        if len(failures) >= max_failures:
            return SimpleNamespace(
                tenant_active=True,
                account_failures=failures,
                client_account_failures=failures,
                reserved=False,
            )
        self.failures.append(occurred_at)
        failures = (*failures, occurred_at)
        return SimpleNamespace(
            tenant_active=True,
            account_failures=failures,
            client_account_failures=failures,
            reserved=True,
        )

    def record_login_attempt(self, tenant_id, account_hash, **kwargs):
        self.calls.append(("login_attempt", tenant_id, account_hash, kwargs))
        if kwargs["succeeded"]:
            self.failures.clear()
        return len(self.calls)

    def create_session(self, tenant_id, user_id, **kwargs):
        self.calls.append(("create_session", tenant_id, user_id, kwargs))
        self.session = SimpleNamespace(
            id=uuid4(), tenant_id=tenant_id, user_id=user_id,
            token_hash=kwargs["token_hash"], csrf_secret_hash=kwargs["csrf_secret_hash"],
            created_at=NOW, expires_at=kwargs["expires_at"], revoked_at=None,
        )
        return self.session

    def lookup_session_by_hash(self, token_hash):
        return self.session if self.session and self.session.token_hash == token_hash else None

    def revoke_session_by_hash(self, token_hash):
        self.calls.append(("revoke_session", token_hash))
        return self.lookup_session_by_hash(token_hash) is not None

    def revoke_session(self, tenant_id, session_id):
        self.calls.append(("revoke_session_id", tenant_id, session_id))
        return True


def random_source(*values):
    queue = list(values)

    def take(size):
        value = queue.pop(0)
        assert len(value) == size
        return value

    return take


def service(catalog, *token_values):
    return CatalogAuthService(
        catalog,
        token_random_bytes=random_source(*token_values) if token_values else None,
        password_random_bytes=lambda size: b"p" * size,
    )


def test_invite_is_written_once_to_the_tenant_catalog_and_never_audits_token():
    catalog = Catalog()
    auth = service(catalog, b"i" * 32)

    token = auth.issue_invite(
        tenant_id=catalog.tenant_id,
        email="member@example.com",
        role="observer",
        now=NOW,
        created_by_user_id=catalog.user_id,
    )

    writes = [call for call in catalog.calls if call[0] == "create_invitation"]
    assert len(writes) == 1
    assert writes[0][2]["token_hash"] == hash_opaque_token(token)
    audits = [call for call in catalog.calls if call[0] == "audit"]
    assert len(audits) == 1
    assert token not in repr(audits)


def test_registration_uses_one_atomic_catalog_redemption():
    catalog = Catalog()
    auth = service(catalog, b"i" * 32)
    token = auth.issue_invite(
        tenant_id=catalog.tenant_id,
        email="member@example.com",
        role="observer",
        now=NOW,
        created_by_user_id=catalog.user_id,
    )

    user = auth.register_with_invite(
        invite_token=token,
        email="member@example.com",
        display_name="Member",
        password=PASSWORD,
        now=NOW + timedelta(minutes=1),
    )

    assert user.user_id == str(catalog.user_id)
    redemptions = [call for call in catalog.calls if call[0] == "redeem"]
    assert len(redemptions) == 1
    assert redemptions[0][2]["expected_existing_user_id"] is None
    assert catalog.membership.status == "active"


def test_existing_global_account_requires_password_and_pins_redeem_to_user_id():
    catalog = Catalog()
    auth = service(catalog, b"i" * 32)
    token = auth.issue_invite(
        tenant_id=catalog.tenant_id,
        email="member@example.com",
        role="observer",
        now=NOW,
        created_by_user_id=catalog.user_id,
    )
    existing_password_hash = hash_password(
        PASSWORD, random_bytes=lambda size: b"e" * size
    )
    catalog.user = SimpleNamespace(
        id=catalog.user_id,
        email_normalized="member@example.com",
        display_name="Existing Member",
        password_hash=existing_password_hash,
        disabled_at=None,
        created_at=NOW - timedelta(days=1),
    )

    with pytest.raises(AuthFailure, match="invalid_invite"):
        auth.register_with_invite(
            invite_token=token,
            email="member@example.com",
            display_name="Attacker Rename",
            password="definitely wrong password",
            now=NOW + timedelta(minutes=1),
        )
    assert not [call for call in catalog.calls if call[0] == "redeem"]

    user = auth.register_with_invite(
        invite_token=token,
        email="member@example.com",
        display_name="Ignored Rename",
        password=PASSWORD,
        now=NOW + timedelta(minutes=2),
    )

    redemption = [call for call in catalog.calls if call[0] == "redeem"][-1]
    assert redemption[2]["expected_existing_user_id"] == catalog.user_id
    assert user.user_id == str(catalog.user_id)
    assert user.password_hash == existing_password_hash


def test_login_requires_active_membership_before_tenant_bound_session():
    catalog = Catalog()
    catalog.user = SimpleNamespace(
        id=catalog.user_id,
        email_normalized="member@example.com",
        display_name="Member",
        password_hash=hash_password(PASSWORD, random_bytes=lambda size: b"s" * size),
        disabled_at=None,
        created_at=NOW,
    )
    auth = service(catalog, b"s" * 32, b"c" * 32)

    with pytest.raises(AuthFailure, match="invalid_credentials"):
        auth.login(
            tenant_id=catalog.tenant_id,
            email="member@example.com",
            password=PASSWORD,
            client_key="127.0.0.1",
            now=NOW,
        )
    assert not [call for call in catalog.calls if call[0] == "create_session"]

    catalog.membership = SimpleNamespace(
        tenant_id=catalog.tenant_id, user_id=catalog.user_id, role="admin", status="active"
    )
    credentials = auth.login(
        tenant_id=catalog.tenant_id,
        email="member@example.com",
        password=PASSWORD,
        client_key="127.0.0.1",
        now=NOW + timedelta(seconds=1),
    )
    session_write = [call for call in catalog.calls if call[0] == "create_session"][-1]
    assert session_write[1:3] == (catalog.tenant_id, catalog.user_id)
    authenticated = auth.authenticate_session(credentials.session_token, now=NOW + timedelta(seconds=2))
    assert authenticated.user.user_id == str(catalog.user_id)
    assert authenticated.session.tenant_id == catalog.tenant_id


def test_absent_or_suspended_tenant_fails_without_attempt_or_session_write():
    catalog = Catalog()
    catalog.user = SimpleNamespace(
        id=catalog.user_id,
        email_normalized="member@example.com",
        display_name="Member",
        password_hash=hash_password(PASSWORD, random_bytes=lambda size: b"s" * size),
        disabled_at=None,
        created_at=NOW,
    )
    catalog.membership = SimpleNamespace(
        tenant_id=catalog.tenant_id, user_id=catalog.user_id, role="admin", status="active"
    )
    auth = service(catalog)

    for tenant_id in (uuid4(), catalog.tenant_id):
        if tenant_id == catalog.tenant_id:
            catalog.tenant_status = "suspended"
        with pytest.raises(AuthFailure, match="invalid_credentials"):
            auth.login(
                tenant_id=tenant_id,
                email="member@example.com",
                password=PASSWORD,
                client_key="127.0.0.1",
                now=NOW,
            )

    assert not [call for call in catalog.calls if call[0] == "login_attempt"]
    assert not [call for call in catalog.calls if call[0] == "create_session"]


def test_account_throttle_survives_client_rotation_and_reserves_before_verify():
    catalog = Catalog()
    catalog.user = SimpleNamespace(
        id=catalog.user_id,
        email_normalized="member@example.com",
        display_name="Member",
        password_hash=hash_password(PASSWORD, random_bytes=lambda size: b"s" * size),
        disabled_at=None,
        created_at=NOW,
    )
    catalog.membership = SimpleNamespace(
        tenant_id=catalog.tenant_id,
        user_id=catalog.user_id,
        role="admin",
        status="active",
    )
    auth = CatalogAuthService(
        catalog,
        throttle_policy=LoginThrottlePolicy(
            max_failures=3, window=timedelta(minutes=15)
        ),
        password_random_bytes=lambda size: b"p" * size,
    )

    for offset, client in enumerate(("192.0.2.10", "192.0.2.11")):
        with pytest.raises(AuthFailure) as rejected:
            auth.login(
                tenant_id=catalog.tenant_id,
                email="member@example.com",
                password="definitely wrong password",
                client_key=client,
                now=NOW + timedelta(seconds=offset),
            )
        assert rejected.value.code == "invalid_credentials"

    with pytest.raises(AuthFailure) as threshold:
        auth.login(
            tenant_id=catalog.tenant_id,
            email="member@example.com",
            password="definitely wrong password",
            client_key="192.0.2.12",
            now=NOW + timedelta(seconds=2),
        )
    assert threshold.value.code == "login_throttled"
    assert threshold.value.retry_after_seconds > 0

    reservations = [call for call in catalog.calls if call[0] == "reserve_login"]
    assert len(reservations) == 3
    assert len({call[2] for call in reservations}) == 1
    assert len({call[3] for call in reservations}) == 3
    assert not [call for call in catalog.calls if call[0] == "login_attempt"]


def test_csrf_binding_and_logout_use_only_persisted_hashes():
    catalog = Catalog()
    catalog.user = SimpleNamespace(
        id=catalog.user_id,
        email_normalized="member@example.com",
        display_name="Member",
        password_hash=hash_password(PASSWORD, random_bytes=lambda size: b"s" * size),
        disabled_at=None,
        created_at=NOW,
    )
    catalog.membership = SimpleNamespace(
        tenant_id=catalog.tenant_id, user_id=catalog.user_id, role="admin", status="active"
    )
    auth = service(catalog, b"s" * 32, b"c" * 32)
    credentials = auth.login(
        tenant_id=catalog.tenant_id,
        email="member@example.com",
        password=PASSWORD,
        client_key="127.0.0.1",
        now=NOW,
    )

    auth.authenticate_csrf(
        session_token=credentials.session_token,
        submitted_csrf_token=credentials.csrf_token,
        csrf_cookie_token=credentials.csrf_token,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(AuthFailure, match="invalid_csrf"):
        auth.authenticate_csrf(
            session_token=credentials.session_token,
            submitted_csrf_token=credentials.session_token,
            csrf_cookie_token=credentials.session_token,
            now=NOW + timedelta(seconds=1),
        )
    assert auth.revoke_session(credentials.session_token, now=NOW + timedelta(seconds=2)) is True
    stored = [call for call in catalog.calls if call[0] == "create_session"][-1][3]
    assert credentials.session_token not in repr(stored)
    assert credentials.csrf_token not in repr(stored)
