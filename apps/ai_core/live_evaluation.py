from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.utils import timezone
from pydantic import Field

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts import CompanyProfile
from apps.ai_core.contracts.base import ContractModel
from apps.ai_core.domain import merge_profile, recommend_services
from apps.ai_core.evaluation import patch_from_case
from apps.ai_core.models import AIExecution, Conversation
from apps.ai_core.providers import ChatModel
from apps.ai_core.services import ConversationService
from apps.ai_core.services.conversation import ServiceError
from apps.ai_core.services.extraction import PROMPT_VERSION


PROFILE_FIELDS = ("name", "sector", "size", "activities", "locations", "needs", "constraints")


class LiveCaseResult(ContractModel):
    case_id: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    turns_expected: int
    turns_completed: int
    field_checks: int
    field_matches: int
    expected_service_ids: list[str] = Field(default_factory=list)
    actual_service_ids: list[str] = Field(default_factory=list)
    forbidden_service_ids_returned: list[str] = Field(default_factory=list)
    provider_error: str = ""
    latency_ms: list[int] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LiveEvaluationSummary(ContractModel):
    case_count: int
    cases_passed: int
    case_pass_rate: float
    field_checks: int
    field_matches: int
    field_accuracy: float
    provider_error_count: int
    forbidden_service_violation_count: int
    latency_p50_ms: int | None = None
    latency_p95_ms: int | None = None
    latency_max_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class LiveEvaluationThresholds(ContractModel):
    minimum_case_pass_rate: float = Field(default=0.8, ge=0, le=1)
    minimum_field_accuracy: float = Field(default=0.9, ge=0, le=1)
    maximum_provider_errors: int = Field(default=0, ge=0)
    maximum_forbidden_service_violations: int = Field(default=0, ge=0)


class LiveEvaluationReport(ContractModel):
    evaluation_schema_version: str = "1.0"
    generated_at: datetime
    provider: str
    model: str
    prompt_version: str
    catalog_version: str
    synthetic_data_only: bool = True
    thresholds: LiveEvaluationThresholds
    gate_passed: bool
    summary: LiveEvaluationSummary
    cases: list[LiveCaseResult]


def _turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    if "turns" in case:
        return case["turns"]
    return [{"message": case["message"], "patch": case["patch"]}]


def _gold_profile(case: dict[str, Any], catalog: CatalogDefinition) -> CompanyProfile:
    profile = CompanyProfile()
    for turn_number, turn in enumerate(_turns(case), start=1):
        profile = merge_profile(
            profile,
            patch_from_case(turn, f"gold:{case['id']}:turn:{turn_number}"),
            catalog=catalog,
        )
    return profile


def _normalized(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _profile_value(profile: CompanyProfile, field_name: str) -> object:
    value = getattr(profile, field_name)
    if isinstance(value, list):
        return sorted(_normalized(fact.value) for fact in value)
    return _normalized(value.value) if value is not None else None


def _list_signature(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(
        token
        for value in values
        for token in re.findall(r"[\wÀ-ÿ]+", str(value).casefold())
        if token not in {"et", "le", "la", "les", "un", "une", "des", "du"}
    )


def _profile_field_matches(field_name: str, expected: object, actual: object) -> bool:
    if field_name in {"activities", "locations", "needs", "constraints"}:
        # Grouping equivalent phrases into one or several list items is acceptable;
        # added or missing content still changes the token multiset and fails.
        return _list_signature(expected) == _list_signature(actual)
    return actual == expected


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


@dataclass(frozen=True)
class _ExecutionTotals:
    latencies: list[int]
    input_tokens: int
    output_tokens: int


def _execution_totals(conversation: Conversation) -> _ExecutionTotals:
    executions = list(
        conversation.ai_executions.filter(purpose="qualification_extraction").order_by("id")
    )
    return _ExecutionTotals(
        latencies=[item.latency_ms for item in executions if item.latency_ms is not None],
        input_tokens=sum(item.input_tokens or 0 for item in executions),
        output_tokens=sum(item.output_tokens or 0 for item in executions),
    )


def evaluate_live_case(
    case: dict[str, Any],
    *,
    model: ChatModel,
    catalog: CatalogDefinition,
    keep_data: bool = False,
) -> LiveCaseResult:
    service = ConversationService(model=model, catalog=catalog)
    conversation = service.create_conversation(
        metadata={"source": "live_gemini_evaluation", "case_id": case["id"]}
    )
    errors: list[str] = []
    provider_error = ""
    turns_completed = 0
    actual_profile = CompanyProfile()
    try:
        for turn_number, turn in enumerate(_turns(case), start=1):
            try:
                result = service.process_conversation_turn(
                    conversation.pk,
                    turn["message"],
                    f"live-eval-{case['id']}-{turn_number}",
                )
            except ServiceError as exc:
                provider_error = exc.code
                errors.append(f"turn {turn_number}: provider/service error {exc.code}")
                break
            turns_completed += 1
            actual_profile = result.profile

        expected_profile = _gold_profile(case, catalog)
        field_matches = 0
        for field_name in PROFILE_FIELDS:
            expected = _profile_value(expected_profile, field_name)
            actual = _profile_value(actual_profile, field_name)
            if _profile_field_matches(field_name, expected, actual):
                field_matches += 1
            else:
                errors.append(
                    f"profile {field_name}: expected {expected!r}, got {actual!r}"
                )

        expected_conflicts = sorted(case.get("expected_conflict_fields", []))
        actual_conflicts = sorted(conflict.field_name for conflict in actual_profile.conflicts)
        if actual_conflicts != expected_conflicts:
            errors.append(
                f"conflicts: expected {expected_conflicts!r}, got {actual_conflicts!r}"
            )

        recommendations = recommend_services(actual_profile, catalog)
        actual_service_ids = [item.service_id for item in recommendations.items]
        expected_service_ids = list(case.get("expected_service_ids", []))
        if actual_service_ids != expected_service_ids:
            errors.append(
                f"services: expected {expected_service_ids!r}, got {actual_service_ids!r}"
            )
        forbidden = sorted(
            set(actual_service_ids) & set(case.get("forbidden_service_ids", []))
        )
        if forbidden:
            errors.append(f"forbidden services returned: {forbidden!r}")

        totals = _execution_totals(conversation)
        return LiveCaseResult(
            case_id=case["id"],
            passed=not errors,
            errors=errors,
            turns_expected=len(_turns(case)),
            turns_completed=turns_completed,
            field_checks=len(PROFILE_FIELDS),
            field_matches=field_matches,
            expected_service_ids=expected_service_ids,
            actual_service_ids=actual_service_ids,
            forbidden_service_ids_returned=forbidden,
            provider_error=provider_error,
            latency_ms=totals.latencies,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
        )
    finally:
        if not keep_data:
            Conversation.objects.filter(pk=conversation.pk).delete()


def build_live_evaluation_report(
    cases: list[dict[str, Any]],
    *,
    model: ChatModel,
    catalog: CatalogDefinition,
    thresholds: LiveEvaluationThresholds | None = None,
    keep_data: bool = False,
) -> LiveEvaluationReport:
    if not cases:
        raise ValueError("at least one live evaluation case is required")
    resolved_thresholds = thresholds or LiveEvaluationThresholds()
    results = [
        evaluate_live_case(
            case,
            model=model,
            catalog=catalog,
            keep_data=keep_data,
        )
        for case in cases
    ]
    latencies = [latency for result in results for latency in result.latency_ms]
    field_checks = sum(result.field_checks for result in results)
    field_matches = sum(result.field_matches for result in results)
    cases_passed = sum(result.passed for result in results)
    provider_errors = sum(bool(result.provider_error) for result in results)
    forbidden_violations = sum(
        len(result.forbidden_service_ids_returned) for result in results
    )
    summary = LiveEvaluationSummary(
        case_count=len(results),
        cases_passed=cases_passed,
        case_pass_rate=cases_passed / len(results),
        field_checks=field_checks,
        field_matches=field_matches,
        field_accuracy=field_matches / field_checks if field_checks else 0,
        provider_error_count=provider_errors,
        forbidden_service_violation_count=forbidden_violations,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies) if latencies else None,
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
    )
    gate_passed = (
        summary.case_pass_rate >= resolved_thresholds.minimum_case_pass_rate
        and summary.field_accuracy >= resolved_thresholds.minimum_field_accuracy
        and summary.provider_error_count <= resolved_thresholds.maximum_provider_errors
        and summary.forbidden_service_violation_count
        <= resolved_thresholds.maximum_forbidden_service_violations
    )
    return LiveEvaluationReport(
        generated_at=timezone.now(),
        provider=model.provider_name,
        model=model.model_name,
        prompt_version=PROMPT_VERSION,
        catalog_version=catalog.catalog_version,
        thresholds=resolved_thresholds,
        gate_passed=gate_passed,
        summary=summary,
        cases=results,
    )


def save_live_evaluation_report(
    report: LiveEvaluationReport, destination: str | Path
) -> Path:
    output_path = Path(destination).resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite evaluation report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output_path
