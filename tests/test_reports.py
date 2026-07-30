import json
from pathlib import Path

import pytest

from apps.ai_core.catalog import load_catalog
from apps.ai_core.contracts import CompanyProfile, Fact, FactStatus
from apps.ai_core.contracts.recommendation import (
    RecommendationItem,
    RecommendationResult,
    RecommendationStatus,
)
from apps.reports.contracts import ReportStatus
from apps.reports.models import GeneratedReport
from apps.reports.services import ReportBuilder
from apps.reports.services.exports import ReportExportError, build_report_export


ROOT = Path(__file__).parents[1]


def fact(value, status=FactStatus.REPORTED) -> Fact:
    return Fact(value=value, status=status, source_refs=["message:1"], confidence=1.0)


def test_builder_marks_incomplete_twin_non_final() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    profile = CompanyProfile(name=fact("Test"), missing_information=["sector"])
    recommendations = RecommendationResult(
        catalog_version=catalog.catalog_version,
        status=RecommendationStatus.NO_MATCH,
    )
    twin = ReportBuilder(catalog).build_business_twin(profile, recommendations).report
    assert twin.status == ReportStatus.NON_FINAL
    assert twin.missing_information == ["sector"]


def test_builder_rejects_unknown_service_from_authoritative_result() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    recommendations = RecommendationResult(
        catalog_version=catalog.catalog_version,
        status=RecommendationStatus.RECOMMENDED,
        items=[
            RecommendationItem(
                service_id="invented_service",
                service_name="Invented",
                score=100,
                reason_codes=["TEST"],
                evidence_refs=["message:1"],
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown services"):
        ReportBuilder(catalog).build_kam(CompanyProfile(), recommendations)


def test_report_explains_offer_without_internal_reason_codes() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    profile = CompanyProfile(
        name=fact("École Lumière"),
        sector=fact("education"),
        size=fact(25),
        activities=[fact("formation")],
        locations=[fact("Kinshasa")],
        needs=[fact("connexion internet stable")],
    )
    from apps.ai_core.domain import recommend_services

    recommendations = recommend_services(profile, catalog)
    report = ReportBuilder(catalog).build_kam(profile, recommendations).report

    assert "besoin exprimé" in report.opportunities[0].description
    assert "NEED_MATCH" not in report.opportunities[0].description


def test_report_keeps_rdc_availability_warning_for_global_offer() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    profile = CompanyProfile(
        name=fact("Groupe Horizon"),
        sector=fact("services"),
        size=fact(350),
        activities=[fact("services numériques")],
        locations=[fact("Kinshasa"), fact("Johannesburg")],
        needs=[fact("migration cloud hybride")],
        constraints=[fact("résidence des données")],
    )
    from apps.ai_core.domain import recommend_services

    recommendations = recommend_services(profile, catalog)
    report = ReportBuilder(catalog).build_kam(profile, recommendations).report

    assert "disponibilité" in report.opportunities[0].description.casefold()
    assert "RDC" in report.opportunities[0].description


def test_report_exports_use_validated_stored_contract_and_escape_html() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    profile = CompanyProfile(
        name=fact("<script>alert('x')</script>"),
        sector=fact("services"),
        needs=[fact("connectivité")],
    )
    recommendations = RecommendationResult(
        catalog_version=catalog.catalog_version,
        status=RecommendationStatus.NO_MATCH,
    )
    twin = ReportBuilder(catalog).build_business_twin(profile, recommendations).report
    stored = GeneratedReport(
        conversation_id=17,
        report_type=GeneratedReport.ReportType.BUSINESS_TWIN,
        status=twin.status.value,
        schema_version=twin.schema_version,
        data=twin.model_dump(mode="json"),
    )

    json_export = build_report_export(stored, "json")
    assert json.loads(json_export.content) == stored.data
    assert json_export.content_type == "application/json; charset=utf-8"
    assert json_export.disposition == "attachment"

    html_export = build_report_export(stored, "html")
    assert html_export.content_type == "text/html; charset=utf-8"
    assert html_export.disposition == "inline"
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html_export.content
    assert "<script>alert('x')</script>" not in html_export.content
    assert "@media print" in html_export.content


def test_report_export_rejects_unknown_format() -> None:
    stored = GeneratedReport(
        conversation_id=17,
        report_type=GeneratedReport.ReportType.KAM,
        data={},
    )
    with pytest.raises(ReportExportError):
        build_report_export(stored, "pdf")
