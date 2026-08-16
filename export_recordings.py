"""
Package recorded calls into a shareable deliverables/ folder.

    python export_recordings.py

Converts each call's WAV to a compact MP3 (about a tenth of the size, and
playable in any browser), copies the transcript alongside it, and writes an
index page listing every flow with its qualification outcome.

Unlike recordings/, the deliverables/ folder is committed to git, so a
reviewer can read the transcripts in the repo and download the audio.
"""
import os
import re
import shutil
import subprocess
import sys

import soundfile as sf

import config

OUTPUT_DIR = "deliverables"
MP3_BITRATE = "64k"  # plenty for speech; keeps a 3-minute call under 1.5MB
PROMPT_PDF = "WOW_Rohan_System_Prompt.pdf"  # written by make_prompt_pdf.py


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, check=True, timeout=15
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _parse_transcript(path: str) -> dict:
    """Pull the qualification outcomes and turn count out of a transcript."""
    if not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8").read()
    outcomes = dict(re.findall(r"^\s{2}(\w+)\s*:\s*(.+)$", text, re.MULTILINE))
    return {
        "outcomes": {
            k: v.strip()
            for k, v in outcomes.items()
            if k in ("intent", "geography", "budget", "timeline")
        },
        "turns": len(re.findall(r"^AGENT:", text, re.MULTILINE)),
    }


def main():
    if not os.path.isdir(config.RECORDINGS_DIR):
        print(f"No {config.RECORDINGS_DIR}/ folder yet. Make a call first.")
        sys.exit(1)

    if not _ffmpeg_available():
        print("ffmpeg not found. Install it, or share the .wav files directly.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    scenarios = sorted(
        name
        for name in os.listdir(config.RECORDINGS_DIR)
        if os.path.exists(os.path.join(config.RECORDINGS_DIR, name, "full_call.wav"))
    )

    if not scenarios:
        print("No completed calls found.")
        sys.exit(1)

    rows = []
    for scenario in scenarios:
        source_dir = os.path.join(config.RECORDINGS_DIR, scenario)
        wav_path = os.path.join(source_dir, "full_call.wav")
        mp3_path = os.path.join(OUTPUT_DIR, f"{scenario}.mp3")

        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
             "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, mp3_path],
            check=True,
        )

        transcript_source = os.path.join(source_dir, "transcript.txt")
        if os.path.exists(transcript_source):
            shutil.copy(transcript_source, os.path.join(OUTPUT_DIR, f"{scenario}.txt"))

        duration = sf.info(wav_path).duration
        details = _parse_transcript(transcript_source)
        size_mb = os.path.getsize(mp3_path) / 1e6

        rows.append((scenario, duration, size_mb, details))
        print(f"{scenario:<24} {duration:5.0f}s  ->  {mp3_path}  ({size_mb:.2f} MB)")

    index_path = os.path.join(OUTPUT_DIR, "README.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# Deliverables\n\n")
        f.write(
            "Live calls with the agent. Each MP3 is the full conversation, both "
            "sides; the matching `.txt` is the transcript with the four "
            "qualification checkpoints the agent established.\n\n"
        )
        if os.path.exists(os.path.join(OUTPUT_DIR, PROMPT_PDF)):
            f.write(
                f"The agent's full system prompt is in "
                f"[{PROMPT_PDF}]({PROMPT_PDF}), generated straight from the "
                f"running source.\n\n"
            )
        f.write("## Call flows\n\n")
        f.write("| Flow | Length | Turns | Audio | Transcript |\n")
        f.write("|---|---|---|---|---|\n")
        for scenario, duration, _size, details in rows:
            turns = details.get("turns", "-")
            f.write(
                f"| {scenario.replace('_', ' ')} | {duration:.0f}s | {turns} | "
                f"[{scenario}.mp3]({scenario}.mp3) | [{scenario}.txt]({scenario}.txt) |\n"
            )

        f.write("\n## Qualification outcomes\n\n")
        f.write("| Flow | Intent | Geography | Budget | Timeline |\n")
        f.write("|---|---|---|---|---|\n")
        for scenario, _d, _s, details in rows:
            outcomes = details.get("outcomes", {})
            cells = " | ".join(
                outcomes.get(k, "-") for k in ("intent", "geography", "budget", "timeline")
            )
            f.write(f"| {scenario.replace('_', ' ')} | {cells} |\n")

    print(f"\nWrote {index_path}")
    print(f"{len(rows)} call(s) packaged in {OUTPUT_DIR}/")
    if len(rows) < 5:
        print(f"NOTE: the assignment asks for at least 5 flows; you have {len(rows)}.")


if __name__ == "__main__":
    main()
