from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import ContractModel


class FactStatus(StrEnum):
    REPORTED = "reported"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


JsonValue = str | int | float | bool | list[str] | None


class Fact(ContractModel):
    value: JsonValue
    status: FactStatus
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = False

    @field_validator("source_refs")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def source_required_for_known_fact(self) -> "Fact":
        if self.status != FactStatus.UNKNOWN and not self.source_refs:
            raise ValueError("a known fact must reference at least one source")
        if self.status == FactStatus.UNKNOWN and self.value is not None:
            raise ValueError("an unknown fact cannot carry a value")
        return self


class FactConflict(ContractModel):
    field_name: str = Field(min_length=1, max_length=100)
    existing: Fact
    incoming: Fact
    resolution_required: bool = True


class CompanyProfile(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    name: Fact | None = None
    sector: Fact | None = None
    size: Fact | None = None
    activities: list[Fact] = Field(default_factory=list, max_length=50)
    locations: list[Fact] = Field(default_factory=list, max_length=20)
    needs: list[Fact] = Field(default_factory=list, max_length=50)
    constraints: list[Fact] = Field(default_factory=list, max_length=50)
    missing_information: list[str] = Field(default_factory=list, max_length=50)
    conflicts: list[FactConflict] = Field(default_factory=list, max_length=50)


class CompanyProfilePatch(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    name: Fact | None = None
    sector: Fact | None = None
    size: Fact | None = None
    activities: list[Fact] = Field(default_factory=list, max_length=20)
    locations: list[Fact] = Field(default_factory=list, max_length=10)
    needs: list[Fact] = Field(default_factory=list, max_length=20)
    constraints: list[Fact] = Field(default_factory=list, max_length=20)


class QualificationTurnOutput(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    assistant_message: str = Field(min_length=1, max_length=2_000)
    profile_patch: CompanyProfilePatch = Field(default_factory=CompanyProfilePatch)
    ready_for_analysis: bool = False
    readiness_reason: str = Field(default="", max_length=500)
