"""
NasTech Signal Call Bot — HTTP server for the Android AI bridge.

The Android NasTechAiBridge (inside SignalCallManager.java) calls these endpoints:

  POST /call/event   {"type":"start"|"end", "call_id":N, "recipient_id":"..."}
  POST /call/audio   {"call_id":N, "pcm_b64":"...", "sample_rate":16000}
  POST /call/levels  {"call_id":N, "captured":N, "received":N}
  GET  /call/response?call_id=N   → raw PCM bytes (16kHz mono 16-bit) or 204

Run with:
    python -m nascall_bridge.call_bot
or:
    uvicorn nascall_bridge.call_bot:app --host 127.0.0.1 --port 7766
"""

from __future__ import annotations

import asyncio
import base64
import collections
import logging
import os
import time
from typing import Deque, Dict, Optional

try:
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import JSONResponse, Response as FastResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from .config import SignalBridgeConfig
from .audio_pipeline import AudioPipeline

logger = logging.getLogger(__name__)

cfg = SignalBridgeConfig.from_env()

# ---------------------------------------------------------------------------
# Per-call state
# ---------------------------------------------------------------------------

class CallSession:
    def __init__(self, call_id: int, recipient_id: str) -> None:
        self.call_id       = call_id
        self.recipient_id  = recipient_id
        self.started_at    = time.monotonic()
        self.pipeline      = AudioPipeline(cfg)
        # Outgoing TTS PCM chunks queued for the Android to poll
        self.response_queue: Deque[bytes] = collections.deque()
        # Whether the pipeline is already running
        self._pipeline_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._pipeline_task = asyncio.create_task(self._run_pipeline())
        logger.info("[call %d] Session started for recipient %s", self.call_id, self.recipient_id)

    async def _run_pipeline(self) -> None:
        async for tts_pcm in self.pipeline.greeting():
            self.response_queue.append(tts_pcm)

    async def feed_audio(self, pcm: bytes, sample_rate: int) -> None:
        async for tts_pcm in self.pipeline.process_audio(pcm, sample_rate):
            self.response_queue.append(tts_pcm)

    def pop_response(self) -> Optional[bytes]:
        if self.response_queue:
            chunks = []
            while self.response_queue:
                chunks.append(self.response_queue.popleft())
            return b"".join(chunks)
        return None

    async def stop(self) -> None:
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
        await self.pipeline.close()
        logger.info("[call %d] Session stopped", self.call_id)


# Active call sessions keyed by call_id
_sessions: Dict[int, CallSession] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

if FASTAPI_AVAILABLE:
    app = FastAPI(title="NasTech Signal Call Bot", version="0.1.0")

    @app.post("/call/event")
    async def call_event(request: Request) -> JSONResponse:
        body = await request.json()
        event_type  = body.get("type", "")
        call_id     = int(body.get("call_id", -1))
        recipient_id = body.get("recipient_id", "")

        if event_type == "start":
            if call_id in _sessions:
                await _sessions[call_id].stop()
            session = CallSession(call_id, recipient_id)
            _sessions[call_id] = session
            await session.start()
            logger.info("Call %d started (recipient=%s)", call_id, recipient_id)

        elif event_type == "end":
            session = _sessions.pop(call_id, None)
            if session:
                await session.stop()
            logger.info("Call %d ended", call_id)

        return JSONResponse({"ok": True})

    @app.post("/call/audio")
    async def call_audio(request: Request) -> JSONResponse:
        body        = await request.json()
        call_id     = int(body.get("call_id", -1))
        pcm_b64     = body.get("pcm_b64", "")
        sample_rate = int(body.get("sample_rate", 16000))

        session = _sessions.get(call_id)
        if session is None:
            return JSONResponse({"ok": False, "error": "no such call"}, status_code=404)

        pcm = base64.b64decode(pcm_b64)
        asyncio.create_task(session.feed_audio(pcm, sample_rate))
        return JSONResponse({"ok": True})

    @app.post("/call/levels")
    async def call_levels(request: Request) -> JSONResponse:
        # Audio level hints — can be used for VAD triggering in future
        return JSONResponse({"ok": True})

    @app.get("/call/response")
    async def call_response(call_id: int) -> Response:
        session = _sessions.get(call_id)
        if session is None:
            return Response(status_code=204)

        pcm = session.pop_response()
        if pcm:
            return Response(content=pcm, media_type="application/octet-stream")
        return Response(status_code=204)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "active_calls": len(_sessions)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi and uvicorn are required: pip install fastapi uvicorn")

    errors = cfg.validate()
    for e in errors:
        logger.warning("Config warning: %s", e)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    logger.info("NasTech Signal Call Bot starting on 127.0.0.1:7766")
    uvicorn.run(app, host="127.0.0.1", port=7766, log_level=cfg.log_level.lower())


if __name__ == "__main__":
    main()
