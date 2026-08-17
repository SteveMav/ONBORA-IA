import pytest
from pydantic import ValidationError

from apps.ai_core.contracts import (
    CompanyProfile,
    Fact,
    FactStatus,
    QualificationTurnOutput,
    RecommendationItem,
    RecommendationResult,
)
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.reports.contracts import (
    CompanyProfileReport,
    CompanySummary,
    ReportItem,
    ReportStatus,
)


def test_known_fact_requires_a_source() -> None:
    with pytest.raises(ValidationError):
        Fact(value="education", status=FactStatus.REPORTED, confidence=1.0)


def test_fact_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        Fact(
            value="education",
            status=FactStatus.REPORTED,
            source_refs=["message:1"],
            confidence=1.1,
        )


def test_unknown_fact_cannot_carry_a_value() -> None:
    with pytest.raises(ValidationError, match="unknown fact cannot carry a value"):
        Fact(value="invented", status=FactStatus.UNKNOWN, confidence=0)


def test_fact_deduplicates_sources_without_reordering_them() -> None:
    fact = Fact(
        value="education",
        status=FactStatus.CONFIRMED,
        source_refs=["message:2", "message:1", "message:2"],
        confidence=1,
    )

    assert fact.source_refs == ["message:2", "message:1"]


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate({"schema_version": "1.0", "invented": True})


def test_no_match_cannot_contain_items() -> None:
    with pytest.raises(ValidationError):
        RecommendationResult.model_validate(
            {
                "schema_version": "1.0",
                "catalog_version": "v1",
                "status": RecommendationStatus.NO_MATCH,
                "items": [
                    {
                        "service_id": "known_service",
                        "service_name": "Known",
                        "score": 50,
                        "reason_codes": ["TEST"],
                    }
                ],
            }
        )


def test_recommended_status_requires_at_least_one_item() -> None:
    with pytest.raises(ValidationError, match="requires at least one item"):
        RecommendationResult(
            catalog_version="v1",
            status=RecommendationStatus.RECOMMENDED,
        )


def test_recommendation_item_enforces_identifier_url_and_score_bounds() -> None:
    valid = {
        "service_id": "known_service",
        "service_name": "Known",
        "score": 50,
        "reason_codes": ["NEED_MATCH"],
    }
    for invalid in (
        {**valid, "service_id": "INVALID-ID"},
        {**valid, "source_url": "http://not-secure.example"},
        {**valid, "score": 101},
    ):
        with pytest.raises(ValidationError):
            RecommendationItem.model_validate(invalid)


def test_reported_report_item_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="require a source"):
        ReportItem(description="Fait sans preuve", status=FactStatus.REPORTED)


def test_minimal_company_profile_report_is_valid() -> None:
    report = CompanyProfileReport(
        status=ReportStatus.NON_FINAL,
        description="Entreprise test dont le secteur reste à préciser.",
        company_summary=CompanySummary(name="Entreprise test"),
        missing_information=["sector"],
    )
    assert report.schema_version == "1.0"
    assert report.missing_information == ["sector"]


def test_qualification_turn_requires_an_assistant_reply() -> None:
    with pytest.raises(ValidationError):
        QualificationTurnOutput.model_validate(
            {"assistant_message": "", "profile_patch": {"schema_version": "1.0"}}
        )
