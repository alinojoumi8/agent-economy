"""Durable, shared reservations for prospective live research completions.

Each adapter invocation reserves a physical call and its declared token/cost
ceiling before transport. Missing responses and interrupted processes retain
that reservation. Prices are operator declarations, not verified invoices.
No prompts, response bodies, credentials or raw provider errors are stored.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from pathlib import Path
import os
import sqlite3
from typing import Annotated, Any, Literal
import uuid

from pydantic import Field, model_serializer, model_validator

from llm.adapters import Adapter, AdapterResult
from llm.completion_guard import BudgetExceeded
from research.artifacts import digest_json
from research.contracts import Contract, Digest

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")]
PositiveTokens = Annotated[int, Field(ge=1, le=10_000_000)]
TokenPrice = Annotated[int, Field(ge=0, le=1_000_000_000)]


class TokenTariff(Contract):
    provider: Identifier
    model: Identifier
    max_input_tokens: PositiveTokens
    max_output_tokens: PositiveTokens
    input_nano_usd_per_token: TokenPrice
    output_nano_usd_per_token: TokenPrice

    @model_validator(mode="after")
    def declared_price(self):
        if not (self.input_nano_usd_per_token or self.output_nano_usd_per_token):
            raise ValueError("declare a positive price for each live target")
        if self.provider in {"scripted", "mock"}:
            raise ValueError("offline adapters do not use live reservations")
        return self


class GatewayTarget(Contract):
    provider: Identifier
    model: Identifier


class GatewayBinding(Contract):
    key: Identifier
    config_sha256: Digest
    targets: tuple[GatewayTarget, ...]


class ProviderBudgetContract(Contract):
    protocol_version: Literal["research-provider-budget-v1", "research-provider-budget-v2"]
    study_manifest_sha256: Digest
    gateway_config_sha256: Digest | None = None
    gateway_bindings: tuple[GatewayBinding, ...] | None = None
    max_provider_calls: Annotated[int, Field(ge=1, le=1_000_000)]
    max_tokens: Annotated[int, Field(ge=1, le=1_000_000_000_000)]
    max_spend_nano_usd: Annotated[int, Field(ge=1, le=1_000_000_000_000_000)]
    tariffs: tuple[TokenTariff, ...]

    @model_serializer(mode="wrap")
    def serialized_contract(self, handler):
        value = handler(self)
        if self.gateway_bindings is None:
            value.pop("gateway_bindings", None)
        if self.gateway_config_sha256 is None:
            value.pop("gateway_config_sha256", None)
        return value

    @model_validator(mode="after")
    def distinct_targets(self):
        targets = [(item.provider, item.model) for item in self.tariffs]
        if not targets or len(targets) > 32 or len(set(targets)) != len(targets):
            raise ValueError("declare between one and 32 distinct provider/model tariffs")
        if self.protocol_version == "research-provider-budget-v1":
            if self.gateway_config_sha256 is None or self.gateway_bindings is not None:
                raise ValueError("v1 budgets require exactly one gateway configuration")
        else:
            if self.gateway_config_sha256 is not None or not self.gateway_bindings or len(self.gateway_bindings) > 16:
                raise ValueError("v2 budgets require one to sixteen named gateway bindings")
            keys = [item.key for item in self.gateway_bindings]
            if len(set(keys)) != len(keys):
                raise ValueError("gateway binding names must be distinct")
            assigned = set()
            for item in self.gateway_bindings:
                configured = [(target.provider, target.model) for target in item.targets]
                if len(configured) != len(set(configured)):
                    raise ValueError("gateway targets must be distinct within each binding")
                assigned.update(configured)
            if assigned != set(targets):
                raise ValueError("gateway bindings must cover exactly the declared tariffs")
        return self


def gateway_config_identity(config: dict) -> str:
    """Bind endpoints, routing, sampling and governor settings without copying keys."""
    return digest_json({"llm": config.get("llm", {}), "budget": config.get("budget", {})})


class BudgetLedgerError(BudgetExceeded):
    """Missing, incompatible or unreadable accounting must stop dispatch."""


_SCHEMA = """
CREATE TABLE budget_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), json TEXT NOT NULL);
CREATE TABLE reservations (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','settled','unknown','breached')),
    reserved_input INTEGER NOT NULL CHECK(reserved_input>0),
    reserved_output INTEGER NOT NULL CHECK(reserved_output>0),
    reserved_cost INTEGER NOT NULL CHECK(reserved_cost>=0),
    input_tokens INTEGER CHECK(input_tokens>=0), output_tokens INTEGER CHECK(output_tokens>=0),
    usage_cost INTEGER CHECK(usage_cost>=0),
    reason TEXT CHECK(reason IN ('no_response','missing_usage','invalid_usage','usage_exceeds_reservation')),
    CHECK(state<>'settled' OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND usage_cost IS NOT NULL))
);
"""


class ProviderBudget:
    """One existing ledger shared by preflight, cells, retries and later processes.

    Opening never creates or replenishes a ledger. A fresh budget requires an
    explicit exclusive create and a new prospective study identity.
    """

    def __init__(self, path: Path, contract: ProviderBudgetContract, *, scope: str,
                 binding_key: str | None = None, read_only: bool = False):
        self._validate_scope(scope)
        self.path = path.absolute()
        self.scope = scope
        self.read_only = read_only
        self.contract = ProviderBudgetContract.model_validate_json(contract.model_dump_json())
        self._contract_json = self.contract.model_dump_json()
        self._tariffs = {(item.provider, item.model): item for item in self.contract.tariffs}
        self.binding_key = binding_key
        if self.contract.gateway_bindings is None:
            if binding_key is not None:
                raise ValueError("a v1 provider budget cannot select a named binding")
            self._config_sha256 = self.contract.gateway_config_sha256
            self._allowed_targets = set(self._tariffs)
        else:
            binding = next((item for item in self.contract.gateway_bindings if item.key == binding_key), None)
            if binding is None:
                raise ValueError("select the gateway binding assigned to this execution")
            self._config_sha256 = binding.config_sha256
            self._allowed_targets = {(item.provider, item.model) for item in binding.targets}
        try:
            stat = self.path.stat()
            if self.path.resolve() != self.path or not self.path.is_file() or stat.st_nlink != 1:
                raise ValueError("budget ledger must be an unaliased regular file")
            self._file_identity = (stat.st_dev, stat.st_ino)
            self.snapshot()
        except (OSError, ValueError) as exc:
            raise BudgetLedgerError("provider budget ledger is unavailable") from exc

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if not isinstance(scope, str) or not scope or len(scope) > 128 or not all(
                char.isascii() and (char.isalnum() or char in "_.-") for char in scope):
            raise ValueError("scope must be a bounded opaque execution identifier")

    @classmethod
    def create(cls, path: Path, contract: ProviderBudgetContract, *, scope: str,
               binding_key: str | None = None) -> ProviderBudget:
        # Validate before creating any artifact. Never replace an old allowance.
        cls._validate_scope(scope)
        contract = ProviderBudgetContract.model_validate_json(contract.model_dump_json())
        if (contract.gateway_bindings is None and binding_key is not None
                or contract.gateway_bindings is not None and binding_key not in {item.key for item in contract.gateway_bindings}):
            raise ValueError("select the gateway binding assigned to this execution")
        path = path.absolute()
        if path.parent.resolve() != path.parent:
            raise ValueError("provider budget parent must be unaliased")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(_SCHEMA)
            if contract.gateway_bindings is not None:
                conn.execute("ALTER TABLE reservations ADD COLUMN binding_key TEXT NOT NULL")
                conn.execute("CREATE TABLE budget_status (singleton INTEGER PRIMARY KEY CHECK(singleton=1), sealed INTEGER NOT NULL CHECK(sealed IN (0,1)))")
                conn.execute("INSERT INTO budget_status VALUES (1,0)")
            conn.execute("INSERT INTO budget_contract VALUES (1,?)", (contract.model_dump_json(),))
            conn.commit()
        return cls(path, contract, scope=scope, binding_key=binding_key)

    @contextmanager
    def _transaction(self):
        conn = None
        try:
            stat = self.path.stat()
            if (stat.st_dev, stat.st_ino) != self._file_identity or stat.st_nlink != 1 or self.path.resolve() != self.path:
                raise BudgetLedgerError("provider budget file identity changed")
            conn = sqlite3.connect(self.path.as_uri() + ("?mode=ro" if self.read_only else "?mode=rw"), uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN" if self.read_only else "BEGIN IMMEDIATE")
            row = conn.execute("SELECT json FROM budget_contract WHERE singleton=1").fetchone()
            if row is None or row[0] != self._contract_json:
                raise BudgetLedgerError("provider budget contract changed")
            yield conn
            conn.commit()
        except (OSError, sqlite3.Error, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BudgetLedgerError("provider budget accounting is unavailable") from exc
        finally:
            if conn is not None:
                conn.close()  # Rolls back a failed reservation; no transport ran.

    @staticmethod
    def _totals(conn: sqlite3.Connection, scope: str | None = None) -> dict:
        totals = dict.fromkeys(("provider_calls", "encumbered_tokens", "encumbered_nano_usd",
            "reported_tokens", "usage_cost_nano_usd", "unresolved_calls", "unknown_usage_calls", "breached_calls"), 0)
        # Python integers preserve exact totals even if multiple in-flight
        # providers simultaneously return extreme usage that breaches the cap.
        # SQLite SUM can overflow before the supervisor can report that evidence.
        query = "SELECT state,reserved_input,reserved_output,reserved_cost,input_tokens,output_tokens,usage_cost FROM reservations"
        query += " WHERE scope=?" if scope is not None else ""
        for row in conn.execute(query, (scope,) if scope is not None else ()):
            tokens = (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
            cost = row["usage_cost"] or 0
            totals["provider_calls"] += 1
            totals["reported_tokens"] += tokens
            totals["usage_cost_nano_usd"] += cost
            totals["unresolved_calls"] += row["state"] == "reserved"
            totals["unknown_usage_calls"] += row["state"] == "unknown"
            totals["breached_calls"] += row["state"] == "breached"
            if row["state"] != "settled":
                tokens = max(tokens, row["reserved_input"] + row["reserved_output"])
                cost = max(cost, row["reserved_cost"])
            totals["encumbered_tokens"] += tokens
            totals["encumbered_nano_usd"] += cost
        return totals

    def snapshot(self, *, scope: str | None = None) -> dict:
        with self._transaction() as conn:
            return {"contract_sha256": digest_json(self.contract.model_dump(mode="json")),
                    **self._totals(conn, scope)}

    def scope_bindings(self) -> dict[str, list[str]]:
        """Expose only opaque accounting ownership for independent verification."""
        if self.contract.gateway_bindings is None:
            raise ValueError("scope bindings require the v2 budget contract")
        with self._transaction() as conn:
            scopes = {}
            bindings = {binding.key: {(target.provider, target.model) for target in binding.targets}
                        for binding in self.contract.gateway_bindings}
            for row in conn.execute("SELECT DISTINCT scope,binding_key,provider,model FROM reservations ORDER BY scope,binding_key"):
                if (row["provider"], row["model"]) not in bindings.get(row["binding_key"], set()):
                    raise BudgetLedgerError("provider reservation leaves its gateway binding")
                keys = scopes.setdefault(row["scope"], [])
                if row["binding_key"] not in keys:
                    keys.append(row["binding_key"])
            return scopes

    def is_sealed(self) -> bool:
        if self.contract.gateway_bindings is None:
            return False
        with self._transaction() as conn:
            row = conn.execute("SELECT sealed FROM budget_status WHERE singleton=1").fetchone()
            if row is None:
                raise BudgetLedgerError("provider budget disposition is missing")
            return bool(row[0])

    def seal(self) -> dict:
        """Close a supervised v2 allowance before freezing its final evidence."""
        if self.contract.gateway_bindings is None:
            raise ValueError("sealing requires an explicitly supervised v2 budget")
        with self._transaction() as conn:
            row = conn.execute("SELECT sealed FROM budget_status WHERE singleton=1").fetchone()
            if row is None:
                raise BudgetLedgerError("provider budget disposition is missing")
            if row[0] == 0:
                conn.execute("UPDATE budget_status SET sealed=1 WHERE singleton=1")
            return {"contract_sha256": digest_json(self.contract.model_dump(mode="json")),
                    **self._totals(conn), "sealed": True}

    def _require_open(self, conn: sqlite3.Connection) -> None:
        if self.contract.gateway_bindings is not None:
            row = conn.execute("SELECT sealed FROM budget_status WHERE singleton=1").fetchone()
            if row is None or row[0] != 0:
                raise BudgetLedgerError("provider budget is sealed or has no open disposition")

    def validate_config(self, config: dict) -> None:
        if gateway_config_identity(config) != self._config_sha256:
            raise BudgetLedgerError("gateway configuration differs from the provider budget")
        providers = config.get("llm", {}).get("providers", {})
        if {"scripted", "mock"}.intersection(providers):
            raise BudgetLedgerError("offline adapter names cannot be overridden in a budgeted gateway")
        for target in self._allowed_targets:
            tariff = self._tariffs[target]
            provider = providers.get(tariff.provider, {})
            if provider.get("kind") not in {"openai_compat", "anthropic"}:
                raise BudgetLedgerError("research completion budgets require a direct HTTP adapter")
            if provider.get("kind") == "openai_compat" and (
                    provider.get("request_defaults")
                    or provider.get("max_tokens_field", "max_tokens") not in {"max_tokens", "max_completion_tokens"}):
                raise BudgetLedgerError("research adapter extras can change the declared request or token ceiling")
        self.snapshot()

    def _reserve(self, provider: str, model: str, messages: list[dict], kwargs: dict) -> str:
        if (provider, model) not in self._allowed_targets:
            raise BudgetExceeded("provider/model is not assigned to this gateway binding")
        tariff = self._tariffs.get((provider, model))
        if tariff is None:
            raise BudgetExceeded("provider/model has no declared research tariff")
        output = kwargs.get("max_tokens")
        if type(output) is not int or not 1 <= output <= tariff.max_output_tokens:
            raise BudgetExceeded("requested output exceeds the declared research token ceiling")
        # A bounded text-only admission heuristic, not a claim about a remote
        # tokenizer. Reserve the entire declared input ceiling, not this estimate.
        if (not isinstance(messages, list) or not messages or len(messages) > 64
                or any(not isinstance(message, dict) or set(message) != {"role", "content"}
                       or message["role"] not in {"system", "user", "assistant"}
                       or not isinstance(message["content"], str) for message in messages)):
            raise BudgetExceeded("research reservations require bounded text messages")
        prompt_bound = sum(len(message["content"].encode("utf-8")) + 512 for message in messages)
        if prompt_bound > tariff.max_input_tokens:
            raise BudgetExceeded("prompt exceeds the declared research input allowance")
        purpose = kwargs.get("purpose")
        if (not isinstance(purpose, str) or not purpose or len(purpose) > 64
                or not all(char.isascii() and (char.isalnum() or char == "_") for char in purpose)):
            raise BudgetExceeded("research completion purpose must be a bounded identifier")
        tokens = tariff.max_input_tokens + output
        cost = tariff.max_input_tokens * tariff.input_nano_usd_per_token + output * tariff.output_nano_usd_per_token
        reservation = uuid.uuid4().hex
        with self._transaction() as conn:
            self._require_open(conn)
            totals = self._totals(conn)
            if totals["breached_calls"]:
                raise BudgetExceeded("provider usage breached its declaration; study dispatch is stopped")
            for field, amount, cap in (
                ("provider_calls", 1, self.contract.max_provider_calls),
                ("encumbered_tokens", tokens, self.contract.max_tokens),
                ("encumbered_nano_usd", cost, self.contract.max_spend_nano_usd),
            ):
                if totals[field] + amount > cap:
                    raise BudgetExceeded(f"research provider budget exhausted: {field}")
            columns = "id,scope,provider,model,purpose,state,reserved_input,reserved_output,reserved_cost"
            values = (reservation, self.scope, provider, model, purpose, "reserved", tariff.max_input_tokens, output, cost)
            if self.binding_key is not None:
                columns += ",binding_key"
                values += (self.binding_key,)
            conn.execute(f"INSERT INTO reservations ({columns}) VALUES ({','.join('?' for _ in values)})", values)
        return reservation

    def _finish(self, reservation: str, result: AdapterResult | None) -> None:
        breach = False
        with self._transaction() as conn:
            self._require_open(conn)
            row = conn.execute("SELECT * FROM reservations WHERE id=? AND state='reserved'", (reservation,)).fetchone()
            if row is None:
                raise BudgetLedgerError("provider reservation is missing or already settled")
            if row["scope"] != self.scope or self.binding_key is not None and row["binding_key"] != self.binding_key:
                raise BudgetLedgerError("provider reservation belongs to another execution binding")
            tariff = self._tariffs[(row["provider"], row["model"])]
            state, reason = "unknown", "no_response"
            input_tokens = output_tokens = cost = None
            if result is not None and result.reported_usage is None:
                reason = "missing_usage"
            elif result is not None:
                values = result.reported_usage
                if (not isinstance(values, tuple) or len(values) != 2
                        or any(type(value) is not int or not 0 <= value <= 2**31 - 1 for value in values)):
                    state, reason, breach = "breached", "invalid_usage", True
                else:
                    input_tokens, output_tokens = values
                    # Charge cached input at the declared upper input tariff.
                    # Discounts and external invoices are separate evidence.
                    cost = input_tokens * tariff.input_nano_usd_per_token + output_tokens * tariff.output_nano_usd_per_token
                    if input_tokens > row["reserved_input"] or output_tokens > row["reserved_output"]:
                        state, reason, breach = "breached", "usage_exceeds_reservation", True
                    elif not input_tokens:
                        state, reason = "unknown", "missing_usage"
                        input_tokens = output_tokens = cost = None
                    else:
                        state, reason = "settled", None
            conn.execute("""UPDATE reservations SET state=?,reason=?,input_tokens=?,output_tokens=?,usage_cost=?
                WHERE id=?""", (state, reason, input_tokens, output_tokens, cost, reservation))
        if breach:
            raise BudgetExceeded("provider reported usage outside its reservation; study dispatch is stopped")

    async def complete(self, provider: str, adapter: Adapter, model: str,
                       messages: list[dict], **kwargs: Any) -> AdapterResult:
        reservation = self._reserve(provider, model, messages, kwargs)
        try:
            result = await adapter.complete(model, messages, **kwargs)
        except BaseException:
            # Cancellation/HTTP failure/timeout is not proof that no billable
            # work occurred. A hard kill leaves 'reserved' with the same charge.
            self._finish(reservation, None)
            raise
        self._finish(reservation, result)
        return result
