"""Small, dependency-free structured operational logging helpers.

The simulation's SQLite ``events`` table is the scientific/domain audit trail.
These logs are deliberately separate: they explain process health, requests,
provider behavior, and lifecycle transitions to operators without recording
prompts, responses, credentials, or other large/private payloads.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "agent_economy"
_REDACTED = "[REDACTED]"
_SENSITIVE_PARTS = ("api_key", "authorization", "credential", "password", "secret")
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)=([^&\s]+)"),
)


def _safe_text(value: str) -> str:
    safe = value
    for pattern in _SECRET_TEXT_PATTERNS:
        safe = pattern.sub(
            (lambda match: f"{match.group(1)}={_REDACTED}"
             if match.lastindex else _REDACTED),
            safe,
        )
    return safe if len(safe) <= 500 else safe[:497] + "..."


def _safe_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if (any(part in lowered for part in _SENSITIVE_PARTS)
            or lowered == "token" or lowered.endswith("_token")):
        return _REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(key, item) for item in value]
    return _safe_value(key, str(value))


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-safe, bounded fields with credential-shaped keys redacted."""
    return {str(key): _safe_value(str(key), value) for key, value in fields.items()}


class JsonFormatter(logging.Formatter):
    """Render an operational record as one machine-readable JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event_name", record.getMessage()),
            **getattr(record, "event_fields", {}),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: str | int | None = None) -> None:
    """Configure JSON stderr and bounded file logging once."""
    configured_level = level or os.getenv("AGENT_ECONOMY_LOG_LEVEL", "INFO")
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(configured_level)
    root = logging.getLogger()
    formatter = JsonFormatter()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(configured_level)
    log_path = Path(os.getenv(
        "AGENT_ECONOMY_LOG_FILE",
        "logs/agent-economy.jsonl.log",
    )).expanduser().resolve()
    if not any(getattr(handler, "baseFilename", None) == str(log_path)
               for handler in root.handlers):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5,
            encoding="utf-8", delay=True)
        file_handler.setLevel(configured_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def log_event(logger: logging.Logger, level: int, event_name: str, **fields: Any) -> None:
    """Emit a stable event name plus safe structured context."""
    logger.log(
        level,
        event_name,
        extra={"event_name": event_name, "event_fields": safe_fields(fields)},
    )
