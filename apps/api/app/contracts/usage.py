from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UsageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    image_count: int = Field(ge=0)
    video_seconds: int = Field(ge=0)
    character_count: int = Field(ge=0)
    storage_bytes: int = Field(ge=0)
    charge_amount_minor: int = Field(ge=0)


class UsageEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_id: str
    source: Literal["chat", "generation"]
    modality: str
    model_id: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billable_units: int = Field(ge=0)
    charge_amount_minor: int = Field(ge=0)
    created_at: datetime


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: str
    entry_type: Literal["credit", "debit", "hold", "release", "adjustment"]
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    reference_type: str
    created_at: datetime


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3)
    balance_minor: int = Field(ge=0)
    reserved_minor: int = Field(ge=0)
    totals: UsageTotals
    recent_usage: list[UsageEntryResponse] = Field(max_length=20)
    recent_ledger: list[LedgerEntryResponse] = Field(max_length=20)


__all__ = [
    "LedgerEntryResponse",
    "UsageEntryResponse",
    "UsageSummaryResponse",
    "UsageTotals",
]
