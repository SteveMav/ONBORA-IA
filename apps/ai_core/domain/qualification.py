from __future__ import annotations

from dataclasses import dataclass

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts.profile import CompanyProfile
from apps.ai_core.domain.recommendation import recommend_services


FIELD_LABELS = {
    "activities": "l’activité et l’usage concret",
    "locations": "la localisation du site concerné",
    "needs": "le besoin principal",
    "sector": "le secteur d’activité",
    "size": "le nombre de personnes ou d’appareils à connecter",
}


@dataclass(frozen=True)
class QualificationAssessment:
    ready: bool
    reason: str
    missing_fields: tuple[str, ...] = ()
    candidate_service_ids: tuple[str, ...] = ()


def qualification_catalog_context(catalog: CatalogDefinition) -> dict[str, object]:
    """Return the concise catalog rules the chat model needs to choose useful questions."""
    return {
        "decision_rule": (
            "Un champ est utile seulement s’il est requis par un service plausible ou "
            "s’il aide à distinguer plusieurs usages. Ne collecte jamais d’abord un profil "
            "d’entreprise générique."
        ),
        "services": [
            {
                "service_id": service.service_id,
                "name": service.name,
                "need_keywords": service.match.need_keywords,
                "required_profile_fields": service.match.required_profile_fields,
                "prerequisites": service.prerequisites,
            }
            for service in catalog.services
        ],
    }


def assess_qualification(
    profile: CompanyProfile, catalog: CatalogDefinition
) -> QualificationAssessment:
    """Decide readiness from the need-specific catalog contract, not a fixed questionnaire."""
    if not profile.needs:
        return QualificationAssessment(
            ready=False,
            reason="Le besoin principal doit encore être compris.",
            missing_fields=("needs",),
        )

    recommendations = recommend_services(profile, catalog)
    if not recommendations.items:
        return QualificationAssessment(
            ready=False,
            reason=(
                "L’usage recherché doit être précisé pour le relier à une solution du catalogue."
            ),
            missing_fields=("needs",),
        )

    candidates = tuple(item.service_id for item in recommendations.items)
    complete = [item for item in recommendations.items if not item.missing_information]
    if complete:
        return QualificationAssessment(
            ready=True,
            reason=(
                "Le besoin et les critères utiles aux solutions correspondantes sont disponibles."
            ),
            candidate_service_ids=candidates,
        )

    # The list is already ranked. Asking for the first candidate's missing fields gives
    # the shortest useful path instead of accumulating every possible profile field.
    missing = tuple(recommendations.items[0].missing_information)
    labels = [FIELD_LABELS.get(field, field) for field in missing]
    return QualificationAssessment(
        ready=False,
        reason=f"Il reste à préciser {', puis '.join(labels)}.",
        missing_fields=missing,
        candidate_service_ids=candidates,
    )
