"""
Configuration for the NasTech Signal Bridge.

All settings are read from environment variables with sensible defaults.
Copy cli-config.yaml.example and add a [nascall_bridge] section, or set
env vars directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SignalBridgeConfig:
    signal_http_url: str = field(default_factory=lambda: os.environ.get("SIGNAL_HTTP_URL", "http://127.0.0.1:8080"))
    signal_account: str = field(default_factory=lambda: os.environ.get("SIGNAL_ACCOUNT", ""))

    ringrtc_bot_path: Path = field(default_factory=lambda: Path(
        os.environ.get("RINGRTC_BOT_PATH", str(Path(__file__).parent / "ringrtc_bot" / "target" / "release" / "nastech_call_bot"))
    ))

    ipc_host: str = field(default_factory=lambda: os.environ.get("NASTECH_CALL_IPC_HOST", "127.0.0.1"))
    ipc_port: int = field(default_factory=lambda: int(os.environ.get("NASTECH_CALL_LISTEN_PORT", "9001")))

    auto_answer: bool = field(default_factory=lambda: os.environ.get("NASTECH_CALL_AUTO_ANSWER", "true").lower() == "true")
    greeting: str = field(default_factory=lambda: os.environ.get(
        "NASTECH_CALL_GREETING",
        "Hello, I'm NasTech AI. How can I help you today?"
    ))

    elevenlabs_api_key: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_VOICE_ID", "Rachel"))

    whisper_model: str = field(default_factory=lambda: os.environ.get("WHISPER_MODEL", "base.en"))
    vad_aggressiveness: int = field(default_factory=lambda: int(os.environ.get("NASTECH_VAD_AGGRESSIVENESS", "2")))

    audio_sample_rate: int = 16000
    audio_frame_duration_ms: int = 30
    silence_threshold_ms: int = 800
    max_utterance_ms: int = 30000

    signal_sfu_url: str = field(default_factory=lambda: os.environ.get(
        "NASTECH_SIGNAL_SFU_URL", "https://sfu.voip.signal.org"
    ))
    signal_ws_url: str = field(default_factory=lambda: os.environ.get(
        "NASTECH_SIGNAL_WS_URL", "wss://chat.signal.org"
    ))

    log_level: str = field(default_factory=lambda: os.environ.get("NASTECH_LOG_LEVEL", "INFO"))

    @classmethod
    def from_env(cls) -> "SignalBridgeConfig":
        return cls()

    def validate(self) -> list[str]:
        errors = []
        if not self.signal_account:
            errors.append("SIGNAL_ACCOUNT must be set (AI's Signal phone number, e.g. +12125551234)")
        if not self.elevenlabs_api_key:
            errors.append("ELEVENLABS_API_KEY not set — TTS will fall back to piper-tts (offline)")
        return errors

    @property
    def frame_samples(self) -> int:
        return self.audio_sample_rate * self.audio_frame_duration_ms // 1000

    @property
    def silence_frames(self) -> int:
        return self.silence_threshold_ms // self.audio_frame_duration_ms
