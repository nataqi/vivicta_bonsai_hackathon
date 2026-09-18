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

### Fallback

AssemblyAI may be used as a fallback if Deepgram causes implementation or diarization issues.

The MVP should not integrate both unless necessary.

---

## AI / LLM

### OpenAI

OpenAI models are used for semantic analysis and coaching.

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

## Database

### Supabase / PostgreSQL

Supabase is used for persistent adviser learning.

Responsibilities:

- selected coaching focus areas
- generic strengths
- generic improvement patterns
- reflection takeaways
- progress history
- adviser coaching memory

Supabase should not store:

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
- rolling context
- customer-specific information
- detected meeting events
- detailed behavioral measurements
- temporary post-meeting analysis
- raw audio where applicable

For the MVP, this may be held in application memory or another simple ephemeral session mechanism.

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
OpenAI
Supabase
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
- AssemblyAI as fallback only

AI
- OpenAI

Persistent Storage
- Supabase
- PostgreSQL

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