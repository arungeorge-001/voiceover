# CCMS Bank Portal — Voiceover & Video Pipeline

Converts a markdown voiceover script to MP3 and merges it onto a demo video.

---

## Files in this folder

| File | Purpose |
|---|---|
| `VOICEOVER_SCRIPT.md` | Source voiceover script (timestamped, markdown) |
| `voiceover_to_mp3.py` | Converts the script to an MP3 using Edge TTS |
| `combine_audio_video.py` | Merges the MP3 onto a video file |
| `VOICEOVER_SCRIPT.mp3` | Generated voiceover audio |
| `CCMS_App_v1.mp4` | Source screen-recording video |
| `CCMS_App_v1_voiced.mp4` | Final output — video + voiceover |

---

## One-time setup

Requires Python 3.10+.

```powershell
pip install edge-tts moviepy
```

That's it. No other dependencies. `moviepy` bundles its own ffmpeg automatically.

---

## Step 1 — Generate the voiceover MP3

```powershell
python voiceover_to_mp3.py
```

Reads `VOICEOVER_SCRIPT.md`, strips stage directions and markdown, and saves `VOICEOVER_SCRIPT.mp3`.

### Options

| Flag | Default | Description |
|---|---|---|
| `[INPUT]` | `VOICEOVER_SCRIPT.md` | Input markdown script file |
| `--output / -o` | `<input>.mp3` | Output MP3 path |
| `--voice / -v` | `en-US-GuyNeural` | Edge TTS voice name |
| `--rate / -r` | `-10%` | Speech rate (`-50%` to `+100%`) |
| `--pitch / -p` | `-5Hz` | Pitch adjustment (`-100Hz` to `+100Hz`) |
| `--volume` | `+0%` | Volume adjustment |
| `--preview` | — | Print extracted text without converting |
| `--list-voices / -l` | — | List all available English male voices |

### Common examples

```powershell
# Default run — GuyNeural at ~134 WPM
python voiceover_to_mp3.py

# Custom output name
python voiceover_to_mp3.py --output ccms_voiceover.mp3

# Slower pace — closer to 130 WPM target
python voiceover_to_mp3.py --rate="-13%" --pitch="-5Hz"

# Try a different voice
python voiceover_to_mp3.py --voice en-US-ChristopherNeural

# Preview the parsed text before committing to a render
python voiceover_to_mp3.py --preview

# See all available English male voices
python voiceover_to_mp3.py --list-voices
```

### Recommended male voices

| Voice name | Character |
|---|---|
| `en-US-GuyNeural` | Authoritative, clear **(default)** |
| `en-US-ChristopherNeural` | Deep, confident |
| `en-US-EricNeural` | Warm, professional |
| `en-US-AndrewNeural` | Natural, conversational |
| `en-GB-RyanNeural` | British formal tone |

### WPM reference

| `--rate` | Approx WPM |
|---|---|
| `+0%` (Edge TTS default) | ~149 |
| `-10%` | ~134 |
| `-13%` | ~130 ← matches script target |
| `-20%` | ~119 |

---

## Step 2 — Combine audio onto the video

```powershell
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3
```

Strips the original video audio and lays the voiceover on top. Output: `CCMS_App_v1_with_audio.mp4`.

### Options

| Flag | Default | Description |
|---|---|---|
| `VIDEO` | *(required)* | Input video file (MP4, MOV, MKV …) |
| `AUDIO` | *(required)* | Input audio file (MP3, WAV, M4A …) |
| `--output / -o` | `<video>_with_audio.mp4` | Output file path |
| `--mode` | `replace` | `replace` = swap audio · `mix` = blend both tracks |
| `--voice-vol` | `1.0` | Voiceover volume multiplier |
| `--video-vol` | `0.15` | Original video audio volume (mix mode only) |
| `--fit` | `trim_audio` | Duration mismatch strategy (see below) |
| `--engine` | `moviepy` | `moviepy` or `ffmpeg` |
| `--threads` | `4` | Encoding threads (moviepy only) |

### `--fit` strategies

| Value | Behaviour |
|---|---|
| `trim_audio` | Trims voiceover if longer than video **(default)** |
| `trim_video` | Trims video to match voiceover length |
| `loop_audio` | Loops voiceover to fill the full video duration |
| `as_is` | No trimming — shorter track ends first |

### Common examples

```powershell
# Default — replace audio, trim voiceover to video length
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3

# Custom output name
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3 -o CCMS_final.mp4

# Trim video to match voiceover (keeps full narration)
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3 --fit trim_video -o CCMS_final.mp4

# Mix voiceover over quiet background audio (video at 10%)
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3 --mode mix --video-vol 0.1

# ffmpeg engine — faster, lossless video copy (requires ffmpeg on PATH)
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3 --engine ffmpeg
```

---

## Full pipeline — run both steps end to end

```powershell
# Step 1 — generate voiceover MP3
python voiceover_to_mp3.py --rate="-13%" --pitch="-5Hz"

# Step 2 — combine with video
python combine_audio_video.py CCMS_App_v1.mp4 VOICEOVER_SCRIPT.mp3 -o CCMS_App_v1_voiced.mp4
```

---

## Troubleshooting

**`edge-tts` not installed**
```powershell
pip install edge-tts
```

**`moviepy` not installed**
```powershell
pip install moviepy
```

**Windows console Unicode error** (`charmap codec can't encode`)
Run with UTF-8 output:
```powershell
$env:PYTHONIOENCODING = "utf-8"
python voiceover_to_mp3.py
```

**ffmpeg engine not found**
The `moviepy` engine is self-contained and works without ffmpeg on PATH.
The `--engine ffmpeg` option requires a separate ffmpeg installation:
Download from https://ffmpeg.org/download.html and add the `bin/` folder to your system PATH.

---

*CCMS Bank Portal · NeST Digital Banking & Finance Division*
cd "d:/Audio" && python combine_audio_video.py Video_v1.mp4 VOICEOVER_SCRIPT.mp3 -o Video_v1_voiced.mp4 2>&1

& d:\Python_June_25\python.exe