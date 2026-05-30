import { Status } from "@/lib/types";

const STYLES: Record<Status, { bg: string; fg: string; label: string }> = {
  RECEIVED: { bg: "#2a2d52", fg: "#d8cfb9", label: "Received" },
  DIAGNOSING: { bg: "#1f2a5c", fg: "#a8b8ff", label: "Diagnosing" },
  DIAGNOSED: { bg: "#1f2a5c", fg: "#a8b8ff", label: "Diagnosed" },
  CALLING: { bg: "#3a2a14", fg: "#f5b06a", label: "Calling" },
  AWAITING_DECISION: { bg: "#3a2a14", fg: "#f5b06a", label: "Awaiting you" },
  FIXING: { bg: "#1f2a5c", fg: "#a8b8ff", label: "Fixing" },
  VERIFYING: { bg: "#1f2a5c", fg: "#a8b8ff", label: "Verifying" },
  PR_OPENING: { bg: "#173322", fg: "#7ee8a4", label: "Opening PR" },
  RESOLVED: { bg: "#173322", fg: "#7ee8a4", label: "Resolved" },
  DISMISSED: { bg: "#2a2d52", fg: "#8c89a8", label: "Dismissed" },
  ESCALATED: { bg: "#3a1818", fg: "#ff9b9b", label: "Escalated" },
};

export function StatusBadge({ status }: { status: Status }) {
  const s = STYLES[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium font-mono"
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: s.fg }}
      />
      {s.label}
    </span>
  );
}
