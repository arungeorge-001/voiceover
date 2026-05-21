#!/usr/bin/env python3
"""
webm_to_mp4.py — Convert WebM file(s) to MP4

Uses the ffmpeg binary bundled with moviepy/imageio (no system ffmpeg needed).
Falls back to system ffmpeg if imageio_ffmpeg is not installed.

Usage:
    python webm_to_mp4.py input.webm
    python webm_to_mp4.py input.webm -o output.mp4
    python webm_to_mp4.py *.webm
    python webm_to_mp4.py --folder ./recordings
    python webm_to_mp4.py input.webm --quality high
"""

import argparse
import subprocess
import sys
from pathlib import Path


# ──────────────────────────────────────────────
# Locate ffmpeg binary
# ──────────────────────────────────────────────

def get_ffmpeg() -> str:
    """Return path to ffmpeg — bundled (imageio_ffmpeg) or system."""
    try:
        import imageio_ffmpeg  # bundled with moviepy
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    print(
        "Error: ffmpeg not found.\n"
        "  Option 1 (recommended): pip install moviepy  (bundles ffmpeg automatically)\n"
        "  Option 2: install ffmpeg from https://ffmpeg.org/download.html"
    )
    sys.exit(1)


# ──────────────────────────────────────────────
# Quality presets
# ──────────────────────────────────────────────

QUALITY_PRESETS = {
    #            crf   preset      audio_bitrate
    "high":     ("18", "slow",     "192k"),
    "medium":   ("23", "medium",   "128k"),   # default
    "fast":     ("28", "veryfast", "96k"),
}


# ──────────────────────────────────────────────
# Conversion
# ──────────────────────────────────────────────

def convert(
    input_path: Path,
    output_path: Path,
    quality: str,
    overwrite: bool,
) -> bool:
    """Convert a single WebM file to MP4. Returns True on success."""
    if output_path.exists() and not overwrite:
        print(f"  Skipping  {output_path.name}  (already exists — use --overwrite to replace)")
        return False

    crf, preset, audio_br = QUALITY_PRESETS[quality]

    cmd = [
        get_ffmpeg(),
        "-y" if overwrite else "-n",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",       # fix white-screen: VP8/VP9/alpha WebM → yuv420p
        "-crf", crf,
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", audio_br,
        "-movflags", "+faststart",
        str(output_path),
    ]

    print(f"  Converting  {input_path.name}  ->  {output_path.name}  [quality={quality}]")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR: ffmpeg failed for {input_path.name}")
        print(result.stderr[-800:])   # last 800 chars of stderr
        return False

    mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Done.  {mb:.1f} MB  ->  {output_path}")
    return True


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert WebM file(s) to MP4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quality presets:
  high    CRF 18, slow encode   — best quality,  largest file
  medium  CRF 23, medium        — balanced       (default)
  fast    CRF 28, veryfast      — smallest file, quickest

Examples:
  python webm_to_mp4.py recording.webm
  python webm_to_mp4.py recording.webm -o final.mp4
  python webm_to_mp4.py recording.webm --quality high
  python webm_to_mp4.py --folder D:/Recordings
  python webm_to_mp4.py --folder D:/Recordings --output-dir D:/MP4s --overwrite
        """,
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="One or more .webm files to convert",
    )
    parser.add_argument(
        "--folder", "-f",
        default=None,
        help="Convert all .webm files in this folder",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output MP4 path (single-file mode only)",
    )
    parser.add_argument(
        "--output-dir", "-d",
        default=None,
        help="Output directory for batch mode (default: same folder as input)",
    )
    parser.add_argument(
        "--quality", "-q",
        choices=["high", "medium", "fast"],
        default="medium",
        help="Encoding quality preset (default: medium)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )

    args = parser.parse_args()

    # ── Collect input files ──
    inputs: list[Path] = []

    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"Warning: file not found — {f}")
            continue
        inputs.append(p)

    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"Error: folder not found — {args.folder}")
            sys.exit(1)
        found = sorted(folder.glob("*.webm"))
        if not found:
            print(f"No .webm files found in {folder}")
            sys.exit(0)
        inputs.extend(found)

    if not inputs:
        parser.print_help()
        sys.exit(0)

    # ── Determine output paths ──
    out_dir = Path(args.output_dir) if args.output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[Path, Path]] = []

    for inp in inputs:
        if args.output and len(inputs) == 1:
            out = Path(args.output)
        elif out_dir:
            out = out_dir / inp.with_suffix(".mp4").name
        else:
            out = inp.with_suffix(".mp4")
        jobs.append((inp, out))

    # ── Run ──
    print(f"\nffmpeg  : {get_ffmpeg()}")
    print(f"Files   : {len(jobs)}")
    print(f"Quality : {args.quality}  (CRF {QUALITY_PRESETS[args.quality][0]})\n")

    ok = fail = skip = 0
    for inp, out in jobs:
        result = convert(inp, out, args.quality, args.overwrite)
        if result is True:
            ok += 1
        elif result is False and out.exists():
            skip += 1
        else:
            fail += 1

    print(f"\nFinished.  Converted: {ok}  |  Skipped: {skip}  |  Failed: {fail}")


if __name__ == "__main__":
    main()
