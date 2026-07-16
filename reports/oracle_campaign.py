"""Fail-closed evaluation for the curated Oracle calibration campaign.

Unlike :func:`oracle.calibration.aggregate_calibration`, this module never
discovers databases by directory scan.  A versioned manifest must enumerate
every source run, seed, resolved profile, and immutable database hash.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from engine.ledger import Ledger
from engine.checkpoint_manifest import (
    build_checkpoint_manifest,
    canonical_json_bytes as checkpoint_manifest_bytes,
    checkpoint_manifest_path,
    finalize_sqlite_artifact as _finalize_sqlite_artifact,
    SQLiteArtifactError,
    sqlite_schema_evidence,
)
from engine.schema import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION
from engine.store import Store, load_json
from llm.gateway import (
    REPLAY_OPERATIONAL_PURPOSES,
    _logical_replay_call,
    _logical_replay_digest,
)
from oracle.calibration import calibration_from_pairs
from oracle.tools import OracleToolError, OracleTools
from oracle.tools import (
    MAX_PROMPT_EVIDENCE_CHARS,
    ORACLE_PREFLIGHT_CONTRACT,
    canonical_oracle_json,
    oracle_tool_definitions,
    validate_bounded_oracle_evidence,
    validate_oracle_plan,
    validate_oracle_tool_args,
)
from run_config import load_config
from world.replay_verify import verify_replay


SCHEMA_VERSION = 1
LATENCY_KIND = "scheduled_e2e_v1"
DEFAULT_MINIMUM_RUNS = 10
DEFAULT_MINIMUM_FORECASTS = 60
DEFAULT_P90_LIMIT_MS = 60_000
NAIVE_BRIER = 0.25
_GATEWAY_CANONICAL_NOOP = {
    "actions": [{"type": "do_nothing"}],
    "reasoning": "unparseable output; no-op",
}
RELEASE_CAMPAIGN_ID = "oracle-calibration-v8"
RELEASE_CAMPAIGN_VERSION = 8
RELEASE_SEEDS = tuple(range(7371, 7381))
RELEASE_PROFILES = {
    seed: f"v8-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml"
    for seed in RELEASE_SEEDS
}
RELEASE_ORACLE_PROVIDER = "kimi"
RELEASE_ORACLE_MODEL = "kimi-for-coding-highspeed"
RELEASE_ORACLE_ADAPTER = {
    "kind": "openai_compat",
    "base_url": "https://api.kimi.com/coding/v1",
    "api_key_env": "KIMI_API_KEY",
    "prompt_cache_mode": "off",
    "healthcheck_path": "/models",
    "max_tokens_field": "max_tokens",
    "request_defaults": {
        "max_tokens": 4096,
        "reasoning_effort": "medium",
        "temperature": 1.0,
    },
    "timeout_s": 180,
}
RELEASE_ORACLE_PRICING = {"in": 2.85, "out": 12.00, "cache": 0.57}
RELEASE_COMMITMENT_FILE = (
    Path(__file__).resolve().parents[1] / "runs" / "oracle"
    / "commitment-v8.yaml"
)
RELEASE_DATA_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "runs"
).resolve()
RELEASE_CHECKPOINT_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "checkpoints"
).resolve()
RELEASE_COMMITMENT_SHA256 = (
    "b0ef0afbc6bd39d9584a4db617ffac5943a263e5fbed4b2d7de5a7f7e0032faf"
)
RELEASE_HORIZON_TICKS = 335
RELEASE_MIN_LIVING_AGENTS = 95
RELEASE_MAX_LIVING_AGENTS = 105
RELEASE_ARRIVAL_DELAY_MIN = 5
RELEASE_ARRIVAL_DELAY_MAX = 20
RELEASE_QUESTION = "What is the probability of a bank run within 30 ticks?"
RELEASE_QUESTION_TICKS = (5, 65, 125, 185, 245, 305)
RELEASE_RULE = {"type": "bank_run", "window": 5, "deposit_drop": 0.30}


def _release_rumor_shocks() -> list[dict[str, Any]]:
    shocks: list[dict[str, Any]] = []
    for question_tick in RELEASE_QUESTION_TICKS:
        precursor_tick = question_tick - 1
        outcome_tick = question_tick + 1
        shocks.extend([
            {
                "kind": "rumor", "trigger": "shock",
                "trigger_params": {"tick": precursor_tick},
                "params": {
                    "bank_selector": "largest_by_deposits",
                    "audience": "all_citizens", "n_agents": 1,
                },
                "label": f"oracle-precursor-{precursor_tick:03d}",
            },
            {
                "kind": "rumor", "trigger": "shock",
                "trigger_params": {"tick": outcome_tick},
                "params": {
                    "bank_selector": "largest_by_deposits",
                    "audience": "current_depositors", "n_agents": 40,
                },
                "label": f"oracle-rumor-{outcome_tick:03d}",
            },
        ])
    return shocks


RELEASE_RUMOR_SHOCKS = _release_rumor_shocks()
ALLOWED_ORACLE_TOOLS = {
    "query_metrics", "read_news", "sample_conversations",
    "inspect_agent", "get_ledger_summary", "read_order_book",
}
FORBIDDEN_PERSISTED_MARKERS = (
    '"private_reasoning"', '"reasoning_content"', '"redacted_thinking"',
    '"signature"', '"thinking"', '"api_key"', '"authorization"',
)
_NON_LIVE_PROVIDERS = {"", "scripted", "mock", "local", "recorded"}
_FAILURE_EVENTS = {
    "provider_failure", "provider_pause", "budget_pause",
    "reconciliation_failure", "report_failed", "oracle_tool_execution_failed",
}


class OracleCampaignError(ValueError):
    """The campaign manifest itself is ambiguous or unsafe to evaluate."""


_CLAIM_KEYS = {
    "schema_version", "campaign_id", "campaign_version",
    "commitment_sha256", "effective_config_sha256", "profile",
    "run_id", "seed", "git_commit", "git_tree",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_clean_git_revision(repo_root: str | Path | None = None) -> dict[str, str]:
    """Return the exact clean Git commit/tree used by a live evidence claim."""
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()

    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=root, check=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise OracleCampaignError(
                f"could not attest campaign Git revision: {detail.strip()}") from exc
        return result.stdout.strip()

    dirty = git("status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise OracleCampaignError(
            "Oracle campaign execution requires a clean tracked and untracked "
            "Git worktree (ignored runtime artifacts are allowed)")
    commit = git("rev-parse", "--verify", "HEAD")
    tree = git("rev-parse", "--verify", "HEAD^{tree}")
    if not (len(commit) == len(tree) == 40 and all(
            character in "0123456789abcdef" for character in commit + tree)):
        raise OracleCampaignError("campaign Git commit/tree identity is invalid")
    return {"git_commit": commit, "git_tree": tree}


def _canonical_artifact_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
            + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    """Durably publish a directory entry where the platform permits it."""
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_publish_bytes(
        target: Path, encoded: bytes, *, allow_identical: bool = False,
        label: str = "artifact") -> bool:
    """Fsync a temporary file, then atomically publish it without clobbering.

    Returns ``True`` for a new publication and ``False`` when an already
    published byte-identical artifact was explicitly permitted.
    """
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            if (allow_identical and target.is_file()
                    and target.read_bytes() == encoded):
                return False
            raise OracleCampaignError(
                f"immutable {label} already exists with different contents: "
                f"{target}") from exc
        except OSError as exc:
            raise OracleCampaignError(
                f"could not atomically publish {label}: {exc}") from exc
        _fsync_directory(target.parent)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _publish_file_no_clobber(
        source: Path, target: Path, *, allow_identical: bool = False,
        label: str = "artifact") -> bool:
    """Atomically hard-link one same-volume file into an immutable slot."""
    source = source.resolve()
    target = target.resolve()
    if not source.is_file():
        raise OracleCampaignError(f"{label} source does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except FileExistsError as exc:
        if (allow_identical and target.is_file()
                and _sha256(source) == _sha256(target)):
            return False
        raise OracleCampaignError(
            f"immutable {label} slot already exists: {target}") from exc
    except OSError as exc:
        raise OracleCampaignError(
            f"could not atomically publish {label}: {exc}") from exc
    _fsync_directory(target.parent)
    return True


def _canonical_campaign_root(data_dir: str | Path) -> Path:
    root = Path(data_dir).resolve()
    if root != RELEASE_DATA_DIR:
        raise OracleCampaignError(
            f"release Oracle artifacts require canonical data directory "
            f"{RELEASE_DATA_DIR}")
    return root


def _claim_paths(data_dir: str | Path, run_id: str) -> tuple[Path, Path]:
    claim_dir = Path(data_dir).resolve() / "oracle-commitments"
    return (
        claim_dir / f"{run_id}.json",
        claim_dir / f"{run_id}.initialized.json",
    )


class _CampaignExecutionLock:
    """Portable advisory lock whose ownership dies with the process handle."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        try:
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write(b"\0")
                self._handle.flush()
                os.fsync(self._handle.fileno())
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(
                    self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self._handle.close()
            self._handle = None
            raise OracleCampaignError(
                "Oracle campaign execution is already active for this seed") from exc
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def oracle_campaign_execution_lock(
        claim: dict, *, data_dir: str | Path):
    """Return the exclusive per-seed lock held through source receipts."""
    root = _canonical_campaign_root(data_dir)
    run_id = str(claim.get("run_id", ""))
    seed = claim.get("seed")
    if (run_id != f"{RELEASE_CAMPAIGN_ID}-s{seed}"
            or seed not in RELEASE_SEEDS):
        raise OracleCampaignError("campaign execution lock identity is invalid")
    return _CampaignExecutionLock(
        root / "oracle-locks" / f"seed-{seed}-{run_id}.lock")


def effective_config_sha256(config: dict) -> str:
    """Hash the fully resolved configuration, independent of mapping order."""
    try:
        canonical = json.dumps(
            config, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise OracleCampaignError(
            f"effective Oracle configuration is not canonical JSON: {exc}") from exc
    return hashlib.sha256(canonical).hexdigest()


def _canonical_value_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OracleCampaignError(f"{label} must be a positive integer")
    return value


def _manifest_path(base: Path, raw: Any, label: str) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise OracleCampaignError(f"{label} must be a non-empty path")
    logical = raw.strip()
    path = Path(logical)
    if not path.is_absolute():
        path = base / path
    return path.resolve(), logical.replace("\\", "/")


def _nearest_rank(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def validate_oracle_campaign_profile(
    config: dict, *, profile_path: str | Path | None = None,
) -> None:
    """Reject profiles that are not one fixed release-campaign arm."""
    if int(config.get("engine_semantics_version", 0)) != 7:
        raise OracleCampaignError("release Oracle profiles require semantics 7")
    acceptance = config.get("acceptance", {})
    if acceptance.get("oracle_campaign_id") != RELEASE_CAMPAIGN_ID:
        raise OracleCampaignError("Oracle profile campaign_id is not the release corpus")
    if acceptance.get("oracle_campaign_version") != RELEASE_CAMPAIGN_VERSION:
        raise OracleCampaignError("Oracle profile campaign_version is invalid")
    if acceptance.get("oracle_latency_source") != LATENCY_KIND:
        raise OracleCampaignError("Oracle profile must use scheduled E2E latency")
    if int(acceptance.get("min_ticks", 0)) != RELEASE_HORIZON_TICKS:
        raise OracleCampaignError("Oracle profile must use the fixed 335-tick horizon")
    if int(acceptance.get("oracle_min_latency_samples", 0)) != 6:
        raise OracleCampaignError("Oracle profile must require all six latency samples")
    if int(acceptance.get("oracle_p90_ms", 0)) != DEFAULT_P90_LIMIT_MS:
        raise OracleCampaignError("Oracle profile must use the fixed 60000 ms p90 gate")
    questions = acceptance.get("oracle_questions")
    if not isinstance(questions, list) or [
            item.get("at_tick") for item in questions if isinstance(item, dict)
    ] != list(RELEASE_QUESTION_TICKS):
        raise OracleCampaignError("Oracle profile must contain the six fixed checkpoints")
    if any(
        item.get("campaign_key") != f"bank_run_t{int(item['at_tick']):03d}"
        or item.get("question") != RELEASE_QUESTION
        or item.get("horizon_ticks") != 30
        or item.get("expected_rule") != RELEASE_RULE
        for item in questions
    ):
        raise OracleCampaignError("Oracle profile changed the governed forecast contract")
    seed = int(config.get("seed", -1))
    if seed not in RELEASE_SEEDS:
        raise OracleCampaignError("Oracle profile seed is not in the release corpus")
    expected_shocks = RELEASE_RUMOR_SHOCKS if seed % 2 == 0 else []
    if config.get("shocks", []) != expected_shocks:
        raise OracleCampaignError("Oracle profile changed its predeclared campaign arm")
    llm = config.get("llm", {})
    routes = llm.get("routes", {})
    route = routes.get("oracle", llm.get("default_route", {}))
    if route != {
        "provider": RELEASE_ORACLE_PROVIDER, "model": RELEASE_ORACLE_MODEL,
    }:
        raise OracleCampaignError("release campaign requires the configured Kimi Oracle route")
    provider_config = llm.get("providers", {}).get(RELEASE_ORACLE_PROVIDER, {})
    if provider_config != RELEASE_ORACLE_ADAPTER:
        raise OracleCampaignError(
            "release campaign requires the official Kimi API adapter contract")
    if llm.get("pricing") != {
            RELEASE_ORACLE_MODEL: RELEASE_ORACLE_PRICING}:
        raise OracleCampaignError(
            "release campaign requires the pinned Kimi pricing contract")
    default_route = llm.get("default_route", {})
    if default_route.get("provider") != "scripted" or any(
        role != "oracle" and isinstance(value, dict)
        and value.get("provider") != "scripted"
        for role, value in routes.items()
    ):
        raise OracleCampaignError("release campaign background routes must be scripted")
    cap = config.get("budget", {}).get("cap_usd")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) \
            or not 0 < float(cap) <= 25.0:
        raise OracleCampaignError("release campaign spend cap must be in (0, 25]")
    if not bool(config.get("population", {}).get("baseline_citizens_core")):
        raise OracleCampaignError(
            "release campaign must opt baseline citizens into the active core")
    if (config.get("population", {}).get("size") != 63
            or config.get("banks", {}).get("count") != 2
            or config.get("checkpoint_every") != 10
            or config.get("checkpoint_dir") != "data/checkpoints"):
        raise OracleCampaignError(
            "release campaign changed its fixed population/bank/checkpoint design")
    lifecycle = config.get("lifecycle", {})
    if (lifecycle.get("population_mode") != "stable"
            or lifecycle.get("arrival_delay_min") != RELEASE_ARRIVAL_DELAY_MIN
            or lifecycle.get("arrival_delay_max") != RELEASE_ARRIVAL_DELAY_MAX):
        raise OracleCampaignError(
            "release campaign changed its fixed replacement-arrival schedule")
    budget = config.get("budget", {})
    if (budget.get("conversation_pairs") != 0
            or budget.get("oracle_reserve_usd") != 25
            or llm.get("concurrency") != 1):
        raise OracleCampaignError(
            "release campaign changed its isolated Oracle execution design")
    if config.get("oracle", {}).get("strict_resolution_rules") is not True:
        raise OracleCampaignError("release campaign requires strict Oracle rules")
    if config.get("information", {}).get(
            "citizen_bank_visibility") != "public_status":
        raise OracleCampaignError(
            "release campaign requires the public bank-information boundary")
    fixed_acceptance = {
        "min_agents": RELEASE_MIN_LIVING_AGENTS,
        "max_agents": RELEASE_MAX_LIVING_AGENTS,
        "required_shocks": [], "require_oracle_scoring": True,
        "require_experiment": False, "require_phenomena": False,
    }
    if any(acceptance.get(key) != value
           for key, value in fixed_acceptance.items()):
        raise OracleCampaignError(
            "release campaign changed its fixed acceptance evidence policy")
    if profile_path is not None:
        expected = (
            Path(__file__).resolve().parents[1] / "runs" / "oracle"
            / RELEASE_PROFILES.get(seed, "invalid-seed")
        ).resolve()
        if seed not in RELEASE_PROFILES or Path(profile_path).resolve() != expected:
            raise OracleCampaignError(
                "campaign execution requires one checked-in predeclared seed profile")


def load_release_campaign_commitment() -> dict:
    """Load and verify the immutable, pre-run release-corpus commitment."""
    if not RELEASE_COMMITMENT_FILE.is_file():
        raise OracleCampaignError("release Oracle commitment file is missing")
    payload = yaml.safe_load(
        RELEASE_COMMITMENT_FILE.read_text(encoding="utf-8")) or {}
    commitment_hash = _canonical_value_sha256(payload)
    if commitment_hash != RELEASE_COMMITMENT_SHA256:
        raise OracleCampaignError("release Oracle commitment hash does not match code")
    if not isinstance(payload, dict) or (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("campaign_id") != RELEASE_CAMPAIGN_ID
        or payload.get("campaign_version") != RELEASE_CAMPAIGN_VERSION
    ):
        raise OracleCampaignError("release Oracle commitment identity is invalid")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or len(raw_runs) != len(RELEASE_SEEDS):
        raise OracleCampaignError("release Oracle commitment corpus is incomplete")
    runs: dict[int, dict] = {}
    expected_keys = {
        "seed", "run_id", "profile", "effective_config_sha256",
    }
    for raw in raw_runs:
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            raise OracleCampaignError("release Oracle commitment entry is invalid")
        seed = _positive_int(raw.get("seed"), "commitment seed")
        expected_profile = RELEASE_PROFILES.get(seed)
        expected_run_id = f"{RELEASE_CAMPAIGN_ID}-s{seed}"
        if (seed in runs or expected_profile is None
                or raw.get("profile") != expected_profile
                or raw.get("run_id") != expected_run_id):
            raise OracleCampaignError(
                "release Oracle commitment changed a predeclared identity")
        profile_path = RELEASE_COMMITMENT_FILE.parent / expected_profile
        resolved = load_config(profile_path)
        validate_oracle_campaign_profile(resolved, profile_path=profile_path)
        resolved_hash = effective_config_sha256(resolved)
        if raw.get("effective_config_sha256") != resolved_hash:
            raise OracleCampaignError(
                "release Oracle commitment differs from resolved configuration")
        runs[seed] = dict(raw)
    if set(runs) != set(RELEASE_SEEDS):
        raise OracleCampaignError("release Oracle commitment seeds are incomplete")
    return {"sha256": commitment_hash, "runs": runs}


def validate_claimed_oracle_genesis(
        source_path: str | Path, claim: dict, config: dict) -> dict:
    """Validate the deterministic zero-call genesis before claim activation."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise OracleCampaignError("claimed Oracle genesis database is missing")
    if Path(f"{source}-wal").exists() or Path(f"{source}-shm").exists():
        raise OracleCampaignError(
            "claimed Oracle staging database is not a finalized standalone file")
    store: Store | None = None
    try:
        store = Store(str(source), create=False, read_only=True)
        quick = str(store.scalar("PRAGMA quick_check", default=""))
        meta = store.get_meta()
        genesis_rows = store.query(
            "SELECT tick,payload_json FROM events WHERE kind='genesis' ORDER BY id")
        genesis = (
            load_json(genesis_rows[0]["payload_json"], {})
            if len(genesis_rows) == 1 else None)
        genesis_tick_valid = bool(
            len(genesis_rows) == 1 and int(genesis_rows[0]["tick"]) == 0)
        reconciled, ledger = Ledger(store).reconcile()
        expected_genesis = {"banks": 2, "agents": 100, "firms": 14}
        if (quick.lower() != "ok"
                or str(meta["run_id"]) != str(claim.get("run_id"))
                or int(meta["seed"]) != int(claim.get("seed", -1))
                or load_json(meta["config_json"], {}) != config
                or int(meta["tick"]) != 0
                or str(meta["status"]) != "paused"
                or meta["parent_run_id"] is not None
                or meta["fork_tick"] is not None
                or int(meta["participant_influenced"] or 0) != 0
                or not _valid_semantics7_prng_state(meta["prng_state"])
                or not _valid_single_prng_state(
                    meta["lifecycle_prng_state"])
                or not genesis_tick_valid
                or genesis != expected_genesis
                or int(store.scalar(
                    "SELECT COUNT(*) FROM llm_calls", default=0)) != 0
                or int(store.scalar(
                    "SELECT COUNT(*) FROM events WHERE kind IN "
                    "('provider_failure','provider_pause','budget_pause')",
                    default=0)) != 0
                or not reconciled):
            raise OracleCampaignError(
                "claimed Oracle staging database is not a complete deterministic "
                f"zero-call genesis (quick_check={quick!r}, ledger={ledger!r})")
        return {
            "run_id": str(meta["run_id"]), "seed": int(meta["seed"]),
            "tick": int(meta["tick"]), "genesis": genesis,
            "quick_check": quick, "reconciled": reconciled,
        }
    except (OSError, sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        if isinstance(exc, OracleCampaignError):
            raise
        raise OracleCampaignError(
            f"claimed Oracle staging database is invalid: {exc}") from exc
    finally:
        if store is not None:
            store.close()


def _quarantine_pending_database(path: Path) -> Path:
    """Preserve a corrupt pre-dispatch staging file under a content name."""
    path = path.resolve()
    digest = _sha256(path) if path.is_file() else "missing"
    target = path.with_name(f".{path.stem}.rejected-{digest[:16]}.db")
    if path.is_file():
        _publish_file_no_clobber(
            path, target, allow_identical=True,
            label="rejected Oracle staging database")
        path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if not sidecar.exists():
            continue
        sidecar_target = Path(f"{target}{suffix}")
        _publish_file_no_clobber(
            sidecar, sidecar_target, allow_identical=True,
            label="rejected Oracle staging sidecar")
        sidecar.unlink()
    _fsync_directory(path.parent)
    return target


def recover_claimed_oracle_genesis(
        claim: dict, config: dict, *, data_dir: str | Path) -> Path | None:
    """Recover a published zero-call genesis without dispatch or resampling.

    A canonical pending slot is never opened for live execution. Therefore a
    valid pending file can be promoted, while an unreadable/partial pending
    file can only be a failed deterministic genesis publication and is safely
    quarantined before a deterministic rebuild.
    """
    root = _canonical_campaign_root(data_dir)
    run_id = str(claim.get("run_id", ""))
    pending = root / "oracle-pending" / f"{run_id}.db"
    final = root / f"{run_id}.db"
    if final.exists():
        if pending.exists():
            has_sidecars = any(
                Path(f"{pending}{suffix}").exists()
                for suffix in ("-wal", "-shm"))
            if not has_sidecars and _sha256(pending) == _sha256(final):
                pending.unlink()
                _fsync_directory(pending.parent)
            else:
                _quarantine_pending_database(pending)
        return final
    if not pending.exists():
        return None
    try:
        validate_claimed_oracle_genesis(pending, claim, config)
    except OracleCampaignError:
        _quarantine_pending_database(pending)
        return None
    _publish_file_no_clobber(
        pending, final, label="Oracle source database")
    pending.unlink()
    _fsync_directory(pending.parent)
    return final


def publish_claimed_oracle_genesis(
        staged_path: str | Path, claim: dict, config: dict, *,
        data_dir: str | Path) -> Path:
    """Publish a validated unique staging DB through pending and final slots."""
    root = _canonical_campaign_root(data_dir)
    staged = Path(staged_path).resolve()
    run_id = str(claim.get("run_id", ""))
    pending = root / "oracle-pending" / f"{run_id}.db"
    final = root / f"{run_id}.db"
    validate_claimed_oracle_genesis(staged, claim, config)
    recovered = recover_claimed_oracle_genesis(
        claim, config, data_dir=root)
    if recovered is not None:
        raise OracleCampaignError(
            "Oracle source slot was published while unique staging was built")
    _publish_file_no_clobber(
        staged, pending, label="Oracle pending genesis database")
    validate_claimed_oracle_genesis(pending, claim, config)
    _publish_file_no_clobber(
        pending, final, label="Oracle source database")
    pending.unlink()
    _fsync_directory(pending.parent)
    return final


def prepare_oracle_campaign_run(
    config: dict, profile_path: str | Path, *, data_dir: str | Path,
    resume_run_id: str | None = None,
) -> dict:
    """Atomically consume one precommitted stochastic sample before dispatch.

    A failed or paused run retains its claim and may only be resumed. Starting
    the same seed afresh is rejected, which prevents selecting a favorable
    result from repeated live samples.
    """
    validate_oracle_campaign_profile(config, profile_path=profile_path)
    commitment = load_release_campaign_commitment()
    seed = int(config["seed"])
    entry = commitment["runs"][seed]
    config_hash = effective_config_sha256(config)
    if config_hash != entry["effective_config_sha256"]:
        raise OracleCampaignError(
            "requested configuration differs from the pre-run commitment")
    if resume_run_id is not None and resume_run_id != entry["run_id"]:
        raise OracleCampaignError(
            "resume run_id differs from the pre-run commitment")

    root = _canonical_campaign_root(data_dir)
    claim_path, initialized_path = _claim_paths(root, entry["run_id"])
    database_path = root / f"{entry['run_id']}.db"
    revision = get_clean_git_revision()
    claim = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "commitment_sha256": commitment["sha256"],
        "effective_config_sha256": config_hash,
        "profile": entry["profile"],
        "run_id": entry["run_id"],
        "seed": seed,
        **revision,
    }
    encoded = _canonical_artifact_bytes(claim)
    claim_sha256 = hashlib.sha256(encoded).hexdigest()
    initialized = {
        "schema_version": SCHEMA_VERSION,
        "state": "initialized",
        "claim_sha256": claim_sha256,
        "run_id": entry["run_id"],
        "seed": seed,
        **revision,
    }
    initialized_encoded = _canonical_artifact_bytes(initialized)
    if resume_run_id is not None:
        if not claim_path.is_file() or claim_path.read_bytes() != encoded:
            raise OracleCampaignError(
                "resumed Oracle source has no matching immutable claim")
        initialized_matches = (
            initialized_path.is_file()
            and initialized_path.read_bytes() == initialized_encoded)
        if database_path.exists() and not initialized_matches:
            # The only permitted recovery is the fully deterministic, zero-call
            # genesis produced by the fixed staging/atomic-rename path. Any
            # partial or advanced final database remains fail closed.
            validate_claimed_oracle_genesis(database_path, claim, config)
        if not database_path.exists() and initialized_path.exists():
            raise OracleCampaignError(
                "initialized Oracle source database is missing; a fresh sample "
                "is forbidden")
        create_pending_database = not database_path.exists()
        recover_initialized_marker = bool(
            database_path.exists() and not initialized_matches)
    else:
        if database_path.exists() or initialized_path.exists():
            raise OracleCampaignError(
                "precommitted Oracle source database already exists; resume it")
        try:
            _atomic_publish_bytes(
                claim_path, encoded, label="Oracle campaign claim")
        except OracleCampaignError as exc:
            raise OracleCampaignError(
                "precommitted Oracle sample is already claimed; resume it") from exc
        create_pending_database = True
        recover_initialized_marker = False
    return {
        **claim,
        "claim_path": str(claim_path),
        "claim_sha256": claim_sha256,
        "initialized_path": str(initialized_path),
        "initialized_payload": initialized,
        "create_pending_database": create_pending_database,
        "recover_initialized_marker": recover_initialized_marker,
    }


def mark_oracle_campaign_initialized(
        claim: dict, source_path: str | Path) -> dict:
    """Atomically close the claim-before-database crash window.

    A pending claim with no DB may be initialized exactly once through an
    explicit resume. Once this marker exists, loss of the DB never authorizes
    a replacement stochastic sample.
    """
    source = Path(source_path).resolve()
    if not source.is_file():
        raise OracleCampaignError("cannot initialize an Oracle claim without its DB")
    store = Store(str(source), create=False, read_only=True)
    try:
        meta = store.get_meta()
        if (str(meta["run_id"]) != str(claim.get("run_id"))
                or int(meta["seed"]) != int(claim.get("seed", -1))
                or meta["parent_run_id"] is not None
                or meta["fork_tick"] is not None):
            raise OracleCampaignError(
                "pending Oracle database identity differs from its claim")
    finally:
        store.close()
    initialized_path = Path(str(claim["initialized_path"])).resolve()
    payload = claim.get("initialized_payload")
    if not isinstance(payload, dict):
        raise OracleCampaignError("Oracle claim has no initialized-state payload")
    encoded = _canonical_artifact_bytes(payload)
    _atomic_publish_bytes(
        initialized_path, encoded, allow_identical=True,
        label="Oracle initialized-state marker")
    return {
        "initialized_path": str(initialized_path),
        "initialized_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _claim_body(claim: dict) -> dict:
    if not isinstance(claim, dict) or not _CLAIM_KEYS.issubset(claim):
        raise OracleCampaignError("campaign claim body is incomplete")
    return {key: claim[key] for key in sorted(_CLAIM_KEYS)}


def _load_campaign_claim(
        entry: dict, *, run_id: str, seed: int,
        commitment_sha256: str, effective_config_hash: str) -> tuple[dict, list[str]]:
    reasons: list[str] = []
    expected_claim_path, expected_initialized_path = _claim_paths(
        RELEASE_DATA_DIR, run_id)
    try:
        claim_path, claim_logical = _manifest_path(
            RELEASE_DATA_DIR, entry.get("claim"), "claim")
        initialized_path, initialized_logical = _manifest_path(
            RELEASE_DATA_DIR, entry.get("initialized_claim"),
            "initialized_claim")
    except OracleCampaignError as exc:
        return {}, [str(exc)]
    if claim_path != expected_claim_path:
        reasons.append("campaign claim path is not canonical for the run")
    if initialized_path != expected_initialized_path:
        reasons.append("campaign initialized-state path is not canonical")
    expected_claim_hash = str(entry.get("claim_sha256", "")).lower()
    expected_initialized_hash = str(
        entry.get("initialized_claim_sha256", "")).lower()
    claim_hash = _sha256(claim_path) if claim_path.is_file() else None
    initialized_hash = (
        _sha256(initialized_path) if initialized_path.is_file() else None)
    if claim_hash != expected_claim_hash:
        reasons.append("campaign claim hash does not match manifest")
    if initialized_hash != expected_initialized_hash:
        reasons.append("campaign initialized-state hash does not match manifest")
    claim = None
    initialized = None
    try:
        claim = json.loads(claim_path.read_text(encoding="utf-8")) \
            if claim_path.is_file() else None
        initialized = json.loads(
            initialized_path.read_text(encoding="utf-8")) \
            if initialized_path.is_file() else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        reasons.append(f"campaign claim artifact is invalid: {exc}")
    if not isinstance(claim, dict) or set(claim) != _CLAIM_KEYS:
        reasons.append("campaign claim body is not canonical")
        claim = {}
    else:
        if claim_path.read_bytes() != _canonical_artifact_bytes(claim):
            reasons.append("campaign claim encoding is not canonical")
        expected = {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": RELEASE_CAMPAIGN_ID,
            "campaign_version": RELEASE_CAMPAIGN_VERSION,
            "commitment_sha256": commitment_sha256,
            "effective_config_sha256": effective_config_hash,
            "profile": RELEASE_PROFILES.get(seed),
            "run_id": run_id,
            "seed": seed,
            "git_commit": entry.get("git_commit"),
            "git_tree": entry.get("git_tree"),
        }
        if claim != expected:
            reasons.append("campaign claim body differs from manifest/commitment")
    expected_initialized = {
        "schema_version": SCHEMA_VERSION,
        "state": "initialized",
        "claim_sha256": claim_hash,
        "run_id": run_id,
        "seed": seed,
        "git_commit": entry.get("git_commit"),
        "git_tree": entry.get("git_tree"),
    }
    if initialized != expected_initialized:
        reasons.append("campaign initialized-state body is invalid")
    elif initialized_path.read_bytes() != _canonical_artifact_bytes(initialized):
        reasons.append("campaign initialized-state encoding is not canonical")
    return {
        "claim": claim_logical,
        "claim_sha256": claim_hash,
        "initialized_claim": initialized_logical,
        "initialized_claim_sha256": initialized_hash,
        "body": claim,
    }, reasons


def _expected_replay_tracker(source_path: Path) -> dict:
    with _private_store(source_path) as store:
        placeholders = ",".join("?" for _ in REPLAY_OPERATIONAL_PURPOSES)
        rows = store.query(
            "SELECT * FROM llm_calls WHERE COALESCE(purpose,'') NOT IN "
            f"({placeholders}) ORDER BY id",
            tuple(sorted(REPLAY_OPERATIONAL_PURPOSES)))
    records = [_logical_replay_call(row) for row in rows]
    purposes = Counter(str(row["purpose"] or "") for row in rows)
    oracle_records = [
        _logical_replay_call(row) for row in rows
        if str(row["purpose"] or "") in {"oracle_plan", "oracle"}
    ]
    return {
        "source_nonoperational_calls": len(records),
        "source_logical_calls_sha256": _logical_replay_digest(records),
        "source_purpose_counts": dict(sorted(purposes.items())),
        "oracle_source_calls": len(oracle_records),
        "oracle_source_calls_sha256": _logical_replay_digest(oracle_records),
    }


def _checkpoint_manifest_for_source(
        source_path: Path) -> tuple[dict, list[str]]:
    try:
        with _private_store(source_path) as store:
            meta = store.get_meta()
            return _checkpoint_integrity(
                store, run_id=str(meta["run_id"]), seed=int(meta["seed"]))
    except (OSError, sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        return {}, [f"source checkpoints cannot be authenticated: {exc}"]


def _load_json_artifact(
        entry: dict, *, manifest_dir: Path, path_key: str,
        hash_key: str, label: str) -> tuple[dict, Path | None, list[str]]:
    reasons: list[str] = []
    try:
        path, _logical = _manifest_path(
            manifest_dir, entry.get(path_key), path_key)
    except OracleCampaignError as exc:
        return {}, None, [str(exc)]
    expected_hash = str(entry.get(hash_key, "")).lower()
    if not path.is_file():
        return {}, path, [f"{label} does not exist"]
    if _sha256(path) != expected_hash:
        reasons.append(f"{label} hash does not match manifest")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, path, [*reasons, f"{label} is invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        reasons.append(f"{label} must be a JSON object")
        return {}, path, reasons
    if path.read_bytes() != _canonical_artifact_bytes(payload):
        reasons.append(f"{label} encoding is not canonical")
    return payload, path, reasons


def _validate_replay_execution_receipt(
        entry: dict, *, manifest_dir: Path, source: Path, replay: Path,
        profile: Path, claim_evidence: dict, proof: dict) -> tuple[dict, list[str]]:
    payload, path, reasons = _load_json_artifact(
        entry, manifest_dir=manifest_dir,
        path_key="replay_execution_receipt",
        hash_key="replay_execution_receipt_sha256",
        label="replay execution receipt")
    if not payload:
        return {}, reasons
    tracker = payload.get("replay_tracker")
    expected = _expected_replay_tracker(source)
    checkpoint_manifest, checkpoint_reasons = (
        _checkpoint_manifest_for_source(source))
    reasons.extend(checkpoint_reasons)
    required_tracker = {
        **expected,
        "consumed_source_calls": expected["source_nonoperational_calls"],
        "consumed_logical_calls_sha256": expected["source_logical_calls_sha256"],
        "consumed_purpose_counts": expected["source_purpose_counts"],
        "oracle_consumed_calls": expected["oracle_source_calls"],
        "oracle_consumed_calls_sha256": expected["oracle_source_calls_sha256"],
        "exact_key_matches": expected["source_nonoperational_calls"],
        "compatibility_fallback_matches": 0,
        "live_dispatch_count": 0,
        "missing_source_calls": 0,
        "unexpected_source_calls": 0,
        "duplicate_source_consumptions": 0,
        "all_nonoperational_calls_consumed_once": True,
        "all_oracle_calls_consumed_once": True,
    }
    if not isinstance(tracker, dict) or any(
            tracker.get(key) != value for key, value in required_tracker.items()):
        reasons.append("replay receipt tracker does not prove exact consumption")
    expected_proof = {
        key: proof.get(key) for key in (
            "exact", "source_run_id", "replay_run_id", "source_tick",
            "replay_tick", "source_hash", "replay_hash", "differences")
    }
    expected_fields = {
        "kind": "oracle_replay_execution_v1",
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_claim": claim_evidence.get("body"),
        "campaign_claim_sha256": claim_evidence.get("claim_sha256"),
        "initialized_claim_sha256": claim_evidence.get(
            "initialized_claim_sha256"),
        "git_commit": entry.get("git_commit"),
        "git_tree": entry.get("git_tree"),
        "source_database": str(source),
        "source_database_sha256": _sha256(source),
        "replay_database": str(replay),
        "replay_database_sha256": _sha256(replay),
        "profile": str(profile),
        "profile_sha256": _sha256(profile),
        "checkpoint_manifest": checkpoint_manifest,
        "checkpoint_manifest_sha256": checkpoint_manifest.get(
            "manifest_sha256"),
        "source_run_id": entry.get("run_id"),
        "source_tick": RELEASE_HORIZON_TICKS,
        "replay_tick": RELEASE_HORIZON_TICKS,
        "exact_replay": expected_proof,
        "passed": True,
    }
    for key, value in expected_fields.items():
        if payload.get(key) != value:
            reasons.append(f"replay execution receipt {key} is invalid")
    return {
        "path": str(path) if path else None,
        "sha256": _sha256(path) if path and path.is_file() else None,
        "tracker": tracker,
    }, reasons


def _validate_source_receipt(
        entry: dict, *, manifest_dir: Path) -> tuple[dict, list[str]]:
    payload, path, reasons = _load_json_artifact(
        entry, manifest_dir=manifest_dir, path_key="source_receipt",
        hash_key="source_receipt_sha256", label="source receipt")
    if not payload:
        return {}, reasons
    base_entry = {
        key: value for key, value in entry.items()
        if key not in {"source_receipt", "source_receipt_sha256"}
    }
    if (payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("campaign_id") != RELEASE_CAMPAIGN_ID
            or payload.get("campaign_version") != RELEASE_CAMPAIGN_VERSION
            or payload.get("manifest_entry") != base_entry
            or payload.get("passed") is not True):
        reasons.append("source receipt body does not bind its manifest entry")
    return {
        "path": str(path) if path else None,
        "sha256": _sha256(path) if path and path.is_file() else None,
    }, reasons


def _bounded_oracle_evidence(value: Any) -> bool:
    return validate_bounded_oracle_evidence(
        value, allowed_tools=ALLOWED_ORACLE_TOOLS,
        max_queries=OracleTools.MAX_QUERIES)


def _openai_metering_evidence(
        row: Any, response: Any) -> tuple[dict, list[str]]:
    """Reconcile one logical call with sanitized provider usage envelopes."""
    reasons: list[str] = []
    raw = response.get("raw") if isinstance(response, dict) else None
    provider_payloads: list[dict] = []
    shape = "direct"
    if isinstance(raw, dict) and raw.get("provider_calls") == 2:
        shape = "repair"
        repair = raw.get("repair")
        if isinstance(repair, dict):
            provider_payloads = [repair.get("initial"), repair.get("final")]
    elif isinstance(raw, dict) and "provider_calls" not in raw \
            and "repair" not in raw:
        provider_payloads = [raw]
    if (not provider_payloads
            or any(not isinstance(payload, dict) for payload in provider_payloads)):
        return {
            "shape": shape, "response_ids": [],
            "prompt_tokens": None, "completion_tokens": None,
            "cached_in_tokens": None, "expected_cost_usd": None,
        }, ["scheduled forecast call lacks provider response usage evidence"]

    response_ids: list[str] = []
    prompt_total = completion_total = cached_total = 0
    for payload in provider_payloads:
        response_id = payload.get("id")
        if payload.get("model") != RELEASE_ORACLE_MODEL:
            reasons.append("provider response model differs from the pinned Kimi model")
        if payload.get("object") != "chat.completion":
            reasons.append("provider response object is not a chat completion")
        usage = payload.get("usage")
        if not isinstance(response_id, str) or not response_id.strip():
            reasons.append("provider response id is missing")
        else:
            response_ids.append(response_id.strip())
        if not isinstance(usage, dict):
            reasons.append("provider response usage is missing")
            continue
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if (isinstance(prompt, bool) or not isinstance(prompt, int) or prompt <= 0
                or isinstance(completion, bool)
                or not isinstance(completion, int) or completion <= 0):
            reasons.append(
                "provider usage requires positive prompt_tokens and completion_tokens")
            continue
        details = usage.get("prompt_tokens_details")
        detailed_cached = (
            details.get("cached_tokens")
            if isinstance(details, dict) and "cached_tokens" in details else None)
        legacy_cached = usage.get("cache_read_input_tokens") \
            if "cache_read_input_tokens" in usage else None
        if (detailed_cached is not None and legacy_cached is not None
                and detailed_cached != legacy_cached):
            reasons.append("provider cached-token usage fields disagree")
            continue
        cached = detailed_cached if detailed_cached is not None else legacy_cached
        cached = 0 if cached is None else cached
        if (isinstance(cached, bool) or not isinstance(cached, int)
                or cached < 0 or cached > prompt):
            reasons.append("provider cached-token usage is invalid")
            continue
        prompt_total += prompt
        completion_total += completion
        cached_total += cached
    if len(response_ids) != len(provider_payloads) \
            or len(set(response_ids)) != len(response_ids):
        reasons.append("provider response ids are missing or duplicated")

    try:
        row_prompt = int(row["in_tokens"])
        row_completion = int(row["out_tokens"])
        recorded_cached = response.get("cached_in_tokens")
        if (isinstance(recorded_cached, bool)
                or not isinstance(recorded_cached, int)):
            raise TypeError("cached_in_tokens")
        row_cost = float(row["cost_usd"])
    except (TypeError, ValueError, OverflowError):
        reasons.append("persisted call metering fields are invalid")
        row_prompt = row_completion = recorded_cached = 0
        row_cost = -1.0
    if row_prompt != prompt_total or row_completion != completion_total:
        reasons.append("provider usage does not reconcile to persisted token totals")
    if recorded_cached != cached_total:
        reasons.append("provider usage does not reconcile to cached_in_tokens")
    noncached = max(0, prompt_total - cached_total)
    expected_cost = round(
        (noncached / 1_000_000) * RELEASE_ORACLE_PRICING["in"]
        + (cached_total / 1_000_000) * RELEASE_ORACLE_PRICING["cache"]
        + (completion_total / 1_000_000) * RELEASE_ORACLE_PRICING["out"],
        8,
    )
    if not math.isfinite(row_cost) or not math.isclose(
            row_cost, expected_cost, rel_tol=0.0, abs_tol=1e-12):
        reasons.append("persisted call cost differs from pinned Kimi pricing")
    return {
        "shape": shape,
        "response_ids": response_ids,
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "cached_in_tokens": cached_total,
        "expected_cost_usd": expected_cost,
    }, reasons


_EXPECTED_AGENT_CENSUS = {
    ("citizen", None): 65,
    ("staff", "central_banker"): 1,
    ("staff", "competition_regulator"): 1,
    ("staff", "credit_officer"): 2,
    ("staff", "editor"): 2,
    ("staff", "exchange"): 1,
    ("staff", "executive"): 1,
    ("staff", "gov_official"): 1,
    ("staff", "labor_regulator"): 1,
    ("staff", "lawyer"): 1,
    ("staff", "legislator_house"): 12,
    ("staff", "legislator_senate"): 6,
    ("staff", "lobbyist"): 2,
    ("staff", "regulator"): 1,
    ("staff", "reporter"): 2,
    ("staff", "vc_partner"): 1,
}


def _valid_single_prng_state(raw: Any) -> bool:
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != 3:
            return False
        state = (parsed[0], tuple(parsed[1]), parsed[2])
        random.Random().setstate(state)
        return True
    except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
        return False


def _valid_semantics7_prng_state(raw: Any) -> bool:
    try:
        parsed = json.loads(raw)
        return (
            isinstance(parsed, dict)
            and set(parsed) == {"engine", "persona"}
            and all(_valid_single_prng_state(json.dumps(parsed[key]))
                    for key in ("engine", "persona"))
        )
    except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
        return False


def _checkpoint_population_evidence(
        connection: sqlite3.Connection) -> dict[str, int]:
    row = connection.execute(
        "SELECT COUNT(*) AS total,"
        "SUM(CASE WHEN alive=1 THEN 1 ELSE 0 END) AS living,"
        "SUM(CASE WHEN alive=0 THEN 1 ELSE 0 END) AS deceased,"
        "SUM(CASE WHEN alive IS NULL OR alive NOT IN (0,1) "
        "THEN 1 ELSE 0 END) AS invalid FROM agents"
    ).fetchone()
    return {
        "total": int(row[0] or 0),
        "living": int(row[1] or 0),
        "deceased": int(row[2] or 0),
        "invalid": int(row[3] or 0),
    }


def _valid_release_checkpoint_population(population: dict[str, int]) -> bool:
    values = tuple(population.get(key) for key in (
        "total", "living", "deceased", "invalid"))
    return (
        all(type(value) is int and value >= 0 for value in values)
        and population.get("invalid") == 0
        and population.get("total", 0) >= 100
        and population.get("total") == (
            population.get("living", 0) + population.get("deceased", 0))
        and RELEASE_MIN_LIVING_AGENTS
        <= population.get("living", 0)
        <= RELEASE_MAX_LIVING_AGENTS
    )


def _evidence_integer(value: Any) -> int:
    if type(value) is not int:
        raise ValueError("evidence value is not an exact integer")
    return value


def _source_population_evidence(
        connection: sqlite3.Connection, *,
        horizon_tick: int = RELEASE_HORIZON_TICKS) -> dict[str, Any]:
    population = _checkpoint_population_evidence(connection)
    baseline_rows = connection.execute(
        "SELECT kind,role,COUNT(*) AS n FROM agents WHERE arrived_tick=0 "
        "GROUP BY kind,role ORDER BY kind,role"
    ).fetchall()
    baseline_census: dict[tuple[str, str | None], int] = {}
    invalid_agent_conversions = 0
    for row in baseline_rows:
        try:
            if type(row[0]) is not str or (
                    row[1] is not None and type(row[1]) is not str):
                raise ValueError("agent kind/role is not text")
            baseline_census[(row[0], row[1])] = _evidence_integer(row[2])
        except (TypeError, ValueError, OverflowError):
            invalid_agent_conversions += 1
            kind = row[0] if type(row[0]) is str else "<invalid-kind>"
            role = (row[1] if row[1] is None or type(row[1]) is str
                    else "<invalid-role>")
            try:
                count = _evidence_integer(row[2])
            except (TypeError, ValueError, OverflowError):
                count = 0
            baseline_census[(kind, role)] = (
                baseline_census.get((kind, role), 0) + count)
    arrivals: list[dict[str, Any]] = []
    deaths: list[dict[str, int]] = []
    for row in connection.execute(
            "SELECT id,arrived_tick,kind,role FROM agents "
            "WHERE arrived_tick>0 ORDER BY id").fetchall():
        try:
            if type(row[2]) is not str or (
                    row[3] is not None and type(row[3]) is not str):
                raise ValueError("agent kind/role is not text")
            arrivals.append({
                "agent_id": _evidence_integer(row[0]),
                "tick": _evidence_integer(row[1]),
                "kind": row[2],
                "role": row[3],
            })
        except (TypeError, ValueError, OverflowError):
            invalid_agent_conversions += 1
    for row in connection.execute(
            "SELECT id,died_tick FROM agents WHERE alive=0 "
            "AND died_tick IS NOT NULL ORDER BY id").fetchall():
        try:
            deaths.append({
                "agent_id": _evidence_integer(row[0]),
                "tick": _evidence_integer(row[1]),
            })
        except (TypeError, ValueError, OverflowError):
            invalid_agent_conversions += 1

    event_links: dict[str, list[tuple[int, int]]] = {
        "arrival": [], "death": [],
    }
    arrival_schedule_links: list[tuple[int, int, int]] = []
    schedules: dict[int, dict[str, int]] = {}
    invalid_event_payloads = 0
    invalid_event_envelopes = 0
    for row in connection.execute(
            "SELECT id,tick,phase,kind,subject_type,subject_id,payload_json "
            "FROM events WHERE kind IN "
            "('arrival_scheduled','arrival','death') ORDER BY tick,id").fetchall():
        try:
            event_id = _evidence_integer(row[0])
            event_tick = _evidence_integer(row[1])
            if type(row[3]) is not str:
                raise ValueError("event kind is not text")
            kind = row[3]
            payload = load_json(row[6], None)
            if event_tick < 0 or event_tick > horizon_tick:
                invalid_event_envelopes += 1
            if not isinstance(payload, dict):
                raise ValueError("invalid payload")
            if kind == "arrival_scheduled":
                due_tick = _evidence_integer(payload["due_tick"])
                schedules[event_id] = {
                    "event_id": event_id,
                    "created_tick": event_tick,
                    "due_tick": due_tick,
                }
                delay = due_tick - event_tick
                if (row[2] != "NIGHT_CLOSE" or row[4] is not None
                        or row[5] is not None
                        or not RELEASE_ARRIVAL_DELAY_MIN
                        <= delay <= RELEASE_ARRIVAL_DELAY_MAX):
                    invalid_event_envelopes += 1
                continue

            agent_id = _evidence_integer(payload["agent_id"])
            if (row[2] != "NIGHT_CLOSE" or row[4] != "agent"
                    or row[5] is None
                    or _evidence_integer(row[5]) != agent_id):
                invalid_event_envelopes += 1
            event_links[kind].append((agent_id, event_tick))
            if kind == "arrival":
                arrival_schedule_links.append((
                    agent_id, event_tick,
                    _evidence_integer(payload["schedule_event_id"])))
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_event_payloads += 1

    arrival_links = sorted(
        (item["agent_id"], item["tick"]) for item in arrivals)
    death_links = sorted(
        (item["agent_id"], item["tick"]) for item in deaths)
    invalid_agent_rows = invalid_agent_conversions + int(connection.execute(
        "SELECT COUNT(*) FROM agents WHERE arrived_tick IS NULL "
        "OR arrived_tick<0 OR arrived_tick>? "
        "OR alive IS NULL OR alive NOT IN (0,1) "
        "OR (alive=1 AND died_tick IS NOT NULL) "
        "OR (alive=0 AND died_tick IS NULL) "
        "OR died_tick>? OR (died_tick IS NOT NULL AND died_tick<arrived_tick) "
        "OR (arrived_tick>0 AND (kind!='citizen' OR role IS NOT NULL))",
        (horizon_tick, horizon_tick),
    ).fetchone()[0])
    referenced_schedules = [item[2] for item in arrival_schedule_links]
    due_schedules = sorted(
        event_id for event_id, item in schedules.items()
        if item["due_tick"] <= horizon_tick)
    schedule_links_valid = (
        len(referenced_schedules) == len(set(referenced_schedules))
        and sorted(referenced_schedules) == due_schedules
        and all(
            schedule_id in schedules
            and schedules[schedule_id]["due_tick"] == event_tick
            for _, event_tick, schedule_id in arrival_schedule_links)
        and sorted(item["tick"] for item in deaths) == sorted(
            item["created_tick"] for item in schedules.values())
    )
    event_links_valid = (
        invalid_event_payloads == 0
        and invalid_event_envelopes == 0
        and invalid_agent_rows == 0
        and arrival_links == sorted(event_links["arrival"])
        and death_links == sorted(event_links["death"])
        and schedule_links_valid
    )
    return {
        "current": population,
        "baseline_total": sum(baseline_census.values()),
        "baseline_census": baseline_census,
        "arrivals": arrivals,
        "deaths": deaths,
        "schedules": [schedules[key] for key in sorted(schedules)],
        "invalid_agent_rows": invalid_agent_rows,
        "invalid_agent_conversions": invalid_agent_conversions,
        "invalid_event_payloads": invalid_event_payloads,
        "invalid_event_envelopes": invalid_event_envelopes,
        "event_links_valid": event_links_valid,
    }


def _checkpoint_integrity(
        store: Store, *, run_id: str, seed: int) -> tuple[dict, list[str]]:
    reasons: list[str] = []
    expected_ticks = sorted({
        *range(10, RELEASE_HORIZON_TICKS, 10),
        *RELEASE_QUESTION_TICKS,
        RELEASE_HORIZON_TICKS,
    })
    rows = store.query("SELECT tick,path FROM checkpoints ORDER BY tick,id")
    ticks = [int(row["tick"]) for row in rows]
    if ticks != expected_ticks:
        reasons.append("source checkpoint ticks differ from the exact 40-tick schedule")
    source_meta = store.get_meta()
    source_schema = sqlite_schema_evidence(store.conn)
    source_config = load_json(source_meta["config_json"], None)
    if (int(source_meta["schema_version"]) != DATABASE_SCHEMA_VERSION
            or not isinstance(source_config, dict)):
        reasons.append("source schema/config cannot authenticate checkpoints")
    checked = 0
    files: list[dict] = []
    for row in rows:
        tick = int(row["tick"])
        raw = row["path"]
        if not isinstance(raw, str) or not raw.strip():
            reasons.append("source checkpoint path is invalid")
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        path = path.resolve()
        try:
            path.relative_to(RELEASE_CHECKPOINT_DIR)
        except ValueError:
            reasons.append("source checkpoint path escapes the configured directory")
            continue
        expected_path = (
            RELEASE_CHECKPOINT_DIR / f"{run_id}_t{tick}.db").resolve()
        if path != expected_path:
            reasons.append("source checkpoint path is not canonical for its run/tick")
            continue
        if (not path.is_file() or Path(f"{path}-wal").exists()
                or Path(f"{path}-shm").exists()):
            reasons.append("source checkpoint is missing or has SQLite sidecars")
            continue
        runtime_manifest_path = checkpoint_manifest_path(path)
        if not runtime_manifest_path.is_file():
            reasons.append("source checkpoint lacks its runtime-persisted manifest")
            continue
        connection: sqlite3.Connection | None = None
        checkpoint_store: Store | None = None
        try:
            persisted_manifest = json.loads(
                runtime_manifest_path.read_text(encoding="utf-8"))
            rebuilt_manifest = build_checkpoint_manifest(path)
            if (not isinstance(persisted_manifest, dict)
                    or runtime_manifest_path.read_bytes()
                    != checkpoint_manifest_bytes(persisted_manifest)
                    or persisted_manifest != rebuilt_manifest):
                reasons.append(
                    "source checkpoint runtime manifest does not match its file/state")
                continue
            uri = f"{path.as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            meta = connection.execute("SELECT * FROM run_meta WHERE id=1").fetchone()
            schema = sqlite_schema_evidence(connection)
            config = load_json(meta["config_json"], None) if meta else None
            phase_state = load_json(meta["phase_state_json"], None) if meta else None
            governor = load_json(meta["governor_json"], None) if meta else None
            core = rebuilt_manifest["core"]
            counts = core["counts"]
            population_evidence = _source_population_evidence(
                connection, horizon_tick=tick)
            population = population_evidence["current"]
            banks = [int(item["id"]) for item in connection.execute(
                "SELECT id FROM banks ORDER BY id").fetchall()]
            complete_deposit_metrics = True
            for bank_id in banks:
                metric_ticks = [int(item["tick"]) for item in connection.execute(
                    "SELECT tick FROM metrics WHERE name=? ORDER BY tick,id",
                    (f"bank_deposits:{bank_id}",)).fetchall()]
                if metric_ticks != list(range(tick + 1)):
                    complete_deposit_metrics = False
            checkpoint_store = Store(
                str(path), create=False, read_only=True)
            reconciled, ledger_evidence = Ledger(checkpoint_store).reconcile()
            if not _valid_release_checkpoint_population(population):
                reasons.append(
                    f"source checkpoint population census is invalid at tick {tick}")
                continue
            if (population_evidence["baseline_total"] != 100
                    or population_evidence["baseline_census"]
                    != _EXPECTED_AGENT_CENSUS
                    or not population_evidence["event_links_valid"]):
                reasons.append(
                    f"source checkpoint lifecycle provenance is invalid at tick {tick}")
                continue
            if (quick.lower() != "ok" or meta is None
                    or str(meta["run_id"]) != run_id
                    or int(meta["seed"]) != seed
                    or int(meta["schema_version"]) != DATABASE_SCHEMA_VERSION
                    or int(meta["tick"]) != tick
                    or config != source_config
                    or schema != source_schema
                    or meta["active_tick"] is not None
                    or str(meta["next_phase"]) != "NIGHT_CLOSE"
                    or str(meta["phase"]) != "FINALIZE"
                    or phase_state != {}
                    or not _valid_semantics7_prng_state(meta["prng_state"])
                    or not _valid_single_prng_state(
                        meta["lifecycle_prng_state"])
                    or not isinstance(governor, dict)
                    or int(meta["participant_influenced"] or 0) != 0
                    or meta["parent_run_id"] is not None
                    or meta["fork_tick"] is not None
                    or rebuilt_manifest.get("quick_check", "").lower() != "ok"
                    or rebuilt_manifest.get("database") != str(path)
                    or counts.get("firms") != 14
                    or counts.get("banks") != 2
                    or counts.get("accounts", 0) < 6
                    or counts.get("transactions", 0) < 1
                    or counts.get("ledger_entries", 0) < 2
                    or counts.get("metrics", 0) < 2 * (tick + 1)
                    or counts.get("events", 0) < 1
                    or core.get("genesis_events") != 1
                    or core.get("genesis_ticks") != [0]
                    or core.get("genesis_payloads") != [{
                        "banks": 2, "agents": 100, "firms": 14}]
                    or core.get("metric_bounds", {}).get(
                        "after_checkpoint") != 0
                    or core.get("event_bounds", {}).get(
                        "after_checkpoint") != 0
                    or core.get("metric_bounds", {}).get("maximum") != tick
                    or not complete_deposit_metrics
                    or core.get("ledger") != {
                        "account_mismatches": 0,
                        "currency_imbalances": 0,
                        "foreign_key_violations": 0,
                    }
                    or not reconciled):
                reasons.append(
                    "source checkpoint schema/state/PRNG/core/ledger binding is invalid")
                continue
            file_evidence = {
                "tick": tick,
                "path": str(path),
                "sha256": rebuilt_manifest["database_sha256"],
                "runtime_manifest": str(runtime_manifest_path),
                "runtime_manifest_sha256": _sha256(runtime_manifest_path),
                "schema_sha256": schema["sha256"],
                "state_sha256": rebuilt_manifest["state_sha256"],
                "core_sha256": rebuilt_manifest["core_sha256"],
                "population": population,
                "lifecycle": {
                    key: population_evidence[key] for key in (
                        "baseline_total", "arrivals", "deaths", "schedules",
                        "invalid_agent_rows", "invalid_agent_conversions",
                        "invalid_event_payloads",
                        "invalid_event_envelopes", "event_links_valid")
                },
                "ledger_sha256": _canonical_value_sha256(ledger_evidence),
            }
            files.append(file_evidence)
            checked += 1
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError,
                UnicodeError, json.JSONDecodeError):
            reasons.append("source checkpoint cannot be authenticated")
        finally:
            if checkpoint_store is not None:
                checkpoint_store.close()
            if connection is not None:
                connection.close()
    return {
        "expected_ticks": expected_ticks,
        "persisted_ticks": ticks,
        "validated_files": checked,
        "schema": source_schema,
        "files": files,
        "manifest_sha256": _canonical_value_sha256(files),
    }, reasons


def _bank_and_metric_integrity(
        store: Store, *, min_ticks: int) -> tuple[dict, list[str]]:
    reasons: list[str] = []
    banks = store.query(
        "SELECT id,status,currency_code,reserve_account_id,equity_account_id "
        "FROM banks ORDER BY id")
    valid_banks = 0
    bank_ids = [int(row["id"]) for row in banks]
    if len(banks) != 2:
        reasons.append("source must contain exactly two campaign banks")
    for bank in banks:
        bid = int(bank["id"])
        currency = str(bank["currency_code"] or "")
        accounts = store.query(
            "SELECT id,owner_type,owner_id,kind,currency_code FROM accounts "
            "WHERE id IN (?,?) ORDER BY id",
            (bank["reserve_account_id"], bank["equity_account_id"]))
        by_kind = {str(account["kind"]): account for account in accounts}
        valid = bool(
            str(bank["status"]) == "open" and currency == "USD"
            and set(by_kind) == {"reserve", "equity"}
            and all(
                str(account["owner_type"]) == "bank"
                and int(account["owner_id"]) == bid
                and str(account["currency_code"]) == currency
                for account in accounts))
        if valid:
            valid_banks += 1
        else:
            reasons.append(f"campaign bank {bid} account/currency identity is invalid")

    metric_rows = store.query(
        "SELECT name,tick,value FROM metrics WHERE name LIKE 'bank_deposits:%' "
        "ORDER BY name,tick,id")
    expected_names = {f"bank_deposits:{bank_id}" for bank_id in bank_ids}
    actual_names = {str(row["name"]) for row in metric_rows}
    if actual_names != expected_names:
        reasons.append("bank deposit metrics reference missing or unknown banks")
    expected_ticks = list(range(0, min_ticks + 1))
    series: dict[str, dict] = {}
    for name in sorted(expected_names):
        rows = [row for row in metric_rows if str(row["name"]) == name]
        ticks = [int(row["tick"]) for row in rows]
        valid = ticks == expected_ticks
        values: list[float] = []
        for row in rows:
            try:
                value = float(row["value"])
            except (TypeError, ValueError, OverflowError):
                valid = False
                continue
            if not math.isfinite(value) or value < 0.0:
                valid = False
            values.append(value)
        if not valid:
            reasons.append(
                f"{name} must contain one finite nonnegative sample at ticks 0..{min_ticks}")
        series[name] = {
            "samples": len(rows), "first_tick": ticks[0] if ticks else None,
            "last_tick": ticks[-1] if ticks else None,
        }
    return {
        "bank_ids": bank_ids, "valid_banks": valid_banks,
        "deposit_series": series,
    }, reasons


def _llm_call_integrity(store: Store) -> tuple[dict, list[str]]:
    """Audit every persisted call, not only rows already labelled Oracle."""
    reasons: list[str] = []
    rows = store.query(
        "SELECT id,tick,role,purpose,provider,model FROM llm_calls ORDER BY id")
    scheduled = set(RELEASE_QUESTION_TICKS)
    live_rows: list[Any] = []
    governed_rows: list[Any] = []
    invalid_live_ids: list[int] = []
    sessions: dict[int, Counter] = {
        tick: Counter() for tick in RELEASE_QUESTION_TICKS}
    for row in rows:
        provider = str(row["provider"] or "").lower()
        try:
            tick = int(row["tick"])
        except (TypeError, ValueError, OverflowError):
            tick = -1
        is_live = provider not in _NON_LIVE_PROVIDERS
        governed = bool(
            str(row["role"] or "") == "oracle"
            and str(row["purpose"] or "") in {"oracle_plan", "oracle"}
            and tick in scheduled
            and provider == RELEASE_ORACLE_PROVIDER
            and str(row["model"] or "") == RELEASE_ORACLE_MODEL)
        if is_live:
            live_rows.append(row)
        if governed:
            governed_rows.append(row)
            sessions[tick][str(row["purpose"])] += 1
        if is_live and not governed:
            invalid_live_ids.append(int(row["id"]))
    if invalid_live_ids:
        reasons.append(
            "source contains live/provider calls outside governed scheduled Oracle work")
    invalid_sessions = [
        tick for tick, counts in sessions.items()
        if counts.get("oracle", 0) != 1
        or not 1 <= counts.get("oracle_plan", 0) <= 3
        or set(counts) - {"oracle_plan", "oracle"}
    ]
    if invalid_sessions or len(sessions) != 6:
        reasons.append(
            "source does not contain six governed scheduled Oracle call sessions")
    if len(live_rows) != len(governed_rows):
        reasons.append(
            "source live-call corpus is not identical to governed Oracle calls")
    return {
        "persisted_calls": len(rows),
        "live_calls": len(live_rows),
        "governed_live_calls": len(governed_rows),
        "invalid_live_call_ids": invalid_live_ids,
        "scheduled_sessions": {
            str(tick): dict(sorted(counts.items()))
            for tick, counts in sorted(sessions.items())
        },
    }, reasons


def _source_integrity(store: Store, config: dict, min_ticks: int) -> tuple[dict, list[str]]:
    reasons: list[str] = []
    meta = store.get_meta()
    run_id = str(meta["run_id"])
    seed = int(meta["seed"])
    quick_check = str(store.scalar("PRAGMA quick_check", default=""))
    if quick_check.lower() != "ok":
        reasons.append("source SQLite quick_check failed")
    reconciled, ledger = Ledger(store).reconcile()
    if not reconciled:
        reasons.append("source ledger does not reconcile")
    acceptance = config.get("acceptance", {})
    population_evidence = _source_population_evidence(store.conn)
    population = population_evidence["current"]
    living_agents = int(population["living"])
    minimum_agents = int(acceptance.get("min_agents", 95))
    maximum_agents = int(acceptance.get("max_agents", 105))
    if not minimum_agents <= living_agents <= maximum_agents:
        reasons.append("source living population is outside its configured range")
    genesis_rows = store.query(
        "SELECT tick,payload_json FROM events WHERE kind='genesis' ORDER BY id")
    genesis = load_json(genesis_rows[0]["payload_json"], {}) \
        if len(genesis_rows) == 1 else None
    if (len(genesis_rows) != 1 or int(genesis_rows[0]["tick"]) != 0
            or genesis != {"banks": 2, "agents": 100, "firms": 14}):
        reasons.append("source genesis census is missing or differs from the fixed corpus")
    census = population_evidence["baseline_census"]
    if census != _EXPECTED_AGENT_CENSUS:
        reasons.append("source institutional agent census differs from genesis")
    if (population_evidence["baseline_total"] != 100
            or int(store.scalar("SELECT COUNT(*) FROM firms", default=0)) != 14):
        reasons.append("source genesis population/firm census changed during campaign")
    if not _valid_release_checkpoint_population(population):
        reasons.append("source current living/deceased population census is invalid")
    if not population_evidence["event_links_valid"]:
        reasons.append("source arrival/death lifecycle provenance is invalid")
    metric_count = int(store.scalar("SELECT COUNT(*) FROM metrics", default=0))
    transaction_count = int(store.scalar("SELECT COUNT(*) FROM transactions", default=0))
    if metric_count <= 0 or transaction_count <= 0:
        reasons.append("source lacks persisted economy evidence")
    checkpoint_evidence, checkpoint_reasons = _checkpoint_integrity(
        store, run_id=run_id, seed=seed)
    reasons.extend(checkpoint_reasons)
    bank_evidence, bank_reasons = _bank_and_metric_integrity(
        store, min_ticks=min_ticks)
    reasons.extend(bank_reasons)
    llm_evidence, llm_reasons = _llm_call_integrity(store)
    reasons.extend(llm_reasons)

    exact_counts = {
        "predictions": int(store.scalar(
            "SELECT COUNT(*) FROM predictions", default=0)),
        "resolved_predictions": int(store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE status='resolved'", default=0)),
        "acceptance_checkpoints": int(store.scalar(
            "SELECT COUNT(*) FROM acceptance_checkpoints", default=0)),
        "completed_acceptance_checkpoints": int(store.scalar(
            "SELECT COUNT(*) FROM acceptance_checkpoints WHERE status='completed'",
            default=0)),
        "oracle_predictions": int(store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='oracle_prediction'", default=0)),
        "prediction_resolutions": int(store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='prediction_resolved'", default=0)),
        "checkpoint_completions": int(store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind='acceptance_checkpoint_completed'", default=0)),
        "checkpoint_misses": int(store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind='acceptance_checkpoint_missed'", default=0)),
        "insufficient_predictions": int(store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE status='insufficient_data'",
            default=0)),
        "oracle_answers": int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='oracle' AND purpose='oracle'",
            default=0)),
        "oracle_plans": int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls "
            "WHERE role='oracle' AND purpose='oracle_plan'", default=0)),
    }
    if any(exact_counts[key] != 6 for key in (
            "predictions", "resolved_predictions", "acceptance_checkpoints",
            "completed_acceptance_checkpoints", "oracle_predictions",
            "prediction_resolutions", "checkpoint_completions", "oracle_answers")):
        reasons.append("source does not contain exactly six complete forecast lifecycles")
    if (exact_counts["checkpoint_misses"] != 0
            or exact_counts["insufficient_predictions"] != 0
            or not 6 <= exact_counts["oracle_plans"] <= 18):
        reasons.append("source has missed/insufficient or invalid planner outcomes")
    off_schedule_calls = int(store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE role='oracle' "
        "AND purpose IN ('oracle_plan','oracle') AND tick NOT IN (5,65,125,185,245,305)",
        default=0))
    off_schedule_predictions = int(store.scalar(
        "SELECT COUNT(*) FROM predictions "
        "WHERE asked_tick NOT IN (5,65,125,185,245,305)", default=0))
    if off_schedule_calls or off_schedule_predictions:
        reasons.append("source contains off-schedule Oracle calls or predictions")
    spend = float(store.scalar(
        "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))
    cap = float(config.get("budget", {}).get("cap_usd", 25.0))
    if spend < 0.0 or spend > cap + 1e-12:
        reasons.append("source spend exceeds its configured campaign cap")
    private_markers: set[str] = set()
    for row in store.query(
            "SELECT request_json,response_json FROM llm_calls ORDER BY id"):
        persisted = f"{row['request_json'] or ''}\n{row['response_json'] or ''}".lower()
        private_markers.update(
            marker for marker in FORBIDDEN_PERSISTED_MARKERS if marker in persisted)
    if private_markers:
        reasons.append("source persisted private reasoning or credential fields")
    return {
        "reconciled": reconciled,
        "quick_check": quick_check,
        "ledger": ledger,
        "living_agents": living_agents,
        "population_range": [minimum_agents, maximum_agents],
        "population": {
            **population_evidence,
            "baseline_census": {
                f"{kind}:{role or 'none'}": count
                for (kind, role), count in sorted(
                    population_evidence["baseline_census"].items(),
                    key=lambda item: (item[0][0], item[0][1] or ""))
            },
        },
        "metrics": metric_count,
        "transactions": transaction_count,
        "genesis": genesis,
        "agent_census": {
            f"{kind}:{role or 'none'}": count
            for (kind, role), count in sorted(
                census.items(), key=lambda item: (item[0][0], item[0][1] or ""))
        },
        "checkpoints": checkpoint_evidence,
        "banks_and_metrics": bank_evidence,
        "llm_calls": llm_evidence,
        "forecast_counts": exact_counts,
        "off_schedule_oracle_calls": off_schedule_calls,
        "off_schedule_predictions": off_schedule_predictions,
        "spend_usd": round(spend, 8),
        "privacy_redacted": not private_markers,
    }, reasons


@contextmanager
def _private_database(source: Path):
    """Yield a disposable byte-for-byte copy of one finalized database."""
    with tempfile.TemporaryDirectory(prefix="agent-economy-oracle-") as folder:
        snapshot = Path(folder) / "source.db"
        shutil.copyfile(source, snapshot)
        yield snapshot


@contextmanager
def _private_store(source: Path):
    """Query a finalized DB through a disposable byte-for-byte copy.

    SQLite databases retain their WAL journal mode in the main header.  Even a
    read-only SQLite connection can consequently create empty ``-wal``/``-shm``
    sidecars beside the source.  Campaign evidence must not mutate its inputs,
    so the manifest requires a finalized standalone DB and all SQLite activity
    happens against this private copy.
    """
    with _private_database(source) as snapshot:
        store = Store(str(snapshot), create=False, read_only=True)
        try:
            yield store
        finally:
            store.close()


def _event_payloads(store: Store, kind: str, tick: int) -> list[dict]:
    payloads: list[dict] = []
    for row in store.query(
            "SELECT payload_json FROM events WHERE kind=? AND tick=? ORDER BY id",
            (kind, tick)):
        payload = load_json(row["payload_json"], {})
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _one_prediction_event(store: Store, kind: str, tick: int,
                          prediction_id: int) -> bool:
    return sum(
        1 for payload in _event_payloads(store, kind, tick)
        if payload.get("prediction_id") == prediction_id
    ) == 1


def _prediction_event_rows(
        store: Store, kind: str, prediction_id: int) -> list[tuple[int, dict]]:
    found: list[tuple[int, dict]] = []
    for row in store.query(
            "SELECT tick,payload_json FROM events WHERE kind=? ORDER BY id", (kind,)):
        payload = load_json(row["payload_json"], {})
        if isinstance(payload, dict) and payload.get("prediction_id") == prediction_id:
            found.append((int(row["tick"]), payload))
    return found


def _recompute_bank_run_result(
    store: Store, *, asked_tick: int, deadline_tick: int,
    rule: dict,
) -> tuple[int | None, int | None, dict, list[str]]:
    """Resolve the fixed campaign rule from raw metrics, not scored rows."""
    reasons: list[str] = []
    try:
        window = int(rule["window"])
        drop = float(rule["deposit_drop"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, None, {}, ["campaign bank-run rule is invalid"]
    bank_ids = [int(row["id"]) for row in store.query(
        "SELECT id FROM banks ORDER BY id")]
    if not bank_ids:
        return None, None, {}, ["campaign source has no banks to resolve"]
    expected_ticks = list(range(asked_tick, deadline_tick + 1))
    earliest: int | None = None
    series_evidence: dict[str, dict] = {}
    for bank_id in bank_ids:
        name = f"bank_deposits:{bank_id}"
        rows = store.query(
            "SELECT tick,value FROM metrics WHERE name=? AND tick BETWEEN ? AND ? "
            "ORDER BY tick,id", (name, asked_tick, deadline_tick))
        ticks = [int(row["tick"]) for row in rows]
        values: list[tuple[int, float]] = []
        valid = ticks == expected_ticks
        for row in rows:
            try:
                value = float(row["value"])
            except (TypeError, ValueError, OverflowError):
                valid = False
                continue
            if not math.isfinite(value) or value < 0.0:
                valid = False
            values.append((int(row["tick"]), value))
        if not valid:
            reasons.append(
                f"{name} does not contain one finite sample for every resolution tick")
        for index, (start_tick, start_value) in enumerate(values):
            for end_tick, end_value in values[index + 1:]:
                if end_tick - start_tick > window:
                    break
                if (start_value > 0.0
                        and end_value / start_value - 1.0 <= -drop):
                    earliest = end_tick if earliest is None else min(earliest, end_tick)
                    break
        series_evidence[name] = {
            "samples": len(values),
            "first_tick": ticks[0] if ticks else None,
            "last_tick": ticks[-1] if ticks else None,
        }
    if reasons:
        return None, None, series_evidence, reasons
    outcome = 1 if earliest is not None else 0
    return outcome, earliest if earliest is not None else deadline_tick, {
        "rule": rule,
        "series": series_evidence,
        "earliest_trigger_tick": earliest,
    }, reasons


def _campaign_arm_integrity(store: Store, seed: int) -> tuple[dict, list[str]]:
    """Prove the predeclared control/treatment schedule actually executed."""
    reasons: list[str] = []
    expected = RELEASE_RUMOR_SHOCKS if seed % 2 == 0 else []
    rows = store.query("SELECT * FROM shocks ORDER BY id")
    fired_rows = store.query(
        "SELECT tick,payload_json FROM events WHERE kind='shock_fired' ORDER BY id")
    rumor_rows = store.query(
        "SELECT tick,payload_json FROM events WHERE kind='rumor' ORDER BY id")
    if len(rows) != len(expected):
        reasons.append("persisted campaign shock schedule differs from its arm")
    if len(fired_rows) != len(expected):
        reasons.append("campaign arm has missing or extra shock_fired events")
    if len(rumor_rows) != len(expected):
        reasons.append("campaign arm has missing or extra rumor events")

    fired_by_tick: dict[int, list[dict]] = {}
    for row in fired_rows:
        payload = load_json(row["payload_json"], {})
        if isinstance(payload, dict):
            fired_by_tick.setdefault(int(row["tick"]), []).append(payload)
    rumor_by_tick: dict[int, list[dict]] = {}
    for row in rumor_rows:
        payload = load_json(row["payload_json"], {})
        if isinstance(payload, dict):
            rumor_by_tick.setdefault(int(row["tick"]), []).append(payload)

    executed: list[dict] = []
    for index, item in enumerate(expected):
        tick = int(item["trigger_params"]["tick"])
        label = str(item["label"])
        row = rows[index] if index < len(rows) else None
        fired = [
            payload for payload in fired_by_tick.get(tick, [])
            if payload.get("label") == label
        ]
        rumors = rumor_by_tick.get(tick, [])
        row_valid = bool(
            row is not None
            and str(row["kind"]) == item["kind"]
            and str(row["trigger_type"]) == item["trigger"]
            and load_json(row["trigger_json"], {}) == item["trigger_params"]
            and load_json(row["params_json"], {}) == item["params"]
            and str(row["label"]) == label
            and int(row["duration_ticks"] or 0) == 0
            and int(row["fired"] or 0) == 1
            and int(row["fired_tick"] or -1) == tick)
        if not row_valid:
            reasons.append(f"campaign shock row {label} did not execute as declared")
        event_valid = False
        target_count = 0
        if len(fired) == 1 and len(rumors) == 1:
            payload = fired[0]
            params = payload.get("params")
            rumor = rumors[0]
            targets = params.get("target_agent_ids") if isinstance(params, dict) else None
            requested = int(item["params"]["n_agents"])
            target_count = len(targets) if isinstance(targets, list) else 0
            event_valid = bool(
                row is not None
                and payload.get("shock_id") == int(row["id"])
                and payload.get("kind") == "rumor"
                and payload.get("trigger_type") == "shock"
                and int(payload.get("duration_ticks", -1)) == 0
                and isinstance(params, dict)
                and all(params.get(key) == value
                        for key, value in item["params"].items())
                and isinstance(params.get("resolved_bank_id"), int)
                and params.get("resolved_bank_id") == params.get("bank_id")
                and isinstance(targets, list)
                and 1 <= target_count <= requested
                and rumor.get("bank_id") == params.get("bank_id")
                and rumor.get("target_agent_ids") == targets
                and int(rumor.get("n_agents", -1)) == target_count)
            if requested == 1:
                event_valid = event_valid and target_count == 1
        if not event_valid:
            reasons.append(f"campaign shock event {label} is missing or invalid")
        executed.append({
            "label": label, "tick": tick, "targets": target_count,
            "row_valid": row_valid, "event_valid": event_valid,
        })
    return {
        "arm": "rumor" if seed % 2 == 0 else "control",
        "expected_shocks": len(expected),
        "persisted_shocks": len(rows),
        "shock_fired_events": len(fired_rows),
        "rumor_events": len(rumor_rows),
        "executed": executed,
    }, reasons


def _planner_query_validation_errors(
        plan: dict, *, tick: int, tool_catalog: list[dict]) -> list[str]:
    """Return deterministic contract errors for one persisted planner response."""
    try:
        queries = validate_oracle_plan(
            plan, max_queries=OracleTools.MAX_QUERIES,
            current_tick=tick, tool_catalog=tool_catalog)
    except OracleToolError as exc:
        return [str(exc)]

    errors: list[str] = []
    for query in queries:
        try:
            if not isinstance(query, dict) or set(query) != {"tool", "args"}:
                raise OracleCampaignError("planner query shape is invalid")
            validate_oracle_tool_args(query["tool"], query["args"])
            for key in ("from_tick", "to_tick"):
                value = query["args"].get(key)
                if value is not None and not 0 <= value <= tick:
                    raise OracleCampaignError(
                        "planner query tick is outside the governed range")
        except (KeyError, TypeError, OracleCampaignError, OracleToolError) as exc:
            errors.append(str(exc))
    return errors


def _planner_runtime_validation_error(
        plan: dict, *, tick: int, tool_catalog: list[dict]) -> str | None:
    """Return the shared pre-execution error for a rejected response."""
    try:
        validate_oracle_plan(
            plan, max_queries=OracleTools.MAX_QUERIES,
            current_tick=tick, tool_catalog=tool_catalog)
    except OracleToolError as exc:
        return str(exc)
    return None


def _forecast_evidence(
    store: Store, *, item: dict, acceptance: dict,
    expected_provider: str, expected_model: str,
) -> tuple[dict, list[str]]:
    tick = int(item["at_tick"])
    question = str(item["question"])
    campaign_key = str(item.get("campaign_key", ""))
    reasons: list[str] = []

    checkpoint = store.query_one(
        "SELECT * FROM acceptance_checkpoints WHERE scheduled_tick=? AND question=?",
        (tick, question))
    prediction = None
    prediction_id = None
    if checkpoint is None or str(checkpoint["status"]) != "completed":
        reasons.append("scheduled checkpoint is not completed")
    elif checkpoint["prediction_id"] is None:
        reasons.append("scheduled checkpoint has no prediction")
    else:
        prediction_id = int(checkpoint["prediction_id"])
        prediction = store.query_one(
            "SELECT * FROM predictions WHERE id=? AND asked_tick=? AND question=?",
            (prediction_id, tick, question))
        if prediction is None:
            reasons.append("scheduled checkpoint prediction is missing or mismatched")

    completion = None
    if prediction_id is not None:
        bound = [
            payload for payload in _event_payloads(
                store, "acceptance_checkpoint_completed", tick)
            if payload.get("prediction_id") == prediction_id
        ]
        if len(bound) != 1:
            reasons.append(
                "scheduled prediction must have exactly one completion event")
        else:
            completion = bound[0]
            expected = {
                "scheduled_tick": tick,
                "question": question,
                "prediction_id": prediction_id,
                "latency_kind": LATENCY_KIND,
                "campaign_id": acceptance.get("oracle_campaign_id"),
                "campaign_version": acceptance.get("oracle_campaign_version"),
                "campaign_key": campaign_key,
            }
            for key, value in expected.items():
                if completion.get(key) != value:
                    reasons.append(f"completion event {key} is invalid")
            latency = completion.get("latency_ms")
            if (isinstance(latency, bool) or not isinstance(latency, int)
                    or latency < 0):
                reasons.append("completion event latency_ms is invalid")
            if completion.get("latency_measurement") not in {
                    "continuous_monotonic", "resumed_wall_clock"}:
                reasons.append("completion event latency_measurement is invalid")

    governed_calls: list[dict] = []
    if prediction_id is not None:
        from reports.acceptance import (
            _completion_latency, _scheduled_call_evidence,
        )

        governed_calls, governed_call_error = _scheduled_call_evidence(
            store, item=item, acceptance=acceptance)
        if governed_call_error:
            reasons.append(
                f"scheduled governed call evidence is invalid: {governed_call_error}")
        strict_completion, strict_completion_error = _completion_latency(
            store, prediction_id=prediction_id, item=item,
            acceptance=acceptance)
        if strict_completion_error:
            reasons.append(
                f"scheduled completion evidence is invalid: {strict_completion_error}")
        elif completion is not None and (
                strict_completion.get("latency_ms") != completion.get("latency_ms")
                or strict_completion.get("model_calls")
                != completion.get("model_calls")):
            reasons.append("scheduled completion differs from shared strict evidence")

    probability = outcome = brier = None
    persisted_outcome = persisted_brier = None
    evidence: Any = []
    resolution_evidence: dict[str, Any] = {}
    if prediction is not None:
        try:
            probability = float(prediction["p"])
        except (TypeError, ValueError, OverflowError):
            probability = None
        if probability is None or not math.isfinite(probability) \
                or not 0.0 <= probability <= 1.0:
            reasons.append("prediction probability is invalid")
        if str(prediction["status"]) != "resolved":
            reasons.append("prediction is not resolved")
        raw_outcome = prediction["outcome"]
        if isinstance(raw_outcome, bool) or raw_outcome not in (0, 1):
            reasons.append("prediction outcome is invalid")
        else:
            persisted_outcome = int(raw_outcome)
        try:
            persisted_brier = float(prediction["brier"])
        except (TypeError, ValueError, OverflowError):
            persisted_brier = None
        if (persisted_brier is None or not math.isfinite(persisted_brier)
                or persisted_brier < 0.0):
            reasons.append("prediction Brier score is invalid")
        elif probability is not None and persisted_outcome is not None \
                and not math.isclose(
                    persisted_brier, (probability - persisted_outcome) ** 2,
                                     rel_tol=0.0, abs_tol=1e-9):
            reasons.append("prediction Brier score does not match p/outcome")
        evidence = load_json(prediction["evidence_json"], [])
        if not _bounded_oracle_evidence(evidence):
            reasons.append("prediction tool evidence is missing, unknown, or unbounded")
        drivers = load_json(prediction["drivers_json"], [])
        if not (isinstance(drivers, list) and 1 <= len(drivers) <= 10 and all(
                isinstance(driver, str) and driver.strip() and len(driver) <= 300
                for driver in drivers)):
            reasons.append("prediction drivers are invalid")
        if str(prediction["confidence"] or "") not in {"low", "med", "high"}:
            reasons.append("prediction confidence is invalid")
        expected_rule = item.get("expected_rule")
        if expected_rule is not None and load_json(
                prediction["resolution_rule_json"], {}) != expected_rule:
            reasons.append("prediction resolution rule differs from campaign rule")
        horizon = item.get("horizon_ticks")
        deadline_tick = tick + int(horizon or 30)
        if int(prediction["deadline_tick"] or -1) != deadline_tick:
            reasons.append("prediction deadline differs from campaign horizon")
        if prediction_id is not None:
            outcome, resolved_tick, resolution_evidence, resolve_reasons = (
                _recompute_bank_run_result(
                    store, asked_tick=tick, deadline_tick=deadline_tick,
                    rule=item.get("expected_rule") or {}))
            reasons.extend(resolve_reasons)
            if outcome is not None and persisted_outcome != outcome:
                reasons.append(
                    "persisted outcome differs from independent metric resolution")
            if outcome is not None and probability is not None:
                brier = (probability - outcome) ** 2
                if (persisted_brier is None or not math.isclose(
                        persisted_brier, brier, rel_tol=0.0, abs_tol=1e-9)):
                    reasons.append(
                        "persisted Brier differs from independent metric resolution")
            if int(prediction["resolved_tick"] or -1) != (resolved_tick or -1):
                reasons.append(
                    "persisted resolution tick is not the earliest metric resolution")

            prediction_events = _prediction_event_rows(
                store, "oracle_prediction", prediction_id)
            if len(prediction_events) != 1:
                reasons.append("prediction has no unique oracle_prediction event")
            else:
                event_tick, payload = prediction_events[0]
                if (event_tick != tick or payload.get("question") != question
                        or payload.get("deadline_tick") != deadline_tick
                        or payload.get("rule") != item.get("expected_rule")):
                    reasons.append("oracle_prediction event contract is invalid")
                try:
                    event_p = float(payload.get("p"))
                except (TypeError, ValueError, OverflowError):
                    event_p = None
                if (event_p is None or probability is None or not math.isclose(
                        event_p, probability, rel_tol=0.0, abs_tol=1e-12)):
                    reasons.append("oracle_prediction event probability is invalid")

            resolved_events = _prediction_event_rows(
                store, "prediction_resolved", prediction_id)
            if len(resolved_events) != 1:
                reasons.append("prediction has no unique prediction_resolved event")
            else:
                event_tick, payload = resolved_events[0]
                if (resolved_tick is None or event_tick != resolved_tick
                        or payload.get("question") != question
                        or payload.get("outcome") != outcome):
                    reasons.append("prediction_resolved event outcome/tick is invalid")
                try:
                    event_p = float(payload.get("p"))
                    event_brier = float(payload.get("brier"))
                except (TypeError, ValueError, OverflowError):
                    event_p = event_brier = None
                if (event_p is None or probability is None or not math.isclose(
                        event_p, probability, rel_tol=0.0, abs_tol=1e-12)):
                    reasons.append("prediction_resolved event probability is invalid")
                if (event_brier is None or brier is None or not math.isclose(
                        event_brier, round(brier, 4),
                        rel_tol=0.0, abs_tol=1e-9)):
                    reasons.append("prediction_resolved event Brier is invalid")

    governed_contract = {
        "campaign_id": acceptance.get("oracle_campaign_id"),
        "campaign_version": acceptance.get("oracle_campaign_version"),
        "campaign_key": campaign_key,
        "scheduled_tick": tick,
        "resolution_rule": item.get("expected_rule"),
        "deadline_tick": tick + int(item.get("horizon_ticks", 30)),
    }
    expected_tool_catalog = oracle_tool_definitions(store, tick=tick)
    calls = store.query(
        "SELECT id,provider,purpose,model,request_json,response_json,in_tokens,"
        "out_tokens,cost_usd,latency_ms FROM llm_calls "
        "WHERE tick=? AND role='oracle' ORDER BY id", (tick,))
    purposes = {str(row["purpose"]) for row in calls}
    providers = {str(row["provider"] or "").lower() for row in calls}
    if not {"oracle_plan", "oracle"}.issubset(purposes):
        reasons.append("scheduled forecast lacks real planner and answer calls")
    if not calls or providers & _NON_LIVE_PROVIDERS:
        reasons.append("scheduled forecast used a non-live Oracle provider")
    if any(
        (str(row["provider"]), str(row["model"]))
        != (expected_provider, expected_model) for row in calls
    ):
        reasons.append("scheduled forecast calls differ from the configured Oracle route")
    purpose_counts = Counter(str(row["purpose"]) for row in calls)
    if (purpose_counts.get("oracle", 0) != 1
            or not 1 <= purpose_counts.get("oracle_plan", 0) <= 3
            or set(purpose_counts) - {"oracle_plan", "oracle"}):
        reasons.append("scheduled forecast has an invalid logical call set")
    plan_ids = [int(row["id"]) for row in calls
                if str(row["purpose"]) == "oracle_plan"]
    answer_ids = [int(row["id"]) for row in calls
                  if str(row["purpose"]) == "oracle"]
    if plan_ids and answer_ids and max(plan_ids) >= min(answer_ids):
        reasons.append("scheduled forecast answer preceded its successful plan")
    parsed_plans: list[dict] = []
    planner_contexts: list[dict | None] = []
    planner_query_errors: list[list[str]] = []
    planner_runtime_errors: list[str | None] = []
    call_metering: list[dict] = []
    for row in calls:
        request = load_json(row["request_json"], None)
        response = load_json(row["response_json"], None)
        context = request.get("context") if isinstance(request, dict) else None
        text = response.get("text") if isinstance(response, dict) else None
        metering, metering_reasons = _openai_metering_evidence(row, response)
        call_metering.append({
            "call_id": int(row["id"]), "purpose": str(row["purpose"]),
            **metering,
        })
        reasons.extend(metering_reasons)
        try:
            user = json.loads(request.get("user", "")) \
                if isinstance(request, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            user = None
        if (not isinstance(request, dict)
                or not isinstance(request.get("system"), str)
                or not request.get("system", "").strip()
                or not isinstance(request.get("user"), str)
                or not request.get("user", "").strip()
                or not isinstance(context, dict)
                or context.get("question") != question
                or context.get("tick") != tick
                or context.get("governed_forecast_contract") != governed_contract):
            reasons.append("scheduled forecast call request identity is invalid")
        expected_system = None
        if str(row["purpose"]) == "oracle_plan":
            from oracle.analyst import PLANNER_SYSTEM
            expected_system = PLANNER_SYSTEM
        elif str(row["purpose"]) == "oracle":
            from oracle.analyst import ANSWER_SYSTEM
            expected_system = ANSWER_SYSTEM
        if (expected_system is None or not isinstance(request, dict)
                or request.get("system") != expected_system):
            reasons.append("scheduled forecast system prompt is invalid")
        if not isinstance(user, dict):
            reasons.append("scheduled forecast user prompt is not valid JSON")
        elif (not isinstance(request, dict)
                or request.get("user") != canonical_oracle_json(user)):
            reasons.append("scheduled forecast user prompt is not canonical compact JSON")
        try:
            metered = (
                int(row["in_tokens"] or 0) > 0
                and int(row["out_tokens"] or 0) > 0
                and float(row["cost_usd"] or 0.0) > 0.0
                and int(row["latency_ms"] or 0) > 0
            )
        except (TypeError, ValueError, OverflowError):
            metered = False
        if not metered:
            reasons.append("scheduled forecast call has no live metering evidence")
        if not isinstance(text, str) or not text.strip():
            reasons.append("scheduled forecast call has no sanitized response text")
            continue
        try:
            parsed_text = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            reasons.append("scheduled forecast call response text is not valid JSON")
            continue
        if str(row["purpose"]) == "oracle_plan":
            if (parsed_text == _GATEWAY_CANONICAL_NOOP
                    and metering.get("shape") != "repair"):
                reasons.append(
                    "canonical no-op planner response lacks repair-call provenance")
            if user != context:
                reasons.append(
                    "scheduled planner user prompt differs from governed context")
            expected_constraints = {
                "tick_range": {"minimum": 0, "maximum": tick},
                "maximum_queries": OracleTools.MAX_QUERIES,
                "read_only": True,
            }
            if (not isinstance(context, dict)
                    or context.get("preflight_contract")
                    != ORACLE_PREFLIGHT_CONTRACT
                    or context.get("available_tools")
                    != expected_tool_catalog
                    or context.get("constraints") != expected_constraints):
                reasons.append("scheduled planner tool catalog/constraints are invalid")
            normalized_plan = parsed_text if isinstance(parsed_text, dict) else {}
            parsed_plans.append(normalized_plan)
            planner_contexts.append(
                context if isinstance(context, dict) else None)
            planner_query_errors.append(
                _planner_query_validation_errors(
                    normalized_plan, tick=tick,
                    tool_catalog=expected_tool_catalog))
            planner_runtime_errors.append(
                _planner_runtime_validation_error(
                    normalized_plan, tick=tick,
                    tool_catalog=expected_tool_catalog))
        elif str(row["purpose"]) == "oracle":
            if (not isinstance(context, dict)
                    or context.get("evidence") != evidence
                    or not isinstance(user, dict)
                    or user.get("governed_forecast_contract") != governed_contract
                    or user.get("question") != question
                    or user.get("tick") != tick
                    or user.get("read_only_evidence") != evidence
                    or user.get("world") != context.get("prompt_world")):
                reasons.append(
                    "scheduled answer user prompt is not evidence/contract-bound")
            try:
                answer_probability = float(parsed_text["p"])
            except (KeyError, TypeError, ValueError, OverflowError):
                answer_probability = None
            if (not isinstance(parsed_text, dict)
                    or answer_probability is None
                    or probability is None
                    or not math.isclose(
                        answer_probability, probability, rel_tol=0.0, abs_tol=1e-12)
                    or parsed_text.get("resolution_rule") != item.get("expected_rule")
                     or parsed_text.get("deadline_tick") != governed_contract["deadline_tick"]):
                reasons.append("scheduled forecast answer response is not prediction-bound")
            if prediction is not None and (
                    parsed_text.get("drivers")
                    != load_json(prediction["drivers_json"], [])
                    or parsed_text.get("confidence") != prediction["confidence"]
                    or parsed_text.get("reasoning") != prediction["reasoning"]):
                reasons.append(
                    "scheduled answer drivers/confidence/reasoning differ from prediction")
    if len(parsed_plans) != purpose_counts.get("oracle_plan", 0):
        reasons.append("scheduled forecast has an unparsable planner attempt")
    elif parsed_plans:
        first_context = planner_contexts[0]
        if (isinstance(first_context, dict)
                and ("previous_plan_error" in first_context
                     or "instruction" in first_context
                     or "planner_attempt" in first_context)):
            reasons.append("initial planner request carries retry-only state")
        expected_queries = [
            {"tool": item.get("tool"), "args": item.get("args")}
            for item in evidence if isinstance(item, dict)
        ]
        final_queries = parsed_plans[-1].get("queries")
        if not expected_queries or final_queries != expected_queries:
            reasons.append(
                "last successful planner tools/args do not match stored evidence")
        reasons.extend(
            f"scheduled planner query is invalid: {error}"
            for error in planner_query_errors[-1]
        )
        rejected = [
            payload for payload in _event_payloads(
                store, "oracle_tool_plan_rejected", tick)
            if payload.get("question") == question
        ]
        prior_plans = parsed_plans[:-1]
        if len(rejected) != len(prior_plans):
            reasons.append(
                "planner retry attempts lack matching rejection events")
        else:
            for attempt, (plan, event) in enumerate(
                    zip(prior_plans, rejected), start=1):
                if (type(event.get("attempt")) is not int
                        or event.get("attempt") != attempt
                        or event.get("plan_sha256")
                        != _canonical_value_sha256(plan)):
                    reasons.append(
                        "planner rejection event does not bind its rejected response")
                event_error = event.get("error")
                expected_error = planner_runtime_errors[attempt - 1]
                if (expected_error is None
                        or event_error != expected_error[:500]):
                    reasons.append(
                        "planner rejection error is not independently reproducible")
                next_context = planner_contexts[attempt]
                retry_context_error = (
                    expected_error if expected_error is not None else event_error)
                if (not isinstance(event_error, str) or not event_error
                        or len(event_error) > 500
                        or not isinstance(next_context, dict)
                        or not isinstance(
                            next_context.get("previous_plan_error"), str)
                        or next_context["previous_plan_error"]
                        != retry_context_error
                        or type(next_context.get("planner_attempt")) is not int
                        or next_context["planner_attempt"] != attempt + 1
                        or next_context.get("instruction") != (
                            "Return a corrected plan that satisfies every supplied "
                            "constraint.")):
                    reasons.append(
                        "planner retry context does not bind its rejection error")
    if completion is not None:
        recorded_calls = completion.get("model_calls")
        if (not isinstance(recorded_calls, list) or not recorded_calls
                or not all(
                    isinstance(call, dict)
                    and isinstance(call.get("purpose"), str)
                    and isinstance(call.get("provider"), str)
                    and isinstance(call.get("model"), str)
                    for call in recorded_calls)):
            reasons.append("completion event has no governed model-call summary")
        else:
            recorded_purposes = {
                str(call.get("purpose")) for call in recorded_calls
                if isinstance(call, dict)
            }
            if not {"oracle_plan", "oracle"}.issubset(recorded_purposes):
                reasons.append("completion model-call summary is incomplete")
            recorded_identities = Counter(
                (str(call.get("purpose")), str(call.get("provider")),
                 str(call.get("model")))
                for call in recorded_calls if isinstance(call, dict))
            actual_identities = Counter(
                (str(call["purpose"]), str(call["provider"]), str(call["model"]))
                for call in calls)
            if any(
                provider != expected_provider or model != expected_model
                for _purpose, provider, model in recorded_identities
            ):
                reasons.append("completion model-call route is invalid")
            if recorded_identities != actual_identities:
                reasons.append("completion model-call summary does not match actual calls")
            if governed_calls and recorded_calls != governed_calls:
                reasons.append(
                    "completion model-call summary differs from shared governed evidence")

    return {
        "campaign_key": campaign_key,
        "scheduled_tick": tick,
        "prediction_id": prediction_id,
        "latency_ms": completion.get("latency_ms") if completion else None,
        "p": probability,
        "outcome": outcome,
        "brier": brier,
        "resolution_evidence": resolution_evidence,
        "provider_metering": call_metering,
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
    }, reasons


def _evaluate_run(entry: dict, *, manifest_dir: Path, campaign_id: str,
                  campaign_version: int,
                  commitment_sha256: str,
                  require_source_receipt: bool = True) -> tuple[
                      dict, list[tuple[float, int]], list[int]]:
    reasons: list[str] = []
    pairs: list[tuple[float, int]] = []
    latencies: list[int] = []
    run_id = str(entry.get("run_id", ""))
    try:
        seed = int(entry["seed"])
        db_path, db_logical = _manifest_path(
            manifest_dir, entry.get("database"), "database")
        profile_path, profile_logical = _manifest_path(
            manifest_dir, entry.get("profile"), "profile")
        replay_path, replay_logical = _manifest_path(
            manifest_dir, entry.get("replay_database"), "replay_database")
    except (KeyError, TypeError, ValueError, OracleCampaignError) as exc:
        return {
            "run_id": run_id, "eligible": False,
            "reasons": [str(exc)], "forecasts": [],
        }, pairs, latencies

    expected_db_hash = str(entry.get("database_sha256", "")).lower()
    expected_profile_hash = str(entry.get("profile_sha256", "")).lower()
    expected_config_hash = str(
        entry.get("effective_config_sha256", "")).lower()
    expected_replay_hash = str(entry.get("replay_database_sha256", "")).lower()
    if (db_path.parent != RELEASE_DATA_DIR
            or db_path != (RELEASE_DATA_DIR / f"{run_id}.db").resolve()):
        reasons.append("source database is outside the canonical campaign directory")
    if replay_path.parent != RELEASE_DATA_DIR:
        reasons.append("replay database is outside the canonical campaign directory")
    if not db_path.is_file():
        reasons.append("database does not exist")
    if not profile_path.is_file():
        reasons.append("profile does not exist")
    if not replay_path.is_file():
        reasons.append("replay database does not exist")
    for label, path in (("database", db_path), ("replay database", replay_path)):
        if Path(f"{path}-wal").exists() or Path(f"{path}-shm").exists():
            reasons.append(
                f"{label} is not a finalized standalone SQLite artifact")
    db_hash_before = _sha256(db_path) if db_path.is_file() else None
    profile_hash_before = _sha256(profile_path) if profile_path.is_file() else None
    replay_hash_before = _sha256(replay_path) if replay_path.is_file() else None
    if db_hash_before != expected_db_hash:
        reasons.append("database hash does not match manifest")
    if profile_hash_before != expected_profile_hash:
        reasons.append("profile hash does not match manifest")
    if replay_hash_before != expected_replay_hash:
        reasons.append("replay database hash does not match manifest")
    expected_profile = (
        Path(__file__).resolve().parents[1] / "runs" / "oracle"
        / RELEASE_PROFILES.get(seed, "invalid-seed")
    ).resolve()
    if seed not in RELEASE_PROFILES or profile_path != expected_profile:
        reasons.append("seed/profile is not one predeclared release corpus arm")

    forecasts: list[dict] = []
    integrity: dict[str, Any] = {}
    replay_proof: dict[str, Any] = {}
    resolved_config_hash: str | None = None
    claim_evidence: dict[str, Any] = {}
    replay_execution_evidence: dict[str, Any] = {}
    source_receipt_evidence: dict[str, Any] = {}
    if not reasons:
        try:
            profile = load_config(profile_path)
            validate_oracle_campaign_profile(profile)
            resolved_config_hash = effective_config_sha256(profile)
            if resolved_config_hash != expected_config_hash:
                reasons.append(
                    "resolved configuration hash does not match manifest")
        except (OSError, UnicodeError, yaml.YAMLError,
                OracleCampaignError, ValueError) as exc:
            reasons.append(f"profile is invalid: {exc}")
    if resolved_config_hash is not None:
        claim_evidence, claim_reasons = _load_campaign_claim(
            entry, run_id=run_id, seed=seed,
            commitment_sha256=commitment_sha256,
            effective_config_hash=resolved_config_hash)
        reasons.extend(claim_reasons)
    if not reasons:
        with _private_store(db_path) as store:
            meta = store.get_meta()
            config = load_json(meta["config_json"], {})
            acceptance = config.get("acceptance", {}) if isinstance(config, dict) else {}
            questions = acceptance.get("oracle_questions", [])
            if str(meta["run_id"]) != run_id or not run_id:
                reasons.append("run_id does not match manifest")
            if int(meta["seed"]) != seed:
                reasons.append("seed does not match manifest")
            if meta["parent_run_id"] is not None or meta["fork_tick"] is not None \
                    or run_id.startswith("replay-"):
                reasons.append("run is a fork or replay")
            if int(meta["participant_influenced"] or 0) != 0:
                reasons.append("run is participant-influenced")
            if config != profile:
                reasons.append("stored configuration differs from resolved profile")
            if effective_config_sha256(config) != expected_config_hash:
                reasons.append(
                    "stored effective configuration hash differs from manifest")
            try:
                validate_oracle_campaign_profile(config)
            except OracleCampaignError as exc:
                reasons.append(f"stored campaign profile is invalid: {exc}")
            if acceptance.get("oracle_latency_source") != LATENCY_KIND:
                reasons.append("profile does not select scheduled E2E latency")
            if acceptance.get("oracle_campaign_id") != campaign_id:
                reasons.append("run campaign_id differs from manifest")
            if acceptance.get("oracle_campaign_version") != campaign_version:
                reasons.append("run campaign_version differs from manifest")
            min_ticks = int(acceptance.get("min_ticks", 0))
            if int(meta["tick"]) < min_ticks or str(meta["status"]) not in {
                    "paused", "finished"}:
                reasons.append("run did not complete its configured horizon")
            failure_events = tuple(sorted(_FAILURE_EVENTS))
            placeholders = ",".join("?" for _ in failure_events)
            failure_count = int(store.scalar(
                f"SELECT COUNT(*) FROM events WHERE kind IN ({placeholders})",
                failure_events, default=0))
            if failure_count:
                reasons.append(
                    "run contains provider/budget/reconciliation/execution failures")
            integrity, integrity_reasons = _source_integrity(
                store, config, min_ticks)
            reasons.extend(integrity_reasons)
            checkpoint_manifest_sha256 = (
                integrity.get("checkpoints", {}).get("manifest_sha256"))
            if (entry.get("checkpoint_manifest_sha256")
                    != checkpoint_manifest_sha256):
                reasons.append(
                    "checkpoint manifest hash does not match authenticated files")
            arm_integrity, arm_reasons = _campaign_arm_integrity(store, seed)
            integrity["campaign_arm"] = arm_integrity
            reasons.extend(arm_reasons)
            if not isinstance(questions, list) or not questions:
                reasons.append("run has no scheduled Oracle questions")
            else:
                for item in questions:
                    forecast, forecast_reasons = _forecast_evidence(
                        store, item=item, acceptance=acceptance,
                        expected_provider=RELEASE_ORACLE_PROVIDER,
                        expected_model=RELEASE_ORACLE_MODEL)
                    forecasts.append(forecast)
                    if forecast_reasons:
                        reasons.append(
                            f"forecast {forecast['campaign_key']} is ineligible")
                    else:
                        pairs.append((float(forecast["p"]), int(forecast["outcome"])))
                        latencies.append(int(forecast["latency_ms"]))

        with _private_database(db_path) as source_copy, \
                _private_database(replay_path) as replay_copy:
            proof = verify_replay(source_copy, replay_copy)
            replay_proof = {
                key: proof[key] for key in (
                    "exact", "source_run_id", "replay_run_id", "source_tick",
                    "replay_tick", "source_hash", "replay_hash", "differences")
            }
        if not replay_proof.get("exact") \
                or replay_proof.get("source_run_id") != run_id \
                or replay_proof.get("source_hash") != replay_proof.get("replay_hash"):
            reasons.append("companion replay is not exact for this source run")
        with _private_store(replay_path) as replay_store:
            replay_meta = replay_store.get_meta()
            replay_config = load_json(replay_meta["config_json"], {})
            if (str(replay_meta["run_id"]) == run_id
                    or str(replay_meta["parent_run_id"] or "") != run_id
                    or replay_meta["fork_tick"] is None
                    or int(replay_meta["fork_tick"]) != 0):
                reasons.append("companion replay lineage is invalid")
            if (int(replay_meta["seed"]) != seed
                    or not isinstance(replay_config, dict)
                    or replay_config.get("replay_source_run_id") != run_id
                    or replay_config.get("replay_source_tick") != int(meta["tick"])
                    or replay_config.get("seed") != seed
                    or not isinstance(
                        replay_config.get("replay_source_path"), str)
                    or not replay_config.get("replay_source_path", "").strip()
                    or Path(replay_config.get(
                        "replay_source_path", "")).resolve() != db_path):
                reasons.append("companion replay source markers are invalid")

        replay_execution_evidence, replay_receipt_reasons = (
            _validate_replay_execution_receipt(
                entry, manifest_dir=manifest_dir, source=db_path,
                replay=replay_path, profile=profile_path,
                claim_evidence=claim_evidence, proof=replay_proof))
        reasons.extend(replay_receipt_reasons)
        if require_source_receipt:
            source_receipt_evidence, source_receipt_reasons = (
                _validate_source_receipt(entry, manifest_dir=manifest_dir))
            reasons.extend(source_receipt_reasons)

    db_hash_after = _sha256(db_path) if db_path.is_file() else None
    profile_hash_after = _sha256(profile_path) if profile_path.is_file() else None
    replay_hash_after = _sha256(replay_path) if replay_path.is_file() else None
    if db_hash_after != db_hash_before:
        reasons.append("database changed while it was evaluated")
    if profile_hash_after != profile_hash_before:
        reasons.append("profile changed while it was evaluated")
    if replay_hash_after != replay_hash_before:
        reasons.append("replay database changed while it was evaluated")
    eligible = not reasons and all(item["eligible"] for item in forecasts)
    if not eligible:
        pairs.clear()
        latencies.clear()
    return {
        "run_id": run_id,
        "seed": seed,
        "database": db_logical,
        "database_sha256": db_hash_before,
        "profile": profile_logical,
        "profile_sha256": profile_hash_before,
        "effective_config_sha256": resolved_config_hash,
        "commitment_sha256": commitment_sha256,
        "replay_database": replay_logical,
        "replay_database_sha256": replay_hash_before,
        "source_unchanged": (
            db_hash_before == db_hash_after
            and profile_hash_before == profile_hash_after
            and replay_hash_before == replay_hash_after),
        "integrity": integrity,
        "claim": claim_evidence,
        "replay_execution": replay_execution_evidence,
        "source_receipt": source_receipt_evidence,
        "replay": replay_proof,
        "eligible": eligible,
        "reasons": sorted(set(reasons)),
        "forecasts": forecasts,
    }, pairs, latencies


def evaluate_oracle_campaign(manifest_path: str | Path) -> dict:
    """Evaluate one explicit campaign manifest without mutating its sources."""
    manifest_file = Path(manifest_path).resolve()
    if not manifest_file.is_file():
        raise OracleCampaignError(f"campaign manifest not found: {manifest_file}")
    manifest_hash = _sha256(manifest_file)
    payload = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise OracleCampaignError("campaign manifest must be a mapping")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise OracleCampaignError(
            f"campaign manifest schema_version must be {SCHEMA_VERSION}")
    campaign_id = payload.get("campaign_id")
    if campaign_id != RELEASE_CAMPAIGN_ID:
        raise OracleCampaignError(
            f"campaign_id must be the predeclared {RELEASE_CAMPAIGN_ID!r}")
    campaign_version = _positive_int(
        payload.get("campaign_version"), "campaign_version")
    if campaign_version != RELEASE_CAMPAIGN_VERSION:
        raise OracleCampaignError("campaign_version is not the release corpus version")
    commitment = load_release_campaign_commitment()
    if payload.get("commitment_sha256") != commitment["sha256"]:
        raise OracleCampaignError(
            "campaign manifest does not bind the immutable pre-run commitment")
    minimum_runs = _positive_int(
        payload.get("minimum_runs", DEFAULT_MINIMUM_RUNS), "minimum_runs")
    minimum_forecasts = _positive_int(
        payload.get("minimum_forecasts", DEFAULT_MINIMUM_FORECASTS),
        "minimum_forecasts")
    if minimum_runs != DEFAULT_MINIMUM_RUNS:
        raise OracleCampaignError("minimum_runs must be the fixed release floor 10")
    if minimum_forecasts != DEFAULT_MINIMUM_FORECASTS:
        raise OracleCampaignError("minimum_forecasts must be the fixed release floor 60")
    p90_limit_ms = _positive_int(
        payload.get("p90_limit_ms", DEFAULT_P90_LIMIT_MS), "p90_limit_ms")
    if p90_limit_ms > DEFAULT_P90_LIMIT_MS:
        raise OracleCampaignError("p90_limit_ms cannot exceed the hard 60000 ms gate")
    naive_brier = payload.get("naive_brier", NAIVE_BRIER)
    if (isinstance(naive_brier, bool)
            or not isinstance(naive_brier, (int, float))
            or not math.isfinite(float(naive_brier))
            or float(naive_brier) != NAIVE_BRIER):
        raise OracleCampaignError("naive_brier must be the p=0.5 baseline 0.25")
    entries = payload.get("runs")
    if not isinstance(entries, list) or len(entries) != minimum_runs:
        raise OracleCampaignError(
            f"campaign manifest must enumerate exactly {minimum_runs} fixed runs")
    identities = [
        (entry.get("run_id"), entry.get("seed"), entry.get("database"),
         entry.get("replay_database"), entry.get("profile"))
        if isinstance(entry, dict) else (None, None, None, None, None)
        for entry in entries
    ]
    if any(value is None for identity in identities for value in identity):
        raise OracleCampaignError(
            "every campaign run requires source, replay, seed, and profile identities")
    for index, label in (
            (0, "run_id"), (1, "seed"), (2, "database"),
            (3, "replay_database"), (4, "profile")):
        values = [identity[index] for identity in identities]
        if len(set(values)) != len(values):
            raise OracleCampaignError(f"campaign run {label} values must be unique")
    seeds = {int(identity[1]) for identity in identities}
    if seeds != set(RELEASE_SEEDS):
        raise OracleCampaignError("campaign seeds differ from the predeclared corpus")
    for entry in entries:
        if not isinstance(entry, dict):
            raise OracleCampaignError("every campaign run entry must be a mapping")
        committed = commitment["runs"].get(int(entry.get("seed", -1)))
        if (committed is None
                or entry.get("run_id") != committed["run_id"]
                or entry.get("effective_config_sha256")
                != committed["effective_config_sha256"]):
            raise OracleCampaignError(
                "campaign manifest differs from the pre-run commitment")
    required_receipt_fields = {
        "claim", "claim_sha256", "initialized_claim",
        "initialized_claim_sha256", "git_commit", "git_tree",
        "replay_execution_receipt", "replay_execution_receipt_sha256",
        "source_receipt", "source_receipt_sha256",
        "checkpoint_manifest_sha256",
    }
    if any(not required_receipt_fields.issubset(entry) for entry in entries):
        raise OracleCampaignError(
            "every campaign run must bind claim, replay, and source receipts")
    revisions = {
        (str(entry.get("git_commit", "")), str(entry.get("git_tree", "")))
        for entry in entries
    }
    if (len(revisions) != 1 or any(
            len(value) != 40
            or any(character not in "0123456789abcdef" for character in value)
            for revision in revisions for value in revision)):
        raise OracleCampaignError(
            "all campaign runs must share one valid Git commit/tree identity")

    run_receipts: list[dict] = []
    pairs: list[tuple[float, int]] = []
    latencies: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise OracleCampaignError("every campaign run entry must be a mapping")
        try:
            receipt, run_pairs, run_latencies = _evaluate_run(
                entry, manifest_dir=manifest_file.parent,
                campaign_id=campaign_id, campaign_version=campaign_version,
                commitment_sha256=commitment["sha256"])
        except (OSError, sqlite3.Error, UnicodeError, yaml.YAMLError) as exc:
            receipt = {
                "run_id": str(entry.get("run_id", "")),
                "seed": entry.get("seed"), "eligible": False,
                "source_unchanged": False,
                "reasons": [f"campaign artifact could not be read: {exc}"],
                "forecasts": [],
            }
            run_pairs, run_latencies = [], []
        run_receipts.append(receipt)
        pairs.extend(run_pairs)
        latencies.extend(run_latencies)
    run_receipts.sort(key=lambda item: (item.get("seed", -1), item.get("run_id", "")))

    calibration = calibration_from_pairs(pairs)
    raw_brier = (
        math.fsum((probability - outcome) ** 2
                  for probability, outcome in pairs) / len(pairs)
        if pairs else None)
    p50 = _nearest_rank(latencies, 0.50)
    p90 = _nearest_rank(latencies, 0.90)
    outcomes = {
        "0": sum(1 for _, outcome in pairs if outcome == 0),
        "1": sum(1 for _, outcome in pairs if outcome == 1),
    }
    eligible_runs = sum(1 for run in run_receipts if run["eligible"])
    checks = [
        {
            "id": "complete_manifest",
            "passed": eligible_runs == len(entries) and eligible_runs >= minimum_runs,
            "evidence": {
                "eligible_runs": eligible_runs, "expected_runs": len(entries),
                "minimum_runs": minimum_runs,
            },
        },
        {
            "id": "forecast_count",
            "passed": len(pairs) >= minimum_forecasts,
            "evidence": {"forecasts": len(pairs), "minimum": minimum_forecasts},
        },
        {
            "id": "outcome_diversity",
            "passed": outcomes["0"] > 0 and outcomes["1"] > 0,
            "evidence": outcomes,
        },
        {
            "id": "end_to_end_latency",
            "passed": p90 is not None and p90 < p90_limit_ms,
            "evidence": {
                "samples": len(latencies), "p50_ms": p50, "p90_ms": p90,
                "max_ms": max(latencies) if latencies else None,
                "limit_ms": p90_limit_ms, "latency_kind": LATENCY_KIND,
            },
        },
        {
            "id": "calibration",
            "passed": (
                raw_brier is not None
                and math.isfinite(raw_brier)
                and raw_brier < float(naive_brier)),
            "evidence": {**calibration, "raw_brier": raw_brier,
                         "raw_naive_brier": float(naive_brier)},
        },
        {
            "id": "sources_unchanged",
            "passed": all(run.get("source_unchanged") for run in run_receipts),
            "evidence": {
                "unchanged": sum(
                    1 for run in run_receipts if run.get("source_unchanged")),
                "expected": len(run_receipts),
            },
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "campaign_version": campaign_version,
        "commitment_sha256": commitment["sha256"],
        "manifest_sha256": manifest_hash,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "calibration": {**calibration, "raw_brier": raw_brier,
                        "raw_naive_brier": float(naive_brier)},
        "runs": run_receipts,
        "excluded_runs": [
            {"run_id": run["run_id"], "reasons": run["reasons"]}
            for run in run_receipts if not run["eligible"]
        ],
    }


def finalize_sqlite_artifact(path: str | Path) -> Path:
    """Finalize a campaign DB while preserving the campaign error contract."""
    try:
        return _finalize_sqlite_artifact(path)
    except SQLiteArtifactError as exc:
        raise OracleCampaignError(str(exc)) from exc


def load_existing_oracle_source_receipt(
        *, campaign_claim: dict, profile_path: str | Path,
        out_dir: str | Path, data_dir: str | Path) -> dict | None:
    """Validate and return a completed receipt chain without opening its DB RW."""
    root = _canonical_campaign_root(data_dir)
    claim_body = _claim_body(campaign_claim)
    run_id = str(claim_body["run_id"])
    profile = Path(profile_path).resolve()
    source = (root / f"{run_id}.db").resolve()
    if not source.is_file():
        return None
    output = Path(out_dir).resolve()
    source_candidates = sorted(output.glob(f"oracle_source_{run_id}_*.json")) \
        if output.is_dir() else []
    replay_candidates = sorted(output.glob(f"oracle_replay_{run_id}_*.json")) \
        if output.is_dir() else []
    if not source_candidates:
        if replay_candidates:
            raise OracleCampaignError(
                "completed Oracle source has a partial/conflicting replay receipt")
        return None
    if (Path(f"{source}-wal").exists() or Path(f"{source}-shm").exists()):
        raise OracleCampaignError(
            "completed Oracle source receipt conflicts with SQLite sidecars")
    expected_source_receipt = output / (
        f"oracle_source_{run_id}_{_sha256(source)[:12]}.json")
    if source_candidates != [expected_source_receipt]:
        raise OracleCampaignError(
            "completed Oracle source has conflicting source receipt artifacts")
    try:
        payload = json.loads(
            expected_source_receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OracleCampaignError(
            f"completed Oracle source receipt is unreadable: {exc}") from exc
    if (not isinstance(payload, dict)
            or expected_source_receipt.read_bytes()
            != _canonical_artifact_bytes(payload)):
        raise OracleCampaignError(
            "completed Oracle source receipt is not canonical")
    base_entry = payload.get("manifest_entry")
    if not isinstance(base_entry, dict):
        raise OracleCampaignError(
            "completed Oracle source receipt has no manifest entry")
    replay_receipt = Path(str(
        base_entry.get("replay_execution_receipt", ""))).resolve()
    if replay_candidates != [replay_receipt]:
        raise OracleCampaignError(
            "completed Oracle source has conflicting replay receipt artifacts")
    entry = {
        **base_entry,
        "source_receipt": str(expected_source_receipt),
        "source_receipt_sha256": _sha256(expected_source_receipt),
    }
    commitment = load_release_campaign_commitment()
    run, pairs, latencies = _evaluate_run(
        entry, manifest_dir=output,
        campaign_id=RELEASE_CAMPAIGN_ID,
        campaign_version=RELEASE_CAMPAIGN_VERSION,
        commitment_sha256=commitment["sha256"],
        require_source_receipt=True)
    persisted_run = payload.get("run")
    comparable_run = {**run, "source_receipt": {}}
    if (payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("campaign_id") != RELEASE_CAMPAIGN_ID
            or payload.get("campaign_version") != RELEASE_CAMPAIGN_VERSION
            or payload.get("commitment_sha256") != commitment["sha256"]
            or payload.get("passed") is not True
            or persisted_run != comparable_run
            or not run.get("eligible")
            or len(pairs) != 6 or len(latencies) != 6
            or entry.get("run_id") != run_id
            or Path(str(entry.get("database", ""))).resolve() != source
            or Path(str(entry.get("profile", ""))).resolve() != profile):
        raise OracleCampaignError(
            "completed Oracle source receipt chain is invalid or conflicting")
    return {
        **payload,
        "artifact": str(expected_source_receipt),
        "artifact_sha256": _sha256(expected_source_receipt),
        "manifest_entry": entry,
    }


def write_replay_execution_receipt(
        source_path: str | Path, replay_path: str | Path,
        profile_path: str | Path, *, replay_tracker: dict,
        campaign_claim: dict, out_dir: str | Path = "reports/out") -> dict:
    """Bind one actual replay execution tracker to finalized artifacts."""
    source = Path(source_path).resolve()
    replay = Path(replay_path).resolve()
    profile = Path(profile_path).resolve()
    for path, label in (
            (source, "source"), (replay, "replay"), (profile, "profile")):
        if not path.is_file():
            raise OracleCampaignError(f"Oracle {label} artifact is missing: {path}")
    for database, label in ((source, "source"), (replay, "replay")):
        if any(Path(f"{database}{suffix}").exists()
               for suffix in ("-wal", "-shm")):
            raise OracleCampaignError(
                f"Oracle {label} database is not a finalized standalone "
                "SQLite artifact")
    revision = get_clean_git_revision()
    claim_body = _claim_body(campaign_claim)
    if (source.parent != RELEASE_DATA_DIR
            or source != (RELEASE_DATA_DIR / f"{claim_body['run_id']}.db").resolve()
            or replay.parent != RELEASE_DATA_DIR):
        raise OracleCampaignError(
            "Oracle source and replay databases must use canonical campaign paths")
    if revision != {
            "git_commit": claim_body["git_commit"],
            "git_tree": claim_body["git_tree"]}:
        raise OracleCampaignError(
            "campaign Git revision/tree changed after the immutable claim")
    claim_path = Path(str(campaign_claim.get("claim_path", ""))).resolve()
    initialized_path = Path(
        str(campaign_claim.get("initialized_path", ""))).resolve()
    if (not claim_path.is_file()
            or claim_path.read_bytes() != _canonical_artifact_bytes(claim_body)
            or not initialized_path.is_file()):
        raise OracleCampaignError(
            "campaign claim/initialized artifacts are missing or changed")
    claim_sha = _sha256(claim_path)
    initialized_sha = _sha256(initialized_path)
    checkpoint_manifest, checkpoint_reasons = (
        _checkpoint_manifest_for_source(source))
    if checkpoint_reasons:
        raise OracleCampaignError("; ".join(sorted(set(checkpoint_reasons))))

    expected_tracker = _expected_replay_tracker(source)
    tracker_required = {
        **expected_tracker,
        "consumed_source_calls": expected_tracker["source_nonoperational_calls"],
        "consumed_logical_calls_sha256": (
            expected_tracker["source_logical_calls_sha256"]),
        "consumed_purpose_counts": expected_tracker["source_purpose_counts"],
        "oracle_consumed_calls": expected_tracker["oracle_source_calls"],
        "oracle_consumed_calls_sha256": (
            expected_tracker["oracle_source_calls_sha256"]),
        "exact_key_matches": expected_tracker["source_nonoperational_calls"],
        "compatibility_fallback_matches": 0,
        "live_dispatch_count": 0,
        "missing_source_calls": 0,
        "unexpected_source_calls": 0,
        "duplicate_source_consumptions": 0,
        "all_nonoperational_calls_consumed_once": True,
        "all_oracle_calls_consumed_once": True,
    }
    if (not isinstance(replay_tracker, dict)
            or any(replay_tracker.get(key) != value
                   for key, value in tracker_required.items())):
        raise OracleCampaignError(
            "replay tracker does not prove exact one-time source-call consumption")

    try:
        proof = verify_replay(source, replay)
    except (OSError, sqlite3.Error) as exc:
        raise OracleCampaignError(f"could not verify campaign replay: {exc}") from exc
    if (not proof.get("exact") or proof.get("differences")
            or proof.get("source_hash") != proof.get("replay_hash")):
        raise OracleCampaignError("campaign replay is not exact")
    with _private_store(source) as source_store, \
            _private_store(replay) as replay_store:
        source_meta = source_store.get_meta()
        replay_meta = replay_store.get_meta()
    proof_summary = {
        key: proof[key] for key in (
            "exact", "source_run_id", "replay_run_id", "source_tick",
            "replay_tick", "source_hash", "replay_hash", "differences")
    }
    if (str(source_meta["run_id"]) != claim_body["run_id"]
            or str(replay_meta["parent_run_id"] or "") != claim_body["run_id"]
            or int(source_meta["tick"]) != RELEASE_HORIZON_TICKS
            or int(replay_meta["tick"]) != RELEASE_HORIZON_TICKS):
        raise OracleCampaignError("replay execution lineage/ticks are invalid")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "oracle_replay_execution_v1",
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_claim": claim_body,
        "campaign_claim_path": str(claim_path),
        "campaign_claim_sha256": claim_sha,
        "initialized_claim_path": str(initialized_path),
        "initialized_claim_sha256": initialized_sha,
        "git_commit": revision["git_commit"],
        "git_tree": revision["git_tree"],
        "source_database": str(source),
        "source_database_sha256": _sha256(source),
        "replay_database": str(replay),
        "replay_database_sha256": _sha256(replay),
        "profile": str(profile),
        "profile_sha256": _sha256(profile),
        "checkpoint_manifest": checkpoint_manifest,
        "checkpoint_manifest_sha256": checkpoint_manifest["manifest_sha256"],
        "source_run_id": str(source_meta["run_id"]),
        "replay_run_id": str(replay_meta["run_id"]),
        "source_tick": int(source_meta["tick"]),
        "replay_tick": int(replay_meta["tick"]),
        "exact_replay": proof_summary,
        "replay_tracker": replay_tracker,
        "passed": True,
    }
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / (
        f"oracle_replay_{claim_body['run_id']}_"
        f"{receipt['source_database_sha256'][:12]}.json")
    _atomic_publish_bytes(
        target, _canonical_artifact_bytes(receipt), allow_identical=True,
        label="Oracle replay execution receipt")
    return {
        **receipt,
        "artifact": str(target),
        "artifact_sha256": _sha256(target),
    }


def write_oracle_source_receipt(
    source_path: str | Path, replay_path: str | Path, profile_path: str | Path,
    *, replay_execution_receipt: str | Path, campaign_claim: dict,
    out_dir: str | Path = "reports/out",
) -> dict:
    """Validate and write one predeclared live-source + exact-replay receipt."""
    source = Path(source_path).resolve()
    replay = Path(replay_path).resolve()
    profile = Path(profile_path).resolve()
    for database in (source, replay):
        if not database.is_file():
            raise OracleCampaignError(f"campaign database not found: {database}")
    if not profile.is_file():
        raise OracleCampaignError(f"campaign profile not found: {profile}")
    with _private_store(source) as store:
        meta = store.get_meta()
        run_id = str(meta["run_id"])
        seed = int(meta["seed"])
        stored_config = load_json(meta["config_json"], {})
    commitment = load_release_campaign_commitment()
    committed = commitment["runs"].get(seed)
    resolved_config = load_config(profile)
    resolved_config_hash = effective_config_sha256(resolved_config)
    if (committed is None or run_id != committed["run_id"]
            or resolved_config_hash != committed["effective_config_sha256"]
            or stored_config != resolved_config):
        raise OracleCampaignError(
            "source does not match the immutable pre-run commitment")
    claim_body = _claim_body(campaign_claim)
    if (source.parent != RELEASE_DATA_DIR
            or source != (RELEASE_DATA_DIR / f"{run_id}.db").resolve()
            or replay.parent != RELEASE_DATA_DIR):
        raise OracleCampaignError(
            "Oracle source and replay databases must use canonical campaign paths")
    claim_path = Path(str(campaign_claim.get("claim_path", ""))).resolve()
    initialized_path = Path(
        str(campaign_claim.get("initialized_path", ""))).resolve()
    replay_receipt_path = Path(replay_execution_receipt).resolve()
    if (not claim_path.is_file() or not initialized_path.is_file()
            or not replay_receipt_path.is_file()):
        raise OracleCampaignError("campaign supporting receipt artifacts are missing")
    checkpoint_manifest, checkpoint_reasons = (
        _checkpoint_manifest_for_source(source))
    if checkpoint_reasons:
        raise OracleCampaignError("; ".join(sorted(set(checkpoint_reasons))))
    entry = {
        "run_id": run_id,
        "seed": seed,
        "database": str(source),
        "database_sha256": _sha256(source),
        "replay_database": str(replay),
        "replay_database_sha256": _sha256(replay),
        "profile": str(profile),
        "profile_sha256": _sha256(profile),
        "effective_config_sha256": resolved_config_hash,
        "claim": str(claim_path),
        "claim_sha256": _sha256(claim_path),
        "initialized_claim": str(initialized_path),
        "initialized_claim_sha256": _sha256(initialized_path),
        "git_commit": claim_body["git_commit"],
        "git_tree": claim_body["git_tree"],
        "checkpoint_manifest_sha256": checkpoint_manifest["manifest_sha256"],
        "replay_execution_receipt": str(replay_receipt_path),
        "replay_execution_receipt_sha256": _sha256(replay_receipt_path),
    }
    run, pairs, latencies = _evaluate_run(
        entry, manifest_dir=Path.cwd(), campaign_id=RELEASE_CAMPAIGN_ID,
        campaign_version=RELEASE_CAMPAIGN_VERSION,
        commitment_sha256=commitment["sha256"],
        require_source_receipt=False)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "commitment_sha256": commitment["sha256"],
        "passed": bool(run["eligible"] and len(pairs) == 6 and len(latencies) == 6),
        "manifest_entry": entry,
        "run": run,
    }
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"oracle_source_{run_id}_{entry['database_sha256'][:12]}.json"
    _atomic_publish_bytes(
        target, _canonical_artifact_bytes(receipt), allow_identical=True,
        label="Oracle source receipt")
    manifest_entry = {
        **entry,
        "source_receipt": str(target.resolve()),
        "source_receipt_sha256": _sha256(target),
    }
    return {
        **receipt, "artifact": str(target),
        "artifact_sha256": _sha256(target),
        "manifest_entry": manifest_entry,
    }


def write_oracle_campaign_package(
        manifest_path: str | Path, *, out_dir: str | Path = "reports/out") -> dict:
    """Write deterministic JSON and Markdown receipts for one manifest."""
    receipt = evaluate_oracle_campaign(manifest_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in str(receipt["campaign_id"])
    ).strip("-") or "oracle-campaign"
    artifact_stem = (
        f"oracle_calibration_{safe_id}_v{receipt['campaign_version']}_"
        f"{receipt['manifest_sha256'][:12]}")
    json_path = out / f"{artifact_stem}.json"
    markdown_path = out / f"{artifact_stem}.md"
    _atomic_publish_bytes(
        json_path, _canonical_artifact_bytes(receipt), allow_identical=True,
        label="Oracle campaign JSON receipt")
    checks = {check["id"]: check for check in receipt["checks"]}
    lines = [
        f"# Oracle calibration — {receipt['campaign_id']}",
        "",
        f"Overall: **{'PASS' if receipt['passed'] else 'FAIL'}**",
        "",
        f"Manifest SHA-256: `{receipt['manifest_sha256']}`",
        "",
        "## Gates",
        "",
    ]
    for check_id in (
            "complete_manifest", "forecast_count", "outcome_diversity",
            "end_to_end_latency", "calibration", "sources_unchanged"):
        check = checks[check_id]
        lines.append(
            f"- [{'x' if check['passed'] else ' '}] `{check_id}` — "
            f"`{json.dumps(check['evidence'], sort_keys=True)}`")
    lines += ["", "## Runs", ""]
    for run in receipt["runs"]:
        lines.append(
            f"- [{'x' if run['eligible'] else ' '}] `{run['run_id']}` "
            f"(seed {run.get('seed', 'unknown')}, "
            f"{len(run.get('forecasts', []))} forecasts)")
        for reason in run.get("reasons", []):
            lines.append(f"  - Excluded: {reason}")
    _atomic_publish_bytes(
        markdown_path, ("\n".join(lines) + "\n").encode("utf-8"),
        allow_identical=True, label="Oracle campaign Markdown receipt")
    return {
        **receipt,
        "artifacts": {
            "json": str(json_path),
            "markdown": str(markdown_path),
        },
    }
