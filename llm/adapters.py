"""Provider adapters. One interface, several implementations (TECH-SPEC §8).

- `scripted`  : NOT a network call. A deterministic, policy-driven decider that
                lets the whole world run free and reproducibly (the spec mandates
                scripted agents before any LLM — build order step 1). Policies are
                injected by the agent runtime to avoid an llm→agents import cycle.
- `mock`      : returns a canned valid JSON envelope; exercises the real parsing
                path without an API key.
- `openai_compat`: Kimi (Moonshot) + MiniMax + OpenRouter/vLLM/Ollama — all speak
                the OpenAI wire format.
- `anthropic` : optional tier if an Anthropic key is present.
- `cli`       : wraps `claude -p --output-format json`; HARD-restricted to
                purpose in {oracle_plan, oracle, dev}. Raises if a swarm role is
                routed to it.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional


@dataclass
class AdapterResult:
    text: str
    in_tokens: int = 0
    out_tokens: int = 0
    cached_in_tokens: int = 0
    raw: dict = field(default_factory=dict)


class AdapterHTTPError(RuntimeError):
    """HTTP failure with machine-readable retry metadata for the gateway."""

    def __init__(self, status_code: int, endpoint: str, detail: str, *,
                 retry_after_s: Optional[float] = None):
        self.status_code = int(status_code)
        self.endpoint = endpoint
        self.detail = detail[:500]
        self.retry_after_s = retry_after_s
        super().__init__(f"HTTP {self.status_code} from {endpoint}: {self.detail}")

    @property
    def rate_limited(self) -> bool:
        # MiniMax uses the non-standard 529 status for an explicitly overloaded
        # provider cluster. Operationally it is the same transient throughput
        # condition as 429: wait provider-wide until capacity returns instead of
        # pausing an unattended production run.
        return self.status_code in {429, 529}


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _raise_http_error(resp, endpoint: str, exc: Exception) -> None:
    detail = resp.text.strip().replace("\n", " ")[:500]
    raise AdapterHTTPError(
        resp.status_code, endpoint, detail,
        retry_after_s=_retry_after_seconds(resp.headers.get("Retry-After"))) from exc


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Adapter:
    name = "base"

    async def complete(self, model: str, messages: list[dict], *, purpose: str = "",
                       context: Optional[dict] = None, max_tokens: int = 700,
                       temperature: float = 0.7, cache_key: str = "") -> AdapterResult:
        raise NotImplementedError

    async def healthcheck(self, model: str) -> dict:
        return {"ok": True, "model": model, "live": False}


# ─────────────────────────────────────────────────────────────────────────────
# Scripted: deterministic policy decider (default provider for offline runs)
# ─────────────────────────────────────────────────────────────────────────────
class ScriptedAdapter(Adapter):
    name = "scripted"

    def __init__(self):
        # purpose -> callable(context) -> dict (already-valid decision envelope)
        self.policies: dict[str, Callable[[dict], dict]] = {}

    def register(self, purpose: str, fn: Callable[[dict], dict]) -> None:
        self.policies[purpose] = fn

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        fn = self.policies.get(purpose)
        context = context or {}
        if fn is None:
            payload = {"reasoning": "no scripted policy", "actions": [{"type": "do_nothing"}]}
        else:
            payload = fn(context)
        text = json.dumps(payload)
        # Approximate token accounting from the assembled prompt for realistic logs.
        in_tok = sum(estimate_tokens(m.get("content", "")) for m in messages) or estimate_tokens(str(context))
        return AdapterResult(text=text, in_tokens=in_tok, out_tokens=estimate_tokens(text),
                             raw={"scripted": True})


class MockAdapter(Adapter):
    name = "mock"

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        payload = {"reasoning": "mock response", "actions": [{"type": "do_nothing"}]}
        text = json.dumps(payload)
        in_tok = sum(estimate_tokens(m.get("content", "")) for m in messages)
        return AdapterResult(text=text, in_tokens=in_tok, out_tokens=estimate_tokens(text),
                             raw={"mock": True})


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible (Kimi / MiniMax / OpenRouter / vLLM / Ollama)
# ─────────────────────────────────────────────────────────────────────────────
class OpenAICompatAdapter(Adapter):
    name = "openai_compat"

    def __init__(self, config: dict):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.api_key_env = str(config.get("api_key_env", ""))
        self.api_key = os.environ.get(self.api_key_env, "")
        self.timeout = float(config.get("timeout_s", 60.0))
        self.healthcheck_path = str(config.get("healthcheck_path", "/models"))
        self.max_tokens_field = str(config.get("max_tokens_field", "max_tokens"))
        self.request_defaults = dict(config.get("request_defaults", {}) or {})
        self.prompt_cache_key = bool(config.get("prompt_cache_key", False))

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": model, "messages": messages,
            "temperature": temperature, "response_format": {"type": "json_object"},
        }
        body[self.max_tokens_field] = max_tokens
        body.update(self.request_defaults)
        if self.prompt_cache_key and cache_key:
            body["prompt_cache_key"] = cache_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            endpoint = f"{self.base_url}/chat/completions"
            resp = await client.post(endpoint, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                _raise_http_error(resp, self.base_url, exc)
            data = resp.json()
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            text = "".join(
                str(part.get("text", "")) for part in content
                if isinstance(part, dict))
        else:
            text = str(content or "")
        usage = data.get("usage", {})
        details = usage.get("prompt_tokens_details", {}) or {}
        cached_in = int(details.get("cached_tokens", 0) or usage.get("cache_read_input_tokens", 0) or 0)
        return AdapterResult(
            text=text,
            in_tokens=int(usage.get("prompt_tokens", 0)) or sum(estimate_tokens(m["content"]) for m in messages),
            out_tokens=int(usage.get("completion_tokens", 0)) or estimate_tokens(text),
            cached_in_tokens=cached_in,
            raw=data)

    async def healthcheck(self, model: str) -> dict:
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=min(self.timeout, 15.0)) as client:
            resp = await client.get(f"{self.base_url}{self.healthcheck_path}", headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                _raise_http_error(resp, self.base_url, exc)
            data = resp.json()
        model_ids = {str(row.get("id")) for row in data.get("data", []) if isinstance(row, dict)}
        return {"ok": model in model_ids, "model": model, "model_available": model in model_ids,
                "live": True, "models_returned": len(model_ids)}


class AnthropicAdapter(Adapter):
    name = "anthropic"

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", *, timeout: float = 60.0):
        self.api_key = os.environ.get(api_key_env, "")
        self.timeout = timeout

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        import httpx
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {"model": model, "system": system, "messages": convo,
                "max_tokens": max_tokens, "temperature": temperature}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            endpoint = "https://api.anthropic.com/v1/messages"
            resp = await client.post(endpoint, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                _raise_http_error(resp, endpoint, exc)
            data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage", {})
        cached_in = int(usage.get("cache_read_input_tokens", 0) or 0)
        return AdapterResult(text=text, in_tokens=int(usage.get("input_tokens", 0)) + cached_in,
                             out_tokens=int(usage.get("output_tokens", 0)),
                             cached_in_tokens=cached_in, raw=data)


class CLIAdapter(Adapter):
    """Wraps the Claude CLI in headless mode. Restricted to Oracle/dev use only."""
    name = "cli"
    ALLOWED_PURPOSES = {"oracle", "oracle_plan", "dev"}

    def __init__(self, command: str = "claude"):
        self.command = command

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        if purpose not in self.ALLOWED_PURPOSES:
            raise PermissionError(
                f"CLI adapter is restricted to {self.ALLOWED_PURPOSES}; refused purpose='{purpose}'. "
                "Consumer subscriptions may not back the agent swarm (TECH-SPEC §8).")
        prompt = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages)
        proc = await asyncio.create_subprocess_exec(
            self.command, "-p", prompt, "--output-format", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            proc.kill()
            await proc.wait()
            raise
        out = stdout.decode("utf-8", errors="replace").strip()
        error_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode:
            detail = error_text or "no stderr output"
            raise RuntimeError(
                f"CLI provider exited with code {proc.returncode}: {detail[:500]}")
        try:
            parsed = json.loads(out)
            text = parsed.get("result", out)
        except json.JSONDecodeError:
            text = out
        return AdapterResult(text=text, in_tokens=estimate_tokens(prompt),
                             out_tokens=estimate_tokens(text), raw={"stderr": error_text})

    async def healthcheck(self, model: str) -> dict:
        return {"ok": shutil.which(self.command) is not None, "model": model, "live": True}


# Default provider registry factory ------------------------------------------------
def build_adapters(config: dict) -> dict[str, Adapter]:
    providers = config.get("providers", {})
    adapters: dict[str, Adapter] = {
        "scripted": ScriptedAdapter(),
        "mock": MockAdapter(),
    }
    for pname, pcfg in providers.items():
        kind = pcfg.get("kind")
        if kind == "openai_compat":
            adapters[pname] = OpenAICompatAdapter(pcfg)
        elif kind == "anthropic":
            adapters[pname] = AnthropicAdapter(pcfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        elif kind == "cli":
            adapters[pname] = CLIAdapter(pcfg.get("command", "claude"))
    return adapters
