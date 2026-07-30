import json
from pathlib import Path

import pytest

from apps.reports.review import (
    prepare_report_review_package,
    validate_report_review_package,
)


ROOT = Path(__file__).parents[1]


def test_prepared_report_review_contains_five_pending_pairs(tmp_path: Path) -> None:
    output = prepare_report_review_package(
        cases_path=ROOT / "evals" / "cases.json",
        catalog_path=ROOT / "catalog" / "versions" / "v1" / "catalog.json",
        destination=tmp_path / "reports.pending.json",
        scenario_count=5,
    )

    package = validate_report_review_package(output)
    scenarios = {sample.scenario_id for sample in package.samples}
    assert len(scenarios) == 5
    assert len(package.samples) == 10
    assert all(sample.decision.status == "pending" for sample in package.samples)
    assert all(
        not any(sample.checklist.model_dump().values())
        for sample in package.samples
    )
    with pytest.raises(ValueError, match="not approved"):
        validate_report_review_package(output, require_approved=True)


def test_report_review_requires_both_types_and_human_identity(tmp_path: Path) -> None:
    output = prepare_report_review_package(
        cases_path=ROOT / "evals" / "cases.json",
        catalog_path=ROOT / "catalog" / "versions" / "v1" / "catalog.json",
        destination=tmp_path / "reports.pending.json",
        scenario_count=5,
    )
    raw = json.loads(output.read_text(encoding="utf-8"))
    raw["samples"] = raw["samples"][:1]
    for sample in raw["samples"]:
        sample["checklist"] = {key: True for key in sample["checklist"]}
        sample["decision"] = {
            "status": "approved",
            "reviewed_by": "",
            "reviewed_on": None,
            "notes": "",
        }
    incomplete = tmp_path / "reports.incomplete.json"
    incomplete.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError) as error:
        validate_report_review_package(incomplete, require_approved=True)
    message = str(error.value)
    assert "reviewer and review date are required" in message
    assert "both kam and business_twin reviews are required" in message
