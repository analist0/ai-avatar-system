"""The 12 GB workstation budget is a contract, not a comment."""

from app.config import settings
from app.hardware import WORKSTATION_12GB, resolve_device


def test_profile_reserves_the_gpu_for_musetalk():
    profile = WORKSTATION_12GB
    assert profile.vram_gb == 12
    assert profile.ram_gb == 64
    assert profile.cpu_threads == 20
    assert profile.ffmpeg_threads == 12
    assert profile.torch_cpu_threads == 8
    assert profile.uvicorn_workers == 1
    assert profile.celery_uses_gpu is False
    assert profile.gpu_resident == ("musetalk",)
    assert profile.tts_device == "cpu"
    assert profile.stt_device == "cpu"
    assert profile.whisper_model == "small"
    assert profile.whisper_compute == "int8"


def test_settings_follow_the_workstation_profile():
    assert settings.HARDWARE_PROFILE == "workstation-12gb"
    assert settings.TTS_DEVICE == "cpu"
    assert settings.STT_DEVICE == "cpu"
    assert settings.WHISPER_MODEL == "small"
    assert settings.FFMPEG_THREADS == 12
    assert settings.UVICORN_WORKERS == 1


def test_cpu_request_is_not_promoted_to_cuda():
    assert resolve_device("cpu", cuda_available=True) == "cpu"
    assert resolve_device("cuda", cuda_available=False) == "cpu"
    assert resolve_device("cuda", cuda_available=True) == "cuda"
    assert resolve_device("auto", cuda_available=False) == "cpu"
