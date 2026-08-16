"""
Text-to-speech with two interchangeable backends (see voices.py):

  edge   - Microsoft neural voices. Natural, free, no API key, needs internet.
  kokoro - Local 82M model. Fully offline, more synthetic.

Also provides SpeechPlayer, which speaks sentences as they arrive from the
LLM instead of waiting for the whole reply. That overlap is what keeps the
agent from going silent for several seconds before every response.
"""
import asyncio
import io
import queue
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf

import config
import voices
from text_normalizer import normalize_for_speech

_kokoro_pipeline = None


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------
def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        print("[TTS] Loading local Kokoro model (first run downloads weights)...")
        from kokoro import KPipeline

        _kokoro_pipeline = KPipeline(lang_code=config.TTS_LANG_CODE)
    return _kokoro_pipeline


def _synth_kokoro(text: str, voice_id: str) -> np.ndarray:
    pipeline = _get_kokoro()
    chunks = [
        np.asarray(audio, dtype=np.float32)
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice_id)
    ]
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


async def _edge_stream(text: str, voice_id: str) -> io.BytesIO:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice_id)
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    buffer.seek(0)
    return buffer


def _synth_edge(text: str, voice_id: str) -> np.ndarray:
    buffer = asyncio.run(_edge_stream(text, voice_id))
    if buffer.getbuffer().nbytes == 0:
        return np.zeros(0, dtype=np.float32)

    audio, sample_rate = sf.read(buffer, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != config.TTS_SAMPLE_RATE:
        from scipy.signal import resample_poly

        gcd = np.gcd(sample_rate, config.TTS_SAMPLE_RATE)
        audio = resample_poly(
            audio, config.TTS_SAMPLE_RATE // gcd, sample_rate // gcd
        ).astype(np.float32)
    return audio


def _synth_elevenlabs(text: str, voice_id: str) -> np.ndarray:
    import elevenlabs_client

    return elevenlabs_client.synthesize(text, voice_id=voice_id)


_BACKENDS = {
    "elevenlabs": _synth_elevenlabs,
    "edge": _synth_edge,
    "kokoro": _synth_kokoro,
}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
# Once a voice has failed, stop retrying it for the rest of the process:
# re-attempting a dead API on every sentence would add seconds of dead air
# to every single turn.
_dead_voices = set()


def synthesize(text: str, voice: str = None) -> np.ndarray:
    """
    Normalize `text`, speak it in the named voice, return float32 samples
    at config.TTS_SAMPLE_RATE.

    If the chosen voice fails mid-call (no internet, exhausted quota, bad
    key) this walks down TTS_FALLBACK_CHAIN rather than dropping the call.
    """
    spoken = normalize_for_speech(text)
    if not spoken.strip():
        return np.zeros(0, dtype=np.float32)

    primary = voice or config.TTS_VOICE
    candidates = [primary] + [v for v in config.TTS_FALLBACK_CHAIN if v != primary]

    last_error = None
    for name in candidates:
        if name in _dead_voices:
            continue
        spec = voices.resolve(name)
        try:
            return _BACKENDS[spec["backend"]](spoken, spec["id"])
        except Exception as exc:
            last_error = exc
            _dead_voices.add(name)
            print(f"\n[TTS] '{name}' unavailable: {exc}")
            remaining = [c for c in candidates if c not in _dead_voices]
            if remaining:
                print(f"[TTS] Switching to '{remaining[0]}' for the rest of the call.\n")

    raise RuntimeError(f"Every configured voice failed. Last error: {last_error}")


def speak_to_file(text: str, out_path: str, voice: str = None) -> str:
    sf.write(out_path, synthesize(text, voice=voice), config.TTS_SAMPLE_RATE)
    return out_path


def play_audio(audio: np.ndarray):
    if audio.size == 0:
        return
    sd.play(audio, config.TTS_SAMPLE_RATE)
    sd.wait()


class SpeechPlayer:
    """
    Synthesizes and plays sentences in the background while the LLM is
    still generating the rest of the reply.

    Two threads: one turns queued text into audio, one plays it in order.
    Keeping them separate means sentence N+1 is being synthesized while
    sentence N is still being spoken.
    """

    def __init__(self, voice: str = None):
        self.voice = voice or config.TTS_VOICE
        self._text_queue = queue.Queue()
        self._audio_queue = queue.Queue()
        self._collected = []
        self._synth_thread = threading.Thread(target=self._synth_loop, daemon=True)
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def _synth_loop(self):
        while True:
            text = self._text_queue.get()
            if text is None:
                self._audio_queue.put(None)
                self._text_queue.task_done()
                return
            try:
                audio = synthesize(text, voice=self.voice)
                if audio.size:
                    self._collected.append(audio)
                    self._audio_queue.put(audio)
            except Exception as exc:  # one bad chunk shouldn't drop the call
                print(f"[TTS] Skipped a chunk: {exc}")
            finally:
                self._text_queue.task_done()

    def _play_loop(self):
        while True:
            audio = self._audio_queue.get()
            if audio is None:
                self._audio_queue.task_done()
                return
            try:
                play_audio(audio)
            except Exception as exc:
                print(f"[TTS] Playback problem: {exc}")
            finally:
                self._audio_queue.task_done()

    def say(self, text: str):
        if text and text.strip():
            self._text_queue.put(text)

    def finish(self) -> np.ndarray:
        """Block until everything queued has been spoken; return the audio."""
        self._text_queue.put(None)
        self._synth_thread.join()
        self._play_thread.join()
        return (
            np.concatenate(self._collected)
            if self._collected
            else np.zeros(0, dtype=np.float32)
        )
