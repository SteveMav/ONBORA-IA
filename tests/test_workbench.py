from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.ai_core.models import Conversation, Message
from apps.reports.models import GeneratedReport


pytestmark = pytest.mark.django_db


def test_home_renders_empty_workbench() -> None:
    response = Client().get(reverse("workbench:home"))
    assert response.status_code == 200
    assert "Tester l’intelligence métier" in response.content.decode()


def test_local_fake_flow_builds_company_profile_and_kam_report(monkeypatch) -> None:
    monkeypatch.setenv("ONBORA_AI_PROVIDER", "fake")
    client = Client()

    created = client.post(reverse("workbench:create_session"))
    conversation = Conversation.objects.get()
    assert created.status_code == 302
    assert created.url == reverse("workbench:session_detail", args=[conversation.pk])

    response = client.post(
        reverse("workbench:submit_message", args=[conversation.pk]),
        {
            "message": "Notre entreprise École Lumière est une école de formation à Kinshasa avec 25 employés et a besoin d’internet.",
            "idempotency_key": "web-test-turn-1",
        },
    )
    assert response.status_code == 302
    conversation.refresh_from_db()
    assert conversation.state_version == 1
    assert Message.objects.get(role=Message.Role.USER).status == Message.Status.COMPLETED
    assistant = Message.objects.get(role=Message.Role.ASSISTANT)
    assert "informations utiles" in assistant.content

    draft_page = client.get(reverse("workbench:session_detail", args=[conversation.pk]))
    draft_content = draft_page.content.decode()
    assert "Bonjour, discutons d’abord de votre situation" in draft_content
    assert "Assistant Onbora" in draft_content
    assert assistant.content in draft_content
    assert "Les informations sont suffisantes" in draft_content
    assert "Lancer l’analyse" in draft_content
    assert "Nom de l’entreprise" not in draft_content
    assert "HTML · imprimer" not in draft_content
    assert conversation.recommendation_records.count() == 0

    locked_report = client.post(
        reverse("workbench:generate_report", args=[conversation.pk, "company_profile"])
    )
    assert locked_report.status_code == 400
    assert "Lancez d’abord l’analyse" in locked_report.content.decode()

    analyzed = client.post(
        reverse("workbench:analyze_conversation", args=[conversation.pk])
    )
    assert analyzed.status_code == 302
    assert analyzed.url.endswith("?analysis=complete")
    assert conversation.recommendation_records.count() == 1

    analysis_page = client.get(
        reverse("workbench:session_detail", args=[conversation.pk])
    )
    analysis_content = analysis_page.content.decode()
    assert "À vérifier" in analysis_content
    assert "Nom de l’entreprise" in analysis_content
    assert "Fiche non confirmée" in analysis_content
    assert "Offres recommandées" in analysis_content
    assert "Internet illimité Fibre" in analysis_content
    assert "Bénéficier d’un accès fibre illimité" in analysis_content
    assert "Vérifier l’éligibilité fibre de chaque site" in analysis_content
    assert "Fibre Pro 90" in analysis_content
    assert "offre publiée en RDC" in analysis_content
    assert "Voir la source officielle Orange Business" in analysis_content
    assert "NEED_MATCH" not in analysis_content
    assert "Voici les offres Orange" in analysis_content

    confirmed = client.post(
        reverse("workbench:confirm_profile", args=[conversation.pk]),
        {
            "name": "École Lumière",
            "sector": "education",
            "size": "25",
            "activities": "formation professionnelle",
            "locations": "Kinshasa",
            "needs": "connexion internet stable",
            "constraints": "budget maîtrisé",
        },
    )
    assert confirmed.status_code == 302
    assert confirmed.url.endswith("?profile=confirmed")
    conversation.refresh_from_db()
    assert conversation.state_version == 2
    latest_profile = conversation.profile_snapshots.order_by("-version").first().data
    assert latest_profile["name"]["status"] == "confirmed"
    assert latest_profile["constraints"][0]["value"] == "budget maîtrisé"

    for report_type in ("company_profile", "kam"):
        response = client.post(
            reverse("workbench:generate_report", args=[conversation.pk, report_type])
        )
        assert response.status_code == 302

    page = client.get(reverse("workbench:session_detail", args=[conversation.pk]))
    content = page.content.decode()
    assert page.status_code == 200
    assert "École Lumière" in content
    assert "Profil d’entreprise" in content
    assert "Business Twin" not in content
    assert "Confirmée" in content
    assert "Synthèse KAM" in content
    assert GeneratedReport.objects.filter(conversation=conversation).count() == 2
    assert content.count("HTML · imprimer") == 2

    company_profile_report = GeneratedReport.objects.get(
        conversation=conversation,
        report_type=GeneratedReport.ReportType.COMPANY_PROFILE,
    )
    json_response = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "company_profile", company_profile_report.pk, "json"],
        )
    )
    assert json_response.status_code == 200
    assert json_response["Content-Type"] == "application/json; charset=utf-8"
    assert json_response["Content-Disposition"].startswith("attachment;")
    assert json.loads(json_response.content) == company_profile_report.data
    assert "interesting_services" not in company_profile_report.data
    assert "recommended_next_actions" not in company_profile_report.data

    html_response = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "company_profile", company_profile_report.pk, "html"],
        )
    )
    assert html_response.status_code == 200
    assert html_response["Content-Type"] == "text/html; charset=utf-8"
    assert html_response["Content-Disposition"].startswith("inline;")
    assert html_response["Cache-Control"] == "private, no-store"
    assert "Profil d’entreprise" in html_response.content.decode()
    assert "Business Twin" not in html_response.content.decode()
    assert "@media print" in html_response.content.decode()

    kam_report = GeneratedReport.objects.get(
        conversation=conversation,
        report_type=GeneratedReport.ReportType.KAM,
    )
    kam_json = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "kam", kam_report.pk, "json"],
        )
    )
    assert kam_json.status_code == 200
    assert json.loads(kam_json.content) == kam_report.data
    kam_html = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "kam", kam_report.pk, "html"],
        )
    )
    assert kam_html.status_code == 200
    assert "Rapport KAM" in kam_html.content.decode()
    assert kam_report.data["executive_summary"] in kam_html.content.decode()

    other_conversation = Conversation.objects.create()
    cross_conversation = client.get(
        reverse(
            "workbench:export_report",
            args=[other_conversation.pk, "company_profile", company_profile_report.pk, "json"],
        )
    )
    assert cross_conversation.status_code == 404

    wrong_type = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "kam", company_profile_report.pk, "json"],
        )
    )
    assert wrong_type.status_code == 404

    invalid_format = client.get(
        reverse(
            "workbench:export_report",
            args=[conversation.pk, "company_profile", company_profile_report.pk, "pdf"],
        )
    )
    assert invalid_format.status_code == 400


def test_gemini_mode_without_key_shows_safe_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv("ONBORA_AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    conversation = Conversation.objects.create()

    response = Client().post(
        reverse("workbench:submit_message", args=[conversation.pk]),
        {"message": "Une entreprise", "idempotency_key": "missing-key"},
    )
    assert response.status_code == 400
    assert "GEMINI_API_KEY n’est pas configurée" in response.content.decode()
    assert conversation.messages.count() == 0


def test_mutating_routes_reject_get() -> None:
    conversation = Conversation.objects.create()
    client = Client()
    assert client.get(reverse("workbench:create_session")).status_code == 405
    assert client.get(reverse("workbench:submit_message", args=[conversation.pk])).status_code == 405
    assert client.get(reverse("workbench:analyze_conversation", args=[conversation.pk])).status_code == 405
    assert client.get(reverse("workbench:confirm_profile", args=[conversation.pk])).status_code == 405
    assert client.get(reverse("workbench:generate_report", args=[conversation.pk, "kam"])).status_code == 405


def test_invalid_profile_form_preserves_draft(monkeypatch) -> None:
    monkeypatch.setenv("ONBORA_AI_PROVIDER", "fake")
    conversation = Conversation.objects.create()
    client = Client()
    client.post(
        reverse("workbench:submit_message", args=[conversation.pk]),
        {
            "message": "École Lumière est une école à Kinshasa.",
            "idempotency_key": "draft-for-invalid-form",
        },
    )
    response = client.post(
        reverse("workbench:confirm_profile", args=[conversation.pk]),
        {"name": "École Lumière", "size": "pas-un-nombre"},
    )
    assert response.status_code == 400
    assert "valeur invalide" in response.content.decode()
    conversation.refresh_from_db()
    assert conversation.state_version == 1
