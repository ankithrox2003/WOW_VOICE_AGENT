"""
Assembles the deliverable artifacts for a call: a single stitched audio
file of the whole conversation plus a readable transcript.

The two audio sources run at different sample rates (the microphone at
16kHz, Kokoro at 24kHz), so every segment is resampled to one rate before
being concatenated. Writing them into a single wav without this makes
whichever half doesn't match the header play at the wrong speed.
"""
import datetime
import os

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

import config

OUTPUT_SAMPLE_RATE = config.TTS_SAMPLE_RATE
_GAP_SECONDS = 0.35  # breathing room between turns


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate or audio.size == 0:
        return audio
    gcd = np.gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // gcd, from_rate // gcd).astype(np.float32)


class CallRecorder:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.dir = os.path.join(config.RECORDINGS_DIR, scenario)
        os.makedirs(self.dir, exist_ok=True)
        self.segments = []
        self.transcript = []
        self.qualification = None
        self._gap = np.zeros(int(OUTPUT_SAMPLE_RATE * _GAP_SECONDS), dtype=np.float32)

    def set_qualification(self, state: dict):
        """Record the four checkpoint outcomes: this call's actual business result."""
        self.qualification = state

    def add_agent(self, text: str, audio: np.ndarray):
        self.transcript.append(("AGENT", text))
        if audio is not None and audio.size:
            self.segments.append(_resample(audio, config.TTS_SAMPLE_RATE, OUTPUT_SAMPLE_RATE))
            self.segments.append(self._gap)

    def add_caller(self, text: str, audio: np.ndarray = None, sample_rate: int = None):
        self.transcript.append(("CALLER", text))
        if audio is not None and audio.size:
            self.segments.append(_resample(audio, sample_rate, OUTPUT_SAMPLE_RATE))
            self.segments.append(self._gap)

    def path_for(self, filename: str) -> str:
        return os.path.join(self.dir, filename)

    def save(self) -> dict:
        audio_path = os.path.join(self.dir, "full_call.wav")
        if self.segments:
            full = np.concatenate(self.segments)
            # Guard against clipping when segments come from different sources.
            peak = float(np.max(np.abs(full))) if full.size else 0.0
            if peak > 1.0:
                full = full / peak
            sf.write(audio_path, full, OUTPUT_SAMPLE_RATE)

        transcript_path = os.path.join(self.dir, "transcript.txt")
        duration = (
            sum(s.size for s in self.segments) / OUTPUT_SAMPLE_RATE
            if self.segments
            else 0.0
        )
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(f"Scenario   : {self.scenario}\n")
            f.write(f"Recorded   : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Duration   : {duration:.0f}s\n")
            f.write(f"LLM        : {config.LLM_MODEL}\n")
            if self.qualification:
                f.write("\nQUALIFICATION OUTCOME\n")
                for checkpoint, value in self.qualification.items():
                    f.write(f"  {checkpoint:<10}: {value or 'not established'}\n")
            f.write("=" * 70 + "\n\n")
            for speaker, text in self.transcript:
                f.write(f"{speaker}: {text}\n\n")

        return {
            "audio": audio_path if self.segments else None,
            "transcript": transcript_path,
            "duration": duration,
        }
