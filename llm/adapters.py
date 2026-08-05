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
- `cli`       : runs a configured local CLI without a shell. Legacy Claude CLI
                routes remain restricted to {oracle_plan, oracle, dev}; agent
                purposes require an explicit provider opt-in and allowlist.
"""
from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional

from .cache_config import normalize_prompt_cache_mode


def catalog_model_suggestions(
    requested: str, model_ids: set[str], *, limit: int = 3,
) -> list[str]:
    """Return bounded, catalog-derived suggestions without silently aliasing."""
    requested_key = str(requested).casefold()
    requested_version = re.search(r"\bm\d+(?:\.\d+)?\b", requested_key)

    def score(model: str) -> float:
        model_key = model.casefold()
        similarity = SequenceMatcher(None, requested_key, model_key).ratio()
        candidate_version = re.search(r"\bm\d+(?:\.\d+)?\b", model_key)
        if (
            requested_version is not None
            and candidate_version is not None
            and requested_version.group() == candidate_version.group()
        ):
            similarity += 0.5
        return similarity

    ranked = sorted(
        ((score(model), model) for model in model_ids),
        key=lambda item: (-item[0], item[1]),
    )
    return [
        model for score, model in ranked
        if score >= 0.35
    ][:max(0, int(limit))]


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


class AdapterTimeoutError(TimeoutError):
    """Provider transport exceeded its configured response deadline."""

    def __init__(self, endpoint: str, timeout_s: float):
        self.endpoint = endpoint
        self.timeout_s = float(timeout_s)
        super().__init__(
            f"provider request to {endpoint} timed out after {self.timeout_s:.1f}s")


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
        self.auth_none = str(config.get("auth", "bearer")).lower() == "none"
        self.api_key_env = str(config.get("api_key_env", ""))
        self.api_key = os.environ.get(self.api_key_env, "")
        self.timeout = float(config.get("timeout_s", 60.0))
        self.healthcheck_path = str(config.get("healthcheck_path", "/models"))
        self.max_tokens_field = str(config.get("max_tokens_field", "max_tokens"))
        self.request_defaults = dict(config.get("request_defaults", {}) or {})
        # `prompt_cache_key` is the backwards-compatible alias for profiles
        # that predate the explicit provider cache contract.
        self.prompt_cache_mode = normalize_prompt_cache_mode(
            config.get("prompt_cache_mode"),
            legacy_prompt_cache_key=bool(config.get("prompt_cache_key")))

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        import httpx
        headers = {"Content-Type": "application/json"}
        if not self.auth_none:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": model, "messages": messages,
            "temperature": temperature, "response_format": {"type": "json_object"},
        }
        body.update(self.request_defaults)
        # Provider extras are defaults; the purpose-specific gateway budget is
        # the authoritative output limit for this logical call.
        body[self.max_tokens_field] = max_tokens
        if self.prompt_cache_mode == "openai_key" and cache_key:
            body["prompt_cache_key"] = cache_key
        endpoint = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    _raise_http_error(resp, self.base_url, exc)
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(self.base_url, self.timeout) from exc
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
        headers = {}
        if not self.auth_none:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout_s = min(self.timeout, 15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(
                    f"{self.base_url}{self.healthcheck_path}", headers=headers)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    _raise_http_error(resp, self.base_url, exc)
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(self.base_url, timeout_s) from exc
        model_ids = {str(row.get("id")) for row in data.get("data", []) if isinstance(row, dict)}
        available = model in model_ids
        return {
            "ok": available,
            "model": model,
            "model_available": available,
            "live": True,
            "models_returned": len(model_ids),
            "suggested_models": (
                [] if available else catalog_model_suggestions(model, model_ids)
            ),
        }


class AnthropicAdapter(Adapter):
    name = "anthropic"

    def __init__(self, config: dict | str | None = None, *, timeout: float = 60.0):
        # Accept the historical string constructor for third-party callers.
        if isinstance(config, str):
            config = {"api_key_env": config}
        config = config or {}
        api_key_env = str(config.get("api_key_env", "ANTHROPIC_API_KEY"))
        self.api_key = os.environ.get(api_key_env, "")
        self.timeout = float(config.get("timeout_s", timeout))
        self.prompt_cache_mode = normalize_prompt_cache_mode(
            config.get("prompt_cache_mode"))

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        import httpx
        system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
        system: str | list[dict[str, Any]] = system_text
        if self.prompt_cache_mode == "anthropic_ephemeral" and system_text:
            system = [{
                "type": "text", "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }]
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {"model": model, "system": system, "messages": convo,
                "max_tokens": max_tokens, "temperature": temperature}
        endpoint = "https://api.anthropic.com/v1/messages"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    _raise_http_error(resp, endpoint, exc)
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(endpoint, self.timeout) from exc
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage", {})
        cached_in = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        return AdapterResult(text=text, in_tokens=int(usage.get("input_tokens", 0)) + cached_in + cache_write,
                             out_tokens=int(usage.get("output_tokens", 0)),
                             cached_in_tokens=cached_in, raw=data)


class CLIAdapter(Adapter):
    """Run a bounded local model CLI and normalize its structured output."""
    name = "cli"
    ALLOWED_PURPOSES = {"oracle", "oracle_plan", "dev"}

    def __init__(self, config: str | dict[str, Any] = "claude"):
        if isinstance(config, str):
            config = {"command": config}
        elif not isinstance(config, dict):
            raise TypeError("CLI adapter config must be a command string or mapping")

        self.command = os.path.expandvars(str(config.get("command", "claude")))
        raw_args = config.get("args")
        self.args = (
            [str(arg) for arg in raw_args]
            if isinstance(raw_args, list)
            else ["-p", "{prompt}", "--output-format", "json"]
        )
        self.parser = str(config.get("parser", "claude_json")).strip().lower()
        if self.parser not in {"claude_json", "grok_json", "codex_jsonl", "plain"}:
            raise ValueError(f"unsupported CLI parser '{self.parser}'")
        self.stdin_prompt = bool(config.get("stdin_prompt", False))
        self.timeout_s = max(1.0, float(config.get("timeout_s", 120.0)))
        raw_cwd = str(config.get("cwd", "")).strip()
        self.cwd = os.path.expandvars(raw_cwd) if raw_cwd else None

        raw_env = config.get("env", {}) or {}
        if not isinstance(raw_env, dict):
            raise TypeError("CLI adapter env must be a mapping")
        self.env = {
            str(key): os.path.expandvars(str(value))
            for key, value in raw_env.items()
        }

        raw_purposes = config.get("allowed_purposes")
        if raw_purposes is None:
            self.allowed_purposes = set(self.ALLOWED_PURPOSES)
        elif not isinstance(raw_purposes, list) or not all(
                isinstance(value, str) and value.strip() for value in raw_purposes):
            raise ValueError("CLI adapter allowed_purposes must be a list of strings")
        else:
            self.allowed_purposes = {value.strip() for value in raw_purposes}
        if (self.allowed_purposes - self.ALLOWED_PURPOSES
                and not bool(config.get("allow_agent_purposes", False))):
            raise ValueError(
                "CLI agent purposes require allow_agent_purposes: true")

    @staticmethod
    def _prompt(messages: list[dict]) -> str:
        return "\n\n".join(
            f"[{str(message.get('role', 'user')).upper()}]\n"
            f"{message.get('content', '')}"
            for message in messages
        )

    @staticmethod
    def _usage_value(usage: dict, *names: str) -> int:
        for name in names:
            value = usage.get(name)
            if value is not None:
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    continue
        return 0

    @classmethod
    def _usage(cls, usage: Any) -> tuple[int, int, int]:
        if not isinstance(usage, dict):
            return 0, 0, 0
        nested = [
            value for value in usage.values()
            if isinstance(value, dict)
        ]
        direct_names = {
            "input_tokens", "inputTokens", "prompt_tokens", "promptTokens",
            "output_tokens", "outputTokens", "completion_tokens",
            "completionTokens", "cached_input_tokens", "cachedInputTokens",
            "cache_read_input_tokens", "cacheReadInputTokens",
        }
        if nested and not direct_names.intersection(usage):
            totals = [cls._usage(value) for value in nested]
            return (
                sum(value[0] for value in totals),
                sum(value[1] for value in totals),
                sum(value[2] for value in totals),
            )
        in_tokens = cls._usage_value(
            usage, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens")
        out_tokens = cls._usage_value(
            usage, "output_tokens", "outputTokens",
            "completion_tokens", "completionTokens")
        cached_in_tokens = cls._usage_value(
            usage, "cached_input_tokens", "cachedInputTokens",
            "cache_read_input_tokens", "cacheReadInputTokens")
        return in_tokens, out_tokens, cached_in_tokens

    @classmethod
    def _parse_claude_json(cls, output: str) -> tuple[str, int, int, int, dict]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return output, 0, 0, 0, {}
        if not isinstance(payload, dict):
            return output, 0, 0, 0, {}
        text = payload.get("result", output)
        if not isinstance(text, str):
            text = json.dumps(text, separators=(",", ":"), ensure_ascii=False)
        in_tokens, out_tokens, cached = cls._usage(payload.get("usage", {}))
        return text, in_tokens, out_tokens, cached, {}

    @classmethod
    def _parse_grok_json(cls, output: str) -> tuple[str, int, int, int, dict]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Grok CLI did not return valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Grok CLI returned a non-object response")
        text = payload.get("text", payload.get("result", payload.get("content", "")))
        if not isinstance(text, str):
            text = json.dumps(text, separators=(",", ":"), ensure_ascii=False)
        usage_source = payload.get("usage")
        if not isinstance(usage_source, dict):
            usage_source = payload.get("modelUsage", {})
        in_tokens, out_tokens, cached = cls._usage(usage_source)
        metadata = {
            key: payload[key]
            for key in (
                "session_id", "sessionId", "request_id", "requestId",
                "stop_reason", "stopReason", "cost", "model",
            )
            if key in payload
        }
        return text, in_tokens, out_tokens, cached, metadata

    @classmethod
    def _parse_codex_jsonl(cls, output: str) -> tuple[str, int, int, int, dict]:
        final_text = ""
        thread_id: str | None = None
        usage: dict = {}
        failure = ""
        event_count = 0
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_count += 1
            event_type = str(event.get("type", ""))
            if event_type == "thread.started":
                thread_id = str(event.get("thread_id") or "") or None
            elif event_type == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    candidate = item.get("text")
                    if isinstance(candidate, str):
                        final_text = candidate
            elif event_type == "turn.completed":
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
            elif event_type in {"turn.failed", "error"}:
                detail = event.get("error", event.get("message", event_type))
                if isinstance(detail, dict):
                    detail = detail.get("message", event_type)
                failure = str(detail)[:500]
        if not final_text:
            detail = f": {failure}" if failure else ""
            raise RuntimeError(f"Codex CLI returned no final agent message{detail}")
        in_tokens, out_tokens, cached = cls._usage(usage)
        metadata: dict[str, Any] = {"event_count": event_count}
        if thread_id:
            metadata["thread_id"] = thread_id
        return final_text, in_tokens, out_tokens, cached, metadata

    def _parse_output(self, output: str) -> tuple[str, int, int, int, dict]:
        if self.parser == "claude_json":
            return self._parse_claude_json(output)
        if self.parser == "grok_json":
            return self._parse_grok_json(output)
        if self.parser == "codex_jsonl":
            return self._parse_codex_jsonl(output)
        return output, 0, 0, 0, {}

    @staticmethod
    def _render_arg(arg: str, *, prompt: str, model: str, purpose: str,
                    max_tokens: int, temperature: float) -> str:
        replacements = {
            "{prompt}": prompt,
            "{model}": str(model),
            "{purpose}": str(purpose),
            "{max_tokens}": str(max_tokens),
            "{temperature}": str(temperature),
        }
        rendered = os.path.expandvars(arg)
        for marker, value in replacements.items():
            rendered = rendered.replace(marker, value)
        return rendered

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        if purpose not in self.allowed_purposes:
            raise PermissionError(
                f"CLI adapter is restricted to {sorted(self.allowed_purposes)}; "
                f"refused purpose='{purpose}'.")
        prompt = self._prompt(messages)
        args = [
            self._render_arg(
                arg, prompt=prompt, model=model, purpose=purpose,
                max_tokens=max_tokens, temperature=temperature)
            for arg in self.args
        ]
        process_env = None
        if self.env:
            process_env = {**os.environ, **self.env}
        process_kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if self.stdin_prompt:
            process_kwargs["stdin"] = asyncio.subprocess.PIPE
        if self.cwd:
            process_kwargs["cwd"] = self.cwd
        if process_env is not None:
            process_kwargs["env"] = process_env
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            process_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = await asyncio.create_subprocess_exec(
            self.command, *args, **process_kwargs)
        try:
            input_bytes = prompt.encode("utf-8") if self.stdin_prompt else None
            communicate = (
                proc.communicate(input_bytes) if input_bytes is not None
                else proc.communicate()
            )
            stdout, stderr = await asyncio.wait_for(
                communicate, timeout=self.timeout_s)
        except asyncio.CancelledError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            raise
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            raise AdapterTimeoutError(self.command, self.timeout_s) from exc
        out = stdout.decode("utf-8", errors="replace").strip()
        error_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode:
            detail = error_text or "no stderr output"
            raise RuntimeError(
                f"CLI provider exited with code {proc.returncode}: {detail[:500]}")
        text, in_tokens, out_tokens, cached, metadata = self._parse_output(out)
        metadata["stderr"] = error_text[:500]
        return AdapterResult(
            text=text,
            in_tokens=in_tokens or estimate_tokens(prompt),
            out_tokens=out_tokens or estimate_tokens(text),
            cached_in_tokens=cached,
            raw=metadata,
        )

    async def healthcheck(self, model: str) -> dict:
        command_found = (
            os.path.isfile(self.command) if os.path.dirname(self.command)
            else shutil.which(self.command) is not None
        )
        cwd_ready = self.cwd is None or os.path.isdir(self.cwd)
        return {
            "ok": command_found and cwd_ready,
            "model": model,
            "live": True,
        }


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
            adapters[pname] = AnthropicAdapter(pcfg)
        elif kind == "cli":
            adapters[pname] = CLIAdapter(pcfg)
    return adapters
