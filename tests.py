"""
Tests for the two pieces of logic that carry real risk: the qualification
tracker and the speech normalizer.

    python tests.py

Neither of these can be verified by ear during a live call - a wrong
checkpoint or a mispronounced price just slips past - so they're pinned
down here instead.
"""
import sys

from qualification import BUDGET, GEOGRAPHY, INTENT, TIMELINE, QualificationTracker
from stt_engine import repair_transcript
from text_normalizer import normalize_for_speech

failures = []


def check(label, got, expected):
    if got == expected:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}\n          got:      {got!r}\n          expected: {expected!r}")
        failures.append(label)


def state_after(utterances, pending=None):
    tracker = QualificationTracker()
    if isinstance(utterances, str):
        utterances = [utterances]
    for utterance in utterances:
        tracker.update(utterance, pending=pending)
    return {k: v for k, v in tracker.state.items() if v}


print("\nQualification tracker: reading checkpoints out of one reply")
check(
    "several checkpoints volunteered at once",
    state_after(
        "I'm an NRI, purely an investment, the Nandi Hills side is fine with me, "
        "and budget up to one and a half crore is okay."
    ),
    {INTENT: "investment", GEOGRAPHY: "comfortable", BUDGET: "fits"},
)
check("self-use phrasing", state_after("I want to build a small house for myself."), {INTENT: "self-use"})
check("distance objection", state_after("That's almost two hours from my side."), {GEOGRAPHY: "concern"})
check("hindi intent", state_after("Haan ji, investment ke liye dekh raha hoon."), {INTENT: "investment"})

print("\nQualification tracker: budget resolved on the number, not keywords")
check("below the entry price", state_after("My budget is only around 45 lakh."), {BUDGET: "below range"})
check("above the entry price", state_after("Budget up to 1.5 crore is okay."), {BUDGET: "fits"})
check("a range takes the ceiling", state_after("Somewhere between 80 lakh and 1 crore."), {BUDGET: "fits"})
check("no figure, no guess", state_after("I live in Koramangala."), {})

print("\nQualification tracker: bare yes/no attaches to the pending question")
check("bare yes", state_after("Yes, that works fine.", pending=GEOGRAPHY), {GEOGRAPHY: "comfortable"})
check("bare no", state_after("No, not really.", pending=TIMELINE), {TIMELINE: "concern"})
check("bare yes in hindi", state_after("Haan ji, thik hai.", pending=GEOGRAPHY), {GEOGRAPHY: "comfortable"})
# Regression: a long reply that merely opens with "Yes" was being counted as
# a yes to whatever question was pending, rather than to what it actually said.
check(
    "long reply opening with 'Yes' does not answer the pending question",
    state_after(
        "Yes, two crores is the budget I have, I don't know your price range, "
        "so tell me what I can get",
        pending=GEOGRAPHY,
    ),
    {BUDGET: "fits"},
)

print("\nQualification tracker: first answer wins")
check(
    "later chatter doesn't overwrite an established checkpoint",
    state_after(["Purely an investment.", "Well, maybe I'd live there one day."]),
    {INTENT: "investment"},
)

print("\nSpeech normalizer: Indian number and currency formatting")
check(
    "price range",
    normalize_for_speech("Plots run from Rs.92.4 lakh to 2.46 crore."),
    "Plots run from ninety two point four laakh to two point four six crore.",
)
check(
    "percentage and area",
    normalize_for_speech("74% open space and a 20,000 sq.ft. clubhouse."),
    "seventy four percent open space and a twenty thousand square feet clubhouse.",
)
check(
    "rupees when no Indian unit follows",
    normalize_for_speech("About Rs.7,700 per sq ft."),
    "About seven thousand seven hundred rupees per square feet.",
)
check("year", normalize_for_speech("Possession in December 2029."), "Possession in December two thousand and twenty nine.")

print("\nSpeech normalizer: pronunciation and stripping")
check(
    "proper nouns respelled, markdown removed",
    normalize_for_speech("**Divyasree** Developers, near Nandi Hills in Devanahalli."),
    "Divya Shree Developers, near Nundee Hills in Deva Nuhhully.",
)
check(
    "control tag never spoken",
    normalize_for_speech("I'll have an expert call you. [END_CALL]"),
    "I'll have an expert call you.",
)
check(
    "placeholder never spoken",
    normalize_for_speech("Our expert, [no name mentioned], will call."),
    "Our expert, will call.",
)

print("\nTranscript repair: Whisper's predictable mishearings")
check(
    "'Tocros' is the amount, not a word to say back",
    repair_transcript("Tocros is the budget I have, tell me what I can get in Tocros"),
    "two crores is the budget I have, tell me what I can get in two crores",
)
check("misheard lakh", repair_transcript("Around ninety two lacs."), "Around ninety two lakh.")
check("developer name", repair_transcript("Is this Divya Shree Developers?"), "Is this Divyasree Developers?")
check("place name", repair_transcript("Somewhere near Deva Nahalli."), "Somewhere near Devanahalli.")
check("repaired text still parses as budget", state_after(repair_transcript("Tocros is my budget")), {BUDGET: "fits"})

print()
if failures:
    print(f"{len(failures)} test(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("All tests passed.")
