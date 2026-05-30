"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HugeiconsIcon } from "@hugeicons/react";
import { UserCircleFreeIcons } from "@hugeicons/core-free-icons";
import { DiffViewer } from "@/components/DiffViewer";
import { MiniTimeline } from "@/components/MiniTimeline";
import { VideoPanel } from "@/components/VideoPanel";
import { LiveLogs } from "@/components/LiveLogs";
import { Notifications } from "@/components/Notifications";
import { useAuth } from "@/lib/useAuth";
import {
  fetchDiff,
  makeApi,
  mapStatus,
  snapshotToIncident,
  type IncidentListItem,
  type Me,
  type RunStateSnapshot,
} from "@/lib/api";
import type { Incident } from "@/lib/types";
import { useIncidentStream } from "@/lib/useIncidentStream";

export default function IncidentsPage() {
  const { user, loading, authedFetch } = useAuth();
  const router = useRouter();
  const api = useMemo(() => makeApi(authedFetch), [authedFetch]);

  const [me, setMe] = useState<Me | null>(null);
  const [inc, setInc] = useState<Incident | null>(null);
  const [diff, setDiff] = useState<string>("");
  const [name, setName] = useState<string>("");
  const [triggering, setTriggering] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Live event stream is the source of truth for both the LiveLogs and
  // Notifications components. Subscribing here means the dashboard tells
  // a single story — every panel reflects the same moment.
  const { events } = useIncidentStream(inc?.id ?? null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // Load me + latest incident
  useEffect(() => {
    if (!user) return;
    setName(
      user.displayName?.split(" ")[0] ||
        user.email?.split("@")[0] ||
        "there",
    );

    (async () => {
      try {
        const data = await api.me();
        setMe(data);

        const list: IncidentListItem[] = await api.listIncidents();
        if (list.length === 0) {
          setInc(null);
          setDiff("");
          return;
        }
        const latest = list[0];
        const snap: RunStateSnapshot = await api.getIncident(latest.run_id);
        const repo =
          data.monitored_repos.find((r) =>
            r.full_name.endsWith(`/${snap.incident.service}`),
          ) ||
          data.monitored_repos[0] ||
          null;

        setInc(snapshotToIncident(snap, repo));
        const realDiff = await fetchDiff({
          repoFullName: repo?.full_name || null,
          headBranch: snap.branch,
          hint: snap.incident.recent_diff_hint,
        });
        setDiff(realDiff);
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : "Failed to load incidents");
      }
    })();
  }, [user, api]);

  // Patch the current incident on live state changes (status + pr_url).
  // Also: when a `patch` event arrives (Kiro just committed), pull the
  // REAL diff from github.com/.../compare/main...branch.diff so the
  // viewer flips from the synthetic placeholder to the actual change.
  useEffect(() => {
    if (events.length === 0 || !inc) return;
    let needsDiffRefresh = false;
    let newBranch: string | null = null;

    setInc((prev) => {
      if (!prev) return prev;
      let next = prev;
      for (const ev of events) {
        if (ev.event === "state_change" && typeof ev.state === "string") {
          next = { ...next, status: mapStatus(ev.state) };
        } else if (ev.event === "pr_opened" && typeof ev.pr_url === "string") {
          next = { ...next, pr_url: ev.pr_url as string };
        } else if (ev.event === "patch" && typeof ev.branch === "string") {
          needsDiffRefresh = true;
          newBranch = ev.branch as string;
        }
      }
      return next;
    });

    if (needsDiffRefresh && newBranch && me) {
      const repo =
        me.monitored_repos.find((r) =>
          r.full_name.endsWith(`/${inc.service}`),
        ) ||
        me.monitored_repos[0] ||
        null;
      if (repo) {
        fetchDiff({
          repoFullName: repo.full_name,
          headBranch: newBranch,
          hint: "payment.js",
        }).then(setDiff);
      }
    }
  }, [events, inc?.id, me]);

  async function handleTrigger() {
    if (!me) return;
    setTriggering(true);
    setErr(null);
    try {
      const repo = me.monitored_repos[0];
      if (!repo) {
        router.push("/projects");
        return;
      }
      const newRunId = repo.is_local_loop
        ? (await api.triggerLocal({
            service: "checkout",
            symptom: `Checkout 500 on pay — ${repo.full_name}`,
            suspect_url: repo.deploy_url,
            repro_flow: "flows/checkout_test.md",
            recent_diff_hint: "payment.js",
          })).run_id
        : (await api.triggerRepo(repo.id)).incident_id;

      // Stay on this page — swap the displayed incident in place so the
      // dashboard immediately re-binds: WebSocket subscribes to the new
      // run, LiveLogs starts ticking, Notifications populate, no
      // navigation. URL stays /incidents.
      const snap = await api.getIncident(newRunId);
      setInc(snapshotToIncident(snap, repo));
      const realDiff = await fetchDiff({
        repoFullName: repo.full_name,
        headBranch: snap.branch,
        hint: snap.incident.recent_diff_hint,
      });
      setDiff(realDiff);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Trigger failed");
    } finally {
      setTriggering(false);
    }
  }

  if (loading || !user) return null;

  // Empty state — no incidents yet
  if (!inc && me) {
    const hasInstall = me.installations.length > 0;
    const hasRepo = me.monitored_repos.length > 0;
    return (
      <div className="min-h-screen w-full bg-black">
        <div className="relative z-10 min-h-screen w-full px-4 md:px-6 pt-10 md:pt-14 pb-16">
          <div className="rounded bg-black p-4 md:p-5">
            <Header name={name || "there"} />
            <section className="mt-12 max-w-2xl">
              <h2 className="text-sm text-white/50">No incidents yet</h2>
              <p className="mt-3 text-white text-lg md:text-xl leading-snug">
                {hasRepo
                  ? "Trigger your first run to see the loop in action."
                  : hasInstall
                  ? "Pick a repository on the next screen and tell Dispatch where it lives."
                  : "Connect your GitHub to import a repository you want monitored."}
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                {/* Always offer the "connect GitHub" CTA so non-admin users
                    who haven't installed the App yet have an obvious next
                    step right on the dashboard. */}
                {!hasInstall ? (
                  <a
                    href={api.githubInstallUrl()}
                    className="inline-flex items-center gap-2 text-sm text-black bg-white hover:bg-white/90 rounded-md px-4 py-2 transition-colors"
                  >
                    Connect GitHub →
                  </a>
                ) : null}

                {hasInstall && !hasRepo ? (
                  <Link
                    href="/projects"
                    className="inline-flex items-center gap-2 text-sm text-black bg-white hover:bg-white/90 rounded-md px-4 py-2 transition-colors"
                  >
                    Add a project →
                  </Link>
                ) : null}

                {hasRepo ? (
                  <button
                    type="button"
                    onClick={handleTrigger}
                    disabled={triggering}
                    className="inline-flex items-center gap-2 text-sm text-black bg-white hover:bg-white/90 disabled:opacity-60 rounded-md px-4 py-2 transition-colors"
                  >
                    {triggering ? "Firing…" : "Trigger first run →"}
                  </button>
                ) : null}

                {/* Secondary link: always available once signed in, lets the
                    user jump straight to "add another repo". */}
                <Link
                  href="/projects"
                  className="inline-flex items-center gap-2 text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-4 py-2 transition-colors"
                >
                  {hasRepo ? "Manage repos" : "Browse repos"}
                </Link>
              </div>

              {err ? (
                <p className="mt-3 text-xs text-red-300/80">{err}</p>
              ) : null}
            </section>
          </div>
        </div>
      </div>
    );
  }

  if (!inc) return null;

  return (
    <div className="min-h-screen w-full bg-black">
      <div className="relative z-10 min-h-screen w-full px-4 md:px-6 pt-10 md:pt-14 pb-16">
        <div className="rounded bg-black p-4 md:p-5">
          <Header name={name || "there"} />

          <section className="mt-8 max-w-3xl">
            <h2 className="text-sm text-white/50">Problem</h2>
            <p className="mt-3 text-white text-lg md:text-xl leading-snug">
              {inc.symptom}
            </p>
            <p className="mt-2 text-white/60 text-sm md:text-base leading-relaxed">
              <span className="font-mono text-white/40">{inc.service}</span> ·{" "}
              {inc.diagnosis?.split(".")[0] || "Waiting for Kane verdict…"}.
            </p>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              {/* HUMAN_GATE — show a prominent Approve button so SHIP fires
                  and the PR opens. Without this the loop blocks forever. */}
              {inc.status === "AWAITING_DECISION" ? (
                <>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.approveIncident(inc.id);
                      } catch (e: unknown) {
                        setErr(e instanceof Error ? e.message : "Approve failed");
                      }
                    }}
                    className="text-sm text-black bg-emerald-300 hover:bg-emerald-200 rounded-md px-4 py-2"
                  >
                    ✅ Open the PR
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.rejectIncident(inc.id);
                      } catch (e: unknown) {
                        setErr(e instanceof Error ? e.message : "Reject failed");
                      }
                    }}
                    className="text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-3.5 py-2"
                  >
                    Stand down
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={handleTrigger}
                  disabled={triggering}
                  className="text-sm text-black bg-white hover:bg-white/90 disabled:opacity-60 rounded-md px-3.5 py-2"
                >
                  {triggering ? "Firing…" : "Trigger another run"}
                </button>
              )}
              <Link
                href="/projects"
                className="text-sm text-white/80 bg-white/[0.04] hover:bg-white/10 rounded-md px-3.5 py-2"
              >
                Add another repo
              </Link>
              {err ? (
                <span className="text-xs text-red-300/80 ml-2">{err}</span>
              ) : null}
            </div>
          </section>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="md:col-span-2 min-w-0 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <MiniTimeline status={inc.status} />
                {inc.pr_url ? (
                  <a
                    href={inc.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-3.5 py-2 transition-colors"
                  >
                    View pull request ↗
                  </a>
                ) : null}
              </div>
              <DiffViewer patch={diff || ""} />

              {/* Before / after — only meaningful once we have media or a verdict */}
              <VideoPanel before={inc.before} after={inc.after} />
            </div>

            <aside className="md:col-span-1 space-y-6">
              <LiveLogs runId={inc.id} />
              <Notifications events={events} />
            </aside>
          </div>
        </div>
      </div>
    </div>
  );
}

function Header({ name }: { name: string }) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <h1
          className="text-white tracking-tight leading-[0.95]"
          style={{
            fontSize: "clamp(2.25rem, 5.5vw, 4.5rem)",
            fontWeight: 300,
            letterSpacing: "-0.03em",
          }}
        >
          Hey, {name}.
        </h1>
        <p
          className="mt-4 text-white/70 max-w-2xl leading-snug"
          style={{
            fontSize: "clamp(1rem, 1.4vw, 1.25rem)",
            fontWeight: 400,
          }}
        >
          Here&apos;s an overview of your recent incident.
        </p>
      </div>
      <Link
        href="/projects"
        className="shrink-0 inline-flex items-center gap-2 text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-3 py-2 transition-colors"
      >
        <HugeiconsIcon
          icon={UserCircleFreeIcons}
          size={16}
          color="currentColor"
          strokeWidth={1.75}
        />
        My account
      </Link>
    </div>
  );
}
