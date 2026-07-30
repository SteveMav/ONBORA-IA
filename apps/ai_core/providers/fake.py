from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from apps.ai_core.contracts.profile import (
    CompanyProfilePatch,
    Fact,
    FactStatus,
    QualificationTurnOutput,
)
from .base import ChatModel, ModelCallResult, ModelError, ModelUsage, T


FakeResponse = BaseModel | dict[str, Any] | Exception | Callable[[dict[str, Any]], BaseModel]


class FakeChatModel(ChatModel):
    provider_name = "fake"
    model_name = "deterministic-fake-v1"

    def __init__(self, responses: dict[str, list[FakeResponse]] | None = None) -> None:
        self._responses = defaultdict(deque)
        for purpose, values in (responses or {}).items():
            self._responses[purpose].extend(values)
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self,
        *,
        purpose: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> ModelCallResult[T]:
        self.calls.append({"purpose": purpose, "payload": payload})
        if not self._responses[purpose]:
            raise ModelError("fake_response_missing", retryable=False)
        response = self._responses[purpose].popleft()
        if isinstance(response, Exception):
            if isinstance(response, ModelError):
                raise response
            raise ModelError("fake_provider_error", retryable=True) from response
        if callable(response):
            response = response(payload)
        try:
            output = response_model.model_validate(response)
        except Exception as exc:
            raise ModelError("invalid_model_output", retryable=False) from exc
        return ModelCallResult(output=output, usage=ModelUsage(input_tokens=10, output_tokens=10))


class HeuristicFakeChatModel(ChatModel):
    """A small offline fake for demos; it is intentionally not a production extractor."""

    provider_name = "fake"
    model_name = "heuristic-fake-v1"

    SECTORS = {
        "école": "education",
        "education": "education",
        "formation": "education",
        "restaurant": "services",
        "restauration": "services",
        "boutique": "commerce",
        "commerce": "commerce",
        "magasin": "retail",
        "clinique": "healthcare",
        "santé": "healthcare",
    }
    NEEDS = {
        "wifi": "connexion internet stable",
        "wi-fi": "connexion internet stable",
        "internet": "connexion internet stable",
        "connexion": "connexion internet stable",
        "sauvegarde": "sauvegarde des données",
        "backup": "sauvegarde des données",
        "collaboration": "collaboration d’équipe",
        "télétravail": "collaboration d’équipe",
        "sécurité": "renforcement de la cybersécurité",
        "sécuriser": "renforcement de la cybersécurité",
        "piratage": "renforcement de la cybersécurité",
        "paiement": "paiement numérique",
        "encaissement": "paiement numérique",
    }
    ACTIVITIES = {
        "restaurant": "restauration",
        "restauration": "restauration",
        "formation": "formation professionnelle",
        "vente": "vente",
        "commerce": "commerce",
        "conseil": "conseil",
        "soins": "services de santé",
    }

    def generate_structured(
        self,
        *,
        purpose: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> ModelCallResult[T]:
        if purpose != "qualification_extraction" or response_model not in {
            CompanyProfilePatch,
            QualificationTurnOutput,
        }:
            raise ModelError("unsupported_fake_purpose", retryable=False)
        message = str(payload.get("message", ""))
        source_ref = str(payload.get("message_ref", "message:unknown"))
        lowered = message.casefold()

        def fact(value: str | int, confidence: float = 1.0) -> Fact:
            return Fact(
                value=value,
                status=FactStatus.REPORTED,
                source_refs=[source_ref],
                confidence=confidence,
            )

        data: dict[str, Any] = {"schema_version": "1.0"}
        name_match = re.search(
            r"(?:entreprise|société|école|boutique|clinique)\s+"
            r"(?:s['’]appelle\s+)?"
            r"([A-ZÀ-Ÿ][\wÀ-ÿ'’\-]*(?:\s+[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]*){0,3})",
            message,
        )
        if name_match:
            data["name"] = fact(name_match.group(1).strip())
        for keyword, sector in self.SECTORS.items():
            if keyword in lowered:
                data["sector"] = fact(sector, 0.95)
                break
        employees = re.search(r"(\d{1,5})\s+(?:employés|employes|personnes|collaborateurs)", lowered)
        if employees:
            data["size"] = fact(int(employees.group(1)))
        location = re.search(
            r"\b(?:à|située? à|basée? à)\s+"
            r"([A-ZÀ-Ÿ][\wÀ-ÿ'\- ]{1,40}?)"
            r"(?=\s+(?:avec|qui|et|compte|a besoin)\b|[,.;]|$)",
            message,
        )
        if location:
            data["locations"] = [fact(location.group(1).strip())]
        activities: list[Fact] = []
        seen_activities: set[str] = set()
        for keyword, activity in self.ACTIVITIES.items():
            if keyword in lowered and activity not in seen_activities:
                activities.append(fact(activity))
                seen_activities.add(activity)
        if activities:
            data["activities"] = activities
        needs: list[Fact] = []
        seen: set[str] = set()
        for keyword, need in self.NEEDS.items():
            if keyword in lowered and need not in seen:
                needs.append(fact(need))
                seen.add(need)
        if needs:
            data["needs"] = needs
        patch = CompanyProfilePatch.model_validate(data)
        if response_model is CompanyProfilePatch:
            output = patch
        else:
            current = payload.get("current_profile") or {}

            def current_values(field_name: str) -> list[object]:
                raw = current.get(field_name)
                if not raw:
                    return []
                values = raw if isinstance(raw, list) else [raw]
                return [
                    item.get("value") if isinstance(item, dict) else item
                    for item in values
                    if item is not None
                ]

            def patch_values(field_name: str) -> list[object]:
                raw = getattr(patch, field_name)
                if not raw:
                    return []
                values = raw if isinstance(raw, list) else [raw]
                return [item.value for item in values if item.value is not None]

            def field_present(field_name: str) -> bool:
                return bool(current_values(field_name) or patch_values(field_name))

            searchable = " ".join(
                str(value).casefold()
                for field_name in ("needs", "activities", "constraints")
                for value in [*current_values(field_name), *patch_values(field_name)]
            )
            context = payload.get("qualification_context") or {}
            rules = context.get("services") if isinstance(context, dict) else []
            candidates = [
                rule
                for rule in rules or []
                if any(
                    str(keyword).casefold() in searchable
                    for keyword in rule.get("need_keywords", [])
                )
            ]
            if not rules:
                # Useful for direct unit usage outside ConversationService.
                if "paiement" in searchable or "encaissement" in searchable:
                    candidates = [{"required_profile_fields": ["sector", "activities"]}]
                elif "internet" in searchable or "connexion" in searchable:
                    candidates = [{"required_profile_fields": ["locations", "size"]}]
                elif "sécurité" in searchable or "cybersécurité" in searchable:
                    candidates = [{"required_profile_fields": ["activities"]}]

            ranked_missing = sorted(
                (
                    [
                        field_name
                        for field_name in candidate.get("required_profile_fields", [])
                        if not field_present(field_name)
                    ]
                    for candidate in candidates
                ),
                key=len,
            )
            has_needs = field_present("needs")
            missing = ranked_missing[0] if ranked_missing else []
            ready_for_analysis = bool(has_needs and candidates and not missing)
            if ready_for_analysis:
                reply = "J’ai les informations utiles pour ce besoin. Vous pouvez lancer l’analyse quand vous le souhaitez."
                readiness_reason = "Le besoin et les critères utiles aux solutions correspondantes sont disponibles."
            elif not has_needs:
                reply = "Merci. Quel est le principal problème que vous cherchez à résoudre aujourd’hui ?"
                readiness_reason = "Le besoin principal manque encore."
            elif not candidates:
                reply = "Je comprends l’objectif général. Concrètement, quel usage souhaitez-vous mettre en place ?"
                readiness_reason = "L’usage doit être précisé pour identifier une solution adaptée."
            elif "activities" in missing or "sector" in missing:
                reply = "Je comprends mieux votre besoin. Quelle est votre activité principale ?"
                readiness_reason = "L’activité ou le secteur utile à ce besoin manque encore."
            elif "locations" in missing:
                reply = "Quel site ou quelle ville est concerné par ce besoin ?"
                readiness_reason = "La localisation du site concerné manque encore."
            elif "size" in missing:
                reply = "Combien de personnes ou d’appareils utiliseront cette solution ?"
                readiness_reason = "Le nombre d’utilisateurs ou d’appareils manque encore."
            else:
                reply = "Quelle précision est la plus importante pour bien comprendre cet usage ?"
                readiness_reason = "Une précision directement liée au besoin manque encore."
            output = QualificationTurnOutput(
                assistant_message=reply,
                profile_patch=patch,
                ready_for_analysis=ready_for_analysis,
                readiness_reason=readiness_reason,
            )
        return ModelCallResult(output=output, usage=ModelUsage(input_tokens=0, output_tokens=0))
