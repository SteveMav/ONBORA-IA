from __future__ import annotations

from dataclasses import dataclass

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts import CompanyProfile, Fact, FactStatus, RecommendationResult
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.reports.contracts import (
    BusinessTwin,
    KAMReport,
    ReportItem,
    ReportStatus,
    TwinCompanySummary,
)


@dataclass(frozen=True)
class ReportBundle:
    report: KAMReport | BusinessTwin
    rendered_text: str


def _text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def _fact_item(fact: Fact, *, prefix: str | None = None) -> ReportItem:
    description = _text(fact.value)
    if prefix:
        description = f"{prefix} : {description}"
    return ReportItem(
        description=description,
        status=fact.status,
        source_refs=fact.source_refs,
    )


def _all_facts(profile: CompanyProfile) -> list[tuple[str, Fact]]:
    facts: list[tuple[str, Fact]] = []
    for name in ("name", "sector", "size"):
        fact = getattr(profile, name)
        if fact:
            facts.append((name, fact))
    for name in ("activities", "locations", "needs", "constraints"):
        facts.extend((name, fact) for fact in getattr(profile, name))
    return facts


class ReportBuilder:
    def __init__(self, catalog: CatalogDefinition) -> None:
        self.catalog = catalog

    def _status(
        self, profile: CompanyProfile, recommendations: RecommendationResult
    ) -> ReportStatus:
        if (
            profile.missing_information
            or profile.conflicts
            or recommendations.status != RecommendationStatus.RECOMMENDED
            or recommendations.missing_information
        ):
            return ReportStatus.NON_FINAL
        return ReportStatus.FINAL

    def _opportunities(self, recommendations: RecommendationResult) -> list[ReportItem]:
        allowed = self.catalog.allowed_service_ids
        unknown = {item.service_id for item in recommendations.items} - allowed
        if unknown:
            raise ValueError(f"recommendation contains unknown services: {sorted(unknown)}")
        services = {service.service_id: service for service in self.catalog.services}
        opportunities: list[ReportItem] = []
        for item in recommendations.items:
            service = services[item.service_id]
            explanation = item.customer_explanation or service.description
            if item.rdc_availability == "to_confirm" and item.availability_note:
                explanation = (
                    f"{explanation} Disponibilité en RDC : {item.availability_note}"
                )
            opportunities.append(
                ReportItem(
                    description=f"{item.service_name} — {explanation}",
                    status=FactStatus.INFERRED,
                    source_refs=item.evidence_refs,
                    service_id=item.service_id,
                )
            )
        return opportunities

    def build_kam(
        self, profile: CompanyProfile, recommendations: RecommendationResult
    ) -> ReportBundle:
        facts = _all_facts(profile)
        confirmed = [_fact_item(fact, prefix=name) for name, fact in facts if fact.status == FactStatus.CONFIRMED]
        reported = [_fact_item(fact, prefix=name) for name, fact in facts if fact.status == FactStatus.REPORTED]
        inferred = [_fact_item(fact, prefix=name) for name, fact in facts if fact.status == FactStatus.INFERRED]
        needs = [_fact_item(fact) for fact in profile.needs]
        opportunities = self._opportunities(recommendations)
        to_verify = [
            ReportItem(description=f"Information manquante : {field}", status=FactStatus.UNKNOWN)
            for field in list(dict.fromkeys([*profile.missing_information, *recommendations.missing_information]))
        ]
        to_verify.extend(
            ReportItem(
                description=(
                    f"Conflit sur {conflict.field_name}: "
                    f"{_text(conflict.existing.value)} / {_text(conflict.incoming.value)}"
                ),
                status=FactStatus.UNKNOWN,
                source_refs=list(
                    dict.fromkeys(
                        [*conflict.existing.source_refs, *conflict.incoming.source_refs]
                    )
                ),
            )
            for conflict in profile.conflicts
        )
        next_actions = [
            ReportItem(
                description=f"Vérifier {field}",
                status=FactStatus.INFERRED,
                source_refs=[],
            )
            for field in recommendations.missing_information
        ]
        if opportunities:
            opportunity_sources = list(
                dict.fromkeys(ref for item in opportunities for ref in item.source_refs)
            )
            next_actions.append(
                ReportItem(
                    description="Faire valider les opportunités proposées par un responsable métier.",
                    status=FactStatus.INFERRED,
                    source_refs=opportunity_sources,
                )
            )
        name = _text(profile.name.value) if profile.name else "Entreprise non identifiée"
        summary = f"Synthèse de {name}. {len(opportunities)} opportunité(s) à examiner."
        report = KAMReport(
            status=self._status(profile, recommendations),
            executive_summary=summary,
            confirmed_facts=confirmed,
            reported_facts=reported,
            inferred_insights=inferred,
            needs=needs,
            opportunities=opportunities,
            points_to_verify=to_verify,
            recommended_next_actions=next_actions,
            catalog_version=recommendations.catalog_version,
        )
        rendered = "\n".join(
            [summary, *[f"- {item.description}" for item in opportunities], *[f"À vérifier: {item.description}" for item in to_verify]]
        )
        return ReportBundle(report=report, rendered_text=rendered)

    def build_business_twin(
        self, profile: CompanyProfile, recommendations: RecommendationResult
    ) -> ReportBundle:
        opportunities = self._opportunities(recommendations)
        all_facts = [fact for _, fact in _all_facts(profile)]
        sources = list(
            dict.fromkeys(
                [
                    *(ref for fact in all_facts for ref in fact.source_refs),
                    *(ref for item in opportunities for ref in item.source_refs),
                ]
            )
        )
        summary = TwinCompanySummary(
            name=_text(profile.name.value) if profile.name else None,
            sector=_text(profile.sector.value) if profile.sector else None,
            size=_text(profile.size.value) if profile.size else None,
            activities=[_text(fact.value) for fact in profile.activities],
            locations=[_text(fact.value) for fact in profile.locations],
        )
        missing = list(
            dict.fromkeys([*profile.missing_information, *recommendations.missing_information])
        )
        next_actions = [
            ReportItem(
                description=f"Collecter ou confirmer : {field}",
                status=FactStatus.INFERRED,
            )
            for field in missing
        ]
        twin = BusinessTwin(
            status=self._status(profile, recommendations),
            company_summary=summary,
            current_situation=[
                *[_fact_item(fact, prefix="activité") for fact in profile.activities],
                *[_fact_item(fact, prefix="localisation") for fact in profile.locations],
            ],
            needs_and_pain_points=[_fact_item(fact) for fact in profile.needs],
            business_opportunities=opportunities,
            interesting_services=opportunities,
            risks_and_constraints=[_fact_item(fact) for fact in profile.constraints],
            missing_information=missing,
            recommended_next_actions=next_actions,
            sources=sources,
            catalog_version=recommendations.catalog_version,
        )
        rendered = (
            f"Business Twin — {summary.name or 'Entreprise non identifiée'}\n"
            + "\n".join(f"- {item.description}" for item in opportunities)
        )
        return ReportBundle(report=twin, rendered_text=rendered)
