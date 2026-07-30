from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai_core.catalog import load_catalog
from apps.ai_core.contracts import CompanyProfilePatch, Fact, FactStatus, QualificationTurnOutput
from apps.ai_core.live_evaluation import _profile_field_matches, build_live_evaluation_report
from apps.ai_core.evaluation import load_evaluation_cases
from apps.ai_core.models import Conversation
from apps.ai_core.providers import FakeChatModel


pytestmark = pytest.mark.django_db
ROOT = Path(__file__).parents[1]


def test_live_evaluation_scores_real_extraction_path_and_cleans_data() -> None:
    case = {
        "id": "live-synthetic-payment",
        "message": "La boutique Test Marché veut accepter les paiements mobiles.",
        "patch": {
            "name": "Test Marché",
            "sector": "retail",
            "activities": ["vente au détail"],
            "needs": ["paiement mobile money"],
        },
        "expected_service_ids": ["api_orange_money"],
        "forbidden_service_ids": ["internet_fibre_illimite"],
    }

    def response(payload):
        source = payload["message_ref"]

        def fact(value):
            return Fact(
                value=value,
                status=FactStatus.REPORTED,
                source_refs=[source],
                confidence=1,
            )

        return QualificationTurnOutput(
            assistant_message="Le besoin de paiement est compris.",
            ready_for_analysis=True,
            readiness_reason="Besoin qualifié.",
            profile_patch=CompanyProfilePatch(
                name=fact("Test Marché"),
                sector=fact("retail"),
                activities=[fact("vente au détail")],
                needs=[fact("paiement mobile money")],
            ),
        )

    model = FakeChatModel({"qualification_extraction": [response]})
    catalog = load_catalog(ROOT / "catalog" / "versions" / "v1" / "catalog.json")

    report = build_live_evaluation_report([case], model=model, catalog=catalog)

    assert report.gate_passed is True
    assert report.summary.case_pass_rate == 1
    assert report.summary.field_accuracy == 1
    assert report.summary.forbidden_service_violation_count == 0
    assert report.cases[0].actual_service_ids == ["api_orange_money"]
    assert Conversation.objects.count() == 0


def test_gemini_command_requires_explicit_network_confirmation() -> None:
    with pytest.raises(CommandError, match="--confirm-network"):
        call_command("run_gemini_eval", limit=1)


def test_gemini_corpus_gold_values_are_grounded_in_each_turn() -> None:
    cases = load_evaluation_cases(ROOT / "evals" / "gemini-cases.json")

    assert len(cases) == 8
    for case in cases:
        turns = case.get("turns") or [case]
        for turn in turns:
            message = turn["message"].casefold()
            patch = turn["patch"]
            values = [
                patch.get("name"),
                patch.get("sector"),
                patch.get("size"),
                *patch.get("activities", []),
                *patch.get("locations", []),
                *patch.get("needs", []),
                *patch.get("constraints", []),
            ]
            assert all(str(value).casefold() in message for value in values if value is not None)


def test_live_list_scoring_accepts_equivalent_grouping_but_not_missing_content() -> None:
    assert _profile_field_matches(
        "constraints",
        ["résidence des données et continuité"],
        ["continuité", "résidence des données"],
    )
    assert not _profile_field_matches(
        "needs",
        ["connexion internet stable"],
        ["internet"],
    )
