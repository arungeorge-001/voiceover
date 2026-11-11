#!/usr/bin/env python3
"""
desktop_app.py — CCMS Audio & Video Tools (desktop, no Streamlit)

The same three tools as app.py, in a native Tkinter window:
  Tab 1 — WebM to MP4          : convert a .webm recording to .mp4
  Tab 2 — Voiceover to MP3     : render a markdown voiceover script as .mp3
  Tab 3 — Combine MP4 + MP3    : lay a voiceover onto a video

Run:
    py desktop_app.py
Build a standalone exe:
    build_exe.bat          → dist\\CCMS_Tools.exe
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# Trust the OS certificate store so corporate SSL-inspecting proxies work
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

APP_TITLE = "CCMS Audio & Video Tools"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # hide ffmpeg console windows


# ─────────────────────────────────────────────────────────
# ffmpeg helpers
# ─────────────────────────────────────────────────────────

def get_ffmpeg() -> str:
    """Return ffmpeg binary path — bundled (imageio_ffmpeg) or system."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        raise RuntimeError("ffmpeg not found. Run: pip install imageio-ffmpeg")


def run_ffmpeg(args: list[str]) -> None:
    res = subprocess.run(
        [get_ffmpeg(), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-800:])


def media_info(path: str) -> tuple[float, bool]:
    """Return (duration_seconds, has_audio_stream) for a media file."""
    res = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW,
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
    if not m:
        raise RuntimeError(f"Could not read media file: {Path(path).name}")
    h, mnt, s = m.groups()
    duration = int(h) * 3600 + int(mnt) * 60 + float(s)
    has_audio = bool(re.search(r"Stream #.*Audio:", res.stderr))
    return duration, has_audio


# ─────────────────────────────────────────────────────────
# Tab 1 logic — WebM to MP4
# ─────────────────────────────────────────────────────────

QUALITY_PRESETS = {
    "high":   ("18", "slow",     "192k"),
    "medium": ("23", "medium",   "128k"),
    "fast":   ("28", "veryfast", "96k"),
}


def convert_webm_to_mp4(src: str, dst: str, quality: str) -> None:
    crf, preset, audio_br = QUALITY_PRESETS[quality]
    run_ffmpeg([
        "-y", "-i", src,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",       # fix white-screen: VP8/VP9/alpha WebM → yuv420p
        "-crf", crf, "-preset", preset,
        "-c:a", "aac", "-b:a", audio_br,
        "-movflags", "+faststart",
        dst,
    ])


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
    chunks = re.split(r"\n---\n", md_text.replace("\r\n", "\n"))
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
    return clean_text(" ".join(segments))


def clean_text(text: str) -> str:
    """Strip markdown emphasis and pause markers so the text reads naturally."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"\[PAUSE\]", "...", text)
    text = text.replace(" — ", ", ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def _edge_tts(text: str, voice: str, rate: str, pitch: str, out_path: str):
    import edge_tts
    # Edge TTS occasionally returns no audio; retry once before failing
    for attempt in range(2):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await comm.save(out_path)
            return
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == 1:
                raise


def generate_mp3(text: str, voice: str, rate: str, pitch: str, out_path: str) -> None:
    if not text:
        raise ValueError("No voiceover speech found in the script. Check the markdown format.")
    asyncio.run(_edge_tts(text, voice, rate, pitch, out_path))


# ─────────────────────────────────────────────────────────
# Tab 3 logic — Combine MP4 + MP3
# ─────────────────────────────────────────────────────────

def combine_video_audio(
    video: str, audio: str, out: str,
    mode: str, fit: str,
    voice_vol: float, video_vol: float,
) -> None:
    v_dur, v_has_audio = media_info(video)
    a_dur, _ = media_info(audio)

    args = ["-y", "-i", video]
    if fit == "loop_audio":
        args += ["-stream_loop", "-1"]
    args += ["-i", audio]

    if mode == "mix" and v_has_audio:
        fc = (f"[0:a]volume={video_vol}[a0];[1:a]volume={voice_vol}[a1];"
              f"[a0][a1]amix=inputs=2:duration=longest:normalize=0[aout]")
    else:
        fc = f"[1:a]volume={voice_vol}[aout]"
    args += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[aout]"]

    if fit in ("trim_audio", "loop_audio"):
        args += ["-t", f"{v_dur:.3f}"]
    elif fit == "trim_video":
        args += ["-t", f"{a_dur:.3f}"]

    audio_opts = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    try:
        # Fast path: copy the video stream untouched
        run_ffmpeg(args + ["-c:v", "copy"] + audio_opts)
    except RuntimeError:
        # Fallback: re-encode (e.g. codecs that can't go into MP4 as-is)
        run_ffmpeg(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "20", "-preset", "veryfast"] + audio_opts)


# ─────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────

def fmt_mb(path: str) -> str:
    return f"{os.path.getsize(path) / (1024 * 1024):.1f} MB"


def open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x640")
        self.minsize(640, 560)
        self.busy = False
        self.last_mp3 = None

        header = ttk.Frame(self, padding=(14, 10, 14, 0))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(header, text="NeST Digital Banking & Finance Division",
                  foreground="#666").pack(anchor="w")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=10)
        self._build_tab1(nb)
        self._build_tab2(nb)
        self._build_tab3(nb)

        status = ttk.Frame(self, padding=(14, 0, 14, 10))
        status.pack(fill="x")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=140)
        self.progress.pack(side="right")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")

    # ── shared widgets ──

    def _file_row(self, parent, row, label, var, save=False, types=None,
                  default_ext=None, on_pick=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=4)

        def browse():
            init = Path(var.get()).parent if var.get() else None
            kw = {"filetypes": types or [("All files", "*.*")]}
            if init and init.exists():
                kw["initialdir"] = str(init)
            if save:
                path = filedialog.asksaveasfilename(defaultextension=default_ext,
                                                    initialfile=Path(var.get()).name if var.get() else "",
                                                    **kw)
            else:
                path = filedialog.askopenfilename(**kw)
            if path:
                var.set(path)
                if on_pick:
                    on_pick(path)

        ttk.Button(parent, text="Browse…", command=browse).grid(row=row, column=2, pady=4)

    def _run_task(self, label, work, on_done):
        """Run work() in a background thread; call on_done(result) on the UI thread."""
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Another task is still running. Please wait.")
            return
        self.busy = True
        self.status_var.set(label)
        self.progress.start(12)

        # The worker only fills `box`; the UI thread polls it, since Tkinter
        # must not be called from a background thread.
        box = {}

        def thread():
            try:
                box["result"] = work()
            except Exception as e:
                box["err"] = e
            box["done"] = True

        def poll():
            if box.get("done"):
                finish(box.get("result"), box.get("err"))
            else:
                self.after(150, poll)

        def finish(result, err):
            self.busy = False
            self.progress.stop()
            if err:
                self.status_var.set("Failed")
                messagebox.showerror(APP_TITLE, f"{label.rstrip('. ')} failed:\n\n{err}")
            else:
                on_done(result)

        threading.Thread(target=thread, daemon=True).start()
        self.after(150, poll)

    # ── Tab 1 — WebM to MP4 ──

    def _build_tab1(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="WebM to MP4")
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Convert a screen recording or browser capture (.webm) to a ready-to-share MP4.",
                  wraplength=680).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.t1_in = tk.StringVar()
        self.t1_out = tk.StringVar()
        self._file_row(tab, 1, "WebM file", self.t1_in, types=[("WebM video", "*.webm")],
                       on_pick=lambda p: self.t1_out.set(str(Path(p).with_suffix(".mp4"))))
        self._file_row(tab, 2, "Save MP4 as", self.t1_out, save=True,
                       types=[("MP4 video", "*.mp4")], default_ext=".mp4")

        ttk.Label(tab, text="Quality").grid(row=3, column=0, sticky="w", pady=4)
        self.t1_quality = tk.StringVar(value="medium")
        q = ttk.Combobox(tab, textvariable=self.t1_quality, values=["medium", "high", "fast"],
                         state="readonly", width=12)
        q.grid(row=3, column=1, sticky="w", padx=6, pady=4)
        self.t1_qinfo = ttk.Label(tab, foreground="#666")
        self.t1_qinfo.grid(row=4, column=1, sticky="w", padx=6)
        q.bind("<<ComboboxSelected>>", lambda e: self._t1_qinfo())
        self._t1_qinfo()

        ttk.Button(tab, text="Convert to MP4", command=self._t1_convert).grid(
            row=5, column=1, sticky="w", padx=6, pady=14)
        self.t1_result = ttk.Label(tab, foreground="#0a7a2f")
        self.t1_result.grid(row=6, column=0, columnspan=3, sticky="w")

    def _t1_qinfo(self):
        crf, preset, ab = QUALITY_PRESETS[self.t1_quality.get()]
        self.t1_qinfo.config(text=f"CRF {crf}  |  preset: {preset}  |  audio: {ab}"
                                  "   (high = best / larger, fast = smaller / quicker)")

    def _t1_convert(self):
        src, dst = self.t1_in.get().strip(), self.t1_out.get().strip()
        if not src or not Path(src).exists():
            return messagebox.showwarning(APP_TITLE, "Choose a WebM file first.")
        if not dst:
            return messagebox.showwarning(APP_TITLE, "Choose where to save the MP4.")

        def done(_):
            self.status_var.set("Ready")
            self.t1_result.config(text=f"Converted successfully — {Path(dst).name} ({fmt_mb(dst)})")
            self.t3_video.set(dst)

        quality = self.t1_quality.get()
        self._run_task(f"Converting {Path(src).name} …",
                       lambda: convert_webm_to_mp4(src, dst, quality), done)

    # ── Tab 2 — Voiceover to MP3 ──

    def _build_tab2(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="Voiceover to MP3")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(8, weight=1)

        ttk.Label(tab, text="Render a voiceover markdown script, or any text you type below, "
                            "as an MP3 using Edge TTS.",
                  wraplength=680).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.t2_in = tk.StringVar()
        self.t2_out = tk.StringVar()
        self._file_row(tab, 1, "Script (.md)", self.t2_in,
                       types=[("Markdown script", "*.md *.txt"), ("All files", "*.*")],
                       on_pick=self._t2_picked)
        self._file_row(tab, 2, "Save MP3 as", self.t2_out, save=True,
                       types=[("MP3 audio", "*.mp3")], default_ext=".mp3")

        ttk.Label(tab, text="Voice").grid(row=3, column=0, sticky="w", pady=4)
        self.t2_voice = tk.StringVar(value=next(iter(VOICES)))
        ttk.Combobox(tab, textvariable=self.t2_voice, values=list(VOICES), state="readonly").grid(
            row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(tab, text="Rate (%)").grid(row=4, column=0, sticky="w")
        self.t2_rate = tk.IntVar(value=-10)
        tk.Scale(tab, variable=self.t2_rate, from_=-50, to=50, orient="horizontal").grid(
            row=4, column=1, sticky="ew", padx=6)

        ttk.Label(tab, text="Pitch (Hz)").grid(row=5, column=0, sticky="w")
        self.t2_pitch = tk.IntVar(value=-5)
        tk.Scale(tab, variable=self.t2_pitch, from_=-50, to=50, orient="horizontal").grid(
            row=5, column=1, sticky="ew", padx=6)

        btns = ttk.Frame(tab)
        btns.grid(row=6, column=1, sticky="w", padx=6, pady=10)
        ttk.Button(btns, text="Load text from script", command=self._t2_load).pack(side="left")
        ttk.Button(btns, text="Generate MP3", command=self._t2_generate).pack(side="left", padx=8)
        self.t2_play = ttk.Button(btns, text="▶ Play", state="disabled",
                                  command=lambda: open_file(self.last_mp3))
        self.t2_play.pack(side="left")

        self.t2_info = ttk.Label(tab, foreground="#666")
        self.t2_info.grid(row=7, column=0, columnspan=3, sticky="w")
        frame = ttk.Frame(tab)
        frame.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        self.t2_text = tk.Text(frame, wrap="word", height=10, font=("Segoe UI", 9), undo=True)
        sb = ttk.Scrollbar(frame, command=self.t2_text.yview)
        self.t2_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.t2_text.pack(side="left", fill="both", expand=True)
        self.t2_text.bind("<<Modified>>", self._t2_text_changed)
        self._t2_text_changed()

    def _t2_picked(self, path):
        self.t2_out.set(str(Path(path).with_suffix(".mp3")))
        self._t2_load()

    def _t2_get_text(self) -> str:
        return self.t2_text.get("1.0", "end").strip()

    def _t2_text_changed(self, _event=None):
        self.t2_text.edit_modified(False)
        words = len(self._t2_get_text().split())
        self.t2_info.config(text=f"Text to convert — {words} words   "
                                 "(load it from a script, or type / edit it here)")

    def _t2_load(self):
        """Fill the text box with the spoken lines parsed from the chosen script."""
        src = self.t2_in.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning(APP_TITLE, "Choose a markdown script first.")
            return
        text = parse_script(Path(src).read_text(encoding="utf-8"))
        if not text:
            messagebox.showwarning(APP_TITLE, "No voiceover speech found in the script — spoken lines "
                                              "must be blockquotes starting with a double quote, "
                                              "e.g.  > \"Hello …\"")
            return
        self.t2_text.delete("1.0", "end")
        self.t2_text.insert("1.0", text)

    def _t2_generate(self):
        text = clean_text(self._t2_get_text())
        if not text:
            return messagebox.showwarning(APP_TITLE, "There is no text to convert. Choose a script "
                                                     "or type some text in the box.")
        dst = self.t2_out.get().strip()
        if not dst:
            dst = filedialog.asksaveasfilename(defaultextension=".mp3", initialfile="voiceover.mp3",
                                               filetypes=[("MP3 audio", "*.mp3")])
            if not dst:
                return
            self.t2_out.set(dst)
        voice = VOICES[self.t2_voice.get()]
        rate, pitch = f"{self.t2_rate.get():+d}%", f"{self.t2_pitch.get():+d}Hz"

        def done(_):
            self.last_mp3 = dst
            self.t2_play.config(state="normal")
            self.t3_audio.set(dst)
            self.status_var.set(f"Generated {Path(dst).name} ({fmt_mb(dst)})")

        self._run_task(f"Rendering with Edge TTS ({voice}) …",
                       lambda: generate_mp3(text, voice, rate, pitch, dst), done)

    # ── Tab 3 — Combine MP4 + MP3 ──

    def _build_tab3(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="Combine MP4 + MP3")
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Lay a voiceover track onto a video. Replace or blend with the original audio.",
                  wraplength=680).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.t3_video = tk.StringVar()
        self.t3_audio = tk.StringVar()
        self.t3_out = tk.StringVar()
        self.t3_video.trace_add("write", lambda *_: self._t3_default_out())
        self._file_row(tab, 1, "Video", self.t3_video,
                       types=[("Video", "*.mp4 *.mov *.mkv"), ("All files", "*.*")])
        self._file_row(tab, 2, "Voiceover audio", self.t3_audio,
                       types=[("Audio", "*.mp3 *.wav *.m4a"), ("All files", "*.*")])
        self._file_row(tab, 3, "Save as", self.t3_out, save=True,
                       types=[("MP4 video", "*.mp4")], default_ext=".mp4")

        ttk.Label(tab, text="Mode").grid(row=4, column=0, sticky="nw", pady=(10, 4))
        modes = ttk.Frame(tab)
        modes.grid(row=4, column=1, sticky="w", padx=6, pady=(10, 4))
        self.t3_mode = tk.StringVar(value="replace")
        ttk.Radiobutton(modes, text="Replace — remove original audio, use voiceover only",
                        variable=self.t3_mode, value="replace",
                        command=self._t3_mode_changed).pack(anchor="w")
        ttk.Radiobutton(modes, text="Mix — blend both tracks",
                        variable=self.t3_mode, value="mix",
                        command=self._t3_mode_changed).pack(anchor="w")

        ttk.Label(tab, text="Duration handling").grid(row=5, column=0, sticky="w", pady=4)
        self.t3_fit = tk.StringVar(value="trim_audio")
        ttk.Combobox(tab, textvariable=self.t3_fit, state="readonly", width=14,
                     values=["trim_audio", "trim_video", "loop_audio", "as_is"]).grid(
            row=5, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(tab, foreground="#666", justify="left", text=(
            "trim_audio — cut voiceover to video length      trim_video — cut video to voiceover length\n"
            "loop_audio — loop voiceover to fill video          as_is — no change, shorter track ends first")
        ).grid(row=6, column=1, sticky="w", padx=6)

        self.t3_vols = ttk.Frame(tab)
        self.t3_vols.grid(row=7, column=1, sticky="ew", padx=6, pady=6)
        self.t3_vols.columnconfigure(1, weight=1)
        self.t3_video_vol = tk.DoubleVar(value=0.15)
        self.t3_voice_vol = tk.DoubleVar(value=1.0)
        ttk.Label(self.t3_vols, text="Original video volume").grid(row=0, column=0, sticky="w")
        tk.Scale(self.t3_vols, variable=self.t3_video_vol, from_=0, to=1, resolution=0.05,
                 orient="horizontal").grid(row=0, column=1, sticky="ew")
        ttk.Label(self.t3_vols, text="Voiceover volume").grid(row=1, column=0, sticky="w")
        tk.Scale(self.t3_vols, variable=self.t3_voice_vol, from_=0, to=1, resolution=0.05,
                 orient="horizontal").grid(row=1, column=1, sticky="ew")
        self._t3_mode_changed()

        btns = ttk.Frame(tab)
        btns.grid(row=8, column=1, sticky="w", padx=6, pady=10)
        ttk.Button(btns, text="Combine", command=self._t3_combine).pack(side="left")
        self.t3_open = ttk.Button(btns, text="▶ Open result", state="disabled",
                                  command=lambda: open_file(self.t3_out.get()))
        self.t3_open.pack(side="left", padx=8)
        self.t3_result = ttk.Label(tab, foreground="#0a7a2f")
        self.t3_result.grid(row=9, column=0, columnspan=3, sticky="w")

    def _t3_default_out(self):
        v = self.t3_video.get().strip()
        if v:
            p = Path(v)
            self.t3_out.set(str(p.with_name(p.stem + "_voiced.mp4")))

    def _t3_mode_changed(self):
        if self.t3_mode.get() == "mix":
            self.t3_vols.grid()
        else:
            self.t3_vols.grid_remove()

    def _t3_combine(self):
        video, audio, out = (self.t3_video.get().strip(), self.t3_audio.get().strip(),
                             self.t3_out.get().strip())
        if not video or not Path(video).exists():
            return messagebox.showwarning(APP_TITLE, "Choose a video file first.")
        if not audio or not Path(audio).exists():
            return messagebox.showwarning(APP_TITLE, "Choose a voiceover audio file first.")
        if not out:
            return messagebox.showwarning(APP_TITLE, "Choose where to save the result.")
        if Path(out).resolve() == Path(video).resolve():
            return messagebox.showwarning(APP_TITLE, "Save the result under a different name "
                                                     "from the input video.")
        mode = self.t3_mode.get()
        fit = self.t3_fit.get()
        voice_vol = self.t3_voice_vol.get() if mode == "mix" else 1.0
        video_vol = self.t3_video_vol.get()

        def done(_):
            self.status_var.set("Ready")
            self.t3_open.config(state="normal")
            self.t3_result.config(text=f"Combined successfully — {Path(out).name} ({fmt_mb(out)})")

        self._run_task("Combining video and audio …",
                       lambda: combine_video_audio(video, audio, out, mode, fit,
                                                   voice_vol, video_vol), done)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp text on high-DPI screens
        except Exception:
            pass
    App().mainloop()
