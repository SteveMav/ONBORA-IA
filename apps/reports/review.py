from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from apps.ai_core.catalog import load_catalog
from apps.ai_core.contracts import CompanyProfile, FactStatus
from apps.ai_core.contracts.base import ContractModel
from apps.ai_core.domain import merge_profile, recommend_services
from apps.ai_core.evaluation import load_evaluation_cases, patch_from_case
from apps.reports.contracts import BusinessTwin, KAMReport
from apps.reports.services import ReportBuilder


class ReportReviewChecklist(ContractModel):
    facts_and_inferences_are_clear: bool = False
    opportunities_are_supported: bool = False
    limitations_are_visible: bool = False
    content_is_useful_for_target_role: bool = False
    next_actions_are_actionable: bool = False
    export_is_readable: bool = False


class ReportReviewDecision(ContractModel):
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_by: str = Field(default="", max_length=160)
    reviewed_on: date | None = None
    notes: str = Field(default="", max_length=2_000)


class ReportReviewSample(ContractModel):
    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    scenario_id: str = Field(min_length=1, max_length=160)
    report_type: Literal["kam", "business_twin"]
    report: dict[str, object]
    checklist: ReportReviewChecklist = Field(default_factory=ReportReviewChecklist)
    decision: ReportReviewDecision = Field(default_factory=ReportReviewDecision)

    @model_validator(mode="after")
    def report_matches_type(self) -> "ReportReviewSample":
        contract = KAMReport if self.report_type == "kam" else BusinessTwin
        contract.model_validate(self.report)
        return self


class ReportReviewPackage(ContractModel):
    review_schema_version: Literal["1.0"] = "1.0"
    generated_on: date
    catalog_version: str = Field(min_length=1, max_length=64)
    minimum_scenarios_required: int = Field(default=5, ge=5, le=20)
    samples: list[ReportReviewSample] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_samples(self) -> "ReportReviewPackage":
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("report review sample_id values must be unique")
        mismatched_catalogs = [
            sample.sample_id
            for sample in self.samples
            if sample.report.get("catalog_version") != self.catalog_version
        ]
        if mismatched_catalogs:
            raise ValueError(
                "report samples must use the package catalog_version: "
                + ", ".join(mismatched_catalogs)
            )
        return self


def _confirmed_profile(profile: CompanyProfile) -> CompanyProfile:
    updates: dict[str, object] = {}
    for field_name in ("name", "sector", "size"):
        fact = getattr(profile, field_name)
        updates[field_name] = (
            fact.model_copy(
                update={
                    "status": FactStatus.CONFIRMED,
                    "confidence": 1.0,
                    "requires_confirmation": False,
                }
            )
            if fact
            else None
        )
    for field_name in ("activities", "locations", "needs", "constraints"):
        updates[field_name] = [
            fact.model_copy(
                update={
                    "status": FactStatus.CONFIRMED,
                    "confidence": 1.0,
                    "requires_confirmation": False,
                }
            )
            for fact in getattr(profile, field_name)
        ]
    return profile.model_copy(update=updates)


def prepare_report_review_package(
    *,
    cases_path: str | Path,
    catalog_path: str | Path,
    destination: str | Path,
    scenario_count: int = 5,
) -> Path:
    if not 5 <= scenario_count <= 20:
        raise ValueError("scenario_count must be between 5 and 20")
    output_path = Path(destination).resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing review package: {output_path}")

    catalog = load_catalog(catalog_path)
    builder = ReportBuilder(catalog)
    samples: list[ReportReviewSample] = []
    selected_scenarios = 0
    for case in load_evaluation_cases(cases_path):
        profile = CompanyProfile()
        turns = case.get("turns") or [{"message": case["message"], "patch": case["patch"]}]
        for turn_number, turn in enumerate(turns, start=1):
            profile = merge_profile(
                profile,
                patch_from_case(turn, f"review:{case['id']}:turn:{turn_number}"),
                catalog=catalog,
            )
        if profile.missing_information or profile.conflicts:
            continue
        profile = _confirmed_profile(profile)
        recommendations = recommend_services(profile, catalog)
        if not recommendations.items or recommendations.missing_information:
            continue

        reports = {
            "kam": builder.build_kam(profile, recommendations).report,
            "business_twin": builder.build_business_twin(profile, recommendations).report,
        }
        for report_type, report in reports.items():
            samples.append(
                ReportReviewSample(
                    sample_id=f"{case['id']}.{report_type}",
                    scenario_id=case["id"],
                    report_type=report_type,
                    report=report.model_dump(mode="json"),
                )
            )
        selected_scenarios += 1
        if selected_scenarios == scenario_count:
            break

    if selected_scenarios < scenario_count:
        raise ValueError(
            f"only {selected_scenarios} complete scenarios are available; "
            f"{scenario_count} required"
        )

    package = ReportReviewPackage(
        generated_on=date.today(),
        catalog_version=catalog.catalog_version,
        minimum_scenarios_required=scenario_count,
        samples=samples,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(package.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output_path


def report_review_approval_errors(package: ReportReviewPackage) -> list[str]:
    errors: list[str] = []
    today = date.today()
    scenarios = {sample.scenario_id for sample in package.samples}
    if len(scenarios) < package.minimum_scenarios_required:
        errors.append(
            f"at least {package.minimum_scenarios_required} distinct scenarios are required"
        )

    by_scenario: dict[str, set[str]] = {}
    for sample in package.samples:
        by_scenario.setdefault(sample.scenario_id, set()).add(sample.report_type)
        prefix = f"sample {sample.sample_id}:"
        unchecked = [
            name
            for name, checked in sample.checklist.model_dump().items()
            if not checked
        ]
        if unchecked:
            errors.append(f"{prefix} unchecked items: {', '.join(unchecked)}")
        if sample.decision.status != "approved":
            errors.append(f"{prefix} decision must be approved")
        if sample.report.get("status") != "final":
            errors.append(f"{prefix} only final reports can be approved")
        if not sample.decision.reviewed_by or sample.decision.reviewed_on is None:
            errors.append(f"{prefix} reviewer and review date are required")
        elif sample.decision.reviewed_on > today:
            errors.append(f"{prefix} review date cannot be in the future")

    for scenario_id, report_types in sorted(by_scenario.items()):
        if report_types != {"kam", "business_twin"}:
            errors.append(
                f"scenario {scenario_id}: both kam and business_twin reviews are required"
            )
    return errors


def validate_report_review_package(
    path: str | Path, *, require_approved: bool = False
) -> ReportReviewPackage:
    review_path = Path(path).resolve()
    if not review_path.is_file():
        raise FileNotFoundError(f"report review package not found: {review_path}")
    with review_path.open("r", encoding="utf-8") as stream:
        package = ReportReviewPackage.model_validate(json.load(stream))
    if require_approved:
        errors = report_review_approval_errors(package)
        if errors:
            raise ValueError(
                "report review package is not approved:\n- " + "\n- ".join(errors)
            )
    return package
