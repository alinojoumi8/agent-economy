"""Persistent local Hermes cohort operator. Secrets stay in isolated profiles.

Provision with --setup, then run bounded days with --days N. Re-running resumes
the same world and profile sessions and verifies queued/executed receipts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

import httpx
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
COHORT = [
    ("maya-chen", "Maya Chen", "engineer", "Practical and careful. Seek engineering work and improve useful skills."),
    ("omar-haddad", "Omar Haddad", "small_business", "Entrepreneurial but cost-conscious. Look for unmet needs and viable business opportunities."),
    ("sofia-reyes", "Sofia Reyes", "teacher", "Patient and community-minded. Seek stable work and develop teaching skills."),
    ("noah-okafor", "Noah Okafor", "nurse", "Service-oriented and reliable. Prefer healthcare employment and a savings buffer."),
    ("leila-patel", "Leila Patel", "accountant", "Analytical and frugal. Seek accounting work and protect household liquidity."),
    ("lucas-moreau", "Lucas Moreau", "construction", "Hands-on and ambitious. Seek construction work and practical training."),
    ("aisha-mensah", "Aisha Mensah", "software_dev", "Inventive and methodical. Develop software skills and look for productive employment."),
    ("ethan-kim", "Ethan Kim", "retail_worker", "Sociable and cautious. Seek retail work and keep essential goods affordable."),
    ("isabel-costa", "Isabel Costa", "economist", "Curious and evidence-driven. Study market conditions and seek sustainable work."),
    ("daniel-novak", "Daniel Novak", "gig_worker", "Adaptable and independent. Balance flexible jobs, learning, and financial reserves."),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class MissingQueuedAction(RuntimeError):
    """A completed model turn has no accepted submission and can be corrected."""


class CohortOperator:
    def __init__(self, args):
        self.args = args
        self.root = ROOT / "data/control-plane/hermes-cohort" / args.run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.json"
        self.client = httpx.Client(base_url=args.url, timeout=300, trust_env=False)
        self.database = ROOT / "data/runs" / f"{args.run_id}.db"
        self.hermes = Path(args.hermes_python)
        self.profiles = Path(args.profiles_root)

    def api(self, path, *, body=None, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self.client.request("POST" if body is not None else "GET", path, json=body, headers=headers)
        response.raise_for_status()
        return response.json()

    def check_world(self):
        state = self.api("/api/run/status")
        if state["run_id"] != self.args.run_id:
            raise RuntimeError("The server is serving a different world; refusing to dispatch citizens")
        if state.get("active_tick") is not None or state.get("running"):
            raise RuntimeError("Pause and complete the current world tick before using the cohort operator")
        if state.get("status") in {"halted", "finished", "error"} or state.get("pause_reason"):
            raise RuntimeError("The world requires operator attention before continuing")
        return state

    def setup(self):
        self.check_world()
        manifest = read_json(self.manifest_path) if self.manifest_path.exists() else {
            "run_id": self.args.run_id, "citizens": [], "created_at": time.time()}
        for slug, name, occupation, goal in COHORT:
            if any(c["name"] == name for c in manifest["citizens"]):
                continue
            profile = f"ae-{self.args.run_id}-{slug}"
            home = self.profiles / profile
            pending_path = self.root / f"{slug}-registration.json"
            if not home.exists():
                subprocess.run([str(self.hermes), "-m", "hermes_cli.main", "profile", "create",
                                profile, "--no-alias", "--no-skills", "--description", goal], check=True,
                               stdout=subprocess.DEVNULL)
            if pending_path.exists():
                registration = read_json(pending_path)
            else:
                registration = self.api("/api/v2/public/agent-registrations", body={
                    "world_slug": "local-sandbox", "handle": profile, "display_name": name,
                    "biography": goal, "preferred_occupation": occupation, "runtime": "hermes"})
                write_json(pending_path, registration)
            claim = self.client.get(registration["claim_url"])
            claim.raise_for_status()
            match = re.search(r'name="csrf_token"\s+value="([^"]+)"', claim.text)
            if not match:
                raise RuntimeError(f"Claim form unavailable for {name}")
            claim = self.client.post(registration["claim_url"], data={"csrf_token": match.group(1)})
            claim.raise_for_status()
            credential_path = home / "agent-economy.json"
            if credential_path.exists():
                credential = read_json(credential_path)
            else:
                credential = self.api(f"/api/v2/public/agent-registrations/{registration['registration_id']}/exchange",
                                      body={}, token=registration["bootstrap_token"])
                write_json(credential_path, credential)
            config = {
                "model": {"provider": "openai-codex", "default": "gpt-5.6-luna", "max_tokens": 2000},
                "agent": {"max_turns": 12, "reasoning_effort": "low", "api_max_retries": 1},
                "toolsets": ["agent_economy"],
                "mcp_servers": {"agent_economy": {"url": self.args.url + "/mcp",
                    "headers": {"Authorization": "Bearer " + credential["access_token"]},
                    "tools": {"include": ["ae_identity_get", "ae_world_observe", "ae_turn_wait",
                        "ae_actions_list", "ae_action_submit", "ae_action_receipt_get"]},
                    "resources": False, "prompts": False}},
            }
            (home / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            (home / "SOUL.md").write_text(f"You are {name}, a persistent simulated citizen. {goal}\n", encoding="utf-8")
            citizen = {"profile": profile, "name": name, "occupation": occupation, "goal": goal,
                       "connection_id": credential["connection"]["id"], "home": str(home)}
            manifest["citizens"].append(citizen)
            write_json(self.manifest_path, manifest)
            # The exchanged bootstrap token is no longer useful.
            pending_path.unlink()
            print(f"Onboarded {name}", flush=True)
        write_json(ROOT / "data/control-plane/hermes-city.json", {"run_id": self.args.run_id})

    def receipts(self, citizen, tick):
        with sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT id,status,actor_id,action_json,result_json FROM external_action_submissions "
                "WHERE connection_id=? AND target_tick=? ORDER BY created_at", (citizen["connection_id"], tick))]

    def recover_day(self, citizens):
        """Finish a crashed operator day only when all decisions were saved."""
        state = self.api("/api/run/status")
        if state["run_id"] != self.args.run_id or state.get("running") or state.get("pause_reason"):
            raise RuntimeError("The world is not available for saved-day recovery")
        active = state.get("active_tick")
        if active is None:
            return
        if (self.root / "STOP").exists():
            raise RuntimeError("A partial day is saved; resume explicitly before recovering it")
        if not all(any(row["status"] in {"queued", "executed", "rejected"}
                       for row in self.receipts(citizen, active)) for citizen in citizens):
            raise RuntimeError("Partial day has incomplete cohort receipts; inspect it before recovery")
        self.api("/api/run/step", body={})
        if self.check_world()["tick"] != active:
            raise RuntimeError("Saved-day recovery did not reach its expected boundary")
        write_json(self.root / f"day-{active}.json", {
            citizen["name"]: self.receipts(citizen, active) for citizen in citizens})
        print(f"Recovered saved day {active} without re-dispatching Hermes", flush=True)

    def decide(self, citizen, tick):
        for attempt in range(1, 4):
            if any(row["status"] == "queued" for row in self.receipts(citizen, tick)):
                return
            if (self.root / "STOP").exists():
                return
            if attempt > 1 and self.check_world()["tick"] != tick - 1:
                raise RuntimeError("The world changed before decision recovery; refusing to retry a stale day")
            try:
                self._decide_once(citizen, tick, attempt=attempt)
                return
            except MissingQueuedAction:
                with (self.root / "decision-retries.jsonl").open("a", encoding="utf-8") as journal:
                    journal.write(json.dumps({"time": time.time(), "citizen": citizen["name"],
                        "tick": tick, "attempt": attempt, "reason": "no_queued_receipt"}) + "\n")
                if attempt == 3:
                    raise
                print(f"{citizen['name']}: refreshing turn after missing receipt (attempt {attempt}/3)", flush=True)

    def _decide_once(self, citizen, tick, *, attempt=1):
        if any(row["status"] == "queued" for row in self.receipts(citizen, tick)):
            return
        if (self.root / "STOP").exists():
            return  # The run loop will retain queued actions without advancing.
        home = Path(citizen["home"])
        token = read_json(home / "agent-economy.json")["access_token"]
        identity = self.api("/api/v2/agent/me", token=token)
        if not identity.get("actor"):
            raise RuntimeError(f"{citizen['name']} has not arrived yet")
        # Polling alone intentionally retains a closed turn. Explicit local
        # renewal reopens only an expired, unconsumed next-day window and audits it.
        self.api("/api/v2/agent/turn/renew", body={"target_tick": tick}, token=token)
        output = self.root / citizen["profile"]
        output.mkdir(exist_ok=True)
        # Keep failed attempts, including those from a previous process, for diagnosis.
        attempt_id = f"tick-{tick}-attempt-{attempt}-{time.time_ns()}"
        prompt = output / f"{attempt_id}.txt"
        prompt.write_text(
            f"You are {citizen['name']}, a persistent Agent Economy citizen. {citizen['goal']} "
            f"Continue your own saved life and prior plans. Target tick {tick}. "
            "Use only agent_economy MCP tools. Read identity and the receipt for your previous action if available. "
            "Observe the world, list legal actions, and get a fresh turn envelope. Submit exactly one valid action "
            "for this wake using its exact tick, projection hash and a unique idempotency key. "
            "Call ae_turn_wait immediately before submitting. Copy its complete 64-character projection hash "
            "verbatim into observed_projection_hash; never abbreviate, guess, or reuse an old hash. "
            "Call one MCP tool per tool_call. If tool argument validation fails or the turn is stale, "
            "fetch ae_turn_wait again and correct the submission. Do not finish until a queued receipt is confirmed. "
            f"This is attempt {attempt} of at most 3; if recovering, your previous turn did not yield a queued receipt. "
            "Choose useful economic "
            "work, job seeking, training, exploration, settlement founding or building, moving, civic voting, "
            "or essential purchases based on your own goals and affordability. Frontier actions appear only when available; "
            "you may choose a meaningful unique name for a new settlement. Read action "
            "schemas; never invent parameters. If already queued, do not duplicate it. Do not publish posts or send "
            "messages, including say_public or Commons writes. Do not advance the world. End with your receipt ID "
            "and a short plan to carry into the next day. The operator executes the day after all citizens finish.", encoding="utf-8")
        model = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))["model"]
        command = [str(self.hermes), "-m", "hermes_cli.main", "--profile", citizen["profile"],
                   "chat", "--oneshot", "--provider", model["provider"], "--model", model["default"],
                   "--toolsets", "agent_economy", "--ignore-rules", "--max-turns", "12",
                   "--run-budget", "180", "--query-file", str(prompt)]
        session = output / "session.json"
        if session.exists():
            command += ["--resume", read_json(session)["session_id"], "--no-restore-cwd"]
        env = os.environ.copy()
        # Resolve OAuth through Hermes' profile/global auth store. Never clone
        # rotating ChatGPT tokens or require an unrelated provider's API key.
        if model["provider"] == "deepseek":
            key = (dotenv_values(home / ".env").get("DEEPSEEK_API_KEY")
                   or dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY"))
            if not key:
                raise RuntimeError("DEEPSEEK_API_KEY is unavailable; no substitute agent will act")
            env["DEEPSEEK_API_KEY"] = key
        env["PYTHONIOENCODING"] = "utf-8"
        log_path = output / f"{attempt_id}.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=home, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
        # Desktop and connection checks can create newer conversations while
        # this citizen resumes an older one. Persist the session from THIS CLI
        # invocation, never the latest row in the shared profile database.
        transcript = re.sub(r"\x1b\[[0-9;]*m", "", log_path.read_text(encoding="utf-8", errors="replace"))
        session_ids = re.findall(r"Session:\s+([a-zA-Z0-9_-]+)", transcript)
        session_id = session_ids[-1] if session_ids else (read_json(session)["session_id"] if session.exists() else None)
        with sqlite3.connect(f"file:{(home / 'state.db').as_posix()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row:
                write_json(session, {"session_id": row[0], "last_attempt_tick": tick})
            elif result.returncode == 0:
                raise RuntimeError(f"{citizen['name']} did not identify its saved session; no unrelated session will be substituted")
        if not any(row["status"] == "queued" for row in self.receipts(citizen, tick)):
            error = RuntimeError if result.returncode else MissingQueuedAction
            raise error(f"{citizen['name']} did not queue an action; inspect {log_path}")
        print(f"{citizen['name']}: queued tick {tick}", flush=True)

    def run(self):
        manifest = read_json(self.manifest_path)
        citizens = manifest["citizens"]
        if len(citizens) != 10:
            raise RuntimeError("Exactly ten provisioned citizens are required")
        with (self.root / "operator.lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover_day(citizens)
            self.check_world()
            if not (self.root / "STOP").exists():
                identities = [self.api("/api/v2/agent/me", token=read_json(
                    Path(c["home"]) / "agent-economy.json")["access_token"]) for c in citizens]
                if any(item.get("status") == "pending_actor" for item in identities):
                    self.api("/api/run/step", body={})
                    print(f"Saved admission day {self.check_world()['tick']}", flush=True)
            for _ in range(self.args.days):
                if (self.root / "STOP").exists():
                    print("Stopped at a saved day boundary", flush=True)
                    break
                tick = self.check_world()["tick"] + 1
                write_json(self.root / "status.json", {"state": "deciding", "tick": tick, "pid": os.getpid()})
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(lambda citizen: self.decide(citizen, tick), citizens))
                if (self.root / "STOP").exists():
                    break
                if self.check_world()["tick"] != tick - 1:
                    raise RuntimeError("The world advanced outside this operator; refreshing is required")
                self.api("/api/run/step", body={})
                state = self.check_world()
                if state["tick"] != tick:
                    raise RuntimeError("The world did not complete the expected day")
                evidence = {c["name"]: self.receipts(c, tick) for c in citizens}
                write_json(self.root / f"day-{tick}.json", evidence)
                write_json(self.root / "status.json", {"state": "day_completed", "tick": tick, "pid": os.getpid()})
                print(f"Saved day {tick}: {sum(len(v) for v in evidence.values())} receipts", flush=True)
            write_json(self.root / "status.json", {"state": "paused", "tick": self.check_world()["tick"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--hermes-python", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/hermes-agent/venv/Scripts/python.exe"))
    parser.add_argument("--profiles-root", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/profiles"))
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--supervise", action="store_true", help="Record child exits and progress independently")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.run_id) or not 1 <= args.days <= 100:
        parser.error("Use a safe run ID and 1-100 days per bounded session")
    if args.url not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        parser.error("This operator supports the local sandbox only")
    if args.supervise:
        from hermes_supervision import supervise
        return supervise(ROOT, args.run_id, [sys.executable, str(Path(__file__).resolve()),
            *[arg for arg in sys.argv[1:] if arg != "--supervise"]], args.days)
    operator = CohortOperator(args)
    try:
        operator.setup() if args.setup else operator.run()
    except Exception as exc:
        write_json(operator.root / "status.json", {"state": "error", "error": str(exc)})
        raise
    finally:
        operator.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
