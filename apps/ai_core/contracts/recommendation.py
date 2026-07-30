from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .base import ContractModel


class RecommendationStatus(StrEnum):
    RECOMMENDED = "recommended"
    NEEDS_INFORMATION = "needs_information"
    NO_MATCH = "no_match"


class RecommendationItem(ContractModel):
    service_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    service_name: str = Field(min_length=1, max_length=160)
    service_category: str = Field(default="", max_length=100)
    service_description: str = Field(default="", max_length=2_000)
    customer_explanation: str = Field(default="", max_length=2_000)
    benefits: list[str] = Field(default_factory=list, max_length=20)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    commercial_terms: list[str] = Field(default_factory=list, max_length=20)
    variant_names: list[str] = Field(default_factory=list, max_length=30)
    source_url: str = Field(default="", max_length=500, pattern=r"^$|^https://")
    provider_name: str = Field(default="Orange Business", min_length=1, max_length=160)
    portfolio_scope: Literal["rdc", "international"] = "rdc"
    portfolio_level: Literal["local_offer", "global_solution_family"] = "local_offer"
    rdc_availability: Literal["published_local", "to_confirm"] = "published_local"
    availability_note: str = Field(default="", max_length=1_000)
    score: int = Field(ge=0, le=100)
    reason_codes: list[str] = Field(min_length=1, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    requires_human_validation: bool = True


class RecommendationResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    catalog_version: str = Field(min_length=1, max_length=64)
    status: RecommendationStatus
    items: list[RecommendationItem] = Field(default_factory=list, max_length=50)
    rejected_service_ids: list[str] = Field(default_factory=list, max_length=50)
    missing_information: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def status_matches_items(self) -> "RecommendationResult":
        if self.status == RecommendationStatus.RECOMMENDED and not self.items:
            raise ValueError("recommended status requires at least one item")
        if self.status == RecommendationStatus.NO_MATCH and self.items:
            raise ValueError("no_match cannot contain recommendation items")
        return self
