"""Pydantic models for Semantics 8 communication commands."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class CommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


class LegacyCommand(CommandBase):
    model_config = ConfigDict(extra="allow")


class BuyComputePlan(CommandBase):
    type: Literal["buy_compute_plan"]
    tier: Literal["flash", "premium"]


class CancelComputePlan(CommandBase):
    type: Literal["cancel_compute_plan"]


class SetComputeSponsorship(CommandBase):
    type: Literal["set_compute_sponsorship"]
    tier: Literal["flash", "premium"]
    max_seats: Annotated[StrictInt, Field(ge=1, le=25)]
    firm_id: Annotated[StrictInt, Field(gt=0)] | None = None


class StudySkill(CommandBase):
    type: Literal["study_skill"]
    skill_key: Literal[
        "household_finance", "labor", "commerce", "entrepreneurship",
        "finance", "law", "media", "governance",
    ]


class BusinessIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission: str = Field(min_length=1, max_length=240)
    customer_problem: str = Field(min_length=1, max_length=240)
    offering: str = Field(min_length=1, max_length=160)

    @field_validator("mission", "customer_problem", "offering")
    @classmethod
    def normalized_nonblank_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class ApplyBusinessPermit(CommandBase):
    type: Literal["apply_business_permit"]
    name: str = Field(min_length=1, max_length=60)
    sector: str = Field(min_length=1, max_length=40)
    lawyer_agent_id: Annotated[StrictInt, Field(gt=0)]
    opening_capital: Annotated[StrictInt, Field(ge=0)]
    business_idea: BusinessIdea

    @field_validator("name", "sector")
    @classmethod
    def normalized_label(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class AttendCivicAppointment(CommandBase):
    type: Literal["attend_civic_appointment"]
    appointment_id: Annotated[StrictInt, Field(gt=0)]


class DecideBusinessPermit(CommandBase):
    type: Literal["decide_business_permit"]
    case_id: Annotated[StrictInt, Field(gt=0)]
    decision: Literal["approve", "deny"]
    reason_code: Literal[
        "market_capacity_supported",
        "market_capacity_constrained",
    ]


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
