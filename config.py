"""
Central configuration for the WOW voice agent.

Every tunable knob lives here so the pipeline modules stay focused on
their one job.
"""

# --- LLM (Ollama, local) ---
# num_ctx matters a lot on a 6GB laptop GPU: Ollama otherwise reserves the
# model's full advertised context (131k for llama3.x), which inflates the
# allocation past VRAM and silently spills most layers onto the CPU.
# Capping it keeps the whole model resident on the GPU.
LLM_MODEL = "llama3.2:3b"
LLM_NUM_CTX = 4096
LLM_TEMPERATURE = 0.6
# A spoken turn should be two sentences. This ceiling is the backstop for
# when the model ignores that instruction; ~110 tokens is roughly 80 words.
LLM_MAX_TOKENS = 110

# --- STT (faster-whisper, local) ---
# "small" is worth the extra ~1s per turn: "base" mangles Indian-accented
# English badly enough that the LLM ends up answering a question you never
# asked. Drop to "base" or "tiny" only if transcription latency hurts.
STT_MODEL_SIZE = "small"
STT_COMPUTE_TYPE = "int8"
STT_DEVICE = "cpu"

# --- TTS ---
# Run `python preview_voices.py` to hear all the options, then set the key
# you liked here. See voices.py for the full catalogue.
TTS_VOICE = "eleven"  # ElevenLabs, using the voice ID from your .env

# ElevenLabs settings. flash_v2_5 is their low-latency model (~75ms), which
# is what a live conversation needs, and it costs 0.5 credits per character
# instead of 1 - so the free tier stretches to roughly twice as many calls.
ELEVENLABS_MODEL = "eleven_flash_v2_5"

# mp3_22050_32 is available on every plan including the free tier. Higher
# bitrates are gated behind paid tiers and will 401 if you're on free.
ELEVENLABS_OUTPUT_FORMAT = "mp3_22050_32"

ELEVENLABS_VOICE_SETTINGS = {
    "stability": 0.45,  # lower = more expressive, higher = more consistent
    "similarity_boost": 0.75,
    "style": 0.30,  # a little warmth for a sales consultant
    "use_speaker_boost": True,
}

# Used when the caller switches to Hindi. ElevenLabs' flash_v2_5 model is
# multilingual, so the same voice handles Hindi and no switch is needed;
# this only applies to the edge/kokoro backends. Set to None to disable.
TTS_HINDI_VOICE = None if TTS_VOICE == "eleven" else "madhur"

# Tried in order if the chosen voice fails mid-call (no key, quota gone,
# internet dropped). The call degrades to a lesser voice instead of dying.
# The last entry is fully offline, so there's always something that works.
TTS_FALLBACK_CHAIN = ["prabhat", "kokoro_michael"]

TTS_LANG_CODE = "a"  # Kokoro's language code, only used by the offline backend
TTS_SAMPLE_RATE = 24000

# --- Audio capture ---
MIC_SAMPLE_RATE = 16000  # webrtcvad and Whisper both want 16kHz
FRAME_MS = 30  # webrtcvad accepts only 10, 20, or 30 ms frames
VAD_AGGRESSIVENESS = 2  # 0-3; higher filters more non-speech
SILENCE_TIMEOUT_MS = 1000  # trailing silence that ends the caller's turn
MAX_TURN_SECONDS = 25
# How long to wait for you to start talking before treating it as dead air.
# Generous, because on a test call you're often still reading the console.
INITIAL_WAIT_SECONDS = 12

# --- Call control ---
MAX_TURNS = 14
END_CALL_TAG = "[END_CALL]"
RECORDINGS_DIR = "recordings"
