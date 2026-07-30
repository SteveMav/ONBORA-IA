from django.http import JsonResponse
from django.urls import include, path


urlpatterns = [
    path("", include("apps.workbench.urls")),
    path("health/", lambda request: JsonResponse({"status": "ok"})),
]
