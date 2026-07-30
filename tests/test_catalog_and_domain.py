import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.ai_core.catalog import CatalogDefinition, load_catalog
from apps.ai_core.contracts import CompanyProfile, CompanyProfilePatch, Fact, FactStatus
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.ai_core.domain import assess_qualification, merge_profile, recommend_services


CATALOG_PATH = Path(__file__).parents[1] / "catalog" / "versions" / "v1" / "catalog.json"


def fact(value, *, status=FactStatus.REPORTED, source="message:1") -> Fact:
    return Fact(value=value, status=status, source_refs=[source], confidence=1.0)


def test_orange_business_catalog_loads_and_is_explicitly_draft() -> None:
    catalog = load_catalog(CATALOG_PATH)
    assert catalog.status == "draft"
    assert catalog.catalog_version == "orange-business-rdc-global-2026-07-28"
    assert len(catalog.services) == 41
    assert catalog.source_url == "https://www.orange-business.com/en/products"
    assert all(service.source_url for service in catalog.services)
    assert sum(service.portfolio_scope == "rdc" for service in catalog.services) == 28
    assert sum(service.portfolio_scope == "international" for service in catalog.services) == 13
    assert all(
        service.rdc_availability == "to_confirm"
        for service in catalog.services
        if service.portfolio_scope == "international"
    )
    with pytest.raises(ValueError, match="approved"):
        load_catalog(CATALOG_PATH, require_approved=True)


def test_catalog_rejects_duplicate_service_ids() -> None:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["services"].append(raw["services"][0])
    with pytest.raises(ValidationError, match="unique"):
        CatalogDefinition.model_validate(raw)


def test_catalog_rejects_international_offer_without_availability_warning() -> None:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    service = raw["services"][0]
    service.update(
        {
            "portfolio_scope": "international",
            "portfolio_level": "global_solution_family",
            "rdc_availability": "to_confirm",
            "availability_note": "",
        }
    )
    with pytest.raises(ValidationError, match="need a note"):
        CatalogDefinition.model_validate(raw)


def test_merge_preserves_reported_fact_when_inference_conflicts() -> None:
    profile = CompanyProfile(sector=fact("education"))
    patch = CompanyProfilePatch(
        sector=fact("commerce", status=FactStatus.INFERRED, source="message:2")
    )
    merged = merge_profile(profile, patch)
    assert merged.sector.value == "education"
    assert len(merged.conflicts) == 1


def test_explicit_confirmation_upgrades_same_fact() -> None:
    profile = CompanyProfile(sector=fact("education"))
    patch = CompanyProfilePatch(
        sector=fact("Education", status=FactStatus.CONFIRMED, source="message:2")
    )
    merged = merge_profile(profile, patch)
    assert merged.sector.status == FactStatus.CONFIRMED
    assert merged.sector.source_refs == ["message:1", "message:2"]


def test_patch_merge_is_idempotent_for_list_facts() -> None:
    patch = CompanyProfilePatch(needs=[fact("connexion internet")])
    once = merge_profile(CompanyProfile(), patch)
    twice = merge_profile(once, patch)
    assert len(twice.needs) == 1


def test_matching_is_deterministic_and_tracks_missing_information() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        name=fact("École Test"),
        sector=fact("education"),
        activities=[fact("formation")],
        needs=[fact("connexion internet stable")],
    )
    first = recommend_services(profile, catalog)
    second = recommend_services(profile, catalog)
    assert first == second
    assert first.status == RecommendationStatus.NEEDS_INFORMATION
    assert [item.service_id for item in first.items] == [
        "internet_fibre_illimite"
    ]
    assert first.items[0].missing_information == ["locations", "size"]
    assert first.items[0].service_description.startswith(
        "Accès fibre asymétrique"
    )
    assert "besoin exprimé" in first.items[0].customer_explanation
    assert "Bénéficier d’un accès fibre illimité" in first.items[0].benefits
    assert first.items[0].variant_names == ["Fibre Pro 90", "Fibre Pro 120", "Fibre Intense 350"]
    assert first.items[0].source_url.startswith("https://business.orange.cd/")
    assert first.items[0].prerequisites[0] == "Vérifier l’éligibilité fibre de chaque site"


def test_global_cloud_need_returns_a_family_with_rdc_availability_warning() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        name=fact("Archives Test"),
        sector=fact("services"),
        size=fact(10),
        activities=[fact("gestion documentaire")],
        locations=[fact("Kinshasa")],
        constraints=[fact("résidence des données")],
        needs=[fact("sauvegarde cloud des données")],
    )
    result = recommend_services(profile, catalog)
    assert result.status == RecommendationStatus.RECOMMENDED
    assert [item.service_id for item in result.items] == ["global_cloud_portfolio"]
    assert result.items[0].provider_name == "Orange Business"
    assert result.items[0].portfolio_scope == "international"
    assert result.items[0].rdc_availability == "to_confirm"
    assert "RDC" in result.items[0].availability_note
    assert "RDC_AVAILABILITY_TO_CONFIRM" in result.items[0].reason_codes


def test_global_cyberdefense_managed_services_are_recommendable() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        name=fact("Industrie Test"),
        sector=fact("industry"),
        size=fact(500),
        activities=[fact("production industrielle")],
        locations=[fact("Kinshasa"), fact("Lubumbashi")],
        constraints=[fact("supervision continue")],
        needs=[fact("service sécurité managé avec mdr")],
    )

    result = recommend_services(profile, catalog)

    assert result.status == RecommendationStatus.RECOMMENDED
    managed = next(item for item in result.items if item.service_id == "ocd_managed_services")
    assert managed.provider_name == "Orange Cyberdefense"
    assert "Managed Detection and Response" in managed.variant_names


def test_every_catalog_service_is_reachable_by_its_primary_keyword() -> None:
    catalog = load_catalog(CATALOG_PATH)
    for service in catalog.services:
        sector = service.match.sectors[0] if service.match.sectors else "services"
        profile = CompanyProfile(
            name=fact("Entreprise Test"),
            sector=fact(sector),
            size=fact(25),
            activities=[fact("activité professionnelle")],
            locations=[fact("Kinshasa")],
            needs=[fact(service.match.need_keywords[0])],
        )
        result = recommend_services(profile, catalog)
        assert service.service_id in {item.service_id for item in result.items}, service.service_id


def test_matching_returns_no_match_instead_of_forcing_a_service() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        name=fact("Atelier Test"),
        sector=fact("agriculture"),
        size=fact(4),
        activities=[fact("production agricole")],
        needs=[fact("agrandir un entrepôt")],
    )
    result = recommend_services(profile, catalog)
    assert result.status == RecommendationStatus.NO_MATCH
    assert result.items == []


def test_payment_qualification_does_not_require_company_size_or_location() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        sector=fact("services"),
        activities=[fact("restauration")],
        needs=[fact("paiement numérique")],
    )

    assessment = assess_qualification(profile, catalog)

    assert assessment.ready is True
    assert assessment.missing_fields == ()
    assert "api_orange_money" in assessment.candidate_service_ids


def test_wifi_qualification_asks_only_for_connectivity_dimensions() -> None:
    catalog = load_catalog(CATALOG_PATH)
    profile = CompanyProfile(
        sector=fact("services"),
        activities=[fact("restauration")],
        needs=[fact("connexion internet stable")],
    )

    assessment = assess_qualification(profile, catalog)

    assert assessment.ready is False
    assert assessment.missing_fields == ("locations", "size")
    assert "name" not in assessment.missing_fields
    assert "sector" not in assessment.missing_fields
