from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from apps.ai_core.contracts.base import ContractModel
from apps.ai_core.contracts.profile import FactStatus


class ReportStatus(StrEnum):
    FINAL = "final"
    NON_FINAL = "non_final"


class ReportItem(ContractModel):
    description: str = Field(min_length=1, max_length=2_000)
    status: FactStatus
    source_refs: list[str] = Field(default_factory=list, max_length=30)
    service_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{2,63}$")

    @model_validator(mode="after")
    def source_or_inference(self) -> "ReportItem":
        if self.status not in {FactStatus.INFERRED, FactStatus.UNKNOWN} and not self.source_refs:
            raise ValueError("reported and confirmed report items require a source")
        return self


class KAMReport(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ReportStatus
    executive_summary: str = Field(min_length=1, max_length=4_000)
    confirmed_facts: list[ReportItem] = Field(default_factory=list, max_length=100)
    reported_facts: list[ReportItem] = Field(default_factory=list, max_length=100)
    inferred_insights: list[ReportItem] = Field(default_factory=list, max_length=100)
    needs: list[ReportItem] = Field(default_factory=list, max_length=100)
    opportunities: list[ReportItem] = Field(default_factory=list, max_length=100)
    points_to_verify: list[ReportItem] = Field(default_factory=list, max_length=100)
    recommended_next_actions: list[ReportItem] = Field(default_factory=list, max_length=50)
    catalog_version: str


class TwinCompanySummary(ContractModel):
    name: str | None = None
    sector: str | None = None
    size: str | None = None
    activities: list[str] = Field(default_factory=list, max_length=50)
    locations: list[str] = Field(default_factory=list, max_length=20)


class BusinessTwin(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ReportStatus
    company_summary: TwinCompanySummary
    current_situation: list[ReportItem] = Field(default_factory=list, max_length=100)
    needs_and_pain_points: list[ReportItem] = Field(default_factory=list, max_length=100)
    business_opportunities: list[ReportItem] = Field(default_factory=list, max_length=100)
    interesting_services: list[ReportItem] = Field(default_factory=list, max_length=50)
    risks_and_constraints: list[ReportItem] = Field(default_factory=list, max_length=100)
    missing_information: list[str] = Field(default_factory=list, max_length=50)
    recommended_next_actions: list[ReportItem] = Field(default_factory=list, max_length=50)
    sources: list[str] = Field(default_factory=list, max_length=200)
    catalog_version: str

