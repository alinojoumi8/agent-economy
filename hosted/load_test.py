"""Bounded, credential-redacted load and tenant-isolation probe for R22.

Passwords are read from named environment variables.  Results never contain
credentials, cookies, e-mail addresses, response bodies, or provider data.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Sequence
from urllib.parse import urlparse
from uuid import UUID

import httpx


MAX_LOAD_USERS = 32
MAX_TOTAL_REQUESTS = 10_000
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 120.0
_GIT_OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True)
class LoadUser:
    tenant_id: UUID
    email: str
    password_env: str
    run_id: UUID | None = None


@dataclass(frozen=True)
class ProbeResult:
    operation: str
    expected_status: int
    actual_status: int
    latency_ms: float
    valid_body: bool

    @property
    def passed(self) -> bool:
        return self.actual_status == self.expected_status and self.valid_body


def _parse_user(value: str) -> LoadUser:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) not in {3, 4}:
        raise argparse.ArgumentTypeError(
            "user must be TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]"
        )
    try:
        tenant_id = UUID(parts[0])
        run_id = UUID(parts[3]) if len(parts) == 4 and parts[3] else None
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tenant and run identifiers must be UUIDs") from exc
    email = parts[1]
    password_env = parts[2]
    if not email or "@" not in email or len(email) > 320:
        raise argparse.ArgumentTypeError("user e-mail is invalid")
    if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", password_env) is None:
        raise argparse.ArgumentTypeError("password environment name is invalid")
    return LoadUser(tenant_id, email, password_env, run_id)


def _allow_insecure(base_url: str, requested: bool) -> bool:
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError("hosted load probes require HTTPS")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an HTTPS origin without credentials or a path")
    if not requested:
        return False
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("TLS verification may be disabled only for loopback hosts")
    return True


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _body_is_valid(
    operation: str,
    response: httpx.Response,
    *,
    own_tenant: UUID,
    own_run: UUID | None,
) -> bool:
    if response.status_code == 404 and operation.startswith("cross_"):
        return True
    if response.status_code != 200:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if operation == "own_session":
        return body.get("tenant_id") == str(own_tenant)
    if operation == "own_runs":
        runs = body.get("runs")
        return isinstance(runs, list) and all(
            isinstance(run, dict) and run.get("tenant_id") == str(own_tenant)
            for run in runs
        )
    if operation == "own_run":
        return (
            own_run is not None
            and body.get("tenant_id") == str(own_tenant)
            and body.get("run_id") == str(own_run)
        )
    return True


async def run_load_test(
    *,
    base_url: str,
    users: Sequence[LoadUser],
    requests_per_user: int = 40,
    concurrency: int = 16,
    allow_insecure_loopback: bool = False,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
    build_ref: str | None = None,
) -> dict[str, Any]:
    """Run authenticated own-scope reads and cross-tenant denial probes."""

    if len(users) < 2:
        raise ValueError("at least two tenant users are required")
    if len(users) > MAX_LOAD_USERS:
        raise ValueError(f"load users cannot exceed {MAX_LOAD_USERS}")
    if not 1 <= requests_per_user <= MAX_TOTAL_REQUESTS:
        raise ValueError(f"requests_per_user must be between 1 and {MAX_TOTAL_REQUESTS}")
    if len(users) * requests_per_user > MAX_TOTAL_REQUESTS:
        raise ValueError(f"total scheduled requests cannot exceed {MAX_TOTAL_REQUESTS}")
    if not 1 <= concurrency <= 256:
        raise ValueError("concurrency must be between 1 and 256")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not MIN_TIMEOUT_SECONDS <= float(timeout_seconds) <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(
            f"timeout_seconds must be finite and between {MIN_TIMEOUT_SECONDS:g} "
            f"and {MAX_TIMEOUT_SECONDS:g}"
        )
    if build_ref is not None and (
        not isinstance(build_ref, str) or _GIT_OBJECT_ID_RE.fullmatch(build_ref) is None
    ):
        raise ValueError(
            "build_ref must be a full lowercase 40- or 64-character Git object ID"
        )
    tenant_ids = [user.tenant_id for user in users]
    if len(set(tenant_ids)) != len(tenant_ids):
        raise ValueError("load users must belong to distinct tenants")
    minimum_requests = max(
        3
        + (1 if user.run_id is not None else 0)
        + (1 if users[(index + 1) % len(users)].run_id is not None else 0)
        for index, user in enumerate(users)
    )
    if requests_per_user < minimum_requests:
        raise ValueError(
            "requests_per_user must cover every own-scope and cross-tenant probe "
            f"at least once (minimum {minimum_requests} for this user set)"
        )
    insecure = _allow_insecure(base_url, allow_insecure_loopback)
    verify: bool = not insecure
    clients: list[httpx.AsyncClient] = []
    results: list[ProbeResult] = []
    started = time.perf_counter()
    try:
        for user in users:
            password = os.environ.get(user.password_env)
            if password is None:
                raise ValueError(f"required password environment variable is unset: {user.password_env}")
            client = httpx.AsyncClient(
                base_url=base_url,
                verify=verify,
                timeout=httpx.Timeout(float(timeout_seconds)),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            )
            clients.append(client)
            response = await client.post(
                "/auth/login",
                json={
                    "tenant_id": str(user.tenant_id),
                    "email": user.email,
                    "password": password,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"load user {len(clients)} login failed with status {response.status_code}"
                )
            payload = response.json()
            if payload.get("tenant_id") != str(user.tenant_id):
                raise RuntimeError("login returned the wrong tenant scope")

        semaphore = asyncio.Semaphore(concurrency)

        async def probe(
            client: httpx.AsyncClient,
            user: LoadUser,
            operation: str,
            path: str,
            expected_status: int,
        ) -> None:
            async with semaphore:
                probe_started = time.perf_counter()
                try:
                    response = await client.get(path)
                    latency_ms = (time.perf_counter() - probe_started) * 1000
                    valid = _body_is_valid(
                        operation,
                        response,
                        own_tenant=user.tenant_id,
                        own_run=user.run_id,
                    )
                    results.append(
                        ProbeResult(
                            operation,
                            expected_status,
                            response.status_code,
                            round(latency_ms, 3),
                            valid,
                        )
                    )
                except httpx.HTTPError:
                    latency_ms = (time.perf_counter() - probe_started) * 1000
                    results.append(
                        ProbeResult(operation, expected_status, 0, round(latency_ms, 3), False)
                    )

        scheduled: list[asyncio.Task[None]] = []
        for index, (client, user) in enumerate(zip(clients, users, strict=True)):
            foreign = users[(index + 1) % len(users)]
            operations = [
                (
                    "own_session",
                    f"/api/v2/tenants/{user.tenant_id}/session",
                    200,
                ),
                ("own_runs", f"/api/v2/tenants/{user.tenant_id}/runs", 200),
                (
                    "cross_session",
                    f"/api/v2/tenants/{foreign.tenant_id}/session",
                    404,
                ),
            ]
            if user.run_id is not None:
                operations.append(
                    (
                        "own_run",
                        f"/api/v2/tenants/{user.tenant_id}/runs/{user.run_id}",
                        200,
                    )
                )
            if foreign.run_id is not None:
                operations.append(
                    (
                        "cross_run",
                        f"/api/v2/tenants/{foreign.tenant_id}/runs/{foreign.run_id}",
                        404,
                    )
                )
            for request_index in range(requests_per_user):
                operation, path, expected = operations[request_index % len(operations)]
                scheduled.append(
                    asyncio.create_task(probe(client, user, operation, path, expected))
                )
        await asyncio.gather(*scheduled)
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))

    elapsed_seconds = round(time.perf_counter() - started, 3)
    latencies = [result.latency_ms for result in results]
    failures = [result for result in results if not result.passed]
    operation_counts: dict[str, int] = {}
    for result in results:
        operation_counts[result.operation] = operation_counts.get(result.operation, 0) + 1
    cross_tenant_denials = sum(
        1
        for result in results
        if result.operation.startswith("cross_") and result.passed
    )
    complete_isolation_probe = cross_tenant_denials >= len(users)
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "build_ref": build_ref,
        "base_origin": f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}",
        "users": len(users),
        "tenants": len(set(tenant_ids)),
        "configured_concurrency": concurrency,
        "requests_per_user": requests_per_user,
        "requests": len(results),
        "passed_requests": len(results) - len(failures),
        "failed_requests": len(failures),
        "cross_tenant_denials": cross_tenant_denials,
        "complete_isolation_probe": complete_isolation_probe,
        "operation_counts": dict(sorted(operation_counts.items())),
        "elapsed_seconds": elapsed_seconds,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies, default=0.0), 3),
        },
        "status": (
            "passed" if not failures and results and complete_isolation_probe else "failed"
        ),
        "failures": [asdict(result) for result in failures[:20]],
    }


def _write_result(path: Path, result: dict[str, Any]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hosted.load_test")
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--user",
        action="append",
        type=_parse_user,
        required=True,
        help="TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]; repeat for each tenant",
    )
    parser.add_argument("--requests-per-user", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--allow-insecure-loopback", action="store_true")
    parser.add_argument("--build-ref")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = asyncio.run(
        run_load_test(
            base_url=args.base_url,
            users=args.user,
            requests_per_user=args.requests_per_user,
            concurrency=args.concurrency,
            allow_insecure_loopback=args.allow_insecure_loopback,
            timeout_seconds=args.timeout_seconds,
            build_ref=args.build_ref,
        )
    )
    if args.output is not None:
        _write_result(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
