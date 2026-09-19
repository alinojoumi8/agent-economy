"""Bounded owner-configured policy designs; clients select identities, not code."""
from __future__ import annotations

import hashlib
from itertools import islice
from pathlib import Path
import stat
from typing import Annotated

from pydantic import Field

from research.artifacts import digest_json
from research.contracts import Contract, Digest
from research.policy_operator import policy_design_view
from research.policy_studies import declare_policy, draft_policy_comparison
from research.provider_budget import TokenTariff
from research.study_results import StudyIdentityChanged


class PolicySelection(Contract):
    id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    sha256: Digest


class PolicyDefinition(Contract):
    key: Annotated[str, Field(min_length=1, max_length=48)]
    llm: dict
    temperature: float | None
    repair_temperature: float = .2


class PolicyFile(Contract):
    # Same private JSON shape accepted by research.policy_studies --design.
    policies: Annotated[list[PolicyDefinition], Field(min_length=2, max_length=4)]
    tariffs: Annotated[list[TokenTariff], Field(min_length=1, max_length=4)]


class OperatorPolicies:
    MAX_BYTES = 64 * 1024
    MAX_SCAN = 100
    MAX_ITEMS = 20
    LIMITS = {"max_seeds": 5, "max_model_replicates": 3, "max_policies": 4,
        "max_horizon": 30, "max_wall_seconds": 600, "max_disk_mib": 1024,
        "max_provider_calls": 5000, "max_tokens": 10_000_000, "max_spend_usd": 5.0}

    def __init__(self, root: Path):
        self.root = root.absolute()

    def _paths(self):
        if self.root != self.root.resolve():
            raise ValueError("policy directory must not be an alias")
        if not self.root.exists():
            return [], False
        entries = list(islice(self.root.iterdir(), self.MAX_SCAN + 1))
        return sorted(path for path in entries[:self.MAX_SCAN] if path.suffix == ".json"), len(entries) > self.MAX_SCAN

    @staticmethod
    def identity(path: Path) -> str:
        return digest_json(path.name)[:32]

    def _read(self, path: Path):
        if path.parent != self.root or path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("policy file must be a regular, unaliased member")
        with path.open("rb") as handle:
            raw = handle.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise ValueError("policy file exceeds the size limit")
        declared = PolicyFile.model_validate_json(raw)
        policies = [declare_policy(**policy.model_dump()) for policy in declared.policies]
        reviewed = hashlib.sha256(raw).hexdigest()
        with path.open("rb") as handle:
            current = handle.read(self.MAX_BYTES + 1)
        if path.resolve() != path or current != raw:
            raise StudyIdentityChanged("Policy design changed while reading it. Refresh and validate again.")
        return policies, declared.tariffs, reviewed

    def catalog(self, config: dict) -> dict:
        unavailable = False
        try:
            paths, truncated = self._paths()
        except (OSError, ValueError):
            paths, truncated, unavailable = [], False, True
        items, omitted = [], int(unavailable)
        for path in paths:
            if len(items) >= self.MAX_ITEMS:
                truncated = True
                break
            try:
                policies, tariffs, reviewed = self._read(path)
                spec = draft_policy_comparison(config, policies=policies, tariffs=tariffs,
                    seeds=[1], model_replicates=["draw1"], horizon=3,
                    max_provider_calls=self.LIMITS["max_provider_calls"],
                    max_tokens=self.LIMITS["max_tokens"], max_spend_usd=self.LIMITS["max_spend_usd"])
                from research.policy_runner import validate_policy_execution
                validate_policy_execution(spec, config)
                items.append({"id": self.identity(path), "sha256": reviewed,
                    "title": " / ".join(policy.key for policy in policies),
                    "policies": policy_design_view(spec)["policies"],
                    "tariffs": policy_design_view(spec)["tariffs"]})
            except (OSError, ValueError, TypeError, KeyError):
                omitted += 1
        return {"contract": "operator-policy-design-catalog-v1", "items": items,
            "truncated": truncated, "unavailable_or_incompatible": omitted, "root_unavailable": unavailable, "limits": self.LIMITS,
            "scope": "Owner-configured models and declared tariffs. Listing and validation make no provider calls; readiness is unchecked."}

    def resolve(self, selection: PolicySelection):
        paths, _ = self._paths()
        path = next((path for path in paths if self.identity(path) == selection.id), None)
        if path is None:
            raise StudyIdentityChanged("Selected policy design is no longer listed. Refresh and validate again.")
        try:
            policies, tariffs, reviewed = self._read(path)
            if reviewed != selection.sha256:
                raise ValueError("changed design")
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise StudyIdentityChanged("Selected policy design changed or is unavailable. Refresh and validate again.") from exc
        return policies, tariffs
