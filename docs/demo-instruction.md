Structure is based on ppt from 2Hero "How to win the hackathon"

## Demo Structure

### 1. The Case

- Why this matters. Vivid, concrete, and short.
- Open with the problem as someone living it would tell it: who it hurts, how often, and what it costs them. One concrete case beats any number of market-size slides.

### 2. The Promise
- What we are about to demonstrate:

### 3. The Proof

- Show that it really works, against the criteria. Run it on a real case, live, in front of them. Name the criterion first, then show the evidence that it is met. 

(That migh mean - Run the solution on a real case, live. Before each important part, name what we are proving / what success looks like. Then show the evidence that the criterion is met.)

### 4. The Insight

- What we learned:
- What the proof means:


## De-risking / Risks
### 1. Distraction during live coaching

**Risk:**  
Live AI coaching could distract or overwhelm the adviser during a sensitive conversation.

**What we did:**  
- Coach stays quiet most of the time.
- Nudges are only shown for high-confidence, actionable moments.
- Cooldowns prevent repeated or constant interruptions.

**Status:**  
Mitigated in the MVP.

---

### 2. Sensitive customer data / privacy

**Risk:**  
Customer conversations may contain sensitive personal and financial information.

**What we did:**  
- Raw audio, transcript, and customer-specific details are temporary.
- Customer conversation data is deleted after the session.
- Only generic adviser-learning information is retained.

**Status:**  
Mitigated by the product design.  
A production version would still require full security controls around temporary processing, access, transport, and external providers.

---

### 3. Speaker-role identification
**Risk:**  
Speaker diarization can sometimes assign the wrong role to the adviser and customer, which can affect coaching accuracy.

**What we did in the MVP:**  
- The adviser establishes the session first, so the prototype can map the first detected speaker to the adviser.

**Remaining limitation:**  
This is not fully solved.

**Production direction:**  
Explicitly identify or enrol the adviser rather than relying on the first-speaker heuristic.

**Status:**  
Known and partially mitigated for the prototype; still an open production risk.

## Transcript
ADVISER — fast, around 185–195 WPM

Hello. Before we start, I want to quickly outline what we can cover today. We can look at what has changed, go through your questions, review the information you have, and decide what would be most useful to focus on first.


CUSTOMER

Okay. I brought my latest statement and some notes with me, and I mainly want to understand what we should look at first.


ADVISER — normal pace

Great. We can go through those together one step at a time.


CUSTOMER

I’m scared I could lose my home. I haven’t been sleeping.


ADVISER — deliberately misses the emotion

What is the balance on your mortgage?


CUSTOMER

I have the numbers here, but honestly it’s the uncertainty that is worrying me most.


ADVISER — responds well after the nudge

That sounds really difficult. What part of the uncertainty feels hardest for you right now?