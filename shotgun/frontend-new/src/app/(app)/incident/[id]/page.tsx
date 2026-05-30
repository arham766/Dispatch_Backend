"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { StatusBadge } from "@/components/StatusBadge";
import { DiagnosisCard } from "@/components/DiagnosisCard";
import { StatusTimeline } from "@/components/StatusTimeline";
import { BeforeAfter } from "@/components/BeforeAfter";
import { DiffViewer } from "@/components/DiffViewer";
import { PrButton } from "@/components/PrButton";
import { useAuth } from "@/lib/useAuth";
import {
  fetchDiff,
  makeApi,
  mapStatus,
  snapshotToIncident,
} from "@/lib/api";
import type { Incident } from "@/lib/types";
import { useIncidentStream } from "@/lib/useIncidentStream";
import { MOCK_INCIDENT, MOCK_DIFF } from "@/lib/mock";

export default function IncidentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { user, loading, authedFetch } = useAuth();
  const router = useRouter();
  const api = useMemo(() => makeApi(authedFetch), [authedFetch]);

  const [incident, setIncident] = useState<Incident>({
    ...MOCK_INCIDENT,
    id,
  });
  const [diff, setDiff] = useState<string>(MOCK_DIFF);

  // Live stream — surfaces every state change so the badge / timeline
  // ticks in real time without re-fetching.
  const { events } = useIncidentStream(id);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // Initial snapshot fetch
  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const snap = await api.getIncident(id);
        const me = await api.me().catch(() => null);
        const repo =
          me?.monitored_repos.find((r) =>
            r.full_name.endsWith(`/${snap.incident.service}`),
          ) ||
          me?.monitored_repos[0] ||
          null;
        setIncident(snapshotToIncident(snap, repo));
        const realDiff = await fetchDiff({
          repoFullName: repo?.full_name || null,
          headBranch: snap.branch,
          hint: snap.incident.recent_diff_hint,
        });
        setDiff(realDiff);
      } catch {
        /* keep mock fallback */
      }
    })();
  }, [user, id, api]);

  // Whenever a fresh state_change / pr_opened event arrives, patch the
  // displayed incident so the UI ticks live without a full refetch.
  useEffect(() => {
    if (events.length === 0) return;
    setIncident((prev) => {
      let next = prev;
      for (const ev of events) {
        if (ev.event === "state_change" && typeof ev.state === "string") {
          next = { ...next, status: mapStatus(ev.state) };
        } else if (ev.event === "pr_opened" && typeof ev.pr_url === "string") {
          next = { ...next, pr_url: ev.pr_url as string, status: "RESOLVED" };
        }
      }
      return next;
    });
  }, [events]);

  if (loading || !user) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <StatusBadge status={incident.status} />
            <span className="text-sm font-mono text-[var(--color-ink-muted)]">
              {incident.id}
            </span>
            <span className="text-sm text-[var(--color-ink-muted)]">
              · {incident.service}
            </span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            {incident.symptom}
          </h1>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            Updated {new Date(incident.updated_at).toLocaleString()}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* HUMAN_GATE — Approve unblocks SHIP, which opens the real PR. */}
          {incident.status === "AWAITING_DECISION" ? (
            <>
              <button
                type="button"
                onClick={() => api.approveIncident(incident.id)}
                className="text-sm text-black bg-emerald-300 hover:bg-emerald-200 rounded-md px-4 py-2"
              >
                ✅ Open the PR
              </button>
              <button
                type="button"
                onClick={() => api.rejectIncident(incident.id)}
                className="text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-3.5 py-2"
              >
                Stand down
              </button>
            </>
          ) : null}
          <PrButton prUrl={incident.pr_url} />
        </div>
      </div>

      <StatusTimeline status={incident.status} />

      <DiagnosisCard
        symptom={incident.symptom}
        diagnosis={incident.diagnosis}
      />

      <BeforeAfter
        before={incident.before}
        after={incident.after}
        status={incident.status}
      />

      <DiffViewer patch={diff} />
    </div>
  );
}
