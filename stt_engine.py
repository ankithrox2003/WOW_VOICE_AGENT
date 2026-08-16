"""
Local speech-to-text using faster-whisper. Runs entirely on this machine;
after the model downloads once it needs no internet.

Language is auto-detected rather than pinned to English, so the agent can
follow a caller who switches to Hindi mid-call.
"""
from faster_whisper import WhisperModel

import config

_model = None

# Whisper is prone to inventing stock phrases when handed near-silence
# (a known artifact of its training data). Anything matching these, with
# nothing else in the turn, is treated as silence.
_HALLUCINATION_PHRASES = {
    "thank you.",
    "thanks for watching!",
    "thank you for watching!",
    "you",
    "bye.",
    ".",
    "please subscribe.",
    "subtitles by the amara.org community",
}


def get_model():
    global _model
    if _model is None:
        print(f"[STT] Loading Whisper '{config.STT_MODEL_SIZE}' (first run downloads it)...")
        _model = WhisperModel(
            config.STT_MODEL_SIZE,
            device=config.STT_DEVICE,
            compute_type=config.STT_COMPUTE_TYPE,
        )
    return _model


def transcribe(wav_path: str):
    """
    Transcribe a wav file.

    Returns (text, language). `text` is empty if the turn was effectively
    silence.
    """
    model = get_model()
    segments, info = model.transcribe(
        wav_path,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )

    kept = [
        segment.text.strip()
        for segment in segments
        if segment.no_speech_prob < 0.75 and segment.text.strip()
    ]
    text = " ".join(kept).strip()

    if text.lower() in _HALLUCINATION_PHRASES:
        return "", info.language

    language = info.language if info.language in ("en", "hi") else "en"
    return text, language
