"""Bounded, opt-in native Hermes rehearsal with two disposable OAuth citizens.

Private credentials and native logs stay under the ignored output directory.
Only receipt.json is suitable for review; this is not hosted certification.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
import yaml

from engine.store import Store
from run_config import load_config
from server.app import create_app
from world.loop import World


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approve-live-inference", action="store_true")
    args = parser.parse_args()
    if not args.approve_live_inference or not os.environ.get("DEEPSEEK_API_KEY"):
        parser.error("explicit live approval and DEEPSEEK_API_KEY are required")
    output = args.output.resolve()
    ignored = subprocess.run(["git", "check-ignore", "--quiet", str(output / "credentials.json")])
    if ignored.returncode != 0:
        parser.error("output must be inside a git-ignored directory because it holds private credentials")
    output.mkdir(parents=True, exist_ok=False)
    config = load_config("runs/hermes-local.yaml")
    config["engine_semantics_version"] = 14
    config["checkpoint_dir"] = str(output / "checkpoints")
    config["external_gateway"]["decision_seconds"] = 180
    config["external_gateway"]["lease_seconds"] = 5
    config["external_gateway"]["public_join"]["passport_db_path"] = str(output / "passports.db")
    store = Store(str(output / "world.db"))
    store.init_run_meta("native-hermes-rehearsal", 42, config)
    world = World(store, config)
    world.initialize()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(create_app(world), log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    clients: list[dict] = []
    receipt: dict = {"status": "running", "semantics": 14, "provider": "deepseek",
                     "model": "deepseek-flash", "citizens": 2, "rounds": 3, "sessions": []}
    try:
        with httpx.Client(base_url=base, timeout=30) as http:
            for _ in range(100):
                try:
                    if http.get("/.well-known/oauth-authorization-server").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("local fixture did not start")
            metadata = http.get("/.well-known/oauth-authorization-server").json()
            for index in range(2):
                http.cookies.clear()  # Independent owners and native token stores.
                redirect = "http://127.0.0.1:43999/callback"
                registered = http.post("/oauth/register", json={
                    "client_name": f"Disposable Hermes {index}", "redirect_uris": [redirect],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"], "token_endpoint_auth_method": "none",
                    "scope": "world.read world.act", "software_id": "hermes-agent",
                })
                registered.raise_for_status()
                client_info = registered.json()
                verifier = "v" * 64
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                consent = http.get("/oauth/authorize", params={
                    "response_type": "code", "client_id": client_info["client_id"],
                    "redirect_uri": redirect, "code_challenge": challenge,
                    "code_challenge_method": "S256", "resource": f"{base}/mcp",
                    "scope": "world.read world.act", "state": f"test-{index}",
                })
                consent.raise_for_status()
                fields = {name: re.search(rf'name="{name}"\s+value="([^"]+)"', consent.text)[1]
                          for name in ("request_id", "csrf_token")}
                approved = http.post("/oauth/authorize/consent", data={
                    **fields, "decision": "approve", "handle": f"rehearsal-{index}",
                    "display_name": f"Rehearsal {index}", "runtime": "hermes",
                })
                assert approved.status_code == 302
                code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
                pair_response = http.post("/oauth/token", data={
                    "grant_type": "authorization_code", "code": code,
                    "client_id": client_info["client_id"], "redirect_uri": redirect,
                    "code_verifier": verifier, "resource": f"{base}/mcp",
                })
                pair_response.raise_for_status()
                pair = pair_response.json()
                home = output / "profiles" / f"citizen-{index}"
                tokens = home / "mcp-tokens"
                tokens.mkdir(parents=True)
                pair["expires_at"] = time.time() + pair["expires_in"]
                for suffix, value in ((".json", pair), (".client.json", client_info), (".meta.json", metadata)):
                    (tokens / f"agent_economy{suffix}").write_text(json.dumps(value))
                (home / "config.yaml").write_text(yaml.safe_dump({
                    "model": {"default": "deepseek-flash", "provider": "deepseek"},
                    "fallback_providers": [],
                    "mcp_servers": {"agent_economy": {"url": f"{base}/mcp", "auth": "oauth", "connect_timeout": 30}},
                }))
                clients.append({"home": home, "pair": pair, "client_id": client_info["client_id"]})

            def step() -> None:
                response = http.post("/api/run/step")
                response.raise_for_status()

            def native(index: int, round_number: int) -> None:
                client = clients[index]
                env = os.environ.copy()
                env.update(HERMES_HOME=str(client["home"]), PYTHONIOENCODING="utf-8")
                for key in ("HERMES_PROFILE", "HERMES_CONFIG", "HERMES_ENV"):
                    env.pop(key, None)
                prompt = output / f"prompt-{index}-{round_number}.txt"
                action = ("Submit exactly one do_nothing action deliberately." if round_number == 2 else
                          "Submit exactly one valid small ordinary action from the supplied catalog; prefer buy_goods qty 1.")
                prompt.write_text(
                    "You are a disposable citizen in an authorized local integration test. Use ONLY agent_economy MCP tools. "
                    "Call one tool per tool_call, never batch local calls. Get your identity and a fresh turn envelope. " + action +
                    " Use the exact target tick, projection hash and a unique idempotency key from this turn. "
                    "Copy only the catalog item's action object, never its channel or other metadata. "
                    "Do not post messages, communicate with anyone, use terminal tools, or advance the world. "
                    "Stop immediately when the server returns a queued receipt. Report the actual receipt ID.")
                accepted_sql = "SELECT COUNT(*) FROM external_action_submissions WHERE status IN ('queued','executed')"
                before = int(store.scalar(accepted_sql) or 0)
                with (output / f"native-{index}-{round_number}.log").open("w", encoding="utf-8") as log:
                    result = subprocess.run([
                        args.hermes_python, "-m", "hermes_cli.main", "chat", "--oneshot",
                        "--provider", "deepseek", "--model", "deepseek-flash", "--toolsets", "agent_economy",
                        "--ignore-rules", "--max-turns", "10", "--run-budget", "120",
                        "--query-file", str(prompt),
                    ], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=150)
                assert result.returncode == 0, f"native citizen {index} failed"
                after = int(store.scalar(accepted_sql) or 0)
                assert after == before + 1, f"native citizen {index} did not submit exactly once"
                receipt["sessions"].append({"citizen": index, "round": round_number, "submitted": True})
                print(f"citizen {index}, round {round_number}: native submission verified", flush=True)

            step()  # Admit both citizens through the ordinary world loop.
            old_refresh = clients[0]["pair"]["refresh_token"]
            for round_number in range(1, 4):
                if round_number == 2:
                    # Deterministic expiry injection, confined to this disposable world's credential.
                    pair = clients[0]["pair"]
                    store.execute("UPDATE external_agent_credentials SET expires_at=? WHERE token_hash=?", (
                        "2000-01-01T00:00:00+00:00", hashlib.sha256(pair["access_token"].encode()).hexdigest()))
                    store.commit()
                    expired = dict(pair, expires_at=time.time() - 60)
                    (clients[0]["home"] / "mcp-tokens/agent_economy.json").write_text(json.dumps(expired))
                for index in range(2):
                    native(index, round_number)
                step()
                if round_number == 2:
                    refreshed = json.loads((clients[0]["home"] / "mcp-tokens/agent_economy.json").read_text())
                    assert refreshed["access_token"] != clients[0]["pair"]["access_token"]
                    assert refreshed["refresh_token"] != old_refresh
                    rejected = http.post("/oauth/token", data={
                        "grant_type": "refresh_token", "refresh_token": old_refresh,
                        "client_id": clients[0]["client_id"], "resource": f"{base}/mcp",
                    })
                    assert rejected.status_code >= 400
                    receipt["native_refresh_after_expiry"] = True
                    receipt["rotated_refresh_reuse_rejected"] = True
            time.sleep(11)  # Gateway clamps leases to at least ten seconds.
            step()  # Both native processes are offline; record missed attendance.
            rows = [dict(row) for row in store.query(
                "SELECT actor_id,target_tick,attendance_status,operational_reason,decision_policy "
                "FROM external_turn_attendance ORDER BY target_tick,actor_id")]
            submitted = [row for row in rows if row["attendance_status"] == "submitted"]
            assert len(submitted) == 6
            missed = [row for row in rows if row["target_tick"] == store.tick]
            assert len(missed) == 2 and all(row["attendance_status"] == "missed" for row in missed)
            assert len({row["actor_id"] for row in submitted}) == 2
            results = [dict(row) for row in store.query(
                "SELECT id,status,result_json FROM external_action_submissions ORDER BY created_at")]
            assert sum(row["status"] == "executed" for row in results) == 6
            assert not any(row["status"] == "queued" for row in results)
            assert all(item.get("ok") is True for row in results if row["status"] == "executed"
                       for item in json.loads(row["result_json"]))
            reconciled, diagnostic = world.economy.ledger.reconcile()
            assert reconciled, diagnostic
            receipt.update(status="passed", tick=store.tick, attendance=rows, submissions=results,
                           ledger_balanced=True, setup="synthetic local OAuth consent; real installed Hermes runtime",
                           expiry="injected expired access credential and cache; native refresh over HTTP")
    except Exception as exc:
        receipt.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        world.close()
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
