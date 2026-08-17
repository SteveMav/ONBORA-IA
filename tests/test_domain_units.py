from pathlib import Path

from apps.ai_core.catalog import CatalogDefinition, MatchRules, ServiceDefinition, load_catalog
from apps.ai_core.contracts import CompanyProfile, CompanyProfilePatch, Fact, FactStatus
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.ai_core.domain import (
    assess_qualification,
    merge_profile,
    qualification_catalog_context,
    recommend_services,
)


ROOT = Path(__file__).parents[1]
CATALOG_PATH = ROOT / "catalog" / "versions" / "v1" / "catalog.json"


def fact(
    value: str | int,
    *,
    status: FactStatus = FactStatus.REPORTED,
    source: str = "message:1",
    confidence: float = 1.0,
    requires_confirmation: bool = False,
) -> Fact:
    return Fact(
        value=value,
        status=status,
        source_refs=[source],
        confidence=confidence,
        requires_confirmation=requires_confirmation,
    )


def service(
    service_id: str,
    *,
    excluded_sectors: list[str] | None = None,
    required_profile_fields: list[str] | None = None,
) -> ServiceDefinition:
    return ServiceDefinition(
        service_id=service_id,
        name=service_id.replace("_", " ").title(),
        description="Service de test",
        allowed_benefits=["Bénéfice autorisé"],
        match=MatchRules(
            need_keywords=["sauvegarde"],
            sectors=["services"],
            excluded_sectors=excluded_sectors or [],
            required_profile_fields=required_profile_fields or [],
        ),
    )


def catalog(*services: ServiceDefinition) -> CatalogDefinition:
    return CatalogDefinition(catalog_version="unit-v1", services=list(services))


def test_reported_scalar_replaces_conflicting_inference_without_conflict() -> None:
    profile = CompanyProfile(
        sector=fact(
            "commerce",
            status=FactStatus.INFERRED,
            source="model:1",
            confidence=0.5,
            requires_confirmation=True,
        )
    )
    patch = CompanyProfilePatch(sector=fact("education", source="message:2"))

    merged = merge_profile(profile, patch)

    assert merged.sector == patch.sector
    assert merged.conflicts == []


def test_confirmed_scalar_is_preserved_and_conflict_is_idempotent() -> None:
    profile = CompanyProfile(
        sector=fact("education", status=FactStatus.CONFIRMED, source="profile_form:1")
    )
    patch = CompanyProfilePatch(sector=fact("commerce", source="message:2"))

    once = merge_profile(profile, patch)
    twice = merge_profile(once, patch)

    assert twice.sector.value == "education"
    assert twice.sector.status == FactStatus.CONFIRMED
    assert len(twice.conflicts) == 1
    assert twice.conflicts[0].incoming.value == "commerce"


def test_equivalent_list_fact_combines_status_sources_and_confirmation_flag() -> None:
    profile = CompanyProfile(
        needs=[
            fact(
                "  Sauvegarde   cloud ",
                status=FactStatus.INFERRED,
                source="model:1",
                confidence=0.4,
            )
        ]
    )
    patch = CompanyProfilePatch(
        needs=[
            fact(
                "sauvegarde cloud",
                status=FactStatus.CONFIRMED,
                source="profile_form:2",
                confidence=0.9,
                requires_confirmation=True,
            )
        ]
    )

    merged = merge_profile(profile, patch)

    assert len(merged.needs) == 1
    assert merged.needs[0].status == FactStatus.CONFIRMED
    assert merged.needs[0].source_refs == ["model:1", "profile_form:2"]
    assert merged.needs[0].confidence == 0.9
    assert merged.needs[0].requires_confirmation is True


def test_excluded_sector_is_rejected_even_when_need_matches() -> None:
    excluded = service("backup_excluded", excluded_sectors=["education"])
    profile = CompanyProfile(
        sector=fact("EDUCATION"),
        needs=[fact("Besoin de sauvegarde quotidienne")],
    )

    result = recommend_services(profile, catalog(excluded))

    assert result.status == RecommendationStatus.NO_MATCH
    assert result.items == []
    assert result.rejected_service_ids == ["backup_excluded"]


def test_matching_sector_without_expressed_need_never_recommends() -> None:
    profile = CompanyProfile(sector=fact("services"))

    result = recommend_services(profile, catalog(service("backup_service")))

    assert result.status == RecommendationStatus.NO_MATCH
    assert result.items == []


def test_equal_scores_are_sorted_by_stable_service_id() -> None:
    reversed_catalog = catalog(service("zeta_backup"), service("alpha_backup"))
    profile = CompanyProfile(
        sector=fact("services", source="message:1"),
        activities=[fact("sauvegarde", source="message:1")],
        needs=[fact("sauvegarde", source="message:2")],
    )

    first = recommend_services(profile, reversed_catalog)
    second = recommend_services(profile, reversed_catalog)

    assert first == second
    assert [item.service_id for item in first.items] == ["alpha_backup", "zeta_backup"]
    assert first.items[0].score == first.items[1].score == 90
    assert first.items[0].evidence_refs == [
        "message:2",
        "message:1",
        "catalog:alpha_backup",
    ]


def test_matching_need_with_missing_required_field_requests_information() -> None:
    profile = CompanyProfile(needs=[fact("sauvegarde externalisée")])
    constrained_catalog = catalog(
        service("backup_service", required_profile_fields=["locations", "size"])
    )

    result = recommend_services(profile, constrained_catalog)

    assert result.status == RecommendationStatus.NEEDS_INFORMATION
    assert result.missing_information == ["locations", "size"]
    assert result.items[0].reason_codes[-1] == "MISSING_INFORMATION"


def test_qualification_without_need_or_catalog_match_stays_not_ready() -> None:
    loaded_catalog = load_catalog(CATALOG_PATH)

    no_need = assess_qualification(CompanyProfile(), loaded_catalog)
    unmatched = assess_qualification(
        CompanyProfile(needs=[fact("construire un entrepôt")]), loaded_catalog
    )

    assert no_need.ready is False
    assert no_need.missing_fields == ("needs",)
    assert no_need.candidate_service_ids == ()
    assert unmatched.ready is False
    assert unmatched.missing_fields == ("needs",)
    assert unmatched.candidate_service_ids == ()
    assert "usage" in unmatched.reason.casefold()


def test_qualification_context_exposes_rules_without_catalog_marketing_fields() -> None:
    context = qualification_catalog_context(catalog(service("backup_service")))

    assert context["services"] == [
        {
            "service_id": "backup_service",
            "name": "Backup Service",
            "need_keywords": ["sauvegarde"],
            "required_profile_fields": [],
            "prerequisites": [],
        }
    ]
    assert "allowed_benefits" not in context["services"][0]
    assert "description" not in context["services"][0]
