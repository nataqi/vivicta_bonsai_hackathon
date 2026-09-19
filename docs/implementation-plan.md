# Implementation Plan

This document is the single source of truth for approved implementation plans. Each approved slice is appended here, then updated only for status and material implementation deviations discovered during implementation.

## Slice 1 — Live Transcription

**Status:** Complete

**Manual verification:** Real browser microphone streaming works; finalized transcript turns appear during the live session; immediate Stop flushes the final phrase; and session cleanup and restart work correctly. Two-person speaker diarization works, though speaker separation was somewhat inconsistent across attempts and remains a known MVP limitation.

**Review lifecycle fix:** Ending a meeting now clears the live transcript and nudge immediately while retaining accepted finalized turns in temporary session state through Deepgram finalization. Stopping during a pending microphone request invalidates startup and stops any stream that resolves afterward.

### 1. Proposed Flow

```text
navigator.mediaDevices.getUserMedia()
→ MediaRecorder producing WebM/Opus chunks
→ binary frames over browser WebSocket
→ FastAPI WebSocket endpoint
→ Deepgram Listen v1 streaming connection
→ finalized, diarized word results
→ backend turn assembler
→ normalized SpeakerTurn JSON events
→ temporary React state
```

Message flow:

1. The adviser selects **Start transcription**.
2. The browser obtains microphone permission.
3. The frontend opens `ws://localhost:8001/ws/transcription`.
4. FastAPI opens one Deepgram stream for that browser session and returns `session.ready`.
5. The frontend starts `MediaRecorder` with a roughly 250 ms timeslice.
6. Each non-empty Blob becomes an `ArrayBuffer` and is sent as one binary WebSocket message.
7. FastAPI forwards those bytes unchanged and in order through SDK 7.9.0's `send_media()`.
8. A concurrent backend receive loop reads typed Deepgram `ListenV1Results` messages.
9. Interim results remain backend-only. Final result words are buffered until `speech_final=true`, grouped by consecutive Deepgram speaker label, and emitted as:

   ```json
   {
     "type": "speaker_turn",
     "turn": {
       "id": "...",
       "speaker": "advisor",
       "text": "...",
       "startTimeMs": 1200,
       "endTimeMs": 3800,
       "durationMs": 2600,
       "isFinal": true
     }
   }
   ```

10. Stop is a text control message. The browser remains connected while FastAPI finalizes Deepgram, emits any last turns, closes Deepgram, sends `session.stopped`, and then closes the browser socket.

WebSockets are appropriate because the same long-lived connection carries ordered binary audio upstream and status/turn events downstream.

### 2. Files

Existing files to modify:

- `backend/app/main.py`
  - Register the transcription WebSocket router.
  - Keep the existing health endpoints.
  - Allow both expected local frontend ports if the existing HTTP health check remains.

- `frontend/src/app/page.tsx`
  - Replace the health-check-only screen with the minimal real meeting state: Start, listening status, Stop, errors, and a lightweight temporary transcript panel.
  - Keep `/mockup` unchanged and isolated.

New files:

- `backend/app/transcription.py`
  - FastAPI WebSocket route.
  - Async Deepgram bridge using the installed SDK.
  - Session-local speaker mapping and finalized-turn assembly.
  - Cleanup and error handling.

- `backend/tests/test_transcription.py`
  - Standard-library unit tests for result buffering, speaker grouping, timestamp conversion, and mapping reset. No new test dependency is necessary.

- `frontend/src/hooks/useLiveTranscription.ts`
  - Export `SpeakerTurn`.
  - Own microphone, `MediaRecorder`, WebSocket, lifecycle state, and cleanup.
  - Hide transport details from the page.

No dependency changes should be required. Do not import mock data or mockup state into the real implementation.

### 3. Frontend Responsibilities

The frontend should own:

- Requesting microphone access with `getUserMedia`.
- Checking `MediaRecorder.isTypeSupported("audio/webm;codecs=opus")`.
- Creating a mono-oriented microphone stream, requesting echo cancellation, noise suppression, and automatic gain control.
- Opening the application WebSocket and waiting for `session.ready`.
- Starting `MediaRecorder` with WebM/Opus and a roughly 250 ms timeslice.
- Converting each Blob to bytes and sending it as a binary frame.
- Holding only the current session's finalized `SpeakerTurn[]` in React memory.
- Displaying connection state, microphone state, actionable errors, and readable adviser/customer turns.
- On Stop, stopping the recorder first, allowing its final `dataavailable` event to enqueue, then sending the JSON stop command.
- Stopping every microphone track and clearing all handlers/references on completion, error, disconnect, unmount, or restart.

The frontend should not know Deepgram credentials, parse Deepgram results, map speakers, or retain transcripts.

`MediaRecorder` supports timesliced Blob delivery, while the exact output type must be checked at runtime with `isTypeSupported`. [MDN MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder), [MDN `isTypeSupported`](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static)

### 4. Backend Responsibilities

FastAPI should own:

- One browser WebSocket and one Deepgram WebSocket per active session.
- Deepgram API credentials and configuration.
- Forwarding browser binary frames unchanged with `send_media()`.
- Concurrently receiving Deepgram events without blocking incoming browser audio.
- Ignoring empty transcripts and not forwarding raw provider events.
- Ignoring interim results for the Slice 1 UI.
- Buffering every `is_final=true` result until a turn boundary.
- Splitting finalized words into consecutive speaker runs.
- Mapping provider speaker labels to application roles.
- Producing IDs and millisecond timestamps.
- Emitting only normalized `SpeakerTurn` events.
- Holding all audio, transcript buffers, and speaker mapping in session memory only.
- Never logging transcript text or writing audio/transcripts to disk.
- Finalizing and closing Deepgram when Stop or disconnect occurs.

The locally installed `deepgram-sdk==7.9.0` exposes the required current API as:

- `AsyncDeepgramClient`
- `client.listen.v1.connect(...)`
- `send_media(bytes)`
- `recv()` or async iteration
- `send_finalize()`
- `send_close_stream()`

### 5. Deepgram Configuration

Use Listen v1 with:

- `model="nova-3"`
- `language="en-US"` for the current English demo
- `diarize_model="latest"`
- Do not also pass deprecated `diarize=true`
- `channels=1`
- `interim_results=True`
- `endpointing=500`
- `punctuate=True`
- `mip_opt_out=True`
- Omit `encoding`
- Omit `sample_rate`
- Omit `utterance_end_ms` and `vad_events` for this slice
- Omit `smart_format` initially to avoid its possible extra finalization delay around incomplete formatted entities

Nova-3 is the current general streaming model. For streaming diarization, `latest` currently resolves to the supported v1 diarizer, and each word receives a numeric speaker label. [Deepgram model options](https://developers.deepgram.com/docs/model), [Deepgram diarization](https://developers.deepgram.com/docs/diarization)

Use `endpointing=500` because Deepgram recommends roughly 300–500 ms for ordinary conversations. Process all `is_final=true` segments and treat `speech_final=true` as the boundary at which the accumulated utterance can be emitted; `speech_final` alone is insufficient because a long utterance may contain several final segments. [Deepgram endpointing and interim results](https://developers.deepgram.com/docs/understand-endpointing-interim-results)

`mip_opt_out=True` excludes the request from Deepgram's Model Improvement Program; Deepgram states opted-out data is retained only as needed to process the request. [Deepgram MIP documentation](https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program)

### 6. Audio Format

Browser capture:

- `getUserMedia({ audio: ... })`
- `MediaRecorder` explicitly configured as `audio/webm;codecs=opus`
- Initial Slice 1 browser target: current Chromium/Chrome or Edge
- Roughly 250 ms Blob chunks

Transport:

- Blob contents are converted to `ArrayBuffer`.
- Each buffer is sent as a binary frame over one continuous browser-to-FastAPI WebSocket.
- Chunks must remain ordered and must not be treated as independent audio files.

Deepgram receives:

- The same continuous WebM container byte stream containing Opus audio.
- The first recorder output supplies the container metadata; later chunks continue that stream.

Transcoding is not required. WebM is a supported Deepgram format, and Deepgram instructs clients to omit `encoding` and `sample_rate` for containerized audio so it can read those values from the container. Supplying Opus parameters for this WebM stream would risk incorrectly treating it as raw audio. [Deepgram live audio format guidance](https://developers.deepgram.com/docs/determining-your-audio-format-for-live-streaming-audio), [Deepgram supported formats](https://developers.deepgram.com/docs/supported-audio-formats)

If the target browser cannot produce WebM/Opus, Slice 1 should show an unsupported-browser error rather than add an AudioWorklet/resampling pipeline.

### 7. Speaker Handling

Deepgram assigns `speaker: 0`, `speaker: 1`, and so on to individual words, not to the entire result.

For each session, the backend keeps:

```text
first Deepgram label observed → advisor
every other label            → customer
```

Under the intended two-person demo, the second distinct label is therefore the customer. Treating any unexpected additional label as customer preserves the required two-role contract, though that limitation should be visible in logs without logging transcript text.

Turn assembly:

1. Ignore `is_final=false`.
2. Append words from each `is_final=true` result to the current utterance buffer.
3. Use each word's `speaker`, `start`, `end`, and `punctuated_word` where available.
4. At `speech_final=true`, split the complete buffer whenever the Deepgram speaker label changes.
5. Convert seconds to rounded milliseconds.
6. Create one `SpeakerTurn` per speaker run:
   - `startTimeMs`: first word start
   - `endTimeMs`: last word end
   - `durationMs`: end minus start
   - `isFinal`: always `true`
7. Clear the utterance buffer, but retain speaker-role mapping until the session ends.

This prevents raw event flooding and handles multiple finalized Deepgram results belonging to one conversational utterance.

### 8. Session and Cleanup Behavior

**Start**

- Clear prior turns and errors.
- Request microphone permission.
- If granted, open the application WebSocket.
- Start recording only after `session.ready`.
- A new start always creates a fresh backend session, Deepgram stream, transcript buffer, and speaker mapping.

**Permission denied**

- Do not open or retain a Deepgram session.
- Show a concise instruction to enable microphone permission.
- Leave Start available for retry.

**Stop**

- Disable repeated Stop actions.
- Stop `MediaRecorder`; its final `dataavailable` event is sent first.
- Send the stop control message.
- FastAPI calls `send_finalize()`.
- Continue receiving briefly for final results or `from_finalize=true`.
- Flush any completed finalized buffer, call `send_close_stream()`, send `session.stopped`, and close.
- The frontend stops all media tracks and returns to an idle/restartable state.

Deepgram's Finalize command forces buffered audio to be processed, although `from_finalize` is not guaranteed when there is no meaningful buffered audio; therefore cleanup needs a short bounded wait rather than waiting forever. [Deepgram Finalize](https://developers.deepgram.com/docs/finalize)

**Unexpected browser disconnect**

- Catch `WebSocketDisconnect`.
- Stop accepting audio.
- Best-effort finalize and close Deepgram.
- Drop all in-memory transcript and mapping state.

**Backend or Deepgram failure**

- Send a sanitized error event if the browser socket is still available.
- Stop the recorder and microphone on the frontend.
- Do not automatically reconnect mid-session in Slice 1, because a new Deepgram stream would reset diarization timestamps and speaker mapping.
- Allow a clean manual restart.

**Component unmount/navigation**

- Stop recorder and microphone tracks.
- Close the browser WebSocket.
- Remove callbacks so an old session cannot update a new page state.

### 9. Verification

#### Automated checks

Backend:

```bash
cd backend
.venv/bin/python -m compileall app
.venv/bin/python -m unittest discover -s tests
```

The unit tests should verify:

- Interim and empty results are ignored.
- Multiple final segments accumulate until `speech_final`.
- Consecutive words are grouped by speaker.
- Speaker changes inside one result produce separate turns.
- First speaker maps to advisor and the next to customer.
- Times convert correctly to milliseconds.
- Duration is calculated correctly.
- Finalize flushing does not duplicate turns.
- A new session resets speaker mapping.

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

Also verify TypeScript accepts binary WebSocket sending, message discrimination, and cleanup references.

#### Manual test

1. Run FastAPI on port 8001 and Next.js in current Chrome/Edge.
2. Open the real root page, not `/mockup`.
3. Select Start and grant microphone permission.
4. Confirm the UI changes from connecting to listening.
5. The adviser speaks first for several seconds and pauses.
6. Confirm a readable finalized `advisor` turn appears.
7. A second person speaks from the same room and pauses.
8. Confirm a separate finalized `customer` turn appears.
9. Alternate speakers several times, including one longer sentence with a short mid-sentence pause.
10. Verify interim revisions do not create duplicate or rapidly changing rows.
11. Select Stop immediately after a final short phrase.
12. Confirm that phrase is flushed if Deepgram finalized it, the microphone indicator turns off, no more turns arrive, and the UI can start a completely new session.

### 10. Risks / Uncertainties

- **Browser format support:** WebM/Opus is the smallest no-transcoding path but is not a safe assumption for every browser. Slice 1 should target and test the exact Chromium browser used for the demo.
- **Chunked WebM behavior:** Deepgram supports WebM, but the target browser's actual MediaRecorder byte stream must be smoke-tested because fragmented container behavior can vary by browser.
- **Single-microphone diarization:** Speaker labels are inferred acoustically and can change with overlap, distance, similar voices, or room noise. The adviser must speak first for the MVP mapping to be correct.
- **Unexpected extra speaker clusters:** Deepgram can produce more than two numeric labels even with two people; the two-role contract necessarily collapses those labels.
- **Turn boundary tuning:** 500 ms is a reasonable starting point but may split reflective speech or delay fast turn-taking. It should be tuned once using the real demo room and microphone.
- **Final phrase on abrupt disconnect:** Graceful Stop can use Finalize, but a tab crash or network loss may make the last unfinalized phrase unrecoverable.

### 11. Implementation Order

1. Add the pure backend turn assembler and its unit tests.
2. Add the FastAPI WebSocket route and async Deepgram bridge using SDK 7.9.0.
3. Add the frontend `useLiveTranscription` hook with microphone, MediaRecorder, WebSocket, and cleanup.
4. Replace the real root page with the minimal meeting/transcript verification UI; leave `/mockup` untouched.
5. Run backend unit checks and frontend lint/build.
6. Perform the two-person Chrome/Edge test.
7. Tune only MediaRecorder timeslice or Deepgram endpointing if the real test demonstrates a concrete latency or fragmentation problem.

## Slice 2 — Live Coaching

**Status:** Complete

**Manual verification:**

- Live Advisor → Customer → Advisor transcription works; missed emotional cues produce `ACKNOWLEDGE_EMOTION`, appropriate acknowledgement produces no acknowledgement nudge, and premature problem-solving produces `STAY_BEFORE_SOLVING`.
- Fast adviser speech produces `PACE_SLOW_DOWN`; a clear closed-question cluster produces `ASK_OPEN_QUESTION`; and the global cooldown suppresses a second eligible nudge.
- Regression verified: an all-Advisor transcript cannot produce customer-dependent semantic nudges. Speaker-role and canonical event/area/nudge validation were added during manual verification.
- End Meeting immediately clears the live transcript and nudge; Slice 3 will replace the empty post-end state with the post-meeting flow.
- Turn-taking/interruption remains pending real two-person manual verification because single-device synthetic voice does not reliably preserve overlap; automated interruption tests pass. Single-microphone diarization remains an MVP limitation, and finalized-turn latency can noticeably delay transcript/nudge appearance; tune only if it becomes a demo blocker.

**Material code-review fixes:** Pace uses recognized word-span elapsed time; stale semantic results are discarded before mutating context; customer-response evidence must cite the first adviser response; and semantic events expire after two minutes.

### 1. Proposed Flow

```text
Finalized Deepgram words
→ existing SpeakerTurnAssembler
→ public SpeakerTurn + backend-only timing observation
→ update session rolling context
→ run deterministic behavioral rules
→ schedule semantic analysis without awaiting it
→ normalize behavioral and semantic results into DetectedEvent
→ retain CUSTOMER_EMOTIONAL_CUE as context/evidence only
→ observe the adviser’s subsequent response
→ emit MISSED_EMOTIONAL_CUE only if the cue was bypassed or ignored
→ apply confidence, focus, cooldown, and repetition rules
→ map the winning actionable event to predefined LiveNudge text
→ send {"type":"live_nudge","nudge":...} over the existing WebSocket
→ show briefly in the meeting UI
```

Each finalized turn continues to reach the frontend as it does today. Coaching failures must never close or delay the transcription stream.

At session start, the frontend sends the selected focus areas over the existing `/ws/transcription` connection before audio begins. The backend creates one session-local coaching state object alongside `SpeakerTurnAssembler`.

### 2. Files

Existing files to modify:

- `backend/requirements.txt`
  - Add and pin the OpenAI Python SDK. It is not currently installed; Pydantic 2.13.5 is already available.

- `backend/app/transcription.py`
  - Pass finalized turns and backend-only word timing into the coaching session.
  - Accept focus configuration.
  - Schedule coaching work outside the Deepgram receive loop.
  - Forward `live_nudge` events and cancel coaching tasks during cleanup.

- `backend/tests/test_transcription.py`
  - Cover coaching integration, session reset, task cleanup, and continued transcription when coaching fails.

- `frontend/src/hooks/useLiveTranscription.ts`
  - Send focus areas, recognize `live_nudge`, expose the current nudge, and clear it after its display period.

- `frontend/src/app/page.tsx`
  - Add lightweight focus selection, active-focus display, and a temporary nudge card.
  - Retain the transcript as a subdued development/debug panel.

New files:

- `backend/app/coaching.py`
  - Canonical backend models, behavioral detection, rolling context, nudge library, cooldown/repetition decisions, and per-session orchestration.

- `backend/app/semantic_analysis.py`
  - OpenAI prompt, structured response model, API adapter, timeout, and error normalization.

- `backend/tests/test_coaching.py`
  - Pure unit tests for behavioral signals, context bounds, prioritization, cooldowns, and nudge mapping.

- `backend/tests/test_semantic_analysis.py`
  - Test schema conversion and failure handling with a fake client; no real API calls.

Do not duplicate `DetectedEvent` in TypeScript. The frontend only needs its existing `SpeakerTurn` and a small `LiveNudge` display type.

### 3. Behavioral Signal Layer

Keep the current public `SpeakerTurn` unchanged. Before Deepgram word data is discarded, create a backend-only observation containing word text, speaker label, start/end times, and the normalized turn.

Initial rules:

- **Speaking pace:** adviser word count divided by the word-span duration.
  - Low: at least 170 WPM but under 10 seconds.
  - Medium: at least 175 WPM for 10–15 seconds.
  - High: at least 175 WPM for 15 seconds or longer.
  - Only high confidence can produce `PACE_SLOW_DOWN`.

- **Long monologue:** continuous finalized adviser speech.
  - Medium at 30 seconds.
  - High at 45 seconds.
  - Treat it as supporting evidence for pace, pauses, and turn-taking rather than inventing another coaching dimension.

- **Response gap:** next-turn start minus prior-turn end.
  - Under roughly 600 ms after a customer turn is supporting evidence.
  - It must not independently trigger `ALLOW_PAUSE`; combine it with the semantic evaluation of the adviser’s response.

- **Possible interruption:** adviser words begin before the customer’s last word ends.
  - Ignore overlaps below roughly 150 ms as noise.
  - One overlap of at least 300 ms: medium.
  - Two such adviser-over-customer overlaps within 120 seconds: high and eligible for `DO_NOT_INTERRUPT`.

- **Talk-time balance:** sum word durations per role over a rolling two-minute window.
  - Evaluate only after at least 60 seconds of usable speech.
  - Adviser share above roughly 70% is supporting evidence, not a standalone nudge.

These are tuning defaults, not scientific claims.

Limitations:

- Single-microphone diarization makes overlap and role attribution approximate.
- The current public turn duration includes silence inside the turn; backend word timings provide a better pace estimate.
- Finalized-turn-only processing cannot coach during an uninterrupted 45-second monologue. Defer periodic checks initially; add a backend-only check of accumulated finalized word segments every 10 seconds only if real testing shows this is a demo blocker.
- Acoustic hesitation, tone, or emotion cannot be measured without prosody and remains out of scope.

### 4. Rolling Context

Maintain one in-memory context per WebSocket session:

- Last 8 finalized turns, capped at approximately 1,200 characters total.
- A one- or two-sentence temporary context summary, capped around 300 characters.
- Behavioral evidence from the last two minutes.
- Last 8 detected events.
- Last 3 displayed nudges with timestamps.
- Selected coaching focus areas.
- A monotonically increasing context version.

On every finalized turn:

1. Append and trim turns.
2. Expire old behavioral evidence.
3. Run behavioral rules.
4. Capture an immutable semantic-analysis snapshot.
5. Retain any `CUSTOMER_EMOTIONAL_CUE` as temporary context for evaluating the adviser’s next response.

Send OpenAI only the selected focus, bounded recent turns with turn IDs and timestamps, relevant recent behavioral evidence, recent event types, recent nudge keys, and the short context summary. Do not send the full transcript or raw audio.

### 5. OpenAI Semantic Analysis

Use `gpt-5.6-luna` with reasoning effort `none` as the initial live-classification model: this is a small, bounded, latency-sensitive classification workload. The current official model documentation identifies Luna for cost-sensitive, high-volume work, supports `none` reasoning and Structured Outputs. If scripted evaluation shows missed nuance, switch only this adapter to `gpt-5.6-terra`. [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

The repository currently has no OpenAI SDK installed. During implementation, pin the then-installed version in `requirements.txt` and use the documented Responses API Structured Outputs helper with a Pydantic model. Official OpenAI documentation supports Pydantic-backed `responses.parse(...)` and `output_parsed`. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Use a response schema such as:

```python
SemanticAnalysisResult:
    context_summary: str
    events: list[SemanticCandidate]

SemanticCandidate:
    area: CoachingArea
    type: SemanticEventType
    confidence: Literal["low", "medium", "high"]
    evidence_turn_ids: list[str]
    evidence: str              # brief reason, no copied quotation
    nudge_key: NudgeKey | None
```

Allowed semantic event types should be closed enums:

- `CLOSED_QUESTION_PATTERN`
- `CUSTOMER_EMOTIONAL_CUE`
- `MISSED_EMOTIONAL_CUE`
- `PREMATURE_PROBLEM_SOLVING`

The backend validates turn IDs, assigns `timestampMs` from the newest evidence turn, and converts candidates into canonical `DetectedEvent` objects.

`CUSTOMER_EMOTIONAL_CUE` is context/evidence only:

1. Detect and retain the customer cue.
2. Wait for the adviser’s response.
3. If the adviser acknowledges or appropriately explores it, emit no actionable event.
4. If the adviser bypasses or ignores it, emit `MISSED_EMOTIONAL_CUE`.
5. Only `MISSED_EMOTIONAL_CUE` is eligible for `ACKNOWLEDGE_EMOTION`.

Prompt responsibilities:

- Analyze only the adviser’s behavior.
- Apply explicit dimension-specific low/medium/high rubrics.
- Distinguish a necessary closed factual question from a missed open-question opportunity.
- Detect explicit versus inferred emotional cues.
- Store emotional cues as context rather than treating them as coaching failures.
- Evaluate the adviser’s subsequent response for acknowledgement or exploration.
- Emit `MISSED_EMOTIONAL_CUE` only when that response clearly bypasses or ignores the cue.
- Check whether the adviser moved into solving before acknowledging or exploring the concern.
- Return no event when evidence is insufficient.
- Select only a permitted `nudgeKey`; never write coaching prose.
- Keep stable instructions before dynamic context to aid caching.

Use `store=False`, no tools, a small output limit, an SDK timeout around four seconds, and no automatic retries in the live path. Because the documented synchronous parse helper is sufficient, run it through `asyncio.to_thread` and wrap it with `asyncio.wait_for`; this avoids assuming an async helper signature and keeps the event loop responsive.

Malformed output, refusal, incomplete output, timeout, rate limit, or network failure produces no semantic event. Log only error metadata—never prompt content or transcript text.

### 6. Nudge Decision Layer

Canonical backend models:

```text
DetectedEvent
- area
- type
- confidence
- timestampMs
- evidence              # temporary
- nudgeKey?

LiveNudge
- area
- nudgeKey
- text
- timestampMs
```

Decision rules:

1. Accept only high-confidence live candidates.
2. Treat `CUSTOMER_EMOTIONAL_CUE` as non-actionable context and reject any nudge attached to it.
3. Discard stale candidates rather than queueing them for later.
4. If several actionable events arrive together, rank selected focus areas first, then direct actionable events over supporting evidence, then newest event.
5. Keep the same high-confidence threshold for selected and non-selected areas initially; focus affects priority, not semantic certainty.
6. Apply a 75-second global cooldown.
7. Suppress the same `nudgeKey` for 180 seconds.
8. During cooldown, discard candidates rather than displaying an outdated nudge later.

Fixed mapping:

```text
FAST_PACE                                 → PACE_SLOW_DOWN
SHORT_RESPONSE_GAP + missed response cue  → ALLOW_PAUSE
INTERRUPTION_PATTERN                      → DO_NOT_INTERRUPT
CLOSED_QUESTION_PATTERN                   → ASK_OPEN_QUESTION
CUSTOMER_EMOTIONAL_CUE                    → no nudge
MISSED_EMOTIONAL_CUE                      → ACKNOWLEDGE_EMOTION
PREMATURE_PROBLEM_SOLVING                 → STAY_BEFORE_SOLVING
```

The server owns the approved text library. An invalid event/key pairing is rejected.

### 7. Frontend Changes

Make the minimum real-screen changes:

- Before starting, show five selectable focus chips; default to one or two existing product priorities.
- Freeze those selections while a meeting is active.
- Replace “Slice 1 / transcription check” language with an active listening/coaching state.
- Show selected focus areas read-only during the meeting.
- Add one calm nudge card using pale indigo, lavender, or light blue, with dark navy text and a subtle indigo accent.
- Avoid warning-like colors or visual urgency; the nudge should feel supportive and consistent with the established mockup.
- Display a nudge for about eight seconds, fade it, then clear it.
- A newer valid nudge may replace the current card, though backend cooldown should make that unusual.
- Keep Start, Stop, microphone state, and current error behavior.
- Retain the transcript below or behind a small “Debug transcript” disclosure; it should not dominate the coaching experience.
- Leave `/mockup` unchanged.

### 8. Session / Error Behavior

A new meeting resets:

- speaker-role mapping and transcript buffers
- focus snapshot
- rolling context and summary
- pending emotional-cue context
- behavioral windows
- detected events
- cooldown and repetition history
- current frontend nudge
- pending and in-flight semantic work

Use a session generation ID so a late result from an old meeting cannot affect a restarted meeting.

Maintain at most one semantic request in flight and one coalesced pending snapshot. If another turn arrives, update context and replace the pending snapshot with the newest version. When the current call finishes, process its still-timely result, then analyze the latest pending snapshot. Do not build an unbounded request queue.

If OpenAI is unavailable or `OPENAI_API_KEY` is missing:

- Continue transcription and behavioral detection.
- Skip semantic analysis.
- Do not send a fatal WebSocket error.
- Log a sanitized backend warning.

Stopping or disconnecting cancels pending tasks and drops all customer conversation state. A semantic timeout or exception never cancels Deepgram, closes the browser connection, or prevents subsequent `SpeakerTurn` events.

### 9. Verification

#### Automated checks

Backend tests should cover:

- Pace boundary cases and adviser-only evaluation.
- Word-timing calculations with internal pauses.
- One overlap versus repeated interruption confidence.
- Talk-time and long-monologue supporting evidence.
- Short response gaps not nudging by themselves.
- Rolling turn, character, event, and time-window bounds.
- `CUSTOMER_EMOTIONAL_CUE` being retained as context but never producing a nudge.
- Appropriate adviser acknowledgement clearing or resolving a pending emotional cue without an actionable event.
- A bypassed or ignored cue producing `MISSED_EMOTIONAL_CUE`.
- Only high-confidence `MISSED_EMOTIONAL_CUE` mapping to `ACKNOWLEDGE_EMOTION`.
- High-only semantic threshold.
- Selected-focus prioritization.
- 75-second global cooldown and 180-second same-key suppression.
- Fixed event-to-nudge mapping and invalid-pair rejection.
- Structured response conversion with server-assigned timestamps.
- Timeout, malformed output, refusal, and API failure returning no events.
- One in-flight plus one latest-pending request.
- Stale result rejection after stop/restart.
- Transcription continuing when coaching raises an exception.
- No transcript text in error logs.

Run:

```bash
cd backend
.venv/bin/python -m compileall app
.venv/bin/python -m unittest discover -s tests

cd ../frontend
npm run lint
npm run build
```

#### Manual tests

Use two people, with the adviser speaking first.

1. **Fast pace**
   - Adviser reads a prepared 55–60-word explanation in about 18 seconds, then pauses.
   - Expect `PACE_SLOW_DOWN`.
   - Repeat slowly; expect no new pace nudge.

2. **Closed versus open question**
   - Customer: “I’m not sure what I can afford.”
   - Adviser asks several narrow questions: “Is your income fixed?” and “Do you have savings?”
   - Expect `ASK_OPEN_QUESTION` only when the context indicates a missed opportunity, not for one necessary factual question.
   - Repeat with “What feels most uncertain for you?”; expect no nudge.

3. **Emotional cue acknowledged**
   - Customer: “I’m scared I might lose the house.”
   - Before the adviser responds, expect no nudge from the cue alone.
   - Adviser: “That sounds frightening. What part feels most urgent right now?”
   - Expect no `ACKNOWLEDGE_EMOTION` nudge.

4. **Emotional cue missed**
   - Customer: “I’m scared I might lose the house.”
   - Before the adviser responds, expect no nudge.
   - Adviser: “What is the remaining mortgage balance?”
   - Expect `MISSED_EMOTIONAL_CUE` followed by `ACKNOWLEDGE_EMOTION`.

5. **Immediate problem-solving**
   - Customer: “Since my partner died, handling all of this has felt overwhelming.”
   - Adviser: “We can move the money into these three products.”
   - Expect `STAY_BEFORE_SOLVING`.

6. **Cooldown and repetition**
   - Trigger `ACKNOWLEDGE_EMOTION` through a missed emotional cue, then deliberately trigger a closed-question event within 20 seconds.
   - Expect only the first nudge.
   - After 80 seconds, trigger a different high-confidence event; expect it.
   - Trigger the original nudge again before 180 seconds; expect suppression.
   - Start a new meeting and repeat; expect cooldown history to be cleared.

### 10. Risks / Uncertainties

- Single-microphone diarization may misattribute pace or interruptions; overlap-based coaching requires real-room tuning.
- Finalized transcript and nudge appearance can sometimes have noticeable latency because live coaching operates on finalized Deepgram turns; tune endpointing/latency only if it becomes a demo blocker.
- The quality difference between Luna and Terra for subtle emotional-cue classification needs evaluation with the scripted scenarios.
- Deepgram word timestamps indicate recognized word spans, not exact conversational intent; interruption thresholds will remain approximate.
- “Open question opportunity” is context-dependent, so the prompt must avoid criticizing necessary compliance or factual questions.
- OpenAI account access to the recommended model must be confirmed during implementation; model availability is not established by repository state.

### 11. Implementation Order

1. Add canonical coaching contracts, nudge library, and pure decision tests.
2. Add backend-only timed turn observations and behavioral rule tests.
3. Add bounded rolling context, pending emotional-cue handling, and per-session reset behavior.
4. Install and pin the OpenAI SDK; implement the structured semantic adapter with mocked tests.
5. Integrate coaching asynchronously into the existing transcription WebSocket.
6. Add focus selection and the calm indigo/lavender temporary nudge UI; keep the debug transcript secondary.
7. Run backend checks and frontend lint/build.
8. Perform the six two-person scripts and tune only thresholds, timeout, or model choice supported by observed results.

## Slice 3 — Post-Meeting Report + Reflection

**Status:** Implemented — pending manual verification

**Implementation deviation:** The approved OpenAI/Terra plan was migrated for the hackathon to OpenRouter with `google/gemini-2.5-flash` for live semantic analysis, report generation, and reflection. OpenRouter's OpenAI-compatible Chat Completions endpoint with strict JSON Schema replaces `responses.parse(...)`; the Pydantic contracts, timeouts, and temporary-data lifecycle are unchanged.

### 1. End-to-End Flow

1. The adviser presses **End meeting**.
2. The frontend immediately stops showing the live transcript and nudge, switches to a post-meeting preparation screen, stops `MediaRecorder`, sends its final audio chunk, and then sends the existing `stop` WebSocket message.
3. The backend sends Deepgram `Finalize`, waits for final results using the existing bounded finalization behavior, flushes `SpeakerTurnAssembler`, passes every flushed observation through `CoachingSession.observe()`, freezes the coaching session, copies the completed transcript, focus areas, events, and nudges into an immutable completed-meeting snapshot, stores that snapshot under a server-generated UUID, and sends `session.stopped` with that session ID.
4. The frontend receives `session.stopped`, transitions from `finalizing` to `preparing_report`, and calls the report HTTP endpoint.
5. The report endpoint retrieves the snapshot, runs structured post-meeting analysis, validates and caches the result, then returns only the adviser-facing report.
6. The frontend shows the concise report with **Reflect** and **Finish**.
7. **Finish** calls the cleanup endpoint, clears all client meeting state, and returns to the initial screen.
8. **Reflect** opens a short free-text conversation with the static first coach message: “How do you think the meeting went?”
9. Exactly two adviser replies are accepted: reply one produces one focused follow-up question; reply two produces a short closing response and one takeaway.
10. Finish after reflection uses the same cleanup endpoint and returns to the initial screen.

The UI never returns to the stopped live-meeting layout.

### 2. Session Data Design

`sessionTurns` already preserves final turns on the frontend, including turns received during finalization. It is useful as a temporary client mirror, but it is not sufficient as the authoritative Slice 3 snapshot because it does not contain selected focus, behavioral events, semantic events, or nudge history. Posting the transcript back from the browser would also be unnecessary.

The authoritative completed snapshot should live in backend memory:

```text
CompletedMeetingSnapshot
- session_id: UUID
- created_at
- turns: immutable tuple of every finalized SpeakerTurn
- selected_focus: immutable tuple of CoachingArea
- behavioral_events: immutable tuple of DetectedEvent
- semantic_events: immutable tuple of DetectedEvent
- nudges: immutable tuple of LiveNudge
```

A mutable post-meeting holder may wrap the immutable snapshot:

```text
PostMeetingSession
- snapshot
- report: PostMeetingReport | None
- reflection_context: str | None
- reflection_messages: bounded list
- processed_reflection_requests: messageId → response
- reflection_reply_count: 0..2
- per-session async lock
- expiry handle
```

`CoachingSession` currently retains only a bounded rolling context: eight events, three nudges, and recent turns. Slice 3 should add separate meeting-lifetime history lists while leaving the live rolling limits and two-minute event expiry unchanged. Expired live events can therefore inform the report without being reintroduced into live semantic context.

Final-turn handling:

1. Deepgram finalization completes or reaches its existing timeout.
2. `assembler.flush_observations()` emits any remaining finalized turn.
3. Each observation is recorded synchronously by `CoachingSession`.
4. The coaching session is closed/frozen.
5. Only then is the completed snapshot copied into the post-meeting store.
6. Only after storage succeeds is `session.stopped` sent.

Each WebSocket gets a new UUID generated by the backend. Report and reflection calls must address that exact UUID. Starting a new meeting therefore cannot select an older snapshot.

Late-safety measures:

- Closing/freezing `CoachingSession` retains the existing `_closed` check and cancels pending semantic work.
- Snapshot fields are immutable copies, not references to rolling deques.
- Report/reflection results are stored only if the same session record still exists.
- The frontend compares every HTTP result with its current session ID and request generation before applying it.
- Aborted or late responses from an old meeting cannot change a new meeting’s state.

### 3. Files

Existing files to modify:

- `backend/app/main.py`
  - Register the post-meeting HTTP router.

- `backend/app/coaching.py`
  - Retain complete meeting-lifetime turn, event, and nudge histories separately from bounded live context.
  - Add an idempotent freeze/export operation.

- `backend/app/transcription.py`
  - Generate a session UUID.
  - Include it in `session.ready` and `session.stopped`.
  - After final flushing, freeze and register the completed snapshot before sending `session.stopped`.

- `backend/tests/test_coaching.py`
  - Cover complete history, freezing, and rejection of late semantic mutations.

- `backend/tests/test_transcription.py`
  - Verify the final flushed turn enters the registered snapshot and that stopped messages identify the correct session.

- `frontend/src/hooks/useLiveTranscription.ts`
  - Parse the session ID.
  - Expose the completed session ID and a method that clears all retained meeting state after cleanup.
  - Preserve the current immediate live-content clearing behavior.

- `frontend/src/app/page.tsx`
  - Add the small end-to-end state machine, report request/retry, report UI, bounded reflection UI, and Finish cleanup.
  - Reuse the established mockup’s visual direction without importing mock data.

New files:

- `backend/app/post_meeting.py`
  - Completed-session store, expiry, Pydantic contracts, OpenAI report/reflection adapters, prompt construction, HTTP endpoints, locking, idempotency, and cleanup.

- `backend/tests/test_post_meeting.py`
  - Focused service and endpoint tests with fake OpenAI responses.

No dependency changes are needed: the installed backend already has `openai==3.16.2` and Pydantic 2.13.5. Do not modify global routing, package files, or `/mockup`.

### 4. Post-Meeting Analysis

Use `gpt-5.6-terra` for post-meeting analysis. It is positioned as the balanced intelligence/cost model, supports the Responses API and Structured Outputs, and is appropriate for a low-frequency task where nuance matters more than live latency. [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)

The installed OpenAI SDK supports native asynchronous `responses.parse(...)` with a Pydantic `text_format`. Use `AsyncOpenAI` directly rather than a worker thread. Official OpenAI documentation recommends Structured Outputs over unconstrained JSON where supported. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Public contract:

```text
PostMeetingReport
- strengths: list[str]          # 1–2 items; each ≤180 characters
- improvements: list[str]       # 1–2 items; each ≤180 characters
- focus_summary: str            # ≤220 characters
- takeaway: str                 # ≤160 characters
```

The model’s internal structured result may additionally include:

```text
- reflection_context: str       # ≤600 characters; never returned in the report API
```

This gives reflection a bounded, generic adviser-behavior context without repeatedly supplying the full transcript. It remains temporary and must contain no quote or customer summary.

Report context supplied:

- every finalized speaker turn, including the final flush;
- authoritative speaker roles, turn IDs, and timestamps;
- selected coaching focus areas;
- complete behavioral event history;
- complete accepted semantic event history;
- complete displayed-nudge history.

Prompt responsibilities:

- Evaluate adviser behavior across all five dimensions.
- Prioritize selected focus areas without ignoring clear learning elsewhere.
- Choose only the one or two most useful strengths and improvements.
- Use supportive, qualitative, actionable language.
- Coach the adviser, not the customer.
- Do not produce scores, rankings, customer summaries, customer quotations, financial advice, or unsupported claims.
- Make `focus_summary` connect selected focus with this meeting.
- Make `takeaway` one concise action the adviser can carry forward.
- Produce a generic, quote-free `reflection_context`.

API configuration:

- `model="gpt-5.6-terra"`
- `reasoning={"effort": "low"}`
- `store=False`
- no tools
- `max_output_tokens` around 800
- SDK timeout around 12 seconds
- outer application timeout around 15 seconds
- `max_retries=0`; user-triggered Retry is clearer than hidden long retries

Pydantic constraints and an additional post-validation step should reject empty strings, excess items, and overlong content.

A refusal, `output_parsed is None`, incomplete response, schema error, timeout, rate limit, or network error must leave the snapshot intact, leave `report` uncached, return a stable generic failure response, and log only error type/status metadata rather than transcript or prompt text.

A successful report is cached in the temporary session so duplicate requests and frontend retries do not cause another model call.

### 5. Reflection

Use the same `gpt-5.6-terra` model. One model is sufficient for both post-meeting tasks and avoids another configuration path. Reflection can use `reasoning={"effort": "none"}` because it is a short, tightly prompted coaching response.

Context should contain only:

- selected focus areas;
- the structured report;
- the bounded internal `reflection_context`;
- reflection messages from this session.

Do not resend the complete transcript during reflection. The post-meeting analysis has already converted it into bounded coaching context, reducing cost and repeated exposure of customer content.

The first coach message is static and therefore requires no API call:

> How do you think the meeting went?

Completion is deterministic, not model-decided:

1. First adviser message:
   - maximum 800 trimmed characters;
   - model uses a `ReflectionFollowUp` schema containing one short `coach_message`;
   - server returns `complete: false`;
   - prompt requires one focused question that helps the adviser notice or articulate something beyond merely repeating the report.
2. Second adviser message:
   - model uses a `ReflectionCompletion` schema containing `coach_message` and `takeaway`;
   - server returns `complete: true`;
   - `takeaway` is capped at about 160 characters and should capture the adviser’s stated intention in practical language.
3. A third adviser message receives `409 reflection_complete`; the input is already disabled in the UI.

This gives exactly two adviser/coach exchanges after the initial question, fitting the requested 60–90-second experience.

Each request includes a client-generated `messageId`. The backend stores a response against that ID only after successful model output. Retrying the same request returns the prior response without incrementing the exchange count.

Reflection failure does not append or count the failed exchange on the backend, does not remove the report, leaves the adviser’s draft/message available for Retry, shows a restrained error with Retry, Back to report, and Finish, and never strands the adviser or replaces the report.

Normal reflection shows Finish only once the takeaway is complete. Failure provides Finish as the escape path required by the product.

### 6. Backend API / Message Flow

WebSocket changes:

```json
{
  "type": "session.ready",
  "sessionId": "uuid"
}
```

Existing client messages remain:

```json
{
  "type": "session.configure",
  "focusAreas": ["acknowledging_emotional_cues"]
}
```

```json
{
  "type": "stop"
}
```

After finalization and snapshot registration:

```json
{
  "type": "session.stopped",
  "sessionId": "same-uuid"
}
```

HTTP endpoints:

```text
POST /post-meeting/{session_id}/report
```

No request body. It retrieves the finalized snapshot, serializes report context, and returns a cached report or generates and caches one through the session lock.

Success:

```json
{
  "report": {
    "strengths": ["..."],
    "improvements": ["..."],
    "focus_summary": "...",
    "takeaway": "..."
  }
}
```

```text
POST /post-meeting/{session_id}/reflection
```

Request:

```json
{
  "messageId": "uuid",
  "message": "Free-text adviser reflection"
}
```

Response after the first adviser message:

```json
{
  "coachMessage": "...?",
  "complete": false,
  "takeaway": null
}
```

Response after the second:

```json
{
  "coachMessage": "...",
  "complete": true,
  "takeaway": "..."
}
```

```text
DELETE /post-meeting/{session_id}
```

It deletes transcript, observations, events, nudges, report, reflection context, messages, cached request results, and expiry metadata; returns `204`; and is idempotent so an already-deleted or expired session also returns `204`.

Error responsibilities:

- `404/410`: session missing or expired; UI offers Finish/start over.
- `409`: report not ready, reflection already complete, or invalid lifecycle transition.
- `422`: empty/overlong adviser message or no usable finalized transcript.
- `503`: OpenAI unavailable, refused, malformed, or timed out.
- Responses contain friendly stable messages/codes, never raw provider errors.

### 7. Frontend State / UI

Keep state local to the root page and existing transcription hook. Do not add routing or global state.

High-level phase:

```text
idle
→ starting
→ listening
→ finalizing
→ preparing_report
→ report
→ reflection
→ finishing
→ idle
```

Add `report_error` as a recoverable branch from `preparing_report`. The existing hook’s `requesting`, `connecting`, `listening`, `stopping`, and error statuses remain transport-level details.

Minimum UI changes:

- **Finalizing/preparing:** Replace the meeting UI immediately with one calm loading card. Initially say “Finalizing the last words…”, then “Preparing your feedback…”.
- **Report:** Reuse the mockup’s pale blue/lavender cards, large typography, and generous spacing: What went well with one or two short items, Try next time with one or two short items, compact focus summary and takeaway, and Reflect and Finish buttons.
- **Report error:** Short neutral message with Retry and Finish.
- **Reflection:** Use the mockup-style chat layout, but with only coach/adviser messages, a free-text input and Send, no chips/presets/multiple choice, a final takeaway card, Back to report, and Finish after completion or on failure.
- **Finish:** Disable duplicate actions while cleanup runs. On `204`, clear report, reflection, session ID, `sessionTurns`, errors, and request controllers before returning to idle.

Focus selections may remain because they are adviser configuration, not customer content. Starting a meeting still clears all prior completed-session UI state.

### 8. Privacy Lifecycle

During the live meeting, customer content exists only in Deepgram’s active stream, WebSocket/session-local assembler buffers, `CoachingSession` rolling and meeting histories, temporary frontend `turns` and `sessionTurns`, and in-flight live OpenAI requests.

At End meeting, visible `turns` and `currentNudge` clear immediately; `sessionTurns` remains temporarily so the existing final-turn hardening is preserved; the backend creates the completed snapshot only after final flush; and live assembler and coaching objects are then closed.

During report/reflection, customer-specific state exists only in the in-memory post-meeting session and bounded in-flight OpenAI requests using `store=False`. Nothing is written to disk or Supabase.

On direct Finish or Finish after reflection:

1. `DELETE` removes the backend record.
2. Any associated expiry handle and active session work are cancelled where possible.
3. The frontend clears the session ID, transcript mirror, report, reflection messages, takeaway, and errors.
4. The application returns to idle.

Additional safety:

- Every completed session expires after 30 minutes; expired records are purged on store access, covering abandoned tabs without a dedicated scheduler.
- Backend restart clears the in-memory store.
- Unexpected WebSocket disconnect does not create a completed snapshot.
- Starting a new meeting always receives a new UUID.
- Deletion never reintroduces data if a late report/reflection response arrives.
- Slice 3 retains no adviser takeaway or other learning persistently; that remains Slice 4 work.

### 9. Verification

Backend automated checks:

- Final Deepgram flush is observed before snapshot creation.
- The final flushed turn appears exactly once in the completed snapshot.
- Complete event and nudge histories remain available even after live rolling-context expiry.
- Report payload contains finalized turns, selected focus, behavioral events, semantic events, and shown nudges.
- Structured report parsing and conversion enforce one-to-two concise items.
- Refusal, malformed output, timeout, and API failure leave the snapshot retryable.
- Duplicate report requests return the cached result.
- Reflection context excludes the full transcript and remains within its limits.
- Reflection message length and message count are bounded.
- First reply returns a follow-up; second returns completion with exactly one takeaway.
- A third reply is rejected.
- Retrying one `messageId` does not duplicate an exchange.
- Reflection failure does not advance the count or remove the report.
- Finish removes all temporary state and is idempotent.
- A new session UUID cannot access an older snapshot.
- A late semantic result cannot mutate a frozen snapshot.
- A late report/reflection result cannot recreate a deleted session.
- No real OpenAI calls; use fake `responses.parse` clients.

Implementation verification commands:

```bash
cd backend
.venv/bin/python -m compileall app
.venv/bin/python -m unittest discover -s tests

cd ../frontend
npm run lint
npm run build
```

Short manual test:

1. Start a meeting with emotional cues and staying-before-solving selected.
2. Daniel: “What would be most helpful to talk through today?”
3. Samantha: “I’m worried my mortgage may become unaffordable.”
4. Daniel moves quickly to an option or product.
5. Samantha adds that the uncertainty is difficult.
6. Daniel acknowledges it and asks what feels most uncertain.
7. Press End meeting immediately after Daniel’s last sentence.
8. Confirm the live transcript/nudge disappear and preparation UI appears.
9. Confirm the final sentence contributes to the report.
10. Confirm the report has concise strengths and improvements, no quote, summary, or score.
11. Click Reflect.
12. Enter: “I moved to options too quickly.”
13. Answer the coach’s one follow-up: “Next time I’ll pause and acknowledge the concern first.”
14. Confirm the input closes and exactly one takeaway appears.
15. Finish and confirm all meeting-specific UI disappears.
16. Start another meeting and confirm there is no old transcript, report, nudge, reflection, or cooldown state.

### 10. Risks / Uncertainties

- Account access to `gpt-5.6-terra` is not established by repository state; implementation should confirm it before manual testing.
- In-memory sessions are intentionally single-process and disappear on backend reload. That is acceptable for the local hackathon but means an active post-meeting flow cannot survive a restart.
- Single-microphone diarization errors can cause incorrect adviser/customer attribution and therefore misleading report feedback.
- Finalization plus report generation creates two sequential waits. The preparation UI and bounded timeouts are important for the demo experience.
- Even with explicit prompting, generated feedback could occasionally include an overly specific paraphrase. Scripted evaluation should check the no-quote/no-customer-summary boundary.
- A very long meeting increases model input cost because report generation intentionally uses the complete finalized transcript.

### 11. Implementation Order

1. Add meeting-lifetime histories and freeze/export behavior to `CoachingSession`, with tests.
2. Add the in-memory completed-session store, immutable snapshot, expiry, and cleanup behavior.
3. Update the transcription WebSocket to issue session IDs and register the snapshot after final flush.
4. Implement structured report generation and its fake-client tests.
5. Implement the two-turn, idempotent reflection service and tests.
6. Register the three HTTP endpoints and cover lifecycle/error responses.
7. Extend the transcription hook with completed-session identity and cleanup.
8. Replace the stopped live state with preparation, report, failure, reflection, and Finish views in the root page.
9. Run backend checks plus frontend lint/build.
10. Perform the short Daniel/Samantha end-to-end test and tune only prompt wording, output limits, or timeout values supported by observed behavior.
