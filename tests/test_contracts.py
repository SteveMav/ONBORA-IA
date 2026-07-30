import pytest
from pydantic import ValidationError

from apps.ai_core.contracts import (
    CompanyProfile,
    Fact,
    FactStatus,
    QualificationTurnOutput,
    RecommendationResult,
)
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.reports.contracts import BusinessTwin, ReportStatus, TwinCompanySummary


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


def test_minimal_business_twin_is_valid() -> None:
    twin = BusinessTwin(
        status=ReportStatus.NON_FINAL,
        company_summary=TwinCompanySummary(name="Entreprise test"),
        missing_information=["sector"],
        catalog_version="demo-1.0.0",
    )
    assert twin.schema_version == "1.0"
    assert twin.missing_information == ["sector"]


def test_qualification_turn_requires_an_assistant_reply() -> None:
    with pytest.raises(ValidationError):
        QualificationTurnOutput.model_validate(
            {"assistant_message": "", "profile_patch": {"schema_version": "1.0"}}
        )
