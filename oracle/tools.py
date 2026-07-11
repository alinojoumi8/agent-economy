"""Bounded read-only tools available to the Oracle analyst."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

class OracleToolError(ValueError):
    pass


class OracleTools:
    MAX_QUERIES = 8
    MAX_RESULT_CHARS = 20_000
    ENTITY_TYPES = {"agent", "firm", "bank", "gov", "central_bank", "system"}
    METRIC_NAME = re.compile(r"^[A-Za-z0-9_:.-]{1,80}$")

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self._tools: dict[str, Callable[..., Any]] = {
            "query_metrics": self.query_metrics,
            "read_news": self.read_news,
            "sample_conversations": self.sample_conversations,
            "inspect_agent": self.inspect_agent,
            "get_ledger_summary": self.get_ledger_summary,
            "read_order_book": self.read_order_book,
        }

    @property
    def definitions(self) -> list[dict]:
        bank_ids = [int(row["id"]) for row in self.store.query(
            "SELECT id FROM banks ORDER BY id LIMIT 20")]
        return [
            {"name": "query_metrics", "args": {
                "names": "list[str]", "from_tick": "int|null",
                "to_tick": "int|null", "limit": "1..200"}},
            {"name": "read_news", "args": {
                "from_tick": "int|null", "to_tick": "int|null", "limit": "1..20"}},
            {"name": "sample_conversations", "args": {
                "agent_id": "int|null", "from_tick": "int|null",
                "to_tick": "int|null", "limit": "1..20"}},
            {"name": "inspect_agent", "args": {"agent_id": "int"}},
            {"name": "get_ledger_summary", "args": {
                "entity_type": "agent|firm|bank|gov|central_bank|system",
                "entity_id": (
                    "existing int required for agent|firm|bank; "
                    "omit for gov|central_bank|system")},
             "available_entity_ids": {"bank": bank_ids}},
            {"name": "read_order_book", "args": {
                "firm_id": "int|null", "depth": "1..20"}},
        ]

    def execute_plan(self, queries: list[dict]) -> list[dict]:
        if not isinstance(queries, list):
            raise OracleToolError("queries must be a list")
        if len(queries) > self.MAX_QUERIES:
            raise OracleToolError(f"at most {self.MAX_QUERIES} tool queries are allowed")
        transcript = []
        total_chars = 0
        for request in queries:
            if not isinstance(request, dict):
                raise OracleToolError("each query must be an object")
            name = str(request.get("tool", ""))
            args = request.get("args", {})
            if name not in self._tools:
                raise OracleToolError(f"unknown or non-read-only Oracle tool: {name!r}")
            if not isinstance(args, dict):
                raise OracleToolError("tool args must be an object")
            try:
                result = self._tools[name](**args)
            except TypeError as exc:
                raise OracleToolError(
                    f"invalid arguments for {name}: {exc}") from exc
            item = {"tool": name, "args": args, "result": result}
            total_chars += len(json.dumps(item, sort_keys=True))
            if total_chars > self.MAX_RESULT_CHARS:
                raise OracleToolError("Oracle tool transcript exceeds the bounded result size")
            transcript.append(item)
        return transcript

    @staticmethod
    def _bounded_limit(value: int, maximum: int) -> int:
        limit = int(value)
        if limit < 1 or limit > maximum:
            raise OracleToolError(f"limit must be between 1 and {maximum}")
        return limit

    def _tick_range(self, from_tick: Optional[int], to_tick: Optional[int]) -> tuple[int, int]:
        end = self.store.tick if to_tick is None else int(to_tick)
        start = max(0, end - 30) if from_tick is None else int(from_tick)
        if start < 0 or end < start or end > self.store.tick:
            raise OracleToolError("invalid tick range")
        return start, end

    def query_metrics(self, names: list[str], from_tick: Optional[int] = None,
                      to_tick: Optional[int] = None, limit: int = 200) -> dict:
        if not isinstance(names, list) or not names or len(names) > 10:
            raise OracleToolError("names must contain 1 to 10 metric names")
        clean = [str(name) for name in names]
        if any(not self.METRIC_NAME.fullmatch(name) for name in clean):
            raise OracleToolError("invalid metric name")
        start, end = self._tick_range(from_tick, to_tick)
        cap = self._bounded_limit(limit, 200)
        out = {}
        for name in clean:
            rows = self.store.query(
                "SELECT tick, value FROM metrics WHERE name=? AND tick BETWEEN ? AND ? "
                "ORDER BY tick DESC LIMIT ?", (name, start, end, cap))
            out[name] = [
                {"tick": int(row["tick"]), "value": float(row["value"])}
                for row in reversed(rows)]
        return out

    def read_news(self, from_tick: Optional[int] = None,
                  to_tick: Optional[int] = None, limit: int = 20) -> list[dict]:
        start, end = self._tick_range(from_tick, to_tick)
        cap = self._bounded_limit(limit, 20)
        return [
            {"id": int(row["id"]), "tick": int(row["tick"]),
             "outlet": row["outlet_name"], "headline": row["headline"],
             "tone": float(row["tone"]), "truthful": bool(row["truthful"])}
            for row in self.store.query(
                "SELECT * FROM news_articles WHERE tick BETWEEN ? AND ? "
                "ORDER BY id DESC LIMIT ?", (start, end, cap))
        ]

    def sample_conversations(self, agent_id: Optional[int] = None,
                             from_tick: Optional[int] = None,
                             to_tick: Optional[int] = None,
                             limit: int = 20) -> list[dict]:
        start, end = self._tick_range(from_tick, to_tick)
        cap = self._bounded_limit(limit, 20)
        params: list[Any] = [start, end]
        where = "m.tick BETWEEN ? AND ?"
        if agent_id is not None:
            aid = int(agent_id)
            if not self.store.query_one("SELECT 1 FROM agents WHERE id=?", (aid,)):
                raise OracleToolError("agent not found")
            where += " AND (m.agent_id=? OR EXISTS (SELECT 1 FROM json_each(c.participant_ids) WHERE value=?))"
            params.extend([aid, aid])
        params.append(cap)
        return [
            {"conversation_id": int(row["conv_id"]), "tick": int(row["tick"]),
             "speaker_id": int(row["agent_id"]), "text": row["text"]}
            for row in self.store.query(
                "SELECT m.conv_id, m.tick, m.agent_id, m.text FROM messages m "
                "JOIN conversations c ON c.id=m.conv_id WHERE " + where +
                " ORDER BY m.id DESC LIMIT ?", params)
        ]

    def inspect_agent(self, agent_id: int) -> dict:
        aid = int(agent_id)
        agent = self.store.query_one(
            "SELECT id,name,kind,role,occupation,age,health,alive,retired,employer_id,"
            "risk_tolerance,political_lean FROM agents WHERE id=?", (aid,))
        if not agent:
            raise OracleToolError("agent not found")
        return {
            "agent": dict(agent),
            "accounts": [dict(row) for row in self.store.query(
                "SELECT id,kind,bank_id,balance_cents FROM accounts "
                "WHERE owner_type='agent' AND owner_id=? ORDER BY id", (aid,))],
            "beliefs": [dict(row) for row in self.store.query(
                "SELECT key,value,updated_tick FROM beliefs WHERE agent_id=? "
                "ORDER BY updated_tick DESC,key LIMIT 20", (aid,))],
            "memories": [dict(row) for row in self.store.query(
                "SELECT tick,kind,text,importance FROM memories WHERE agent_id=? "
                "ORDER BY id DESC LIMIT 12", (aid,))],
        }

    def get_ledger_summary(self, entity_type: str, entity_id: Optional[int] = None) -> dict:
        kind = str(entity_type)
        if kind not in self.ENTITY_TYPES:
            raise OracleToolError("unsupported entity type")
        if kind in {"gov", "central_bank", "system"}:
            rows = self.store.query(
                "SELECT id,kind,label,balance_cents,bank_id FROM accounts "
                "WHERE owner_type=? ORDER BY id", (kind,))
        else:
            if entity_id is None:
                raise OracleToolError("entity_id is required")
            rows = self.store.query(
                "SELECT id,kind,label,balance_cents,bank_id FROM accounts "
                "WHERE owner_type=? AND owner_id=? ORDER BY id",
                (kind, int(entity_id)))
        accounts = [dict(row) for row in rows]
        if not accounts:
            raise OracleToolError("entity ledger accounts not found")
        summary = {
            "entity_type": kind, "entity_id": entity_id,
            "accounts": accounts,
            "net_balance_cents": sum(int(row["balance_cents"]) for row in rows),
        }
        if kind == "bank" and entity_id is not None:
            bid = int(entity_id)
            summary.update({
                "deposits_cents": self.e.bank.deposits(bid),
                "reserves_cents": self.e.bank.reserves(bid),
                "outstanding_loans_cents": self.e.bank.outstanding_loans(bid),
                "reserve_ratio": self.e.bank.reserve_ratio(bid),
            })
        return summary

    def read_order_book(self, firm_id: Optional[int] = None,
                        depth: int = 10) -> list[dict]:
        cap = self._bounded_limit(depth, 20)
        params: list[Any] = []
        where = "status IN ('open','partial')"
        if firm_id is not None:
            fid = int(firm_id)
            if not self.store.query_one("SELECT 1 FROM firms WHERE id=?", (fid,)):
                raise OracleToolError("firm not found")
            where += " AND firm_id=?"
            params.append(fid)
        rows = self.store.query(
            "SELECT id,firm_id,side,order_type,qty_remaining,limit_price_cents,seq "
            "FROM orders WHERE " + where + " AND side='buy' "
            "ORDER BY limit_price_cents DESC,seq ASC LIMIT ?",
            [*params, cap])
        sells = self.store.query(
            "SELECT id,firm_id,side,order_type,qty_remaining,limit_price_cents,seq "
            "FROM orders WHERE " + where + " AND side='sell' "
            "ORDER BY limit_price_cents ASC,seq ASC LIMIT ?",
            [*params, cap])
        return [dict(row) for row in rows + sells]
