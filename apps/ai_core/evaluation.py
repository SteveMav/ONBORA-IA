from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts import CompanyProfile, CompanyProfilePatch, Fact, FactStatus
from apps.ai_core.domain import merge_profile, recommend_services
from apps.reports.services import ReportBuilder


@dataclass(frozen=True)
class EvaluationCaseResult:
    case_id: str
    passed: bool
    errors: tuple[str, ...]
    turn_count: int
    profile: CompanyProfile
    recommendation_ids: tuple[str, ...]


def load_evaluation_cases(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, list) or not data or len(data) > 100:
        raise ValueError("evaluation file must contain between 1 and 100 cases")
    case_ids: set[str] = set()
    for index, case in enumerate(data):
        if not isinstance(case, dict):
            raise ValueError(f"evaluation case {index} must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"evaluation case {index} must have a non-empty id")
        if case_id in case_ids:
            raise ValueError(f"duplicate evaluation case id: {case_id}")
        case_ids.add(case_id)
        _turns_from_case(case)
    return data


def _turns_from_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize legacy one-shot cases and ordered conversational cases."""
    if "turns" not in case:
        if not isinstance(case.get("patch"), dict):
            raise ValueError(f"evaluation case {case.get('id', '<unknown>')} has no patch")
        return [{"message": case.get("message", ""), "patch": case["patch"]}]

    turns = case["turns"]
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"evaluation case {case.get('id', '<unknown>')} has no turns")
    if len(turns) > 20:
        raise ValueError(f"evaluation case {case.get('id', '<unknown>')} exceeds 20 turns")
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict) or not isinstance(turn.get("patch"), dict):
            raise ValueError(
                f"evaluation case {case.get('id', '<unknown>')} turn {index} must contain a patch"
            )
        if not isinstance(turn.get("message"), str) or not turn["message"].strip():
            raise ValueError(
                f"evaluation case {case.get('id', '<unknown>')} turn {index} must contain a message"
            )
    return turns


def patch_from_case(case: dict[str, Any], source_ref: str) -> CompanyProfilePatch:
    raw = case["patch"]

    def fact(value: Any) -> Fact:
        return Fact(
            value=value,
            status=FactStatus.REPORTED,
            source_refs=[source_ref],
            confidence=1.0,
        )

    return CompanyProfilePatch(
        name=fact(raw["name"]) if raw.get("name") is not None else None,
        sector=fact(raw["sector"]) if raw.get("sector") is not None else None,
        size=fact(raw["size"]) if raw.get("size") is not None else None,
        activities=[fact(value) for value in raw.get("activities", [])],
        locations=[fact(value) for value in raw.get("locations", [])],
        needs=[fact(value) for value in raw.get("needs", [])],
        constraints=[fact(value) for value in raw.get("constraints", [])],
    )


def _profile_values(profile: CompanyProfile, field_name: str) -> Any:
    value = getattr(profile, field_name)
    if isinstance(value, list):
        return [fact.value for fact in value]
    return value.value if value is not None else None


def _check_profile_expectations(
    profile: CompanyProfile,
    expected: dict[str, Any],
    *,
    context: str,
) -> list[str]:
    errors: list[str] = []
    known_fields = {"name", "sector", "size", "activities", "locations", "needs", "constraints"}
    for field_name, expected_value in expected.items():
        if field_name not in known_fields:
            errors.append(f"{context}: unknown expected profile field {field_name}")
            continue
        actual_value = _profile_values(profile, field_name)
        if actual_value != expected_value:
            errors.append(
                f"{context}: expected {field_name}={expected_value!r}, got {actual_value!r}"
            )
    return errors


def evaluate_case(case: dict[str, Any], catalog: CatalogDefinition) -> EvaluationCaseResult:
    errors: list[str] = []
    turns = _turns_from_case(case)
    profile = CompanyProfile()
    for turn_number, turn in enumerate(turns, start=1):
        patch = patch_from_case(turn, f"eval:{case['id']}:turn:{turn_number}")
        profile = merge_profile(profile, patch, catalog=catalog)
        if "expected_profile" in turn:
            errors.extend(
                _check_profile_expectations(
                    profile,
                    turn["expected_profile"],
                    context=f"turn {turn_number}",
                )
            )
        if "expected_missing_information" in turn:
            expected_missing = turn["expected_missing_information"]
            if profile.missing_information != expected_missing:
                errors.append(
                    f"turn {turn_number}: expected missing information {expected_missing}, "
                    f"got {profile.missing_information}"
                )

    if "expected_profile" in case:
        errors.extend(
            _check_profile_expectations(
                profile,
                case["expected_profile"],
                context="final profile",
            )
        )
    expected_conflicts = case.get("expected_conflict_fields", [])
    actual_conflicts = [conflict.field_name for conflict in profile.conflicts]
    if actual_conflicts != expected_conflicts:
        errors.append(f"expected conflicts {expected_conflicts}, got {actual_conflicts}")

    recommendations = recommend_services(profile, catalog)
    actual_ids = [item.service_id for item in recommendations.items]
    expected_ids = case.get("expected_service_ids", [])
    forbidden_ids = case.get("forbidden_service_ids", [])
    if actual_ids != expected_ids:
        errors.append(f"expected services {expected_ids}, got {actual_ids}")
    unexpected = sorted(set(actual_ids) & set(forbidden_ids))
    if unexpected:
        errors.append(f"forbidden services returned: {unexpected}")

    builder = ReportBuilder(catalog)
    kam = builder.build_kam(profile, recommendations).report
    twin = builder.build_business_twin(profile, recommendations).report
    allowed = catalog.allowed_service_ids
    report_service_ids = {
        item.service_id
        for item in [*kam.opportunities, *twin.interesting_services]
        if item.service_id
    }
    unknown = sorted(report_service_ids - allowed)
    if unknown:
        errors.append(f"reports contain unknown services: {unknown}")
    expected_status = case.get("expected_recommendation_status")
    if expected_status is not None and recommendations.status.value != expected_status:
        errors.append(
            f"expected recommendation status {expected_status}, got {recommendations.status.value}"
        )
    return EvaluationCaseResult(
        case_id=case["id"],
        passed=not errors,
        errors=tuple(errors),
        turn_count=len(turns),
        profile=profile,
        recommendation_ids=tuple(actual_ids),
    )
