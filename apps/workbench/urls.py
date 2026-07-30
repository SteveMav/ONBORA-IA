from django.urls import path

from . import views


app_name = "workbench"

urlpatterns = [
    path("", views.home, name="home"),
    path("sessions/new/", views.create_session, name="create_session"),
    path("sessions/<int:conversation_id>/", views.session_detail, name="session_detail"),
    path(
        "sessions/<int:conversation_id>/messages/",
        views.submit_message,
        name="submit_message",
    ),
    path(
        "sessions/<int:conversation_id>/profile/",
        views.confirm_profile,
        name="confirm_profile",
    ),
    path(
        "sessions/<int:conversation_id>/analyze/",
        views.analyze_conversation,
        name="analyze_conversation",
    ),
    path(
        "sessions/<int:conversation_id>/reports/<str:report_type>/",
        views.generate_report,
        name="generate_report",
    ),
    path(
        "sessions/<int:conversation_id>/reports/<str:report_type>/<int:report_id>/export/<str:export_format>/",
        views.export_report,
        name="export_report",
    ),
]
