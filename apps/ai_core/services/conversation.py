from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ai_core.catalog import CatalogDefinition, load_catalog
from apps.ai_core.contracts import (
    CompanyProfile,
    GeneratedReportResult,
    Fact,
    FactStatus,
    RecommendationResult,
    TurnResult,
)
from apps.ai_core.contracts.profile import CompanyProfilePatch
from apps.ai_core.domain import assess_qualification, merge_profile, recommend_services
from apps.ai_core.models import (
    CompanyProfileSnapshot,
    Conversation,
    Message,
    RecommendationRecord,
)
from apps.ai_core.providers import ChatModel, ModelError
from apps.reports.models import GeneratedReport
from apps.reports.services import ReportBuilder
from .extraction import QualificationExtractor


MAX_MESSAGE_LENGTH = 20_000
MAX_IDEMPOTENCY_KEY_LENGTH = 100
MAX_PROCESSING_ATTEMPTS = 2


class ServiceError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class _PreparedMessage:
    message: Message
    replay: TurnResult | None = None


def _fingerprint(*values: object) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConversationService:
    def __init__(
        self,
        *,
        model: ChatModel,
        catalog: CatalogDefinition | None = None,
    ) -> None:
        self.catalog = catalog or load_catalog(settings.ONBORA_CATALOG_PATH)
        self.extractor = QualificationExtractor(model, self.catalog)
        self.report_builder = ReportBuilder(self.catalog)

    def create_conversation(self, *, metadata: dict[str, object] | None = None) -> Conversation:
        return Conversation.objects.create(metadata=metadata or {})

    def confirm_company_profile(
        self,
        conversation_id: int,
        *,
        name: str,
        sector: str,
        size: int | None,
        activities: list[str],
        locations: list[str],
        needs: list[str],
        constraints: list[str],
    ) -> CompanyProfile:
        """Replace the current draft with the facts explicitly confirmed in the form."""
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist as exc:
            raise ServiceError("conversation_not_found") from exc
        if conversation.status != Conversation.Status.ACTIVE:
            raise ServiceError("conversation_not_active")
        current_snapshot = conversation.profile_snapshots.order_by("-version").first()
        if current_snapshot is None or not current_snapshot.recommendation_records.exists():
            raise ServiceError("conversation_not_analyzed")

        scalar_values = [name, sector]
        list_values = [*activities, *locations, *needs, *constraints]
        if any(len(value) > 500 for value in [*scalar_values, *list_values]):
            raise ServiceError("invalid_company_profile")
        if any(len(values) > 50 for values in (activities, locations, needs, constraints)):
            raise ServiceError("invalid_company_profile")
        if size is not None and not 1 <= size <= 10_000_000:
            raise ServiceError("invalid_company_profile")

        base_version = conversation.state_version
        source_ref = f"profile_form:{conversation.pk}:{base_version + 1}"

        def fact(value: str | int) -> Fact:
            return Fact(
                value=value,
                status=FactStatus.CONFIRMED,
                source_refs=[source_ref],
                confidence=1.0,
                requires_confirmation=False,
            )

        patch = CompanyProfilePatch(
            name=fact(name) if name else None,
            sector=fact(sector) if sector else None,
            size=fact(size) if size is not None else None,
            activities=[fact(value) for value in activities],
            locations=[fact(value) for value in locations],
            needs=[fact(value) for value in needs],
            constraints=[fact(value) for value in constraints],
        )
        profile = merge_profile(CompanyProfile(), patch, catalog=self.catalog)
        recommendations = recommend_services(profile, self.catalog)
        profile_data = profile.model_dump(mode="json")
        profile_hash = _fingerprint(profile_data)
        recommendation_data = recommendations.model_dump(mode="json")
        recommendation_fingerprint = _fingerprint(profile_hash, recommendation_data)

        with transaction.atomic():
            updated = Conversation.objects.filter(
                pk=conversation.pk,
                state_version=base_version,
            ).update(state_version=base_version + 1, updated_at=timezone.now())
            if updated != 1:
                raise ServiceError("conversation_version_conflict", retryable=True)
            snapshot = CompanyProfileSnapshot.objects.create(
                conversation=conversation,
                version=base_version + 1,
                schema_version=profile.schema_version,
                data=profile_data,
                content_hash=profile_hash,
            )
            RecommendationRecord.objects.create(
                conversation=conversation,
                profile_snapshot=snapshot,
                catalog_version=recommendations.catalog_version,
                input_fingerprint=recommendation_fingerprint,
                data=recommendation_data,
            )
        return profile

    def _current_profile(self, conversation: Conversation) -> CompanyProfile:
        snapshot = conversation.profile_snapshots.order_by("-version").first()
        if snapshot:
            return CompanyProfile.model_validate(snapshot.data)
        return merge_profile(CompanyProfile(), CompanyProfilePatch(), catalog=self.catalog)

    def _prepare_message(
        self, conversation: Conversation, text: str, idempotency_key: str
    ) -> _PreparedMessage:
        text = text.strip()
        idempotency_key = idempotency_key.strip()
        if not text or len(text) > MAX_MESSAGE_LENGTH:
            raise ServiceError("invalid_message")
        if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ServiceError("invalid_idempotency_key")

        try:
            message, created = Message.objects.get_or_create(
                conversation=conversation,
                idempotency_key=idempotency_key,
                defaults={
                    "role": Message.Role.USER,
                    "content": text,
                    "status": Message.Status.PROCESSING,
                    "attempt_count": 1,
                },
            )
        except IntegrityError:
            message = Message.objects.get(
                conversation=conversation, idempotency_key=idempotency_key
            )
            created = False

        if created:
            return _PreparedMessage(message=message)
        if message.content != text:
            raise ServiceError("idempotency_key_reused_with_different_content")
        if message.status == Message.Status.COMPLETED:
            replay = TurnResult.model_validate(message.result_data).model_copy(
                update={"replayed": True}
            )
            return _PreparedMessage(message=message, replay=replay)
        if message.status == Message.Status.PROCESSING:
            raise ServiceError("message_already_processing", retryable=True)
        if message.attempt_count >= MAX_PROCESSING_ATTEMPTS:
            raise ServiceError("message_attempt_limit_reached")
        message.status = Message.Status.PROCESSING
        message.attempt_count += 1
        message.error_code = ""
        message.save(update_fields=["status", "attempt_count", "error_code", "updated_at"])
        return _PreparedMessage(message=message)

    def process_conversation_turn(
        self,
        conversation_id: int,
        text: str,
        idempotency_key: str,
    ) -> TurnResult:
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist as exc:
            raise ServiceError("conversation_not_found") from exc
        if conversation.status != Conversation.Status.ACTIVE:
            raise ServiceError("conversation_not_active")

        prepared = self._prepare_message(conversation, text, idempotency_key)
        if prepared.replay:
            return prepared.replay
        message = prepared.message
        base_version = conversation.state_version
        current_profile = self._current_profile(conversation)

        try:
            model_turn = self.extractor.extract(
                conversation=conversation,
                message=message,
                current_profile=current_profile,
            )
            merged_profile = merge_profile(
                current_profile,
                model_turn.profile_patch,
                catalog=self.catalog,
            )
            assessment = assess_qualification(merged_profile, self.catalog)
            assistant_message = model_turn.assistant_message
            if assessment.ready and not model_turn.ready_for_analysis:
                assistant_message = (
                    "J’ai les informations utiles pour ce besoin. "
                    "Vous pouvez lancer l’analyse quand vous le souhaitez."
                )
            elif model_turn.ready_for_analysis and not assessment.ready:
                assistant_message = (
                    "Merci, je comprends mieux. "
                    f"{assessment.reason}"
                )
            result = self._commit_turn(
                conversation=conversation,
                message=message,
                base_version=base_version,
                profile=merged_profile,
                assistant_message=assistant_message,
                ready_for_analysis=assessment.ready,
                readiness_reason=assessment.reason,
            )
        except ModelError as exc:
            self._mark_message_failed(message, exc.code)
            raise ServiceError(exc.code, retryable=exc.retryable) from exc
        except ServiceError:
            raise
        except Exception:
            self._mark_message_failed(message, "turn_processing_failed")
            raise
        return result

    @staticmethod
    def _mark_message_failed(message: Message, code: str) -> None:
        Message.objects.filter(pk=message.pk).update(
            status=Message.Status.FAILED,
            error_code=code,
            updated_at=timezone.now(),
        )

    def _commit_turn(
        self,
        *,
        conversation: Conversation,
        message: Message,
        base_version: int,
        profile: CompanyProfile,
        assistant_message: str,
        ready_for_analysis: bool,
        readiness_reason: str,
    ) -> TurnResult:
        profile_data = profile.model_dump(mode="json")
        profile_hash = _fingerprint(profile_data)
        metadata = dict(conversation.metadata)
        metadata.update(
            {
                "ready_for_analysis": ready_for_analysis,
                "readiness_reason": readiness_reason,
            }
        )

        try:
            with transaction.atomic():
                updated = Conversation.objects.filter(
                    pk=conversation.pk, state_version=base_version
                ).update(
                    state_version=base_version + 1,
                    metadata=metadata,
                    updated_at=timezone.now(),
                )
                if updated != 1:
                    raise ServiceError("conversation_version_conflict", retryable=True)
                snapshot = CompanyProfileSnapshot.objects.create(
                    conversation=conversation,
                    version=base_version + 1,
                    schema_version=profile.schema_version,
                    data=profile_data,
                    content_hash=profile_hash,
                )
                result = TurnResult(
                    conversation_id=conversation.pk,
                    message_id=message.pk,
                    profile_snapshot_id=snapshot.pk,
                    profile=profile,
                    assistant_message=assistant_message,
                    ready_for_analysis=ready_for_analysis,
                    readiness_reason=readiness_reason,
                )
                message.status = Message.Status.COMPLETED
                message.error_code = ""
                message.result_data = result.model_dump(mode="json")
                message.save(
                    update_fields=["status", "error_code", "result_data", "updated_at"]
                )
                Message.objects.create(
                    conversation=conversation,
                    role=Message.Role.ASSISTANT,
                    content=assistant_message,
                    idempotency_key=f"assistant:{message.pk}",
                    status=Message.Status.COMPLETED,
                    attempt_count=1,
                )
        except ServiceError:
            self._mark_message_failed(message, "conversation_version_conflict")
            raise
        return result

    def analyze_conversation(self, conversation_id: int) -> RecommendationResult:
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist as exc:
            raise ServiceError("conversation_not_found") from exc
        if conversation.status != Conversation.Status.ACTIVE:
            raise ServiceError("conversation_not_active")
        if not conversation.metadata.get("ready_for_analysis", False):
            raise ServiceError("conversation_not_ready")

        snapshot = conversation.profile_snapshots.order_by("-version").first()
        if snapshot is None:
            raise ServiceError("conversation_has_no_profile")
        profile = CompanyProfile.model_validate(snapshot.data)
        recommendations = recommend_services(profile, self.catalog)
        recommendation_data = recommendations.model_dump(mode="json")
        input_fingerprint = _fingerprint(
            snapshot.content_hash,
            recommendation_data,
        )
        try:
            record, _ = RecommendationRecord.objects.get_or_create(
                conversation=conversation,
                profile_snapshot=snapshot,
                catalog_version=recommendations.catalog_version,
                input_fingerprint=input_fingerprint,
                defaults={"data": recommendation_data},
            )
        except DjangoValidationError:
            # Model.save() validates uniqueness before INSERT, so a concurrent
            # identical analysis can surface ValidationError instead of IntegrityError.
            record = RecommendationRecord.objects.filter(
                profile_snapshot=snapshot,
                input_fingerprint=input_fingerprint,
            ).first()
            if record is None:
                raise

        validated = RecommendationResult.model_validate(record.data)
        Message.objects.get_or_create(
            conversation=conversation,
            idempotency_key=f"analysis:{record.pk}",
            defaults={
                "role": Message.Role.ASSISTANT,
                "content": self._customer_offer_message(validated),
                "status": Message.Status.COMPLETED,
                "attempt_count": 1,
            },
        )
        return validated

    def _customer_offer_message(
        self,
        recommendations: RecommendationResult,
    ) -> str:
        if not recommendations.items:
            return (
                "J’ai analysé votre situation. Pour le moment, aucune offre du catalogue "
                "Orange disponible ne correspond suffisamment à votre besoin. Un conseiller "
                "pourra reprendre votre demande sans vous orienter vers une offre inadaptée."
            )

        lines = [
            "J’ai analysé votre situation. Voici les offres Orange qui semblent les plus "
            "adaptées à votre besoin :"
        ]
        for item in recommendations.items[:5]:
            description = item.service_description or "Solution du catalogue Orange."
            lines.append(f"• {item.service_name} — {description}")
            if item.benefits:
                lines.append(f"  Ce que cela peut vous apporter : {item.benefits[0]}.")
        lines.append(
            "Ces propositions viennent de vos réponses et du catalogue disponible. "
            "Elles devront être confirmées par un conseiller Orange."
        )
        return "\n".join(lines)

    def generate_report(
        self,
        conversation_id: int,
        report_type: Literal["kam", "company_profile", "business_twin"],
    ) -> GeneratedReportResult:
        # Preserve callers of the previous public service contract while storing and
        # returning only the new descriptive company profile type.
        if report_type == "business_twin":
            report_type = GeneratedReport.ReportType.COMPANY_PROFILE
        if report_type not in {
            GeneratedReport.ReportType.KAM,
            GeneratedReport.ReportType.COMPANY_PROFILE,
        }:
            raise ServiceError("invalid_report_type")
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
            snapshot = conversation.profile_snapshots.order_by("-version").first()
            if snapshot is None:
                raise ServiceError("conversation_has_no_profile")
            recommendation_record = snapshot.recommendation_records.get()
        except Conversation.DoesNotExist as exc:
            raise ServiceError("conversation_not_found") from exc
        except RecommendationRecord.DoesNotExist as exc:
            raise ServiceError("conversation_has_no_profile") from exc

        profile = CompanyProfile.model_validate(snapshot.data)
        recommendations = RecommendationResult.model_validate(recommendation_record.data)
        if report_type == GeneratedReport.ReportType.KAM:
            bundle = self.report_builder.build_kam(profile, recommendations)
        else:
            bundle = self.report_builder.build_company_profile(profile)
        data = bundle.report.model_dump(mode="json")
        input_fingerprint = _fingerprint(
            report_type,
            snapshot.content_hash,
            recommendation_record.input_fingerprint,
            data,
        )
        report, created = GeneratedReport.objects.get_or_create(
            conversation=conversation,
            report_type=report_type,
            input_fingerprint=input_fingerprint,
            defaults={
                "profile_snapshot": snapshot,
                "recommendation": recommendation_record,
                "status": bundle.report.status.value,
                "schema_version": bundle.report.schema_version,
                "data": data,
                "rendered_text": bundle.rendered_text,
            },
        )
        return GeneratedReportResult(
            report_id=report.pk,
            conversation_id=conversation.pk,
            report_type=report_type,
            status=report.status,
            data=report.data,
            rendered_text=report.rendered_text,
            replayed=not created,
        )
