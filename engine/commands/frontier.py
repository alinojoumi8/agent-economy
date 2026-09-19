"""Strict commands for the opt-in frontier contract."""
from typing import Annotated, Literal

from pydantic import Field, StrictInt
from .models import CommandBase


class ExploreSite(CommandBase):
    type: Literal["explore_site"]
    site_id: Annotated[StrictInt, Field(gt=0)]


class FoundSettlement(CommandBase):
    type: Literal["found_settlement"]
    site_id: Annotated[StrictInt, Field(gt=0)]
    name: str = Field(min_length=2, max_length=48)


class BuildSettlement(CommandBase):
    type: Literal["build_settlement"]
    settlement_id: Annotated[StrictInt, Field(gt=0)]


class MoveSettlement(CommandBase):
    type: Literal["move_settlement"]
    settlement_id: Annotated[StrictInt, Field(gt=0)]


class CharterRegion(CommandBase):
    type: Literal["charter_region"]
    settlement_id: Annotated[StrictInt, Field(gt=0)]


FRONTIER_MODELS = {model.model_fields["type"].annotation.__args__[0]: model for model in (
    ExploreSite, FoundSettlement, BuildSettlement, MoveSettlement, CharterRegion)}
