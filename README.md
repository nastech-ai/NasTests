# NasCall - NasTech AI-2-P Android App

Modified Signal-Android where NasTech Agent answers live voice calls.

## Files in this repo

| Path | Purpose |
|------|--------|
| NasCall/nastech/MODIFICATIONS.md | Full build + architecture guide |
| NasCall/app/build.gradle.kts | Set NASTECH_AI_MODE=true to enable AI |
| NasCall/local.properties | Add your Android SDK path here |
| NasCall/app/.../SignalCallManager.java | NasTechAiBridge inner class |
| NasCall/app/.../IncomingCallActionProcessor.java | Auto-answer with human delay |
| NasCall/app/src/main/res/values/strings.xml | NasCall branding |
| nascall_bridge/call_bot.py | Python call bot (STT to AI to TTS) |
| nascall_bridge/audio_pipeline.py | Audio processing |
| nascall_bridge/config.py | Config via env vars |

## Quick start

1. Open NasCall/ in Android Studio
2. Set sdk.dir in NasCall/local.properties
3. Set NASTECH_AI_MODE=true in NasCall/app/build.gradle.kts
4. Start the call bot: python -m nascall_bridge.call_bot
5. Build and flash the APK
6. Call the NasTech number - AI answers after 1.8-3.5s

## Architecture

Caller dials -> NasCall rings -> mic verified -> human delay ->
NasTechAiBridge -> AudioRecord PCM -> call_bot.py ->
STT + NasTech AI + TTS -> AudioTrack plays response

Built by NasTech
