#!/usr/bin/env python3
"""
combine_audio_video.py — Overlay voiceover MP3 onto a video file

Modes:
  replace   Remove original video audio, use voiceover only (default)
  mix       Blend voiceover with original video audio

Duration handling (--fit):
  trim_audio   Trim voiceover if longer than video (default)
  trim_video   Trim video to match voiceover length
  loop_audio   Loop voiceover to fill the full video duration
  as_is        No change — shorter track ends first

Engines:
  moviepy   Pure-Python, handles all formats  (pip install moviepy)
  ffmpeg    Lossless video copy, fastest       (requires ffmpeg on PATH)

Usage:
    python combine_audio_video.py demo.mp4 VOICEOVER_SCRIPT.mp3
    python combine_audio_video.py demo.mp4 VOICEOVER_SCRIPT.mp3 -o final.mp4
    python combine_audio_video.py demo.mp4 voice.mp3 --mode mix --video-vol 0.1
    python combine_audio_video.py demo.mp4 voice.mp3 --engine ffmpeg
    python combine_audio_video.py demo.mp4 voice.mp3 --fit trim_video
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────
# moviepy compatibility shims  (supports v1 and v2)
# ──────────────────────────────────────────────────────────

def _import_moviepy():
    """Return (VideoFileClip, AudioFileClip, CompositeAudioClip, concat, version)."""
    try:
        from moviepy.editor import (  # noqa: PLC0415
            VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips,
        )
        return VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips, 1
    except ImportError:
        pass
    try:
        from moviepy import (  # noqa: PLC0415
            VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips,
        )
        return VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips, 2
    except ImportError:
        return None


def _trim(clip, end, ver):
    # v1: subclip  |  v2: subclipped
    if hasattr(clip, "subclipped"):
        return clip.subclipped(0, end)
    return clip.subclip(0, end)


def _set_audio(video, audio, ver):
    # v1: set_audio  |  v2: with_audio
    if hasattr(video, "with_audio"):
        return video.with_audio(audio)
    return video.set_audio(audio)


def _volumex(audio_clip, factor, ver):
    # v1: volumex  |  v2: with_volume_scaled
    if hasattr(audio_clip, "with_volume_scaled"):
        return audio_clip.with_volume_scaled(factor)
    return audio_clip.volumex(factor)


# ──────────────────────────────────────────────────────────
# moviepy engine
# ──────────────────────────────────────────────────────────

def run_moviepy(
    video_path: str,
    audio_path: str,
    output_path: str,
    mode: str,
    voice_vol: float,
    video_vol: float,
    fit: str,
    threads: int,
) -> None:
    result = _import_moviepy()
    if result is None:
        print("Error: moviepy not installed.\nRun: pip install moviepy")
        sys.exit(1)

    VideoFileClip, AudioFileClip, CompositeAudioClip, concat_audio, ver = result
    print(f"Engine : moviepy v{ver}")

    video = VideoFileClip(video_path)
    voice = AudioFileClip(audio_path)

    v_dur = video.duration
    a_dur = voice.duration
    print(f"Video  : {v_dur:.1f}s")
    print(f"Audio  : {a_dur:.1f}s")

    # ── Duration handling ──
    if fit == "trim_audio" and a_dur > v_dur:
        print(f"Trimming audio to {v_dur:.1f}s to match video")
        voice = _trim(voice, v_dur, ver)

    elif fit == "trim_video" and v_dur > a_dur:
        print(f"Trimming video to {a_dur:.1f}s to match audio")
        video = _trim(video, a_dur, ver)

    elif fit == "loop_audio" and a_dur < v_dur:
        loops = int(v_dur / a_dur) + 2
        print(f"Looping audio x{loops} to fill {v_dur:.1f}s")
        voice = _trim(concat_audio([voice] * loops), v_dur, ver)

    # ── Volume ──
    if voice_vol != 1.0:
        voice = _volumex(voice, voice_vol, ver)

    # ── Compose audio track ──
    if mode == "mix" and video.audio is not None:
        orig = _volumex(video.audio, video_vol, ver)
        final_audio = CompositeAudioClip([orig, voice])
        print(f"Mixing: video audio x{video_vol}  +  voiceover x{voice_vol}")
    else:
        final_audio = voice
        if mode == "mix":
            print("Warning: source video has no audio track — using voiceover only")

    # ── Encode ──
    ext = Path(output_path).suffix.lower()
    codec = "libx264" if ext in (".mp4", ".mov", ".mkv") else "libvpx"

    final = _set_audio(video, final_audio, ver)
    print(f"\nEncoding  (codec={codec}, threads={threads}) ...")

    final.write_videofile(
        output_path,
        codec=codec,
        audio_codec="aac",
        threads=threads,
        logger="bar",
    )

    for clip in (video, voice, final):
        try:
            clip.close()
        except Exception:
            pass

    mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"\nDone.  {output_path}  ({mb:.1f} MB)")


# ──────────────────────────────────────────────────────────
# ffmpeg engine
# ──────────────────────────────────────────────────────────

def run_ffmpeg(
    video_path: str,
    audio_path: str,
    output_path: str,
    mode: str,
    voice_vol: float,
    video_vol: float,
    fit: str,
) -> None:
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        print(
            "Error: ffmpeg binary not found on PATH.\n"
            "  Install ffmpeg: https://ffmpeg.org/download.html\n"
            "  Or use --engine moviepy instead."
        )
        sys.exit(1)

    print(f"Engine : ffmpeg  ({ffmpeg_bin})")

    # -shortest trims to the shorter stream; without it ffmpeg pads with silence
    shortest = ["-shortest"] if fit in ("trim_audio", "trim_video") else []

    if mode == "replace":
        # Copy video stream unchanged, replace audio with voiceover
        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",           # no video re-encode — instant + lossless
            "-map", "0:v:0",
            "-map", "1:a:0",
            *shortest,
            output_path,
        ]

    elif mode == "mix":
        # Mix original audio (quieter) + voiceover using amix filter
        fgraph = (
            f"[0:a]volume={video_vol}[orig];"
            f"[1:a]volume={voice_vol}[voice];"
            "[orig][voice]amix=inputs=2:duration=shortest[aout]"
        )
        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", fgraph,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

    else:
        raise ValueError(f"Unknown mode: {mode}")

    print("ffmpeg command:")
    print("  " + " ".join(cmd) + "\n")

    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"ffmpeg exited with code {proc.returncode}")
        sys.exit(proc.returncode)

    mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"\nDone.  {output_path}  ({mb:.1f} MB)")


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine voiceover audio with a video file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Replace video audio with voiceover (default)
  python combine_audio_video.py demo.mp4 VOICEOVER_SCRIPT.mp3

  # Custom output filename
  python combine_audio_video.py demo.mp4 VOICEOVER_SCRIPT.mp3 -o ccms_final.mp4

  # Mix voiceover over background video audio (video at 10% volume)
  python combine_audio_video.py demo.mp4 voice.mp3 --mode mix --video-vol 0.1

  # Trim video to match voiceover length
  python combine_audio_video.py demo.mp4 voice.mp3 --fit trim_video

  # Use ffmpeg engine (fastest, lossless video, requires ffmpeg on PATH)
  python combine_audio_video.py demo.mp4 voice.mp3 --engine ffmpeg

  # Full options example
  python combine_audio_video.py demo.mp4 voice.mp3 -o out.mp4 --mode mix --video-vol 0.08 --fit trim_audio --engine ffmpeg
        """,
    )

    parser.add_argument("video",
                        help="Input video file  (MP4, MOV, MKV, AVI ...)")
    parser.add_argument("audio",
                        help="Input voiceover audio file  (MP3, WAV, M4A ...)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output file path  (default: <video>_with_audio.<ext>)")
    parser.add_argument("--mode", "-m",
                        choices=["replace", "mix"], default="replace",
                        help="replace = swap audio entirely; mix = blend  (default: replace)")
    parser.add_argument("--voice-vol", type=float, default=1.0,
                        help="Voiceover volume multiplier  (default: 1.0)")
    parser.add_argument("--video-vol", type=float, default=0.15,
                        help="Original video audio volume when mixing  (default: 0.15)")
    parser.add_argument("--fit",
                        choices=["trim_audio", "trim_video", "loop_audio", "as_is"],
                        default="trim_audio",
                        help="Duration mismatch strategy  (default: trim_audio)")
    parser.add_argument("--engine",
                        choices=["moviepy", "ffmpeg"], default="moviepy",
                        help="Processing engine  (default: moviepy)")
    parser.add_argument("--threads", type=int, default=4,
                        help="Encoding threads for moviepy  (default: 4)")

    args = parser.parse_args()

    video_path = Path(args.video)
    audio_path = Path(args.audio)

    if not video_path.exists():
        print(f"Error: video file not found: {video_path}")
        sys.exit(1)
    if not audio_path.exists():
        print(f"Error: audio file not found: {audio_path}")
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        output_path = str(
            video_path.with_name(f"{video_path.stem}_with_audio{video_path.suffix}")
        )

    print(f"\nVideo  : {video_path}")
    print(f"Audio  : {audio_path}")
    print(f"Mode   : {args.mode}  |  Fit: {args.fit}  |  Engine: {args.engine}")
    print(f"Output : {output_path}\n")

    if args.engine == "ffmpeg":
        run_ffmpeg(
            str(video_path), str(audio_path), output_path,
            args.mode, args.voice_vol, args.video_vol, args.fit,
        )
    else:
        run_moviepy(
            str(video_path), str(audio_path), output_path,
            args.mode, args.voice_vol, args.video_vol, args.fit, args.threads,
        )


if __name__ == "__main__":
    main()
