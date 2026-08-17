from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from apps.ai_core.models import CompanyProfileSnapshot, Conversation, RecommendationRecord
from .contracts import CompanyProfileReport, KAMReport


class GeneratedReport(models.Model):
    class ReportType(models.TextChoices):
        KAM = "kam", "KAM"
        COMPANY_PROFILE = "company_profile", "Profil d’entreprise"

    class Status(models.TextChoices):
        FINAL = "final", "Final"
        NON_FINAL = "non_final", "Non final"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="reports")
    profile_snapshot = models.ForeignKey(
        CompanyProfileSnapshot, on_delete=models.CASCADE, related_name="reports"
    )
    recommendation = models.ForeignKey(
        RecommendationRecord, on_delete=models.CASCADE, related_name="reports"
    )
    report_type = models.CharField(max_length=30, choices=ReportType.choices)
    status = models.CharField(max_length=20, choices=Status.choices)
    schema_version = models.CharField(max_length=20, default="1.0")
    input_fingerprint = models.CharField(max_length=64)
    data = models.JSONField()
    rendered_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "report_type", "input_fingerprint"],
                name="unique_report_fingerprint",
            )
        ]

    def clean(self) -> None:
        if self.report_type == self.ReportType.KAM:
            contract = KAMReport
        elif self.report_type == self.ReportType.COMPANY_PROFILE:
            contract = CompanyProfileReport
        else:
            raise ValidationError({"report_type": "unsupported report type"})
        try:
            report = contract.model_validate(self.data)
        except PydanticValidationError as exc:
            raise ValidationError({"data": str(exc)}) from exc
        if report.schema_version != self.schema_version:
            raise ValidationError({"schema_version": "does not match report data"})
        if report.status.value != self.status:
            raise ValidationError({"status": "does not match report data"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
