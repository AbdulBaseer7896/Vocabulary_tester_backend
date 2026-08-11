from django.conf import settings
from django.http import HttpResponse


class LocalCorsMiddleware:
    """Allows the Vite dev server to talk to Django without an extra package."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.origins = set(getattr(settings, "LOCAL_CORS_ORIGINS", []))

    def __call__(self, request):
        origin = request.headers.get("Origin")
        allowed = origin in self.origins

        if request.method == "OPTIONS" and allowed:
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-Requested-With"
            response["Vary"] = "Origin"
        return response
