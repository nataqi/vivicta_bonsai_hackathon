# Tech Stack

## Overview

The project uses a lightweight web stack optimized for a hackathon prototype.

The architecture separates the user interface from the application logic:

- the frontend handles the meeting experience and UI
- the backend owns coaching logic, AI calls, session state, and persistence
- external services handle transcription, semantic analysis, and persistent adviser learning

The goal is to keep the stack simple, understandable, and fast to implement.

---

## Frontend

### React

Used for the application UI.

Main responsibilities:

- Home / Progress screen
- Meeting screen
- Post-meeting report
- Reflection chat
- Displaying live nudges
- Capturing microphone input

### Next.js

Used as the frontend framework.

Reasons:

- React-based structure
- easy local development
- convenient routing
- good TypeScript support
- straightforward integration with the FastAPI backend

The frontend should remain relatively thin.

Business logic should live primarily in the backend.

### TypeScript

Used throughout the frontend.

Reasons:

- typed data structures
- clearer API contracts
- safer handling of meeting events and AI responses
- easier maintenance during rapid development

### Tailwind CSS

Used for styling.

The UI should remain lightweight and functional.

The hackathon prototype does not require a complex design system.

---

## Backend

### Python

Python is the primary backend language.

Most application logic should live in Python.

This includes:

- meeting session state
- behavioral signal calculations
- rolling context
- semantic analysis orchestration
- live nudge logic
- post-meeting analysis
- reflection coaching
- adviser-learning extraction
- persistence logic

### FastAPI

FastAPI is used as the backend framework.

Reasons:

- lightweight
- fast to develop
- strong Python typing support
- good WebSocket support
- convenient async APIs
- suitable for streaming and AI workflows

The FastAPI backend should act as the main application brain rather than being only a thin API wrapper.

### WebSockets

WebSockets are used for real-time communication between the frontend and backend.

Possible real-time messages include:

- finalized speaker turns
- detected coaching events
- behavioral metrics
- live nudges
- meeting state updates

The exact message schema can evolve during implementation.

---

## Speech-to-Text

### Deepgram

Deepgram is the primary speech-to-text provider.

Responsibilities:

- streaming transcription
- speaker diarization
- timestamps
- finalized speaker turns
- endpoint / turn detection

The live transcription output is normalized by the backend into the application's internal `SpeakerTurn` representation.

Deepgram was chosen because it fits the real-time meeting architecture well and offers low integration overhead.

Deepgram is the only transcription provider integrated in the MVP. AssemblyAI is
not integrated; it was only a historical fallback consideration.

---

## AI / LLM

### OpenRouter / Google Gemini

Application LLM access uses OpenRouter with `google/gemini-2.5-flash` for live
semantic analysis, post-meeting reports, and reflection. The backend uses
OpenRouter's OpenAI-compatible Chat Completions API with strict JSON Schema
structured outputs.

The endpoint is `https://openrouter.ai/api/v1` and the required credential is
`OPENROUTER_API_KEY`. The Python `openai` package is retained as the client SDK
for this compatible endpoint; it does not mean the application calls direct
OpenAI services or uses `OPENAI_API_KEY`.

OpenRouter is an additional processor/router for temporary conversation data.
The application keeps customer conversation data in temporary in-memory session
state and does not intentionally persist it.

Main responsibilities:

- open vs closed question classification
- emotional cue detection
- acknowledgement detection
- premature problem-solving detection
- structured semantic event output
- post-meeting analysis
- reflection coaching
- adviser-learning extraction

During live meetings, the model should return structured outputs rather than unrestricted prose wherever possible.

Example output concepts include:

- coaching area
- event type
- confidence
- supporting evidence
- nudge key

The model should not generate arbitrary live coaching messages.

Live nudge text should primarily come from the predefined application nudge library.

---

## Voice Replay

### ElevenLabs

Used only in the post-meeting "key moment" replay. The report picks one adviser
turn; the adviser hears their own recorded turn, then an AI-written better answer
spoken in a temporary instant clone of their own voice. The required credential is
`ELEVENLABS_API_KEY`; the backend calls the ElevenLabs REST API with `httpx`, so
the key never reaches the browser. Without a key, or if cloning fails or too
little adviser speech was captured, the better take falls back to a neutral
premade voice (`ELEVENLABS_NEUTRAL_VOICE_ID` can override it).

Privacy rules:

- The full meeting recording stays in the browser only; the backend never stores audio.
- Only adviser speech is used for the voice sample. Customer speech is never
  replayed or sent to ElevenLabs.
- ElevenLabs is an additional processor for the adviser's voice sample and the
  better-answer text. That text is a generic paraphrase-based suggestion, not a
  customer quote.
- The cloned voice is deleted at the provider on Finish, on cleanup, or when the
  post-meeting session is dropped. The Finish receipt only claims deletion the
  provider confirmed.

---

## Database

### SQLite

Python's built-in `sqlite3` module is used for persistent adviser learning.
SQLite was chosen for the localhost hackathon MVP to provide persistent adviser
learning with zero external database setup for teammates. The backend creates
`backend/data/adviser_learning.db` and its two tables automatically.

Responsibilities:

- selected coaching focus areas
- canonical strength and improvement areas
- optional canonical reflection takeaway area
- bounded adviser learning history

The application derives recurrence, qualitative progress, and the Home insight
from at most five recent valid records; generated insight prose is not stored.
No database credentials or external migration step is required.

SQLite should not store:

- raw audio
- full transcripts
- customer identifiers
- customer-specific conversation summaries
- exact customer quotes

Customer conversation data is temporary session data and should be deleted after the immediate coaching workflow is complete.

---

## Temporary Session State

Temporary meeting data should remain outside normal persistent adviser storage.

This includes:

- live transcript
- meeting audio while it is being streamed
- rolling context
- customer-specific information
- reflection dictation audio and intermediate transcript
- detected meeting events
- detailed behavioral measurements
- temporary post-meeting analysis
- raw audio where applicable

For the MVP, this may be held in application memory or another simple ephemeral session mechanism.

Live session state clears on stop, failure, and reset. Post-meeting in-memory
state is removed on Finish/completion or explicit cleanup. Abandoned post-meeting
sessions expire after 30 minutes when the store is accessed; there is no general
background deletion scheduler.

Do not introduce additional infrastructure unless needed.

---

## Local Development and Hosting

### Localhost

The MVP is intended to run locally.

A production hosting setup is not required for the hackathon.

The full demo should be able to run from a developer machine using localhost.

Typical setup:

```text
Frontend:
Next.js development server

Backend:
FastAPI development server

External services:
Deepgram
OpenRouter / Google Gemini

Local persistence:
SQLite (`backend/data/adviser_learning.db`)
```

Hosting or deployment may be added later if time allows, but it is not part of the required MVP.

Avoid spending hackathon time on deployment before the end-to-end product works reliably.

---

## Prosody / Voice-Emotion Analysis

True acoustic prosody analysis is not part of the MVP.

A provider such as Hume may be explored only as a stretch goal if the core product is already working.

Possible additional signals could include:

- hesitation
- vocal tension
- warmth
- pitch variation
- emotional expression

Adding a prosody provider would introduce another external destination for raw customer audio and therefore additional privacy and integration complexity.

---

## Stack Summary

```text
Frontend
- React
- Next.js
- TypeScript
- Tailwind CSS

Backend
- Python
- FastAPI
- WebSockets

Speech-to-Text
- Deepgram
- no secondary transcription provider integrated

AI
- OpenRouter / Google Gemini

Voice Replay (post-meeting only)
- ElevenLabs instant voice clone and text-to-speech

Persistent Storage
- Python `sqlite3`
- local SQLite file

Temporary Meeting State
- Backend application memory / ephemeral session state

Hosting
- Localhost for MVP
- Deployment optional if time allows

Stretch Goal
- Prosody / voice-emotion analysis
```

---

## Implementation Principles

1. Keep the architecture proportional to a hackathon prototype.
2. Put application and coaching logic in the FastAPI backend.
3. Keep the frontend focused on interaction and presentation.
4. Prefer structured AI outputs.
5. Prefer deterministic rules where deterministic logic is sufficient.
6. Keep customer conversation data temporary.
7. Persist adviser learning, not customer conversation history.
8. Avoid unnecessary infrastructure.
9. Do not integrate multiple providers for the same capability unless needed.
10. Make the local end-to-end demo reliable before considering deployment or stretch goals.
