"""
Show the ElevenLabs voices available on your account, plus how many
credits you have left.

    python list_voices.py                 # list voices and quota
    python list_voices.py --preview       # also speak a sample in each one
    python list_voices.py --preview VOICE_ID

Copy the voice ID you want into ELEVENLABS_VOICE_ID in your .env file.
Your API key is only read from .env; it is never printed.
"""
import argparse
import os

import soundfile as sf

import config
import elevenlabs_client
import voices
from tts_engine import play_audio

SAMPLE_DIR = "voice_samples"


# ElevenLabs blocks Voice Library voices (category "professional") over the
# API on the free tier, returning 402. Voices you own -- the built-in
# "premade" set, plus anything you cloned or generated yourself -- work on
# every plan. Flagging this here beats discovering it mid-call.
_FREE_TIER_CATEGORIES = {"premade", "cloned", "generated"}


def _usable(voice: dict) -> bool:
    return voice.get("category") in _FREE_TIER_CATEGORIES


def _describe(voice: dict) -> str:
    labels = voice.get("labels") or {}
    wanted = ("accent", "gender", "age", "use_case")
    parts = [str(labels[k]) for k in wanted if labels.get(k)]
    return ", ".join(parts) if parts else voice.get("category", "")


def main():
    parser = argparse.ArgumentParser(description="Browse your ElevenLabs voices")
    parser.add_argument(
        "--preview",
        nargs="?",
        const="ALL",
        help="Speak a sample. Optionally pass a single voice ID.",
    )
    args = parser.parse_args()

    try:
        quota = elevenlabs_client.get_quota()
        print(f"\nPlan: {quota['tier']}")
        print(
            f"Credits: {quota['remaining']:,} of {quota['limit']:,} remaining "
            f"({quota['used']:,} used)"
        )
        # flash_v2_5 bills 0.5 credits per character; a 2-3 minute call is
        # roughly 1,200 characters of agent speech.
        print(f"That's roughly {int(quota['remaining'] / 600)} more demo calls at this rate.\n")

        voice_list = elevenlabs_client.list_voices()
    except elevenlabs_client.ElevenLabsError as exc:
        print(f"\n{exc}\n")
        return
    except Exception as exc:
        print(f"\nCouldn't reach ElevenLabs: {exc}\n")
        return

    is_free = quota["tier"] == "free"
    usable = [v for v in voice_list if _usable(v)]
    blocked = [v for v in voice_list if not _usable(v)]

    print(f"{'VOICE ID':<24} {'NAME':<22} DESCRIPTION")
    print("-" * 90)
    for voice in usable:
        print(f"{voice['voice_id']:<24} {voice['name'][:21]:<22} {_describe(voice)[:44]}")

    if blocked:
        header = (
            "BLOCKED on the free tier - Voice Library voices need a paid plan "
            "to use over the API"
            if is_free
            else "Voice Library voices"
        )
        print(f"\n{header}:")
        print("-" * 90)
        for voice in blocked:
            print(f"{voice['voice_id']:<24} {voice['name'][:21]:<22} {_describe(voice)[:44]}")

    current = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    current_voice = next((v for v in voice_list if v["voice_id"] == current), None)
    print(f"\nCurrently selected in .env: {current or '(none yet)'}")
    if current_voice and not _usable(current_voice) and is_free:
        print(
            f"  WARNING: '{current_voice['name']}' is a Voice Library voice and will "
            "fail with a 402 on your plan.\n  Pick one from the first list instead."
        )
    print("Paste the voice ID you want into ELEVENLABS_VOICE_ID in .env")

    if not args.preview:
        return

    targets = (
        usable  # previewing blocked voices just burns time on 402s
        if args.preview == "ALL"
        else [v for v in voice_list if v["voice_id"] == args.preview]
    )
    if not targets:
        print(f"\nNo voice found with ID {args.preview}")
        return

    os.makedirs(SAMPLE_DIR, exist_ok=True)
    print(f"\nSpeaking a sample in {len(targets)} voice(s)...\n")
    for voice in targets:
        print(f"  {voice['name']} ({voice['voice_id']})")
        try:
            audio = elevenlabs_client.synthesize(voices.SAMPLE_LINE, voice_id=voice["voice_id"])
        except Exception as exc:
            print(f"    failed: {exc}")
            continue
        safe_name = "".join(c if c.isalnum() else "_" for c in voice["name"])
        sf.write(os.path.join(SAMPLE_DIR, f"eleven_{safe_name}.wav"), audio, config.TTS_SAMPLE_RATE)
        play_audio(audio)

    print(f"\nSamples saved to {SAMPLE_DIR}/")


if __name__ == "__main__":
    main()
