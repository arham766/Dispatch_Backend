import { HugeiconsIcon } from "@hugeicons/react";
import {
  BellFreeIcons,
  InspectCodeFreeIcons,
  CallFreeIcons,
  WrenchFreeIcons,
  CheckmarkCircleFreeIcons,
  GitPullRequestFreeIcons,
} from "@hugeicons/core-free-icons";
import { Status, TIMELINE_STEPS, TimelineStepKey } from "@/lib/types";

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

type StepState = "pending" | "active" | "done" | "failed";

const ICONS: Partial<Record<TimelineStepKey, typeof BellFreeIcons>> = {
  detected: BellFreeIcons,
  diagnosing: InspectCodeFreeIcons,
  awaiting: CallFreeIcons,
  fixing: WrenchFreeIcons,
  verifying: CheckmarkCircleFreeIcons,
  pr: GitPullRequestFreeIcons,
};

function stepStateFor(
  stepStates: Status[],
  current: Status,
  failedAttempt: boolean,
  key: string,
): StepState {
  if (current === "DISMISSED" || current === "ESCALATED") {
    return key === "ended" ? "failed" : "pending";
  }
  const i = ORDER.indexOf(current);
  const max = Math.max(...stepStates.map((s) => ORDER.indexOf(s)));
  const min = Math.min(...stepStates.map((s) => ORDER.indexOf(s)));
  if (i > max) return "done";
  if (i >= min && i <= max)
    return key === "verifying" && failedAttempt ? "failed" : "active";
  return "pending";
}

const COLOR: Record<StepState, { icon: string; text: string }> = {
  pending: { icon: "rgba(255,255,255,0.3)", text: "rgba(255,255,255,0.35)" },
  active: { icon: "#e85d1a", text: "#ffffff" },
  done: { icon: "#4ade80", text: "#ffffff" },
  failed: { icon: "#f87171", text: "#ffffff" },
};

export function MiniTimeline({
  status,
  failedAttempt = false,
  trailing,
}: {
  status: Status;
  failedAttempt?: boolean;
  trailing?: React.ReactNode;
}) {
  const steps = TIMELINE_STEPS.filter((s) =>
    status === "DISMISSED" || status === "ESCALATED"
      ? s.key !== "pr"
      : s.key !== "ended",
  );

  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
      {steps.map((step, i) => {
        const state = stepStateFor(
          step.states,
          status,
          failedAttempt,
          step.key,
        );
        const c = COLOR[state];
        const Icon = ICONS[step.key];
        const isActive = state === "active" || state === "failed";
        return (
          <li key={step.key} className="flex items-center gap-3">
            <span className="flex items-center gap-1.5">
              {Icon ? (
                <HugeiconsIcon
                  icon={Icon}
                  size={14}
                  color={c.icon}
                  strokeWidth={1.75}
                  className={isActive ? "animate-pulse" : ""}
                />
              ) : null}
              <span style={{ color: c.text }}>{step.label}</span>
            </span>
            {step.key === "pr" && trailing ? (
              <span className="ml-1 inline-flex items-center">{trailing}</span>
            ) : null}
            {i < steps.length - 1 ? (
              <span className="text-white/20">·</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
