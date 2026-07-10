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
                purpose in {oracle, dev}. Raises if a swarm role is routed to it.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AdapterResult:
    text: str
    in_tokens: int = 0
    out_tokens: int = 0
    raw: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Adapter:
    name = "base"

    async def complete(self, model: str, messages: list[dict], *, purpose: str = "",
                       context: Optional[dict] = None, max_tokens: int = 700,
                       temperature: float = 0.7) -> AdapterResult:
        raise NotImplementedError


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
                       temperature=0.7) -> AdapterResult:
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
                       temperature=0.7) -> AdapterResult:
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

    def __init__(self, base_url: str, api_key_env: str, *, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.timeout = timeout

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7) -> AdapterResult:
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return AdapterResult(
            text=text,
            in_tokens=int(usage.get("prompt_tokens", 0)) or sum(estimate_tokens(m["content"]) for m in messages),
            out_tokens=int(usage.get("completion_tokens", 0)) or estimate_tokens(text),
            raw=data)


class AnthropicAdapter(Adapter):
    name = "anthropic"

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", *, timeout: float = 60.0):
        self.api_key = os.environ.get(api_key_env, "")
        self.timeout = timeout

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7) -> AdapterResult:
        import httpx
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {"model": model, "system": system, "messages": convo,
                "max_tokens": max_tokens, "temperature": temperature}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage", {})
        return AdapterResult(text=text, in_tokens=int(usage.get("input_tokens", 0)),
                             out_tokens=int(usage.get("output_tokens", 0)), raw=data)


class CLIAdapter(Adapter):
    """Wraps the Claude CLI in headless mode. Restricted to Oracle/dev use only."""
    name = "cli"
    ALLOWED_PURPOSES = {"oracle", "dev"}

    def __init__(self, command: str = "claude"):
        self.command = command

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7) -> AdapterResult:
        if purpose not in self.ALLOWED_PURPOSES:
            raise PermissionError(
                f"CLI adapter is restricted to {self.ALLOWED_PURPOSES}; refused purpose='{purpose}'. "
                "Consumer subscriptions may not back the agent swarm (TECH-SPEC §8).")
        prompt = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages)
        proc = subprocess.run([self.command, "-p", prompt, "--output-format", "json"],
                              capture_output=True, text=True, timeout=120)
        out = proc.stdout.strip()
        try:
            parsed = json.loads(out)
            text = parsed.get("result", out)
        except json.JSONDecodeError:
            text = out
        return AdapterResult(text=text, in_tokens=estimate_tokens(prompt),
                             out_tokens=estimate_tokens(text), raw={"stderr": proc.stderr})


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
            adapters[pname] = OpenAICompatAdapter(pcfg["base_url"], pcfg.get("api_key_env", ""))
        elif kind == "anthropic":
            adapters[pname] = AnthropicAdapter(pcfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        elif kind == "cli":
            adapters[pname] = CLIAdapter(pcfg.get("command", "claude"))
    return adapters
