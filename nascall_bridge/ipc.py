"""
IPC protocol between Python (call_bot.py) and Rust (ringrtc_bot).

Uses newline-delimited JSON over a TCP socket.

Python → Rust commands:
  {"cmd": "answer",   "call_id": "...", "offer_sdp": "...", "offer_opaque": "base64"}
  {"cmd": "hangup",   "call_id": "..."}
  {"cmd": "send_audio","call_id": "...", "pcm_b64": "base64", "sample_rate": 16000}
  {"cmd": "ice_candidate", "call_id": "...", "candidate": "...", "mid": "...", "line": 0}
  {"cmd": "shutdown"}

Rust → Python events:
  {"event": "call_incoming",  "call_id": "...", "peer_id": "...", "media_type": "audio"}
  {"event": "call_connected", "call_id": "..."}
  {"event": "call_ended",     "call_id": "...", "reason": "..."}
  {"event": "audio_frame",    "call_id": "...", "pcm_b64": "base64", "sample_rate": 16000}
  {"event": "ice_candidate",  "call_id": "...", "candidate": "...", "mid": "...", "line": 0}
  {"event": "answer_ready",   "call_id": "...", "answer_sdp": "...", "answer_opaque": "base64"}
  {"event": "error",          "call_id": "...", "message": "..."}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, AsyncIterator, Callable, Coroutine

logger = logging.getLogger(__name__)


class RingRtcIpcClient:
    """Async TCP client that speaks JSON-RPC with the Rust ringrtc_bot."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._event_handlers: dict[str, list[Callable]] = {}
        self._connected = asyncio.Event()

    async def connect(self, retries: int = 10, delay: float = 0.5) -> None:
        for attempt in range(retries):
            try:
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
                self._connected.set()
                logger.info("Connected to ringrtc_bot at %s:%d", self.host, self.port)
                return
            except (ConnectionRefusedError, OSError):
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise

    async def send(self, message: dict[str, Any]) -> None:
        if self._writer is None:
            raise RuntimeError("Not connected to ringrtc_bot")
        data = json.dumps(message) + "\n"
        self._writer.write(data.encode())
        await self._writer.drain()

    async def send_answer(self, call_id: str, offer_sdp: str, offer_opaque: bytes) -> None:
        await self.send({
            "cmd": "answer",
            "call_id": call_id,
            "offer_sdp": offer_sdp,
            "offer_opaque": base64.b64encode(offer_opaque).decode(),
        })

    async def send_hangup(self, call_id: str) -> None:
        await self.send({"cmd": "hangup", "call_id": call_id})

    async def send_audio_frame(self, call_id: str, pcm_data: bytes, sample_rate: int = 16000) -> None:
        await self.send({
            "cmd": "send_audio",
            "call_id": call_id,
            "pcm_b64": base64.b64encode(pcm_data).decode(),
            "sample_rate": sample_rate,
        })

    async def send_ice_candidate(self, call_id: str, candidate: str, mid: str, line: int) -> None:
        await self.send({
            "cmd": "ice_candidate",
            "call_id": call_id,
            "candidate": candidate,
            "mid": mid,
            "line": line,
        })

    def on(self, event: str, handler: Callable) -> None:
        self._event_handlers.setdefault(event, []).append(handler)

    async def read_events(self) -> None:
        """Continuously read events from ringrtc_bot and dispatch to handlers."""
        if self._reader is None:
            raise RuntimeError("Not connected")
        while True:
            try:
                line = await self._reader.readline()
                if not line:
                    logger.warning("ringrtc_bot closed connection")
                    break
                event = json.loads(line.decode().strip())
                event_name = event.get("event", "")
                handlers = self._event_handlers.get(event_name, [])
                for handler in handlers:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(event))
                    else:
                        handler(event)
            except json.JSONDecodeError as e:
                logger.warning("Bad JSON from ringrtc_bot: %s", e)
            except Exception as e:
                logger.error("Error reading from ringrtc_bot: %s", e)
                break

    async def close(self) -> None:
        try:
            await self.send({"cmd": "shutdown"})
        except Exception:
            pass
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
