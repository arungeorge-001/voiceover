#!/usr/bin/env python3
"""
voiceover_to_mp3.py — Convert CCMS Bank Portal voiceover script to MP3

Usage:
    python voiceover_to_mp3.py [INPUT_FILE] [OPTIONS]

Requirements:
    pip install edge-tts

Recommended male voices (run --list-voices for full list):
    en-US-GuyNeural           — authoritative, clear  (default)
    en-US-ChristopherNeural   — deep, confident
    en-US-EricNeural          — warm, professional
    en-US-AndrewNeural        — natural, conversational
    en-GB-RyanNeural          — British male, formal

Note: Edge TTS does not have an "Adam" voice. GuyNeural is the closest
      equivalent in tone for a professional banking demo.
"""

import re
import asyncio
import argparse
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("Error: edge-tts not installed.\nRun: pip install edge-tts")
    raise SystemExit(1)


# ─────────────────────────────────────────────
# Script parser
# ─────────────────────────────────────────────

def parse_voiceover_script(file_path: str) -> str:
    """
    Extract only the spoken voiceover text from the markdown script.

    Strategy:
    - Split the file on horizontal rules (---) — each section lives between two.
    - Within each section, collect blockquote lines (starting with >).
    - A blockquote block is speech if its first meaningful line starts with "
      (recording notes/tips never start with a quote).
    - Strip markdown bold/italic, [PAUSE] markers, and em dashes.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    chunks = re.split(r"\n---\n", content)

    speech_segments: list[str] = []

    for chunk in chunks:
        # Collect all blockquote line content for this chunk
        bq_lines = []
        for line in chunk.split("\n"):
            stripped = line.strip()
            if stripped.startswith(">"):
                text = stripped[1:].strip()
                bq_lines.append(text)

        if not bq_lines:
            continue

        # Join non-empty blockquote lines
        joined = " ".join(t for t in bq_lines if t)

        # Speech blocks open with a quotation mark; skip recording notes/tips
        if not joined.startswith('"'):
            continue

        # Strip the enclosing opening and closing quotes
        speech = joined
        if speech.startswith('"'):
            speech = speech[1:]
        if speech.endswith('"'):
            speech = speech[:-1]

        speech = speech.strip()
        if speech:
            speech_segments.append(speech)

    full_text = " ".join(speech_segments)

    # Remove markdown bold (**text**) and italic (*text*) markers
    full_text = re.sub(r"\*\*(.+?)\*\*", r"\1", full_text)
    full_text = re.sub(r"\*(.+?)\*",     r"\1", full_text)

    # [PAUSE] → ellipsis for a natural TTS breath
    full_text = re.sub(r"\[PAUSE\]", "...", full_text)

    # Em dash → comma+space (TTS reads "—" inconsistently)
    full_text = full_text.replace(" — ", ", ")

    # Collapse stray double-spaces
    full_text = re.sub(r" {2,}", " ", full_text)

    return full_text.strip()


# ─────────────────────────────────────────────
# Audio conversion
# ─────────────────────────────────────────────

async def convert_to_mp3(
    text: str,
    output_path: str,
    voice: str,
    rate: str,
    volume: str,
    pitch: str,
) -> None:
    """Stream Edge TTS synthesis and write the result as an MP3 file."""
    print(f"\nVoice   : {voice}")
    print(f"Rate    : {rate}   Volume: {volume}   Pitch: {pitch}")
    print(f"Words   : {len(text.split())}")
    print(f"Output  : {output_path}")
    print("\nRendering audio - this usually takes 20-60 seconds...\n")

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
    await communicate.save(output_path)

    size_kb = Path(output_path).stat().st_size // 1024
    print(f"Done.  Saved {size_kb} KB -> {output_path}")


async def list_male_voices() -> None:
    """Print all available English male Edge TTS voices."""
    voices = await edge_tts.list_voices()
    male_en = sorted(
        [v for v in voices if v["Gender"] == "Male" and v["Locale"].startswith("en-")],
        key=lambda v: v["ShortName"],
    )
    print(f"\n{'Voice Name':<42} {'Locale':<12} Friendly Name")
    print("-" * 90)
    for v in male_en:
        print(f"{v['ShortName']:<42} {v['Locale']:<12} {v['FriendlyName']}")
    print(f"\n{len(male_en)} English male voices available.")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert voiceover markdown script to MP3 using Microsoft Edge TTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python voiceover_to_mp3.py
  python voiceover_to_mp3.py VOICEOVER_SCRIPT.md -o ccms_demo.mp3
  python voiceover_to_mp3.py --voice en-US-ChristopherNeural --rate -15%
  python voiceover_to_mp3.py --list-voices
  python voiceover_to_mp3.py --preview
        """,
    )

    parser.add_argument(
        "input",
        nargs="?",
        default="VOICEOVER_SCRIPT.md",
        help="Input .md script file (default: VOICEOVER_SCRIPT.md)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output MP3 path (default: same name as input with .mp3 extension)",
    )
    parser.add_argument(
        "--voice", "-v",
        default="en-US-AndrewNeural",
        help="Edge TTS voice name (default: en-US-AndrewNeural)",
    )
    parser.add_argument(
        "--rate", "-r",
        default="-10%",
        help="Speech rate: -50%% to +100%% (default: -10%% = slightly slower for gravitas)",
    )
    parser.add_argument(
        "--volume",
        default="+0%",
        help="Volume adjustment: -100%% to +100%% (default: +0%%)",
    )
    parser.add_argument(
        "--pitch", "-p",
        default="-5Hz",
        help="Pitch: -100Hz to +100Hz (default: -5Hz = marginally deeper tone)",
    )
    parser.add_argument(
        "--list-voices", "-l",
        action="store_true",
        help="List all available English male Edge TTS voices and exit",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the extracted spoken text without converting to audio",
    )

    args = parser.parse_args()

    if args.list_voices:
        asyncio.run(list_male_voices())
        return

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: '{input_path}' not found.")
        raise SystemExit(1)

    output_path = str(args.output or input_path.with_suffix(".mp3"))

    print(f"Parsing : {input_path}")
    text = parse_voiceover_script(str(input_path))

    if args.preview:
        print("\n" + "-" * 70)
        print(text)
        print("-" * 70)
        print(f"\nWords : {len(text.split())}")
        print(f"Chars : {len(text)}")
        return

    asyncio.run(convert_to_mp3(
        text=text,
        output_path=output_path,
        voice=args.voice,
        rate=args.rate,
        volume=args.volume,
        pitch=args.pitch,
    ))


if __name__ == "__main__":
    main()
