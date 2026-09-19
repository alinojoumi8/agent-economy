"""Real loopback HTTP through both model capabilities and observer boundaries."""
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from agents.typed_policy import TypedDecisionPolicy, record_execution_receipt
from llm.gateway import Gateway, LLMRequest
from run import open_run, replay_headless
from run_config import load_config
from server.projections.causal import _semantic_row
from server.projections.decisions import build_decision_workspace
from server.projections.events import build_events
from tests.test_jev_candidates import observation
from world.replay_verify import verify_replay

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def loopback():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, data))
            assert self.headers["Authorization"] == "Bearer loopback-private-key"
            native = self.path == "/api/alpha/decisions"
            value = data if native else json.loads(data["messages"][1]["content"])
            questions = value["questions"]
            answers = {key: {"type": "choice", "choice": next(iter(question["criteria"])),
                "confidence": .2 if native else .9} for key, question in questions.items()}
            if native:
                assert set(data) == {"model", "state", "questions", "provider"}
                assert data["provider"] == {"allow_fallbacks": False}
                response = {"model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
                    "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 20, "cost": .0000042}}
            else:
                raise AssertionError("The Jev pilot must not call another model")
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_jev_abstention_uses_no_second_model_and_replays_without_service(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "loopback-private-key")
    with loopback() as (url, calls):
        config = load_config(ROOT / "runs/jev-hybrid.yaml")
        config["llm"]["providers"]["openrouter_jev"]["endpoint"] = url + "/api/alpha/decisions"
        config.update(checkpoint_dir=str(tmp_path / "checkpoints"), report_dir=str(tmp_path / "reports"))
        store, world, run_id = open_run(config, None, None, data_dir=tmp_path)
        source = Path(store.path)
        try:
            asyncio.run(world.step())
            receipts = [json.loads(row[0]) for row in store.query("SELECT payload_json FROM events WHERE kind='typed_decision'")]
            abstained = [r for r in receipts if r["status"] == "abstained"]
            assert abstained and all(len(r["calls"]) == 1 for r in abstained)
            assert all(not r["escalated"] and r["selected_candidate"] == "wait" for r in abstained)
            assert calls and all(path == "/api/alpha/decisions" for path, _ in calls)
            assert world.gateway._typed_completion_guard.snapshot()["provider_calls"] == len(calls)
            assert world.economy.ledger.reconcile()[0]
        finally:
            world.close()
    monkeypatch.delenv("OPENROUTER_API_KEY")
    replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 1))
        proof = verify_replay(source, replay_store.path)
        assert proof["exact"], proof["differences"]
    finally:
        replay_world.close()


def test_observer_events_and_causal_views_strip_private_menu(store):
    receipt = {"status": "selected", "reason": "provider_choice", "selected_candidate": "choice",
        "receipt_key": "fixture", "confidence": .7, "escalated": False,
        "evaluation": {"state": {"memories": ["PRIVATE-MEMORY"]}},
        "candidates": [{"id": "choice", "actions": [{"type": "buy_goods", "qty": 2}],
                        "facts": {"remaining_cash_cents": 123456}}], "calls": []}
    record_execution_receipt(store, 2, {"agent_id": 1, "typed_receipt": receipt}, [{"ok": True}])
    assert not build_decision_workspace(store, as_of_tick=1)["items"]
    summary = build_decision_workspace(store, as_of_tick=2)
    event = build_events(store, as_of_tick=2)["items"][0]
    causal = _semantic_row(store, {"kind": "event", "id": event["id"]})
    for value in (summary, event, causal):
        serialized = json.dumps(value)
        assert "PRIVATE-MEMORY" not in serialized and "123456" not in serialized
        assert "evaluation" not in serialized and "candidates" not in serialized
    assert summary["items"][0]["action_types"] == ["buy_goods"]
    assert summary["items"][0]["accepted"] == 1
