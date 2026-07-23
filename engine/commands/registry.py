"""Fail-closed command model and handler registration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Type

from pydantic import BaseModel, ValidationError as PydanticValidationError

from .models import (BuyComputePlan, CancelComputePlan, ForwardMessage,
                     LegacyCommand, ReplyMessage, SendMessage,
                     SetComputeSponsorship, StudySkill)


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


def default_registry(known_types: Iterable[str]) -> CommandRegistry:
    registry = CommandRegistry()
    strict_types = set(COMMUNICATION_MODELS) | set(COGNITION_MODELS)
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
    return registry
