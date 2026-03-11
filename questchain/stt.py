"""Offline speech-to-text using faster-whisper.

Lazy-loads the model on first use. Model is downloaded automatically
on first transcription (~39 MB for the default 'tiny' model).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Override model size via env var: WHISPER_MODEL=base, tiny, small, etc.
_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "tiny")

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
            logger.info("Loading Whisper '%s' model…", _MODEL_SIZE)
            _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info("Whisper model ready.")
        except ImportError:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            )
    return _model


def transcribe(audio_path: str | Path) -> str:
    """Transcribe an audio file to text.

    Accepts any format supported by ffmpeg (OGG, WAV, MP3, M4A, …).
    Returns the transcribed text, or an empty string on failure.
    """
    model = _get_model()
    try:
        segments, _ = model.transcribe(str(audio_path), beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        return ""


def is_available() -> bool:
    """Return True if faster-whisper is installed."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False
