# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md` holds the product principles, privacy rules, and working guidelines. `docs/architecture.md` is the source of truth for system design and `docs/tech-stack.md` for technology choices; update those rather than adding new docs.

## Commands

Backend (FastAPI, run from `backend/`; the README setup uses a `.venv` there, and `.env` with `DEEPGRAM_API_KEY` and `OPENROUTER_API_KEY` must exist because `app.main` reads `DEEPGRAM_API_KEY` at import):

```bash
uvicorn app.main:app --reload --port 8001
python -m compileall app
python -m unittest discover -s tests
python -m unittest tests.test_coaching                          # one module
python -m unittest tests.test_coaching.SomeTestCase.test_name   # one test
```

Frontend (Next.js, run from `frontend/`):

```bash
npm ci
npm run dev      # http://localhost:3000
npm run lint
npm run build    # uses --webpack
```

Pre-commit sanity check from the repo root: `git diff --check`.

## Architecture

Two processes: a FastAPI backend on port **8001** and a Next.js frontend on 3000. The frontend hardcodes `http://localhost:8001` / `ws://localhost:8001` (in `frontend/src/app/page.tsx` and `frontend/src/hooks/*`), and backend CORS allows only localhost:3000/3001. `/` is the real MVP; `/mockup` is an isolated frontend-only reference and does not talk to the backend.

Backend modules in `backend/app/`, in the order data flows through them:

- `transcription.py` — WebSocket `/ws/transcription` streams mic audio to Deepgram (nova-3, diarization). `SpeakerTurnAssembler` buffers finalized words and emits speaker turns only at Deepgram turn boundaries (first speaker = adviser, everyone else = customer). `/ws/reflection-dictation` is a separate, non-diarized Deepgram socket used only for reflection voice input.
- `coaching.py` — deterministic behavioral signals (pace, pauses, interruptions, talk-time, monologues), rolling context, the nudge decision layer (confidence gating, focus priority, cooldown, repeat suppression), and the fixed nudge-text library. The LLM only picks a `nudgeKey`; the text is predefined.
- `semantic_analysis.py` / `openrouter.py` — event-driven semantic analysis after each finalized turn via OpenRouter (`google/gemini-2.5-flash`) through the `openai` SDK, returning structured output. Uses `OPENROUTER_API_KEY`, not any OpenAI key.
- `post_meeting.py` — in-memory `PostMeetingStore` holding the completed meeting snapshot; REST endpoints `/post-meeting/{id}/report`, `/reflection`, and `DELETE`. Sessions expire after 30 minutes lazily on store access (no scheduler). Reflection generation must not receive the full transcript, only focus, the generated report, and bounded generic context.
- `adviser_learning.py` — SQLite persistence (`backend/data/adviser_learning.db`, auto-created, path override via `ADVISER_LEARNING_DB_PATH`) and endpoints `/adviser-learning/home`, `/adviser-learning/focus`, `/post-meeting/{id}/complete`. Stores only canonical coaching-area fields for a single stable demo adviser; recurrence, progress, and the Home insight are derived deterministically from the last five records rather than stored as prose.

Everything is keyed on the five `CoachingArea` enum values in `coaching.py`; new analysis, nudges, and learning must map to them, with no numeric empathy scores.

Privacy invariant that spans modules: audio, transcripts, rolling context, and customer-specific details live only in memory for the session and the post-meeting store, and are cleared on stop, failure, reset, or finish. Only generic adviser-learning fields may reach SQLite. Never log or persist transcript content.

## Frontend notes

`frontend/AGENTS.md` warns that this Next.js (16.x) and React 19 differ from older versions; read the relevant guide in `frontend/node_modules/next/dist/docs/` before writing Next-specific code. `frontend/CLAUDE.md` imports the root `AGENTS.md`. UI direction (light theme only, large type, no red styling for coaching feedback, no dense dashboards) is in `docs/ui-guidelines.md`. The main screen state machine and API calls are in `frontend/src/app/page.tsx`; mic/WebSocket handling is in `frontend/src/hooks/useLiveTranscription.ts` and `useReflectionDictation.ts`.
