"""Speak tool — generates audio via Kokoro TTS and plays it."""

import importlib.util
import io
import wave
from collections.abc import Callable, Awaitable
from pathlib import Path

import numpy as np
from langchain_core.tools import tool

# Lazy-loaded singleton
_kokoro = None

SAMPLE_RATE = 24000


def _get_model_dir() -> Path:
    from questchain.config import SPEAK_MODEL_DIR
    return Path(SPEAK_MODEL_DIR)


def _model_path() -> Path:
    return _get_model_dir() / "kokoro-v1.0.onnx"


def _voices_path() -> Path:
    return _get_model_dir() / "voices-v1.0.bin"


def is_speak_available() -> bool:
    """Return True if kokoro_onnx is installed, SPEAK_ENABLED is set, and model files exist."""
    from questchain.config import SPEAK_ENABLED
    if not SPEAK_ENABLED:
        return False
    if importlib.util.find_spec("kokoro_onnx") is None:
        return False
    return _model_path().exists() and _voices_path().exists()


def _get_kokoro():
    """Lazy-load and cache the Kokoro TTS model."""
    global _kokoro
    if _kokoro is None:
        if not is_speak_available():
            raise RuntimeError(
                "Speak not set up — run /speak in the CLI to install Kokoro TTS."
            )
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(_model_path()), str(_voices_path()))
    return _kokoro


def _samples_to_wav(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convert float32 samples to WAV bytes."""
    pcm_int16 = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


def create_speak_tool(on_audio: Callable[[bytes], Awaitable[None]]):
    """Create a speak tool that calls on_audio with WAV bytes.

    Args:
        on_audio: Async callback that receives WAV bytes and outputs them
                  (e.g. play on speakers or send as Telegram voice message).
    """
    from questchain.config import SPEAK_VOICE

    @tool
    async def speak(text: str) -> str:
        """Speak text aloud using text-to-speech. Use this to talk to the user with your voice."""
        kokoro = _get_kokoro()
        voice = SPEAK_VOICE or "bm_fable"

        all_samples = []
        stream = kokoro.create_stream(text, voice=voice, speed=1.0, lang="en-us")
        async for samples, _sr in stream:
            all_samples.append(samples)

        if not all_samples:
            return "Failed to generate audio."

        combined = np.concatenate(all_samples)
        wav_bytes = _samples_to_wav(combined)
        await on_audio(wav_bytes)

        truncated = text[:80] + "..." if len(text) > 80 else text
        return f"Spoke: {truncated}"

    return speak
