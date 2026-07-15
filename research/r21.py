"""R21 deterministic initialization from pinned real-U.S. distribution supports.

The records are disclosure-protected public statistical supports, never simulated
identities. Names, personality, beliefs, and relationships remain fictional.
"""
from __future__ import annotations

import bisect
import json
import math
import random
from dataclasses import dataclass, replace
from typing import Any, Iterable

from agents.personas.library import Persona, sample_persona, sample_population
from engine.store import Store


class R21CalibrationError(ValueError):
    pass


def _json_number(value: Any, *, label: str) -> float:
    """Return a finite JSON number without accepting Python's bool coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise R21CalibrationError(f"{label} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise R21CalibrationError(f"{label} must be finite")
    return number


def _json_integer(value: Any, *, label: str) -> int:
    number = _json_number(value, label=label)
    if not number.is_integer():
        raise R21CalibrationError(f"{label} must be an integer")
    return int(number)


def _positive_config_integer(config: dict, key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise R21CalibrationError(f"calibration.{key} must be a positive integer")
    return value


@dataclass(frozen=True)
class HouseholdSample:
    persona: Persona
    family_id: int
    work_status: int
    occupation_category: int
    annual_income_cents: int
    liquid_wealth_cents: int
    net_worth_cents: int

    def provenance(self) -> dict[str, Any]:
        return {
            "annual_income_cents": self.annual_income_cents,
            "family_id": self.family_id,
            "liquid_wealth_cents": self.liquid_wealth_cents,
            "net_worth_cents": self.net_worth_cents,
            "non_liquid_net_worth_cents": (
                self.net_worth_cents - self.liquid_wealth_cents),
            "occupation_category": self.occupation_category,
            "work_status": self.work_status,
        }


@dataclass(frozen=True)
class FirmSizeSample:
    class_code: str
    source_representative_employees: int
    requested_employees: int
    source_firm_count: int

    def provenance(self) -> dict[str, Any]:
        return {
            "class_code": self.class_code,
            "requested_employees": self.requested_employees,
            "source_representative_employees": self.source_representative_employees,
            "source_firm_count": self.source_firm_count,
        }


class _IntegerWeightedSupport:
    def __init__(self, rows: list[dict[str, Any]], weights: Iterable[int], *, label: str):
        self.rows = rows
        self.cumulative: list[int] = []
        total = 0
        for weight in weights:
            if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
                raise R21CalibrationError(f"{label}: weights must be positive integers")
            total += weight
            self.cumulative.append(total)
        if not rows or len(rows) != len(self.cumulative) or total <= 0:
            raise R21CalibrationError(f"{label}: weighted support is empty")
        self.total = total

    def draw(self, prng: random.Random) -> dict[str, Any]:
        point = prng.randrange(self.total)
        return self.rows[bisect.bisect_right(self.cumulative, point)]


class R21Calibration:
    HOUSEHOLD_TRANSFORM = "scf-household-distributions-v1"
    FIRM_TRANSFORM = "susb-firm-size-sector-v1"
    HOUSEHOLD_TARGET = "household_microdata.records"
    FIRM_TARGET = "firm_size_distribution.classes"

    def __init__(self, store: Store, config: dict, seed: int):
        self.store = store
        self.config = config
        self.seed = int(seed)
        cfg = config.get("calibration") or {}
        if not isinstance(cfg, dict):
            raise R21CalibrationError("calibration must be an object")
        self.mode = str(cfg.get("mode", "synthetic")).strip().lower()
        if self.mode not in {"synthetic", "real_us"}:
            raise R21CalibrationError(
                "calibration.mode must be 'synthetic' or 'real_us'")
        self.enabled = self.mode == "real_us"
        self.household_dataset_key = str(
            cfg.get("household_dataset_key", "federal-reserve-scf"))
        self.firm_dataset_key = str(cfg.get("firm_dataset_key", "census-susb"))
        self.max_initial_firm_employees = 50
        self.minimum_wage_per_interval_cents = 50_000
        self.maximum_wage_per_interval_cents = 5_000_000
        self.retirement_age = 65
        self._households: list[dict[str, Any]] = []
        self._firm_classes: list[dict[str, Any]] = []
        self._household_support: _IntegerWeightedSupport | None = None
        self._firm_support: _IntegerWeightedSupport | None = None
        self._sampled_households: list[HouseholdSample] = []
        self._sampled_firms: list[FirmSizeSample] = []
        self._realized_firm_sizes: list[int] = []
        self.sources: list[dict[str, Any]] = []
        if not self.enabled:
            return
        if int(config.get("engine_semantics_version", 1)) < 7:
            raise R21CalibrationError("real_us calibration requires engine semantics 7+")
        self.max_initial_firm_employees = _positive_config_integer(
            cfg, "max_initial_firm_employees", 50)
        self.minimum_wage_per_interval_cents = _positive_config_integer(
            cfg, "minimum_wage_per_interval_cents", 50_000)
        self.maximum_wage_per_interval_cents = _positive_config_integer(
            cfg, "maximum_wage_per_interval_cents", 5_000_000)
        if self.minimum_wage_per_interval_cents > self.maximum_wage_per_interval_cents:
            raise R21CalibrationError(
                "calibration minimum wage must not exceed maximum wage")
        lifecycle = config.get("lifecycle") or {}
        if not isinstance(lifecycle, dict):
            raise R21CalibrationError("lifecycle must be an object")
        retirement_age = lifecycle.get("retirement_age", 65)
        if (isinstance(retirement_age, bool)
                or not isinstance(retirement_age, int)
                or retirement_age <= 0):
            raise R21CalibrationError(
                "lifecycle.retirement_age must be a positive integer")
        self.retirement_age = retirement_age
        self._load()

    def _target(self, dataset_key: str, transform: str, target_key: str) -> tuple[dict, dict]:
        rows = self.store.query(
            "SELECT d.dataset_key,d.source_url,d.retrieval_time,d.release_date,"
            "d.vintage_date,d.checksum_sha256,d.transform_version,d.status,"
            "c.value_json,c.unit,c.dimensions_json,c.id AS target_id "
            "FROM dataset_manifests d JOIN calibration_targets c "
            "ON c.dataset_manifest_id=d.id "
            "WHERE d.dataset_key=? AND c.target_key=? ORDER BY c.id",
            (dataset_key, target_key))
        if not rows:
            raise R21CalibrationError(
                f"missing required calibration target {dataset_key}:{target_key}")
        if len(rows) != 1:
            raise R21CalibrationError(
                f"{dataset_key}:{target_key} must resolve to exactly one target; "
                f"found {len(rows)}")
        row = rows[0]
        if str(row["status"]) != "verified" or str(row["transform_version"]) != transform:
            raise R21CalibrationError(
                f"{dataset_key}: expected verified transform {transform}")
        checksum = str(row["checksum_sha256"]).lower()
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise R21CalibrationError(f"{dataset_key}: invalid persisted checksum")
        try:
            value = json.loads(row["value_json"])
            dimensions = json.loads(row["dimensions_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise R21CalibrationError(f"{dataset_key}: malformed persisted target") from exc
        if not isinstance(value, dict) or not isinstance(dimensions, dict):
            raise R21CalibrationError(f"{dataset_key}: malformed persisted target")
        source = {key: row[key] for key in (
            "dataset_key", "source_url", "retrieval_time", "release_date",
            "vintage_date", "checksum_sha256", "transform_version")}
        source.update({"target_key": target_key, "unit": row["unit"],
                       "dimensions": dimensions})
        return value, source

    def _load(self) -> None:
        household_value, household_source = self._target(
            self.household_dataset_key, self.HOUSEHOLD_TRANSFORM,
            self.HOUSEHOLD_TARGET)
        firm_value, firm_source = self._target(
            self.firm_dataset_key, self.FIRM_TRANSFORM, self.FIRM_TARGET)
        households = household_value.get("records")
        classes = firm_value.get("classes")
        try:
            record_count = _json_integer(
                household_value.get("record_count"), label="SCF record_count")
        except R21CalibrationError as exc:
            raise R21CalibrationError(
                "SCF household support count is malformed") from exc
        if not isinstance(households, list) or record_count != len(households):
            raise R21CalibrationError("SCF household support count is malformed")
        try:
            class_count = _json_integer(
                firm_value.get("class_count"), label="SUSB class_count")
        except R21CalibrationError as exc:
            raise R21CalibrationError(
                "SUSB firm support count is malformed") from exc
        if not isinstance(classes, list) or class_count != len(classes):
            raise R21CalibrationError("SUSB firm support count is malformed")
        for record in households:
            self._validate_household(record)
        for row in classes:
            self._validate_firm_class(row)
        self._households = households
        self._firm_classes = classes
        self._household_support = _IntegerWeightedSupport(
            households,
            [max(1, int(round(_json_number(
                row["weight"], label="SCF weight") * 1_000_000)))
             for row in households], label="SCF household support")
        self._firm_support = _IntegerWeightedSupport(
            classes, [_json_integer(
                row["firm_count"], label="SUSB firm_count") for row in classes],
            label="SUSB firm-size support")
        self.sources = [household_source, firm_source]

    @staticmethod
    def _validate_household(record: Any) -> None:
        required = {
            "family_id", "weight", "age", "dependents", "work_status",
            "occupation_category", "annual_income_dollars",
            "liquid_assets_dollars", "net_worth_dollars",
        }
        if not isinstance(record, dict) or not required <= set(record):
            raise R21CalibrationError("SCF household support record is malformed")
        try:
            family_id = _json_integer(record["family_id"], label="SCF family_id")
            weight = _json_number(record["weight"], label="SCF weight")
            age = _json_integer(record["age"], label="SCF age")
            dependents = _json_integer(record["dependents"], label="SCF dependents")
            work_status = _json_integer(record["work_status"], label="SCF work_status")
            occupation = _json_integer(
                record["occupation_category"], label="SCF occupation_category")
            amounts = [_json_number(record[key], label=f"SCF {key}") for key in (
                "annual_income_dollars", "liquid_assets_dollars",
                "net_worth_dollars")]
        except (KeyError, R21CalibrationError) as exc:
            raise R21CalibrationError("SCF household support record is malformed") from exc
        if (family_id <= 0 or not math.isfinite(weight) or weight <= 0
                or not 18 <= age <= 110 or dependents < 0
                or work_status not in {1, 2, 3, 4}
                or occupation not in {1, 2, 3, 4}):
            raise R21CalibrationError("SCF household support record is out of range")

    @staticmethod
    def _validate_firm_class(row: Any) -> None:
        required = {
            "code", "firm_count", "min_employees", "max_employees",
            "representative_employees",
        }
        if not isinstance(row, dict) or not required <= set(row):
            raise R21CalibrationError("SUSB firm-size support record is malformed")
        try:
            count = _json_integer(row["firm_count"], label="SUSB firm_count")
            lower = _json_integer(row["min_employees"], label="SUSB min_employees")
            representative = _json_integer(
                row["representative_employees"],
                label="SUSB representative_employees")
            upper = (None if row["max_employees"] is None
                     else _json_integer(
                         row["max_employees"], label="SUSB max_employees"))
        except (KeyError, R21CalibrationError) as exc:
            raise R21CalibrationError("SUSB firm-size support record is malformed") from exc
        if (not str(row["code"]) or count <= 0 or lower < 1
                or representative < lower or (upper is not None and
                                               (upper < lower or representative > upper))):
            raise R21CalibrationError("SUSB firm-size support record is out of range")

    def sample_households(
            self, persona_prng: random.Random, size: int, n_outlets: int) -> list[HouseholdSample]:
        if not self.enabled or self._household_support is None:
            raise R21CalibrationError("real_us calibration is not enabled")
        draw_prng = random.Random(self.seed ^ 0x52323148)
        samples: list[HouseholdSample] = []
        for _ in range(size):
            record = self._household_support.draw(draw_prng)
            occupation = _occupation_for(record, self.retirement_age)
            base = sample_persona(
                persona_prng, n_outlets=n_outlets, occupation=occupation)
            income_cents = int(round(float(record["annual_income_dollars"]) * 100))
            liquid_cents = max(
                0, int(round(float(record["liquid_assets_dollars"]) * 100)))
            net_worth_cents = int(round(float(record["net_worth_dollars"]) * 100))
            retired = int(record["age"]) >= self.retirement_age
            persona = replace(
                base,
                age=int(record["age"]),
                occupation=occupation,
                income_cents=income_cents,
                wealth_cents=liquid_cents,
                dependents=int(record["dependents"]),
                extra={**base.extra, "r21_retired": retired},
            )
            samples.append(HouseholdSample(
                persona=persona,
                family_id=int(record["family_id"]),
                work_status=int(record["work_status"]),
                occupation_category=int(record["occupation_category"]),
                annual_income_cents=income_cents,
                liquid_wealth_cents=liquid_cents,
                net_worth_cents=net_worth_cents,
            ))
        self._sampled_households = samples
        return samples

    def sample_firms(self, count: int) -> list[FirmSizeSample]:
        if not self.enabled or self._firm_support is None:
            raise R21CalibrationError("real_us calibration is not enabled")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise R21CalibrationError(
                "real_us calibration requires at least one initial firm")
        prng = random.Random(self.seed ^ 0x52323146)
        samples: list[FirmSizeSample] = []
        for _ in range(count):
            row = self._firm_support.draw(prng)
            samples.append(FirmSizeSample(
                class_code=str(row["code"]),
                source_representative_employees=int(row["representative_employees"]),
                requested_employees=min(
                    self.max_initial_firm_employees,
                    int(row["representative_employees"])),
                source_firm_count=int(row["firm_count"]),
            ))
        self._sampled_firms = samples
        self._realized_firm_sizes = []
        return samples

    def record_realized_firm(
            self, sample: FirmSizeSample, realized_employees: int) -> None:
        """Bind an engine-created headcount to its deterministic source sample."""
        if (isinstance(realized_employees, bool)
                or not isinstance(realized_employees, int)
                or realized_employees < 0):
            raise R21CalibrationError(
                "realized firm headcount must be a non-negative integer")
        index = len(self._realized_firm_sizes)
        if index >= len(self._sampled_firms):
            raise R21CalibrationError(
                "realized firm headcount has no matching calibration sample")
        if self._sampled_firms[index] != sample:
            raise R21CalibrationError(
                "realized firm headcount does not match calibration sample order")
        self._realized_firm_sizes.append(realized_employees)

    def evidence(self) -> dict[str, Any]:
        if not self.enabled or not self._sampled_households:
            raise R21CalibrationError("calibration evidence requires sampled households")
        if not self._sampled_firms:
            raise R21CalibrationError(
                "calibration evidence requires at least one sampled firm")
        if len(self._realized_firm_sizes) != len(self._sampled_firms):
            raise R21CalibrationError(
                "calibration evidence requires one realized headcount per firm sample")
        target_income = [(int(row["annual_income_dollars"]), float(row["weight"]))
                         for row in self._households]
        target_wealth = [(max(0, int(row["liquid_assets_dollars"])),
                          float(row["weight"])) for row in self._households]
        target_net_worth = [(int(row["net_worth_dollars"]), float(row["weight"]))
                            for row in self._households]
        target_firms = [(int(row["representative_employees"]),
                         float(row["firm_count"])) for row in self._firm_classes]
        actual_income = [sample.annual_income_cents // 100
                         for sample in self._sampled_households]
        actual_wealth = [sample.liquid_wealth_cents // 100
                         for sample in self._sampled_households]
        actual_net_worth = [sample.net_worth_cents // 100
                            for sample in self._sampled_households]
        actual_firms = list(self._realized_firm_sizes)

        synthetic = sample_population(
            random.Random(self.seed ^ 0xA11CE), len(self._sampled_households))
        synthetic_income = [persona.income_cents // 100 for persona in synthetic]
        synthetic_wealth = [persona.wealth_cents // 100 for persona in synthetic]
        synthetic_firms = [3 for _ in self._sampled_firms]
        calibrated = {
            "income": _quantile_distance(actual_income, target_income),
            "liquid_wealth": _quantile_distance(actual_wealth, target_wealth),
            "total_net_worth": _quantile_distance(
                actual_net_worth, target_net_worth),
            "firm_size": _quantile_distance(actual_firms, target_firms),
        }
        baseline = {
            "income": _quantile_distance(synthetic_income, target_income),
            "liquid_wealth": _quantile_distance(synthetic_wealth, target_wealth),
            "total_net_worth": _quantile_distance(
                synthetic_wealth, target_net_worth),
            "firm_size": _quantile_distance(synthetic_firms, target_firms),
        }
        calibrated["composite"] = round(sum(calibrated.values()) / 4, 6)
        baseline["composite"] = round(sum(baseline.values()) / 4, 6)
        return {
            "mode": self.mode,
            "households_sampled": len(self._sampled_households),
            "firms_sampled": len(self._sampled_firms),
            "distance": {"real_us": calibrated, "synthetic_baseline": baseline},
            "sources": self.sources,
            "wealth_definition": (
                "SCF LIQ liquid financial assets fund opening deposits; SCF NETWORTH "
                "is authoritative off-ledger calibration state and is not posted as "
                "liquid money"),
        }


def _occupation_for(record: dict[str, Any], retirement_age: int) -> str:
    work_status = int(record["work_status"])
    age = int(record["age"])
    family_id = int(record["family_id"])
    if work_status == 3 and age >= retirement_age:
        return "retiree"
    if work_status == 3:
        # OCCAT1 category 3 also contains disabled respondents under retirement
        # age. Lifecycle state stays engine-owned, so this category cannot retire
        # a younger simulated citizen.
        return "gig_worker"
    if work_status == 4:
        return "student" if age <= 27 else "gig_worker"
    if work_status == 2:
        return "small_business"
    choices = {
        1: ("engineer", "lawyer", "economist", "accountant", "software_dev",
            "doctor", "civil_servant"),
        2: ("teacher", "nurse", "retail_worker", "journalist"),
        3: ("construction", "gig_worker", "retail_worker"),
        4: ("gig_worker",),
    }[int(record["occupation_category"])]
    return choices[family_id % len(choices)]


def _weighted_quantile(values: list[tuple[int, float]], quantile: float) -> float:
    ordered = sorted((int(value), float(weight)) for value, weight in values)
    total = sum(weight for _, weight in ordered)
    if not ordered or not math.isfinite(total) or total <= 0:
        raise R21CalibrationError("calibration distance target support is empty")
    threshold = total * quantile
    upto = 0.0
    for value, weight in ordered:
        if not math.isfinite(weight) or weight <= 0:
            raise R21CalibrationError("calibration distance has an invalid weight")
        upto += weight
        if upto >= threshold:
            return float(value)
    return float(ordered[-1][0])


def _sample_quantile(values: list[int], quantile: float) -> float:
    if not values:
        raise R21CalibrationError("calibration distance sample is empty")
    ordered = sorted(int(value) for value in values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return float(ordered[index])


def _quantile_distance(sample: list[int], target: list[tuple[int, float]]) -> float:
    quantiles = (0.1, 0.25, 0.5, 0.75, 0.9)
    target_values = [_weighted_quantile(target, value) for value in quantiles]
    sample_values = [_sample_quantile(sample, value) for value in quantiles]
    scale = max(1.0, target_values[-1] - target_values[0], abs(target_values[2]))
    return round(sum(abs(left - right) for left, right in zip(
        sample_values, target_values)) / (len(quantiles) * scale), 6)


__all__ = [
    "FirmSizeSample", "HouseholdSample", "R21Calibration",
    "R21CalibrationError",
]
