import json
from types import SimpleNamespace

import pytest

from apps.ai_core.contracts import CompanyProfilePatch, FactStatus, QualificationTurnOutput
from apps.ai_core.providers import (
    FakeChatModel,
    GeminiChatModel,
    HeuristicFakeChatModel,
    ModelError,
)
from apps.ai_core.providers.gemini_adapter import _gemini_response_schema


def test_fake_returns_validated_structured_output() -> None:
    fake = FakeChatModel(
        {"qualification_extraction": [{"schema_version": "1.0", "needs": []}]}
    )
    result = fake.generate_structured(
        purpose="qualification_extraction",
        instructions="test",
        payload={},
        response_model=CompanyProfilePatch,
    )
    assert isinstance(result.output, CompanyProfilePatch)
    assert len(fake.calls) == 1


def test_fake_normalizes_malformed_output_to_typed_error() -> None:
    fake = FakeChatModel({"qualification_extraction": [{"unknown": True}]})
    with pytest.raises(ModelError) as error:
        fake.generate_structured(
            purpose="qualification_extraction",
            instructions="test",
            payload={},
            response_model=CompanyProfilePatch,
        )
    assert error.value.code == "invalid_model_output"


def test_heuristic_fake_extracts_demo_fields_without_network() -> None:
    fake = HeuristicFakeChatModel()
    result = fake.generate_structured(
        purpose="qualification_extraction",
        instructions="test",
        payload={
            "message_ref": "message:7",
            "message": "Notre entreprise École Lumière, une école de formation à Kinshasa avec 25 employés, a besoin d’internet.",
        },
        response_model=CompanyProfilePatch,
    )
    assert result.output.name.value == "École Lumière"
    assert result.output.sector.value == "education"
    assert result.output.size.value == 25
    assert result.output.locations[0].value == "Kinshasa"
    assert result.output.activities[0].value == "formation professionnelle"
    assert result.output.needs[0].status == FactStatus.REPORTED


def test_heuristic_fake_returns_a_conversational_reply() -> None:
    fake = HeuristicFakeChatModel()
    result = fake.generate_structured(
        purpose="qualification_extraction",
        instructions="test",
        payload={
            "message_ref": "message:8",
            "message": "Bonjour, je cherche à mieux sécuriser mes données.",
            "current_profile": {},
            "conversation_history": [],
        },
        response_model=QualificationTurnOutput,
    )
    assert result.output.profile_patch.needs[0].value == "renforcement de la cybersécurité"
    assert result.output.assistant_message == "Je comprends mieux votre besoin. Quelle est votre activité principale ?"
    assert result.output.ready_for_analysis is False


def test_gemini_adapter_fails_closed_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiChatModel(model_name="gemini-3.5-flash-lite")


def test_gemini_adapter_uses_pydantic_structured_output() -> None:
    adapter = GeminiChatModel(model_name="gemini-3.5-flash-lite", api_key="test-key")
    captured = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            parsed=CompanyProfilePatch(),
            text="{}",
            usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=4),
        )

    adapter._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result = adapter.generate_structured(
        purpose="qualification_extraction",
        instructions="strict",
        payload={"message": "fictif"},
        response_model=CompanyProfilePatch,
    )
    assert result.output == CompanyProfilePatch()
    assert result.usage.input_tokens == 12
    assert captured["model"] == "gemini-3.5-flash-lite"
    assert captured["config"].response_schema is None
    assert captured["config"].response_json_schema == CompanyProfilePatch.model_json_schema()
    assert captured["config"].response_mime_type == "application/json"
    assert captured["config"].temperature == 0


def test_gemini_qualification_schema_avoids_unsupported_object_keywords() -> None:
    schema = _gemini_response_schema(QualificationTurnOutput)
    serialized = json.dumps(schema)
    assert "additionalProperties" not in serialized
    assert schema["required"] == [
        "assistant_message",
        "profile_patch",
        "ready_for_analysis",
        "readiness_reason",
    ]
    assert schema["properties"]["profile_patch"]["type"] == "object"
