"""Shared strict value contracts for prospective research artifacts."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              allow_inf_nan=False)
