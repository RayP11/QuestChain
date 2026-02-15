"""Kokoro TTS service for Pipecat using kokoro-onnx (local, no PyTorch)."""

import numpy as np
from kokoro_onnx import Kokoro
from loguru import logger

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService


class KokoroTTSService(TTSService):
    """Local TTS using Kokoro ONNX.

    Model files must be downloaded manually from:
    https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0

    Place ``kokoro-v1.0.onnx`` and ``voices-v1.0.bin`` in the working directory
    (or pass custom paths).
    """

    SAMPLE_RATE = 24000

    def __init__(
        self,
        *,
        model_path: str = "kokoro-v1.0.onnx",
        voices_path: str = "voices-v1.0.bin",
        voice: str = "af_heart",
        speed: float = 1.0,
        lang: str = "en-us",
        **kwargs,
    ):
        super().__init__(sample_rate=self.SAMPLE_RATE, **kwargs)
        self._voice = voice
        self._speed = speed
        self._lang = lang
        logger.info("Loading Kokoro TTS model from {}", model_path)
        self._kokoro = Kokoro(model_path, voices_path)
        logger.info("Kokoro TTS ready (voice={}, lang={})", voice, lang)

    async def run_tts(self, text: str, context_id: str):
        """Synthesize *text* and push audio frames into the pipeline."""
        try:
            await self.start_ttfb_metrics()
            yield TTSStartedFrame(context_id=context_id)

            await self.start_tts_usage_metrics(text)

            stream = self._kokoro.create_stream(
                text,
                voice=self._voice,
                speed=self._speed,
                lang=self._lang,
            )
            async for samples, _sample_rate in stream:
                # kokoro returns float32 [-1, 1]; convert to int16 PCM bytes
                pcm_int16 = (samples * 32767).astype(np.int16)
                yield TTSAudioRawFrame(
                    audio=pcm_int16.tobytes(),
                    sample_rate=self.SAMPLE_RATE,
                    num_channels=1,
                    context_id=context_id,
                )

            yield TTSStoppedFrame(context_id=context_id)

        except Exception as e:
            logger.error("Kokoro TTS error: {}", e)
            yield ErrorFrame(error=f"Kokoro TTS error: {e}")
            yield TTSStoppedFrame(context_id=context_id)
