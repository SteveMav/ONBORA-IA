from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ai_core.catalog import CatalogDefinition
from apps.ai_core.contracts import (
    CompanyProfile,
    CompanyProfilePatch,
    QualificationTurnOutput,
    RecommendationResult,
    TurnResult,
)
from apps.reports.contracts import BusinessTwin, KAMReport


SCHEMAS = {
    "business-twin.schema.json": BusinessTwin,
    "catalog.schema.json": CatalogDefinition,
    "company-profile-patch.schema.json": CompanyProfilePatch,
    "company-profile.schema.json": CompanyProfile,
    "qualification-turn-output.schema.json": QualificationTurnOutput,
    "kam-report.schema.json": KAMReport,
    "recommendation-result.schema.json": RecommendationResult,
    "turn-result.schema.json": TurnResult,
}


class Command(BaseCommand):
    help = "Exporte les JSON Schemas versionnés des contrats Onbora IA."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--output", default=str(settings.BASE_DIR / "contracts"))

    def handle(self, *args, **options) -> None:
        output = Path(options["output"])
        output.mkdir(parents=True, exist_ok=True)
        for filename, contract in SCHEMAS.items():
            target = output / filename
            target.write_text(
                json.dumps(contract.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.stdout.write(str(target))
