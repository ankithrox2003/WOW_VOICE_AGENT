"""
Tracks which of the four qualification checkpoints the caller has already
answered.

The assignment's sharpest requirement is "avoid re-asking questions if the
user provides info early", and a small local model cannot be trusted to
keep that state in its head across a whole call. So the state is tracked
here, in code, and injected back into the model's context each turn as an
explicit briefing telling it exactly which question to ask next.

Detection is deliberately keyword-based rather than a second LLM call:
this runs in microseconds and adds nothing to the turn latency, which is
the whole budget we're protecting in a voice agent.
"""
import re

INTENT = "intent"
GEOGRAPHY = "geography"
BUDGET = "budget"
TIMELINE = "timeline"

CHECKPOINT_ORDER = [INTENT, GEOGRAPHY, BUDGET, TIMELINE]

_QUESTION_FOR = {
    INTENT: "whether this is for their own use or an investment",
    GEOGRAPHY: "whether they're comfortable with the Nun-dee Hills corridor",
    BUDGET: "whether a starting price of ninety two point four laakh broadly works",
    TIMELINE: "whether a December twenty twenty nine possession suits them",
}

# Short topic names, for telling the model which questions are now off limits.
_TOPIC_FOR = {
    INTENT: "their reason for buying",
    GEOGRAPHY: "the location or distance",
    BUDGET: "their budget or the price",
    TIMELINE: "possession timing",
}

# Each entry maps a checkpoint to (regex, resolved value). Hindi/Hinglish
# equivalents are included since the agent supports code-switching callers.
_PATTERNS = {
    INTENT: [
        (r"\b(invest(ment|ing|or)?|appreciat|resale|rental|returns?|portfolio|nivesh)\b", "investment"),
        (r"(\bself[\s-]?use\b|\blive there\b|\bweekend (home|place|house)\b|\bsecond home\b|\bretire\b|\bmy own\b|\bfor myself\b|\bfor my family\b|\bbuild\b.{0,25}\b(house|villa|home)\b|\bkhud ke liye\b|\brehne\b)", "self-use"),
    ],
    GEOGRAPHY: [
        (r"(\btoo far\b|\bvery far\b|\bquite far\b|\bthat.?s far\b|\bbahut door\b|\bdoor hai\b|\btwo hours\b|\b2 hours\b|\bother side of\b|\bnot convenient\b|\bprefer south\b)", "concern"),
        (r"(\bfine with me\b|\bworks for me\b|\bcomfortable\b|\bfamiliar with\b|\bknow that area\b|\bi go there\b|\blove that area\b|\bno issue\b|\bnear my\b)", "comfortable"),
    ],
    BUDGET: [
        (r"(\btoo expensive\b|\bout of my\b|\bbeyond my\b|\bcan.?t afford\b|\bcannot afford\b|\bbit steep\b|\btoo much\b|\bmehenga\b)", "below range"),
        # Deliberately specific: generic approval like "that works" or
        # "comfortable" is how callers answer the geography and timeline
        # questions too, so it can't be treated as budget evidence.
        (r"(\bbudget is fine\b|\baffordable\b|\bwithin (my|our) budget\b|\bbudget.{0,12}(no problem|not a problem|is okay)\b)", "fits"),
    ],
    TIMELINE: [
        (r"\b(long[\s-]?term|no hurry|not in a rush|fine with (that|2029)|20\s?29|that horizon works|hold it|patient)\b", "comfortable"),
        (r"\b(too long|need it sooner|immediately|ready to move|possession soon|jaldi|can't wait|four years is)\b", "concern"),
    ],
}


# The entry price for the project, in lakhs. A budget figure the caller
# states is compared against this rather than pattern-matched, so
# "only 45 lakh" and "up to 2 crore" resolve correctly on the numbers.
ENTRY_PRICE_LAKHS = 92.4

_UNIT_RE = r"(lakhs?|lacs?|crores?|cr)\b"
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*" + _UNIT_RE, re.IGNORECASE)

# Speech-to-text writes figures as words far more often than as digits, so
# "two crores" and "one and a half crore" have to parse as well as "1.5 cr".
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "das": 10,
}

_WORD_AMOUNT_RE = re.compile(
    r"((?:(?:" + "|".join(_NUMBER_WORDS) + r"|hundred|and|half|point)\s+)+)" + _UNIT_RE,
    re.IGNORECASE,
)


def _words_to_number(phrase: str):
    """Turn 'one and a half' or 'forty five' into a number, or None."""
    tokens = phrase.lower().split()
    total = 0.0
    seen_any = False
    pending_half = False

    for i, token in enumerate(tokens):
        if token == "half":
            # "one and a half" -> 1.5; "half a crore" -> 0.5
            total += 0.5
            seen_any = True
        elif token == "hundred":
            total = (total or 1) * 100
        elif token == "point":
            fraction = [_NUMBER_WORDS.get(t, 0) for t in tokens[i + 1:] if t in _NUMBER_WORDS]
            if fraction:
                total += fraction[0] / 10
            break
        elif token == "and":
            pending_half = True
        elif token in _NUMBER_WORDS:
            # Don't let the "a" in "and a half" register as another 1.
            if token in ("a", "an") and pending_half:
                continue
            total += _NUMBER_WORDS[token]
            seen_any = True

    return total if seen_any or pending_half else None


def _to_lakhs(value: float, unit: str) -> float:
    return value * (100 if unit.lower().startswith(("crore", "cr")) else 1)


def _budget_from_amounts(text: str):
    """Resolve the budget checkpoint from any rupee figure the caller states."""
    amounts_in_lakhs = [
        _to_lakhs(float(value), unit) for value, unit in _AMOUNT_RE.findall(text)
    ]

    for phrase, unit in _WORD_AMOUNT_RE.findall(text):
        value = _words_to_number(phrase)
        if value:
            amounts_in_lakhs.append(_to_lakhs(value, unit))

    if not amounts_in_lakhs:
        return None
    # Compare against the highest figure mentioned: "80 lakh to 1 crore"
    # means the ceiling is what matters.
    return "fits" if max(amounts_in_lakhs) >= ENTRY_PRICE_LAKHS else "below range"


# A bare "yes" only means something relative to the question just asked, so
# these are resolved against the checkpoint that was pending. Intent is
# excluded: it's a choice between two options, never a yes/no.
#
# The length guard matters. "Yes, two crores is the budget I have, tell me
# what that gets me" opens with an affirmative but is answering about budget,
# not about whichever question happened to be pending. Only treat a reply as
# a bare yes/no when there's essentially nothing else in it.
_BARE_REPLY_MAX_WORDS = 7
_AFFIRMATION_RE = re.compile(
    r"^\W*(yes|yeah|yep|sure|ok(ay)?|fine|absolutely|of course|no problem|"
    r"that.?s fine|sounds good|haan|haan ji|ji|bilkul|thik hai|theek hai|chalega)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"^\W*(no|nope|not really|nah|nahi|bilkul nahi|i don.?t think)\b", re.IGNORECASE
)
_YES_NO_RESOLUTION = {
    GEOGRAPHY: ("comfortable", "concern"),
    BUDGET: ("fits", "below range"),
    TIMELINE: ("comfortable", "concern"),
}


class QualificationTracker:
    def __init__(self):
        self.state = {checkpoint: None for checkpoint in CHECKPOINT_ORDER}
        self.permission_granted = False

    def update(self, caller_text: str, pending: str = None):
        """
        Scan a caller utterance and record any checkpoints it answers.

        `pending` is the checkpoint the agent just asked about, used to
        interpret bare affirmatives like "yes" or "thik hai".
        """
        text = caller_text.lower()

        if re.search(r"\b(yes|sure|go ahead|ok(ay)?|haan|boliye|tell me|i have a min)\b", text):
            self.permission_granted = True

        # A stated rupee figure is stronger evidence than any keyword.
        if not self.state[BUDGET]:
            self.state[BUDGET] = _budget_from_amounts(text)

        for checkpoint, patterns in _PATTERNS.items():
            if self.state[checkpoint]:
                continue  # first answer wins; don't let later chatter overwrite it
            for pattern, value in patterns:
                if re.search(pattern, text):
                    self.state[checkpoint] = value
                    break

        # Fall back to the question that was actually on the table, but only
        # for replies short enough to be purely a yes or no.
        stripped = caller_text.strip()
        if (
            pending in _YES_NO_RESOLUTION
            and not self.state[pending]
            and len(stripped.split()) <= _BARE_REPLY_MAX_WORDS
        ):
            yes_value, no_value = _YES_NO_RESOLUTION[pending]
            if _AFFIRMATION_RE.match(stripped):
                self.state[pending] = yes_value
            elif _NEGATION_RE.match(stripped):
                self.state[pending] = no_value

    @property
    def known(self):
        return {k: v for k, v in self.state.items() if v}

    @property
    def open_checkpoints(self):
        return [c for c in CHECKPOINT_ORDER if not self.state[c]]

    @property
    def all_qualified(self):
        return not self.open_checkpoints

    def briefing(self) -> str:
        """
        The live state note injected into the model's context each turn.

        Worded as a neutral status board on purpose. An earlier version said
        the caller had "ALREADY answered" things, and the model read that as
        an accusation and opened its replies with "I apologise for not
        knowing your budget earlier" - apologising to the caller for the
        contents of its own private notes.
        """
        lines = [
            "CALL STATE (private note to you, not part of the conversation).",
            "Never mention this note, never apologise, and never refer to what "
            "you did or didn't know earlier.",
        ]

        if self.known:
            lines.append("Confirmed so far:")
            for checkpoint, value in self.known.items():
                lines.append(f"  {checkpoint} = {value}")
            # Naming the off-limits questions outright works far better than
            # telling a small model to "move past" the settled ones.
            settled = ", ".join(_TOPIC_FOR[c] for c in self.known)
            lines.append(
                f"Do not ask about {settled} again, in any form, not even to "
                "confirm. Do not restate these figures back to the caller."
            )
        else:
            lines.append("Nothing confirmed yet.")

        if self.all_qualified:
            lines.append(
                "All four are settled. If you haven't pitched yet, give the "
                "two-sentence pitch now. Otherwise ask for the follow-up call "
                "with a Property Expert."
            )
        else:
            next_checkpoint = self.open_checkpoints[0]
            lines.append(f"Next: ask {_QUESTION_FOR[next_checkpoint]}.")
            lines.append("That one question only, in two sentences at most.")

        return "\n".join(lines)
