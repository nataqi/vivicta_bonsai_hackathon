# AI Compassion Coach

Hackathon prototype of an AI coaching assistant for customer-facing financial advisers.

The system helps advisers improve how they communicate during difficult or emotionally sensitive customer conversations through:

- lightweight live coaching nudges
- concise post-meeting feedback
- short reflection
- adviser learning that carries across meetings

The core principle is:

> Remember the learning, forget the customer conversation.

## Product Flow

```text
Home / Progress
      ↓
Start Meeting
      ↓
Live Meeting + Coaching Nudges
      ↓
Post-meeting Report
      ↓
Optional Reflection
      ↓
Updated Adviser Learning
```

The product focuses on coaching the adviser rather than analysing or profiling the customer.

## Coaching Dimensions

The MVP uses five coaching dimensions:

1. Pace & pauses
2. Turn-taking & interruptions
3. Open questions
4. Acknowledging emotional cues
5. Stay with the customer before solving

These are qualitative coaching dimensions, not numeric performance scores.

## Tech Stack

### Frontend

- React
- Next.js
- TypeScript
- Tailwind CSS

### Backend

- Python
- FastAPI
- WebSockets

### Services

- Deepgram — streaming speech-to-text and speaker diarization
- OpenAI — semantic analysis and coaching
- Supabase / PostgreSQL — persistent adviser learning

See [`docs/tech-stack.md`](docs/tech-stack.md) for details.

## Repository Structure

```text
/
├── AGENTS.md
├── README.md
├── docs/
│   ├── architecture.md
│   ├── tech-stack.md
│   └── ui-guidelines.md
├── frontend/
│   └── src/
│       ├── app/
│       │   └── mockup/
│       ├── components/
│       │   └── mockup/
│       └── lib/
│           └── mockup/
└── backend/
    └── app/
```

## Documentation

### [`AGENTS.md`](AGENTS.md)

Context and instructions for AI coding agents.

Contains:

- hackathon context
- product idea
- coaching principles
- privacy constraints
- MVP boundaries
- implementation guidelines

### [`docs/architecture.md`](docs/architecture.md)

Source of truth for system design.

Contains:

- end-to-end architecture
- live meeting flow
- behavioral and semantic analysis
- rolling context
- nudge logic
- post-meeting analysis
- reflection
- persistent adviser learning
- data lifecycle
- product screens
- MVP boundaries

### [`docs/tech-stack.md`](docs/tech-stack.md)

Source of truth for technology choices.

Contains:

- frontend stack
- FastAPI backend
- Deepgram
- OpenAI
- Supabase / PostgreSQL
- temporary session state
- localhost development
- optional prosody stretch goal

### [`docs/ui-guidelines.md`](docs/ui-guidelines.md)

Visual and interaction guidelines.

Contains:

- light and projector-friendly visual direction
- color usage
- layout principles
- coaching UI principles
- readability requirements
- guidance for avoiding surveillance-style or dashboard-heavy design

## Frontend Mockup

A frontend-only clickable mockup is available under:

```text
/mockup
```

The mockup demonstrates:

- Home / Progress
- coaching focus selection
- Start Meeting flow
- live meeting state
- sample coaching nudges
- post-meeting report
- reflection experience
- return to Home

The mockup uses frontend-only mock data and does not call the real backend, Deepgram, OpenAI, or Supabase.

Mockup-specific code is intentionally isolated under:

```text
frontend/src/app/mockup/
frontend/src/components/mockup/
frontend/src/lib/mockup/
```

This allows the mockup to be changed or removed without affecting the future production implementation.

## Local Development

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend will normally run on:

```text
http://localhost:3000
```

If that port is already occupied, Next.js may automatically use another port such as `3001`.

The mockup is then available at:

```text
http://localhost:<frontend-port>/mockup
```

### Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001
```

Backend health check:

```text
http://localhost:8001/health
```

Deepgram authentication check:

```text
http://localhost:8001/deepgram/health
```

## Environment Variables

Backend credentials are stored locally in:

```text
backend/.env
```

Current services may require:

```text
DEEPGRAM_API_KEY=
OPENAI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
```

Not all integrations are implemented yet.

Do not commit secrets or `.env` files to Git.

## MVP Direction

The intended real MVP will eventually support:

- real microphone input
- streaming transcription
- speaker separation
- behavioral signal detection
- semantic conversation analysis
- selective live coaching nudges
- post-meeting coaching report
- short reflection chat
- adviser learning across sessions
- lightweight Home / Progress experience

The current frontend mockup is for product discussion and UX validation before implementing the complete system.

## Development Principles

- Keep the project proportional to a hackathon.
- Prefer simple end-to-end vertical slices over large all-at-once implementation.
- Keep application logic primarily in the FastAPI backend.
- Keep the frontend focused on interaction and presentation.
- Use deterministic logic where possible.
- Use AI where conversational meaning and context are required.
- Keep customer conversation data temporary.
- Persist adviser learning, not customer conversation history.
- Keep documentation minimal and update existing documents instead of creating unnecessary new files.
- Make the local end-to-end experience reliable before spending time on deployment or stretch goals.

## Status

Hackathon MVP under active development.

Current focus:

- product concept and architecture defined
- documentation baseline established
- frontend mockup available for team discussion
- real implementation to be developed in vertical slices after team alignment