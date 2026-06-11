# NasTech AI Modifications to Signal-Android

## What was changed and why

### 1. `app/src/main/java/.../service/webrtc/SignalCallManager.java`

**Changes:**
- Added `NasTechAiBridge` private inner class
- Added `nasTechBridge` field, initialized in constructor
- Hooked into `onCallEvent()` → `LOCAL_CONNECTED`/`REMOTE_CONNECTED` → `nasTechBridge.onCallConnected()`
- Hooked into `onCallEnded()` → `nasTechBridge.onCallEnded()`
- Hooked into `onAudioLevels()` → `nasTechBridge.onAudioLevels()`
- Added imports: `AudioRecord`, `AudioTrack`, `AudioFormat`, `HttpURLConnection`, `ScheduledExecutorService`

**What NasTechAiBridge does:**
- When a call connects and AI mode is enabled (`nastech` SharedPrefs `ai_mode=true`):
  - Starts `AudioRecord` capturing mic audio at 16kHz mono
  - Sends PCM chunks via `POST http://127.0.0.1:7766/call/audio`
  - Polls `GET http://127.0.0.1:7766/call/response` every 200ms for TTS audio
  - Plays TTS audio back through `AudioTrack` on the earpiece/speaker
- When the call ends: stops capture, stops playback, notifies Python server

**AI mode toggle:**
```kotlin
// Enable AI mode programmatically:
context.getSharedPreferences("nastech", Context.MODE_PRIVATE)
       .edit().putBoolean("ai_mode", true).apply()
```

---

### 2. `app/src/main/java/.../service/webrtc/IncomingCallActionProcessor.java`

**Changes:**
- Added `BuildConfig` import
- Modified `handleLocalRinging()` to auto-accept when AI mode is enabled

**What it does:**
- When `BuildConfig.NASTECH_AI_MODE = true` OR SharedPrefs `ai_mode = true`:
  - Skips the incoming call UI (no ring, no notification to user)
  - Immediately calls `handleAcceptCall(currentState, false)` (audio only)
  - The NasTechAiBridge then handles the audio pipeline

---

### 3. `app/build.gradle.kts`

**Changes:**
- Added `buildConfigField("boolean", "NASTECH_AI_MODE", "false")`
- Added `buildConfigField("String", "NASTECH_BRIDGE_URL", "\"http://127.0.0.1:7766\"")`

**To enable AI mode at build time:**
```kotlin
// In a product flavor or debug build type:
buildConfigField("boolean", "NASTECH_AI_MODE", "true")
```

---

## How to run the full AI-2-P system

### Step 1: Start signal-cli daemon (existing — handles text messages)
```bash
signal-cli -a +YOUR_NUMBER daemon --http 127.0.0.1:8080
```

### Step 2: Start the NasTech call bot (new)
```bash
cd /path/to/workspace
python -m nascall_bridge.call_bot
# Runs on http://127.0.0.1:7766
```

### Step 3: Build NasCall with NASTECH_AI_MODE=true
```bash
cd NasCall
./gradlew assemblePlayProdDebug \
  -PnasTechAiMode=true
```

Or in `app/build.gradle.kts` defaultConfig set:
```kotlin
buildConfigField("boolean", "NASTECH_AI_MODE", "true")
```

### Step 4: Install on device and make a call
- Install the modified APK
- When someone calls the phone, Signal auto-answers
- The NasTechAiBridge captures their audio → sends to call bot
- call_bot.py runs STT → NasTech AI → TTS → sends audio back
- Caller hears the AI speaking in real time

---

## Required Android permissions

Already declared in Signal's AndroidManifest.xml:
- `RECORD_AUDIO` — for AudioRecord capture
- `MODIFY_AUDIO_SETTINGS` — for AudioTrack playback
- `INTERNET` — for HTTP calls to 127.0.0.1:7766

---

## Network security (Android 9+)

The bridge calls `http://127.0.0.1:7766` (cleartext loopback).
This is allowed by default for localhost in Android.
If blocked, add to `res/xml/network_security_config.xml`:
```xml
<network-security-config>
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">127.0.0.1</domain>
  </domain-config>
</network-security-config>
```

---

## Signal Call Flow with NasTech (Direction A)

```
Caller dials phone
    ↓ Signal Protocol → Signal Server → WebSocket
Signal-Android receives CallMessage.offer
    ↓ CallMessageProcessor.kt → SignalCallManager.receivedOffer()
    ↓ RingRTC processes offer (ICE/DTLS setup)
    ↓ onCallEvent(LOCAL_RINGING)
IncomingCallActionProcessor.handleLocalRinging()
    ↓ [NASTECH_AI_MODE=true] → handleAcceptCall(false) immediately
    ↓ RingRTC sends answer + ICE candidates back to caller
    ↓ WebRTC connected (DTLS-SRTP established)
    ↓ onCallEvent(LOCAL_CONNECTED)
SignalCallManager.onCallEvent() → nasTechBridge.onCallConnected()
    ↓ NasTechAiBridge starts:
       - AudioRecord (mic → PCM)
       - AudioTrack (PCM → speaker)
       - HTTP to call_bot.py (127.0.0.1:7766)
    ↓ call_bot.py:
       - Plays greeting TTS immediately
       - Receives PCM → STT (faster-whisper)
       - Transcript → NasTech Agent (LLM)
       - Response → TTS (ElevenLabs/piper)
       - TTS PCM → queued for Android to poll
    ↓ Android polls /call/response every 200ms → plays via AudioTrack
Caller hears AI speaking, AI hears caller via AudioRecord
    ↓ Call ends (hangup from either side)
onCallEnded() → nasTechBridge.onCallEnded()
    ↓ AudioRecord stopped, AudioTrack stopped, call_bot notified
```
