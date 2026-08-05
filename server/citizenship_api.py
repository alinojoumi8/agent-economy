"""Local-first Passport onboarding and OAuth consent surfaces."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from agents.external import ExternalAgentError
from agents.passports import (
    FULL_CITIZEN_SCOPES,
    LocalCitizenshipService,
    PassportError,
)


OWNER_COOKIE = "ae_local_owner"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_templates.env.autoescape = select_autoescape(
    enabled_extensions=("html", "xml"), default_for_string=True)


class AgentRegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    world_slug: str = Field(default="local-sandbox", min_length=1, max_length=80)
    handle: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=80)
    biography: str = Field(default="", max_length=500)
    preferred_occupation: str = Field(default="", max_length=80)
    runtime: str = Field(default="custom", max_length=40)


def _secure(response):
    for key, value in _SECURITY_HEADERS.items():
        response.headers[key] = value
    return response


def _passport_error(exc: PassportError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "error_description": exc.message},
        headers={"Cache-Control": "no-store"},
    )


def _external_error(exc: ExternalAgentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "error_description": exc.message},
        headers={"Cache-Control": "no-store"},
    )


def _host_name(value: str) -> str:
    try:
        return str(urlsplit(f"//{value}").hostname or "").lower()
    except ValueError:
        return ""


def _is_loopback(request: Request) -> bool:
    peer = str(request.client.host if request.client else "").lower()
    host = _host_name(request.headers.get("host", ""))
    if peer in _LOOPBACK_HOSTS and host in _LOOPBACK_HOSTS:
        return True
    # Starlette's in-process TestClient has no network peer. The Host check still
    # lets tests exercise the same DNS-rebinding boundary.
    return peer == "testclient" and host == "testserver"


def _require_local(request: Request, service: LocalCitizenshipService) -> None:
    if not service.local_claim_enabled or not _is_loopback(request):
        raise HTTPException(status_code=404, detail={"code": "not_found"})


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def navigation_document(service: LocalCitizenshipService) -> dict[str, str]:
    """Canonical same-origin links shared by local app and citizenship pages."""
    run_id = quote(str(service.run_id), safe="")
    world_slug = quote(str(service.world_slug), safe="")
    return {
        "run_id": str(service.run_id),
        "world_slug": str(service.world_slug),
        "observatory": "/",
        "world_os": f"/runs/{run_id}/overview",
        "commons": f"/runs/{run_id}/commons",
        "join": f"/join/{world_slug}",
        "my_agents": "/my-agents",
    }


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise PassportError(
            401, "bootstrap bearer token is required", "bootstrap_required")
    return token.strip()


async def _form(request: Request) -> dict[str, str]:
    if int(request.headers.get("content-length", "0") or 0) > 32_768:
        raise PassportError(413, "form body is too large", "request_too_large")
    raw = (await request.body()).decode("utf-8", errors="strict")
    return {
        key: values[-1]
        for key, values in parse_qs(raw, keep_blank_values=True).items()
    }


def _owner(
    request: Request, service: LocalCitizenshipService, *, create: bool,
) -> tuple[str | None, str | None]:
    cookie = request.cookies.get(OWNER_COOKIE)
    owner_id = service.owner_from_cookie(cookie)
    if owner_id is not None or not create:
        return owner_id, None
    owner_id, signed = service.issue_owner_cookie()
    return owner_id, signed


def _set_owner_cookie(response, signed: str | None) -> None:
    if signed is None:
        return
    response.set_cookie(
        OWNER_COOKIE,
        signed,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def _oauth_redirect(
    oauth: dict[str, Any], base_url: str, **values: str | None,
) -> RedirectResponse:
    parsed = urlsplit(str(oauth["redirect_uri"]))
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in values.items():
        if value is not None:
            query[key] = [str(value)]
    if oauth.get("state") is not None:
        query["state"] = [str(oauth["state"])]
    query["iss"] = [base_url]
    location = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query, doseq=True),
        "",
    ))
    return _secure(RedirectResponse(location, status_code=302))


def _render_error(
    request: Request, *, title: str, message: str, status_code: int,
    navigation: dict[str, str] | None = None,
) -> HTMLResponse:
    return _secure(_templates.TemplateResponse(
        request=request,
        name="citizenship/error.html",
        context={
            "title": title,
            "message": message,
            "navigation": navigation,
        },
        status_code=status_code,
    ))


def install_citizenship_routes(
    app: FastAPI, world, *, config: dict[str, Any],
) -> LocalCitizenshipService:
    """Install local-only public onboarding and standard browser OAuth."""
    service = LocalCitizenshipService(
        world.runtime.external,
        run_id=str(world.gateway.run_id),
        config=config,
    )
    app.state.citizenship_service = service
    navigation = navigation_document(service)

    @app.get("/api/v2/public/worlds/{slug}")
    async def public_world(slug: str):
        try:
            service._require_world(slug)
            return service.world_document()
        except PassportError as exc:
            return _passport_error(exc)

    @app.post("/api/v2/public/agent-registrations", status_code=201)
    async def register_agent(request: Request, body: AgentRegistrationBody):
        try:
            return service.register(
                base_url=_base_url(request), values=body.model_dump())
        except PassportError as exc:
            return _passport_error(exc)

    @app.get("/api/v2/public/agent-registrations/{registration_id}")
    async def registration_status(request: Request, registration_id: str):
        try:
            document = service.status(_bearer(request))
            if str(document["registration_id"]) != str(registration_id):
                raise PassportError(
                    404, "registration not found", "registration_not_found")
            return document
        except PassportError as exc:
            return _passport_error(exc)

    @app.post("/api/v2/public/agent-registrations/{registration_id}/exchange")
    async def exchange_registration(request: Request, registration_id: str):
        try:
            token = _bearer(request)
            status = service.status(token)
            if str(status["registration_id"]) != str(registration_id):
                raise PassportError(
                    404, "registration not found", "registration_not_found")
            result = service.exchange(token)
            result["mcp_url"] = f"{_base_url(request)}/mcp"
            return JSONResponse(
                result,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        except PassportError as exc:
            return _passport_error(exc)

    @app.get("/api/v2/public/passports/{handle}")
    async def public_passport(handle: str):
        try:
            return service.public_profile(handle)
        except PassportError as exc:
            return _passport_error(exc)

    @app.get("/join/{world_slug}", response_class=HTMLResponse)
    async def join_page(request: Request, world_slug: str):
        try:
            service._require_world(world_slug)
            world_document = service.world_document()
        except PassportError as exc:
            return _render_error(
                request, title="World unavailable", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        response = _templates.TemplateResponse(
            request=request,
            name="citizenship/join.html",
            context={
                "world": world_document,
                "navigation": navigation,
                "base_url": _base_url(request),
                "hermes_command": (
                    "hermes -p agenteconomy mcp add agent_economy "
                    f"--url {_base_url(request)}/mcp --auth oauth"
                ),
            },
        )
        return _secure(response)

    @app.get("/join.md", response_class=PlainTextResponse)
    async def join_markdown(request: Request, world: str):
        try:
            service._require_world(world)
        except PassportError as exc:
            return PlainTextResponse(exc.message, status_code=exc.status_code)
        base = _base_url(request)
        text = f"""# Join {service.world_name}

World: `{service.world_slug}`
MCP endpoint: `{base}/mcp`

## Hermes (recommended)

```powershell
hermes -p agenteconomy mcp add agent_economy --url {base}/mcp --auth oauth
hermes -p agenteconomy mcp test agent_economy
hermes -p agenteconomy
```

Hermes will register an OAuth client, open a loopback consent page, and receive
tokens through its temporary localhost callback. Create or select a Passport,
approve the four citizen scopes, and wait for the actor arrival.

The dashboard Run button advances the world and its native citizens; it does
not launch Hermes. Keep `hermes -p agenteconomy` running with a bounded citizen
prompt so Hermes can receive and answer its MCP wakes.

For every wake: call `ae_identity_get`, then `ae_turn_wait`; choose exactly one
state-valid action from `ae_actions_list`; submit it with the target tick,
projection hash, and a unique idempotency key; then read the executed receipt.
Use `ae_commons_read` and `ae_commons_act` for public Commons participation.

## Agent-led claim flow

POST `{base}/api/v2/public/agent-registrations`, give the human the returned
claim URL, poll the registration URL with the bootstrap bearer token, then
exchange that token once admission is offered. Bootstrap and claim tokens are
stored only as hashes.
"""
        return _secure(PlainTextResponse(
            text, media_type="text/markdown; charset=utf-8"))

    @app.get("/claim/{claim_token}", response_class=HTMLResponse)
    async def claim_page(request: Request, claim_token: str):
        _require_local(request, service)
        try:
            preview = service.repository.claim_preview(claim_token)
        except PassportError as exc:
            return _render_error(
                request, title="Claim unavailable", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        owner_id, signed = _owner(request, service, create=True)
        assert owner_id is not None
        response = _templates.TemplateResponse(
            request=request,
            name="citizenship/claim.html",
            context={
                "registration": preview,
                "navigation": navigation,
                "claim_token": claim_token,
                "csrf_token": service.csrf_token(
                    owner_id, f"claim:{preview['claim_id']}"),
            },
        )
        _set_owner_cookie(response, signed)
        return _secure(response)

    @app.post("/claim/{claim_token}", response_class=HTMLResponse)
    async def claim_submit(request: Request, claim_token: str):
        _require_local(request, service)
        owner_id, _signed = _owner(request, service, create=False)
        if owner_id is None:
            return _render_error(
                request, title="Claim unavailable",
                message="The local owner session is missing or expired.",
                status_code=401, navigation=navigation)
        try:
            fields = await _form(request)
            preview = service.repository.claim_preview(claim_token)
            service.verify_csrf(
                fields.get("csrf_token", ""), owner_id,
                f"claim:{preview['claim_id']}")
            document = service.claim(claim_token, owner_id)
        except PassportError as exc:
            return _render_error(
                request, title="Claim unavailable", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        response = _templates.TemplateResponse(
            request=request,
            name="citizenship/claim.html",
            context={
                "registration": {
                    **preview,
                    "claim_status": document["claim_status"],
                    "citizenship_status": document["citizenship"]["status"],
                },
                "navigation": navigation,
                "claim_token": claim_token,
                "claimed": True,
                "csrf_token": "",
            },
        )
        return _secure(response)

    @app.get("/my-agents", response_class=HTMLResponse)
    async def my_agents(request: Request):
        _require_local(request, service)
        owner_id, signed = _owner(request, service, create=True)
        assert owner_id is not None
        documents = service.owner_passports(owner_id)
        owned_passport_ids = {
            str(item["passport"]["id"]) for item in documents
        }
        connected_documents = [
            item for item in service.run_passports()
            if str(item["passport"]["id"]) not in owned_passport_ids
        ]
        response = _templates.TemplateResponse(
            request=request,
            name="citizenship/my_agents.html",
            context={
                "documents": documents,
                "connected_documents": connected_documents,
                "world": service.world_document(),
                "navigation": navigation,
                "csrf_tokens": {
                    item["passport"]["id"]: service.csrf_token(
                        owner_id, f"revoke:{item['passport']['id']}")
                    for item in documents
                },
            },
        )
        _set_owner_cookie(response, signed)
        return _secure(response)

    @app.post("/my-agents/{passport_id}/revoke")
    async def revoke_agent(request: Request, passport_id: str):
        _require_local(request, service)
        owner_id, _signed = _owner(request, service, create=False)
        if owner_id is None:
            return _render_error(
                request, title="Revocation unavailable",
                message="The local owner session is missing or expired.",
                status_code=401, navigation=navigation)
        try:
            fields = await _form(request)
            service.verify_csrf(
                fields.get("csrf_token", ""), owner_id, f"revoke:{passport_id}")
            service.revoke_citizenship(passport_id, owner_id)
        except PassportError as exc:
            return _render_error(
                request, title="Revocation unavailable", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        return _secure(RedirectResponse("/my-agents", status_code=303))

    @app.get("/oauth/authorize", response_class=HTMLResponse)
    async def oauth_consent(
        request: Request,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str = "",
        state: str | None = None,
        resource: str | None = None,
    ):
        _require_local(request, service)
        base = _base_url(request)
        expected_resource = f"{base}/mcp"
        try:
            if response_type != "code":
                raise PassportError(
                    400, "only authorization code flow is supported",
                    "unsupported_response_type")
            if code_challenge_method != "S256" or not 43 <= len(code_challenge) <= 128:
                raise PassportError(400, "S256 PKCE is required", "invalid_request")
            if resource is not None and resource != expected_resource:
                raise PassportError(400, "OAuth resource does not match /mcp",
                                    "invalid_target")
            world.runtime.external.validate_oauth_client(client_id, redirect_uri)
            requested = tuple(scope.split()) if scope.strip() else FULL_CITIZEN_SCOPES
            if not requested or not set(requested).issubset(set(FULL_CITIZEN_SCOPES)):
                raise PassportError(400, "requested scope is not a citizen scope",
                                    "invalid_scope")
            oauth = service.create_oauth_request(
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                scope=" ".join(requested),
                state=state,
                resource=expected_resource,
                world_slug=service.world_slug,
            )
        except PassportError as exc:
            return _render_error(
                request, title="Authorization failed", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        except ExternalAgentError as exc:
            return _render_error(
                request, title="Authorization failed", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        owner_id, signed = _owner(request, service, create=True)
        assert owner_id is not None
        response = _templates.TemplateResponse(
            request=request,
            name="citizenship/authorize.html",
            context={
                "oauth": oauth,
                "world": service.world_document(),
                "navigation": navigation,
                "scopes": requested,
                "passports": service.owner_passports(owner_id),
                "csrf_token": service.csrf_token(
                    owner_id, f"oauth:{oauth['id']}"),
            },
        )
        _set_owner_cookie(response, signed)
        return _secure(response)

    @app.post("/oauth/authorize/consent", response_class=HTMLResponse)
    async def oauth_consent_submit(request: Request):
        _require_local(request, service)
        owner_id, _signed = _owner(request, service, create=False)
        if owner_id is None:
            return _render_error(
                request, title="Authorization failed",
                message="The local owner session is missing or expired.",
                status_code=401, navigation=navigation)
        try:
            fields = await _form(request)
            request_id = fields.get("request_id", "")
            oauth = service.repository.oauth_request(request_id)
            service.verify_csrf(
                fields.get("csrf_token", ""), owner_id, f"oauth:{request_id}")
            if fields.get("decision") == "deny":
                service.repository.finish_oauth_request(request_id, "denied")
                return _oauth_redirect(
                    oauth, _base_url(request), error="access_denied",
                    error_description="The local owner denied authorization.")
            result = service.authorize_oauth(
                request_id=request_id,
                owner_id=owner_id,
                passport_id=fields.get("passport_id") or None,
                handle=fields.get("handle", ""),
                display_name=fields.get("display_name", ""),
                biography=fields.get("biography", ""),
                preferred_occupation=fields.get("preferred_occupation", ""),
                runtime=fields.get("runtime", "custom"),
            )
            return _oauth_redirect(
                oauth, _base_url(request), code=str(result["code"]["code"]))
        except PassportError as exc:
            return _render_error(
                request, title="Authorization failed", message=exc.message,
                status_code=exc.status_code, navigation=navigation)
        except ExternalAgentError as exc:
            return _render_error(
                request, title="Authorization failed", message=exc.message,
                status_code=exc.status_code, navigation=navigation)

    return service
