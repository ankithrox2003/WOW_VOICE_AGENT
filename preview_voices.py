"""
Audition every available voice and pick the one Rohan should use.

    python preview_voices.py              # play each voice out loud
    python preview_voices.py --save-only  # just write the wav files
    python preview_voices.py --voice prabhat

Each sample is also written to voice_samples/ so you can re-listen without
re-synthesizing. Once you've chosen, set TTS_VOICE in config.py.
"""
import argparse
import os

import soundfile as sf

import config
import voices
from tts_engine import play_audio, synthesize

OUTPUT_DIR = "voice_samples"


def main():
    parser = argparse.ArgumentParser(description="Listen to the available agent voices")
    parser.add_argument("--voice", help="Preview one voice instead of all of them")
    parser.add_argument(
        "--save-only", action="store_true", help="Write wav files without playing them"
    )
    parser.add_argument("--text", default=voices.SAMPLE_LINE, help="Custom line to speak")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if args.voice:
        names = [args.voice]
    else:
        # ElevenLabs voices live on your account, not in this catalogue, and
        # would silently render through the fallback voice here.
        names = [n for n in voices.VOICES if voices.VOICES[n]["backend"] != "elevenlabs"]
        print("\nFor ElevenLabs voices, run: python list_voices.py --preview")

    print(f"\nSpeaking: \"{args.text}\"\n")
    print(f"{'KEY':<18} {'BACKEND':<8} DESCRIPTION")
    print("-" * 78)

    for name in names:
        spec = voices.resolve(name)
        note = f"  <-- {spec['note']}" if spec.get("note") else ""
        print(f"{name:<18} {spec['backend']:<8} {spec['label']}{note}")

        try:
            audio = synthesize(args.text, voice=name)
        except Exception as exc:
            print(f"{'':<18} failed: {exc}")
            continue

        if audio.size == 0:
            print(f"{'':<18} produced no audio")
            continue

        sf.write(os.path.join(OUTPUT_DIR, f"{name}.wav"), audio, config.TTS_SAMPLE_RATE)
        if not args.save_only:
            play_audio(audio)

    print(f"\nSamples saved in {OUTPUT_DIR}/")
    print(f"Current voice is '{config.TTS_VOICE}'. To change it, edit TTS_VOICE in config.py.")


if __name__ == "__main__":
    main()
