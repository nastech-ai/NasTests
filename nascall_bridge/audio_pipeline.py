"""
NasTech real-time audio pipeline: STT → AI → TTS

Receives raw PCM audio frames from the Signal call,
runs speech-to-text, feeds the transcript to the NasTech agent,
and yields TTS PCM audio back to the caller.

Dependencies (install via pip):
    faster-whisper          # local STT
    webrtcvad               # voice activity detection
    elevenlabs              # TTS (or piper-tts for offline)
    httpx                   # already in NasTech
"""

from __future__ import annotations

import asyncio
import io
import logging
import struct
import time
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Stateful pipeline for one call session."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._stt      = None
        self._vad      = None
        self._tts      = None
        self._buf: bytearray = bytearray()
        self._silence_frames = 0
        self._is_speaking    = False
        self._initialized    = False
        self._greeting_done  = False

    # ------------------------------------------------------------------
    # Lazy init (imports are heavy — only load when a call arrives)
    # ------------------------------------------------------------------

    def _init(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        try:
            from faster_whisper import WhisperModel
            self._stt = WhisperModel(self.cfg.whisper_model, device="cpu", compute_type="int8")
            logger.info("faster-whisper loaded: %s", self.cfg.whisper_model)
        except ImportError:
            logger.warning("faster-whisper not installed — STT disabled (pip install faster-whisper)")

        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self.cfg.vad_aggressiveness)
        except ImportError:
            logger.warning("webrtcvad not installed — VAD disabled (pip install webrtcvad)")

        self._init_tts()

    def _init_tts(self) -> None:
        if self.cfg.elevenlabs_api_key:
            try:
                from elevenlabs.client import ElevenLabs
                self._tts_client = ElevenLabs(api_key=self.cfg.elevenlabs_api_key)
                self._tts = "elevenlabs"
                logger.info("TTS: ElevenLabs (voice=%s)", self.cfg.elevenlabs_voice_id)
                return
            except ImportError:
                logger.warning("elevenlabs not installed (pip install elevenlabs)")

        try:
            import subprocess
            result = subprocess.run(["piper", "--version"], capture_output=True)
            if result.returncode == 0:
                self._tts = "piper"
                logger.info("TTS: piper-tts (offline)")
                return
        except FileNotFoundError:
            pass

        logger.warning("No TTS engine available — AI responses will be silent")
        self._tts = None

    # ------------------------------------------------------------------
    # Greeting — played immediately when call connects
    # ------------------------------------------------------------------

    async def greeting(self) -> AsyncIterator[bytes]:
        self._init()
        if not self._greeting_done:
            self._greeting_done = True
            text = self.cfg.greeting
            async for chunk in self._synthesize(text):
                yield chunk

    # ------------------------------------------------------------------
    # Main loop — process incoming PCM
    # ------------------------------------------------------------------

    async def process_audio(self, pcm: bytes, sample_rate: int) -> AsyncIterator[bytes]:
        """
        Feed raw PCM (16-bit mono) from the call microphone.
        Yields TTS PCM chunks whenever an AI response is ready.
        """
        self._init()

        # Resample to pipeline sample rate if needed
        if sample_rate != self.cfg.audio_sample_rate:
            pcm = _resample_pcm(pcm, sample_rate, self.cfg.audio_sample_rate)

        self._buf.extend(pcm)

        # VAD chunking
        frame_len = self.cfg.frame_samples * 2  # 16-bit = 2 bytes/sample
        while len(self._buf) >= frame_len:
            frame = bytes(self._buf[:frame_len])
            del self._buf[:frame_len]

            is_speech = self._check_vad(frame)

            if is_speech:
                self._is_speaking = True
                self._silence_frames = 0
            else:
                if self._is_speaking:
                    self._silence_frames += 1
                    if self._silence_frames >= self.cfg.silence_frames:
                        # End of utterance — flush buffer to STT
                        utterance = bytes(self._buf)
                        self._buf.clear()
                        self._is_speaking = False
                        self._silence_frames = 0

                        transcript = await asyncio.get_event_loop().run_in_executor(
                            None, self._transcribe, utterance
                        )
                        if transcript and transcript.strip():
                            logger.info("STT: %r", transcript)
                            ai_response = await self._ask_ai(transcript)
                            if ai_response:
                                logger.info("AI: %r", ai_response[:80])
                                async for chunk in self._synthesize(ai_response):
                                    yield chunk

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_vad(self, frame: bytes) -> bool:
        if self._vad is None:
            # Fallback: energy-based VAD
            if len(frame) < 2:
                return False
            samples = struct.unpack(f"{len(frame)//2}h", frame)
            energy = sum(s * s for s in samples) / len(samples)
            return energy > 500_000
        try:
            return self._vad.is_speech(frame, self.cfg.audio_sample_rate)
        except Exception:
            return False

    def _transcribe(self, pcm: bytes) -> str:
        if self._stt is None or not pcm:
            return ""
        try:
            import numpy as np
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = self._stt.transcribe(samples, beam_size=5, language="en")
            return " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.warning("STT error: %s", e)
            return ""

    async def _ask_ai(self, text: str) -> str:
        """
        Send transcript to the NasTech agent and get a response.
        Uses the agent's internal run_agent() if available,
        otherwise falls back to the local HTTP API.
        """
        try:
            from agent.agent_runtime_helpers import run_one_shot
            response = await asyncio.get_event_loop().run_in_executor(
                None, run_one_shot, text
            )
            return response or ""
        except ImportError:
            pass

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "http://127.0.0.1:8000/api/chat",
                    json={"message": text, "session_id": "signal_call"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("response", data.get("text", ""))
        except Exception as e:
            logger.warning("AI API call failed: %s", e)

        return "I received your message. One moment please."

    async def _synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw PCM bytes (16kHz mono 16-bit) for the given text."""
        if not text or self._tts is None:
            return

        if self._tts == "elevenlabs":
            async for chunk in self._tts_elevenlabs(text):
                yield chunk
        elif self._tts == "piper":
            async for chunk in self._tts_piper(text):
                yield chunk

    async def _tts_elevenlabs(self, text: str) -> AsyncIterator[bytes]:
        try:
            loop = asyncio.get_event_loop()
            audio_bytes = await loop.run_in_executor(None, self._elevenlabs_blocking, text)
            if audio_bytes:
                pcm = _mp3_to_pcm(audio_bytes, self.cfg.audio_sample_rate)
                if pcm:
                    yield pcm
        except Exception as e:
            logger.warning("ElevenLabs TTS error: %s", e)

    def _elevenlabs_blocking(self, text: str) -> Optional[bytes]:
        audio = self._tts_client.generate(
            text=text,
            voice=self.cfg.elevenlabs_voice_id,
            model="eleven_turbo_v2",
            output_format="mp3_22050_32",
        )
        return b"".join(audio)

    async def _tts_piper(self, text: str) -> AsyncIterator[bytes]:
        try:
            import subprocess
            proc = await asyncio.create_subprocess_exec(
                "piper", "--output-raw",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            raw, _ = await proc.communicate(text.encode())
            if raw:
                yield raw
        except Exception as e:
            logger.warning("piper TTS error: %s", e)

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample_pcm(pcm: bytes, from_rate: int, to_rate: int) -> bytes:
    """Simple nearest-neighbour resampling for PCM 16-bit mono."""
    if from_rate == to_rate:
        return pcm
    try:
        import numpy as np
        samples = np.frombuffer(pcm, dtype=np.int16)
        ratio   = to_rate / from_rate
        n_out   = int(len(samples) * ratio)
        indices = (np.arange(n_out) / ratio).astype(int)
        indices = np.clip(indices, 0, len(samples) - 1)
        return samples[indices].tobytes()
    except ImportError:
        return pcm


def _mp3_to_pcm(mp3_bytes: bytes, sample_rate: int) -> Optional[bytes]:
    """Convert mp3 bytes → raw PCM 16-bit mono at sample_rate via ffmpeg."""
    try:
        import subprocess
        proc = subprocess.run(
            [
                "ffmpeg", "-i", "pipe:0",
                "-f", "s16le", "-ar", str(sample_rate),
                "-ac", "1", "pipe:1", "-loglevel", "quiet",
            ],
            input=mp3_bytes,
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except FileNotFoundError:
        logger.warning("ffmpeg not found — cannot convert MP3 to PCM")
    except Exception as e:
        logger.warning("ffmpeg error: %s", e)
    return None
