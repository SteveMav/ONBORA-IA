from __future__ import annotations

from dataclasses import dataclass

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts import CompanyProfile, Fact, FactStatus, RecommendationResult
from apps.ai_core.contracts.recommendation import RecommendationStatus
from apps.reports.contracts import (
    CompanyProfileReport,
    CompanySummary,
    KAMReport,
    ReportItem,
    ReportStatus,
)


@dataclass(frozen=True)
class ReportBundle:
    report: KAMReport | CompanyProfileReport
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


def _company_description(profile: CompanyProfile) -> str:
    name = _text(profile.name.value) if profile.name else "L’entreprise"
    sentences: list[str] = []
    if profile.sector:
        sentences.append(f"{name} évolue dans le secteur {_text(profile.sector.value)}.")
    else:
        sentences.append(f"{name} est une entreprise dont le secteur reste à préciser.")
    if profile.activities:
        sentences.append(
            "Ses activités déclarées sont : "
            + ", ".join(_text(fact.value) for fact in profile.activities)
            + "."
        )
    if profile.size:
        sentences.append(f"Sa taille déclarée est de {_text(profile.size.value)}.")
    if profile.locations:
        sentences.append(
            "Elle est présente à "
            + ", ".join(_text(fact.value) for fact in profile.locations)
            + "."
        )
    if profile.needs:
        sentences.append(
            "Ses besoins déclarés sont : "
            + ", ".join(_text(fact.value) for fact in profile.needs)
            + "."
        )
    if profile.constraints:
        sentences.append(
            "Ses contraintes déclarées sont : "
            + ", ".join(_text(fact.value) for fact in profile.constraints)
            + "."
        )
    description = " ".join(sentences)
    if len(description) > 4_000:
        description = description[:3_999].rstrip() + "…"
    return description


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

    def build_company_profile(self, profile: CompanyProfile) -> ReportBundle:
        all_facts = [fact for _, fact in _all_facts(profile)]
        sources = list(
            dict.fromkeys(
                ref for fact in all_facts for ref in fact.source_refs
            )
        )
        summary = CompanySummary(
            name=_text(profile.name.value) if profile.name else None,
            sector=_text(profile.sector.value) if profile.sector else None,
            size=_text(profile.size.value) if profile.size else None,
            activities=[_text(fact.value) for fact in profile.activities],
            locations=[_text(fact.value) for fact in profile.locations],
        )
        missing = list(
            dict.fromkeys(
                [
                    *profile.missing_information,
                    *(conflict.field_name for conflict in profile.conflicts),
                ]
            )
        )
        company_profile = CompanyProfileReport(
            status=(
                ReportStatus.NON_FINAL
                if profile.missing_information or profile.conflicts
                else ReportStatus.FINAL
            ),
            description=_company_description(profile),
            company_summary=summary,
            needs=[_fact_item(fact) for fact in profile.needs],
            constraints=[_fact_item(fact) for fact in profile.constraints],
            missing_information=missing,
            sources=sources,
        )
        rendered = "\n".join(
            [
                f"Profil d’entreprise — {summary.name or 'Entreprise non identifiée'}",
                company_profile.description,
                *[f"Besoin : {item.description}" for item in company_profile.needs],
                *[f"Contrainte : {item.description}" for item in company_profile.constraints],
            ]
        )
        return ReportBundle(report=company_profile, rendered_text=rendered)
