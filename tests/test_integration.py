from pathlib import Path

import pytest
from django.core.exceptions import ValidationError

from apps.ai_core.catalog import load_catalog
from apps.ai_core.contracts import (
    CompanyProfile,
    CompanyProfilePatch,
    Fact,
    FactStatus,
    QualificationTurnOutput,
)
from apps.ai_core.models import (
    AIExecution,
    CompanyProfileSnapshot,
    Conversation,
    Message,
    RecommendationRecord,
)
from apps.ai_core.providers import FakeChatModel, HeuristicFakeChatModel, ModelError
from apps.ai_core.services.conversation import ConversationService, ServiceError
from apps.reports.models import GeneratedReport


pytestmark = pytest.mark.django_db
ROOT = Path(__file__).parents[1]


def catalog():
    return load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")


def successful_patch(payload):
    source = payload["message_ref"]

    def fact(value):
        return Fact(
            value=value,
            status=FactStatus.REPORTED,
            source_refs=[source],
            confidence=1.0,
        )

    return QualificationTurnOutput(
        assistant_message="Merci. Quelle contrainte est la plus importante pour vous ?",
        ready_for_analysis=True,
        readiness_reason="Besoin, activité, localisation, taille et nom disponibles.",
        profile_patch=CompanyProfilePatch(
            name=fact("École Lumière"),
            sector=fact("education"),
            size=fact(25),
            activities=[fact("formation professionnelle")],
            locations=[fact("Kinshasa")],
            needs=[fact("connexion internet stable")],
        ),
    )


def service_with(*responses) -> ConversationService:
    return ConversationService(
        model=FakeChatModel({"qualification_extraction": list(responses)}),
        catalog=catalog(),
    )


class UnexpectedFailureModel:
    provider_name = "broken"
    model_name = "broken-v1"

    def generate_structured(self, **kwargs):
        raise RuntimeError("sensitive provider detail")


def test_complete_turn_persists_valid_state_and_sanitized_trace() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    result = service.process_conversation_turn(conversation.pk, "Message de test", "turn-1")

    conversation.refresh_from_db()
    message = Message.objects.get(conversation=conversation, role=Message.Role.USER)
    assistant = Message.objects.get(conversation=conversation, role=Message.Role.ASSISTANT)
    execution = AIExecution.objects.get(conversation=conversation)
    assert conversation.state_version == 1
    assert message.status == Message.Status.COMPLETED
    assert assistant.content == "Merci. Quelle contrainte est la plus importante pour vous ?"
    assert result.assistant_message == assistant.content
    assert result.profile.name.value == "École Lumière"
    assert result.recommendations is None
    assert result.ready_for_analysis is True
    assert conversation.metadata["ready_for_analysis"] is True
    assert CompanyProfileSnapshot.objects.count() == 1
    assert RecommendationRecord.objects.count() == 0
    assert execution.status == AIExecution.Status.SUCCEEDED
    assert not hasattr(execution, "prompt")
    assert "Message de test" not in str(execution.__dict__)


def test_completed_turn_is_replayed_without_second_model_call() -> None:
    fake = FakeChatModel({"qualification_extraction": [successful_patch]})
    service = ConversationService(model=fake, catalog=catalog())
    conversation = service.create_conversation()
    first = service.process_conversation_turn(conversation.pk, "Même message", "same-key")
    second = service.process_conversation_turn(conversation.pk, "Même message", "same-key")
    assert first.message_id == second.message_id
    assert second.replayed is True
    assert len(fake.calls) == 1
    assert CompanyProfileSnapshot.objects.count() == 1


def test_next_model_call_receives_user_and_assistant_history() -> None:
    fake = FakeChatModel(
        {"qualification_extraction": [successful_patch, successful_patch]}
    )
    service = ConversationService(model=fake, catalog=catalog())
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Premier besoin", "turn-1")
    service.process_conversation_turn(conversation.pk, "Deuxième précision", "turn-2")

    history = fake.calls[1]["payload"]["conversation_history"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "Premier besoin"
    assert history[1]["content"].startswith("Merci.")


def test_model_cannot_attribute_new_facts_to_another_message() -> None:
    def wrong_source(payload):
        return QualificationTurnOutput(
            assistant_message="Question suivante ?",
            profile_patch=CompanyProfilePatch(
                needs=[
                    Fact(
                        value="connexion internet",
                        status=FactStatus.REPORTED,
                        source_refs=["message:999"],
                        confidence=1,
                    )
                ]
            ),
        )

    service = service_with(wrong_source)
    conversation = service.create_conversation()
    with pytest.raises(ServiceError) as error:
        service.process_conversation_turn(conversation.pk, "Mon besoin", "bad-source")
    assert error.value.code == "invalid_model_output"
    assert conversation.profile_snapshots.count() == 0
    assert conversation.messages.filter(role=Message.Role.ASSISTANT).count() == 0


def test_reused_key_with_different_content_is_rejected() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Premier", "same-key")
    with pytest.raises(ServiceError) as error:
        service.process_conversation_turn(conversation.pk, "Différent", "same-key")
    assert error.value.code == "idempotency_key_reused_with_different_content"


def test_provider_failure_preserves_state_and_allows_one_retry() -> None:
    service = service_with(ModelError("provider_timeout", retryable=True), successful_patch)
    conversation = service.create_conversation()
    with pytest.raises(ServiceError) as error:
        service.process_conversation_turn(conversation.pk, "Message", "retry-key")
    assert error.value.retryable is True
    conversation.refresh_from_db()
    assert conversation.state_version == 0
    assert CompanyProfileSnapshot.objects.count() == 0
    assert Message.objects.get(role=Message.Role.USER).status == Message.Status.FAILED

    result = service.process_conversation_turn(conversation.pk, "Message", "retry-key")
    assert result.profile.name.value == "École Lumière"
    assert Message.objects.get(role=Message.Role.USER).attempt_count == 2


def test_unexpected_provider_failure_is_normalized_and_trace_is_closed() -> None:
    service = ConversationService(model=UnexpectedFailureModel(), catalog=catalog())
    conversation = service.create_conversation()
    with pytest.raises(ServiceError) as error:
        service.process_conversation_turn(conversation.pk, "Message", "broken-key")
    assert error.value.code == "provider_unexpected_error"
    execution = AIExecution.objects.get()
    assert execution.status == AIExecution.Status.FAILED
    assert execution.error_code == "provider_unexpected_error"
    assert "sensitive provider detail" not in str(execution.__dict__)


def test_message_attempts_are_bounded_to_two() -> None:
    error = ModelError("provider_timeout", retryable=True)
    service = service_with(error, error)
    conversation = service.create_conversation()
    for _ in range(2):
        with pytest.raises(ServiceError):
            service.process_conversation_turn(conversation.pk, "Message", "retry-key")
    with pytest.raises(ServiceError) as final_error:
        service.process_conversation_turn(conversation.pk, "Message", "retry-key")
    assert final_error.value.code == "message_attempt_limit_reached"


def test_reports_are_schema_valid_and_idempotent() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Message", "turn-1")
    service.analyze_conversation(conversation.pk)

    kam = service.generate_report(conversation.pk, "kam")
    twin = service.generate_report(conversation.pk, "business_twin")
    replay = service.generate_report(conversation.pk, "kam")

    assert kam.status == "final"
    assert twin.data["company_summary"]["name"] == "École Lumière"
    assert {item["service_id"] for item in twin.data["interesting_services"]} <= catalog().allowed_service_ids
    assert replay.report_id == kam.report_id
    assert replay.replayed is True
    assert GeneratedReport.objects.count() == 2


def test_confirmed_profile_replaces_draft_and_recomputes_recommendations() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Message", "turn-1")
    service.analyze_conversation(conversation.pk)

    profile = service.confirm_company_profile(
        conversation.pk,
        name="École Lumière corrigée",
        sector="education",
        size=30,
        activities=["formation professionnelle"],
        locations=["Kinshasa", "Matadi"],
        needs=["connexion internet stable"],
        constraints=["budget annuel"],
    )

    conversation.refresh_from_db()
    assert conversation.state_version == 2
    assert profile.name.value == "École Lumière corrigée"
    assert profile.name.status == FactStatus.CONFIRMED
    assert profile.name.source_refs == [f"profile_form:{conversation.pk}:2"]
    assert profile.locations[1].value == "Matadi"
    assert CompanyProfileSnapshot.objects.count() == 2
    assert RecommendationRecord.objects.count() == 2


def test_invalid_profile_json_is_rejected_before_persistence() -> None:
    conversation = Conversation.objects.create()
    with pytest.raises(ValidationError):
        CompanyProfileSnapshot.objects.create(
            conversation=conversation,
            version=1,
            data={"schema_version": "1.0", "invented": True},
            content_hash="0" * 64,
        )


def test_conversation_version_conflict_does_not_create_snapshot() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content="Message",
        idempotency_key="conflict",
        attempt_count=1,
    )
    Conversation.objects.filter(pk=conversation.pk).update(state_version=1)
    profile = CompanyProfile(name=Fact(value="Test", status=FactStatus.REPORTED, source_refs=["message:1"], confidence=1))
    with pytest.raises(ServiceError) as error:
        service._commit_turn(
            conversation=conversation,
            message=message,
            base_version=0,
            profile=profile,
            assistant_message="Question suivante ?",
            ready_for_analysis=True,
            readiness_reason="Dossier complet.",
        )
    assert error.value.code == "conversation_version_conflict"
    assert CompanyProfileSnapshot.objects.count() == 0
    message.refresh_from_db()
    assert message.status == Message.Status.FAILED


def test_analysis_is_rejected_until_model_marks_conversation_ready() -> None:
    response = QualificationTurnOutput(
        assistant_message="Quelle est votre activité principale ?",
        ready_for_analysis=False,
        readiness_reason="L’activité et la taille manquent.",
    )
    service = service_with(response)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Je cherche internet.", "turn-1")

    with pytest.raises(ServiceError) as error:
        service.analyze_conversation(conversation.pk)

    assert error.value.code == "conversation_not_ready"
    assert RecommendationRecord.objects.count() == 0


def test_analysis_is_explicit_and_idempotent() -> None:
    service = service_with(successful_patch)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Message", "turn-1")

    first = service.analyze_conversation(conversation.pk)
    second = service.analyze_conversation(conversation.pk)

    assert first == second
    assert first.items[0].service_id == "internet_fibre_illimite"
    assert RecommendationRecord.objects.count() == 1
    analysis_messages = Message.objects.filter(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        idempotency_key__startswith="analysis:",
    )
    assert analysis_messages.count() == 1
    assert "offres Orange" in analysis_messages.get().content
    assert "Internet illimité Fibre" in analysis_messages.get().content


def test_same_profile_can_be_analyzed_again_on_a_new_snapshot() -> None:
    unchanged_turn = QualificationTurnOutput(
        assistant_message="Le dossier est toujours complet.",
        ready_for_analysis=True,
        readiness_reason="Toutes les informations sont présentes.",
    )
    service = service_with(successful_patch, unchanged_turn)
    conversation = service.create_conversation()
    service.process_conversation_turn(conversation.pk, "Description complète", "turn-1")
    service.analyze_conversation(conversation.pk)
    first_snapshot = conversation.profile_snapshots.order_by("-version").first()

    service.process_conversation_turn(conversation.pk, "Je confirme.", "turn-2")
    second_snapshot = conversation.profile_snapshots.order_by("-version").first()
    assert second_snapshot.content_hash == first_snapshot.content_hash

    service.analyze_conversation(conversation.pk)

    assert RecommendationRecord.objects.count() == 2
    assert first_snapshot.recommendation_records.count() == 1
    assert second_snapshot.recommendation_records.count() == 1


def test_restaurant_payment_flow_is_ready_without_employee_count() -> None:
    service = ConversationService(model=HeuristicFakeChatModel(), catalog=catalog())
    conversation = service.create_conversation()

    result = service.process_conversation_turn(
        conversation.pk,
        "Nous sommes un restaurant et voulons accepter les paiements Orange Money sur notre application.",
        "restaurant-payment",
    )

    assert result.ready_for_analysis is True
    assert result.profile.activities[0].value == "restauration"
    assert result.profile.size is None
    assert result.profile.locations == []
    assert "personnes" not in result.assistant_message.casefold()
    assert "employ" not in result.assistant_message.casefold()


def test_restaurant_wifi_flow_asks_location_before_dimensioning() -> None:
    service = ConversationService(model=HeuristicFakeChatModel(), catalog=catalog())
    conversation = service.create_conversation()

    result = service.process_conversation_turn(
        conversation.pk,
        "Nous sommes un restaurant et voulons du Wi-Fi pour nos clients.",
        "restaurant-wifi",
    )

    assert result.ready_for_analysis is False
    assert result.profile.size is None
    assert "site ou quelle ville" in result.assistant_message
    assert result.readiness_reason == "Il reste à préciser la localisation du site concerné, puis le nombre de personnes ou d’appareils à connecter."
