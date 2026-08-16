"""
Local LLM via Ollama. Requires the Ollama server running on localhost
(https://ollama.com) with the configured model pulled, e.g.:

    ollama pull llama3.2:3b

No API key, no cloud calls.

The conversation streams tokens and hands back complete sentences as soon
as they form, so the TTS layer can start speaking while the model is
still writing.
"""
import re

import ollama

import config
from system_prompt import SYSTEM_PROMPT

# Periods that do not end a sentence: decimals (92.4), initials, and the
# handful of abbreviations that show up in this domain.
_ABBREVIATIONS = ("Rs.", "Mr.", "Mrs.", "Ms.", "Dr.", "sq.", "ft.", "approx.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Small chat models sometimes echo their own turn header ("assistant\n\n")
# into the reply body. Spoken aloud that becomes the agent literally saying
# the word "assistant", so it's stripped before anything reaches the voice.
_ROLE_HEADER_RE = re.compile(r"^\s*(assistant|system|user)\s*[:\n]+", re.IGNORECASE)


def _strip_role_headers(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _ROLE_HEADER_RE.sub("", text).lstrip()
    return text


def _split_complete_sentences(buffer: str):
    """
    Split `buffer` into (finished_sentences, remainder).

    The remainder is text after the last sentence terminator, which may
    still be growing as more tokens arrive.
    """
    parts = _SENTENCE_END.split(buffer)
    if len(parts) == 1:
        return [], buffer

    finished, remainder = parts[:-1], parts[-1]

    # Re-join pieces that were split on a period that wasn't a real
    # sentence break, like "92." + "4 lakh" or "Rs." + "5000".
    merged = []
    for part in finished:
        if merged and (
            merged[-1].endswith(_ABBREVIATIONS) or re.search(r"\d\.$", merged[-1])
        ):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)

    if merged and (
        merged[-1].endswith(_ABBREVIATIONS) or re.search(r"\d\.$", merged[-1])
    ):
        remainder = f"{merged.pop()} {remainder}"

    return merged, remainder


class Conversation:
    """
    Holds the running message history for one call so the model remembers
    what the caller already said and doesn't re-ask.
    """

    def __init__(self, model: str = None, system_prompt: str = None):
        self.model = model or config.LLM_MODEL
        self.messages = [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT}
        ]

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.messages.append({"role": "assistant", "content": text})

    @property
    def _options(self):
        return {
            "temperature": config.LLM_TEMPERATURE,
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": config.LLM_MAX_TOKENS,
        }

    def _messages_with(self, context_note: str):
        """
        History plus a transient system note.

        The note is placed last so it's the most recent thing the model
        sees, and it is never stored in history: it describes the state
        *right now*, and keeping stale copies would confuse later turns.
        """
        if not context_note:
            return self.messages
        return self.messages + [{"role": "system", "content": context_note}]

    def stream_reply(self, context_note: str = None):
        """
        Yield the assistant's reply one complete sentence at a time.

        The full reply is appended to history once the stream ends.
        """
        buffer = ""
        full_reply = ""

        stream = ollama.chat(
            model=self.model,
            messages=self._messages_with(context_note),
            options=self._options,
            stream=True,
        )

        yielded_any = False
        for chunk in stream:
            token = chunk["message"]["content"]
            if not token:
                continue
            buffer += token
            full_reply += token

            sentences, buffer = _split_complete_sentences(buffer)
            for sentence in sentences:
                cleaned = _strip_role_headers(sentence).strip()
                if cleaned:
                    yielded_any = True
                    yield cleaned

        leftover = _strip_role_headers(buffer).strip()
        # If the token ceiling cut the model off mid-sentence, speaking the
        # fragment sounds worse than stopping at the last complete thought.
        if leftover and (not yielded_any or leftover.endswith((".", "!", "?", "]"))):
            yield leftover
        elif leftover:
            full_reply = full_reply[: full_reply.rfind(leftover)]

        # Store the cleaned text: leaving a stray role header in the history
        # teaches the model to keep producing them on later turns.
        self.add_assistant(_strip_role_headers(full_reply).strip())

    def get_reply(self, context_note: str = None) -> str:
        """Non-streaming variant, for callers that don't need incremental audio."""
        response = ollama.chat(
            model=self.model,
            messages=self._messages_with(context_note),
            options=self._options,
        )
        reply = _strip_role_headers(response["message"]["content"]).strip()
        self.add_assistant(reply)
        return reply
