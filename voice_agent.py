"""
WOW Lead Qualifier - a live outbound voice agent you talk to directly.

Run it, and Rohan places the call. He speaks first, you reply into your
microphone, and he responds. There is no second synthetic voice: the only
voices on the call are Rohan's and yours.

    python voice_agent.py                        # start a call
    python voice_agent.py --scenario budget_test # name the recording folder
    python voice_agent.py --voice ryan           # override the agent's voice
    python voice_agent.py --list-devices         # check your mic/speakers

Pipeline per turn:
    your mic -> WebRTC VAD (detects when you stop) -> faster-whisper (STT)
             -> Ollama (LLM, streamed sentence by sentence)
             -> neural TTS -> speaker

Every call is saved to recordings/<scenario>/ as full_call.wav plus a
transcript.
"""
import argparse
import re
import sys
import time

import config
from audio_io import load_wav_mono, record_until_silence
from call_recorder import CallRecorder
from llm_engine import Conversation
from qualification import QualificationTracker
from stt_engine import transcribe
from tts_engine import SpeechPlayer, play_audio, synthesize

GREETING = (
    "Good morning! This is Rohan calling from DivyaSree Developers. "
    "I'm reaching out about Whispers of the Wind, our new villa plot project "
    "in Nandi Valley, near Nandi Hills. Do you have two minutes to talk?"
)

# The model is told to emit "[END_CALL]", but small models paraphrase
# control tokens, so accept the common variants rather than running past
# the end of the call.
_END_CALL_RE = re.compile(r"\[?\s*END[_\s-]?CALL\s*\]?", re.IGNORECASE)

# Models occasionally emit a fill-in-later placeholder, e.g. "our expert,
# [no name mentioned]". The TTS normalizer already drops bracketed text so
# it's never spoken, but it would otherwise survive into the transcript.
_PLACEHOLDER_RE = re.compile(r"\s*[\[\{][^\]\}]*[\]\}]\s*")


def _strip_end_tag(text: str) -> str:
    text = _END_CALL_RE.sub("", text)
    text = _PLACEHOLDER_RE.sub(" ", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _speak(text: str, voice: str):
    """Speak one complete line and return its audio."""
    audio = synthesize(text, voice=voice)
    play_audio(audio)
    return audio


def run_call(scenario: str, voice: str) -> dict:
    recorder = CallRecorder(scenario)
    agent = Conversation()
    tracker = QualificationTracker()
    turn_latencies = []
    active_voice = voice

    print("\n" + "=" * 70)
    print(f"  OUTBOUND CALL  |  voice: {active_voice}  |  saving to: {recorder.dir}")
    print("=" * 70)
    print("  Rohan speaks first. Reply out loud; he'll respond when you pause.")
    print("  Press Ctrl+C to hang up early.\n")

    # --- Warm the models up before the caller hears anything, so the very
    # --- first turn isn't slowed down by lazy loading.
    print("[INIT] Warming up speech recognition...")
    from stt_engine import get_model

    get_model()

    print(f"\n[AGENT] {GREETING}")
    recorder.add_agent(GREETING, _speak(GREETING, active_voice))
    agent.add_assistant(GREETING)

    silent_turns = 0
    pending_checkpoint = None

    for turn in range(1, config.MAX_TURNS + 1):
        # --- Your turn on the microphone ---
        wav_path = recorder.path_for(f"turn_{turn:02d}_you.wav")
        got_speech = record_until_silence(wav_path)

        caller_text, language = ("", "en")
        if got_speech:
            print("[...] transcribing")
            caller_text, language = transcribe(wav_path)

        if not caller_text:
            silent_turns += 1
            if silent_turns >= 2:
                print("[CALL] No response. Closing the call.")
                break
            nudge = "Hello? Can you still hear me?"
            print(f"[AGENT] {nudge}")
            recorder.add_agent(nudge, _speak(nudge, active_voice))
            agent.add_assistant(nudge)
            continue

        silent_turns = 0
        print(f"[YOU  ] ({language}) {caller_text}")

        # Multilingual bonus: match the caller's language in the reply voice.
        if config.TTS_HINDI_VOICE and language == "hi" and active_voice != config.TTS_HINDI_VOICE:
            active_voice = config.TTS_HINDI_VOICE
            print(f"[LANG ] Caller switched to Hindi; agent voice -> {active_voice}")

        caller_audio, caller_rate = load_wav_mono(wav_path)
        recorder.add_caller(caller_text, caller_audio, caller_rate)
        agent.add_user(caller_text)
        # `pending_checkpoint` is what the agent asked last turn, so a bare
        # "yes" gets attributed to the right question.
        tracker.update(caller_text, pending=pending_checkpoint)

        # --- Rohan's turn, streamed and spoken sentence by sentence ---
        open_before_reply = tracker.open_checkpoints
        started = time.time()
        player = SpeechPlayer(voice=active_voice)

        collected = []
        first_audio_latency = None
        for sentence in agent.stream_reply(context_note=tracker.briefing()):
            collected.append(sentence)
            clean = _strip_end_tag(sentence)
            if clean:
                if first_audio_latency is None:
                    first_audio_latency = time.time() - started
                player.say(clean)

        agent_audio = player.finish()
        pending_checkpoint = open_before_reply[0] if open_before_reply else None

        full_reply = " ".join(collected).strip()
        spoken_text = _strip_end_tag(full_reply)
        print(f"[AGENT] {spoken_text}")
        if first_audio_latency is not None:
            turn_latencies.append(first_audio_latency)
            print(f"        ({first_audio_latency:.1f}s to first audio)")

        recorder.add_agent(spoken_text, agent_audio)

        if _END_CALL_RE.search(full_reply):
            print("\n[CALL] Rohan ended the call.")
            break
    else:
        print(f"\n[CALL] Reached the {config.MAX_TURNS}-turn safety cap.")

    recorder.set_qualification(tracker.state)
    result = recorder.save()

    print("\n" + "-" * 70)
    print("QUALIFICATION SUMMARY")
    for checkpoint, value in tracker.state.items():
        print(f"  {checkpoint:<10}: {value or 'not established'}")
    print("-" * 70)
    print(f"[SAVED] {result['audio']}")
    print(f"[SAVED] {result['transcript']}")
    print(f"[TIME ] {result['duration']:.0f}s of audio")
    if turn_latencies:
        print(f"[LAT  ] {sum(turn_latencies) / len(turn_latencies):.1f}s average to first audio")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="WOW outbound lead-qualification voice agent (live microphone)"
    )
    parser.add_argument(
        "--scenario",
        default="call",
        help="Folder name under recordings/ for this call",
    )
    parser.add_argument(
        "--voice",
        default=config.TTS_VOICE,
        help="Agent voice key; run preview_voices.py to hear the options",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="Show audio devices and exit"
    )
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        print(f"\nDefault (input, output): {sd.default.device}")
        return

    try:
        run_call(args.scenario, args.voice)
    except KeyboardInterrupt:
        print("\n[CALL] Hung up.")
        sys.exit(0)


if __name__ == "__main__":
    main()
