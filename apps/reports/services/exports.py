from __future__ import annotations

import json
from dataclasses import dataclass

from django.template.loader import render_to_string

from apps.reports.contracts import BusinessTwin, KAMReport
from apps.reports.models import GeneratedReport


class ReportExportError(ValueError):
    """Raised when a stored report cannot be exported safely."""


@dataclass(frozen=True)
class ReportExport:
    content: str
    content_type: str
    filename: str
    disposition: str


def _validated_contract(report: GeneratedReport) -> KAMReport | BusinessTwin:
    if report.report_type == GeneratedReport.ReportType.KAM:
        contract = KAMReport
    elif report.report_type == GeneratedReport.ReportType.BUSINESS_TWIN:
        contract = BusinessTwin
    else:
        raise ReportExportError("unsupported report type")

    try:
        return contract.model_validate(report.data)
    except ValueError as exc:
        raise ReportExportError("stored report does not match its contract") from exc


def build_report_export(report: GeneratedReport, export_format: str) -> ReportExport:
    if export_format not in {"json", "html"}:
        raise ReportExportError("unsupported export format")

    contract = _validated_contract(report)
    slug = "kam" if report.report_type == GeneratedReport.ReportType.KAM else "business-twin"
    base_filename = f"onbora-{slug}-session-{report.conversation_id}"

    if export_format == "json":
        content = json.dumps(
            contract.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        return ReportExport(
            content=content,
            content_type="application/json; charset=utf-8",
            filename=f"{base_filename}.json",
            disposition="attachment",
        )

    if export_format == "html":
        content = render_to_string(
            "reports/report_export.html",
            {
                "generated_report": report,
                "report": contract,
                "is_kam": report.report_type == GeneratedReport.ReportType.KAM,
            },
        )
        return ReportExport(
            content=content,
            content_type="text/html; charset=utf-8",
            filename=f"{base_filename}.html",
            disposition="inline",
        )

    raise AssertionError("validated export format was not handled")
