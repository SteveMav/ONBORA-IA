import pytest
from django.core.exceptions import ValidationError

from apps.ai_core.contracts import CompanyProfile, RecommendationResult
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.ai_core.models import (
    CompanyProfileSnapshot,
    Conversation,
    Message,
    RecommendationRecord,
)
from apps.reports.contracts import KAMReport, ReportStatus
from apps.reports.models import GeneratedReport


pytestmark = pytest.mark.django_db


def profile_data() -> dict:
    return CompanyProfile().model_dump(mode="json")


def recommendation_data(catalog_version: str = "unit-v1") -> dict:
    return RecommendationResult(
        catalog_version=catalog_version,
        status=RecommendationStatus.NO_MATCH,
    ).model_dump(mode="json")


def create_snapshot(conversation: Conversation) -> CompanyProfileSnapshot:
    return CompanyProfileSnapshot.objects.create(
        conversation=conversation,
        version=1,
        schema_version="1.0",
        data=profile_data(),
        content_hash="a" * 64,
    )


def create_recommendation(
    conversation: Conversation, snapshot: CompanyProfileSnapshot
) -> RecommendationRecord:
    return RecommendationRecord.objects.create(
        conversation=conversation,
        profile_snapshot=snapshot,
        catalog_version="unit-v1",
        input_fingerprint="b" * 64,
        data=recommendation_data(),
    )


def kam_data() -> dict:
    return KAMReport(
        status=ReportStatus.NON_FINAL,
        executive_summary="Rapport de test",
        catalog_version="unit-v1",
    ).model_dump(mode="json")


def test_completed_user_message_rejects_invalid_final_result() -> None:
    conversation = Conversation.objects.create()

    with pytest.raises(ValidationError, match="result_data"):
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content="Message",
            idempotency_key="invalid-result",
            status=Message.Status.COMPLETED,
            result_data={},
        )

    assert Message.objects.count() == 0


def test_profile_snapshot_rejects_schema_version_mismatch() -> None:
    conversation = Conversation.objects.create()

    with pytest.raises(ValidationError, match="does not match profile data"):
        CompanyProfileSnapshot.objects.create(
            conversation=conversation,
            version=1,
            schema_version="2.0",
            data=profile_data(),
            content_hash="a" * 64,
        )

    assert CompanyProfileSnapshot.objects.count() == 0


def test_recommendation_record_rejects_catalog_version_mismatch() -> None:
    conversation = Conversation.objects.create()
    snapshot = create_snapshot(conversation)

    with pytest.raises(ValidationError, match="does not match recommendation data"):
        RecommendationRecord.objects.create(
            conversation=conversation,
            profile_snapshot=snapshot,
            catalog_version="other-v1",
            input_fingerprint="b" * 64,
            data=recommendation_data("unit-v1"),
        )

    assert RecommendationRecord.objects.count() == 0


def test_generated_report_rejects_status_mismatch() -> None:
    conversation = Conversation.objects.create()
    snapshot = create_snapshot(conversation)
    recommendation = create_recommendation(conversation, snapshot)

    with pytest.raises(ValidationError, match="does not match report data"):
        GeneratedReport.objects.create(
            conversation=conversation,
            profile_snapshot=snapshot,
            recommendation=recommendation,
            report_type=GeneratedReport.ReportType.KAM,
            status=GeneratedReport.Status.FINAL,
            schema_version="1.0",
            input_fingerprint="c" * 64,
            data=kam_data(),
        )

    assert GeneratedReport.objects.count() == 0


def test_conversation_delete_cascades_to_all_derived_records() -> None:
    conversation = Conversation.objects.create()
    message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content="Réponse",
        idempotency_key="assistant:1",
        status=Message.Status.COMPLETED,
    )
    snapshot = create_snapshot(conversation)
    recommendation = create_recommendation(conversation, snapshot)
    report = GeneratedReport.objects.create(
        conversation=conversation,
        profile_snapshot=snapshot,
        recommendation=recommendation,
        report_type=GeneratedReport.ReportType.KAM,
        status=GeneratedReport.Status.NON_FINAL,
        schema_version="1.0",
        input_fingerprint="c" * 64,
        data=kam_data(),
    )

    ids = {
        "message": message.pk,
        "snapshot": snapshot.pk,
        "recommendation": recommendation.pk,
        "report": report.pk,
    }
    conversation.delete()

    assert not Message.objects.filter(pk=ids["message"]).exists()
    assert not CompanyProfileSnapshot.objects.filter(pk=ids["snapshot"]).exists()
    assert not RecommendationRecord.objects.filter(pk=ids["recommendation"]).exists()
    assert not GeneratedReport.objects.filter(pk=ids["report"]).exists()
