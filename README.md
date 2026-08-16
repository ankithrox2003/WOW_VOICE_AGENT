# WOW Lead Qualifier - Outbound AI Voice Agent

A real-time outbound voice agent for **DivyaSree "Whispers of the Wind"**,
built from raw Python rather than a hosted voice platform. You run it, the
phone "rings", and you hold a live spoken conversation with Rohan, the
property consultant.

There is only ever one synthetic voice on the call: Rohan's. You are the
caller, speaking into your microphone.

**Deliverables: [`deliverables/`](deliverables/)** - recorded call audio with
transcripts and the qualification outcome for each, plus
[the system prompt as a PDF](deliverables/WOW_Rohan_System_Prompt.pdf).

| Layer | What it uses | Runs where |
|---|---|---|
| Turn-taking | WebRTC VAD | Local |
| Speech to text | faster-whisper | Local |
| Reasoning | Ollama + llama3.2:3b | Local (your GPU) |
| Text to speech | ElevenLabs `eleven_flash_v2_5` | API (free tier) |
| Fallback voices | Microsoft `edge-tts`, then Kokoro 82M | Network, then local |

---

## 1. Prerequisites

**Ollama** - download from https://ollama.com, then pull the model:

```powershell
ollama pull llama3.2:3b
ollama list          # confirm it's there
```

**Python 3.11** is recommended (3.10–3.12 all work).

## 2. Install

```powershell
cd wow_voice_agent
py -3.11 -m venv venv
.\venv\Scripts\activate

# CPU-only PyTorch keeps the download to ~200MB instead of ~2.5GB
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## 3. Set up the voice

### ElevenLabs (default, best quality)

1. Sign up at https://elevenlabs.io - the free tier gives 10,000 credits/month.
2. Profile icon → **API Keys** → create one.
3. Copy `.env.example` to `.env` and paste the key in:

```powershell
copy .env.example .env
notepad .env
```

4. Pick a voice. This lists every voice on your account and your remaining
   credits:

```powershell
python list_voices.py            # list them
python list_voices.py --preview  # hear them
```

Browse https://elevenlabs.io/app/voice-library for Indian-accented voices and
add them to your account first; they'll then appear in the list above. Paste
the ID you want into `ELEVENLABS_VOICE_ID` in `.env`.

**Credits.** `eleven_flash_v2_5` bills 0.5 credits per character, so 10,000
credits is roughly 20,000 characters - about **15–20 full demo calls**.
`list_voices.py` prints how many you have left.

### Free alternatives (no key needed)

If you'd rather not use a key, or you run out of credits, set `TTS_VOICE` in
`config.py` to any of these and audition them with `python preview_voices.py`:

| Key | Voice |
|---|---|
| `prabhat` | Indian English, male, warm - best keyless option |
| `neerja` / `neerja_expressive` | Indian English, female |
| `ryan` / `christopher` | British / American male |
| `sonia` | British female |
| `madhur` / `swara` | Hindi male / female |
| `kokoro_michael` / `kokoro_heart` | Fully offline, more robotic |

Override per call with `python voice_agent.py --voice prabhat`.

If the primary voice fails mid-call - bad key, exhausted quota, dropped
connection - the agent automatically walks down `TTS_FALLBACK_CHAIN` in
`config.py` instead of crashing. The last link is fully offline, so a call
never dies for want of a voice.

## 4. Make a call

```powershell
python voice_agent.py
```

Rohan speaks first. Reply out loud - the agent detects when you stop talking
and responds, so you never press a key. `Ctrl+C` hangs up.

Name the recording folder per scenario:

```powershell
python voice_agent.py --scenario happy_path
python voice_agent.py --scenario budget_mismatch
python voice_agent.py --scenario geography_mismatch
python voice_agent.py --scenario irritated_caller
python voice_agent.py --scenario hindi_hinglish
```

**Use headphones.** On open speakers the mic can hear Rohan and transcribe
him as if he were you.

## 5. What each call produces

```
recordings/<scenario>/
    full_call.wav      <- the complete conversation, both sides
    transcript.txt     <- text log + the four qualification outcomes
    turn_01_you.wav    <- your individual turns
    ...
```

`recordings/` is gitignored, since the wav files are large. To package calls
for sharing, and to rebuild the prompt PDF from the live source:

```powershell
python export_recordings.py   # wav -> mp3 + transcripts into deliverables/
python make_prompt_pdf.py     # deliverables/WOW_Rohan_System_Prompt.pdf
```

## 6. How it works

```
you speak ─► VAD detects your pause ─► Whisper transcribes
   └─► qualification tracker updates the four checkpoints
       └─► Ollama streams a reply, sentence by sentence
           └─► each finished sentence is spoken while the next is generated
```

Four design decisions carry most of the quality:

**Sentence-level streaming.** Rohan starts speaking as soon as his first
sentence exists, rather than after the whole reply is written. That's the
difference between ~1 second and ~5 seconds of dead air per turn.

**A qualification tracker outside the model** (`qualification.py`). The
assignment's sharpest requirement is never re-asking something the caller
already answered. A 3B model won't reliably hold that state across a call,
so it's tracked in code and injected into the model's context each turn as
an explicit "you already know X, ask about Y next" briefing.

**Deterministic pronunciation** (`text_normalizer.py`). The system prompt
asks the model to spell out "ninety two point four laakh", but models drift.
Every reply is rewritten in code before it reaches the voice: digits and
currency become Indian-format words, `sq.ft.` becomes "square feet", and
proper nouns like *DivyaSree* and *Nandi* are respelled phonetically.

**Transcript repair before the model sees it** (`stt_engine.py`). Whisper
mishears Indian property vocabulary in consistent ways - "two crores" comes
back as "Tocros" almost every time. Left alone, the model reads the nonsense
word back to the caller, which is the fastest way to sound like a machine.
Instructing the model not to do that failed twice: naming the bad string in
the prompt is exactly what makes the model produce it. Repairing the
transcription in code fixed it permanently, for any model.

## 7. Tests

```powershell
python tests.py
```

Covers the qualification tracker and the speech normalizer - the two places
where a bug is invisible during a live call. A checkpoint silently recorded
against the wrong question, or a price read aloud as "92.4" instead of "ninety
two point four laakh", both sound fine to the code and wrong to the caller.
Four real bugs came out of writing these, including a caller saying "Yes, two
crores is my budget" being logged as a yes to whatever question happened to be
pending.

## 8. Configuration

Everything tunable lives in `config.py`:

- `LLM_MODEL` - see the comparison below
- `LLM_NUM_CTX` - **keep this capped.** Left unset, Ollama reserves the
  model's full 131k context, which inflates the allocation past a laptop
  GPU's VRAM and silently pushes most layers onto the CPU. On a 6GB RTX 3050
  this one setting is the difference between 2.6 and 36 tokens/sec.
- `SILENCE_TIMEOUT_MS` - how long a pause ends your turn (raise it if you're
  cut off mid-sentence)
- `VAD_AGGRESSIVENESS` - 0–3; raise it in a noisy room
- `STT_MODEL_SIZE` - `small` transcribes Indian accents better; `tiny` is faster

### Why llama3.2:3b and not llama3.1:8b

Both were replayed against the same four recorded caller turns, transcription
errors included, on a 6GB RTX 3050:

| | llama3.2:3b | llama3.1:8b |
|---|---|---|
| Time to first spoken word | **1.0s** | 4.8s |
| Cold start | 1.8s | 12.4s |
| GPU placement at 4096 context | 100% GPU | 25% CPU / 75% GPU |
| Average reply length | 32 words | 33 words |

The 8B reasoned better on garbled input, which was the one thing that would
have justified the latency. Once transcript repair moved that problem out of
the model's hands, the 3B matched it on facts at roughly four times the speed.
Five seconds of silence after every question is far more damaging to a sales
call than an occasional clumsy sentence, so the 3B is the default. Set
`LLM_MODEL = "llama3.1:8b"` if you'd rather trade the latency back.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Cut off mid-sentence | Raise `SILENCE_TIMEOUT_MS` in `config.py` |
| It transcribes Rohan's own voice | Use headphones |
| `ELEVENLABS_API_KEY is not set` | Copy `.env.example` to `.env` and fill it in |
| ElevenLabs `401` | Key is wrong, or `ELEVENLABS_OUTPUT_FORMAT` is a paid-tier format |
| ElevenLabs `429` | Out of credits - check `python list_voices.py` |
| `403` from edge-tts | `pip install --upgrade edge-tts` |
| Replies take many seconds | Confirm `ollama ps` shows `100% GPU` |
| Wrong microphone | `python voice_agent.py --list-devices` |

Secrets live only in `.env`, which is gitignored and never printed by any
script here.
