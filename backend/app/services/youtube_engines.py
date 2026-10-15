"""What this YouTube pipeline actually takes from other talking-head repos.

The catalog is the contract. A row is "builtin" only when this process can run
that idea without downloading someone else's weights. "refused" means we looked
and deliberately did not ship it.
"""

from __future__ import annotations

from app.config import settings
from app.services.animator import avatar_animator


def _musetalk_ready() -> bool:
    return avatar_animator._find_dir(settings.MUSETALK_PATH, "scripts/inference.py") is not None


def engine_catalog() -> list[dict[str, str]]:
    musetalk = _musetalk_ready()
    return [
        {
            "id": "musetalk",
            "role": "lip-sync",
            "source": "TMElyralab/MuseTalk",
            "license": "MIT",
            "taken": (
                "Real-time mouth inpainting via the persistent worker already in "
                "this repo, including the per-face coordinate cache. Used as the "
                "lip engine when the weights are installed."
            ),
            "left_out": (
                "MuseTalk does not move the body, blinks, or hold silence cleanly. "
                "A 2026 comparison put its silence score near 0.68. It is not a "
                "living avatar by itself."
            ),
            "status": "builtin" if musetalk else "missing",
        },
        {
            "id": "life",
            "role": "presence",
            "source": "KwaiVGI/LivePortrait and OpenTalker/SadTalker",
            "license": "idea only — LivePortrait weights are disputed",
            "taken": (
                "A still upload has to breathe. Each shot gets a slow zoom and a "
                "small head drift so the frame is not a frozen slide. On a "
                "MuseTalk clip the same motion is gentler, so the mouth stays in frame."
            ),
            "left_out": (
                "No neural blinks, no 3D head pose, no expression transfer. "
                "Those need LivePortrait or SadTalker weights, which are not vendored."
            ),
            "status": "builtin",
        },
        {
            "id": "hallo-chunking",
            "role": "long-form",
            "source": "fudan-generative-vision/hallo3",
            "license": "idea only",
            "taken": (
                "Long videos are rendered one paragraph at a time and cut on the "
                "sentence. That is how Hallo-class models avoid identity drift "
                "past half a minute, applied here to MuseTalk and to the still path."
            ),
            "left_out": (
                "No Hallo3 weights, and no crossfade between shots. A dissolve "
                "on a face ghosts the identity. Hard cuts at chapter lines are "
                "the edit YouTube videos actually use."
            ),
            "status": "builtin",
        },
        {
            "id": "captions",
            "role": "youtube-package",
            "source": "YouTube chapter and SRT conventions",
            "license": "n/a",
            "taken": (
                "UTF-8 SRT timed from the real audio length, plus a description "
                "file whose first chapter is 0:00 so YouTube accepts the list. "
                "Hebrew and Arabic stay right-to-left in the sidecar file."
            ),
            "left_out": (
                "Burned-in captions are optional and best-effort. YouTube's own "
                "player handles Hebrew RTL better than a burned font, so the SRT "
                "is the file you upload."
            ),
            "status": "builtin",
        },
        {
            "id": "chatterbox",
            "role": "voice",
            "source": "resemble-ai/chatterbox (already in this repo) with edge-tts fallback",
            "license": "MIT",
            "taken": (
                "The avatar's cloned voice, including Hebrew. If Chatterbox is "
                "not loaded, Microsoft neural voices (he-IL-HilaNeural for Hebrew) "
                "speak the script instead of failing silent."
            ),
            "left_out": (
                "The render reports when the clone was dropped. A fallback voice "
                "is not your voice, and the UI says so."
            ),
            "status": "builtin",
        },
        {
            "id": "latentsync",
            "role": "lip-sync-hq",
            "source": "bytedance/LatentSync",
            "license": "Apache-2.0",
            "taken": "Nothing in the runtime.",
            "left_out": (
                "Best open re-dub in 2026 comparisons, and the license is clean, "
                "but it needs a driving video plus about 18 GB of VRAM. This "
                "workstation has 12 GB, and that 12 GB is already reserved for "
                "MuseTalk. A photo upload cannot use LatentSync either."
            ),
            "status": "not_integrated",
        },
        {
            "id": "echomimic",
            "role": "half-body",
            "source": "antgroup/echomimic_v3",
            "license": "Apache-2.0",
            "taken": "Nothing in the runtime.",
            "left_out": (
                "Half-body gestures are the right next step, and the license is "
                "usable, but EchoMimic wants the whole 12 GB card for itself. "
                "Loading it beside MuseTalk would OOM this machine. A cropped "
                "portrait is not a gesture."
            ),
            "status": "not_integrated",
        },
        {
            "id": "sonic",
            "role": "expression",
            "source": "Tencent/Sonic",
            "license": "non-commercial",
            "taken": "Nothing.",
            "left_out": (
                "Refused. Sonic's README sends commercial use through Tencent Cloud. "
                "A YouTube channel is commercial, monetized or not."
            ),
            "status": "refused",
        },
        {
            "id": "wav2lip",
            "role": "lip-sync",
            "source": "Rudrabha/Wav2Lip",
            "license": "disputed training data",
            "taken": "Nothing.",
            "left_out": (
                "Rejected as a default. Sync is strong and the mouth is blurry, "
                "and the training-set license is not something to ship in a "
                "YouTube tool."
            ),
            "status": "refused",
        },
    ]
