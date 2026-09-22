# Implementation Plan

This document records the implemented MVP, its operational constraints, and
remaining verification work. `docs/architecture.md` remains the source of truth
for system design.

## Current MVP flow

```text
Home focus selection
→ Start meeting
→ live Deepgram transcription
→ behavioral and semantic coaching
→ selective live nudge
→ End meeting
→ finalization and completed-session snapshot
→ post-meeting report
→ optional reflection
→ Finish / cleanup
→ generic adviser-learning persistence
```

The root route is the implemented application. `/mockup` remains an isolated
frontend-only reference route.

## Slice 1 — Live transcription

**Status:** Implemented; manual browser verification recorded.

### Current implementation

The browser captures mono `audio/webm;codecs=opus` microphone audio and sends
ordered binary chunks over `/ws/transcription`. FastAPI bridges each active
browser session to a Deepgram Listen v1 connection using:

- `model="nova-3"` and `language="en-US"`
- `diarize_model="latest"`, `channels=1`, and `interim_results=True`
- `endpointing=500`, `punctuate=True`, and `mip_opt_out=True`

Interim results are not emitted as application `SpeakerTurn`s. Finalized words
are accumulated into coherent speaker turns, using word timestamps to create
millisecond start, end, and duration values. The first observed raw Deepgram
speaker label maps to `advisor`; all other labels map to `customer`. Extra
labels are therefore collapsed into the two-role contract.

On Stop, the browser stops the recorder, sends its queued final chunk, then
sends the stop control message. The backend calls Deepgram Finalize, waits for a
bounded final-result window, flushes remaining buffered words, and sends
`session.stopped`. No automatic mid-session reconnect is attempted because it
would reset diarization mapping and timestamps.

### Constraints and recorded verification

Coherent finalized turns are preferred to immediate incremental speaker-run
emission. Short handoffs can remain buffered until endpointing or finalization,
so transcript and coaching latency are accepted MVP tradeoffs. There is no
incremental speaker-boundary optimization or periodic partial-turn analysis.

Known limitations are browser MediaRecorder/WebM support, fragmented WebM
behavior across browsers, loss of an unfinalized final phrase after abrupt
disconnect, and imperfect single-microphone diarization.

Recorded manual verification confirms real browser microphone streaming,
finalized turns during a live session, final-phrase handling on Stop, and
restart/reset behavior. A real two-person speaker-separation test was performed,
but diarization consistency remains an MVP limitation rather than a guarantee of
speaker identity.

## Slice 2 — Live coaching

**Status:** Implemented; automated checks pass. Core semantic, pace, and
open-question paths have recorded manual verification. Real two-person
interruption/overlap verification remains pending.

### Dimensions and behavioral signals

Every meeting monitors all five coaching dimensions:

1. Pace & pauses
2. Turn-taking & interruptions
3. Open questions
4. Acknowledging emotional cues
5. Stay with the customer before solving

Selected focus areas prioritize otherwise eligible nudges and receive more
report attention. They do not disable the other dimensions or lower the
high-confidence nudge threshold.

Behavioral rules are MVP heuristics, not scientific measurements:

- Pace uses recognized-word span: `>=175 WPM` is high confidence after at least
  3 seconds, medium after 2 seconds, and `>=170 WPM` is low confidence.
- Adviser turns of 30 seconds or more produce long-monologue evidence; 45
  seconds is high confidence.
- A response gap below 600 ms after a customer turn is supporting evidence.
- Adviser/customer overlap of at least 300 ms is an interruption candidate;
  two such overlaps within the two-minute relevance window are high confidence.
- After at least 60 seconds of usable speech, adviser talk time above 70% is
  supporting evidence rather than a standalone nudge.

Talk-time balance is evidence for turn-taking, not a sixth coaching dimension.
Prosody or emotion inferred from audio is not part of the MVP. Single-microphone
diarization makes overlap and role attribution approximate.

### Semantic rules, context, and concurrency

Semantic analysis uses bounded rolling context: up to eight recent finalized
turns capped near 1,200 characters, a summary capped at 300 characters, up to
eight recent events, and the last three displayed nudges. Events remain live for
approximately two minutes.

Only one semantic request runs at a time. New turns replace a single coalesced
latest pending snapshot; stale results are rejected before they mutate context.
Semantic failures do not stop transcription or behavioral detection.

Important event rules are:

```text
CLOSED_QUESTION_PATTERN
→ open_questions
→ ASK_OPEN_QUESTION

CUSTOMER_EMOTIONAL_CUE
→ acknowledging_emotional_cues
→ context only; never directly nudges

MISSED_EMOTIONAL_CUE
→ acknowledging_emotional_cues
→ ACKNOWLEDGE_EMOTION

PREMATURE_PROBLEM_SOLVING
→ stay_before_solving
→ STAY_BEFORE_SOLVING
```

Customer-dependent events require customer evidence. Missed emotional-cue and
premature-solving analysis must concern the immediate first adviser response;
an adviser-only transcript cannot create those nudges. A necessary factual
closed question is not automatically a coaching issue.

### Nudge behavior and regression history

Live nudges require high confidence and use a short predefined text library.
The decision layer applies a 75-second global cooldown and 180-second same-key
suppression. Candidates blocked by cooldown are discarded rather than queued.

Recorded regression fixes include preventing adviser-only customer-dependent
false positives, requiring first-adviser-response evidence, rejecting stale
semantic mutations, and expiring old semantic events. The existing manual
checks also cover missed emotional cues, appropriate acknowledgement, premature
problem-solving, fast pace, closed-question patterns, and cooldown suppression.

## Slice 3 — Post-meeting report and reflection

**Status:** Implemented; automated checks pass. Real OpenRouter/Gemini report
generation and the reflection flow have been manually verified. The broader
end-to-end two-person rehearsal remains pending in Slice 5.

### Completed meeting snapshot and report

After Deepgram finalization and the final transcript flush, the backend freezes
the coaching session and creates a backend-authoritative immutable
`CompletedMeetingSnapshot`. It contains the server-generated session ID,
finalized turns, selected focus, behavioral events, semantic events, and shown
nudges. The frontend's `sessionTurns` is only a temporary UI mirror and is not
the source of truth for report generation.

The report uses this completed snapshot and is cached in the in-memory
post-meeting session, so retrying an already successful report request does not
make another model call. A failed report remains retryable while the snapshot is
available. The client checks the active session ID before applying responses,
and the backend rejects results for expired/deleted sessions.

Report generation may use the complete temporary meeting transcript. It returns
concise qualitative strengths, improvements, focus summary, and takeaway; it
must not return scores, customer summaries or quotes, or financial advice.

### Reflection and cleanup

Reflection uses selected focus, the generated report, bounded generic reflection
context, and the reflection conversation messages. It does not send the full
meeting transcript to the reflection model.

The flow accepts at most two adviser replies. Each request has a client-generated
`messageId`; successful responses are stored by that ID, making retries
idempotent. Reflection and report results are guarded against expiry or stale
session state. `DELETE /post-meeting/{session_id}` is idempotent.

Reflection voice dictation uses `/ws/reflection-dictation`, a separate Deepgram
path with no diarization and no coaching observations. Its temporary transcript
is inserted into the editable reflection input before Send. Dictation audio and
intermediate transcription are not persisted.

### LLM route

```text
Provider/router: OpenRouter
Environment key: OPENROUTER_API_KEY
Base URL: https://openrouter.ai/api/v1
Model: google/gemini-2.5-flash
Client SDK: Python openai package used as the OpenRouter-compatible client
```

The Python `openai` package is an SDK choice only. Application calls do not use
direct OpenAI services or `OPENAI_API_KEY`.

## Slice 4 — Persistent adviser learning

**Status:** Implemented; automated and recorded manual verification cover focus
persistence, completion with and without reflection, SQLite privacy boundaries,
and cleanup on persistence failure.

### Persistence contract

SQLite stores generic canonical adviser-learning data only: the local demo
adviser identifier, opaque session record ID, selected focus areas, canonical
strength and improvement areas, an optional canonical reflection-takeaway area,
and timestamps. It does not store audio, transcript text, speaker turns,
customer details or quotes, customer-specific summaries, report prose,
reflection free text, provider output, evidence, nudges, or behavioral
measurements.

The default database is created automatically at
`backend/data/adviser_learning.db`. `ADVISER_LEARNING_DB_PATH` is an optional
development/test override. The Home endpoint reads saved focus and at most five
recent valid learning records to derive one deterministic qualitative coaching
insight. Persisted learning does not alter live-meeting coaching behavior.

Malformed history rows are ignored safely. Completion uses the session UUID as
an idempotency key, and temporary post-meeting state is deleted even if the
SQLite write fails. If no report is available, no learning row is created and
cleanup still runs.

Recorded manual verification includes SQLite inspection: persisted rows had the
expected generic adviser-learning fields, with no transcript, customer, report,
or reflection prose. It also covered focus persistence across reload/backend
restart, real OpenRouter/Gemini report generation, and completion with and
without reflection.

## Slice 5 — Integration, UI cleanup, hardening, and demo readiness

**Status:** Implemented.

The current code includes the simplified Home, live transcript presentation,
shared post-End preparation state, report/reflection flow, dictation controls,
Finish cleanup, persistence warning, bounded request handling, and idle reset.

Remaining manual work is a complete Chrome/Edge two-person rehearsal: verify
speaker separation, finalized-turn and nudge behavior, reflection dictation,
Finish cleanup, a second clean meeting, provider/setup instructions, and
failure/retry paths. Do not mark this slice complete until that rehearsal has
been recorded.

## Lifecycle and privacy boundary

Temporary meeting data includes meeting audio while streamed to Deepgram,
finalized transcript and rolling context, customer-specific context and meeting
events, reflection-dictation audio and intermediate transcript, temporary
reports, reflection context, and model requests.

Live frontend/backend session state clears on stop, failure, reset, disconnect,
or unmount as applicable. Visible live turns and the current nudge clear at End
meeting, while accepted finalized turns remain long enough to build the backend
snapshot. The completed post-meeting session remains in memory for report and
reflection until Finish, explicit cleanup, backend restart, or expiry after 30
minutes when the store is accessed. There is no general background deletion
scheduler.

## Verification commands

```bash
cd backend
.venv/bin/python -m compileall app
.venv/bin/python -m unittest discover -s tests

cd ../frontend
npm run lint
npm run build

cd ..
git diff --check
```

Automated tests do not make real Deepgram or OpenRouter calls.
