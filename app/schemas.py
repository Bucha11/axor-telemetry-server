from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AnonymizedRecord(BaseModel):
    """Wire-format AnonymizedTraceRecord. Stays in lockstep with axor-core contract."""

    signal_chosen: str
    classifier_used: str
    confidence: float = Field(ge=0.0, le=1.0)
    tokens_spent: int = Field(ge=0)
    policy_adjusted: bool

    fingerprint: list[int] | None = None
    fingerprint_kind: str = "none"

    axor_version: str = ""
    schema_version: int = 1

    @field_validator("signal_chosen", "classifier_used", "fingerprint_kind")
    @classmethod
    def _reject_long_strings(cls, v: str) -> str:
        if len(v) > 128:
            raise ValueError("string field exceeds 128 chars")
        return v

    @field_validator("fingerprint")
    @classmethod
    def _cap_fingerprint(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        if len(v) > 512:
            raise ValueError("fingerprint exceeds 512 dims")
        return v


class IngestResponse(BaseModel):
    accepted: int
