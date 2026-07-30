from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.reports.review import prepare_report_review_package


class Command(BaseCommand):
    help = "Génère des rapports synthétiques à soumettre à la revue KAM/métier."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--cases",
            type=Path,
            default=Path(settings.BASE_DIR) / "evals" / "cases.json",
        )
        parser.add_argument(
            "--catalog",
            type=Path,
            default=Path(settings.ONBORA_CATALOG_PATH),
        )
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--scenario-count", type=int, default=5)

    def handle(self, *args, **options) -> None:
        try:
            output = prepare_report_review_package(
                cases_path=options["cases"],
                catalog_path=options["catalog"],
                destination=options["output"],
                scenario_count=options["scenario_count"],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Paquet de revue rapports préparé: {output}")
        )
