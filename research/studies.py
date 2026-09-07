"""Strict, prospective study protocols and immutable launch preparation.

Validating a protocol does not establish empirical validity or authorize live
provider use. Runners must check their own supported execution capabilities.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_serializer, model_validator
import yaml

from engine.schema import SCHEMA_VERSION
from engine.semantics import validate_engine_semantics_version
from engine.keyed_random import DAILY_STREAM_CONTRACT
from research.artifacts import create_batch, digest_json, file_sha256, publish_copy, safe_key
from research.metric_registry import metric_definition
from research.contracts import Contract, Digest, Text
from research.provider_budget import TokenTariff
from research.working_contracts import working_protocol

PROTOCOL_VERSION = "research-study-v1"
MODEL_DESCRIPTION_VERSION = "agent-economy-odd-v1"
Tick = Annotated[int, Field(ge=0)]


class InputArtifact(Contract):
    key: Text
    path: Text
    sha256: Digest
    role: Literal["initialization", "calibration", "holdout", "scenario", "checkpoint"]
    vintage: Text
    transform_version: Text


class CheckpointSource(Contract):
    seed: Annotated[int, Field(ge=0)]
    input_key: Text
    receipt_sha256: Digest


class CheckpointOrigins(Contract):
    kind: Literal["verified_checkpoints"]
    tick: Tick
    sources: list[CheckpointSource]


class ModelContract(Contract):
    engine_semantics_version: int
    schema_version: int
    resolved_config_sha256: Digest
    model_description_version: Literal["agent-economy-odd-v1"]
    regimes: list[Text]

    @model_validator(mode="after")
    def supported_model(self):
        validate_engine_semantics_version(self.engine_semantics_version)
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("fresh study schema must match this executable")
        if not self.regimes or len(set(self.regimes)) != len(self.regimes):
            raise ValueError("declare a unique, nonempty regime list")
        return self


class BehaviorContract(Contract):
    family: Literal["scripted", "adaptive", "recorded_llm", "live_llm"]
    version: Text
    prompt_sha256: Digest | None
    provider_reference: Text | None
    model_reference: Text | None
    endpoint_reference: Text | None
    temperature: Annotated[float, Field(ge=0, le=2)] | None
    wake_cadence: Text
    communication_policy: Text
    population_assignment: Text

    @model_validator(mode="after")
    def provider_identity(self):
        if self.family in {"recorded_llm", "live_llm"}:
            if any(value is None for value in (self.prompt_sha256,
                    self.provider_reference, self.model_reference,
                    self.endpoint_reference, self.temperature)):
                raise ValueError("LLM policy requires its complete provider and prompt identity")
        elif any(value is not None for value in (self.prompt_sha256,
                self.provider_reference, self.model_reference,
                self.endpoint_reference, self.temperature)):
            raise ValueError("offline policies must not carry an undeclared LLM identity")
        if self.endpoint_reference:
            endpoint = urlsplit(self.endpoint_reference)
            if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
                raise ValueError("endpoint references must not contain credentials or query values")
        return self


class TimeContract(Contract):
    tick_duration: Literal["one_day"]
    warmup_ticks: Tick
    intervention_start: Tick
    intervention_end: Tick
    measurement_start: Tick
    measurement_end: Tick
    horizon: Annotated[int, Field(ge=1)]
    stop_rule: Literal["fixed_horizon"]

    @model_validator(mode="after")
    def ordered_windows(self):
        if not (self.warmup_ticks < self.intervention_start <=
                self.intervention_end <= self.horizon):
            raise ValueError("intervention must follow warmup and fit within the horizon")
        if not (self.intervention_start <= self.measurement_start <=
                self.measurement_end == self.horizon):
            raise ValueError("measurement must follow intervention and end at the horizon")
        return self


class Outcome(Contract):
    key: Text
    metric: Text
    metric_version: Text
    aggregation: Literal["terminal", "window_mean", "window_sum", "window_vwap"]
    currency: Text | None
    purpose: Literal["primary", "exploratory"]


class AnalysisContract(Contract):
    intent: Literal["exploratory", "confirmatory"]
    estimand: Text
    treatment_unit: Literal["world_seed_pair", "checkpoint_world_pair"]
    outcomes: list[Outcome]
    missing_data: Literal["exclude_pair_report_reason"]
    uncertainty: Literal["paired_world_bootstrap", "paired_replicated_world_bootstrap"]
    minimum_pairs: Annotated[int, Field(ge=2)]
    bootstrap_samples: Annotated[int, Field(ge=100, le=100000)]
    multiple_outcome_policy: Literal["descriptive_only", "single_primary"]


class RandomnessContract(Contract):
    seeds: list[int]
    seed_role: Literal["initial_world_and_engine_stream", "initial_world_and_keyed_daily_streams", "checkpoint_origin_seed"]
    stream_contract: Literal["legacy_shared_rng_v1", "mechanism_day_identity_v1"]
    pairing: Literal["verified_common_genesis", "verified_common_checkpoint"]
    model_replicates: list[Text]


class OperationContract(Contract):
    mode: Literal["provider_free", "live"]
    max_provider_calls: Annotated[int, Field(ge=0)]
    max_tokens: Annotated[int, Field(ge=0)]
    max_spend_usd: Annotated[float, Field(ge=0)]
    max_wall_seconds: Annotated[int, Field(ge=1)]
    max_disk_bytes: Annotated[int, Field(ge=1)]
    concurrency: Annotated[int, Field(ge=1, le=32)]
    failure_policy: Literal["preserve_and_exclude"]
    pause_policy: Literal["preserve_and_stop", "preserve_and_resume", "preserve_and_resume_phases"]

    @model_validator(mode="after")
    def bounded_mode(self):
        limits = (self.max_provider_calls, self.max_tokens, self.max_spend_usd)
        if self.mode == "provider_free" and any(limits):
            raise ValueError("provider-free studies require zero provider budgets")
        if self.mode == "live" and not all(limits):
            raise ValueError("live studies require positive call, token and spend caps")
        return self


class InputCostShock(Contract):
    kind: Literal["oil"]
    tick: Annotated[int, Field(ge=1)]
    multiplier: Annotated[float, Field(gt=0, le=100)]


class FirmInformationShock(Contract):
    kind: Literal["scandal"]
    tick: Annotated[int, Field(ge=1)]
    firm_id: Annotated[int, Field(ge=1)]
    description: Text


class ArmChanges(Contract):
    shocks: list[Annotated[InputCostShock | FirmInformationShock,
                          Field(discriminator="kind")]] = Field(default_factory=list)


class StudyArm(Contract):
    key: Text
    label: Text
    role: Literal["baseline", "treatment"]
    changes: ArmChanges
    information_policy: Text
    policy: Text | None = None

    @model_serializer(mode="wrap")
    def serialized_arm(self, handler):
        value = handler(self)
        if self.policy is None:
            value.pop("policy", None)
        return value

    @model_validator(mode="after")
    def arm_identity(self):
        safe_key(self.key)
        if self.role == "baseline" and self.changes.shocks:
            raise ValueError("baseline changes must be empty; use the resolved base configuration")
        if self.role == "treatment" and not self.changes.shocks and self.policy is None:
            raise ValueError("treatment must declare its changes")
        return self


class StudyPolicy(Contract):
    key: Text
    behavior: BehaviorContract
    llm: dict[str, Any]
    sampling_contract: Literal["fixed-primary-and-repair-v1"]
    repair_temperature: Annotated[float, Field(ge=0, le=2)]
    preflight_temperature: Annotated[float, Field(ge=0, le=0)]
    observation_action_contract: Literal["shared-runtime-observation-action-v1"]

    @model_validator(mode="after")
    def policy_identity(self):
        safe_key(self.key)
        reject_inline_secrets(self.llm)
        if self.behavior.family not in {"scripted", "live_llm"}:
            raise ValueError("policy studies require executable scripted or live policies")
        return self


class PolicyDesign(Contract):
    policies: list[StudyPolicy]
    tariffs: list[TokenTariff]
    replicate_aggregation: Literal["complete-paired-block-mean-v1"]
    execution_governor: Literal["fixed-cadence-under-shared-budget-v1"]

    @model_validator(mode="after")
    def declared_catalog(self):
        keys = [item.key for item in self.policies]
        if not 1 <= len(keys) <= 16 or len(set(keys)) != len(keys):
            raise ValueError("declare one to sixteen distinct decision policies")
        targets = [(item.provider, item.model) for item in self.tariffs]
        expected = {(item.behavior.provider_reference, item.behavior.model_reference)
                    for item in self.policies if item.behavior.family == "live_llm"}
        if not expected or set(targets) != expected or len(set(targets)) != len(targets):
            raise ValueError("declare exactly one tariff for every live provider/model")
        return self


class StudySpec(Contract):
    protocol_version: Literal["research-study-v1", "research-study-v2", "research-study-v3"]
    key: Text
    title: Text
    hypothesis: Text
    limitations: list[Text]
    domains: list[Literal["goods", "equities"]]
    model: ModelContract
    inputs: list[InputArtifact]
    calibration_targets: list[Text]
    arms: list[StudyArm]
    behavior: BehaviorContract
    time: TimeContract
    randomness: RandomnessContract
    analysis: AnalysisContract
    operations: OperationContract
    origin: CheckpointOrigins | None = None
    policy_design: PolicyDesign | None = None

    @model_serializer(mode="wrap")
    def serialized_contract(self, handler):
        value = handler(self)
        # Existing frozen v1 manifests must not gain even a null/default field.
        if self.origin is None:
            value.pop("origin", None)
        if self.policy_design is None:
            value.pop("policy_design", None)
        return value

    @model_validator(mode="after")
    def consistent_study(self):
        safe_key(self.key)
        if not self.domains or len(set(self.domains)) != len(self.domains):
            raise ValueError("declare unique supported price domains")
        if not self.limitations:
            raise ValueError("declare the model's relevant limitations")
        keys = [arm.key for arm in self.arms]
        if len(keys) < 2 or len(set(keys)) != len(keys):
            raise ValueError("study needs at least two uniquely named arms")
        if sum(arm.role == "baseline" for arm in self.arms) != 1:
            raise ValueError("study needs exactly one baseline")
        for arm in self.arms:
            for shock in arm.changes.shocks:
                if not self.time.intervention_start <= shock.tick <= self.time.intervention_end:
                    raise ValueError("arm shock is outside the declared intervention window")
        seeds = self.randomness.seeds
        if not seeds or len(seeds) != len(set(seeds)) or any(seed < 0 for seed in seeds):
            raise ValueError("seeds must be nonnegative, nonempty and unique")
        policy_study = self.protocol_version == "research-study-v3"
        if policy_study != (self.policy_design is not None):
            raise ValueError("policy assignments require research-study-v3")
        if self.randomness.model_replicates and not policy_study:
            raise ValueError("model replicate scheduling is not supported by this protocol version")
        if not policy_study and any(arm.policy is not None for arm in self.arms):
            raise ValueError("legacy studies cannot carry per-arm decision policies")
        if not policy_study and self.analysis.uncertainty != "paired_world_bootstrap":
            raise ValueError("legacy studies retain their world bootstrap contract")
        if policy_study:
            self._validate_policy_assignments()
        checkpoint = self.origin is not None
        if not policy_study and checkpoint != (self.protocol_version == "research-study-v2"):
            raise ValueError("checkpoint origins require the explicit research-study-v2 protocol")
        if checkpoint:
            if self.model.engine_semantics_version < 7:
                raise ValueError("checkpoint studies require persisted random semantics")
            if (len(self.origin.sources) != len(seeds)
                    or {item.seed for item in self.origin.sources} != set(seeds)
                    or len({item.input_key for item in self.origin.sources}) != len(seeds)):
                raise ValueError("each initial-world seed needs one distinct checkpoint input")
            if self.origin.tick + self.time.warmup_ticks >= self.time.intervention_start:
                raise ValueError("checkpoint intervention must follow origin and warmup")
            inputs = {item.key: item for item in self.inputs if item.role == "checkpoint"}
            if set(inputs) != {item.input_key for item in self.origin.sources}:
                raise ValueError("checkpoint sources and declared checkpoint inputs must agree")
        elif any(item.role == "checkpoint" for item in self.inputs):
            raise ValueError("genesis studies cannot declare checkpoint inputs")
        if (self.randomness.pairing != ("verified_common_checkpoint" if checkpoint else "verified_common_genesis")
                or self.analysis.treatment_unit != ("checkpoint_world_pair" if checkpoint else "world_seed_pair")):
            raise ValueError("pairing and treatment unit must match the declared initial conditions")
        keyed = self.model.engine_semantics_version >= 16
        expected_stream = DAILY_STREAM_CONTRACT if keyed else "legacy_shared_rng_v1"
        expected_role = ("checkpoint_origin_seed" if checkpoint else
                         "initial_world_and_keyed_daily_streams" if keyed else "initial_world_and_engine_stream")
        if self.randomness.stream_contract != expected_stream or self.randomness.seed_role != expected_role:
            raise ValueError("randomness declaration does not match the engine semantics")
        outcomes = self.analysis.outcomes
        if not outcomes or len({item.key for item in outcomes}) != len(outcomes):
            raise ValueError("outcome keys must be nonempty and unique")
        primary = [item for item in outcomes if item.purpose == "primary"]
        if not primary:
            raise ValueError("declare at least one primary outcome")
        if self.analysis.multiple_outcome_policy == "single_primary" and len(primary) != 1:
            raise ValueError("single-primary policy requires exactly one primary outcome")
        # Keyed streams remove cross-mechanism cursor drift, but do not establish
        # design adequacy, empirical fitness, power or a held-out hypothesis.
        if self.analysis.intent == "confirmatory":
            raise ValueError("confirmatory execution requires a supported study design beyond its stream contract")
        observed_domains = set()
        for outcome in outcomes:
            definition = metric_definition(outcome.metric)
            if definition is None or definition.version != outcome.metric_version:
                raise ValueError(f"unknown metric/version for outcome {outcome.key}")
            if self.model.engine_semantics_version < definition.min_semantics:
                raise ValueError(f"incompatible engine semantics for outcome {outcome.key}")
            if definition.currency_policy != "currency_neutral" and not outcome.currency:
                raise ValueError(f"declare a currency for outcome {outcome.key}")
            if outcome.aggregation == "window_sum" and (definition.time_basis != "one_tick" or definition.price_kind != "not_price"):
                raise ValueError("only one-tick flows can be summed across a window")
            if outcome.aggregation == "window_vwap" and not outcome.metric.startswith(("goods_vwap:", "equity_vwap:")):
                raise ValueError("window VWAP requires a registered goods or equity execution measure")
            observed_domains.add(definition.domain)
        if not set(self.domains).issubset(observed_domains):
            raise ValueError("each declared price domain requires an outcome")
        inputs = self.inputs
        if len({item.key for item in inputs}) != len(inputs):
            raise ValueError("input artifact keys must be unique")
        fitting = {item.sha256 for item in inputs if item.role in {"initialization", "calibration", "checkpoint"}}
        if any(item.sha256 in fitting for item in inputs if item.role == "holdout"):
            raise ValueError("holdout artifacts must be separate from initialization/calibration")
        if not policy_study and self.operations.mode == "live" and self.behavior.family != "live_llm":
            raise ValueError("live execution requires a declared live LLM policy")
        if self.behavior.family == "live_llm" and self.operations.mode != "live":
            raise ValueError("live LLM policy cannot run with provider-free limits")
        return self

    def _validate_policy_assignments(self) -> None:
        policies = {item.key: item for item in self.policy_design.policies}
        if {arm.policy for arm in self.arms} != set(policies):
            raise ValueError("every arm must reference a declared policy, with no unused policies")
        baseline = next(arm for arm in self.arms if arm.role == "baseline")
        if self.behavior != policies[baseline.policy].behavior:
            raise ValueError("study behavior must identify the declared baseline policy")
        if self.operations.mode != "live":
            raise ValueError("policy studies require one shared live operations budget")
        replicates = self.randomness.model_replicates
        if not 1 <= len(replicates) <= 32 or len(set(replicates)) != len(replicates):
            raise ValueError("declare one to thirty-two distinct model replicate labels")
        for replicate in replicates:
            safe_key(replicate)
        if len(replicates) * len(self.arms) * len(self.randomness.seeds) > 8192:
            raise ValueError("policy study assignment exceeds 8192 cells")
        if self.analysis.uncertainty != "paired_replicated_world_bootstrap":
            raise ValueError("model replicates require world-level replicated uncertainty")
        first_tick = self.origin.tick + 1 if self.origin else 1
        for arm in self.arms:
            if arm.role == "baseline":
                continue
            changed = policies[arm.policy].model_dump(exclude={"key"}) != policies[baseline.policy].model_dump(exclude={"key"})
            if not arm.changes.shocks and not changed:
                raise ValueError("treatment must change its policy or declare an economic shock")
            if changed and (self.time.intervention_start != first_tick or self.time.warmup_ticks):
                raise ValueError("a policy change begins at the first newly executed day")


def reject_inline_secrets(value: Any) -> None:
    """Reject credential fields; use environment references in provider config."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("configuration keys must be strings")
            if re.fullmatch(r"(?i)(api_?key|api_?token|access_token|password|secret|authorization|credential)", key):
                raise ValueError("inline credentials are not allowed in study artifacts")
            reject_inline_secrets(item)
    elif isinstance(value, list):
        for item in value:
            reject_inline_secrets(item)


def load_study(path: str | Path) -> StudySpec:
    return StudySpec.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def validate_study_inputs(spec: StudySpec, config: dict, *, input_root: str | Path) -> dict:
    """Verify declarations and local inputs without creating any artifacts."""
    # Revalidate nested mutable containers before publication.
    spec = StudySpec.model_validate(spec.model_dump(mode="json"))
    reject_inline_secrets(config)
    if digest_json(config) != spec.model.resolved_config_sha256:
        raise ValueError("resolved configuration differs from the study declaration")
    if config.get("engine_semantics_version") != spec.model.engine_semantics_version:
        raise ValueError("study and configuration engine semantics differ")
    root = Path(input_root).resolve()
    for artifact in spec.inputs:
        path = (root / artifact.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"input artifact is outside its declared root or missing: {artifact.key}")
        if artifact.role == "checkpoint" and path.stat().st_size > spec.operations.max_disk_bytes:
            raise ValueError("checkpoint input exceeds its admission size limit")
        if file_sha256(path) != artifact.sha256:
            raise ValueError(f"input artifact hash mismatch: {artifact.key}")
    if config.get("dataset_manifest"):
        dataset_path = Path(config["dataset_manifest"]).resolve()
        declared = {(root / artifact.path).resolve() for artifact in spec.inputs
                    if artifact.role == "initialization"}
        if dataset_path not in declared:
            raise ValueError("the configured dataset manifest must be a pinned initialization artifact")
    description = Path(__file__).resolve().parents[1] / "docs/research/model-description.md"
    protocol = {"kind": "prospective_study", "study": spec.model_dump(mode="json"),
                "resolved_config": config, "model_description_sha256": file_sha256(description),
                "creation_provenance": "prepared_before_attempt_initialization"}
    if spec.policy_design is not None:
        from research.policy_studies import policy_configurations, study_cells
        protocol["policy_configurations"] = policy_configurations(spec, config)
        protocol["assigned_cells"] = study_cells(spec)
    if spec.origin is not None:
        from research.checkpoint_origins import inspect_checkpoint
        declared = {item.key: item for item in spec.inputs}
        origins = {}
        for item in spec.origin.sources:
            artifact = declared[item.input_key]
            receipt = inspect_checkpoint(root / artifact.path, max_bytes=spec.operations.max_disk_bytes,
                                         config={**config, "seed": item.seed})
            if (digest_json(receipt) != item.receipt_sha256 or receipt["database_sha256"] != artifact.sha256
                    or receipt["tick"] != spec.origin.tick or receipt["seed"] != item.seed):
                raise ValueError("checkpoint origin differs from the study declaration")
            origins[str(item.seed)] = receipt
        if len({item["run_id"] for item in origins.values()}) != len(origins):
            raise ValueError("checkpoint replications must have distinct source-world identities")
        protocol["checkpoint_origins"] = origins
        protocol["origin_contract"] = "admitted-state-with-recorded-continuation-v1"
    return protocol


def prepare_study(spec: StudySpec, config: dict, *, input_root: str | Path,
                  data_root: str | Path, out_dir: str | Path) -> dict:
    """Verify declarations, then claim a new immutable, prospective study batch."""
    protocol = validate_study_inputs(spec, config, input_root=input_root)
    attempt_protocol = working_protocol(spec.operations.pause_policy)
    if attempt_protocol:
        protocol["attempt_protocol"] = attempt_protocol
        protocol["timing_contract"] = "cumulative-active-wall-v1"
    description = Path(__file__).resolve().parents[1] / "docs/research/model-description.md"
    sources = {"model-description.md": (description, protocol["model_description_sha256"])}
    for artifact in spec.inputs:
        sources[f"inputs/{artifact.sha256}.blob"] = (
            (Path(input_root) / artifact.path).resolve(), artifact.sha256)
    checkpoints = {item.sha256 for item in spec.inputs if item.role == "checkpoint"}
    ordinary_bytes = sum(path.stat().st_size for path, digest in sources.values() if digest not in checkpoints)
    checkpoint_bytes = sum(path.stat().st_size for path, digest in sources.values() if digest in checkpoints)
    if ordinary_bytes > min(spec.operations.max_disk_bytes, 128 * 1024 * 1024):
        raise ValueError("declared study context exceeds the snapshot size limit")
    # Each source needs a context copy plus source/replay copies for every arm.
    if ordinary_bytes + checkpoint_bytes * (1 + 2 * len(spec.arms)) > spec.operations.max_disk_bytes:
        raise ValueError("checkpoint study cannot fit its initial context and independent arm/replay copies")
    protocol["evidence_snapshot_version"] = "declared-inputs-v1"
    batch = create_batch(spec.key, protocol, data_root=data_root, out_dir=out_dir)
    remaining = spec.operations.max_disk_bytes if checkpoints else min(spec.operations.max_disk_bytes, 128 * 1024 * 1024)
    for name, (source, digest) in sources.items():
        target = Path(batch["data_dir"]) / "context" / name
        publish_copy(target, source, expected_sha256=digest, max_bytes=remaining)
        remaining -= target.stat().st_size
    return batch
