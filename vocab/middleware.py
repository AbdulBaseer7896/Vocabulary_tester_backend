from django.conf import settings
from django.http import HttpResponse


class SimpleCorsMiddleware:
    """Lets the browser frontend call this API from its own origin.

    Small enough not to warrant django-cors-headers: it echoes back only
    origins that are explicitly listed in CORS_ALLOWED_ORIGINS, and answers
    the preflight request the browser sends before a PATCH or DELETE.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.origins = set(getattr(settings, "CORS_ALLOWED_ORIGINS", []))

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
            response["Access-Control-Max-Age"] = "86400"
            response["Vary"] = "Origin"
        return response
