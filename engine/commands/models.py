"""Pydantic models for Semantics 8 communication commands."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class CommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


class LegacyCommand(CommandBase):
    model_config = ConfigDict(extra="allow")


class DirectAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["direct"]
    agent_ids: list[int] = Field(min_length=1, max_length=20)

    @field_validator("agent_ids", mode="before")
    @classmethod
    def positive_unique_ids(cls, value: list[int]) -> list[int]:
        if not isinstance(value, list) or any(
                isinstance(item, bool) or not isinstance(item, int) or item <= 0
                for item in value):
            raise ValueError("direct audience agent ids must be positive integers")
        if len(set(value)) != len(value):
            raise ValueError("direct audience agent ids must be unique")
        return value


class OrganizationAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["organization"]
    organization_kind: Literal["firm", "bank", "government", "outlet"]
    organization_id: Annotated[StrictInt, Field(gt=0)]


class PublicAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["public"]


Audience = Annotated[
    DirectAudience | OrganizationAudience | PublicAudience,
    Field(discriminator="kind"),
]


class SendMessage(CommandBase):
    type: Literal["send_message"]
    audience: Audience
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("subject")
    @classmethod
    def subject_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("subject cannot be blank")
        return value

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body cannot be blank")
        return value


class ReplyMessage(CommandBase):
    type: Literal["reply_message"]
    parent_message_id: Annotated[StrictInt, Field(gt=0)]
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body cannot be blank")
        return value


class ForwardMessage(CommandBase):
    type: Literal["forward_message"]
    source_message_id: Annotated[StrictInt, Field(gt=0)]
    audience: Audience
    note: str = Field(default="", max_length=1000)
