from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts.base import ContractModel


MAX_CATALOG_BYTES = 1_000_000


class MatchRules(ContractModel):
    need_keywords: list[str] = Field(min_length=1, max_length=50)
    sectors: list[str] = Field(default_factory=list, max_length=30)
    excluded_sectors: list[str] = Field(default_factory=list, max_length=30)
    required_profile_fields: list[str] = Field(default_factory=list, max_length=20)


class OfferVariant(ContractModel):
    name: str = Field(min_length=1, max_length=160)
    details: list[str] = Field(default_factory=list, max_length=20)


class ServiceDefinition(ContractModel):
    service_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="Autres", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2_000)
    allowed_benefits: list[str] = Field(min_length=1, max_length=20)
    target_customers: list[str] = Field(default_factory=list, max_length=20)
    variants: list[OfferVariant] = Field(default_factory=list, max_length=30)
    commercial_terms: list[str] = Field(default_factory=list, max_length=20)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    source_url: str = Field(default="", max_length=500, pattern=r"^$|^https://")
    source_checked_on: date | None = None
    source_status: Literal["official_page", "official_listing", "official_secondary"] = (
        "official_page"
    )
    provider_name: str = Field(default="Orange Business", min_length=1, max_length=160)
    portfolio_scope: Literal["rdc", "international"] = "rdc"
    portfolio_level: Literal["local_offer", "global_solution_family"] = "local_offer"
    rdc_availability: Literal["published_local", "to_confirm"] = "published_local"
    availability_note: str = Field(default="", max_length=1_000)
    match: MatchRules

    @model_validator(mode="after")
    def geographic_scope_is_consistent(self) -> "ServiceDefinition":
        if self.portfolio_scope == "international":
            if self.portfolio_level != "global_solution_family":
                raise ValueError("international services must be global solution families")
            if self.rdc_availability != "to_confirm":
                raise ValueError("international services cannot be marked as published in RDC")
        if self.rdc_availability == "to_confirm" and not self.availability_note:
            raise ValueError("services whose RDC availability is unconfirmed need a note")
        return self


class CatalogDefinition(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    catalog_version: str = Field(min_length=1, max_length=64)
    status: Literal["draft", "approved"] = "draft"
    source_name: str = Field(default="", max_length=160)
    source_url: str = Field(default="", max_length=500, pattern=r"^$|^https://")
    source_checked_on: date | None = None
    services: list[ServiceDefinition] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_service_ids(self) -> "CatalogDefinition":
        ids = [service.service_id for service in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("service_id values must be unique")
        return self

    @property
    def allowed_service_ids(self) -> set[str]:
        return {service.service_id for service in self.services}


def load_catalog(path: str | Path, *, require_approved: bool = False) -> CatalogDefinition:
    catalog_path = Path(path).resolve()
    if catalog_path.suffix.lower() != ".json":
        raise ValueError("the V1 catalog loader accepts JSON files only")
    if not catalog_path.is_file():
        raise FileNotFoundError(f"catalog not found: {catalog_path}")
    if catalog_path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError("catalog exceeds the 1 MB V1 limit")

    with catalog_path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    catalog = CatalogDefinition.model_validate(raw)
    if require_approved and catalog.status != "approved":
        raise ValueError("catalog must be approved for this operation")
    return catalog
