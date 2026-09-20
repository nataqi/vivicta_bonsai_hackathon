# AI Compassion Coach

Hackathon prototype of a private AI coaching assistant for customer-facing financial advisers. It listens during difficult or emotionally sensitive customer conversations, offers selective live nudges, and turns each meeting into concise feedback and generic adviser learning.

> Remember the learning, forget the customer conversation.

## Product flow

```text
Choose coaching focus
→ Start a live meeting
→ Receive selective coaching nudges
→ Review post-meeting feedback
→ Optionally reflect with the coach
→ Carry generic adviser learning into the next meeting
```

The MVP coaches how the adviser communicates across five dimensions:

1. Pace & pauses
2. Turn-taking & interruptions
3. Open questions
4. Acknowledging emotional cues
5. Stay with the customer before solving

Audio, transcript, customer details, and exact meeting moments are temporary session data. SQLite stores only canonical, generic adviser-learning fields.

## Stack

- Next.js, React, TypeScript, and Tailwind CSS
- FastAPI and WebSockets
- Deepgram for streaming transcription and speaker separation
- OpenRouter with `google/gemini-2.5-flash` for semantic coaching and post-meeting generation
- SQLite for automatic local adviser-learning persistence

The root route is the real MVP. `/mockup` remains an isolated frontend-only reference route.

## Local setup

Clone the repository, then create the backend environment:

```bash
git clone <repository-url>
cd vivicta_finance/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the example environment file and add the two required credentials:

```bash
cp ../.env.example .env
```

```text
DEEPGRAM_API_KEY=...
OPENROUTER_API_KEY=...
```

Start FastAPI on port 8001:

```bash
uvicorn app.main:app --reload --port 8001
```

In another terminal, install and start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). If port 3000 is occupied, use the alternate local URL printed by Next.js.

SQLite creates `backend/data/adviser_learning.db` automatically. It needs no credentials, server, or migration step.

## Checks

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

Architecture and technology decisions are documented in `docs/architecture.md` and `docs/tech-stack.md`.
