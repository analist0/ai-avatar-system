"""Turn a YouTube script into spoken beats, captions, and chapter markers.

The heading syntax matches what YouTube's description box already expects:
a chapter title on its own line, then the words the avatar should say.

    # כותרת הסרטון
    ## פתיח
    משפט ראשון.

    משפט שני.

    [pause 0.4]
    ## הנושא הבא
    עוד משפט.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_H1 = re.compile(r"^#(?!#)\s+(.+?)\s*$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_PAUSE = re.compile(r"^\[pause\s+([0-9]+(?:\.[0-9]+)?)\]\s*$", re.IGNORECASE)

# Preview only. Real captions use the measured WAV length after TTS.
# Hebrew and Arabic pack more meaning per character than English.
_CHARS_PER_SEC = {"he": 12.0, "ar": 12.0, "ja": 8.0, "zh": 8.0, "ko": 9.0}
_DEFAULT_CPS = 14.0
MAX_BEATS = 40
_MAX_PAUSE = 3.0


@dataclass
class Beat:
    text: str
    chapter: str | None
    starts_chapter: bool
    pause_after: float


@dataclass
class ScriptPlan:
    title: str | None
    beats: list[Beat] = field(default_factory=list)

    @property
    def chapters(self) -> list[str]:
        names: list[str] = []
        for beat in self.beats:
            if beat.starts_chapter and beat.chapter and beat.chapter not in names:
                names.append(beat.chapter)
        return names


def parse_script(raw: str) -> ScriptPlan:
    """Split a script into spoken beats. Raises ValueError on empty or huge input."""
    title: str | None = None
    chapter: str | None = None
    chapter_announced = False
    beats: list[Beat] = []
    buf: list[str] = []

    def flush() -> None:
        nonlocal chapter_announced
        text = " ".join(part.strip() for part in buf).strip()
        buf.clear()
        if not text:
            return
        starts = bool(chapter) and not chapter_announced
        beats.append(
            Beat(
                text=text,
                chapter=chapter,
                starts_chapter=starts,
                pause_after=0.0,
            )
        )
        if starts:
            chapter_announced = True

    for line in raw.replace("\r\n", "\n").split("\n"):
        h1 = _H1.match(line)
        if h1 and title is None and not beats and not buf:
            title = h1.group(1).strip() or None
            continue
        h2 = _H2.match(line)
        if h2:
            flush()
            chapter = h2.group(1).strip() or None
            chapter_announced = False
            continue
        pause = _PAUSE.match(line.strip())
        if pause:
            flush()
            if beats:
                beats[-1].pause_after = min(_MAX_PAUSE, float(pause.group(1)))
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line)
    flush()

    if not beats:
        raise ValueError("Script has no spoken lines.")
    if len(beats) > MAX_BEATS:
        raise ValueError(f"Script has {len(beats)} paragraphs; the maximum is {MAX_BEATS}.")

    # YouTube drops the chapter list unless the first marker is 0:00.
    if any(beat.starts_chapter for beat in beats) and not beats[0].starts_chapter:
        beats[0].starts_chapter = True
        beats[0].chapter = beats[0].chapter or "פתיח"
    return ScriptPlan(title=title, beats=beats)


def estimate_seconds(plan: ScriptPlan, language: str) -> float:
    cps = _CHARS_PER_SEC.get(language, _DEFAULT_CPS)
    total = 0.0
    for beat in plan.beats:
        total += max(0.8, len(beat.text) / cps) + beat.pause_after
    return round(total, 1)


def format_timestamp(seconds: float, *, srt: bool = False) -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    hours, ms_total = divmod(ms_total, 3_600_000)
    minutes, ms_total = divmod(ms_total, 60_000)
    secs, millis = divmod(ms_total, 1000)
    if srt:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def build_srt(beats: list[Beat], durations: list[float]) -> str:
    if len(beats) != len(durations):
        raise ValueError("Each spoken beat needs one measured duration.")
    cues: list[str] = []
    cursor = 0.0
    for index, (beat, duration) in enumerate(zip(beats, durations), start=1):
        start = cursor
        end = cursor + max(duration, 0.2)
        cues.append(
            f"{index}\n"
            f"{format_timestamp(start, srt=True)} --> {format_timestamp(end, srt=True)}\n"
            f"{beat.text}\n"
        )
        cursor = end + beat.pause_after
    return "\n".join(cues) + "\n"


def build_chapters(beats: list[Beat], durations: list[float]) -> str:
    if len(beats) != len(durations):
        raise ValueError("Each spoken beat needs one measured duration.")
    lines: list[str] = []
    cursor = 0.0
    for beat, duration in zip(beats, durations):
        if beat.starts_chapter and beat.chapter:
            lines.append(f"{format_timestamp(cursor)} {beat.chapter}")
        cursor += max(duration, 0.2) + beat.pause_after
    if not lines:
        return ""
    if not lines[0].startswith("0:00"):
        lines.insert(0, "0:00 פתיח")
    return "\n".join(lines) + "\n"


def build_description(title: str, chapters: str) -> str:
    body = chapters.strip()
    if body:
        return f"{title}\n\n{body}\n"
    return f"{title}\n"
