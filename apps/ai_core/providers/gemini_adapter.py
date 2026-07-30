from __future__ import annotations

import json
import os
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import ValidationError as PydanticValidationError

from apps.ai_core.contracts import QualificationTurnOutput
from .base import ChatModel, ModelCallResult, ModelError, ModelUsage, T


def _gemini_response_schema(response_model: type[T]) -> dict[str, Any]:
    if response_model is not QualificationTurnOutput:
        return response_model.model_json_schema()

    fact_schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "status": {"type": "string", "enum": ["reported", "inferred"]},
            "source_refs": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "requires_confirmation": {"type": "boolean"},
        },
        "required": ["value", "status", "source_refs", "confidence"],
    }
    profile_properties: dict[str, Any] = {
        field: fact_schema for field in ("name", "sector", "size")
    }
    profile_properties.update(
        {
            field: {"type": "array", "items": fact_schema}
            for field in ("activities", "locations", "needs", "constraints")
        }
    )
    return {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string"},
            "profile_patch": {
                "type": "object",
                "properties": profile_properties,
            },
            "ready_for_analysis": {"type": "boolean"},
            "readiness_reason": {"type": "string"},
        },
        "required": [
            "assistant_message",
            "profile_patch",
            "ready_for_analysis",
            "readiness_reason",
        ],
    }


class GeminiChatModel(ChatModel):
    provider_name = "gemini"

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError("GEMINI_API_KEY is required for the Gemini provider")
        self.model_name = model_name
        # ConversationService owns the two-attempt application policy. Keeping a
        # single SDK attempt prevents hidden retries from exceeding that limit.
        self._client = genai.Client(
            api_key=resolved_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1_000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate_structured(
        self,
        *,
        purpose: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> ModelCallResult[T]:
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=instructions,
                    response_mime_type="application/json",
                    temperature=0,
                    # JSON Schema preserves Pydantic's strict object contract.
                    # The Developer API rejects that contract through the older
                    # OpenAPI-style response_schema transformation.
                    response_json_schema=_gemini_response_schema(response_model),
                    max_output_tokens=4_096,
                ),
            )
            parsed = response.parsed
            output = (
                response_model.model_validate(parsed)
                if parsed is not None
                else response_model.model_validate_json(response.text)
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code == 408:
                raise ModelError("provider_timeout", retryable=True) from exc
            if code == 429:
                raise ModelError("provider_rate_limited", retryable=True) from exc
            if code is not None and code >= 500:
                raise ModelError("provider_unavailable", retryable=True) from exc
            raise ModelError("provider_api_error", retryable=False) from exc
        except (PydanticValidationError, ValueError, TypeError) as exc:
            raise ModelError("invalid_model_output", retryable=False) from exc

        usage = getattr(response, "usage_metadata", None)
        return ModelCallResult(
            output=output,
            usage=ModelUsage(
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
            ),
        )
