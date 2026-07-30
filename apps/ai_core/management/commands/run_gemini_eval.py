from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai_core.catalog import load_catalog
from apps.ai_core.evaluation import load_evaluation_cases
from apps.ai_core.live_evaluation import (
    LiveEvaluationThresholds,
    build_live_evaluation_report,
    save_live_evaluation_report,
)
from apps.ai_core.providers import GeminiChatModel


class Command(BaseCommand):
    help = "Évalue réellement Gemini sur le corpus synthétique Onbora."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--confirm-network", action="store_true")
        parser.add_argument(
            "--cases",
            type=Path,
            default=Path(settings.BASE_DIR) / "evals" / "gemini-cases.json",
        )
        parser.add_argument("--case", action="append", dest="case_ids")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--keep-data", action="store_true")
        parser.add_argument("--fail-on-thresholds", action="store_true")
        parser.add_argument("--minimum-case-pass-rate", type=float, default=0.8)
        parser.add_argument("--minimum-field-accuracy", type=float, default=0.9)
        parser.add_argument("--maximum-provider-errors", type=int, default=0)
        parser.add_argument(
            "--maximum-forbidden-service-violations", type=int, default=0
        )

    def handle(self, *args, **options) -> None:
        if not options["confirm_network"]:
            raise CommandError(
                "refusing network calls without --confirm-network; the corpus must "
                "contain synthetic data only"
            )
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1")

        cases = load_evaluation_cases(options["cases"])
        requested_ids = options.get("case_ids") or []
        if requested_ids:
            known = {case["id"] for case in cases}
            unknown = sorted(set(requested_ids) - known)
            if unknown:
                raise CommandError(f"unknown case ids: {', '.join(unknown)}")
            requested = set(requested_ids)
            cases = [case for case in cases if case["id"] in requested]
        if options["limit"] is not None:
            cases = cases[: options["limit"]]

        try:
            thresholds = LiveEvaluationThresholds(
                minimum_case_pass_rate=options["minimum_case_pass_rate"],
                minimum_field_accuracy=options["minimum_field_accuracy"],
                maximum_provider_errors=options["maximum_provider_errors"],
                maximum_forbidden_service_violations=options[
                    "maximum_forbidden_service_violations"
                ],
            )
            catalog = load_catalog(settings.ONBORA_CATALOG_PATH)
            model = GeminiChatModel(model_name=settings.GEMINI_MODEL)
            report = build_live_evaluation_report(
                cases,
                model=model,
                catalog=catalog,
                thresholds=thresholds,
                keep_data=options["keep_data"],
            )
            output = options["output"]
            if output is None:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                output = Path(settings.BASE_DIR) / "output" / "evals" / f"gemini-{stamp}.json"
            saved = save_live_evaluation_report(report, output)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        for result in report.cases:
            marker = "PASS" if result.passed else "FAIL"
            self.stdout.write(
                f"[{marker}] {result.case_id} "
                f"fields={result.field_matches}/{result.field_checks} "
                f"turns={result.turns_completed}/{result.turns_expected}"
            )
        summary = report.summary
        self.stdout.write(
            f"case_pass_rate={summary.case_pass_rate:.1%} "
            f"field_accuracy={summary.field_accuracy:.1%} "
            f"provider_errors={summary.provider_error_count} "
            f"forbidden_service_violations={summary.forbidden_service_violation_count}"
        )
        self.stdout.write(f"Rapport: {saved}")
        if options["fail_on_thresholds"] and not report.gate_passed:
            raise CommandError("Gemini evaluation thresholds were not met")
        if report.gate_passed:
            self.stdout.write(self.style.SUCCESS("Gemini evaluation gate passed"))
        else:
            self.stdout.write(self.style.WARNING("Gemini evaluation gate not met"))
