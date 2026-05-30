import { Status, TIMELINE_STEPS, TimelineStep } from "@/lib/types";

type StepState = "pending" | "active" | "done" | "failed";

const ORDER: Status[] = [
  "RECEIVED",
  "DIAGNOSING",
  "DIAGNOSED",
  "CALLING",
  "AWAITING_DECISION",
  "FIXING",
  "VERIFYING",
  "PR_OPENING",
  "RESOLVED",
];

function stepStateFor(
  step: TimelineStep,
  status: Status,
  failedAttempt: boolean,
): StepState {
  if (status === "DISMISSED" || status === "ESCALATED") {
    return step.key === "ended" ? "failed" : "pending";
  }
  const currentIdx = ORDER.indexOf(status);
  const stepMaxIdx = Math.max(...step.states.map((s) => ORDER.indexOf(s)));
  const stepMinIdx = Math.min(...step.states.map((s) => ORDER.indexOf(s)));
  if (currentIdx > stepMaxIdx) return "done";
  if (currentIdx >= stepMinIdx && currentIdx <= stepMaxIdx) {
    if (step.key === "verifying" && failedAttempt) return "failed";
    return "active";
  }
  return "pending";
}

const COLORS: Record<StepState, { dot: string; ring: string; text: string }> = {
  pending: { dot: "#3a3d6a", ring: "#1f2244", text: "#8c89a8" },
  active: { dot: "#e85d1a", ring: "#3a2614", text: "#ffe4a8" },
  done: { dot: "#4ade80", ring: "#173322", text: "#7ee8a4" },
  failed: { dot: "#f87171", ring: "#3a1818", text: "#ff9b9b" },
};

export function StatusTimeline({
  status,
  attempt,
  failedAttempt = false,
}: {
  status: Status;
  attempt?: number;
  failedAttempt?: boolean;
}) {
  const steps = TIMELINE_STEPS.filter((s) =>
    status === "DISMISSED" || status === "ESCALATED"
      ? s.key !== "pr"
      : s.key !== "ended",
  );

  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono">
        Status
      </h2>
      <ol className="mt-4 flex flex-wrap items-center gap-2">
        {steps.map((step, i) => {
          const state = stepStateFor(step, status, failedAttempt);
          const c = COLORS[state];
          const isVerifying = step.key === "verifying" && state === "active";
          return (
            <li key={step.key} className="flex items-center gap-2">
              <span
                className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-mono ${
                  isVerifying ? "animate-pulse" : ""
                }`}
                style={{ backgroundColor: c.ring, color: c.text }}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: c.dot }}
                />
                {step.label}
                {step.key === "verifying" && attempt && attempt > 1 ? (
                  <span className="opacity-70">· attempt {attempt}</span>
                ) : null}
              </span>
              {i < steps.length - 1 ? (
                <span className="text-[var(--color-text-muted)]">→</span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
