# Implementation Plan

This document is the single source of truth for approved implementation plans. Each approved slice is appended here, then updated only for status and material implementation deviations discovered during implementation.

## Slice 1 — Live Transcription

**Status:** Complete

**Manual verification:** Real browser microphone streaming works; finalized transcript turns appear during the live session; immediate Stop flushes the final phrase; and session cleanup and restart work correctly. Two-person speaker diarization works, though speaker separation was somewhat inconsistent across attempts and remains a known MVP limitation.

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
