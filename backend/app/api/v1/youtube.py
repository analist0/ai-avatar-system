"""YouTube studio: script in, talking-avatar package out."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.users import get_current_user
from app.api.v1.voices import _ALLOWED_LANGUAGES
from app.database import AsyncSessionLocal, get_db
from app.models import Avatar, User, YoutubeProject
from app.schemas import YoutubeEngineInfo, YoutubeProjectCreate, YoutubeProjectResponse
from app.services.storage import storage_service
from app.services.youtube_engines import engine_catalog
from app.services.youtube_render import ASPECTS, preview_metadata, render_project
from app.services.youtube_script import parse_script

logger = logging.getLogger(__name__)
router = APIRouter()


def _user_id(current_user: Optional[User]) -> str:
    return current_user.id if current_user else "demo-user"


def _validate_uuid(value: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Project not found")


async def _to_response(project: YoutubeProject) -> YoutubeProjectResponse:
    async def url_for(key: Optional[str]) -> Optional[str]:
        if not key:
            return None
        return await storage_service.serving_url(key)

    payload = YoutubeProjectResponse.model_validate(project)
    payload.video_url = await url_for(project.video_key)
    payload.srt_url = await url_for(project.srt_key)
    payload.chapters_url = await url_for(project.chapters_key)
    payload.description_url = await url_for(project.description_key)
    return payload


async def _owned_project(
    project_id: str,
    db: AsyncSession,
    current_user: Optional[User],
) -> YoutubeProject:
    _validate_uuid(project_id)
    result = await db.execute(select(YoutubeProject).where(YoutubeProject.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != _user_id(current_user):
        raise HTTPException(status_code=403, detail="Not authorised to access this project")
    return project


async def _render_in_background(project_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await render_project(project_id, db)
        except Exception:
            logger.exception("Background YouTube render crashed for %s", project_id)


@router.get("/engines", response_model=List[YoutubeEngineInfo])
async def list_engines():
    """Honest map of which talking-head repos this studio uses, and which it does not."""
    return engine_catalog()


@router.post(
    "/projects", response_model=YoutubeProjectResponse, status_code=status.HTTP_201_CREATED
)
async def create_project(
    body: YoutubeProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if body.language not in _ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {body.language}")
    if body.aspect not in ASPECTS:
        raise HTTPException(status_code=400, detail="aspect must be landscape, portrait, or square")
    try:
        uuid.UUID(body.avatar_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Avatar not found")

    try:
        plan = parse_script(body.script)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    uid = _user_id(current_user)
    avatar_result = await db.execute(select(Avatar).where(Avatar.id == body.avatar_id))
    avatar = avatar_result.scalar_one_or_none()
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if avatar.user_id != uid:
        raise HTTPException(status_code=403, detail="Not authorised to use this avatar")

    title = body.title.strip() or plan.title or avatar.name or "סרטון"
    project = YoutubeProject(
        user_id=uid,
        avatar_id=avatar.id,
        title=title[:120],
        script=body.script,
        language=body.language,
        aspect=body.aspect,
        burn_captions=body.burn_captions,
        status="draft",
        progress=0,
        project_metadata=preview_metadata(plan, body.language),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return await _to_response(project)


@router.get("/projects", response_model=List[YoutubeProjectResponse])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    uid = _user_id(current_user)
    result = await db.execute(
        select(YoutubeProject)
        .where(YoutubeProject.user_id == uid)
        .order_by(YoutubeProject.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    projects = result.scalars().all()
    return [await _to_response(project) for project in projects]


@router.get("/projects/{project_id}", response_model=YoutubeProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    project = await _owned_project(project_id, db, current_user)
    return await _to_response(project)


@router.post("/projects/{project_id}/render", response_model=YoutubeProjectResponse)
async def start_render(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    project = await _owned_project(project_id, db, current_user)
    if project.status == "rendering":
        raise HTTPException(status_code=409, detail="This video is already rendering")
    project.status = "rendering"
    project.progress = 1
    project.error = None
    await db.commit()
    await db.refresh(project)
    asyncio.create_task(_render_in_background(project.id))
    return await _to_response(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    project = await _owned_project(project_id, db, current_user)
    if project.status == "rendering":
        raise HTTPException(status_code=409, detail="Wait for the render to finish before deleting")
    keys = project.asset_keys()
    try:
        await db.delete(project)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to delete YouTube project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete project")
    for key in keys:
        try:
            await storage_service.delete_file(key)
        except Exception as exc:
            logger.warning("Could not delete %s: %s", key, exc)
