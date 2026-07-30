from __future__ import annotations

import json
from collections.abc import Iterable

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts.profile import (
    CompanyProfile,
    CompanyProfilePatch,
    Fact,
    FactConflict,
    FactStatus,
)


SCALAR_FIELDS = ("name", "sector", "size")
LIST_FIELDS = ("activities", "locations", "needs", "constraints")
STATUS_RANK = {
    FactStatus.UNKNOWN: 0,
    FactStatus.INFERRED: 1,
    FactStatus.REPORTED: 2,
    FactStatus.CONFIRMED: 3,
}


def _normalized_value(fact: Fact) -> str:
    if isinstance(fact.value, str):
        return " ".join(fact.value.casefold().split())
    return json.dumps(fact.value, ensure_ascii=False, sort_keys=True)


def _same_value(left: Fact, right: Fact) -> bool:
    return _normalized_value(left) == _normalized_value(right)


def _combine_same_fact(left: Fact, right: Fact) -> Fact:
    stronger = right if STATUS_RANK[right.status] > STATUS_RANK[left.status] else left
    return stronger.model_copy(
        update={
            "source_refs": list(dict.fromkeys([*left.source_refs, *right.source_refs])),
            "confidence": max(left.confidence, right.confidence),
            "requires_confirmation": left.requires_confirmation or right.requires_confirmation,
        }
    )


def _merge_scalar(
    field_name: str,
    existing: Fact | None,
    incoming: Fact | None,
    conflicts: list[FactConflict],
) -> Fact | None:
    if incoming is None:
        return existing
    if existing is None or existing.status == FactStatus.UNKNOWN:
        return incoming
    if _same_value(existing, incoming):
        return _combine_same_fact(existing, incoming)
    if existing.status == FactStatus.INFERRED and incoming.status in {
        FactStatus.REPORTED,
        FactStatus.CONFIRMED,
    }:
        return incoming

    conflict = FactConflict(field_name=field_name, existing=existing, incoming=incoming)
    if not any(
        item.field_name == field_name
        and _same_value(item.existing, existing)
        and _same_value(item.incoming, incoming)
        for item in conflicts
    ):
        conflicts.append(conflict)
    return existing


def _merge_fact_list(existing: Iterable[Fact], incoming: Iterable[Fact]) -> list[Fact]:
    merged = list(existing)
    positions = {_normalized_value(fact): index for index, fact in enumerate(merged)}
    for fact in incoming:
        key = _normalized_value(fact)
        if key in positions:
            index = positions[key]
            merged[index] = _combine_same_fact(merged[index], fact)
        else:
            positions[key] = len(merged)
            merged.append(fact)
    return merged


def _is_present(profile: CompanyProfile, field_name: str) -> bool:
    value = getattr(profile, field_name, None)
    if isinstance(value, list):
        return bool(value)
    return value is not None and value.value not in (None, "", [])


def _missing_information(profile: CompanyProfile, catalog: CatalogDefinition | None) -> list[str]:
    missing = [field for field in ("name", "sector", "needs") if not _is_present(profile, field)]
    if catalog:
        candidate_required: set[str] = set()
        needs_text = " ".join(
            str(fact.value).casefold() for fact in [*profile.needs, *profile.activities] if fact.value
        )
        for service in catalog.services:
            if any(keyword.casefold() in needs_text for keyword in service.match.need_keywords):
                candidate_required.update(service.match.required_profile_fields)
        missing.extend(field for field in sorted(candidate_required) if not _is_present(profile, field))
    return list(dict.fromkeys(missing))


def merge_profile(
    profile: CompanyProfile,
    patch: CompanyProfilePatch,
    *,
    catalog: CatalogDefinition | None = None,
) -> CompanyProfile:
    conflicts = list(profile.conflicts)
    updates: dict[str, object] = {}
    for field_name in SCALAR_FIELDS:
        updates[field_name] = _merge_scalar(
            field_name,
            getattr(profile, field_name),
            getattr(patch, field_name),
            conflicts,
        )
    for field_name in LIST_FIELDS:
        updates[field_name] = _merge_fact_list(
            getattr(profile, field_name), getattr(patch, field_name)
        )
    updates["conflicts"] = conflicts
    merged = profile.model_copy(update=updates)
    return merged.model_copy(update={"missing_information": _missing_information(merged, catalog)})

