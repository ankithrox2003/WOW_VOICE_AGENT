"""
Preflight check. Run this before a call to confirm every piece is ready.

    python check_setup.py

Verifies the .env file, the ElevenLabs key and voice, the Ollama server and
model, the speech-to-text model, and your audio devices. Never prints your
API key.
"""
import os
import sys

OK = "  OK  "
FAIL = " FAIL "
WARN = " WARN "

results = []


def report(status, label, detail=""):
    results.append(status)
    print(f"[{status}] {label}" + (f"  -  {detail}" if detail else ""))


def check_env_files():
    print("\n--- Configuration ---")
    if not os.path.exists(".env"):
        extra = ""
        if os.path.exists(".env.example"):
            extra = "You have .env.example, but the key must go in a file named exactly '.env'"
        report(FAIL, ".env file", extra or "Copy .env.example to .env")
        return

    from dotenv import load_dotenv

    load_dotenv(override=True)

    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()

    report(OK, ".env file", "found")
    if key:
        report(OK, "ELEVENLABS_API_KEY", f"set, {len(key)} characters")
    else:
        report(FAIL, "ELEVENLABS_API_KEY", "empty in .env")
    if voice_id:
        report(OK, "ELEVENLABS_VOICE_ID", voice_id)
    else:
        report(FAIL, "ELEVENLABS_VOICE_ID", "empty in .env")


def check_elevenlabs():
    print("\n--- ElevenLabs ---")
    try:
        import elevenlabs_client
    except Exception as exc:
        report(FAIL, "elevenlabs client", str(exc))
        return

    try:
        quota = elevenlabs_client.get_quota()
        report(
            OK,
            "API key accepted",
            f"{quota['tier']} plan, {quota['remaining']:,} of {quota['limit']:,} credits left",
        )
        calls_left = int(quota["remaining"] / 600)
        if calls_left < 3:
            report(WARN, "Credits", f"only about {calls_left} calls left")
        else:
            report(OK, "Credits", f"roughly {calls_left} more demo calls")
    except Exception as exc:
        report(FAIL, "API key", str(exc))
        return

    try:
        voice_id = elevenlabs_client.get_voice_id()
        names = {v["voice_id"]: v["name"] for v in elevenlabs_client.list_voices()}
        if voice_id in names:
            report(OK, "Voice ID", f"'{names[voice_id]}'")
        else:
            report(
                WARN,
                "Voice ID",
                "not in your account's voice list; add it from the Voice Library",
            )
    except Exception as exc:
        report(FAIL, "Voice ID", str(exc))
        return

    try:
        audio = elevenlabs_client.synthesize("Testing one two three.")
        report(OK, "Speech synthesis", f"{audio.size:,} samples returned")
    except Exception as exc:
        report(FAIL, "Speech synthesis", str(exc))


def check_ollama():
    print("\n--- Ollama ---")
    import config

    try:
        import ollama

        models = [m.get("model", "") for m in ollama.list().get("models", [])]
    except Exception as exc:
        report(FAIL, "Ollama server", f"{exc}  -  is the Ollama app running?")
        return

    report(OK, "Ollama server", "reachable")
    if config.LLM_MODEL in models:
        report(OK, f"Model {config.LLM_MODEL}", "installed")
    else:
        report(
            FAIL,
            f"Model {config.LLM_MODEL}",
            f"not found. Run: ollama pull {config.LLM_MODEL}",
        )
        return

    try:
        import time

        started = time.time()
        ollama.chat(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": "Say OK."}],
            options={"num_ctx": config.LLM_NUM_CTX, "num_predict": 8},
        )
        elapsed = time.time() - started
        note = "first call includes loading the model into VRAM" if elapsed > 8 else ""
        report(OK, "Model responds", f"{elapsed:.1f}s  {note}".strip())
    except Exception as exc:
        report(FAIL, "Model responds", str(exc))


def check_audio():
    print("\n--- Audio ---")
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        input_index, output_index = sd.default.device
        report(OK, "Microphone", devices[input_index]["name"])
        report(OK, "Speaker", devices[output_index]["name"])
        report(
            WARN,
            "Echo",
            "use headphones, or the mic will hear the agent and transcribe it",
        )
    except Exception as exc:
        report(FAIL, "Audio devices", str(exc))


def check_stt():
    print("\n--- Speech to text ---")
    try:
        from stt_engine import get_model

        get_model()
        report(OK, "Whisper model", "loaded")
    except Exception as exc:
        report(FAIL, "Whisper model", str(exc))


def main():
    print("=" * 72)
    print("  WOW VOICE AGENT - PREFLIGHT CHECK")
    print("=" * 72)

    check_env_files()
    check_elevenlabs()
    check_ollama()
    check_stt()
    check_audio()

    failures = results.count(FAIL)
    print("\n" + "=" * 72)
    if failures:
        print(f"  {failures} problem(s) found. Fix the FAIL lines above, then re-run.")
        print("=" * 72)
        sys.exit(1)
    print("  All good. Start a call with:  python voice_agent.py")
    print("=" * 72)


if __name__ == "__main__":
    main()
