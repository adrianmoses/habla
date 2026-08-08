"""La Libreta to Habla durable speaking-session handoffs (spec #032)."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from api.routes.learner import require_api_token

router = APIRouter(prefix="/api/sessions")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    return value if scheme.lower() == "bearer" and value else None


def require_la_libreta_token(request: Request) -> None:
    expected = request.app.state.settings.la_libreta_api_token
    presented = _bearer(request)
    if not expected or presented is None or not secrets.compare_digest(
        presented, expected
    ):
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db pool not ready")
    return pool


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source: Literal["la-libreta"]
    source_ref: str = Field(alias="sourceRef", min_length=1, max_length=200)
    mode: Literal["speaking"]
    text: str = Field(min_length=1, max_length=20_000)
    structures: list[str] = Field(max_length=100)
    target: str = Field(min_length=1, max_length=1_000)
    date: date
    callback_url: HttpUrl | None = Field(default=None, alias="callbackUrl")


class SessionCreated(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    url: str
    created_at: datetime = Field(alias="createdAt")


class SessionHandoff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    source_ref: str = Field(alias="sourceRef")
    mode: str
    text: str
    structures: list[str]
    target: str
    date: date
    created_at: datetime = Field(alias="createdAt")


def _public_url(settings: Any, handoff_id: str) -> str:
    base = str(settings.public_base_url).strip()
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=503, detail="public base URL not configured")
    return f"{parsed.scheme}://{parsed.netloc}/session/{handoff_id}"


@router.post(
    "",
    response_model=SessionCreated,
    response_model_by_alias=True,
    dependencies=[Depends(require_la_libreta_token)],
)
async def create_session(
    request: Request, response: Response, body: SessionCreate
) -> SessionCreated:
    """Create once per source key; on replay the first payload wins."""
    handoff_id = f"sess_{uuid.uuid4().hex}"
    callback_url = str(body.callback_url) if body.callback_url is not None else None
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO external_session_handoffs
                (id, source, source_ref, source_date, mode, prompt_text,
                 structures, target, callback_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
            ON CONFLICT (source, source_ref, source_date) DO NOTHING
            RETURNING id, created_at
            """,
            handoff_id, body.source, body.source_ref, body.date, body.mode,
            body.text, json.dumps(body.structures), body.target, callback_url,
        )
        created = row is not None
        if row is None:
            row = await conn.fetchrow(
                """
                SELECT id, created_at FROM external_session_handoffs
                WHERE source = $1 AND source_ref = $2 AND source_date = $3
                """,
                body.source, body.source_ref, body.date,
            )
    if row is None:
        raise HTTPException(status_code=503, detail="handoff unavailable")
    response.status_code = 201 if created else 200
    return SessionCreated(
        id=row["id"],
        url=_public_url(request.app.state.settings, row["id"]),
        createdAt=row["created_at"],
    )


@router.get(
    "/{handoff_id}",
    response_model=SessionHandoff,
    response_model_by_alias=True,
    dependencies=[Depends(require_api_token)],
)
async def get_session(request: Request, handoff_id: str) -> SessionHandoff:
    row = await _pool(request).fetchrow(
        """
        SELECT id, source, source_ref, source_date, mode, prompt_text,
               structures, target, created_at
        FROM external_session_handoffs WHERE id = $1
        """,
        handoff_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionHandoff(
        id=row["id"], source=row["source"], sourceRef=row["source_ref"],
        mode=row["mode"], text=row["prompt_text"], structures=row["structures"],
        target=row["target"], date=row["source_date"], createdAt=row["created_at"],
    )
