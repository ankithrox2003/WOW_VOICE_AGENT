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
        (r"(\bthat works\b|\bcomfortable\b|\bno problem\b|\bbudget is fine\b|\baffordable\b|\bwithin (my|our) budget\b|\bmanageable\b)", "fits"),
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

_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\b", re.IGNORECASE)


def _budget_from_amounts(text: str):
    """Resolve the budget checkpoint from any rupee figure the caller states."""
    amounts_in_lakhs = []
    for value, unit in _AMOUNT_RE.findall(text):
        lakhs = float(value) * (100 if unit.lower().startswith(("crore", "cr")) else 1)
        amounts_in_lakhs.append(lakhs)

    if not amounts_in_lakhs:
        return None
    # Compare against the highest figure mentioned: "80 lakh to 1 crore"
    # means the ceiling is what matters for fitment.
    return "fits" if max(amounts_in_lakhs) >= ENTRY_PRICE_LAKHS else "below range"


# A bare "yes" only means something relative to the question just asked, so
# these are resolved against the checkpoint that was pending. Intent is
# excluded: it's a choice between two options, never a yes/no.
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

        # Fall back to the question that was actually on the table.
        if pending in _YES_NO_RESOLUTION and not self.state[pending]:
            yes_value, no_value = _YES_NO_RESOLUTION[pending]
            if _AFFIRMATION_RE.match(caller_text.strip()):
                self.state[pending] = yes_value
            elif _NEGATION_RE.match(caller_text.strip()):
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
        """The live state note injected into the model's context each turn."""
        lines = ["LIVE CALL STATE - read this before you reply."]

        if self.known:
            lines.append("The caller has ALREADY answered these. Do NOT ask about them again:")
            for checkpoint, value in self.known.items():
                lines.append(f"  - {checkpoint.upper()}: {value}")
        else:
            lines.append("No checkpoints answered yet.")

        if self.all_qualified:
            lines.append(
                "All four checkpoints are done. Give your two-sentence pitch if you "
                "haven't yet, then ask for the follow-up call with a Property Expert."
            )
        else:
            next_checkpoint = self.open_checkpoints[0]
            lines.append(
                f"Your next question must be about {next_checkpoint.upper()}: "
                f"ask {_QUESTION_FOR[next_checkpoint]}."
            )
            lines.append("Ask that ONE question only. Two sentences maximum.")

        return "\n".join(lines)
