"""Render a scripted avatar video into a YouTube package.

Pipeline, per paragraph:

    text → TTS (cloned voice, or the neural fallback)
         → MuseTalk lip-sync when the weights are installed
         → a living camera move (breathing zoom + slow drift)
         → hard cut into the next paragraph

Then one MP4 (H.264 + AAC, faststart), an SRT, chapter lines, and a
description you can paste into YouTube. No model weights are downloaded here.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.voices import VOICE_DIR
from app.config import settings
from app.models import Avatar, YoutubeProject
from app.services.storage import storage_service
from app.services.tts import SynthResult, tts_service
from app.services.youtube_engines import _musetalk_ready
from app.services.youtube_script import (
    ScriptPlan,
    build_chapters,
    build_description,
    build_srt,
    estimate_seconds,
    parse_script,
)

logger = logging.getLogger(__name__)

FPS = 25
ASPECTS: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "square": (1080, 1080),
}

Synthesizer = Callable[[str, str, Optional[str], str], Awaitable[SynthResult]]


async def _default_synth(
    text: str,
    output_path: str,
    speaker_wav: Optional[str],
    language: str,
) -> SynthResult:
    return await tts_service.synthesize(
        text, output_path, speaker_wav=speaker_wav, language=language
    )


def living_still_filter(width: int, height: int, frames: int) -> str:
    """Breathing zoom + slow drift for a single still. Not a neural pose model."""
    src_w, src_h = width * 2, height * 2
    breath = max(1, int(FPS * 4))
    drift_x = max(1, int(FPS * 9))
    drift_y = max(1, int(FPS * 6.5))
    dx = max(4, int(width * 0.012))
    dy = max(3, int(height * 0.008))
    return (
        f"scale={src_w}:{src_h}:force_original_aspect_ratio=increase,"
        f"crop={src_w}:{src_h},"
        f"zoompan=z='1.04+0.03*sin(2*PI*on/{breath})':"
        f"x='iw/2-(iw/zoom/2)+{dx}*sin(2*PI*on/{drift_x})':"
        f"y='ih/2-(ih/zoom/2)+{dy}*sin(2*PI*on/{drift_y})':"
        f"d={frames}:s={width}x{height}:fps={FPS},"
        f"format=yuv420p"
    )


def living_video_filter(width: int, height: int) -> str:
    """Small camera drift on an existing lip-sync clip. The mouth moves with the frame."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"crop=w=iw*0.97:h=ih*0.97:"
        f"x='(in_w-out_w)/2+in_w*0.008*sin(t/1.6)':"
        f"y='(in_h-out_h)/2+in_h*0.005*sin(t/1.2)',"
        f"scale={width}:{height}:flags=lanczos,fps={FPS},format=yuv420p"
    )


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = stderr.decode(errors="replace")[-1200:]
        raise RuntimeError(f"{cmd[0]} failed: {tail}")


async def probe_duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode(errors='replace')[-400:]}")
    return float(stdout.decode().strip())


def _encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-threads",
        str(settings.FFMPEG_THREADS),
    ]


async def render_living_still(
    image: str,
    audio: str,
    output: str,
    width: int,
    height: int,
) -> None:
    duration = await probe_duration(audio)
    frames = max(int(duration * FPS) + FPS, FPS * 2)
    await _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            image,
            "-i",
            audio,
            "-vf",
            living_still_filter(width, height, frames),
            "-map",
            "0:v",
            "-map",
            "1:a",
            *_encode_args(),
            "-shortest",
            "-t",
            f"{duration:.3f}",
            output,
        ]
    )


async def render_living_video(
    video: str,
    audio: str,
    output: str,
    width: int,
    height: int,
) -> None:
    """Reframe a lip-sync clip and put the original WAV back so audio stays clean."""
    await _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-i",
            audio,
            "-vf",
            living_video_filter(width, height),
            "-map",
            "0:v",
            "-map",
            "1:a",
            *_encode_args(),
            "-shortest",
            output,
        ]
    )


async def append_pause(src: str, dst: str, pause: float) -> None:
    if pause <= 0:
        shutil.copyfile(src, dst)
        return
    duration = await probe_duration(src)
    await _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={pause:.3f}",
            "-af",
            f"apad=pad_dur={pause:.3f}",
            *_encode_args(),
            "-t",
            f"{duration + pause:.3f}",
            dst,
        ]
    )


def _concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", r"'\''")
    return f"file '{escaped}'\n"


async def concat_clips(clips: list[Path], output: Path) -> None:
    listing = output.with_suffix(".txt")
    listing.write_text("".join(_concat_line(clip) for clip in clips), encoding="utf-8")
    await _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            *_encode_args(),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def _subtitle_path(path: Path) -> str:
    # ffmpeg's subtitles filter treats colon, backslash, and quotes specially.
    text = str(path.resolve())
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")


async def burn_captions(video: Path, srt: Path, output: Path) -> None:
    escaped = _subtitle_path(srt)
    style = "FontName=DejaVu Sans,FontSize=22,Outline=2,Shadow=0,Alignment=2,MarginV=48"
    await _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"subtitles='{escaped}':force_style='{style}'",
            *_encode_args(),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


async def _lip_sync(image: str, audio: str, output: str) -> Optional[str]:
    """Run MuseTalk when it is actually installed. Otherwise return None."""
    if not _musetalk_ready():
        return None
    from app.services.animator import avatar_animator

    await avatar_animator.initialize()
    if avatar_animator.engine != "musetalk":
        return None
    return await avatar_animator.animate(image, audio, output)


def _speaker_wav(voice_id: Optional[str]) -> Optional[str]:
    if not voice_id:
        return None
    path = VOICE_DIR / f"{voice_id}.wav"
    if path.is_file():
        return str(path)
    return None


async def _set_progress(db: AsyncSession, project: YoutubeProject, progress: int) -> None:
    project.progress = progress
    await db.commit()


async def render_project(
    project_id: str,
    db: AsyncSession,
    *,
    synthesizer: Optional[Synthesizer] = None,
) -> None:
    result = await db.execute(select(YoutubeProject).where(YoutubeProject.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise LookupError(project_id)

    synth = synthesizer or _default_synth
    warnings: list[str] = []
    project.status = "rendering"
    project.error = None
    project.progress = 2
    await db.commit()

    try:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise RuntimeError("ffmpeg and ffprobe are required to render a YouTube video.")

        plan: ScriptPlan = parse_script(project.script)
        width, height = ASPECTS.get(project.aspect, ASPECTS["landscape"])
        avatar = await db.get(Avatar, project.avatar_id)
        if avatar is None:
            raise RuntimeError("Avatar no longer exists.")

        image_bytes = await storage_service.download_file(avatar.s3_key)
        speaker = _speaker_wav(avatar.voice_id)
        if avatar.voice_id and speaker is None:
            warnings.append("לקול של האווטר אין קובץ WAV — הדיבור יהיה בקול ברירת המחדל.")

        work = Path(tempfile.mkdtemp(prefix="yt-"))
        try:
            image_path = work / "avatar.jpg"
            image_path.write_bytes(image_bytes)
            clips: list[Path] = []
            durations: list[float] = []
            engines: list[str] = []
            tts_engines: list[str] = []
            voice_cloned = False

            for index, beat in enumerate(plan.beats):
                wav = work / f"beat-{index}.wav"
                spoken: SynthResult = await synth(beat.text, str(wav), speaker, project.language)
                tts_engines.append(spoken.engine)
                voice_cloned = voice_cloned or spoken.voice_cloned
                if spoken.fallback:
                    warnings.append(
                        f"פסקה {index + 1} לא יצאה בקול המשוכפל (מנוע: {spoken.engine})."
                    )
                speech = await probe_duration(str(wav))
                durations.append(speech)

                raw = work / f"raw-{index}.mp4"
                lived = work / f"live-{index}.mp4"
                lip = await _lip_sync(str(image_path), str(wav), str(raw))
                if lip:
                    await render_living_video(lip, str(wav), str(lived), width, height)
                    engines.append("musetalk+life")
                else:
                    await render_living_still(str(image_path), str(wav), str(lived), width, height)
                    engines.append("living-still")

                final_beat = lived
                if beat.pause_after > 0:
                    held = work / f"held-{index}.mp4"
                    await append_pause(str(lived), str(held), beat.pause_after)
                    final_beat = held
                clips.append(final_beat)
                span = len(plan.beats)
                await _set_progress(db, project, 8 + int(80 * (index + 1) / span))

            if "living-still" in engines:
                warnings.append(
                    "MuseTalk לא מותקן, אז אין ליפ-סינק. יש תנועת חיים על התמונה — "
                    "נשימה וסחיפה איטית — לא מודל הבעות."
                )

            master = work / "master.mp4"
            await concat_clips(clips, master)
            await _set_progress(db, project, 92)

            srt_text = build_srt(plan.beats, durations)
            chapters = build_chapters(plan.beats, durations)
            description = build_description(project.title, chapters)
            srt_path = work / "captions.srt"
            srt_path.write_text(srt_text, encoding="utf-8")

            upload_path = master
            captions_burned = False
            if project.burn_captions:
                burned = work / "burned.mp4"
                try:
                    await burn_captions(master, srt_path, burned)
                    upload_path = burned
                    captions_burned = True
                except Exception as exc:
                    warnings.append(
                        "צריבת הכתוביות נכשלה. קובץ ה-SRT עדיין מוכן להעלאה ליוטיוב. "
                        f"({exc.__class__.__name__})"
                    )

            prefix = f"youtube/{project.user_id}/{project.id}"
            video_key = f"{prefix}/video.mp4"
            srt_key = f"{prefix}/captions.srt"
            chapters_key = f"{prefix}/chapters.txt"
            description_key = f"{prefix}/description.txt"
            await storage_service.upload_file(
                upload_path.read_bytes(), video_key, content_type="video/mp4"
            )
            await storage_service.upload_file(
                srt_text.encode("utf-8"), srt_key, content_type="application/x-subrip"
            )
            await storage_service.upload_file(
                chapters.encode("utf-8"), chapters_key, content_type="text/plain"
            )
            await storage_service.upload_file(
                description.encode("utf-8"), description_key, content_type="text/plain"
            )

            engine_name = (
                "musetalk+life"
                if engines and set(engines) == {"musetalk+life"}
                else ("living-still" if set(engines) == {"living-still"} else "mixed")
            )
            project.video_key = video_key
            project.srt_key = srt_key
            project.chapters_key = chapters_key
            project.description_key = description_key
            project.engine = engine_name
            project.status = "ready"
            project.progress = 100
            project.error = None
            project.project_metadata = {
                **(project.project_metadata or {}),
                "beats": len(plan.beats),
                "chapters": plan.chapters,
                "duration_seconds": round(
                    sum(durations) + sum(b.pause_after for b in plan.beats), 2
                ),
                "tts_engines": sorted(set(tts_engines)),
                "voice_cloned": voice_cloned,
                "captions_burned": captions_burned,
                "width": width,
                "height": height,
                "warnings": _unique(warnings),
            }
            await db.commit()
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except Exception as exc:
        logger.exception("YouTube render failed for %s", project_id)
        project.status = "failed"
        project.error = str(exc)[:500]
        project.progress = 0
        meta = dict(project.project_metadata or {})
        meta["warnings"] = _unique(warnings)
        project.project_metadata = meta
        await db.commit()


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def preview_metadata(plan: ScriptPlan, language: str) -> dict:
    return {
        "beats": len(plan.beats),
        "chapters": plan.chapters,
        "estimated_seconds": estimate_seconds(plan, language),
        "warnings": [],
    }


# Re-exported so callers don't import Beat just to type a hint.
__all__ = ["ASPECTS", "render_project", "preview_metadata"]
