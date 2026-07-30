from __future__ import annotations

import os
import uuid
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.ai_core.contracts import CompanyProfile, RecommendationResult
from apps.ai_core.models import Conversation
from apps.ai_core.providers import build_chat_model
from apps.ai_core.services.conversation import ConversationService, ServiceError
from apps.reports.models import GeneratedReport
from apps.reports.services.exports import ReportExportError, build_report_export


ERROR_MESSAGES = {
    "invalid_message": "Écrivez un message avant de l’envoyer.",
    "invalid_idempotency_key": "La requête a expiré. Rechargez la page puis réessayez.",
    "idempotency_key_reused_with_different_content": "Ce message a déjà été utilisé. Rechargez la page puis réessayez.",
    "message_already_processing": "Ce message est déjà en cours d’analyse.",
    "message_attempt_limit_reached": "L’analyse a échoué deux fois. Envoyez un nouveau message pour continuer.",
    "provider_timeout": "Gemini met trop de temps à répondre. Vous pouvez réessayer.",
    "provider_rate_limited": "Gemini reçoit trop de demandes. Réessayez dans un instant.",
    "provider_unavailable": "Gemini est temporairement indisponible.",
    "provider_api_error": "Gemini a refusé la requête. Vérifiez la clé et le modèle configurés.",
    "invalid_model_output": "La réponse du modèle n’avait pas le format attendu.",
    "invalid_company_profile": "La fiche contient une valeur invalide ou trop longue.",
    "conversation_not_ready": "Le modèle indique qu’il manque encore des informations avant l’analyse.",
    "conversation_not_analyzed": "Lancez d’abord l’analyse de la conversation.",
    "profile_not_confirmed": "Relisez et confirmez d’abord la fiche entreprise.",
    "conversation_has_no_profile": "Ajoutez d’abord une description de l’entreprise.",
    "invalid_report_type": "Ce type de rapport n’est pas disponible.",
}


def _provider_display() -> dict[str, str]:
    provider = os.getenv("ONBORA_AI_PROVIDER")
    if not provider:
        provider = "gemini" if os.getenv("GEMINI_API_KEY") else "fake"
    provider = provider.casefold()
    if provider == "gemini":
        return {
            "provider": "Gemini",
            "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            "mode": "réel",
        }
    return {
        "provider": "Simulateur local",
        "model": "heuristic-fake-v1",
        "mode": "démo · aucun LLM",
    }


def _facts(profile: CompanyProfile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    single_fields = (("Entreprise", profile.name), ("Secteur", profile.sector), ("Taille", profile.size))
    plural_fields = (
        ("Activité", profile.activities),
        ("Implantation", profile.locations),
        ("Besoin", profile.needs),
        ("Contrainte", profile.constraints),
    )
    for label, fact in single_fields:
        if fact is not None and fact.value is not None:
            rows.append({"label": label, "fact": fact})
    for label, facts in plural_fields:
        rows.extend({"label": label, "fact": fact} for fact in facts if fact.value is not None)
    return rows


def _split_values(value: str) -> list[str]:
    normalized = value.replace("\r", "\n").replace(",", "\n")
    return list(dict.fromkeys(item.strip() for item in normalized.split("\n") if item.strip()))


def _profile_form(profile: CompanyProfile | None) -> dict[str, Any]:
    if profile is None:
        return {key: "" for key in ("name", "sector", "size", "activities", "locations", "needs", "constraints")}

    def scalar(field: str) -> str | int:
        item = getattr(profile, field)
        return item.value if item and item.value is not None else ""

    def listed(field: str) -> str:
        return "\n".join(str(item.value) for item in getattr(profile, field) if item.value is not None)

    return {
        "name": scalar("name"),
        "sector": scalar("sector"),
        "size": scalar("size"),
        "activities": listed("activities"),
        "locations": listed("locations"),
        "needs": listed("needs"),
        "constraints": listed("constraints"),
    }


def _context(
    conversation: Conversation | None = None,
    *,
    error_message: str = "",
    success_message: str = "",
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "recent_conversations": Conversation.objects.order_by("-created_at")[:8],
        "conversation": conversation,
        "error_message": error_message,
        "success_message": success_message,
        "idempotency_key": str(uuid.uuid4()),
        "is_fake_provider": _provider_display()["provider"] == "Simulateur local",
        **_provider_display(),
    }
    if conversation is None:
        return context

    snapshot = conversation.profile_snapshots.order_by("-version").first()
    qualification_profile = CompanyProfile.model_validate(snapshot.data) if snapshot else None
    recommendation_record = (
        snapshot.recommendation_records.order_by("-created_at").first()
        if snapshot
        else None
    )
    analysis_complete = recommendation_record is not None
    profile = qualification_profile if analysis_complete else None
    facts = _facts(profile) if profile else []
    profile_confirmed = bool(facts) and all(
        row["fact"].status.value == "confirmed" for row in facts
    )
    recommendations = (
        RecommendationResult.model_validate(recommendation_record.data)
        if recommendation_record
        else None
    )
    reports = {}
    if snapshot:
        for report in conversation.reports.filter(profile_snapshot=snapshot).order_by("-created_at"):
            reports.setdefault(report.report_type, report)
    context.update(
        {
            "messages": conversation.messages.all(),
            "executions": conversation.ai_executions.order_by("-created_at")[:5],
            "profile": profile,
            "profile_facts": facts,
            "profile_form": _profile_form(profile),
            "profile_confirmed": profile_confirmed,
            "recommendations": recommendations,
            "ready_for_analysis": bool(
                conversation.metadata.get("ready_for_analysis", False)
            ),
            "readiness_reason": str(
                conversation.metadata.get("readiness_reason", "")
            ),
            "analysis_complete": analysis_complete,
            "kam_report": reports.get(GeneratedReport.ReportType.KAM),
            "twin_report": reports.get(GeneratedReport.ReportType.BUSINESS_TWIN),
        }
    )
    return context


def _service() -> ConversationService:
    return ConversationService(model=build_chat_model())


def _render_error(
    request: HttpRequest,
    conversation: Conversation,
    error: Exception,
    *,
    status: int = 400,
) -> HttpResponse:
    if isinstance(error, ServiceError):
        message = ERROR_MESSAGES.get(error.code, "L’opération n’a pas pu être terminée.")
    elif isinstance(error, ValueError) and "GEMINI_API_KEY" in str(error):
        message = "Le mode Gemini est actif, mais GEMINI_API_KEY n’est pas configurée."
    else:
        message = "Une erreur inattendue est survenue. Consultez les logs locaux."
    return render(request, "workbench/index.html", _context(conversation, error_message=message), status=status)


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    latest = Conversation.objects.order_by("-created_at").first()
    return render(request, "workbench/index.html", _context(latest))


@require_GET
def session_detail(request: HttpRequest, conversation_id: int) -> HttpResponse:
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    success = ""
    if request.GET.get("profile") == "confirmed":
        success = "La fiche entreprise est confirmée. Les rapports utilisent maintenant cette version."
    elif request.GET.get("analysis") == "complete":
        success = "Analyse terminée. Les offres Orange proposées sont maintenant disponibles."
    return render(
        request,
        "workbench/index.html",
        _context(conversation, success_message=success),
    )


@require_POST
def create_session(request: HttpRequest) -> HttpResponse:
    conversation = Conversation.objects.create(metadata={"source": "web_workbench"})
    return redirect("workbench:session_detail", conversation_id=conversation.pk)


@require_POST
def submit_message(request: HttpRequest, conversation_id: int) -> HttpResponse:
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    try:
        _service().process_conversation_turn(
            conversation.pk,
            request.POST.get("message", ""),
            request.POST.get("idempotency_key", ""),
        )
    except (ServiceError, ValueError) as exc:
        return _render_error(request, conversation, exc)
    return redirect("workbench:session_detail", conversation_id=conversation.pk)


@require_POST
def confirm_profile(request: HttpRequest, conversation_id: int) -> HttpResponse:
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    size_text = request.POST.get("size", "").strip()
    try:
        size = int(size_text) if size_text else None
    except ValueError as exc:
        return _render_error(
            request,
            conversation,
            ServiceError("invalid_company_profile"),
        )
    try:
        _service().confirm_company_profile(
            conversation.pk,
            name=request.POST.get("name", "").strip(),
            sector=request.POST.get("sector", "").strip(),
            size=size,
            activities=_split_values(request.POST.get("activities", "")),
            locations=_split_values(request.POST.get("locations", "")),
            needs=_split_values(request.POST.get("needs", "")),
            constraints=_split_values(request.POST.get("constraints", "")),
        )
    except (ServiceError, ValueError) as exc:
        return _render_error(request, conversation, exc)
    return redirect(
        f"{reverse('workbench:session_detail', args=[conversation.pk])}?profile=confirmed"
    )


@require_POST
def analyze_conversation(request: HttpRequest, conversation_id: int) -> HttpResponse:
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    try:
        _service().analyze_conversation(conversation.pk)
    except (ServiceError, ValueError) as exc:
        return _render_error(request, conversation, exc)
    return redirect(
        f"{reverse('workbench:session_detail', args=[conversation.pk])}?analysis=complete"
    )


@require_POST
def generate_report(
    request: HttpRequest,
    conversation_id: int,
    report_type: str,
) -> HttpResponse:
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    try:
        snapshot = conversation.profile_snapshots.order_by("-version").first()
        if snapshot is None or not snapshot.recommendation_records.exists():
            raise ServiceError("conversation_not_analyzed")
        profile = CompanyProfile.model_validate(snapshot.data) if snapshot else None
        facts = _facts(profile) if profile else []
        if not facts or any(row["fact"].status.value != "confirmed" for row in facts):
            raise ServiceError("profile_not_confirmed")
        _service().generate_report(conversation.pk, report_type)
    except (ServiceError, ValueError) as exc:
        return _render_error(request, conversation, exc)
    return redirect("workbench:session_detail", conversation_id=conversation.pk)


@require_GET
def export_report(
    request: HttpRequest,
    conversation_id: int,
    report_type: str,
    report_id: int,
    export_format: str,
) -> HttpResponse:
    if report_type not in GeneratedReport.ReportType.values:
        return HttpResponseBadRequest("Type de rapport non pris en charge.")
    if export_format not in {"json", "html"}:
        return HttpResponseBadRequest("Format d’export non pris en charge.")

    report = get_object_or_404(
        GeneratedReport,
        pk=report_id,
        conversation_id=conversation_id,
        report_type=report_type,
    )
    try:
        exported = build_report_export(report, export_format)
    except ReportExportError:
        return HttpResponseBadRequest("Le rapport stocké ne peut pas être exporté.")

    response = HttpResponse(exported.content, content_type=exported.content_type)
    response.headers["Content-Disposition"] = (
        f'{exported.disposition}; filename="{exported.filename}"'
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    if export_format == "html":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
        )
    return response
