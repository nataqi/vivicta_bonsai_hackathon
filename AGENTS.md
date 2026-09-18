# AGENTS.md

## Project

This repository contains a hackathon prototype of an AI coaching assistant for
customer-facing financial advisers.

The goal is to help advisers improve how they communicate during difficult or
emotionally sensitive customer conversations.

This is a coaching tool, not a knowledge assistant. It focuses on how the
adviser interacts with the customer rather than providing financial answers.

## Product loop

1. Adviser starts a customer meeting and confirms their coaching focus.
2. The system observes the conversation.
3. It stays mostly silent and shows short live nudges only when useful.
4. After the meeting, the adviser receives a short coaching report.
5. The adviser may complete a brief reflection conversation with the AI coach.
6. Generic adviser learning is retained to support improvement across meetings.

## Coaching dimensions

The MVP uses five coaching dimensions:

1. Pace & pauses
2. Turn-taking & interruptions
3. Open questions
4. Acknowledging emotional cues
5. Stay with the customer before solving

All analysis and coaching should map back to these dimensions.

## Product principles

- Coach the adviser, not the customer.
- Prefer self-awareness over judgment.
- Keep live intervention minimal.
- Do not use numeric empathy scores.
- Live nudges should be short, predefined, and actionable.
- The adviser remains in control of their coaching focus.
- Post-meeting reflection should be short and useful rather than a long chat.
- Detailed coaching data belongs to the adviser, not managers or HR.

## Privacy

Follow the principle:

> Remember the learning, forget the customer conversation.

Audio, transcripts, rolling context, customer identifiers, customer-specific
details, and exact customer moments are temporary session data.

They may be used during the meeting and immediate post-meeting reflection but
must not become long-term coaching memory.

Persistent data should contain only generic adviser learning such as:

- focus areas
- strengths
- recurring patterns
- improvement areas
- reflection takeaways
- progress over time

## MVP

The prototype should support:

- real microphone input
- streaming transcription with speaker separation
- behavioral signal detection
- semantic conversation analysis
- selective live coaching nudges
- post-meeting coaching report
- short optional reflection chat
- persistent adviser learning across sessions
- lightweight home/progress view

Do not add unnecessary production infrastructure or enterprise features.

Prosody / voice-emotion analysis is a stretch goal only.

## Working guidelines

- Keep implementation proportional to a hackathon prototype.
- Prefer simple, explicit solutions over abstraction-heavy architecture.
- Do not introduce dependencies without a clear need.
- Keep documentation minimal and update existing documents instead of creating
  new documentation files unnecessarily.
- Treat `docs/architecture.md` as the source of truth for system design.
- Treat `docs/tech-stack.md` as the source of truth for technology choices.
- Keep customer conversation data temporary by design.