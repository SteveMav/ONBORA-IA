from __future__ import annotations

from collections.abc import Iterable

from apps.ai_core.catalog import CatalogDefinition, ServiceDefinition
from apps.ai_core.contracts.profile import CompanyProfile, Fact
from apps.ai_core.contracts.recommendation import (
    RecommendationItem,
    RecommendationResult,
    RecommendationStatus,
)


def _fact_text(facts: Iterable[Fact]) -> str:
    return " ".join(str(fact.value).casefold() for fact in facts if fact.value is not None)


def _scalar_text(fact: Fact | None) -> str:
    return str(fact.value).casefold() if fact and fact.value is not None else ""


def _source_refs(facts: Iterable[Fact]) -> list[str]:
    return list(dict.fromkeys(ref for fact in facts for ref in fact.source_refs))


def _field_present(profile: CompanyProfile, field_name: str) -> bool:
    value = getattr(profile, field_name, None)
    if isinstance(value, list):
        return bool(value)
    return value is not None and value.value not in (None, "", [])


def _evaluate_service(
    service: ServiceDefinition, profile: CompanyProfile
) -> tuple[RecommendationItem | None, bool]:
    sector = _scalar_text(profile.sector)
    if sector and sector in {item.casefold() for item in service.match.excluded_sectors}:
        return None, True

    searchable_facts = [*profile.needs, *profile.activities, *profile.constraints]
    searchable = _fact_text(searchable_facts)
    matching_needs = [
        keyword for keyword in service.match.need_keywords if keyword.casefold() in searchable
    ]
    matching_sector = bool(
        sector and sector in {item.casefold() for item in service.match.sectors}
    )
    # The V1 never recommends from sector alone: an expressed need is required.
    if not matching_needs:
        return None, False

    missing = [
        field for field in service.match.required_profile_fields if not _field_present(profile, field)
    ]
    local_availability_bonus = 10 if service.rdc_availability == "published_local" else 0
    score = min(100, 60 + (20 if matching_sector else 0) + local_availability_bonus)
    reason_codes = []
    reason_codes.append("NEED_MATCH")
    if matching_sector:
        reason_codes.append("SECTOR_MATCH")
    if service.rdc_availability == "published_local":
        reason_codes.append("PUBLISHED_IN_RDC")
    else:
        reason_codes.append("RDC_AVAILABILITY_TO_CONFIRM")
    if missing:
        reason_codes.append("MISSING_INFORMATION")

    evidence = _source_refs(searchable_facts)
    if profile.sector:
        evidence.extend(profile.sector.source_refs)
    evidence.append(f"catalog:{service.service_id}")
    matched_need = matching_needs[0]
    customer_explanation = (
        f"Cette offre a été retenue parce qu’elle répond à votre besoin exprimé "
        f"autour de « {matched_need} »."
    )
    if matching_sector:
        customer_explanation = (
            f"{customer_explanation[:-1]} et qu’elle est pertinente pour votre secteur."
        )
    return (
        RecommendationItem(
            service_id=service.service_id,
            service_name=service.name,
            service_category=service.category,
            service_description=service.description,
            customer_explanation=customer_explanation,
            benefits=service.allowed_benefits,
            prerequisites=service.prerequisites,
            commercial_terms=service.commercial_terms,
            variant_names=[variant.name for variant in service.variants],
            source_url=service.source_url,
            provider_name=service.provider_name,
            portfolio_scope=service.portfolio_scope,
            portfolio_level=service.portfolio_level,
            rdc_availability=service.rdc_availability,
            availability_note=service.availability_note,
            score=score,
            reason_codes=reason_codes,
            evidence_refs=list(dict.fromkeys(evidence)),
            missing_information=missing,
            requires_human_validation=True,
        ),
        False,
    )


def recommend_services(
    profile: CompanyProfile, catalog: CatalogDefinition
) -> RecommendationResult:
    items: list[RecommendationItem] = []
    rejected: list[str] = []
    for service in catalog.services:
        item, explicitly_rejected = _evaluate_service(service, profile)
        if explicitly_rejected:
            rejected.append(service.service_id)
        elif item:
            items.append(item)

    items.sort(key=lambda item: (-item.score, item.service_id))
    missing = list(
        dict.fromkeys(field for item in items for field in item.missing_information)
    )
    complete_items = [item for item in items if not item.missing_information]
    if complete_items:
        status = RecommendationStatus.RECOMMENDED
    elif items:
        status = RecommendationStatus.NEEDS_INFORMATION
    else:
        status = RecommendationStatus.NO_MATCH

    return RecommendationResult(
        catalog_version=catalog.catalog_version,
        status=status,
        items=items,
        rejected_service_ids=sorted(rejected),
        missing_information=missing,
    )
