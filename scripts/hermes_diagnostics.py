"""Explicit local diagnostics. Never use to bypass a host execution-policy denial."""
from __future__ import annotations

import sys
# CHECK must not leave import caches behind when invoked as a script.
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager, ExitStack, redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psutil
import yaml

if __package__ in {None, ""}:
    from hermes_citizens import CohortOperator, ROOT, cohort_lock, read_json
    sys.path.insert(0, str(ROOT))
else:
    from .hermes_citizens import CohortOperator, ROOT, cohort_lock, read_json


class DiagnosticError(RuntimeError):
    """A safe, machine-readable precondition failure (no private error text)."""


from engine.inspection import inspection_snapshot as readonly_database


def lock_state(path):
    """Probe an existing lock with a read-only handle; never create a lock file."""
    try:
        with path.open("rb") as stream:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBRLCK, 1)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(stream, fcntl.LOCK_UN)
        return "available"
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        return "held" if exc.errno in {11, 13, 35, 36} else "unknown"


def controller_processes(run_id):
    """Process matches are observations, not proof of exclusive ownership."""
    matches, inaccessible = [], 0
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            info = process.info
            command = info["cmdline"] or []
            if (info["name"] or "").lower().startswith("python") and any(
                    Path(arg).name == "hermes_citizens.py" for arg in command):
                if any(arg == "--run-id=" + run_id for arg in command) or any(
                        command[i:i+2] == ["--run-id", run_id] for i in range(len(command))):
                    matches.append({"pid": info["pid"], "created_at": info["create_time"],
                                    "supervisor": "--supervise" in command})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            inaccessible += 1
    return {"appears_active": bool(matches), "matches": matches, "inaccessible": inaccessible}


def budget_state(path):
    """Read accounting directly: ProviderBudget.snapshot opens a write transaction."""
    if not path or not Path(path).is_file():
        return {"state": "unavailable", "reason": "no_existing_ledger"}
    with readonly_database(path) as db:
        contract = json.loads(db.execute("SELECT json FROM budget_contract WHERE singleton=1").fetchone()[0])
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sealed = bool(db.execute("SELECT sealed FROM budget_status WHERE singleton=1").fetchone()[0]) if "budget_status" in tables else None
        totals = [dict(r) for r in db.execute(
            "SELECT state,COUNT(*) calls,SUM(reserved_input+reserved_output) reserved_tokens,"
            "SUM(reserved_cost) reserved_nano_usd,SUM(input_tokens+output_tokens) used_tokens,"
            "SUM(usage_cost) used_nano_usd FROM reservations GROUP BY state ORDER BY state")]
        return {"state": "observed", "sealed": sealed, "totals": totals,
                "limits": {k: contract[k] for k in ("max_provider_calls", "max_tokens", "max_spend_nano_usd")},
                "contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()}


def inspect_budget(path):
    try:
        return budget_state(path)
    except (OSError, sqlite3.Error, DiagnosticError, ValueError, TypeError) as exc:
        return {"state": "unavailable", "reason": str(exc) if isinstance(exc, DiagnosticError)
                else "unreadable_ledger", "error_type": type(exc).__name__}


class DiagnosticOperator(CohortOperator):
    """No constructor writes; expose only explicit single-operation entry points."""

    def __init__(self, args):
        super().__init__(args, world_root=args.world_root, create_directory=False)
        self.selected = None
        self.target_tick = None

    def api(self, path, *, body=None, token=None):
        # Deliberately no transport retry (including GET), admission or clock API.
        allowed = {("GET", "/api/run/diagnostics"), ("GET", "/api/v2/agent/me"),
                   ("POST", "/api/v2/agent/turn/renew")}
        method = "GET" if body is None else "POST"
        if (method, path) not in allowed:
            raise DiagnosticError("diagnostic_api_forbidden")
        if path == "/api/v2/agent/turn/renew":
            self.require_boundary(self.target_tick - 1)
            if body != {"target_tick": self.target_tick}:
                raise DiagnosticError("stale_expected_tick")
        response = self.client.request(method, path, json=body,
            headers={"Authorization": f"Bearer {token}"} if token else {})
        response.raise_for_status()
        value = response.json()
        if path == "/api/v2/agent/me":
            self.validate_identity(value)
        return value

    def validate_identity(self, identity):
        citizen = self.selected
        if (identity.get("run_id") != self.args.run_id or not citizen
                or identity.get("connection_id") != citizen["connection_id"]):
            raise DiagnosticError("identity_mismatch")
        if identity.get("status") == "pending_actor" or not identity.get("actor"):
            raise DiagnosticError("admission_required")
        if (identity.get("status") != "active" or identity["actor"].get("id") != citizen["actor_id"]
                or not identity["actor"].get("alive") or identity.get("tier") != "actor"):
            raise DiagnosticError("identity_not_active")

    def manifest(self):
        manifest = read_json(self.manifest_path)
        if manifest.get("run_id") != self.args.run_id:
            raise DiagnosticError("manifest_identity_mismatch")
        citizens = manifest["citizens"]
        for key in ("profile", "connection_id", "home"):
            if len({c[key] for c in citizens}) != len(citizens):
                raise DiagnosticError("duplicate_profile_identity")
        return citizens

    def local_state(self):
        citizens = self.manifest()
        with readonly_database(self.database) as db:
            meta = dict(db.execute("SELECT * FROM run_meta").fetchone())
            if meta["run_id"] != self.args.run_id:
                raise DiagnosticError("wrong_run_id")
            connections = {r["id"]: dict(r) for r in db.execute(
                "SELECT id,status,actor_id,tier FROM external_agent_connections")}
            profiles = [{"profile": c["profile"], "connection_id": c["connection_id"],
                "profile_exists": Path(c["home"]).is_dir(),
                "admission": connections.get(c["connection_id"], {"status": "missing"})} for c in citizens]
            return {"run_id": meta["run_id"], "tick": meta["tick"], "active_tick": meta["active_tick"],
                "saved_status": meta["status"], "identity": {"run_id": meta["run_id"], "seed": meta["seed"],
                    "config_sha256": hashlib.sha256(meta["config_json"].encode()).hexdigest()},
                "profile_count": len(profiles), "profiles": profiles,
                "queued_actions": [dict(r) for r in db.execute(
                    "SELECT id,connection_id,actor_id,target_tick,status FROM external_action_submissions "
                    "WHERE status='queued' ORDER BY target_tick,id")],
                "saved_decisions": len(json.loads(meta["phase_state_json"] or "{}").get("decisions", [])),
                "recorded_decisions_after_completed_tick": db.execute(
                    "SELECT COUNT(*) FROM agent_decisions WHERE tick>?", (meta["tick"],)).fetchone()[0],
                "run_budget": json.loads(meta["config_json"]).get("budget", {}),
                "saved_governor": json.loads(meta["governor_json"] or "{}")}

    def validate_server(self, state):
        if state.get("run_id") != self.args.run_id:
            raise DiagnosticError("wrong_run_id")
        if Path(state["database"]).resolve() != self.database.resolve():
            raise DiagnosticError("database_identity_mismatch")

    def check(self):
        local = self.local_state()
        try:
            server = self.api("/api/run/diagnostics")
            self.validate_server(server)
        except (httpx.HTTPError, ValueError) as exc:
            server = {"state": "unavailable", "error_type": type(exc).__name__}
        return {"operation": "check", "expected_run_id": self.args.run_id, "local": local,
                "server": server, "snapshot_consistent": server.get("tick") == local["tick"]
                    and server.get("active_tick") == local["active_tick"],
                "locks": {name: lock_state(self.root / name) for name in ("operator.lock", "supervisor.lock")},
                "controller": controller_processes(self.args.run_id),
                "provider_budget": inspect_budget(self.args.budget_db),
                "typed_run_budget": inspect_budget(self.database.with_suffix(".jev-budget.db")),
                "hermes_budget": "Hermes provider/auth accounting remains external; oneshot is not one billed call"}

    def require_boundary(self, expected_tick):
        state = self.api("/api/run/diagnostics")
        self.validate_server(state)
        if state.get("tick") != expected_tick:
            raise DiagnosticError("stale_expected_tick")
        if state.get("running") or state.get("control_lock_held"):
            raise DiagnosticError("world_running")
        if state.get("active_tick") is not None:
            raise DiagnosticError("partial_tick_requires_recovery")
        if state.get("status") in {"running", "halted", "finished", "error"} or state.get("pause_reason"):
            raise DiagnosticError("world_not_ready")
        if (self.root / "STOP").exists():
            raise DiagnosticError("operator_stopped")
        return state

    @contextmanager
    def exclusive(self):
        # Same order as production supervisor -> worker. No child/supervisor starts.
        with ExitStack() as stack:
            for name in ("supervisor.lock", "operator.lock"):
                try:
                    stack.enter_context(cohort_lock(self.root / name))
                except FileNotFoundError as exc:
                    raise DiagnosticError("cohort_directory_absent") from exc
                except OSError as exc:
                    raise DiagnosticError("controller_busy") from exc
            yield

    def save_evidence(self, directory, name, value):
        # Exclusive create: never overwrite an earlier attempt; no persistence retry.
        with (directory / (name + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

    def evidence_directory(self):
        directory = self.root / "diagnostics" / (str(time.time_ns()) + "-" + uuid4().hex[:8])
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def decide_one(self, profile):
        if not isinstance(profile, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", profile):
            raise DiagnosticError("select_exactly_one_profile")
        citizens = [c for c in self.manifest() if c["profile"] == profile]
        if len(citizens) != 1:
            raise DiagnosticError("select_exactly_one_profile")
        citizen = citizens[0]
        if Path(citizen["home"]).resolve() != (self.profiles / profile).resolve():
            raise DiagnosticError("profile_home_mismatch")
        with self.exclusive():
            local = self.local_state()
            admission = next(p["admission"] for p in local["profiles"] if p["profile"] == profile)
            if admission.get("status") == "pending_actor" or admission.get("actor_id") is None:
                raise DiagnosticError("admission_required")
            if admission.get("status") != "active" or admission.get("tier") != "actor":
                raise DiagnosticError("identity_not_active")
            config = yaml.safe_load((Path(citizen["home"]) / "config.yaml").read_text(encoding="utf-8"))
            credential = read_json(Path(citizen["home"]) / "agent-economy.json")
            mcp = config.get("mcp_servers", {}).get("agent_economy", {})
            tools = {"ae_identity_get", "ae_world_observe", "ae_turn_wait", "ae_actions_list",
                     "ae_action_submit", "ae_action_receipt_get"}
            if (set(config.get("mcp_servers", {})) != {"agent_economy"}
                    or mcp.get("url") != self.args.url + "/mcp"
                    or mcp.get("headers", {}).get("Authorization") != "Bearer " + credential["access_token"]
                    or set(mcp.get("tools", {}).get("include", [])) != tools):
                raise DiagnosticError("profile_gateway_mismatch")
            self.selected = {**citizen, "actor_id": admission["actor_id"]}
            self.target_tick = local["tick"] + 1
            before = self.require_boundary(local["tick"])
            receipts = self.receipts(citizen, self.target_tick)
            if any(r["status"] in {"queued", "executed"} for r in receipts):
                raise DiagnosticError("decision_already_recorded")
            directory = self.evidence_directory()
            self.save_evidence(directory, "before", {"operation": "decide-one", "profile": profile,
                "connection_id": citizen["connection_id"], "world": before, "receipts": receipts,
                "controller_attempt_limit": 1, "underlying_model_requests": "potentially_multiple"})
            result = {"operation": "decide-one", "outcome": "ambiguous", "evidence": str(directory)}
            try:
                with redirect_stdout(sys.stderr):
                    attempt = self.decision_attempt(citizen, self.target_tick, max_attempts=1)
                result["attempt"] = attempt
                result["outcome"] = "queued" if attempt and not attempt["timed_out"] and attempt["exit_code"] == 0 else "ambiguous"
            except Exception as exc:
                result["error_type"] = type(exc).__name__
                if isinstance(exc, DiagnosticError):
                    result["reason"] = str(exc)
            try:
                result["receipts"] = self.receipts(citizen, self.target_tick)
                result["after"] = self.api("/api/run/diagnostics")
                if result["after"].get("run_id") != self.args.run_id or result["after"].get("tick") != local["tick"]:
                    result["outcome"] = "ambiguous"
            except Exception as exc:
                result["observation_error"] = type(exc).__name__
                result["outcome"] = "ambiguous"
            self.save_evidence(directory, "after", result)
            return result

    def advance_one(self, expected_tick):
        with self.exclusive():
            before = self.require_boundary(expected_tick)
            # Also bind the local manifest/database to the requested server world.
            if self.local_state()["tick"] != expected_tick:
                raise DiagnosticError("stale_expected_tick")
            directory = self.evidence_directory()
            body = {"expected_run_id": self.args.run_id, "expected_tick": expected_tick}
            self.save_evidence(directory, "before", {"operation": "advance-one", "request": body, "world": before})
            result = {"operation": "advance-one", "outcome": "ambiguous", "evidence": str(directory)}
            try:
                # Exactly one POST. The server verifies identity/tick under its lock.
                response = self.client.post("/api/run/advance-one", json=body)
                response.raise_for_status()
                result["response"] = response.json()
                result["outcome"] = result["response"].get("outcome", "ambiguous")
            except httpx.HTTPStatusError as exc:
                result["error_type"] = type(exc).__name__
                result["http_status"] = exc.response.status_code
                if 400 <= exc.response.status_code < 500:
                    result["outcome"] = "rejected"
            except Exception as exc:
                result["error_type"] = type(exc).__name__
            try:
                result["after"] = self.api("/api/run/diagnostics")
            except Exception as exc:
                result["observation_error"] = type(exc).__name__
            self.save_evidence(directory, "after", result)
            return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--url", required=True, help="Local sandbox HTTP origin, including port")
    parser.add_argument("--world-root", type=Path, default=ROOT)
    parser.add_argument("--budget-db", type=Path, help="Existing shared allowance to inspect, never create")
    parser.add_argument("--profiles-root", type=Path, default=Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/profiles")
    parser.add_argument("--hermes-python", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/hermes-agent/venv/Scripts/python.exe"))
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("check", allow_abbrev=False)
    decide = sub.add_parser("decide-one", allow_abbrev=False)
    decide.add_argument("--profile", required=True, action="append")
    advance = sub.add_parser("advance-one", allow_abbrev=False)
    advance.add_argument("--expected-tick", type=int, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.run_id):
        parser.error("Use a safe explicit run ID")
    try:
        url = urlsplit(args.url)
        valid = url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"} and url.port is not None and 1 <= url.port <= 65535
    except ValueError:
        valid = False
    if not valid or url.username or url.password or url.path or url.query or url.fragment:
        parser.error("Use a local sandbox HTTP origin with an explicit port")
    if args.operation == "decide-one":
        if len(args.profile) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]+", args.profile[0]):
            parser.error("Specify exactly one profile")
        args.profile = args.profile[0]
    if args.operation == "advance-one" and args.expected_tick < 0:
        parser.error("Expected tick must be nonnegative")
    return args


def main(argv=None):
    args = parse_args(argv)
    operator = DiagnosticOperator(args)
    try:
        if args.operation == "check":
            result = operator.check()
        elif args.operation == "decide-one":
            result = operator.decide_one(args.profile)
        else:
            result = operator.advance_one(args.expected_tick)
        print(json.dumps(result, indent=2))
        return 0 if result.get("outcome", "observed") in {"observed", "queued", "advanced"} else 2
    except Exception as exc:
        print(json.dumps({"outcome": "rejected", "error_type": type(exc).__name__,
            "reason": str(exc) if isinstance(exc, DiagnosticError) else "diagnostic_unavailable"}))
        return 2
    finally:
        operator.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
