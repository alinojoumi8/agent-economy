"""Rehearse v4 choices and voting, then prove exact replay without networking.

Creates a fresh private directory; never resumes or overwrites a world. The
fixed scripted profile measures integration correctness, not model quality.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay


async def rehearse(output: Path, ticks: int) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    config = load_config(ROOT / "runs/jev-society-offline.yaml")
    config.update(checkpoint_dir=str(output / "checkpoints"), report_dir=str(output / "reports"))
    config.setdefault("government", {})["election_interval_ticks"] = 5
    network_attempts = []

    def forbidden(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError("The Jev offline rehearsal cannot use networking")

    async def forbidden_async(*args, **kwargs):
        return forbidden()

    # Enter after asyncio creates its Windows wakeup socket. Block HTTP clients
    # and new outbound socket connections during both source and replay runs.
    with ExitStack() as guards:
        guards.enter_context(patch.object(httpx.AsyncClient, "send", forbidden_async))
        guards.enter_context(patch.object(httpx.Client, "send", forbidden))
        guards.enter_context(patch.object(socket, "create_connection", forbidden))
        guards.enter_context(patch.object(socket.socket, "connect", forbidden))
        guards.enter_context(patch.object(socket.socket, "connect_ex", forbidden))
        store, world, run_id = open_run(config, None, None, data_dir=output)
        source_path = Path(store.path)
        try:
            for tick in range(1, ticks + 1):
                await world.step()
                if store.tick != tick:
                    raise AssertionError(f"World stopped before tick {tick}")
            statuses, retained_routes, rejections = Counter(), Counter(), Counter()
            accepted = 0
            for row in store.query("SELECT json_extract(payload_json,'$.status') AS status, "
                    "json_extract(payload_json,'$.reason') AS reason, "
                    "json_extract(payload_json,'$.outcomes') AS outcomes "
                    "FROM events WHERE kind='typed_decision'"):
                statuses[row["status"]] += 1
                if row["status"] == "outside_menu":
                    retained_routes[row["reason"]] += 1
                for outcome in json.loads(row["outcomes"]):
                    if outcome.get("ok") is True:
                        accepted += 1
                    else:
                        rejections[outcome.get("reason", "unspecified")] += 1
            receipt = {
                "contract": "jev-domains-offline-acceptance-v1",
                "profile": "runs/jev-society-offline.yaml",
                "overrides": {"government.election_interval_ticks": 5},
                "run_id": run_id, "tick": store.tick,
                "decision_errors": store.scalar("SELECT COUNT(*) FROM events WHERE kind='decision_error'"),
                "typed_decisions": store.scalar("SELECT COUNT(*) FROM events WHERE kind='typed_decision'"),
                "ballots_cast": store.scalar("SELECT COUNT(*) FROM events WHERE kind='ballot_cast'"),
                "service_selections": store.scalar("SELECT COUNT(*) FROM events WHERE kind='bounded_selection'"),
                "recorded_cost_usd": store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls"),
                "non_scripted_calls": store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'"),
                "ledger_reconciled": world.economy.ledger.reconcile()[0],
                "typed_statuses": dict(statuses),
                "retained_route_reasons": dict(retained_routes),
                "accepted_actions": accepted, "rejected_actions": sum(rejections.values()),
                "rejection_reasons": dict(rejections),
            }
        finally:
            world.close()
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        replay_store, replay_world, replay_id = open_run({}, None, run_id, data_dir=output)
        replay_path = Path(replay_store.path)
        try:
            await replay_headless(replay_world, ticks)
            receipt["replay_ledger_reconciled"] = replay_world.economy.ledger.reconcile()[0]
            receipt["replay_calls_consumed_once"] = replay_world.gateway.replay_execution_stats()[
                "all_nonoperational_calls_consumed_once"]
        finally:
            replay_world.close()
        proof = verify_replay(source_path, replay_path)
        receipt.update(
            replay_run_id=replay_id, replay_exact=proof["exact"], differences=proof["differences"],
            source_unchanged=hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash,
            source_sha256=source_hash, source_canonical_sha256=proof["source_hash"],
            replay_canonical_sha256=proof["replay_hash"], provider_free=receipt["non_scripted_calls"] == 0,
            network_attempts=len(network_attempts), network_disabled=True,
        )
    (output / "replay-proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    gates = (receipt["replay_exact"], receipt["source_unchanged"], receipt["provider_free"],
             receipt["ledger_reconciled"], receipt["replay_ledger_reconciled"],
             receipt["replay_calls_consumed_once"], receipt["decision_errors"] == 0,
             receipt["recorded_cost_usd"] == 0, receipt["network_attempts"] == 0)
    if not all(gates):
        raise AssertionError(f"Acceptance failed; retained evidence: {output / 'receipt.json'}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New private output directory")
    parser.add_argument("--ticks", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.ticks <= 100:
        parser.error("--ticks must be between 1 and 100")
    print(json.dumps(asyncio.run(rehearse(args.out.resolve(), args.ticks)), indent=2))


if __name__ == "__main__":
    main()
