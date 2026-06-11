# NasCall — NasTech AI-2-P Android App

> Signal-Android fully rebranded and extended so **NasTech Agent answers live voice calls in real time**.

---

## What is NasCall?

NasCall transforms a registered Signal number into an **AI-to-Person (AI-2-P) voice endpoint**.
When someone calls the NasTech number:

1. The phone rings naturally for 1.8 - 3.5 s (human feel)
2. The microphone is silently verified before answering
3. NasTech AI auto-answers and speaks in real time
4. The caller hears the AI voice — STT to NasTech Agent to TTS — live

Text messaging still works through `gateway/platforms/signal.py` (signal-cli, untouched).

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Android Studio | Ladybug 2024.2 or newer | https://developer.android.com/studio |
| JDK | 17+ | Bundled with Android Studio |
| Android SDK | API 36 (compile), API 35 (target) | Install via SDK Manager |
| Android NDK | Latest stable | Required by Signal |
| Gradle | 9.3.1 | Downloaded automatically by wrapper |
| Python | 3.10+ | For the NasCall call bot |
| pip packages | fastapi uvicorn faster-whisper httpx | See Step 4 |

---

## Project Structure

```
NasCall/                               <- Open THIS folder in Android Studio
  app/
    build.gradle.kts                   <- NASTECH_AI_MODE + NASTECH_BRIDGE_URL flags
    src/main/
      AndroidManifest.xml              <- RECORD_AUDIO, INTERNET already declared
      java/.../service/webrtc/
        SignalCallManager.java         <- NasTechAiBridge inner class (full AI pipeline)
        IncomingCallActionProcessor.java  <- voice-verified human-delay auto-answer
      res/values/strings.xml           <- NasCall branding (0 Signal strings)
  local.properties                     <- Add your sdk.dir before building
  gradle/wrapper/gradle-wrapper.properties  <- Gradle 9.3.1
  nastech/
    MODIFICATIONS.md                   <- Full architecture detail

nascall_bridge/                        <- Python call bot (run on NasTech server)
  call_bot.py                          <- FastAPI server on 127.0.0.1:7766
  audio_pipeline.py                    <- STT to NasTech AI to TTS
  config.py                            <- All settings via env vars
  ipc.py                               <- IPC helpers
```

---

## Step 1 — Get the full NasCall project

NasCall is built on top of Signal-Android. Apply the NasTech-modified files on top of a Signal clone.

```bash
# 1. Clone Signal-Android as NasCall base
git clone https://github.com/signalapp/Signal-Android NasCall

# 2. Copy the NasTech-modified files from this repo into the clone
MODS=/path/to/NasTests/NasCall

cp $MODS/app/build.gradle.kts \
   NasCall/app/build.gradle.kts

cp $MODS/app/src/main/res/values/strings.xml \
   NasCall/app/src/main/res/values/strings.xml

cp $MODS/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java \
   NasCall/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/

cp $MODS/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/IncomingCallActionProcessor.java \
   NasCall/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/
```

---

## Step 2 — Configure Android SDK path

Open `NasCall/local.properties` and set your SDK path (Android Studio fills this automatically):

```properties
# macOS
sdk.dir=/Users/YOUR_NAME/Library/Android/sdk

# Windows
sdk.dir=C\:\\Users\\YOUR_NAME\\AppData\\Local\\Android\\Sdk

# Linux
sdk.dir=/home/YOUR_NAME/Android/Sdk
```

---

## Step 3 — Enable AI mode

In `NasCall/app/build.gradle.kts` inside `defaultConfig`, change one line:

```kotlin
buildConfigField("boolean", "NASTECH_AI_MODE", "true")   // was "false"
buildConfigField("String",  "NASTECH_BRIDGE_URL", "\"http://127.0.0.1:7766\"")
```

Sync the project after saving (`File > Sync Project with Gradle Files`).

---

## Step 4 — Start the Python call bot

The Android app sends microphone audio to this bot and receives TTS audio back.

```bash
# Install dependencies
pip install fastapi uvicorn faster-whisper httpx

# Run from the NasTech workspace root
python -m nascall_bridge.call_bot

# Output: NasTech Signal Call Bot starting on 127.0.0.1:7766
```

Keep this running during calls. The bot must be reachable at `127.0.0.1:7766` from the device
(use USB tethering or run both on the same machine / same LAN with firewall open).

---

## Step 5 — Build the APK

### Android Studio (recommended)

1. Open Android Studio
2. File > Open > select the `NasCall/` folder
3. Wait for Gradle sync (downloads dependencies, ~5 min first time)
4. Build > Build Bundle(s)/APK(s) > Build APK(s)
5. APK lands at `app/build/outputs/apk/playProd/debug/`

### Command line

```bash
cd NasCall
./gradlew assemblePlayProdDebug
# APK: app/build/outputs/apk/playProd/debug/app-playProd-debug.apk
```

---

## Step 6 — Install and test

```bash
# Flash via ADB
adb install -r app/build/outputs/apk/playProd/debug/app-playProd-debug.apk
```

Test the call:
1. Make sure `python -m nascall_bridge.call_bot` is running
2. Call the NasTech number from any Signal client
3. Phone rings 1.8 - 3.5 s
4. AI answers and speaks — caller hears NasTech AI voice in real time

---

## How the AI Call Flow Works

```
Caller dials NasTech number
        |
        v
IncomingCallActionProcessor.handleLocalRinging()
  checks BuildConfig.NASTECH_AI_MODE
  OR SharedPrefs("nastech", "ai_mode") == true
        |
        v
NasTechAiBridge.onRingStarted(callId, acceptCallback)
  probes AudioRecord — verifies mic hardware is available
  if mic OK: schedules acceptCallback after 1800-3500 ms random delay
  if mic fails: stays ringing (hardware not ready)
        |
        v
SignalCallManager.acceptCallFromAi()
  delegates to IncomingCallActionProcessor.handleAcceptCall()
  call connects normally via WebRTC
        |
        v
NasTechAiBridge.onCallConnected(callId, recipientId)
  POST /call/event {"type":"start"} to call bot
  AudioRecord starts capturing mic at 16kHz mono PCM
  AudioTrack starts playing TTS responses
        |
        v
nascall_bridge/call_bot.py  (Python, running on server)
  POST /call/audio  <- receives base64 PCM from Android every frame
  faster-whisper STT -> text
  NasTech Agent LLM -> response text
  ElevenLabs / piper TTS -> PCM audio
  GET  /call/response <- Android polls every 200 ms
        |
        v
AudioTrack plays TTS -> Caller hears NasTech AI
```

---

## Toggle AI Mode Without Rebuilding

AI mode can be flipped at runtime via SharedPreferences (no APK rebuild needed):

```java
// In any Activity or Service
getSharedPreferences("nastech", Context.MODE_PRIVATE)
    .edit()
    .putBoolean("ai_mode", true)   // false to disable
    .apply();
```

Or always-on at build time via `BuildConfig.NASTECH_AI_MODE = true`.

---

## Call Bot Configuration

All settings via environment variables (no config file needed):

| Env var | Default | Description |
|---------|---------|-------------|
| `NASTECH_BRIDGE_HOST` | `127.0.0.1` | Interface the bot binds to |
| `NASTECH_BRIDGE_PORT` | `7766` | Port the bot listens on |
| `NASTECH_STT_MODEL` | `base.en` | faster-whisper model size |
| `NASTECH_TTS_ENGINE` | `piper` | TTS engine: piper or elevenlabs |
| `ELEVENLABS_API_KEY` | — | Required for ElevenLabs TTS |
| `NASTECH_LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Android Permissions

All already declared in `AndroidManifest.xml` — no changes needed:

| Permission | Used for |
|---|---|
| `RECORD_AUDIO` | AudioRecord mic capture at 16kHz |
| `INTERNET` | HTTP to nascall_bridge call bot on 127.0.0.1:7766 |
| `MODIFY_AUDIO_SETTINGS` | AudioTrack TTS playback routing |
| `WAKE_LOCK` | Keep CPU awake during call |
| `VIBRATE` | Incoming call vibration |

---

## Verification Checklist

- [x] `SignalCallManager.java` — NasTechAiBridge inner class present, 1808 lines, braces balanced (321/321)
- [x] `SignalCallManager.java` — BuildConfig imported, NASTECH_BASE_URL reads BuildConfig.NASTECH_BRIDGE_URL
- [x] `IncomingCallActionProcessor.java` — NasTech AI mode block at handleLocalRinging()
- [x] `strings.xml` — 0 Signal brand strings in user-visible values
- [x] `build.gradle.kts` — NASTECH_AI_MODE and NASTECH_BRIDGE_URL BuildConfig fields present
- [x] `AndroidManifest.xml` — RECORD_AUDIO, INTERNET, MODIFY_AUDIO_SETTINGS declared
- [x] `nascall_bridge/` — all 5 Python files pass AST syntax check
- [x] `gateway/platforms/signal.py` — untouched (handles text messaging)

---

## What is NOT in This Repo

The rest of Signal-Android (crypto, UI, protocol, database) is unmodified and publicly available at
https://github.com/signalapp/Signal-Android

Only the NasTech AI call additions and NasCall branding are maintained here.

---

Built by **NasTech**
