"""
Microphone capture with automatic silence-based turn-taking, so the
caller never has to press a key to hand the turn back.

Uses WebRTC's voice activity detector to find the start of speech and the
sustained pause that ends it.
"""
import collections
import wave

import numpy as np
import sounddevice as sd

import config

# The original `webrtcvad` package needs a C compiler on Windows;
# `webrtcvad-wheels` is the same code shipped as a prebuilt wheel.
try:
    import webrtcvad
except ImportError:  # pragma: no cover
    import webrtcvad_wheels as webrtcvad

FRAME_SAMPLES = int(config.MIC_SAMPLE_RATE * config.FRAME_MS / 1000)
_SILENCE_FRAMES = max(1, int(config.SILENCE_TIMEOUT_MS / config.FRAME_MS))


def _write_wav(path: str, frames: list):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(config.MIC_SAMPLE_RATE)
        wf.writeframes(b"".join(frames))


def record_until_silence(out_path: str) -> bool:
    """
    Record from the microphone until the caller stops talking.

    Returns True if speech was captured, False if the caller stayed silent
    for INITIAL_WAIT_SECONDS (which the call loop treats as dead air).
    """
    vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
    ring_buffer = collections.deque(maxlen=_SILENCE_FRAMES)
    recorded_frames = []
    triggered = False

    print("[MIC] Listening... (just talk; it stops when you pause)")

    max_frames = int(config.MAX_TURN_SECONDS * 1000 / config.FRAME_MS)
    max_wait_frames = int(config.INITIAL_WAIT_SECONDS * 1000 / config.FRAME_MS)

    stream = sd.InputStream(
        samplerate=config.MIC_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME_SAMPLES,
    )
    with stream:
        for frame_index in range(max_frames):
            frame, _overflowed = stream.read(FRAME_SAMPLES)
            frame_bytes = frame.tobytes()
            is_speech = vad.is_speech(frame_bytes, config.MIC_SAMPLE_RATE)

            if not triggered:
                ring_buffer.append((frame_bytes, is_speech))
                voiced = sum(1 for _f, s in ring_buffer if s)
                if voiced > 0.6 * ring_buffer.maxlen:
                    triggered = True
                    # Keep the buffered frames so the first word isn't clipped.
                    recorded_frames.extend(f for f, _s in ring_buffer)
                    ring_buffer.clear()
                elif frame_index >= max_wait_frames:
                    _write_wav(out_path, [])
                    return False
            else:
                recorded_frames.append(frame_bytes)
                ring_buffer.append((frame_bytes, is_speech))
                unvoiced = sum(1 for _f, s in ring_buffer if not s)
                if unvoiced == ring_buffer.maxlen:
                    break  # sustained silence: the caller's turn is over

    _write_wav(out_path, recorded_frames)
    return bool(recorded_frames)


def load_wav_mono(path: str):
    """Read a wav file as float32 samples plus its sample rate."""
    import soundfile as sf

    data, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), sample_rate


def play_wav(path: str):
    """Play a wav file through the default speaker."""
    data, sample_rate = load_wav_mono(path)
    sd.play(data, sample_rate)
    sd.wait()
