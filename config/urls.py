from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, HttpResponse
from django.urls import include, path, re_path


def spa(_request, path: str = ""):
    dist: Path = settings.FRONTEND_DIST
    if dist.exists():
        if path:
            candidate = dist / path
            if candidate.is_file():
                return FileResponse(candidate.open("rb"))
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index.open("rb"), content_type="text/html")
    return HttpResponse(
        """<!doctype html>
<html><body style="font-family:sans-serif;padding:2rem">
<h1>Frontend not built yet</h1>
<p>From the repo root run:</p>
<pre>cd frontend && npm install && npm run build</pre>
<p>Then refresh. API is already at <a href="/api/health">/api/health</a>.</p>
</body></html>""",
        status=200,
        content_type="text/html",
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("pipeline.urls")),
    re_path(r"^(?P<path>.*)$", spa),
]
