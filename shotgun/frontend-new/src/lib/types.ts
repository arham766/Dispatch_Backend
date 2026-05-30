export type Status =
  | "RECEIVED"
  | "DIAGNOSING"
  | "DIAGNOSED"
  | "CALLING"
  | "AWAITING_DECISION"
  | "FIXING"
  | "VERIFYING"
  | "PR_OPENING"
  | "RESOLVED"
  | "DISMISSED"
  | "ESCALATED";

export interface Media {
  screenshot: string;
  replay_url: string | null;
  caption?: string;
  accent?: string;
}

export interface Incident {
  id: string;
  service: string;
  symptom: string;
  status: Status;
  diagnosis: string | null;
  before: Media | null;
  after: Media | null;
  diff_url: string;
  pr_url: string | null;
  updated_at: string;
}

export interface LiveEvent {
  incident_id: string;
  status: Status;
  attempt?: number;
  run?: { phase: string; status: "passed" | "failed" | "running" };
}

export type TimelineStepKey =
  | "detected"
  | "diagnosing"
  | "awaiting"
  | "fixing"
  | "verifying"
  | "pr"
  | "ended";

export interface TimelineStep {
  key: TimelineStepKey;
  label: string;
  states: Status[];
}

export const TIMELINE_STEPS: TimelineStep[] = [
  { key: "detected", label: "Detected", states: ["RECEIVED"] },
  { key: "diagnosing", label: "Diagnosing", states: ["DIAGNOSING", "DIAGNOSED"] },
  { key: "awaiting", label: "Awaiting you", states: ["CALLING", "AWAITING_DECISION"] },
  { key: "fixing", label: "Fixing", states: ["FIXING"] },
  { key: "verifying", label: "Verifying", states: ["VERIFYING"] },
  { key: "pr", label: "PR open", states: ["PR_OPENING", "RESOLVED"] },
  { key: "ended", label: "Ended", states: ["DISMISSED", "ESCALATED"] },
];
