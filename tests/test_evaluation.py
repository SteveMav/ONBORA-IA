import json
from pathlib import Path

import pytest

from apps.ai_core.catalog import load_catalog
from apps.ai_core.evaluation import evaluate_case, load_evaluation_cases


ROOT = Path(__file__).parents[1]


def test_all_synthetic_evaluation_cases_pass() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    cases = load_evaluation_cases(ROOT / "evals" / "cases.json")
    results = [evaluate_case(case, catalog) for case in cases]
    assert len(results) == 32
    assert [result.errors for result in results if not result.passed] == []


def test_multiturn_cases_are_replayed_in_order_with_intermediate_checkpoints() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    cases = load_evaluation_cases(ROOT / "evals" / "cases.json")
    multiturn_cases = [case for case in cases if "turns" in case]

    assert len(multiturn_cases) == 15
    assert sum(len(case["turns"]) for case in multiturn_cases) == 52
    assert all(
        any(
            "expected_profile" in turn or "expected_missing_information" in turn
            for turn in case["turns"][:-1]
        )
        for case in multiturn_cases
    )

    results = {case["id"]: evaluate_case(case, catalog) for case in multiturn_cases}
    assert all(result.passed for result in results.values())
    assert all(
        results[case["id"]].turn_count == len(case["turns"])
        for case in multiturn_cases
    )

    repeated = results["multiturn-repeated-fact-deduplicated"]
    assert repeated.profile.name is not None
    assert repeated.profile.name.source_refs == [
        "eval:multiturn-repeated-fact-deduplicated:turn:1",
        "eval:multiturn-repeated-fact-deduplicated:turn:2",
    ]

    correction = results["multiturn-size-correction-conflict"]
    assert correction.profile.conflicts[0].incoming.source_refs == [
        "eval:multiturn-size-correction-conflict:turn:4"
    ]


def test_injection_turn_does_not_add_profile_facts_or_offers() -> None:
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")
    cases = load_evaluation_cases(ROOT / "evals" / "cases.json")
    case = next(case for case in cases if case["id"] == "multiturn-prompt-injection-ignored")

    result = evaluate_case(case, catalog)

    assert result.passed
    serialized_profile = result.profile.model_dump_json()
    assert "turn:1" not in serialized_profile
    assert result.recommendation_ids == ("api_orange_money",)


def test_case_loader_rejects_duplicate_ids_and_invalid_turns(tmp_path: Path) -> None:
    duplicate_path = tmp_path / "duplicates.json"
    duplicate_path.write_text(
        json.dumps(
            [
                {"id": "same", "message": "Premier", "patch": {}},
                {"id": "same", "message": "Second", "patch": {}},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate evaluation case id"):
        load_evaluation_cases(duplicate_path)

    invalid_turn_path = tmp_path / "invalid-turn.json"
    invalid_turn_path.write_text(
        json.dumps([{"id": "invalid", "turns": [{"message": "", "patch": {}}]}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must contain a message"):
        load_evaluation_cases(invalid_turn_path)
