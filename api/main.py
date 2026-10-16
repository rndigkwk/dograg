"""RagDog API (ADR-0008, step P1): the app's logic in src/ behind HTTP, for the Next.js frontend.

    uv run uvicorn api.main:app --reload --port 8000

The same container image as the Streamlit app, started with this command instead, runs as its own
Cloud Run service (ragdog-api). The Streamlit service keeps serving until the new frontend replaces
it (step P5). Routes are added one pull request at a time: /health first, then /chat (streamed),
/places and /stats, /visit-prep, /memory and /feedback.

The browser calls this API directly (not through Vercel functions), so it allows the frontend's
origins: RAGDOG_WEB_ORIGINS, comma separated, and RAGDOG_WEB_ORIGIN_REGEX for the Vercel preview
deployments of each pull request. Without them only the local Next.js dev server is allowed.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import settings, tracing

LOCAL_WEB = "http://localhost:3000"


def allowed_origins() -> list[str]:
    configured = settings.get_setting("RAGDOG_WEB_ORIGINS") or ""
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or [LOCAL_WEB]


def create_app() -> FastAPI:
    # The interactive docs list every route and schema; deployed, they stay off unless RAGDOG_API_DOCS=1.
    docs = not settings.deployed() or settings.get_setting("RAGDOG_API_DOCS") == "1"
    app = FastAPI(title="RagDog API", version="0.1.0", docs_url="/docs" if docs else None, redoc_url=None,
                  openapi_url="/openapi.json" if docs else None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_origin_regex=settings.get_setting("RAGDOG_WEB_ORIGIN_REGEX") or None,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-RagDog-Client"],
        allow_credentials=False,  # the Supabase token goes in the Authorization header, not a cookie
    )

    from api.chat import router as chat_router
    from api.feedback import router as feedback_router
    from api.places import router as places_router
    from api.stats import router as stats_router
    from api.visit_prep import router as visit_prep_router

    app.include_router(chat_router)
    app.include_router(feedback_router)
    app.include_router(places_router)
    app.include_router(stats_router)
    app.include_router(visit_prep_router)

    @app.get("/health")
    def health() -> dict:
        """Up and which commit. The frontend calls it when a page opens, so a scaled-to-zero
        instance starts while the guardian is still typing (ADR-0008, decision 2)."""
        return {"status": "ok", "commit": tracing.release()}

    return app


app = create_app()
