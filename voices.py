"""
The voice catalogue for the agent.

Three backends are supported:

  "elevenlabs" - The best quality by a wide margin, and the one to use for
                 the demo recordings. Needs an API key in .env; the free
                 tier is enough for the assignment.
  "edge"       - Microsoft neural voices. Free and keyless, decent, but
                 flatter than ElevenLabs. Needs internet.
  "kokoro"     - The local 82M-param model. Fully offline and private, but
                 clearly synthetic and it has no Indian-accented voice.

Run `python preview_voices.py` to hear every option and pick one.
"""

VOICES = {
    # --- Best quality: your own ElevenLabs voice ---
    "eleven": {
        "backend": "elevenlabs",
        "id": None,  # taken from ELEVENLABS_VOICE_ID in .env
        "label": "ElevenLabs, the voice ID set in your .env",
        "note": "Best quality; needs an API key",
    },
    # --- Indian English: the natural fit for a Bengaluru property consultant ---
    "prabhat": {
        "backend": "edge",
        "id": "en-IN-PrabhatNeural",
        "label": "Indian English, male, warm and measured",
        "note": "Recommended for Rohan",
    },
    "neerja": {
        "backend": "edge",
        "id": "en-IN-NeerjaNeural",
        "label": "Indian English, female, friendly and clear",
    },
    "neerja_expressive": {
        "backend": "edge",
        "id": "en-IN-NeerjaExpressiveNeural",
        "label": "Indian English, female, more animated",
    },
    # --- Hindi, used automatically when the caller switches language ---
    "madhur": {
        "backend": "edge",
        "id": "hi-IN-MadhurNeural",
        "label": "Hindi, male",
        "note": "Auto-selected when the caller speaks Hindi",
    },
    "swara": {
        "backend": "edge",
        "id": "hi-IN-SwaraNeural",
        "label": "Hindi, female",
    },
    # --- Other polished options, if you prefer a non-Indian accent ---
    "ryan": {
        "backend": "edge",
        "id": "en-GB-RyanNeural",
        "label": "British English, male, crisp and premium",
    },
    "christopher": {
        "backend": "edge",
        "id": "en-US-ChristopherNeural",
        "label": "American English, male, deep and authoritative",
    },
    "sonia": {
        "backend": "edge",
        "id": "en-GB-SoniaNeural",
        "label": "British English, female, polished",
    },
    # --- Offline fallback: works with no internet at all ---
    "kokoro_michael": {
        "backend": "kokoro",
        "id": "am_michael",
        "label": "Offline local model, male",
        "note": "Works with no internet; more robotic",
    },
    "kokoro_heart": {
        "backend": "kokoro",
        "id": "af_heart",
        "label": "Offline local model, female",
        "note": "Works with no internet; more robotic",
    },
}

# Sample line used by preview_voices.py, chosen to exercise the tricky
# pronunciations (the developer name, Nandi, lakh) in one breath.
SAMPLE_LINE = (
    "Good morning! This is Rohan calling from Divya Shree Developers, about "
    "Whispers of the Wind, our villa plot project near Nundee Hills. "
    "Plots start at ninety two point four laakh. Do you have two minutes to talk?"
)


def resolve(name: str) -> dict:
    if name not in VOICES:
        raise KeyError(
            f"Unknown voice '{name}'. Available: {', '.join(VOICES)}. "
            "Run 'python preview_voices.py' to hear them."
        )
    return VOICES[name]
