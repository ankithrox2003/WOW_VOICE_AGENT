"""
ElevenLabs text-to-speech.

Talks to the REST API directly with `requests` rather than the official
SDK: it's one endpoint, and it keeps the dependency surface small.

The API key is read from the environment (or a local .env file) and is
never logged, printed, or written into any recording or transcript.

Model choice: eleven_flash_v2_5 is their low-latency model (~75ms), which
is what a live phone conversation needs, and it bills at half the credit
rate of the standard models. It also handles Hindi, so the multilingual
part of the call works on the same voice.
"""
import io
import os

import numpy as np
import requests
import soundfile as sf
from dotenv import load_dotenv

import config

load_dotenv()

API_BASE = "https://api.elevenlabs.io/v1"
_TIMEOUT = 30


class ElevenLabsError(RuntimeError):
    pass


def get_api_key() -> str:
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise ElevenLabsError(
            "ELEVENLABS_API_KEY is not set. Copy .env.example to .env and paste "
            "your key in, then re-run."
        )
    return key


def get_voice_id() -> str:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if not voice_id:
        raise ElevenLabsError(
            "ELEVENLABS_VOICE_ID is not set. Run 'python list_voices.py' to see "
            "the voices on your account, then paste one into .env."
        )
    return voice_id


def _headers() -> dict:
    return {"xi-api-key": get_api_key()}


def list_voices() -> list:
    """Every voice available on this account."""
    response = requests.get(f"{API_BASE}/voices", headers=_headers(), timeout=_TIMEOUT)
    if response.status_code == 401:
        raise ElevenLabsError("ElevenLabs rejected the API key (401).")
    response.raise_for_status()
    return response.json().get("voices", [])


def get_quota() -> dict:
    """Remaining credits, so you can see how many demo calls are left."""
    response = requests.get(
        f"{API_BASE}/user/subscription", headers=_headers(), timeout=_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    used = data.get("character_count", 0)
    limit = data.get("character_limit", 0)
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "tier": data.get("tier", "unknown"),
    }


def synthesize(text: str, voice_id: str = None) -> np.ndarray:
    """Render `text` and return float32 mono samples at config.TTS_SAMPLE_RATE."""
    voice_id = voice_id or get_voice_id()

    response = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}",
        headers={**_headers(), "Content-Type": "application/json"},
        params={"output_format": config.ELEVENLABS_OUTPUT_FORMAT},
        json={
            "text": text,
            "model_id": config.ELEVENLABS_MODEL,
            "voice_settings": config.ELEVENLABS_VOICE_SETTINGS,
        },
        timeout=_TIMEOUT,
    )

    if response.status_code == 401:
        raise ElevenLabsError("ElevenLabs rejected the API key (401).")
    if response.status_code == 429:
        raise ElevenLabsError("ElevenLabs quota exhausted or rate limited (429).")
    if not response.ok:
        raise ElevenLabsError(f"ElevenLabs returned {response.status_code}: {response.text[:200]}")

    audio, sample_rate = sf.read(io.BytesIO(response.content), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if sample_rate != config.TTS_SAMPLE_RATE:
        from scipy.signal import resample_poly

        gcd = np.gcd(sample_rate, config.TTS_SAMPLE_RATE)
        audio = resample_poly(
            audio, config.TTS_SAMPLE_RATE // gcd, sample_rate // gcd
        ).astype(np.float32)

    return audio.astype(np.float32)
