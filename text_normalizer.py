"""
Turns raw LLM output into something a TTS engine will read out loud
correctly.

The system prompt asks the model to spell numbers out and respell proper
nouns phonetically, but a model will drift from that eventually. This
module enforces it deterministically, so pronunciation never depends on
the LLM having a good day.

Three jobs:
  1. Strip formatting the model shouldn't have emitted (markdown, the
     [END_CALL] control tag, stage directions in brackets).
  2. Expand numbers, currency, and units into spoken words, using Indian
     numbering conventions (lakh / crore).
  3. Respell domain proper nouns phonetically for the voice model.
"""
import re

from num2words import num2words

# Phonetic respellings fed to the TTS engine. These are grapheme hacks:
# Kokoro's G2P frontend pronounces the respelled form correctly where it
# mangles the real spelling.
PRONUNCIATION_DICT = {
    "Divyasree": "Divya Shree",
    "DivyaSree": "Divya Shree",
    "Divya Sree": "Divya Shree",
    "Nandi": "Nundee",
    "Devanahalli": "Deva Nuhhully",
    "lakhs": "laakhs",
    "lakh": "laakh",
    "crores": "crores",
    "crore": "crore",
}

# Unit expansions applied before number handling.
UNIT_PATTERNS = [
    (r"\bsq\.?\s?ft\.?", "square feet"),
    (r"\bsq\.?\s?feet\b", "square feet"),
    (r"\bBHK\b", "B H K"),
    (r"\bkm\b", "kilometres"),
    (r"\bmins?\b", "minutes"),
    (r"\bhrs?\b", "hours"),
]


def _spell_number(text_number: str) -> str:
    """Convert a numeric string (possibly with commas/decimals) to words."""
    cleaned = text_number.replace(",", "")
    try:
        if "." in cleaned:
            whole, frac = cleaned.split(".", 1)
            words = num2words(int(whole)) if whole else "zero"
            # Decimals in prices are read digit by digit: 92.4 -> "point four"
            frac_words = " ".join(num2words(int(d)) for d in frac if d.isdigit())
            spoken = f"{words} point {frac_words}"
        else:
            spoken = num2words(int(cleaned))
    except (ValueError, OverflowError):
        return text_number
    # num2words emits "one thousand, two hundred"; the comma makes the voice
    # pause mid-figure, which sounds like two separate numbers.
    return spoken.replace(",", "")


def _expand_numbers(text: str) -> str:
    """Replace digit sequences with spoken words, handling ranges and currency."""
    # Ranges: "1200-3199" or "1200 - 3199" -> "... to ..."
    text = re.sub(
        r"(\d[\d,]*\.?\d*)\s*[-\u2013]\s*(\d[\d,]*\.?\d*)",
        lambda m: f"{_spell_number(m.group(1))} to {_spell_number(m.group(2))}",
        text,
    )

    # Percentages: "74%" -> "seventy-four percent"
    text = re.sub(
        r"(\d[\d,]*\.?\d*)\s*%",
        lambda m: f"{_spell_number(m.group(1))} percent",
        text,
    )

    # Rupee amounts. "lakh"/"crore" already imply rupees in speech, so only
    # append "rupees" when no Indian unit follows.
    def _rupees(match):
        amount = _spell_number(match.group(1))
        trailing_unit = match.group(2)
        if trailing_unit:
            return f"{amount} {trailing_unit}"
        return f"{amount} rupees "

    text = re.sub(
        r"(?:\u20b9|Rs\.?|INR)\s*(\d[\d,]*\.?\d*)(?:\s*(lakhs?|crores?))?",
        _rupees,
        text,
        flags=re.IGNORECASE,
    )

    # Any remaining bare numbers.
    text = re.sub(r"\b(\d[\d,]*\.?\d*)\b", lambda m: _spell_number(m.group(1)), text)
    return text


def _strip_formatting(text: str) -> str:
    """Remove anything that would be read aloud as literal punctuation noise."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)  # italics
    text = re.sub(r"^\s*[-*\u2022]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"`+", "", text)
    # Stage directions / control tags the model may leak, e.g. "[pause]".
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\([Ss]miles?\)|\([Ll]aughs?\)", "", text)
    return text


def _apply_pronunciations(text: str) -> str:
    for word, replacement in PRONUNCIATION_DICT.items():
        text = re.sub(rf"\b{re.escape(word)}\b", replacement, text, flags=re.IGNORECASE)
    return text


def normalize_for_speech(text: str) -> str:
    """Full pipeline: raw LLM text -> TTS-ready text."""
    text = _strip_formatting(text)

    for pattern, replacement in UNIT_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = _expand_numbers(text)

    # num2words hyphenates ("ninety-two"); spaces read more reliably. This
    # runs before the pronunciation dict so respellings survive intact.
    text = text.replace("-", " ")

    text = _apply_pronunciations(text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    # Removing a bracketed aside leaves its surrounding punctuation orphaned,
    # e.g. "our expert, [no name], will call" -> "our expert,, will call".
    text = re.sub(r",\s*(?=[,.!?])", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Unit expansion can swallow a sentence-final period ("sq.ft." -> "square
    # feet"), leaving the voice without a place to land.
    if text and text[-1] not in ".!?":
        text += "."
    return text
