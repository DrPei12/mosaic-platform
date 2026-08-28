from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: Literal["mosaic-api"]
    status: Literal["ok", "ready"]
    version: str = Field(min_length=1)
