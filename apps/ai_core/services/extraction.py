from __future__ import annotations

from pathlib import Path
from time import perf_counter

from django.conf import settings
from django.utils import timezone

from apps.ai_core.contracts import CompanyProfile, QualificationTurnOutput
from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.domain import assess_qualification, qualification_catalog_context
from apps.ai_core.models import AIExecution, Conversation, Message
from apps.ai_core.providers import ChatModel, ModelError


PROMPT_VERSION = "extraction-1.6.0"


class QualificationExtractor:
    def __init__(self, model: ChatModel, catalog: CatalogDefinition) -> None:
        self.model = model
        self.catalog = catalog
        self.qualification_context = qualification_catalog_context(catalog)
        prompt_path = Path(settings.BASE_DIR) / "prompts" / "extraction" / "v1.md"
        self.instructions = prompt_path.read_text(encoding="utf-8")

    def extract(
        self,
        *,
        conversation: Conversation,
        message: Message,
        current_profile: CompanyProfile,
    ) -> QualificationTurnOutput:
        execution = AIExecution.objects.create(
            conversation=conversation,
            message=message,
            purpose="qualification_extraction",
            provider=self.model.provider_name,
            model_name=self.model.model_name,
            prompt_version=PROMPT_VERSION,
        )
        started = perf_counter()
        try:
            recent_messages = list(
                conversation.messages.exclude(pk=message.pk)
                .filter(status=Message.Status.COMPLETED)
                .order_by("-created_at", "-id")
                .values("role", "content")[:12]
            )
            recent_messages.reverse()
            recent_messages = [
                {"role": item["role"], "content": item["content"][:2_000]}
                for item in recent_messages
            ]
            current_profile_data = current_profile.model_dump(mode="json")
            current_assessment = assess_qualification(current_profile, self.catalog)
            # The persisted profile also tracks fields useful to later reports. For the
            # chat, expose only need-specific gaps so the model does not revive a generic
            # company questionnaire (for example by asking a merchant for its headcount).
            current_profile_data["missing_information"] = list(
                current_assessment.missing_fields
            )
            result = self.model.generate_structured(
                purpose="qualification_extraction",
                instructions=self.instructions,
                payload={
                    "message_ref": f"message:{message.pk}",
                    "message": message.content,
                    "conversation_history": recent_messages,
                    "current_profile": current_profile_data,
                    "qualification_context": self.qualification_context,
                },
                response_model=QualificationTurnOutput,
            )
            patch = result.output.profile_patch
            facts = [
                fact
                for fact in [
                    patch.name,
                    patch.sector,
                    patch.size,
                    *patch.activities,
                    *patch.locations,
                    *patch.needs,
                    *patch.constraints,
                ]
                if fact is not None
            ]
            expected_source = f"message:{message.pk}"
            if any(fact.source_refs != [expected_source] for fact in facts):
                raise ModelError("invalid_model_output", retryable=False)
        except ModelError as exc:
            execution.status = AIExecution.Status.FAILED
            execution.error_code = exc.code
            execution.latency_ms = int((perf_counter() - started) * 1000)
            execution.completed_at = timezone.now()
            execution.save(
                update_fields=["status", "error_code", "latency_ms", "completed_at"]
            )
            raise
        except Exception as exc:
            execution.status = AIExecution.Status.FAILED
            execution.error_code = "provider_unexpected_error"
            execution.latency_ms = int((perf_counter() - started) * 1000)
            execution.completed_at = timezone.now()
            execution.save(
                update_fields=["status", "error_code", "latency_ms", "completed_at"]
            )
            raise ModelError("provider_unexpected_error", retryable=False) from exc

        execution.status = AIExecution.Status.SUCCEEDED
        execution.latency_ms = int((perf_counter() - started) * 1000)
        execution.input_tokens = result.usage.input_tokens
        execution.output_tokens = result.usage.output_tokens
        execution.completed_at = timezone.now()
        execution.save(
            update_fields=[
                "status",
                "latency_ms",
                "input_tokens",
                "output_tokens",
                "completed_at",
            ]
        )
        return result.output
