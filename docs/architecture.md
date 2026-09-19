# Architecture

## Overview

This system is a lightweight AI coaching assistant for customer-facing financial advisers.

It helps advisers improve how they communicate during difficult or emotionally sensitive customer conversations.

The product has three main states:

1. Home / Progress
2. Live Meeting
3. Post-meeting Report + Reflection

The core architectural principle is:

> Temporary customer context powers the session. Persistent adviser learning powers long-term coaching.

The system focuses on coaching the adviser rather than analysing or profiling the customer.

---

## High-Level Flow

### During the Meeting

```text
Microphone
   ↓
Deepgram
   ↓
Speaker-labelled finalized turns + timestamps
   ↓
 ┌──────────────────────┬────────────────────────┐
 │ Behavioral signals   │ Rolling context        │
 │                      │                        │
 │ - pace               │ - recent turns         │
 │ - pauses             │ - recent events        │
 │ - interruptions      │ - recent nudges        │
 │ - talk-time balance  │ - selected focus       │
 │ - long monologues    │                        │
 └──────────┬───────────┴───────────┬────────────┘
            ↓                       ↓
     Rule-based events       OpenAI semantic analysis
            ↓                       ↓
      confidence rules       semantic events + confidence
            └───────────┬───────────┘
                        ↓
                 Nudge decision layer
                        ↓
              Predefined live nudge
```

### After the Meeting

```text
Temporary transcript
+ behavioral metrics
+ detected semantic events
+ nudges shown
+ selected coaching focus
        ↓
OpenAI post-meeting analysis
        ↓
Structured analysis across
the five coaching dimensions
        ↓
Short coaching report
        ↓
Optional reflection conversation
        ↓
Generic adviser learning
        ↓
Persistent adviser profile/history
```

After the post-meeting coaching session finishes, temporary customer conversation data is deleted.

---

## Coaching Dimensions

All coaching and analysis should map to the same five dimensions:

1. Pace & pauses
2. Turn-taking & interruptions
3. Open questions
4. Acknowledging emotional cues
5. Stay with the customer before solving

These are coaching dimensions, not numeric performance scores.

The system may use lower-level measurements internally, but the adviser should receive human-readable coaching rather than scores such as "Empathy: 72%".

---

## Coaching Focus

The system monitors all five coaching dimensions during every meeting. Selected
focus areas are prioritized when deciding which eligible nudge to show;
selecting a focus does not disable monitoring of the other dimensions.

The adviser may choose one or more dimensions as their current coaching focus.

Selected focus areas:

- receive higher priority during live coaching
- may use a lower intervention threshold
- receive more attention in the post-meeting report

Non-selected areas are still monitored.

A very clear issue in a non-selected area may still trigger a live nudge.

The adviser selects or changes their active focus areas on the Home / Progress screen.

When the adviser selects Start Meeting, those active focus areas are used directly for the session.

Saved focus areas may carry over between sessions.

There is no separate pre-meeting focus-confirmation workflow.

---

# Live Meeting Architecture

## Streaming Transcription

The microphone audio is streamed to Deepgram.

The transcription layer should provide:

- near-real-time transcription
- speaker separation / diarization
- timestamps
- finalized speaker turns
- turn-ending information

The transcript is temporary session data.

For the hackathon MVP, speaker mapping may be simplified:

- first detected speaker → adviser
- second detected speaker → customer

A production implementation should use a more reliable identity mechanism such as separate audio channels or known adviser input.

Biometric voice identification is not required.

---

## Speaker Turns

The application should normalize transcription output into a simple internal representation.

Example:

```ts
type SpeakerTurn = {
  id: string
  speaker: "advisor" | "customer"
  text: string
  startTimeMs: number
  endTimeMs: number
  durationMs: number
  isFinal: boolean
}
```

The application should primarily run semantic analysis after a speaker turn has been finalized.

If someone speaks continuously for an unusually long time, a fallback analysis may run approximately every 8–10 seconds rather than waiting indefinitely for the turn to finish.

---

# Behavioral Signal Layer

Some coaching signals should be detected deterministically rather than asking the LLM to infer everything.

Examples include:

- speaking pace
- pause length
- interruptions / overlapping speech
- talk-time balance
- longest continuous monologue

These signals are derived from speaker turns, words, and timestamps.

They provide evidence for the five higher-level coaching dimensions.

For example:

```text
Speaking pace
+ pause duration
        ↓
Pace & pauses
```

```text
Overlap
+ interruption frequency
+ talk-time balance
        ↓
Turn-taking & interruptions
```

The exact thresholds can be tuned during testing rather than treated as scientifically fixed values.

Initial MVP values may include:

- sustained fast speech around 170–180+ words/minute
- sustained fast pace for approximately 15–20 seconds before triggering
- repeated interruptions treated as stronger evidence than one possible interruption
- very short pauses after significant customer statements treated as supporting evidence rather than an automatic failure

Behavioral-event confidence should be rule-based.

For example:

- one possible interruption → medium confidence
- repeated clear interruptions → high confidence
- brief fast sentence → low confidence
- sustained fast speech → high confidence

---

# Semantic Analysis

Semantic analysis is handled by an OpenAI model.

The LLM should focus on signals requiring meaning and conversational context rather than deterministic measurements.

Examples include:

- whether a question is open or closed
- whether the customer expressed an emotional cue
- whether the adviser acknowledged that cue
- whether the adviser moved too quickly into problem-solving
- whether a live intervention is warranted

Semantic analysis should return structured output rather than unrestricted prose.

Conceptually:

```ts
type DetectedEvent = {
  area:
    | "pace_and_pauses"
    | "turn_taking_and_interruptions"
    | "open_questions"
    | "acknowledging_emotional_cues"
    | "stay_before_solving"

  type: string

  confidence: "low" | "medium" | "high"

  timestampMs: number

  evidence?: string

  nudgeKey?: string
}
```

---

## Semantic Confidence

Semantic confidence is an LLM classification based on explicit rubrics.

Confidence should not be treated as a calibrated mathematical probability.

Each coaching dimension should have its own confidence rubric.

Example for acknowledging emotional cues:

### High confidence

The customer expresses an explicit emotional statement or significant life event, and the adviser's next response clearly ignores or bypasses it.

Example:

> "I'm really scared I won't be able to keep the house."

followed immediately by:

> "Let's look at the repayment options."

### Medium confidence

The customer likely expresses worry, uncertainty, or discomfort, but the cue is less explicit.

### Low confidence

The interpretation requires substantial inference or there is insufficient context.

Example for staying with the customer before solving:

### High confidence

A significant emotional or problem disclosure is immediately followed by advice, numbers, or solutions without acknowledgement or exploration.

### Medium confidence

The adviser moves toward a solution fairly quickly, but the situation is ambiguous.

### Low confidence

It is unclear whether additional acknowledgement or exploration was necessary.

For the live system, semantic events should generally need high confidence before triggering a nudge.

---

# Rolling Context

The live LLM should not continuously receive the entire meeting transcript.

Instead, maintain a compact rolling context.

It may contain:

- recent speaker turns
- short current meeting context
- important detected events
- recent live nudges
- active coaching focus areas

Conceptual example:

```text
Recent turns:
Customer: "I'm worried I might not be able to afford this."
Adviser: "Let's look at the repayment options."

Current context:
Customer is discussing financial uncertainty.

Important events:
- emotional cue detected

Recent nudges:
- "Slow down a little." shown 80 seconds ago

Selected focus:
- Acknowledging emotional cues
- Stay with the customer before solving
```

The rolling context is updated as the conversation progresses.

Semantic analysis is event-driven rather than sent at a fixed high frequency.

Normal flow:

```text
speaker turn ends
      ↓
update rolling context
      ↓
semantic analysis
      ↓
detected event
```

This reduces:

- latency
- cost
- unnecessary repeated data
- excessive LLM calls

---

# Live Nudge Decision Layer

The system should stay silent most of the time.

A live coaching nudge should only appear when an actionable coaching pattern is sufficiently clear.

The decision layer considers:

- detected coaching area
- event confidence
- adviser's selected focus areas
- recent nudges
- cooldown state
- whether the same nudge was recently shown
- whether interrupting now would likely be distracting

A provisional cooldown of approximately 60–90 seconds is appropriate for the MVP.

There should not necessarily be a hard maximum number of nudges per meeting.

Instead, the system should naturally remain quiet through confidence thresholds, cooldowns, and repetition prevention.

---

## Live Nudge Library

Live nudge text should primarily come from a predefined approved library.

The LLM detects the event and selects a `nudgeKey`.

The application maps that key to fixed text.

Examples:

```text
PACE_SLOW_DOWN
→ "Slow down a little."

ALLOW_PAUSE
→ "Give the customer a moment."

DO_NOT_INTERRUPT
→ "Let them finish."

ASK_OPEN_QUESTION
→ "Try an open question."

ACKNOWLEDGE_EMOTION
→ "Acknowledge what they just shared."

STAY_BEFORE_SOLVING
→ "Stay with the moment before solving."
```

Live nudges should be:

- short
- actionable
- non-judgmental
- approximately one line
- easy to process while speaking
- briefly displayed

Avoid live generated paragraphs.

Avoid numeric messages such as:

> Customer distress: 82%

or:

> Empathy score: 64%

---

# Post-Meeting Analysis

When the meeting ends, one richer analysis is performed using:

- the temporary full transcript
- behavioral metrics
- detected events
- nudges shown
- selected coaching focus areas

The analysis should create structured observations across the five coaching dimensions.

Example conceptual result:

```json
{
  "paceAndPauses": {
    "strength": "Generally calm pace.",
    "improvement": "One difficult moment was answered very quickly."
  },
  "turnTaking": {
    "strength": "The customer had room to explain most concerns.",
    "improvement": "There were two interruptions."
  },
  "openQuestions": {
    "strength": "Several open questions encouraged the customer to explain."
  },
  "acknowledgingEmotionalCues": {
    "improvement": "One important emotional cue was not acknowledged."
  },
  "stayBeforeSolving": {
    "improvement": "You moved into solution mode quickly after one concern."
  }
}
```

The adviser should receive a concise human-readable report rather than raw metrics.

The report should focus on:

- what went well
- what could improve
- useful behavioral observations
- selected coaching focus
- a possible reflection prompt

The experience should take roughly 90 seconds to 2 minutes rather than becoming a large performance review.

---

# Reflection Coach

After viewing the report, the adviser may optionally start a short AI reflection conversation.

The reflection coach may temporarily access:

- the full meeting transcript
- structured meeting analysis
- behavioral events
- adviser coaching history
- selected coaching focus
- the adviser's responses during reflection

The adviser does not need to see the raw transcript.

The AI may use it internally to refer to relevant moments.

A typical reflection may follow:

1. Ask how the adviser thinks the meeting went.
2. Let the adviser answer freely using the text input.
3. Respond using observations from the meeting.
4. Help identify one useful takeaway or improvement intention.

The reflection should normally remain around 2–3 exchanges / approximately 60–90 seconds.

It should not become an unrestricted generic chatbot conversation.

Role-play and replay of meeting situations are possible future extensions but are not required for the MVP.

---

# Persistent Adviser Learning

The product should improve across meetings.

At the end of the post-meeting experience, the system extracts generic adviser learning.

Examples:

- current coaching focus
- recurring strengths
- recurring improvement patterns
- reflection takeaways
- progress over time
- improvement intentions

Example persistent learning:

> Tends to move into solution mode quickly after emotional cues.

Another example:

> Has increasingly used open questions when customers express uncertainty.

This learning may be used in future sessions.

The goal is for the coach to remember the adviser, not the customer's conversation.

---

# Data Lifecycle

The core privacy principle is:

> Remember the learning, forget the customer conversation.

## Temporary Session Data

The following may exist temporarily:

- raw audio
- full transcript
- rolling context
- customer identifiers
- customer-specific information
- exact customer statements
- customer-specific meeting events
- detailed meeting context
- temporary semantic events
- temporary behavioral measurements

Temporary data may be used during:

1. the live meeting
2. post-meeting report generation
3. the optional immediate reflection session

If the adviser chooses reflection:

```text
Meeting
  ↓
Temporary transcript
  ↓
Post-meeting report
  ↓
Reflection session
  ↓
Extract adviser learning
  ↓
Delete transcript/customer context
```

If the adviser skips reflection:

```text
Meeting
  ↓
Temporary transcript
  ↓
Post-meeting report
  ↓
Extract adviser learning
  ↓
Delete transcript/customer context
```

The transcript should not become long-term history.

---

## Persistent Data

Persistent storage should contain only adviser-specific coaching information such as:

- adviser identifier
- selected focus areas
- generic strengths
- generic improvement patterns
- reflection takeaways
- coaching history
- qualitative progress over time

Do not persist:

- raw audio
- full transcripts
- customer names
- customer identifiers
- customer conversation summaries
- exact customer quotes
- detailed customer-specific moments

Persistent adviser coaching information is still personal employee data and would require appropriate access controls, retention rules, and security in a production deployment.

---

# Storage Architecture

Use two conceptual storage layers.

## Temporary Session State

Used for:

- live audio processing
- transcript
- rolling context
- meeting metrics
- detected events
- temporary post-meeting analysis

This should ideally remain ephemeral and outside normal persistent application storage.

## Persistent Adviser Store

Used for:

- coaching focus
- generic adviser patterns
- reflection takeaways
- progress history

For the hackathon MVP, persistent adviser learning will be stored in Supabase / Postgres.

Supabase should not receive meeting transcripts or raw customer audio.

---

# Product Screens

The MVP should remain lightweight.

There are three main product areas.

---

## Home / Progress

The Home screen represents the adviser's longer-term coaching journey.

It should show lightweight information such as:

- current coaching focus
- recent progress
- recurring strengths
- areas being worked on
- qualitative improvement over time
- Start Meeting

Example:

```text
Current focus
• Acknowledging emotional cues
• Stay with the customer before solving

Recent progress
You're giving customers more space before offering solutions.

Keep working on
You sometimes move into solution mode before exploring the concern.

[ Start meeting ]
```

This should not become a large analytics dashboard.

Avoid complex charts and numeric performance scores unless there is a clear future reason to introduce them.

---

## Meeting

The adviser starts the meeting directly from Home / Progress using the focus areas already selected there.

During the meeting:

- show the active focus areas in a lightweight, read-only way
- listen to live microphone audio
- transcribe conversation
- analyze all five coaching dimensions
- show minimal live nudges only when useful
- allow adviser to end the meeting

The transcript does not need to be prominently displayed to the adviser.

The primary live experience is coaching, not transcription.

---

## Post-Meeting

After the meeting:

1. Show the short coaching report.
2. Offer optional reflection.
3. Allow adviser to finish.
4. Update persistent adviser learning.
5. Return to Home / Progress.

---

# MVP Scope

The hackathon prototype should demonstrate a real end-to-end flow.

## Real

The MVP should use:

- real microphone input
- real Deepgram streaming transcription
- real speaker separation
- real behavioral measurements
- real OpenAI semantic analysis
- real live nudge decisions
- real predefined live nudges
- real post-meeting analysis
- real reflection conversation
- real persistent adviser learning
- real reuse of adviser learning in later meetings

The demo should allow two people to actually role-play adviser and customer.

---

## Simplified or Mocked

The hackathon does not require:

- real banking CRM integration
- real customer banking records
- production-grade authentication
- production bank infrastructure
- production anonymization infrastructure
- on-premise inference
- complete enterprise security architecture
- real Handelsbanken internal data
- biometric speaker identification

All demonstration conversations should use fictional customer information.

---

# Prosody / Voice-Emotion Analysis

True acoustic/prosody analysis is not part of the MVP.

Possible future signals include:

- vocal tension
- hesitation
- warmth
- pitch variation
- emotional expression
- loudness patterns

A provider such as Hume may be explored as a stretch goal if the core system is completed early.

Adding prosody introduces an additional privacy flow because raw customer audio would need to be sent to another external provider.

Therefore it should only be added if it materially improves the prototype.

---

# Technology Responsibilities

Technology selection is documented separately in `docs/tech-stack.md`.

At the architectural level:

```text
Deepgram
→ streaming speech-to-text
→ speaker diarization
→ timestamps / turn information

Application code
→ behavioral metrics
→ rolling context
→ nudge decision logic
→ predefined nudge library

OpenAI
→ semantic event analysis
→ post-meeting analysis
→ reflection coaching
→ adviser learning extraction

Supabase / Postgres
→ persistent adviser learning
→ coaching history
→ selected focus areas
```

---

# Architecture Principles

When implementing this system:

1. Prefer simple hackathon-scale architecture over production complexity.
2. Keep live coaching minimally intrusive.
3. Use deterministic logic where deterministic logic is sufficient.
4. Use the LLM where meaning and context are required.
5. Keep LLM outputs structured wherever possible.
6. Keep customer conversation data temporary.
7. Persist adviser learning rather than customer conversation history.
8. Keep coaching qualitative rather than score-based.
9. Keep the adviser in control of coaching focus.
10. Optimize for a working end-to-end prototype rather than broad feature coverage.
