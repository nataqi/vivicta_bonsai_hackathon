export type CoachingFocus =
  | "Pace & pauses"
  | "Turn-taking & interruptions"
  | "Open questions"
  | "Acknowledging emotional cues"
  | "Stay with the customer before solving";

export const coachingDimensions: { label: CoachingFocus; short: string }[] = [
  { label: "Pace & pauses", short: "Pace" },
  { label: "Turn-taking & interruptions", short: "Turn-taking" },
  { label: "Open questions", short: "Open questions" },
  { label: "Acknowledging emotional cues", short: "Emotional cues" },
  { label: "Stay with the customer before solving", short: "Stay with it" },
];

export const defaultFocus: CoachingFocus[] = [
  "Acknowledging emotional cues",
  "Stay with the customer before solving",
];

export type CoachingInsightKind =
  | "improvement"
  | "stable-positive-pattern"
  | "recurring-challenge"
  | "not-enough-history";

export type CoachingInsight = {
  kind: CoachingInsightKind;
  observation: string;
  keepExploring: string;
};

export const mockCoachingInsights: Record<CoachingInsightKind, CoachingInsight> = {
  improvement: {
    kind: "improvement",
    observation: "You paused and acknowledged a concern before moving forward.",
    keepExploring: "Keep making room for the concern before moving into a solution.",
  },
  "stable-positive-pattern": {
    kind: "stable-positive-pattern",
    observation: "You’ve been giving customers more space before offering solutions.",
    keepExploring: "Stay with uncertainty a little longer before moving into a solution.",
  },
  "recurring-challenge": {
    kind: "recurring-challenge",
    observation: "You often move toward solutions before the customer has finished sharing their concern.",
    keepExploring: "Try one acknowledging response before offering the next step.",
  },
  "not-enough-history": {
    kind: "not-enough-history",
    observation: "A few more conversations will help your coach notice useful patterns.",
    keepExploring: "Choose a focus for your next meeting to begin building a clearer picture.",
  },
};

export const liveNudges = [
  "Stay with the moment before solving.",
];
