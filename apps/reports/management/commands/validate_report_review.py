from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.reports.review import validate_report_review_package


class Command(BaseCommand):
    help = "Valide un paquet de revue KAM/Business Twin."

    def add_arguments(self, parser) -> None:
        parser.add_argument("review_file", type=Path)
        parser.add_argument("--require-approved", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            package = validate_report_review_package(
                options["review_file"],
                require_approved=options["require_approved"],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        scenarios = {sample.scenario_id for sample in package.samples}
        self.stdout.write(
            self.style.SUCCESS(
                f"Paquet valide: {len(package.samples)} rapports, "
                f"{len(scenarios)} scénarios."
            )
        )
