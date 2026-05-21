#!/usr/bin/env python3
"""
app.py — CCMS Audio & Video Tools (Streamlit)

Three tools in one UI:
  Tab 1 — WebM to MP4          : upload a .webm, download .mp4
  Tab 2 — Voiceover to MP3     : upload a markdown script, download .mp3
  Tab 3 — Combine MP4 + MP3    : merge video and voiceover, download final .mp4

Run:
    streamlit run app.py
"""

import asyncio
import re
import subprocess
import tempfile
import threading
from pathlib import Path

import streamlit as st


# ─────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CCMS Audio & Video Tools",
    layout="centered",
)

st.title("CCMS Audio & Video Tools")
st.caption("NeST Digital Banking & Finance Division")

# Initialise session state buckets
for _key in ["tab1_mp4", "tab1_mp4_name",
             "tab2_mp3", "tab2_preview_text",
             "tab3_video"]:
    if _key not in st.session_state:
        st.session_state[_key] = None


# ─────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────

def get_ffmpeg() -> str:
    """Return ffmpeg binary path — bundled (imageio_ffmpeg) or system."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        st.error("ffmpeg not found. Run: pip install moviepy")
        st.stop()


def _run_async(coro):
    """Run an async coroutine safely from a synchronous Streamlit context."""
    result, exc = [None], [None]
    def _thread():
        try:
            result[0] = asyncio.run(coro)
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=_thread)
    t.start()
    t.join()
    if exc[0]:
        raise exc[0]
    return result[0]


def fmt_mb(b: bytes) -> str:
    return f"{len(b) / (1024 * 1024):.1f} MB"


# ─────────────────────────────────────────────────────────
# Tab 1 logic — WebM to MP4
# ─────────────────────────────────────────────────────────

QUALITY_PRESETS = {
    "high":   ("18", "slow",     "192k"),
    "medium": ("23", "medium",   "128k"),
    "fast":   ("28", "veryfast", "96k"),
}


def convert_webm_to_mp4(webm_bytes: bytes, src_name: str, quality: str) -> bytes:
    crf, preset, audio_br = QUALITY_PRESETS[quality]
    ffmpeg = get_ffmpeg()
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / src_name
        out = Path(tmp) / Path(src_name).with_suffix(".mp4").name
        inp.write_bytes(webm_bytes)
        cmd = [
            ffmpeg, "-y", "-i", str(inp),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",       # fix white-screen: VP8/VP9/alpha WebM → yuv420p
            "-crf", crf, "-preset", preset,
            "-c:a", "aac", "-b:a", audio_br,
            "-movflags", "+faststart",
            str(out),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr[-600:])
        return out.read_bytes()


# ─────────────────────────────────────────────────────────
# Tab 2 logic — Voiceover to MP3
# ─────────────────────────────────────────────────────────

VOICES = {
    "Andrew — natural, conversational  (default)": "en-US-AndrewNeural",
    "Guy — authoritative, clear":                  "en-US-GuyNeural",
    "Christopher — deep, confident":               "en-US-ChristopherNeural",
    "Eric — warm, professional":                   "en-US-EricNeural",
    "Ryan GB — British formal":                    "en-GB-RyanNeural",
    "Thomas GB — British":                         "en-GB-ThomasNeural",
}


def parse_script(md_text: str) -> str:
    """Extract spoken lines from voiceover markdown. Returns clean plain text."""
    chunks = re.split(r"\n---\n", md_text)
    segments = []
    for chunk in chunks:
        bq = [ln.strip()[1:].strip() for ln in chunk.splitlines() if ln.strip().startswith(">")]
        if not bq:
            continue
        joined = " ".join(t for t in bq if t)
        if not joined.startswith('"'):
            continue
        speech = joined.strip('"').strip()
        if speech:
            segments.append(speech)
    text = " ".join(segments)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"\[PAUSE\]", "...", text)
    text = text.replace(" — ", ", ")
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


async def _edge_tts(text: str, voice: str, rate: str, pitch: str, out_path: str):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(out_path)


def convert_script_to_mp3(md_text: str, voice: str, rate: str, pitch: str) -> tuple[bytes, str]:
    """Returns (mp3_bytes, parsed_text)."""
    text = parse_script(md_text)
    if not text:
        raise ValueError("No voiceover speech found in the script. Check the markdown format.")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "voiceover.mp3"
        _run_async(_edge_tts(text, voice, rate, pitch, str(out)))
        return out.read_bytes(), text


# ─────────────────────────────────────────────────────────
# Tab 3 logic — Combine MP4 + MP3
# ─────────────────────────────────────────────────────────

def combine_video_audio(
    video_bytes: bytes, video_name: str,
    audio_bytes: bytes, audio_name: str,
    mode: str, fit: str,
    voice_vol: float, video_vol: float,
) -> bytes:
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips
        ver = 2
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips
        ver = 1

    def _trim(clip, end):
        return clip.subclipped(0, end) if hasattr(clip, "subclipped") else clip.subclip(0, end)

    def _vol(clip, factor):
        return clip.with_volume_scaled(factor) if hasattr(clip, "with_volume_scaled") else clip.volumex(factor)

    def _set_audio(vid, aud):
        return vid.with_audio(aud) if hasattr(vid, "with_audio") else vid.set_audio(aud)

    with tempfile.TemporaryDirectory() as tmp:
        vpath = Path(tmp) / video_name
        apath = Path(tmp) / audio_name
        opath = Path(tmp) / "combined.mp4"
        vpath.write_bytes(video_bytes)
        apath.write_bytes(audio_bytes)

        video = VideoFileClip(str(vpath))
        voice = AudioFileClip(str(apath))
        v_dur, a_dur = video.duration, voice.duration

        if fit == "trim_audio" and a_dur > v_dur:
            voice = _trim(voice, v_dur)
        elif fit == "trim_video" and v_dur > a_dur:
            video = _trim(video, a_dur)
        elif fit == "loop_audio" and a_dur < v_dur:
            loops = int(v_dur / a_dur) + 2
            voice = _trim(concatenate_audioclips([voice] * loops), v_dur)

        if voice_vol != 1.0:
            voice = _vol(voice, voice_vol)

        if mode == "mix" and video.audio is not None:
            orig = _vol(video.audio, video_vol)
            final_audio = CompositeAudioClip([orig, voice])
        else:
            final_audio = voice

        final = _set_audio(video, final_audio)
        final.write_videofile(str(opath), codec="libx264", audio_codec="aac",
                              threads=4, logger=None)
        for c in (video, voice, final):
            try: c.close()
            except: pass

        return opath.read_bytes()


# ─────────────────────────────────────────────────────────
# UI — three tabs
# ─────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["WebM to MP4", "Voiceover to MP3", "Combine MP4 + MP3"])


# ══════════════════════════════════════════════
# Tab 1 — WebM to MP4
# ══════════════════════════════════════════════

with tab1:
    st.subheader("Convert WebM to MP4")
    st.write("Upload a screen recording or browser capture (.webm) and download a ready-to-share MP4.")

    webm_file = st.file_uploader("Choose a WebM file", type=["webm"], key="webm_upload")

    col_q, col_gap = st.columns([1, 2])
    with col_q:
        quality = st.selectbox(
            "Quality",
            options=["medium", "high", "fast"],
            index=0,
            help="high = best quality / large file  |  fast = smaller / quicker",
        )

    st.caption(f"CRF {QUALITY_PRESETS[quality][0]}  |  preset: {QUALITY_PRESETS[quality][1]}  |  audio: {QUALITY_PRESETS[quality][2]}")

    convert_btn = st.button("Convert to MP4", disabled=webm_file is None, key="btn_webm")

    if convert_btn and webm_file:
        with st.spinner(f"Converting {webm_file.name} ..."):
            try:
                mp4_bytes = convert_webm_to_mp4(webm_file.read(), webm_file.name, quality)
                st.session_state["tab1_mp4"] = mp4_bytes
                st.session_state["tab1_mp4_name"] = Path(webm_file.name).with_suffix(".mp4").name
            except Exception as e:
                st.error(f"Conversion failed:\n{e}")

    if st.session_state["tab1_mp4"]:
        mp4_bytes = st.session_state["tab1_mp4"]
        out_name  = st.session_state["tab1_mp4_name"]
        st.success(f"Converted successfully — {fmt_mb(mp4_bytes)}")
        st.download_button(
            label=f"Download  {out_name}",
            data=mp4_bytes,
            file_name=out_name,
            mime="video/mp4",
            use_container_width=True,
        )


# ══════════════════════════════════════════════
# Tab 2 — Voiceover to MP3
# ══════════════════════════════════════════════

with tab2:
    st.subheader("Convert Voiceover Script to MP3")
    st.write("Upload a timestamped voiceover markdown script and render it as an MP3 using Edge TTS.")

    # Source: upload or use local file
    local_script = Path("VOICEOVER_SCRIPT.md")
    source_opts  = ["Upload .md file"]
    if local_script.exists():
        source_opts.append("Use VOICEOVER_SCRIPT.md  (already in folder)")

    source = st.radio("Script source", source_opts, horizontal=True)

    md_file = None
    md_text = None

    if source == "Upload .md file":
        md_file = st.file_uploader("Choose a markdown script", type=["md", "txt"], key="md_upload")
        if md_file:
            md_text = md_file.read().decode("utf-8")
    else:
        md_text = local_script.read_text(encoding="utf-8")
        st.caption(f"Loaded: {local_script}  ({len(md_text):,} chars)")

    st.divider()

    col_v, col_r, col_p = st.columns(3)
    with col_v:
        voice_label = st.selectbox("Voice", options=list(VOICES.keys()), index=0)
        voice_id    = VOICES[voice_label]
    with col_r:
        rate_val = st.slider("Rate (%)", min_value=-50, max_value=50, value=-10, step=1)
        rate_str = f"{rate_val:+d}%"
        st.caption(f"→ {rate_str}")
    with col_p:
        pitch_val = st.slider("Pitch (Hz)", min_value=-50, max_value=50, value=-5, step=1)
        pitch_str = f"{pitch_val:+d}Hz"
        st.caption(f"→ {pitch_str}")

    col_prev, col_gen = st.columns(2)

    with col_prev:
        if st.button("Preview parsed text", disabled=md_text is None, key="btn_preview"):
            try:
                parsed = parse_script(md_text)
                st.session_state["tab2_preview_text"] = parsed
            except Exception as e:
                st.error(str(e))

    with col_gen:
        if st.button("Generate MP3", disabled=md_text is None, key="btn_mp3", type="primary"):
            with st.spinner(f"Rendering with Edge TTS ({voice_id}) ..."):
                try:
                    mp3_bytes, parsed = convert_script_to_mp3(md_text, voice_id, rate_str, pitch_str)
                    st.session_state["tab2_mp3"] = mp3_bytes
                    st.session_state["tab2_preview_text"] = parsed
                except Exception as e:
                    st.error(f"Generation failed:\n{e}")

    # Preview expander
    if st.session_state["tab2_preview_text"]:
        txt = st.session_state["tab2_preview_text"]
        wpm_est = int(len(txt.split()) / ((1 + (rate_val / -100)) * 0.01 + 1) * 1.5)
        with st.expander(f"Parsed text — {len(txt.split())} words"):
            st.text(txt)

    if st.session_state["tab2_mp3"]:
        mp3_bytes = st.session_state["tab2_mp3"]
        st.success(f"Generated successfully — {fmt_mb(mp3_bytes)}")
        st.audio(mp3_bytes, format="audio/mp3")
        st.download_button(
            label="Download  VOICEOVER_SCRIPT.mp3",
            data=mp3_bytes,
            file_name="VOICEOVER_SCRIPT.mp3",
            mime="audio/mpeg",
            use_container_width=True,
        )


# ══════════════════════════════════════════════
# Tab 3 — Combine MP4 + MP3
# ══════════════════════════════════════════════

with tab3:
    st.subheader("Combine MP4 + MP3")
    st.write("Lay a voiceover track onto a video. Replace or blend with the original audio.")

    # ── Video source ──
    st.markdown("**Video source**")
    video_source_opts = ["Upload MP4"]
    if st.session_state["tab1_mp4"]:
        video_source_opts.append(f"Use converted MP4 from Tab 1  ({st.session_state['tab1_mp4_name']})")

    video_source = st.radio("", video_source_opts, horizontal=True, key="vid_src", label_visibility="collapsed")

    vid_bytes = vid_name = None
    if "Tab 1" in video_source:
        vid_bytes = st.session_state["tab1_mp4"]
        vid_name  = st.session_state["tab1_mp4_name"]
        st.caption(f"Using: {vid_name}  ({fmt_mb(vid_bytes)})")
    else:
        mp4_upload = st.file_uploader("Choose an MP4 / MOV / MKV file", type=["mp4", "mov", "mkv"], key="mp4_upload")
        if mp4_upload:
            vid_bytes = mp4_upload.read()
            vid_name  = mp4_upload.name

    st.divider()

    # ── Audio source ──
    st.markdown("**Audio source**")
    audio_source_opts = ["Upload MP3"]
    if st.session_state["tab2_mp3"]:
        audio_source_opts.append("Use generated MP3 from Tab 2")

    audio_source = st.radio("", audio_source_opts, horizontal=True, key="aud_src", label_visibility="collapsed")

    aud_bytes = aud_name = None
    if "Tab 2" in audio_source:
        aud_bytes = st.session_state["tab2_mp3"]
        aud_name  = "VOICEOVER_SCRIPT.mp3"
        st.caption(f"Using: {aud_name}  ({fmt_mb(aud_bytes)})")
    else:
        mp3_upload = st.file_uploader("Choose an MP3 / WAV / M4A file", type=["mp3", "wav", "m4a"], key="mp3_upload")
        if mp3_upload:
            aud_bytes = mp3_upload.read()
            aud_name  = mp3_upload.name

    st.divider()

    # ── Settings ──
    col_m, col_f = st.columns(2)
    with col_m:
        mode = st.radio(
            "Mode",
            ["replace", "mix"],
            captions=["Remove original audio, use voiceover only", "Blend both tracks"],
        )
    with col_f:
        fit = st.selectbox(
            "Duration handling",
            ["trim_audio", "trim_video", "loop_audio", "as_is"],
            help=(
                "trim_audio — cut voiceover to video length\n"
                "trim_video — cut video to voiceover length\n"
                "loop_audio — loop voiceover to fill video\n"
                "as_is      — no change, shorter track ends first"
            ),
        )

    voice_vol = 1.0
    video_vol = 0.15
    if mode == "mix":
        col_vv, col_av = st.columns(2)
        with col_vv:
            video_vol = st.slider("Original video volume", 0.0, 1.0, 0.15, 0.05)
        with col_av:
            voice_vol = st.slider("Voiceover volume", 0.0, 1.0, 1.0, 0.05)

    ready = vid_bytes is not None and aud_bytes is not None
    combine_btn = st.button("Combine", disabled=not ready, type="primary", key="btn_combine")

    if combine_btn and ready:
        with st.spinner("Combining video and audio — this may take a minute ..."):
            try:
                out_bytes = combine_video_audio(
                    vid_bytes, vid_name,
                    aud_bytes, aud_name,
                    mode, fit, voice_vol, video_vol,
                )
                st.session_state["tab3_video"] = out_bytes
            except Exception as e:
                st.error(f"Combine failed:\n{e}")

    if st.session_state["tab3_video"]:
        out_bytes = st.session_state["tab3_video"]
        out_name  = Path(vid_name).stem + "_voiced.mp4" if vid_name else "combined.mp4"
        st.success(f"Combined successfully — {fmt_mb(out_bytes)}")
        st.download_button(
            label=f"Download  {out_name}",
            data=out_bytes,
            file_name=out_name,
            mime="video/mp4",
            use_container_width=True,
        )
