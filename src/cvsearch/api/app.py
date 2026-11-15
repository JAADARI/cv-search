"""FastAPI application: ingestion, status, profiles and natural-language search.

No ``from __future__ import annotations`` here on purpose: FastAPI resolves dependency
annotations at runtime and cannot see function-local aliases when they are strings.
"""

import hmac
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from cvsearch.domain.models import Profile
from cvsearch.logging_config import configure_logging
from cvsearch.parsing.loader import SUPPORTED_EXTENSIONS
from cvsearch.search.models import SearchResponse
from cvsearch.services import Services, build_services


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000, examples=["Profil ayant développé des chatbots"])
    top_k: int = Field(default=5, ge=1, le=20)


class UploadResult(BaseModel):
    cv_id: uuid.UUID
    filename: str
    status: str
    duplicate: bool = Field(description="True when an identical file was already ingested; nothing was queued.")


def create_app(services_factory: Callable[[], Services] = build_services) -> FastAPI:
    """Application factory; tests inject a factory returning fakes."""
    state: dict[str, Services] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        built = services_factory()
        configure_logging(built.settings.log_level)
        state["services"] = built
        yield
        built.repo.close()

    app = FastAPI(title="CV Search", version="0.1.0", description="Parse, structure and search CVs.", lifespan=lifespan)

    def services() -> Services:
        return state["services"]

    def require_key(
        svc: Annotated[Services, Depends(services)], x_api_key: Annotated[str | None, Header()] = None
    ) -> None:
        expected = svc.settings.api_key
        if expected is None:  # open mode, for local development only
            return
        if not x_api_key or not hmac.compare_digest(x_api_key, expected.get_secret_value()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")

    svc_dep = Annotated[Services, Depends(services)]
    protected = [Depends(require_key)]

    @app.get("/health", tags=["ops"])
    def health(svc: svc_dep) -> dict[str, str]:
        svc.repo.list_cvs()  # touches the database
        return {"status": "ok"}

    @app.post("/cvs", status_code=status.HTTP_202_ACCEPTED, tags=["ingestion"], dependencies=protected)
    async def upload_cvs(svc: svc_dep, files: Annotated[list[UploadFile], File()]) -> list[UploadResult]:
        """Queue one or more CVs (PDF, DOCX, PPTX). Processing is asynchronous: poll ``GET /cvs/{id}``."""
        results: list[UploadResult] = []
        for upload in files:
            name = upload.filename or "cv"
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in SUPPORTED_EXTENSIONS:
                raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{name}: use PDF, DOCX or PPTX")
            content = await upload.read(svc.settings.max_upload_bytes + 1)
            if len(content) > svc.settings.max_upload_bytes:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{name}: file too large")
            if not content:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{name}: empty file")
            cv_id, created = svc.repo.enqueue(name, content)
            row = svc.repo.cv_status(cv_id)
            results.append(
                UploadResult(
                    cv_id=cv_id, filename=name, status=row["status"] if row else "queued", duplicate=not created
                )
            )
        return results

    @app.get("/cvs", tags=["ingestion"], dependencies=protected)
    def list_cvs(svc: svc_dep) -> list[dict[str, Any]]:
        return svc.repo.list_cvs()

    @app.get("/cvs/{cv_id}", tags=["ingestion"], dependencies=protected)
    def cv_status(cv_id: uuid.UUID, svc: svc_dep) -> dict[str, Any]:
        row = svc.repo.cv_status(cv_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown CV")
        return row

    @app.get("/cvs/{cv_id}/profile", tags=["ingestion"], dependencies=protected)
    def get_profile(cv_id: uuid.UUID, svc: svc_dep) -> Profile:
        profile = svc.repo.get_profiles([str(cv_id)]).get(str(cv_id))
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile (unknown CV or not processed yet)")
        return profile

    @app.post("/cvs/{cv_id}/retry", status_code=status.HTTP_202_ACCEPTED, tags=["ingestion"], dependencies=protected)
    def retry_cv(cv_id: uuid.UUID, svc: svc_dep) -> dict[str, str]:
        if not svc.repo.retry(cv_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Only failed CVs can be retried")
        return {"status": "queued"}

    @app.delete("/cvs/{cv_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["ingestion"], dependencies=protected)
    def delete_cv(cv_id: uuid.UUID, svc: svc_dep) -> None:
        """Delete a CV and everything derived from it (personal-data erasure)."""
        if not svc.repo.delete_cv(cv_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown CV")

    @app.post("/search", tags=["search"], dependencies=protected)
    def search(body: SearchRequest, svc: svc_dep) -> SearchResponse:
        return svc.search.search(body.query, body.top_k)

    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory``."""
    return create_app()
