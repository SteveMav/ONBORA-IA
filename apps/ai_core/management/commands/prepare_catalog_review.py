from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.intake.validate_intake import prepare_catalog_review_package


class Command(BaseCommand):
    help = "Prépare un paquet de revue métier sans approuver le catalogue."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--catalog",
            type=Path,
            default=Path(settings.ONBORA_CATALOG_PATH),
        )
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args, **options) -> None:
        try:
            output = prepare_catalog_review_package(
                options["catalog"], options["output"]
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Paquet de revue catalogue préparé: {output}")
        )
