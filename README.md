# AI Compassion Coach

Hackathon prototype of an AI coaching assistant for customer-facing financial advisers.

The system listens to customer conversations, provides minimal live coaching nudges, and supports short post-meeting reflection to help advisers improve communication over time.

## Core Flow

1. Adviser starts a meeting and confirms coaching focus.
2. Live conversation is transcribed and analysed.
3. Short coaching nudges appear only when useful.
4. After the meeting, the adviser receives a concise coaching report.
5. The adviser may complete a short reflection conversation.
6. Generic adviser learning is retained for future coaching sessions.

The system follows the principle:

> Remember the learning, forget the customer conversation.

## Tech Stack

Frontend:

- React
- Next.js
- TypeScript
- Tailwind CSS

Backend:

- Python
- FastAPI
- WebSockets

Services:

- Deepgram — streaming speech-to-text
- OpenAI — semantic analysis and coaching
- Supabase / PostgreSQL — persistent adviser learning

See [`docs/tech-stack.md`](docs/tech-stack.md) for details.

## Architecture

See [`docs/architecture.md`](docs/architecture.md).

## Development

The MVP is designed to run locally.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Exact commands may change as the project structure is implemented.

## Environment Variables

The application will require credentials for:

- Deepgram
- OpenAI
- Supabase

Use a local `.env` file and do not commit secrets to Git.

## Repository Documentation

- `AGENTS.md` — product context and instructions for AI coding agents
- `docs/architecture.md` — system architecture and data lifecycle
- `docs/tech-stack.md` — technology choices

## Status

Hackathon MVP under active development.