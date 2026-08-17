from __future__ import annotations

from django.db import migrations, models


def _deduplicated_sources(data: dict[str, object]) -> list[str]:
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        return []
    return list(dict.fromkeys(source for source in sources if isinstance(source, str)))


def _description(summary: dict[str, object]) -> str:
    name = summary.get("name") or "L’entreprise"
    sector = summary.get("sector")
    activities = summary.get("activities") or []
    size = summary.get("size")
    locations = summary.get("locations") or []
    sentences = [
        f"{name} évolue dans le secteur {sector}."
        if sector
        else f"{name} est une entreprise dont le secteur reste à préciser."
    ]
    if activities:
        sentences.append(f"Ses activités déclarées sont : {', '.join(activities)}.")
    if size:
        sentences.append(f"Sa taille déclarée est de {size}.")
    if locations:
        sentences.append(f"Elle est présente à {', '.join(locations)}.")
    description = " ".join(sentences)
    return description[:4_000]


def forwards(apps, schema_editor) -> None:
    GeneratedReport = apps.get_model("reports", "GeneratedReport")
    for report in GeneratedReport.objects.filter(report_type="business_twin").iterator():
        old = report.data if isinstance(report.data, dict) else {}
        summary = old.get("company_summary", {})
        if not isinstance(summary, dict):
            summary = {}
        report.report_type = "company_profile"
        report.data = {
            "schema_version": old.get("schema_version", "1.0"),
            "status": old.get("status", report.status),
            "description": _description(summary),
            "company_summary": summary,
            "needs": old.get("needs_and_pain_points", []),
            "constraints": old.get("risks_and_constraints", []),
            "missing_information": old.get("missing_information", []),
            "sources": _deduplicated_sources(old),
        }
        report.rendered_text = (
            f"Profil d’entreprise — {summary.get('name') or 'Entreprise non identifiée'}\n"
            f"{report.data['description']}"
        )
        report.save(update_fields=["report_type", "data", "rendered_text"])


def backwards(apps, schema_editor) -> None:
    GeneratedReport = apps.get_model("reports", "GeneratedReport")
    for report in GeneratedReport.objects.filter(report_type="company_profile").iterator():
        old = report.data if isinstance(report.data, dict) else {}
        recommendation = getattr(report, "recommendation", None)
        recommendation_data = (
            recommendation.data
            if recommendation is not None and isinstance(recommendation.data, dict)
            else {}
        )
        report.report_type = "business_twin"
        report.data = {
            "schema_version": old.get("schema_version", "1.0"),
            "status": old.get("status", report.status),
            "company_summary": old.get("company_summary", {}),
            "current_situation": [],
            "needs_and_pain_points": old.get("needs", []),
            "business_opportunities": [],
            "interesting_services": [],
            "risks_and_constraints": old.get("constraints", []),
            "missing_information": old.get("missing_information", []),
            "recommended_next_actions": [],
            "sources": _deduplicated_sources(old),
            "catalog_version": recommendation_data.get("catalog_version", "unknown"),
        }
        report.rendered_text = (
            "Business Twin — "
            f"{report.data['company_summary'].get('name') or 'Entreprise non identifiée'}"
        )
        report.save(update_fields=["report_type", "data", "rendered_text"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="generatedreport",
            name="report_type",
            field=models.CharField(
                choices=[("kam", "KAM"), ("company_profile", "Profil d’entreprise")],
                max_length=30,
            ),
        ),
    ]
