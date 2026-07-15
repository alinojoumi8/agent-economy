"""Bounded read-only tools available to the Oracle analyst."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Optional

class OracleToolError(ValueError):
    pass


MAX_PROMPT_EVIDENCE_CHARS = 8_000
MAX_PROMPT_RESULT_CHARS = 700
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_oracle_json(value: Any) -> str:
    """The one wire/persistence encoding used for governed Oracle evidence."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OracleToolError(f"Oracle evidence is not canonical JSON: {exc}") from exc


def _truncation_envelope(value: Any, *, include_prefix: bool) -> dict[str, Any]:
    encoded = canonical_oracle_json(value)
    envelope: dict[str, Any] = {
        "truncated": True,
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "original_chars": len(encoded),
    }
    if include_prefix:
        envelope["json_prefix"] = encoded[:MAX_PROMPT_RESULT_CHARS]
    return envelope


def bound_oracle_evidence(value: Any) -> list[dict]:
    """Return a deterministic transcript no larger than the prompt contract.

    Tool names and arguments are never truncated. Results first receive a
    hash-bound prefix envelope; if the aggregate still exceeds the limit the
    prefix is omitted, leaving the exact three-field hash envelope.
    """
    if not isinstance(value, list):
        raise OracleToolError("Oracle evidence must be a list")
    normalized = [
        {"tool": item["tool"], "args": item["args"], "result": item["result"]}
        for item in value
    ]
    if len(canonical_oracle_json(normalized)) <= MAX_PROMPT_EVIDENCE_CHARS:
        return normalized
    bounded = [
        {
            "tool": item["tool"], "args": item["args"],
            "result": _truncation_envelope(
                item["result"], include_prefix=True),
        }
        for item in normalized
    ]
    if len(canonical_oracle_json(bounded)) <= MAX_PROMPT_EVIDENCE_CHARS:
        return bounded
    bounded = [
        {
            "tool": item["tool"], "args": item["args"],
            "result": _truncation_envelope(
                item["result"], include_prefix=False),
        }
        for item in normalized
    ]
    if len(canonical_oracle_json(bounded)) > MAX_PROMPT_EVIDENCE_CHARS:
        raise OracleToolError(
            "Oracle tool names/arguments exceed the prompt evidence bound")
    return bounded


def _valid_truncation_envelope(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("truncated") is not True:
        return False
    keys = set(value)
    if keys not in (
            {"truncated", "sha256", "original_chars"},
            {"truncated", "sha256", "original_chars", "json_prefix"}):
        return False
    digest = value.get("sha256")
    original_chars = value.get("original_chars")
    if (not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            or isinstance(original_chars, bool)
            or not isinstance(original_chars, int) or original_chars < 1):
        return False
    if "json_prefix" in value:
        prefix = value["json_prefix"]
        if (not isinstance(prefix, str)
                or len(prefix) > MAX_PROMPT_RESULT_CHARS
                or len(prefix) > original_chars):
            return False
    return True


def validate_bounded_oracle_evidence(
        value: Any, *, allowed_tools: set[str] | None = None,
        max_queries: int = 8) -> bool:
    """Validate the exact compact transcript accepted by runtime and receipts."""
    if not isinstance(value, list) or not 1 <= len(value) <= max_queries:
        return False
    for item in value:
        if (not isinstance(item, dict) or set(item) != {"tool", "args", "result"}
                or not isinstance(item.get("tool"), str)
                or (allowed_tools is not None and item["tool"] not in allowed_tools)
                or not isinstance(item.get("args"), dict)):
            return False
        try:
            validate_oracle_tool_args(item["tool"], item["args"])
        except OracleToolError:
            return False
        result = item["result"]
        if isinstance(result, dict) and result.get("truncated") is True \
                and not _valid_truncation_envelope(result):
            return False
    try:
        return len(canonical_oracle_json(value)) <= MAX_PROMPT_EVIDENCE_CHARS
    except OracleToolError:
        return False


def _plain_int(value: Any, label: str, *, minimum: int | None = None,
               maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OracleToolError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise OracleToolError(f"{label} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise OracleToolError(f"{label} must be at most {maximum}")
    return value


def validate_oracle_tool_args(name: str, args: dict[str, Any]) -> None:
    """Fail closed on unknown, extra, or weakly typed tool arguments."""
    schemas = {
        "query_metrics": {"names", "from_tick", "to_tick", "limit"},
        "read_news": {"from_tick", "to_tick", "limit"},
        "sample_conversations": {"agent_id", "from_tick", "to_tick", "limit"},
        "inspect_agent": {"agent_id"},
        "get_ledger_summary": {"entity_type", "entity_id"},
        "read_order_book": {"firm_id", "depth"},
    }
    allowed = schemas.get(name)
    if allowed is None:
        raise OracleToolError(f"unknown or non-read-only Oracle tool: {name!r}")
    if not isinstance(args, dict):
        raise OracleToolError("tool args must be an object")
    extra = set(args) - allowed
    if extra:
        raise OracleToolError(
            f"invalid arguments for {name}: unexpected "
            f"{', '.join(sorted(extra))}")
    for key in ("from_tick", "to_tick"):
        if key in args and args[key] is not None:
            _plain_int(args[key], key, minimum=0)
    if name == "query_metrics":
        names = args.get("names")
        if (not isinstance(names, list) or not 1 <= len(names) <= 10
                or any(not isinstance(item, str)
                       or not OracleTools.METRIC_NAME.fullmatch(item)
                       for item in names)):
            raise OracleToolError("names must contain 1 to 10 valid metric names")
        if "limit" in args:
            _plain_int(args["limit"], "limit", minimum=1, maximum=200)
    elif name in {"read_news", "sample_conversations"}:
        if "limit" in args:
            _plain_int(args["limit"], "limit", minimum=1, maximum=20)
        if name == "sample_conversations" and args.get("agent_id") is not None:
            _plain_int(args["agent_id"], "agent_id", minimum=1)
    elif name == "inspect_agent":
        _plain_int(args.get("agent_id"), "agent_id", minimum=1)
    elif name == "get_ledger_summary":
        entity_type = args.get("entity_type")
        if entity_type not in OracleTools.ENTITY_TYPES:
            raise OracleToolError("unsupported entity type")
        entity_id = args.get("entity_id")
        if entity_type in {"agent", "firm", "bank"}:
            _plain_int(entity_id, "entity_id", minimum=1)
        elif entity_id is not None:
            raise OracleToolError(
                "entity_id must be omitted for gov, central_bank, and system")
    elif name == "read_order_book":
        if args.get("firm_id") is not None:
            _plain_int(args["firm_id"], "firm_id", minimum=1)
        if "depth" in args:
            _plain_int(args["depth"], "depth", minimum=1, maximum=20)


def validate_oracle_plan(
        plan: Any, *, max_queries: int = 8) -> list[dict]:
    """Normalize and preflight one planner response exactly as runtime does.

    JSON values other than objects are normalized to an empty plan. The
    returned queries have passed every deterministic check that occurs before
    a read-only tool is executed. Tool-state failures remain runtime errors;
    release receipts deliberately do not treat those as independently proven
    planner rejections.
    """
    normalized = plan if isinstance(plan, dict) else {}
    queries = normalized.get("queries", [])
    if not queries:
        raise OracleToolError("at least one evidence query is required")
    if not isinstance(queries, list):
        raise OracleToolError("queries must be a list")
    if len(queries) > max_queries:
        raise OracleToolError(
            f"at most {max_queries} tool queries are allowed")
    for request in queries:
        if not isinstance(request, dict):
            raise OracleToolError("each query must be an object")
        name = str(request.get("tool", ""))
        args = request.get("args", {})
        validate_oracle_tool_args(name, args)
        from_tick = args.get("from_tick")
        to_tick = args.get("to_tick")
        if (from_tick is not None and to_tick is not None
                and from_tick > to_tick):
            raise OracleToolError("invalid tick range")
    return queries


def oracle_tool_definitions(store) -> list[dict]:
    """Canonical governed tool catalog shared by runtime and evidence audit."""
    bank_ids = [int(row["id"]) for row in store.query(
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


class OracleTools:
    MAX_QUERIES = 8
    # Backward-compatible name; the aggregate compact transcript is the limit.
    MAX_RESULT_CHARS = MAX_PROMPT_EVIDENCE_CHARS
    LEGACY_MAX_RESULT_CHARS = 20_000
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
        return oracle_tool_definitions(self.store)

    def execute_plan(self, queries: list[dict]) -> list[dict]:
        if not isinstance(queries, list):
            raise OracleToolError("queries must be a list")
        if len(queries) > self.MAX_QUERIES:
            raise OracleToolError(f"at most {self.MAX_QUERIES} tool queries are allowed")
        transcript = []
        for request in queries:
            if not isinstance(request, dict):
                raise OracleToolError("each query must be an object")
            name = str(request.get("tool", ""))
            args = request.get("args", {})
            if name not in self._tools:
                raise OracleToolError(f"unknown or non-read-only Oracle tool: {name!r}")
            validate_oracle_tool_args(name, args)
            try:
                result = self._tools[name](**args)
            except TypeError as exc:
                raise OracleToolError(
                    f"invalid arguments for {name}: {exc}") from exc
            item = {"tool": name, "args": args, "result": result}
            transcript.append(item)
        return bound_oracle_evidence(transcript)

    def execute_plan_legacy(self, queries: list[dict]) -> list[dict]:
        """Preserve the semantics 1-6/pre-hardening transcript contract."""
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
                raise OracleToolError(
                    f"unknown or non-read-only Oracle tool: {name!r}")
            if not isinstance(args, dict):
                raise OracleToolError("tool args must be an object")
            try:
                result = self._tools[name](**args)
            except TypeError as exc:
                raise OracleToolError(
                    f"invalid arguments for {name}: {exc}") from exc
            item = {"tool": name, "args": args, "result": result}
            total_chars += len(json.dumps(item, sort_keys=True))
            if total_chars > self.LEGACY_MAX_RESULT_CHARS:
                raise OracleToolError(
                    "Oracle tool transcript exceeds the bounded result size")
            transcript.append(item)
        return transcript

    @staticmethod
    def _bounded_limit(value: int, maximum: int) -> int:
        # Keep the historical tool-method coercion used by stored semantics 1-6
        # replays. Maintained semantics-7 plans are type-checked first by
        # ``validate_oracle_tool_args`` and therefore cannot reach this helper
        # with strings, floats, or booleans.
        try:
            bounded = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise OracleToolError("limit must be an integer") from exc
        if bounded < 1 or bounded > maximum:
            raise OracleToolError(f"limit must be between 1 and {maximum}")
        return bounded

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
