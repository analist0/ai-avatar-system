"""YouTube studio: script parsing, the engine contract, and a real ffmpeg render."""

import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Avatar, YoutubeProject
from app.services.storage import storage_service
from app.services.tts import SynthResult
from app.services.youtube_render import render_project
from app.services.youtube_script import build_chapters, build_srt, parse_script

SCRIPT = """# למה השינה חשובה

## פתיח
אם אתם קמים עייפים, הבעיה היא לא רק השעה.

[pause 0.3]
## מה לעשות
כבו מסכים חצי שעה לפני השינה.
"""


def test_parse_hebrew_script_chapters_and_pause():
    plan = parse_script(SCRIPT)
    assert plan.title == "למה השינה חשובה"
    assert len(plan.beats) == 2
    assert plan.beats[0].chapter == "פתיח"
    assert plan.beats[0].starts_chapter is True
    assert plan.beats[0].pause_after == 0.3
    assert plan.beats[1].chapter == "מה לעשות"
    assert "מסכים" in plan.beats[1].text
    # The title line is not spoken.
    assert all("למה השינה" not in beat.text for beat in plan.beats)


def test_opening_without_heading_still_starts_at_zero():
    plan = parse_script("שלום.\n\n## אחר כך\nעולם.")
    assert plan.beats[0].chapter == "פתיח"
    assert plan.beats[0].starts_chapter is True
    chapters = build_chapters(plan.beats, [1.2, 2.0])
    assert chapters.startswith("0:00 פתיח\n")
    assert "0:01 אחר כך" in chapters


def test_srt_uses_measured_durations_not_estimates():
    plan = parse_script("שלום עולם\n\n[pause 0.5]\nעוד משפט")
    srt = build_srt(plan.beats, [1.0, 2.0])
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:01,500 --> 00:00:03,500" in srt
    assert "שלום עולם" in srt


def test_empty_script_and_too_many_beats():
    with pytest.raises(ValueError):
        parse_script("# כותרת בלבד\n\n## בלי טקסט\n")
    huge = "\n\n".join(f"משפט {i}" for i in range(41))
    with pytest.raises(ValueError, match="40"):
        parse_script(huge)


@pytest.mark.asyncio
async def test_engine_catalog_refuses_noncommercial_sonic(client: AsyncClient):
    response = await client.get("/api/v1/youtube/engines")
    assert response.status_code == 200
    by_id = {row["id"]: row for row in response.json()}
    assert by_id["sonic"]["status"] == "refused"
    assert by_id["wav2lip"]["status"] == "refused"
    assert by_id["life"]["status"] == "builtin"
    assert by_id["latentsync"]["status"] == "not_integrated"
    assert by_id["echomimic"]["status"] == "not_integrated"
    # Honest: MuseTalk is not installed in this environment.
    assert by_id["musetalk"]["status"] == "missing"


@pytest.mark.asyncio
async def test_create_project_preview(client: AsyncClient, auth_headers, db_session: AsyncSession):
    from app.models import User

    user = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    avatar = Avatar(
        user_id=user.id,
        name="פני",
        image_url="http://localhost/face.jpg",
        s3_key="avatars/preview/image.jpg",
        status="ready",
    )
    db_session.add(avatar)
    await db_session.commit()
    await db_session.refresh(avatar)

    response = await client.post(
        "/api/v1/youtube/projects",
        headers=auth_headers,
        json={
            "avatar_id": avatar.id,
            "script": SCRIPT,
            "language": "he",
            "aspect": "portrait",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "למה השינה חשובה"
    assert body["status"] == "draft"
    assert body["aspect"] == "portrait"
    assert body["project_metadata"]["chapters"] == ["פתיח", "מה לעשות"]
    assert body["project_metadata"]["beats"] == 2

    listed = await client.get("/api/v1/youtube/projects", headers=auth_headers)
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json())

    missing = await client.post(
        "/api/v1/youtube/projects",
        headers=auth_headers,
        json={"avatar_id": avatar.id, "script": "# רק כותרת", "language": "he"},
    )
    assert missing.status_code == 400


@pytest.mark.asyncio
async def test_render_living_still_and_package(
    db_session: AsyncSession, auth_headers, client: AsyncClient
):
    from app.models import User

    user = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    portrait = Path("/tmp/yt-face.jpg")
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x224466:s=640x640,drawbox=x=40:y=80:w=220:h=220:color=white:t=fill",
            "-frames:v",
            "1",
            str(portrait),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    image_key = "avatars/render-test/image.jpg"
    await storage_service.upload_file(portrait.read_bytes(), image_key, content_type="image/jpeg")
    avatar = Avatar(
        user_id=user.id,
        name="פני",
        image_url="http://localhost/face.jpg",
        s3_key=image_key,
        status="ready",
    )
    db_session.add(avatar)
    await db_session.commit()
    await db_session.refresh(avatar)

    created = await client.post(
        "/api/v1/youtube/projects",
        headers=auth_headers,
        json={
            "avatar_id": avatar.id,
            "title": "בדיקה",
            "script": "שלום, זה סרטון קצר.\n\nעוד משפט אחד.",
            "language": "he",
            "aspect": "square",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    async def synth(text: str, output_path: str, speaker_wav, language: str) -> SynthResult:
        subprocess.check_call(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.6:sample_rate=48000",
                output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return SynthResult(
            output_path=output_path, engine="test", fallback=False, voice_cloned=False
        )

    await render_project(project_id, db_session, synthesizer=synth)
    project = (
        await db_session.execute(select(YoutubeProject).where(YoutubeProject.id == project_id))
    ).scalar_one()
    assert project.status == "ready", project.error
    assert project.engine == "living-still"
    assert project.progress == 100
    warnings = project.project_metadata["warnings"]
    assert any("אין ליפ-סינק" in warning for warning in warnings)

    video = Path(storage_service.get_local_path(project.video_key))
    srt = Path(storage_service.get_local_path(project.srt_key)).read_text(encoding="utf-8")
    chapters = Path(storage_service.get_local_path(project.chapters_key)).read_text(
        encoding="utf-8"
    )
    assert "שלום, זה סרטון קצר." in srt
    assert chapters == ""  # no headings → no fake chapter list
    assert video.stat().st_size > 1000
    probed = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        text=True,
    )
    assert float(probed.strip()) > 1.0

    frame_a = Path("/tmp/yt-frame-a.png")
    frame_b = Path("/tmp/yt-frame-b.png")
    for stamp, dest in (("0.04", frame_a), ("0.50", frame_b)):
        subprocess.check_call(
            ["ffmpeg", "-y", "-ss", stamp, "-i", str(video), "-frames:v", "1", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    assert frame_a.read_bytes() != frame_b.read_bytes()

    # Deleting the avatar must not 500, and the render row goes with it.
    deleted = await client.delete(f"/api/v1/avatars/{avatar.id}", headers=auth_headers)
    assert deleted.status_code == 204
    leftover = (
        await db_session.execute(select(YoutubeProject).where(YoutubeProject.id == project_id))
    ).scalar_one_or_none()
    assert leftover is None
