"""Fail-closed command model and handler registration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Type

from pydantic import BaseModel, ValidationError as PydanticValidationError

from .models import (ApplyBusinessPermit, ApplyConstructionPermit,
                     AttendCivicAppointment,
                     BuyComputePlan, CancelComputePlan,
                     CancelConstruction, ContributeConstructionFunding,
                     DecideBusinessPermit, DecideConstructionPermit,
                     ForwardMessage, LegacyCommand, PerformConstructionWork,
                     ProposeConstruction, ReplyMessage, SendMessage,
                     SetComputeSponsorship, StudySkill)
from .models import (CancelHouseholdProposal, ProposeHouseholdMove,
                     ProposePartnership, RespondHousehold, SeparateHousehold, SetTimePlan)
from .models import AcceptEstatePropertyBid, PlaceEstatePropertyBid, WithdrawEstatePropertyBid
from .models import AcceptEstateUnlistedBid, PlaceEstateUnlistedBid, WithdrawEstateUnlistedBid
from .models import ProposePopulationMovement, RespondPopulationMovement


class CommandValidationError(ValueError):
    """Raised when a command is unknown, unavailable, or schema-invalid."""


@dataclass(frozen=True)
class CommandDefinition:
    command_type: str
    model: Type[BaseModel]
    handler_name: str
    introduced_in_semantics: int


class CommandRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, CommandDefinition] = {}

    def register(self, definition: CommandDefinition) -> None:
        if definition.command_type in self._definitions:
            raise CommandValidationError(
                f"duplicate command type: {definition.command_type}")
        self._definitions[definition.command_type] = definition

    def resolve(self, command_type: str, semantics: int) -> CommandDefinition:
        definition = self._definitions.get(command_type)
        if definition is None:
            raise CommandValidationError(f"unknown action type: {command_type}")
        if semantics < definition.introduced_in_semantics:
            raise CommandValidationError(f"unknown action type: {command_type}")
        return definition

    def validate(self, command_type: str, payload: dict, semantics: int) -> tuple[CommandDefinition, dict]:
        definition = self.resolve(command_type, semantics)
        try:
            command = definition.model.model_validate({"type": command_type, **payload})
        except PydanticValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_url=False)
            )
            raise CommandValidationError(detail) from exc
        return definition, command.model_dump(exclude={"type"}, exclude_none=True)

    def definitions(self) -> tuple[CommandDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


COMMUNICATION_MODELS = {
    "send_message": SendMessage,
    "reply_message": ReplyMessage,
    "forward_message": ForwardMessage,
}

COGNITION_MODELS = {
    "buy_compute_plan": BuyComputePlan,
    "cancel_compute_plan": CancelComputePlan,
    "set_compute_sponsorship": SetComputeSponsorship,
    "study_skill": StudySkill,
}

CIVIC_MODELS = {
    "apply_business_permit": ApplyBusinessPermit,
    "attend_civic_appointment": AttendCivicAppointment,
    "decide_business_permit": DecideBusinessPermit,
}

CONSTRUCTION_MODELS = {
    "propose_construction": ProposeConstruction,
    "apply_construction_permit": ApplyConstructionPermit,
    "decide_construction_permit": DecideConstructionPermit,
    "contribute_construction_funding": ContributeConstructionFunding,
    "perform_construction_work": PerformConstructionWork,
    "cancel_construction": CancelConstruction,
}

HOUSEHOLD_MODELS = {
    "propose_partnership": ProposePartnership,
    "propose_household_move": ProposeHouseholdMove,
    "respond_household": RespondHousehold,
    "cancel_household_proposal": CancelHouseholdProposal,
    "separate_household": SeparateHousehold,
}

ESTATE_BID_MODELS = {
    "place_estate_property_bid": PlaceEstatePropertyBid,
    "accept_estate_property_bid": AcceptEstatePropertyBid,
    "withdraw_estate_property_bid": WithdrawEstatePropertyBid,
    "place_estate_unlisted_bid": PlaceEstateUnlistedBid,
    "accept_estate_unlisted_bid": AcceptEstateUnlistedBid,
    "withdraw_estate_unlisted_bid": WithdrawEstateUnlistedBid,
}


POPULATION_MODELS = {
    "propose_population_movement": ProposePopulationMovement,
    "respond_population_movement": RespondPopulationMovement,
}


def default_registry(known_types: Iterable[str]) -> CommandRegistry:
    registry = CommandRegistry()
    legal_mandates = {"request_legal_counsel", "respond_legal_counsel", "end_legal_counsel"}
    strict_types = (
        set(COMMUNICATION_MODELS)
        | set(COGNITION_MODELS)
        | set(CIVIC_MODELS)
        | set(CONSTRUCTION_MODELS)
        | set(HOUSEHOLD_MODELS)
        | {"set_time_plan"}
        | legal_mandates
        | set(ESTATE_BID_MODELS)
        | set(POPULATION_MODELS)
    )
    for command_type in sorted(set(known_types) - strict_types):
        registry.register(CommandDefinition(
            command_type=command_type,
            model=LegacyCommand,
            handler_name=f"_do_{command_type}",
            introduced_in_semantics=1,
        ))
    for command_type, model in COMMUNICATION_MODELS.items():
        registry.register(CommandDefinition(
            command_type=command_type,
            model=model,
            handler_name=f"_do_{command_type}",
            introduced_in_semantics=8,
        ))
    for command_type, model in COGNITION_MODELS.items():
        registry.register(CommandDefinition(
            command_type=command_type,
            model=model,
            handler_name=f"_do_{command_type}",
            introduced_in_semantics=11,
        ))
    for command_type, model in CIVIC_MODELS.items():
        registry.register(CommandDefinition(
            command_type=command_type,
            model=model,
            handler_name=f"_do_{command_type}",
            introduced_in_semantics=12,
        ))
    for command_type, model in CONSTRUCTION_MODELS.items():
        registry.register(CommandDefinition(
            command_type=command_type,
            model=model,
            handler_name=f"_do_{command_type}",
            introduced_in_semantics=13,
        ))
    for command_type, model in HOUSEHOLD_MODELS.items():
        registry.register(CommandDefinition(
            command_type=command_type, model=model,
            handler_name=f"_do_{command_type}", introduced_in_semantics=17,
        ))
    registry.register(CommandDefinition(command_type="set_time_plan", model=SetTimePlan,
        handler_name="_do_set_time_plan", introduced_in_semantics=18))
    for command_type in sorted(legal_mandates):
        registry.register(CommandDefinition(command_type=command_type, model=LegacyCommand,
            handler_name=f"_do_{command_type}", introduced_in_semantics=20))
    for command_type, model in ESTATE_BID_MODELS.items():
        registry.register(CommandDefinition(command_type=command_type, model=model,
            handler_name=f"_do_{command_type}", introduced_in_semantics=20))
    for command_type, model in POPULATION_MODELS.items():
        registry.register(CommandDefinition(command_type=command_type, model=model,
            handler_name=f"_do_{command_type}", introduced_in_semantics=21))
    return registry
