"""
NasTech NasCall Bridge — AI-2-P call integration.

Transforms NasCall from peer-to-peer into AI-to-peer:
- Text messaging: handled by gateway/platforms/signal.py (signal-cli)
- Voice calls: handled by this package (call_bot + ringrtc_bot + audio_pipeline)

Quick start:
    python -m nascall_bridge.call_bot
"""

from .config import SignalBridgeConfig

__all__ = ["SignalBridgeConfig"]
__version__ = "0.1.0"
