from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai_core.catalog import load_catalog
from apps.ai_core.evaluation import evaluate_case, load_evaluation_cases


class Command(BaseCommand):
    help = "Exécute le corpus synthétique déterministe Onbora IA."

    def handle(self, *args, **options) -> None:
        catalog = load_catalog(settings.ONBORA_CATALOG_PATH)
        cases = load_evaluation_cases(settings.BASE_DIR / "evals" / "cases.json")
        failures = []
        for case in cases:
            result = evaluate_case(case, catalog)
            marker = "PASS" if result.passed else "FAIL"
            self.stdout.write(f"[{marker}] {result.case_id}")
            for error in result.errors:
                self.stdout.write(f"  - {error}")
            if not result.passed:
                failures.append(result.case_id)
        if failures:
            raise CommandError(f"evaluation failed for: {', '.join(failures)}")
        self.stdout.write(self.style.SUCCESS(f"{len(cases)} evaluation cases passed"))

