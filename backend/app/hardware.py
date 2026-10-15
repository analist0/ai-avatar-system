"""Workstation budget for a 12 GB GPU, 64 GB RAM, and a 20-thread Intel Core Ultra.

The card is an RTX-class 12 GB part next to a Core Ultra (8 performance cores
plus efficiency cores, 20 threads). MuseTalk in float16 already wants several
gigabytes. Chatterbox and Whisper large-v3-turbo do too. Loading all three
onto this GPU runs out of memory mid-render.

So the GPU has one resident: MuseTalk. Voice cloning and transcription run on
the CPU, which has the RAM and the cores to do it. FFmpeg takes 12 of the 20
threads and leaves the rest for the desktop and for PyTorch.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    name: str
    vram_gb: int
    ram_gb: int
    cpu_threads: int
    ffmpeg_threads: int
    torch_cpu_threads: int
    uvicorn_workers: int
    celery_concurrency: int
    celery_uses_gpu: bool
    tts_device: str
    stt_device: str
    whisper_model: str
    whisper_compute: str
    gpu_resident: tuple[str, ...]
    notes: str


# One API process. A second Uvicorn worker would load a second MuseTalk.
WORKSTATION_12GB = HardwareProfile(
    name="workstation-12gb",
    vram_gb=12,
    ram_gb=64,
    cpu_threads=20,
    ffmpeg_threads=12,
    torch_cpu_threads=8,
    uvicorn_workers=1,
    celery_concurrency=1,
    celery_uses_gpu=False,
    tts_device="cpu",
    stt_device="cpu",
    whisper_model="small",
    whisper_compute="int8",
    gpu_resident=("musetalk",),
    notes=(
        "Intel Core Ultra, 20 threads, 64 GB RAM, 12 GB VRAM. "
        "The GPU holds MuseTalk in float16 and nothing else. "
        "Chatterbox and Whisper run on the CPU. One API process. "
        "Celery does not see the GPU, so it cannot load a second copy."
    ),
)


def resolve_device(requested: str, cuda_available: bool) -> str:
    """Honor an explicit cpu/cuda choice. 'auto' uses CUDA only when it exists."""
    choice = (requested or "cpu").strip().lower()
    if choice == "cpu":
        return "cpu"
    if choice == "cuda":
        return "cuda" if cuda_available else "cpu"
    if choice == "auto":
        return "cuda" if cuda_available else "cpu"
    return "cpu"


def apply_cpu_thread_budget(torch_threads: int) -> None:
    """Keep PyTorch from spawning one thread per core on top of FFmpeg."""
    import os

    count = str(max(1, torch_threads))
    os.environ.setdefault("OMP_NUM_THREADS", count)
    os.environ.setdefault("MKL_NUM_THREADS", count)
    try:
        import torch

        torch.set_num_threads(max(1, torch_threads))
    except Exception:
        return
